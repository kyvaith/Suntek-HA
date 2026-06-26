"""Suntek LTE Camera integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    CoreState,
    EVENT_HOMEASSISTANT_STARTED,
    HomeAssistant,
    ServiceCall,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SuntekCloudClient
from .const import (
    ATTR_CONTENT,
    ATTR_ENTRY_ID,
    CONF_CLOUD_DEVICE_ID,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_ADDR,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WAKE_COMMAND,
    DOMAIN,
    SERVICE_REFRESH,
    SERVICE_WAKEUP,
)
from .coordinator import SuntekDataUpdateCoordinator, SuntekRuntimeData
from .frontend import SuntekFrontend

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CAMERA,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

WAKEUP_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_CONTENT, default=DEFAULT_WAKE_COMMAND): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
    }
)

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up services for Suntek LTE Camera."""
    hass.data.setdefault(DOMAIN, {})
    _async_schedule_frontend(hass)

    async def handle_wakeup(call: ServiceCall) -> None:
        content = call.data[ATTR_CONTENT]
        for runtime in _iter_runtime_data(hass, call.data.get(ATTR_ENTRY_ID)):
            await runtime.client.async_wakeup(content, force=True)
            await runtime.coordinator.async_request_refresh()

    async def handle_refresh(call: ServiceCall) -> None:
        for runtime in _iter_runtime_data(hass, call.data.get(ATTR_ENTRY_ID)):
            await runtime.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_WAKEUP, handle_wakeup, schema=WAKEUP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Suntek LTE Camera config entry."""
    session = async_get_clientsession(hass)
    client = SuntekCloudClient(
        session=session,
        device_id=entry.data[CONF_DEVICE_ID],
        server_addr=_entry_value(entry, CONF_SERVER_ADDR),
        password=_entry_value(entry, CONF_PASSWORD, ""),
        cloud_device_id=_entry_value(entry, CONF_CLOUD_DEVICE_ID, ""),
    )
    coordinator = SuntekDataUpdateCoordinator(
        hass,
        client,
        scan_interval=int(_entry_value(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SuntekRuntimeData(
        client=client,
        coordinator=coordinator,
    )
    await coordinator.async_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _iter_runtime_data(
    hass: HomeAssistant, entry_id: str | None
) -> list[SuntekRuntimeData]:
    entries: dict[str, SuntekRuntimeData] = hass.data.get(DOMAIN, {})
    if entry_id:
        runtime = entries.get(entry_id)
        if runtime is None:
            _LOGGER.warning("Suntek entry_id %s not found", entry_id)
            return []
        return [runtime]
    return list(entries.values())


def _entry_value(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    return entry.options.get(key, entry.data.get(key, default))


def _async_schedule_frontend(hass: HomeAssistant) -> None:
    """Register frontend resources after Lovelace has initialized."""
    if hass.state == CoreState.running:
        hass.async_create_task(SuntekFrontend(hass).async_register())
        return

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED,
        lambda _event: hass.async_create_task(SuntekFrontend(hass).async_register()),
    )
