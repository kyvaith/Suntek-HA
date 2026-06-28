"""Client for the SuntekCam cloud endpoints found in the Android APK."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import aiohttp

from .const import (
    CONF_CLOUD_DEVICE_ID,
    CONF_P2P_API,
    CONF_P2P_DID,
    DEFAULT_SERVER_ADDR,
    DEFAULT_WAKE_COMMAND,
)

_LOGGER = logging.getLogger(__name__)

SERVER_COMMAND_SECRET = "8ac10106160c56f023a8063d5c"
LEGACY_HTTP_SECRET = "dfs4132541df512sfd0"
LEGACY_HTTPS_SECRET = "xme4x84lzd3dsfsfd0"
_MD5_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

_DEVICE_ID_KEYS = (
    "imei",
    "deviceid",
    "device_id",
    "deviceId",
    "devId",
    "did",
    "sn",
)
_DEVICE_CLOUD_ID_KEYS = ("deviceid", "device_id", "deviceId")
_DEVICE_P2P_API_KEYS = ("deviceapi", "deviceApi", "p2papi", "p2pApi")
_DEVICE_NAME_KEYS = (
    "devicename",
    "deviceName",
    "name",
    "nickname",
    "nickName",
    "alias",
    "remark",
)
_DEVICE_SERVER_KEYS = (
    "serveraddr",
    "serverAddr",
    "server_addr",
    "server",
    "serverUrl",
    "userdata2",
)
_IMAGE_URL_HINTS = (
    "image",
    "img",
    "jpg",
    "jpeg",
    "photo",
    "pic",
    "preview",
    "snapshot",
    "thumb",
)
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi")


class SuntekApiError(Exception):
    """Raised when the Suntek cloud API call fails."""


def _md5(value: str) -> str:
    """Return the lowercase MD5 format used by the APK."""
    return hashlib.md5(value.encode()).hexdigest()


def _encode_param(value: str) -> str:
    """Encode a query value close to the APK's manual escaping."""
    return quote(value, safe="")


def _strip_trailing_slash(value: str) -> str:
    return value.strip().rstrip("/")


def normalise_server_addr(value: str) -> str:
    """Return a full 4gcardv server URL from APK server hints."""
    value = _strip_trailing_slash(value or DEFAULT_SERVER_ADDR)
    if not value:
        return DEFAULT_SERVER_ADDR

    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"

    parsed = urlparse(value)
    if parsed.netloc and "." not in parsed.netloc:
        value = parsed._replace(netloc=f"{parsed.netloc}.car-dv.com").geturl()

    if not value.endswith("/4gcardv"):
        value = f"{value}/4gcardv"

    return value


def av_server_addr(server_addr: str) -> str:
    """Convert a 4gcardv base URL to the APK's AV command host."""
    server_addr = _strip_trailing_slash(server_addr or DEFAULT_SERVER_ADDR)

    if server_addr.startswith("http://av") or server_addr.startswith("https://av"):
        server_addr = server_addr.replace("https://", "http://", 1)
        server_addr = server_addr.replace(":1888", "")
        return server_addr.replace(":80/4gcardv", "").replace("/4gcardv", "")

    if server_addr.startswith("http://"):
        return server_addr.replace("http://", "http://av", 1).replace(
            ":80/4gcardv", ""
        )

    if server_addr.startswith("https://"):
        return server_addr.replace("https://", "http://av", 1).replace(
            "/4gcardv", ""
        )

    return f"http://av{server_addr}".replace(":80/4gcardv", "").replace(
        "/4gcardv", ""
    )


def legacy_signed_url(params: Mapping[str, Any], url: str) -> str:
    """Build the signed 4gcardv URL used by queryPassword/queryFiles/etc."""
    if not params or not url:
        raise SuntekApiError("Missing URL or params for signed Suntek request")

    sorted_items = sorted((key, str(value)) for key, value in params.items())
    query = "&".join(f"{key}={_encode_param(value)}" for key, value in sorted_items)
    values = "".join(value for _, value in sorted_items)
    secret = LEGACY_HTTP_SECRET if url.startswith("http://") else LEGACY_HTTPS_SECRET
    return f"{url}?{query}&sign={_md5(values + secret)}"


