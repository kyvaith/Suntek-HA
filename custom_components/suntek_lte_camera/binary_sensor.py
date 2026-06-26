"""Binary sensors for Suntek LTE Camera."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import SuntekRuntimeData
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensor entities."""
    runtime: SuntekRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SuntekCloudConnectionSensor(runtime, entry)])


class SuntekCloudConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    """Cloud command endpoint connectivity sensor."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "cloud_connection"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_online"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        """Return whether the Suntek command cloud endpoint responded."""
        data = self.coordinator.data or {}
        return data.get("cloud_connected")
