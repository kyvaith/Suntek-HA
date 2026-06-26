"""Camera entity for Suntek LTE Camera."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the camera entity."""
    runtime: SuntekRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SuntekCamera(runtime, entry)])


class SuntekCamera(CoordinatorEntity, Camera):
    """Suntek camera entity.

    The APK receives live frames through a proprietary P2P library. This entity
    wakes the camera and hands Home Assistant an RTSP/HLS/MJPEG URL if one is
    configured, for example from a local P2P bridge.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "camera"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_camera"
        self._attr_device_info = device_info(entry)
        self._attr_supported_features = (
            CameraEntityFeature.STREAM
            if entry_value(entry, CONF_STREAM_URL_TEMPLATE, "")
            else CameraEntityFeature(0)
        )

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
        """Return a still image if a still-image URL template is configured."""
        template = entry_value(self._entry, CONF_STILL_IMAGE_URL_TEMPLATE, "")
        if not template:
            return None

        try:
            url = self._runtime.client.render_url_template(template)
            return await self._runtime.client.async_fetch_bytes(url)
        except SuntekApiError as err:
            _LOGGER.warning("Suntek still image fetch failed: %s", err)
            return None