def online_from_response(value: Any) -> bool | None:
    """Best-effort online extraction from different server response shapes."""
    if isinstance(value, bool):
        return value

    if isinstance(value, int | float):
        return value > 0

    if isinstance(value, str):
        return _state_to_online(value)

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_l = str(key).lower()
            if "online" in key_l:
                return _truthy(item)
            if key_l in {"status", "state"}:
                parsed = _state_to_online(item)
                if parsed is not None:
                    return parsed
            if key_l in {"data", "result", "device"}:
                parsed = online_from_response(item)
                if parsed is not None:
                    return parsed

    if isinstance(value, list):
        for item in value:
            parsed = online_from_response(item)
            if parsed is not None:
                return parsed

    return None


def devices_from_response(
    value: Any, fallback_id: str, default_server_addr: str = DEFAULT_SERVER_ADDR
) -> list[dict[str, str]]:
    """Extract device choices from the different cloud response shapes."""
    devices: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in _iter_device_mappings(value):
        imei = _first_mapping_value(item, ("imei",))
        cloud_device_id = _first_mapping_value(item, _DEVICE_CLOUD_ID_KEYS)
        device_id = (
            imei or cloud_device_id or _first_mapping_value(item, _DEVICE_ID_KEYS)
        )
        if not device_id and _has_device_hint(item):
            device_id = _first_mapping_value(item, ("id",))
        if not device_id or device_id in seen:
            continue

        seen.add(device_id)
        name = _device_display_name(item, device_id)
        server_addr = normalise_server_addr(
            _first_mapping_value(item, _DEVICE_SERVER_KEYS) or default_server_addr
        )
        p2p_api = _first_mapping_value(item, _DEVICE_P2P_API_KEYS)
        devices.append(
            {
                "device_id": device_id,
                CONF_CLOUD_DEVICE_ID: cloud_device_id or device_id,
                CONF_P2P_DID: cloud_device_id or device_id,
                CONF_P2P_API: p2p_api,
                "name": name,
                "server_addr": server_addr,
            }
        )

    if devices:
        return devices

    fallback_id = fallback_id.strip()
    return [
        {
            "device_id": fallback_id,
            CONF_CLOUD_DEVICE_ID: fallback_id,
            CONF_P2P_DID: fallback_id,
            CONF_P2P_API: "",
            "name": fallback_id,
            "server_addr": normalise_server_addr(default_server_addr),
        }
    ]


def image_url_from_response(value: Any, base_url: str) -> str:
    """Return the first likely preview image URL from a file-list response."""
    for item in cloud_files_from_response(value, base_url):
        if item["media_type"] == "image":
            return str(item["download_url"])

    for item in _iter_image_url_candidates(value):
        url = _normalise_image_url(item, base_url)
        if url:
            return url
    return ""


def cloud_files_from_response(value: Any, base_url: str) -> list[dict[str, Any]]:
    """Extract cloud media records from queryFiles responses."""
    files: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in _iter_file_mappings(value):
        media = _media_from_file_mapping(item, base_url)
        if not media:
            continue

        dedupe_key = str(media["download_url"])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        files.append(media)

    return files


def device_status_from_response(value: Any) -> dict[str, Any]:
    """Parse the compact Suntek config string into Home Assistant-friendly data."""
    config = _config_from_response(value)
    if not config:
        return {}

    status: dict[str, Any] = {}
    status["signal"] = _int_or_none(config.get("10"))
    status["battery"] = _int_or_none(config.get("11"))
    status["sd_used"], status["sd_total"], status["sd_percent"] = _parse_sd(
        config.get("12", "")
    )
    status["model"] = _blank_to_none(config.get("13"))
    status["firmware"] = _blank_to_none(config.get("14"))
    status["modem_firmware"] = _blank_to_none(config.get("79"))
    status["last_communication"] = _parse_timestamp(
        config.get("15") or config.get("18")
    )
    status["temperature"] = _int_or_none(config.get("17"))
    status["apn"] = _blank_to_none(config.get("42"))
    status["latitude"] = _float_or_none(config.get("47"))
    status["longitude"] = _float_or_none(config.get("48"))
    status["position_valid"] = _truthy(config.get("49"))
    status["capture_mode"] = _capture_mode(config.get("21"))
    status["video_resolution"] = _video_resolution(config.get("62") or config.get("54"))
    status["video_length"] = _int_or_none(config.get("26"))
    status["date_format"] = _date_format(config.get("31"))
    status["temperature_unit"] = _temperature_unit(config.get("32"))
    status["upload_target"] = _upload_target(config.get("66"))
    status["schedule"] = _format_schedule(config.get("33"))
    return status


