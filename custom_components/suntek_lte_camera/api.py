"""Client for the SuntekCam cloud endpoints found in the Android APK."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import logging
import time
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import DEFAULT_SERVER_ADDR, DEFAULT_WAKE_COMMAND

_LOGGER = logging.getLogger(__name__)

SERVER_COMMAND_SECRET = "8ac10106160c56f023a8063d5c"
LEGACY_HTTP_SECRET = "dfs4132541df512sfd0"
LEGACY_HTTPS_SECRET = "xme4x84lzd3dsfsfd0"


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


class SuntekCloudClient:
    """Small async client for the SuntekCam cloud API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        device_id: str,
        server_addr: str = DEFAULT_SERVER_ADDR,
        password: str = "",
        timeout: int = 15,
    ) -> None:
        self.session = session
        self.device_id = device_id.strip()
        self.server_addr = _strip_trailing_slash(server_addr or DEFAULT_SERVER_ADDR)
        self.password = password or ""
        self.timeout = timeout
        self._last_wakeup = 0.0

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
        return await self._async_get_json(url)

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
        return await self._async_get_json(url)

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

        data = await self.async_send_server_command(content)
        self._last_wakeup = now
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
        return await self._async_get_json(url)

    async def async_query_device(self, password: str | None = None) -> dict[str, Any]:
        """Query device metadata from the 4gcardv cloud."""
        url = legacy_signed_url(
            {
                "imei": self.device_id,
                "password": password if password is not None else self.password,
                "timestamp": int(time.time()),
            },
            f"{self.server_addr}/msgfileApi/api/queryDevice",
        )
        return await self._async_get_json(url)

    async def async_query_files(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """Query cloud files for the configured device."""
        url = legacy_signed_url(
            {
                "curPage": page,
                "deviceid": self.device_id,
                "pageSize": page_size,
                "password": self.password,
                "timestamp": int(time.time()),
            },
            f"{self.server_addr}/msgfileApi/api/queryFiles",
        )
        return await self._async_get_json(url)

    async def async_fetch_bytes(self, url: str) -> bytes:
        """Fetch bytes for a still-image URL."""
        headers = {"User-Agent": "SuntekCam/2.0 HomeAssistant"}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with self.session.get(url, headers=headers, timeout=timeout) as response:
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

