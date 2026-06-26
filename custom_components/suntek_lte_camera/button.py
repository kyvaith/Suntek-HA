"""Button entities for Suntek LTE Camera."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SuntekApiError
from .const import CONF_DEVICE_ID, DEFAULT_WAKE_COMMAND, DOMAIN
from .coordinator import SuntekRuntimeData
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up button entities."""
    runtime: SuntekRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SuntekWakeButton(runtime, entry)])


class SuntekWakeButton(CoordinatorEntity, ButtonEntity):
    """Button that sends the APK's wakeup command."""

    _attr_has_entity_name = True
    _attr_translation_key = "wakeup"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_wakeup"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        """Wake the camera."""
        try:
            await self._runtime.client.async_wakeup(DEFAULT_WAKE_COMMAND, force=True)
        except SuntekApiError as err:
            self.async_write_ha_state()
            raise HomeAssistantError(f"Suntek wake-up failed: {err}") from err

        await self._runtime.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the last cloud response for quick troubleshooting."""
        return self._runtime.client.last_wakeup