def raise_for_ret_code(value: Mapping[str, Any]) -> None:
    """Raise a readable error for Suntek API retCode failures."""
    code = value.get("retCode")
    if code in (None, 0, "0"):
        return

    message = str(value.get("message") or value.get("msg") or "").strip()
    if not message:
        message = f"Suntek API returned retCode {code}"
    raise SuntekApiError(message)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "online", "on"}
    return bool(value)


def _state_to_online(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        value_l = value.strip().lower()
        if value_l in {"online", "on", "connected", "true", "1"}:
            return True
        if value_l in {"offline", "off", "disconnected", "false", "0"}:
            return False
    return None


def _iter_device_mappings(value: Any):
    if isinstance(value, Mapping):
        if _first_mapping_value(value, _DEVICE_ID_KEYS) or (
            _first_mapping_value(value, ("id",)) and _has_device_hint(value)
        ):
            yield value

        for item in value.values():
            if isinstance(item, (Mapping, list)):
                yield from _iter_device_mappings(item)

    elif isinstance(value, list):
        for item in value:
            yield from _iter_device_mappings(item)


def _first_mapping_value(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    lower_mapping = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        value = lower_mapping.get(key.lower())
        if value is None:
            continue
        value = str(value).strip()
        if value:
            return value
    return ""


def _has_device_hint(mapping: Mapping[str, Any]) -> bool:
    keys = {str(key).lower() for key in mapping}
    hint_keys = {key.lower() for key in (*_DEVICE_NAME_KEYS, *_DEVICE_SERVER_KEYS)}
    return bool(keys & hint_keys) or any(
        "device" in key or "imei" in key for key in keys
    )


def _device_display_name(mapping: Mapping[str, Any], device_id: str) -> str:
    name = _first_mapping_value(mapping, _DEVICE_NAME_KEYS)
    if name:
        return name

    imei = _first_mapping_value(mapping, ("imei",))
    cloud_id = _first_mapping_value(mapping, ("deviceid", "device_id", "deviceId"))
    if imei and cloud_id and device_id == imei:
        return cloud_id

    return device_id


def _iter_image_url_candidates(value: Any, key_hint: str = ""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _iter_image_url_candidates(item, str(key).lower())
    elif isinstance(value, list):
        for item in value:
            yield from _iter_image_url_candidates(item, key_hint)
    elif isinstance(value, str) and _looks_like_image_url(value, key_hint):
        yield value


def _iter_file_mappings(value: Any):
    if isinstance(value, Mapping):
        if any(str(key).lower() in {"fileurl", "reducefileurl"} for key in value):
            yield value

        for item in value.values():
            if isinstance(item, (Mapping, list)):
                yield from _iter_file_mappings(item)

    elif isinstance(value, list):
        for item in value:
            yield from _iter_file_mappings(item)


def _media_from_file_mapping(
    mapping: Mapping[str, Any], base_url: str
) -> dict[str, Any] | None:
    file_url = _first_mapping_value(mapping, ("fileurl", "url"))
    preview_url = _first_mapping_value(
        mapping, ("reducefileurl", "thumbnail", "thumburl")
    )
    media_type = _media_type(mapping, file_url, preview_url)
    download_url = preview_url if media_type == "image" and preview_url else file_url
    if not download_url:
        return None

    normalised_download_url = _normalise_image_url(download_url, base_url)
    normalised_file_url = _normalise_image_url(file_url, base_url) if file_url else ""
    normalised_preview_url = (
        _normalise_image_url(preview_url, base_url) if preview_url else ""
    )
    return {
        "id": str(mapping.get("id") or ""),
        "device_id": str(mapping.get("deviceid") or ""),
        "file_type": mapping.get("filetype"),
        "media_type": media_type,
        "file_url": normalised_file_url,
        "preview_url": normalised_preview_url,
        "download_url": normalised_download_url,
        "file_name": _file_name_from_url(normalised_file_url or normalised_download_url),
        "upload_time": str(mapping.get("uploadtime") or ""),
        "created_at": str(mapping.get("createtime") or ""),
        "size": mapping.get("filesize"),
        "latitude": _float_or_none(mapping.get("lat")),
        "longitude": _float_or_none(mapping.get("lon")),
    }


def _media_type(mapping: Mapping[str, Any], file_url: str, preview_url: str) -> str:
    file_type = str(mapping.get("filetype") or "").strip()
    if file_type == "1":
        return "image"
    if file_type == "2":
        return "video"

    url_l = (file_url or preview_url).lower().split("?", 1)[0]
    if any(url_l.endswith(extension) for extension in _VIDEO_EXTENSIONS):
        return "video"
    return "image"


def _file_name_from_url(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name or "suntek-media"


def _looks_like_image_url(value: str, key_hint: str) -> bool:
    value_l = value.strip().lower().replace("\\", "/")
    if not value_l.startswith(("http://", "https://", "/", "//")):
        return False

    path = value_l.split("?", 1)[0]
    has_image_extension = any(
        path.endswith(extension) for extension in _IMAGE_EXTENSIONS
    )
    has_image_hint = any(hint in key_hint for hint in _IMAGE_URL_HINTS)
    return has_image_extension or has_image_hint


def _normalise_image_url(value: str, base_url: str) -> str:
    value = value.strip().replace("\\", "/")
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith(("http://", "https://")):
        return value
    return urljoin(f"{normalise_server_addr(base_url)}/", value)


def _config_from_response(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        config_value = value.get("config")
        if isinstance(config_value, str):
            return _parse_config_string(config_value)

        for key in ("data", "device", "result"):
            parsed = _config_from_response(value.get(key))
            if parsed:
                return parsed

    return {}


def _parse_config_string(value: str) -> dict[str, str]:
    config: dict[str, str] = {}
    for part in value.split("#"):
        if "=" not in part:
            continue
        key, item = part.split("=", 1)
        key = key.strip()
        if key:
            config[key] = item.strip()
    return config


def _parse_sd(value: str) -> tuple[int | None, int | None, int | None]:
    if "|" not in value:
        return None, None, _int_or_none(value)

    used_raw, total_raw = value.split("|", 1)
    used = _int_or_none(used_raw)
    total = _int_or_none(total_raw)
    if used is None or total in (None, 0):
        return used, total, None
    return used, total, round(used / total * 100)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    value = str(value).strip()
    try:
        if len(value) == 14 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        if value.isdigit():
            return datetime.fromtimestamp(int(value), UTC)
    except (OSError, ValueError):
        return None

    return None


def _video_resolution(value: str | None) -> str | None:
    value = str(value or "").strip()
    return {
        "0": "4K",
        "1": "2K",
        "2": "1080P",
        "3": "720P",
        "4": "VGA",
    }.get(value, value or None)


def _upload_target(value: str | None) -> str | None:
    value = str(value or "").strip()
    return {
        "0": "Cloud",
        "1": "Mail",
        "2": "Cloud + Mail",
        "3": "FTP",
        "4": "Cloud + FTP",
    }.get(value, value or None)


def _capture_mode(value: str | None) -> str | None:
    value = str(value or "").strip()
    return {
        "0": "Photo",
        "1": "Video",
        "2": "Photo + Video",
        "3": "Timelapse",
    }.get(value, value or None)


def _date_format(value: str | None) -> str | None:
    value = str(value or "").strip()
    return {
        "0": "YMD",
        "1": "DMY",
        "2": "MDY",
    }.get(value, value or None)


def _temperature_unit(value: str | None) -> str | None:
    value = str(value or "").strip()
    return {
        "0": "F",
        "1": "C",
    }.get(value, value or None)


def _format_schedule(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value or "-" not in value:
        return None

    start, end = value.split("-", 1)
    return f"{_format_hhmmss(start)} - {_format_hhmmss(end)}"


def _format_hhmmss(value: str) -> str:
    value = value.strip()
    if len(value) == 6 and value.isdigit():
        return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"
    return value


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _blank_to_none(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


class SuntekCloudClient:
    """Small async client for the SuntekCam cloud API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        device_id: str,
        server_addr: str = DEFAULT_SERVER_ADDR,
        password: str = "",
        cloud_device_id: str = "",
        p2p_did: str = "",
        p2p_api: str = "",
        timeout: int = 15,
    ) -> None:
        self.session = session
        self.device_id = device_id.strip()
        self.cloud_device_id = cloud_device_id.strip()
        self.p2p_did = p2p_did.strip() or self.cloud_device_id
        self.p2p_api = p2p_api.strip()
        self.server_addr = normalise_server_addr(server_addr or DEFAULT_SERVER_ADDR)
        self.password = password or ""
        self.timeout = timeout
        self._last_wakeup = 0.0
        self._cloud_password: str | None = None
        self.last_wakeup: dict[str, Any] = {"state": "never"}

    @property
    def av_server_addr(self) -> str:
        """Return the AV command server base URL."""
        return av_server_addr(self.server_addr)

    def render_url_template(self, template: str) -> str:
        """Render user supplied stream/still URL templates."""
        try:
            return template.format(
                device_id=self.device_id,
                imei=self.device_id,
                password=self.password,
                server_addr=self.server_addr,
                av_server_addr=self.av_server_addr,
                cloud_device_id=self.cloud_device_id,
                p2p_did=self.p2p_did,
                p2p_api=self.p2p_api,
            )
        except Exception as err:  # noqa: BLE001
            raise SuntekApiError(f"Invalid Suntek URL template: {err}") from err

    async def async_check_online(self) -> dict[str, Any]:
        """Call /api/device/checkOnline."""
        signature = _md5(f"{self.device_id}{SERVER_COMMAND_SECRET}")
        url = (
            f"{self.av_server_addr}:1888/api/device/checkOnline"
            f"?deviceId={_encode_param(self.device_id)}&sign={signature}"
        )
        data = await self._async_get_json(url)
        raise_for_ret_code(data)
        return data

    async def async_send_server_command(
        self, content: int = DEFAULT_WAKE_COMMAND
    ) -> dict[str, Any]:
        """Call /api/device/sendMsg with a numeric command content."""
        content = int(content)
        signature = _md5(f"{content}{self.device_id}{SERVER_COMMAND_SECRET}")
        url = (
            f"{self.av_server_addr}:1888/api/device/sendMsg"
            f"?deviceId={_encode_param(self.device_id)}"
            f"&content={content}&sign={signature}"
        )
        data = await self._async_get_json(url)
        raise_for_ret_code(data)
        return data

    async def async_query_device_status(self, status_id: int = 1003) -> dict[str, Any]:
        """Call the device status endpoint used by the APK before live view."""
        url = legacy_signed_url(
            {
                "id": int(status_id),
                "imei": self.device_id,
                "timestamp": int(time.time()),
            },
            f"{self.server_addr}/deviceApi/api/queryDeviceStatus",
        )
        data = await self._async_get_json(url)
        raise_for_ret_code(data)
        return data

    async def async_wakeup(
        self,
        content: int = DEFAULT_WAKE_COMMAND,
        cooldown: int = 0,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Wake the camera, optionally throttling repeated stream requests."""
        now = time.monotonic()
        if not force and cooldown > 0 and now - self._last_wakeup < cooldown:
            return {"skipped": True, "reason": "cooldown"}

        try:
            data = await self.async_send_server_command(content)
        except SuntekApiError as err:
            self.last_wakeup = {
                "state": "error",
                "at": datetime.now(UTC).isoformat(),
                "error": str(err),
            }
            raise

        self._last_wakeup = now
        self.last_wakeup = {
            "state": "sent",
            "at": datetime.now(UTC).isoformat(),
            "response": data,
        }
        return data

    async def async_query_cloud_password(self) -> dict[str, Any]:
        """Query the cloud password by IMEI/device id."""
        url = legacy_signed_url(
            {
                "imei": self.device_id,
                "timestamp": int(time.time()),
            },
            f"{self.server_addr}/msgfileApi/api/queryPassword",
        )
        data = await self._async_get_json(url)
        raise_for_ret_code(data)
        return data

    async def async_effective_password(self) -> str:
        """Return the cloud password hash used by the Android app."""
        if self._cloud_password:
            return self._cloud_password

        try:
            response = await self.async_query_cloud_password()
        except SuntekApiError as err:
            _LOGGER.debug("Suntek queryPassword failed, using local hash: %s", err)
        else:
            cloud_password = str(response.get("data") or "").strip()
            if cloud_password:
                self._cloud_password = cloud_password
                return cloud_password

        password = self.password.strip()
        if not password:
            return ""
        if _MD5_RE.match(password):
            return password.lower()
        return _md5(password)

    async def async_live_password(self) -> str:
        """Return the cloud password hash used by the native live-view login."""
        try:
            await self.async_query_device()
        except SuntekApiError as err:
            _LOGGER.debug(
                "Suntek live metadata refresh failed, using cached server: %s",
                err,
            )
        return await self.async_effective_password()

    async def async_query_device(self, password: str | None = None) -> dict[str, Any]:
        """Query device metadata from the 4gcardv cloud."""
        effective_password = (
            password if password is not None else await self.async_effective_password()
        )
        url = legacy_signed_url(
            {
                "imei": self.device_id,
                "password": effective_password,
                "timestamp": int(time.time()),
            },
            f"{self.server_addr}/msgfileApi/api/queryDevice",
        )
        data = await self._async_get_json(url)
        raise_for_ret_code(data)
        if not data.get("data"):
            raise SuntekApiError("Device was not found")
        self._apply_device_metadata(data)
        return data

    async def async_discover_devices(self) -> list[dict[str, str]]:
        """Return camera choices for the config flow."""
        response = await self.async_query_device()
        return devices_from_response(response, self.device_id, self.server_addr)

    async def async_cloud_device_id(self) -> str:
        """Return the cloud file-list device id, usually VIST-..."""
        if self.cloud_device_id:
            return self.cloud_device_id

        await self.async_query_device()
        return self.cloud_device_id or self.device_id

    async def async_query_files(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """Query cloud files for the configured device."""
        cloud_device_id = await self.async_cloud_device_id()
        url = legacy_signed_url(
            {
                "curPage": page,
                "deviceid": cloud_device_id,
                "pageSize": page_size,
                "password": await self.async_effective_password(),
                "timestamp": int(time.time()),
            },
            f"{self.server_addr}/msgfileApi/api/queryFiles",
        )
        data = await self._async_get_json(url)
        raise_for_ret_code(data)
        return data

    async def async_list_cloud_files(
        self, page: int = 1, page_size: int = 100
    ) -> list[dict[str, Any]]:
        """Return normalised cloud media file records."""
        response = await self.async_query_files(page=page, page_size=page_size)
        return cloud_files_from_response(response, self.server_addr)

    async def async_fetch_latest_image(self) -> bytes:
        """Fetch the latest cloud preview image when the file list exposes one."""
        files = await self.async_list_cloud_files(page=1, page_size=100)
        image = next(
            (item for item in files if item.get("media_type") == "image"),
            None,
        )
        if image is None:
            raise SuntekApiError("No preview image URL found in the file list")
        return await self.async_fetch_bytes(str(image["download_url"]))

    def _apply_device_metadata(self, response: Mapping[str, Any]) -> None:
        data = response.get("data")
        if not isinstance(data, Mapping):
            return

        cloud_device_id = _first_mapping_value(data, _DEVICE_CLOUD_ID_KEYS)
        if cloud_device_id:
            self.cloud_device_id = cloud_device_id
            self.p2p_did = cloud_device_id

        p2p_api = _first_mapping_value(data, _DEVICE_P2P_API_KEYS)
        if p2p_api:
            self.p2p_api = p2p_api

        server_addr = _first_mapping_value(data, _DEVICE_SERVER_KEYS)
        if server_addr:
            next_server_addr = normalise_server_addr(server_addr)
            if next_server_addr != self.server_addr:
                self.server_addr = next_server_addr
                self._cloud_password = None

    async def async_fetch_bytes(self, url: str, timeout: int | None = None) -> bytes:
        """Fetch bytes for a cloud media URL."""
        headers = {"User-Agent": "SuntekCam/2.0 HomeAssistant"}
        client_timeout = aiohttp.ClientTimeout(total=timeout or self.timeout)
        async with self.session.get(
            url, headers=headers, timeout=client_timeout
        ) as response:
            if response.status >= 400:
                raise SuntekApiError(f"HTTP {response.status} while fetching {url}")
            return await response.read()

    async def _async_get_json(self, url: str) -> dict[str, Any]:
        headers = {"User-Agent": "SuntekCam/2.0 HomeAssistant"}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        _LOGGER.debug("Suntek GET %s", url)

        try:
            async with self.session.get(
                url, headers=headers, timeout=timeout
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    raise SuntekApiError(f"HTTP {response.status}: {text[:200]}")
        except TimeoutError as err:
            raise SuntekApiError(f"Timeout while calling {url}") from err
        except aiohttp.ClientError as err:
            raise SuntekApiError(str(err)) from err

        if not text:
            return {}

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.debug("Suntek non-JSON response from %s: %s", url, text[:500])
            return {"raw": text}

        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
