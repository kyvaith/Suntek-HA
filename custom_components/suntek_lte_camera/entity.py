"""Entity helpers for Suntek LTE Camera."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_DEVICE_ID, CONF_NAME, DEFAULT_NAME, DOMAIN


def entry_value(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Return an option value with config-entry data as fallback."""
    return entry.options.get(key, entry.data.get(key, default))


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return common Home Assistant device info."""
    device_id = entry.data[CONF_DEVICE_ID]
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        manufacturer="Suntek",
        model="LTE trail camera",
        name=name,
    )

