"""Camera entity for Suntek LTE Camera."""

from __future__ import annotations

import logging
from pathlib import Path

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

_LOGGER = logging.getLogger(__name__)
_FALLBACK_IMAGE = Path(__file__).parent / "brand" / "logo.png"


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
    _attr_content_type = "image/png"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__()
        self._runtime = runtime
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_camera"
        self._attr_device_info = device_info(entry)
        self._attr_supported_features = (
            CameraEntityFeature.STREAM
            if entry_value(entry, CONF_STREAM_URL_TEMPLATE, "")
            else CameraEntityFeature(0)
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

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image for Home Assistant camera previews."""
        template = entry_value(self._entry, CONF_STILL_IMAGE_URL_TEMPLATE, "")
        if not template:
            return await self._async_latest_or_fallback_image()

        try:
            url = self._runtime.client.render_url_template(template)
            return await self._runtime.client.async_fetch_bytes(url)
        except SuntekApiError as err:
            _LOGGER.warning("Suntek still image fetch failed: %s", err)
            return await self._async_latest_or_fallback_image()

    async def _async_latest_or_fallback_image(self) -> bytes | None:
        try:
            return await self._runtime.client.async_fetch_latest_image()
        except SuntekApiError as err:
            _LOGGER.debug("Suntek latest image fetch failed: %s", err)
            return await self.hass.async_add_executor_job(_read_fallback_image)


def _read_fallback_image() -> bytes | None:
    try:
        return _FALLBACK_IMAGE.read_bytes()
    except OSError as err:
        _LOGGER.warning("Suntek fallback image is unavailable: %s", err)
        return None
