"""Camera entity for Suntek LTE Camera."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from pathlib import Path
import queue
import threading

from aiohttp import web
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SuntekApiError
from .const import (
    CONF_DEVICE_ID,
    CONF_STILL_IMAGE_URL_TEMPLATE,
    CONF_STREAM_URL_TEMPLATE,
    CONF_WAKE_BEFORE_STREAM,
    CONF_WAKE_COOLDOWN,
    DEFAULT_WAKE_COOLDOWN,
    DOMAIN,
)
from .coordinator import SuntekRuntimeData
from .entity import device_info, entry_value
from .live import SuntekP2PLiveClient, SuntekP2PLiveStopped

_LOGGER = logging.getLogger(__name__)
_FALLBACK_IMAGE = Path(__file__).parent / "brand" / "logo.png"
_MJPEG_BOUNDARY = b"suntekframe"
_STREAM_KEEPALIVE_SECONDS = 5.0
_QUEUE_EMPTY = object()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the camera entity."""
    runtime: SuntekRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SuntekCamera(runtime, entry)])


class SuntekCamera(Camera):
    """Suntek camera entity for the Home Assistant camera dashboard tile."""

    _attr_has_entity_name = True
    _attr_translation_key = "camera"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__()
        self._runtime = runtime
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_camera"
        self._attr_device_info = device_info(entry)
        self._last_preview_image: bytes | None = None
        has_stream = bool(entry_value(entry, CONF_STREAM_URL_TEMPLATE, ""))
        self._attr_supported_features = (
            CameraEntityFeature.STREAM if has_stream else CameraEntityFeature(0)
        )

    @property
    def available(self) -> bool:
        """Keep the camera tile available even when LTE status polling is offline."""
        return True

    async def stream_source(self) -> str | None:
        """Return the configured stream URL after optionally waking the camera."""
        template = entry_value(self._entry, CONF_STREAM_URL_TEMPLATE, "")
        if not template:
            return None

        if entry_value(self._entry, CONF_WAKE_BEFORE_STREAM, True):
            cooldown = int(
                entry_value(
                    self._entry, CONF_WAKE_COOLDOWN, DEFAULT_WAKE_COOLDOWN
                )
            )
            try:
                await self._runtime.client.async_wakeup(cooldown=cooldown)
            except SuntekApiError as err:
                _LOGGER.warning("Suntek wakeup before stream failed: %s", err)

        return self._runtime.client.render_url_template(template)

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse | None:
        """Handle a Home Assistant MJPEG stream using the native Suntek P2P path."""
        if entry_value(self._entry, CONF_STREAM_URL_TEMPLATE, ""):
            return None

        did = self._runtime.client.p2p_did
        if not did:
            return None

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": (
                    "multipart/x-mixed-replace; "
                    f"boundary={_MJPEG_BOUNDARY.decode()}"
                ),
                "Cache-Control": "no-cache",
            },
        )
        await response.prepare(request)

        keepalive_image = self._last_preview_image
        if keepalive_image is None:
            keepalive_image = await self.hass.async_add_executor_job(
                _read_fallback_image
            )
        if keepalive_image:
            await _async_write_mjpeg_frame(response, keepalive_image)

        if entry_value(self._entry, CONF_WAKE_BEFORE_STREAM, True):
            cooldown = int(
                entry_value(
                    self._entry, CONF_WAKE_COOLDOWN, DEFAULT_WAKE_COOLDOWN
                )
            )
            with suppress(SuntekApiError):
                await self._runtime.client.async_wakeup(cooldown=cooldown)

        password_hash = await self._runtime.client.async_effective_password()
        frame_queue: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=2)
        stop_event = threading.Event()
        live_client = SuntekP2PLiveClient(
            did,
            self._runtime.client.p2p_api,
            password_hash,
        )

        def _worker() -> None:
            try:
                for frame in live_client.iter_jpeg_frames(stop_event):
                    if stop_event.is_set():
                        break
                    try:
                        frame_queue.put(frame, timeout=1)
                    except queue.Full:
                        continue
            except SuntekP2PLiveStopped:
                _LOGGER.debug("Suntek P2P live stream stopped by the client")
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Suntek P2P live stream failed: %s", err)
                with suppress(queue.Full):
                    frame_queue.put(err, timeout=1)
            finally:
                live_client.close()
                with suppress(queue.Full):
                    frame_queue.put(None, timeout=1)

        thread = threading.Thread(
            target=_worker,
            name=f"suntek-live-{self._entry.entry_id}",
            daemon=True,
        )
        thread.start()

        try:
            while not stop_event.is_set():
                item = await self.hass.async_add_executor_job(
                    _queue_get, frame_queue, _STREAM_KEEPALIVE_SECONDS
                )
                if item is _QUEUE_EMPTY:
                    if keepalive_image:
                        await _async_write_mjpeg_frame(response, keepalive_image)
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    break
                keepalive_image = item
                await _async_write_mjpeg_frame(response, item)
        except (asyncio.CancelledError, ConnectionResetError):
            raise
        finally:
            stop_event.set()
            live_client.close()

        return response

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image for Home Assistant camera previews."""
        await self._async_wakeup_for_preview()

        template = entry_value(self._entry, CONF_STILL_IMAGE_URL_TEMPLATE, "")
        if not template:
            return await self._async_latest_or_fallback_image()

        try:
            url = self._runtime.client.render_url_template(template)
            data = await self._runtime.client.async_fetch_bytes(url)
            self.content_type = _content_type(data)
            self._remember_preview_image(data)
            return data
        except SuntekApiError as err:
            _LOGGER.warning("Suntek still image fetch failed: %s", err)
            return await self._async_latest_or_fallback_image()

    async def _async_latest_or_fallback_image(self) -> bytes | None:
        try:
            data = await self._runtime.client.async_fetch_latest_image()
        except SuntekApiError as err:
            _LOGGER.debug("Suntek latest image fetch failed: %s", err)
            data = await self.hass.async_add_executor_job(_read_fallback_image)

        self.content_type = _content_type(data)
        self._remember_preview_image(data)
        return data

    async def _async_wakeup_for_preview(self) -> None:
        cooldown = int(
            entry_value(self._entry, CONF_WAKE_COOLDOWN, DEFAULT_WAKE_COOLDOWN)
        )
        try:
            await self._runtime.client.async_wakeup(cooldown=cooldown)
        except SuntekApiError as err:
            _LOGGER.debug("Suntek wakeup before preview failed: %s", err)

    def _remember_preview_image(self, data: bytes | None) -> None:
        """Remember the last preview so slow live streams can start immediately."""
        if data:
            self._last_preview_image = data


def _read_fallback_image() -> bytes | None:
    try:
        return _FALLBACK_IMAGE.read_bytes()
    except OSError as err:
        _LOGGER.warning("Suntek fallback image is unavailable: %s", err)
        return None


def _content_type(data: bytes | None) -> str:
    if not data:
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


def _queue_get(
    frame_queue: queue.Queue[bytes | Exception | None], timeout: float
) -> bytes | Exception | None | object:
    try:
        return frame_queue.get(timeout=timeout)
    except queue.Empty:
        return _QUEUE_EMPTY


async def _async_write_mjpeg_frame(
    response: web.StreamResponse, image: bytes
) -> None:
    content_type = _content_type(image).encode()
    await response.write(
        b"--"
        + _MJPEG_BOUNDARY
        + b"\r\nContent-Type: "
        + content_type
        + b"\r\nContent-Length: "
        + str(len(image)).encode()
        + b"\r\n\r\n"
        + image
        + b"\r\n"
    )
