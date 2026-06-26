"""Cloud media backup helpers for Suntek LTE Camera."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import SuntekApiError, SuntekCloudClient
from .const import CONF_DEVICE_ID, CONF_NAME, DOMAIN
from .coordinator import SuntekRuntimeData

_LOGGER = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})")


async def async_sync_cloud_media(
    hass: HomeAssistant,
    runtime: SuntekRuntimeData,
    *,
    limit: int,
    include_images: bool,
    include_videos: bool,
) -> dict[str, Any]:
    """Copy cloud photos/videos into Home Assistant's local media directory."""
    started_at = datetime.now(UTC)
    target_root = media_backup_path(hass, runtime.entry)
    result: dict[str, Any] = {
        "state": "running",
        "started_at": started_at.isoformat(),
        "path": str(target_root),
        "limit": limit,
        "include_images": include_images,
        "include_videos": include_videos,
        "downloaded": 0,
        "skipped": 0,
        "errors": [],
        "files": [],
    }
    _store_result(runtime, result)

    try:
        cloud_files = await _async_list_cloud_files(runtime.client, limit)
        await hass.async_add_executor_job(_ensure_directory, target_root)

        for item in cloud_files:
            if not _media_type_enabled(item, include_images, include_videos):
                continue

            url = _download_url(item)
            if not url:
                continue

            target = target_root / _date_folder(item) / _media_file_name(item)
            if await hass.async_add_executor_job(target.exists):
                result["skipped"] += 1
                continue

            try:
                data = await runtime.client.async_fetch_bytes(url, timeout=180)
                await hass.async_add_executor_job(_write_bytes_atomic, target, data)
            except (OSError, SuntekApiError) as err:
                _LOGGER.warning("Suntek media backup failed for %s: %s", url, err)
                result["errors"].append({"url": url, "error": str(err)})
                continue

            result["downloaded"] += 1
            result["files"].append(
                {
                    "path": str(target),
                    "media_type": item.get("media_type"),
                    "created_at": item.get("created_at"),
                    "upload_time": item.get("upload_time"),
                }
            )

        result["finished_at"] = datetime.now(UTC).isoformat()
        result["state"] = "ok" if not result["errors"] else "partial"
        try:
            await hass.async_add_executor_job(_write_index, target_root, result)
        except OSError as err:
            result["state"] = "partial"
            result["errors"].append({"path": str(target_root), "error": str(err)})
        return result
    except SuntekApiError as err:
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["state"] = "error"
        result["error"] = str(err)
        raise
    finally:
        _store_result(runtime, result)


def media_backup_path(hass: HomeAssistant, entry: ConfigEntry) -> Path:
    """Return the local media folder used by this config entry."""
    name = str(entry.data.get(CONF_NAME) or entry.title or entry.data[CONF_DEVICE_ID])
    folder = _safe_name(name, entry.data[CONF_DEVICE_ID])
    return Path(hass.config.path("media", DOMAIN, folder))


async def _async_list_cloud_files(
    client: SuntekCloudClient, limit: int
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    page = 1
    limit = max(1, limit)

    while len(files) < limit:
        page_size = min(100, limit - len(files))
        batch = await client.async_list_cloud_files(page=page, page_size=page_size)
        if not batch:
            break

        files.extend(batch)
        if len(batch) < page_size:
            break

        page += 1

    return files[:limit]


def _media_type_enabled(
    item: dict[str, Any], include_images: bool, include_videos: bool
) -> bool:
    media_type = str(item.get("media_type") or "")
    return (media_type == "image" and include_images) or (
        media_type == "video" and include_videos
    )


def _download_url(item: dict[str, Any]) -> str:
    return str(item.get("file_url") or item.get("download_url") or "").strip()


def _date_folder(item: dict[str, Any]) -> str:
    for key in ("created_at", "upload_time"):
        value = str(item.get(key) or "").strip()
        match = _DATE_RE.match(value)
        if match:
            return "-".join(match.groups())

    return "undated"


def _media_file_name(item: dict[str, Any]) -> str:
    file_name = str(item.get("file_name") or "").strip()
    fallback = f"suntek-{item.get('id') or datetime.now(UTC).timestamp()}"
    return _safe_name(file_name, fallback)


def _safe_name(value: str, fallback: str) -> str:
    value = _SAFE_NAME_RE.sub("_", value.strip())
    value = value.strip("._-")
    return value[:140] or _SAFE_NAME_RE.sub("_", fallback) or "suntek"


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(path)


def _write_index(path: Path, result: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    index_path = path / "index.json"
    index_path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _store_result(runtime: SuntekRuntimeData, result: dict[str, Any]) -> None:
    runtime.last_media_sync = result
    runtime.coordinator.async_update_listeners()
