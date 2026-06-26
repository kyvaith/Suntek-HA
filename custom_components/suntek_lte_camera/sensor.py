"""Sensor entities for Suntek LTE Camera."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import SuntekRuntimeData
from .entity import device_info

STATUS_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="signal",
        translation_key="signal",
        icon="mdi:signal",
        native_unit_of_measurement="/5",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="sd_percent",
        translation_key="sd_storage",
        icon="mdi:sd",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="last_communication",
        translation_key="last_communication",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="position",
        translation_key="position",
        icon="mdi:map-marker",
    ),
    SensorEntityDescription(
        key="model",
        translation_key="model",
        icon="mdi:camera-iris",
    ),
    SensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
    ),
    SensorEntityDescription(
        key="apn",
        translation_key="apn",
        icon="mdi:sim",
    ),
    SensorEntityDescription(
        key="video_resolution",
        translation_key="video_resolution",
        icon="mdi:video-high-definition",
    ),
    SensorEntityDescription(
        key="video_length",
        translation_key="video_length",
        icon="mdi:timer-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="upload_target",
        translation_key="upload_target",
        icon="mdi:cloud-upload-outline",
    ),
    SensorEntityDescription(
        key="schedule",
        translation_key="schedule",
        icon="mdi:calendar-clock",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor entities."""
    runtime: SuntekRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            *(
                SuntekStatusSensor(runtime, entry, description)
                for description in STATUS_SENSOR_DESCRIPTIONS
            ),
            SuntekLastWakeupSensor(runtime, entry),
            SuntekLastMediaSyncSensor(runtime, entry),
        ]
    )


class SuntekStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor backed by the last known camera status from the cloud."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: SuntekRuntimeData,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(runtime.coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        """Return whether camera status data was received."""
        status = self._status
        return bool(status) and self.native_value is not None

    @property
    def native_value(self) -> Any:
        """Return the parsed camera status value."""
        key = self.entity_description.key
        status = self._status

        if key == "position":
            latitude = status.get("latitude")
            longitude = status.get("longitude")
            if latitude is None or longitude is None:
                return None
            return f"{latitude:.6f}, {longitude:.6f}"

        return status.get(key)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Return useful attributes for compound status values."""
        status = self._status
        key = self.entity_description.key

        if key == "signal":
            return {"maximum": 5}
        if key == "sd_percent":
            return {
                "used": status.get("sd_used"),
                "total": status.get("sd_total"),
            }
        if key == "position":
            return {
                "latitude": status.get("latitude"),
                "longitude": status.get("longitude"),
                "position_valid": status.get("position_valid"),
            }
        if key == "firmware":
            return {"modem_firmware": status.get("modem_firmware")}

        return None

    @property
    def _status(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        status = data.get("device_status")
        return status if isinstance(status, dict) else {}


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
    def available(self) -> bool:
        """Keep the diagnostic entity available even when status polling fails."""
        return True

    @property
    def native_value(self) -> str:
        """Return the last wake-up state."""
        return str(self._runtime.client.last_wakeup.get("state", "never"))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the raw command response and timestamp."""
        return self._runtime.client.last_wakeup


class SuntekLastMediaSyncSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor for the last cloud media backup."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "last_media_sync"

    def __init__(self, runtime: SuntekRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_last_media_sync"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        """Keep the diagnostic entity available even when status polling fails."""
        return True

    @property
    def native_value(self) -> str:
        """Return the last media sync state."""
        return str(self._runtime.last_media_sync.get("state", "never"))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the last media sync details."""
        return self._runtime.last_media_sync
