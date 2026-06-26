"""Sensor entities for Suntek LTE Camera."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import SuntekRuntimeData
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities."""
    runtime: SuntekRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SuntekLastWakeupSensor(runtime, entry)])


class SuntekLastWakeupSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor for the last wake-up command."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "last_wakeup"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_last_wakeup"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str:
        """Return the last wake-up state."""
        return str(self._runtime.client.last_wakeup.get("state", "never"))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the raw command response and timestamp."""
        return self._runtime.client.last_wakeup
