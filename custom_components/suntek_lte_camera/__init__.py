"""Suntek LTE Camera integration."""

from __future__ import annotations

from datetime import timedelta
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .api import SuntekApiError, SuntekCloudClient
from .const import (
    ATTR_CONTENT,
    ATTR_ENTRY_ID,
    ATTR_INCLUDE_IMAGES,
    ATTR_INCLUDE_VIDEOS,
    ATTR_LIMIT,
    CONF_CLOUD_DEVICE_ID,
    CONF_DEVICE_ID,
    CONF_MEDIA_BACKUP_ENABLED,
    CONF_MEDIA_BACKUP_INCLUDE_VIDEOS,
    CONF_MEDIA_BACKUP_INTERVAL,
    CONF_MEDIA_BACKUP_LIMIT,
    CONF_PASSWORD,
    CONF_P2P_API,
    CONF_P2P_DID,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_ADDR,
    DEFAULT_MEDIA_BACKUP_INTERVAL,
    DEFAULT_MEDIA_BACKUP_LIMIT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WAKE_COMMAND,
    DOMAIN,
    SERVICE_REFRESH,
    SERVICE_SYNC_CLOUD_MEDIA,
    SERVICE_WAKEUP,
)
from .coordinator import SuntekDataUpdateCoordinator, SuntekRuntimeData
from .frontend import SuntekFrontend
from .media import async_sync_cloud_media

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

SYNC_CLOUD_MEDIA_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_LIMIT, default=DEFAULT_MEDIA_BACKUP_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1000)
        ),
        vol.Optional(ATTR_INCLUDE_IMAGES, default=True): cv.boolean,
        vol.Optional(ATTR_INCLUDE_VIDEOS, default=True): cv.boolean,
    }
)


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

    async def handle_sync_cloud_media(call: ServiceCall) -> None:
        for runtime in _iter_runtime_data(hass, call.data.get(ATTR_ENTRY_ID)):
            try:
                await async_sync_cloud_media(
                    hass,
                    runtime,
                    limit=call.data[ATTR_LIMIT],
                    include_images=call.data[ATTR_INCLUDE_IMAGES],
                    include_videos=call.data[ATTR_INCLUDE_VIDEOS],
                )
            except SuntekApiError as err:
                raise HomeAssistantError(
                    f"Suntek cloud media sync failed: {err}"
                ) from err

    hass.services.async_register(
        DOMAIN, SERVICE_WAKEUP, handle_wakeup, schema=WAKEUP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, handle_refresh, schema=REFRESH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_CLOUD_MEDIA,
        handle_sync_cloud_media,
        schema=SYNC_CLOUD_MEDIA_SCHEMA,
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
        p2p_did=_entry_value(entry, CONF_P2P_DID, ""),
        p2p_api=_entry_value(entry, CONF_P2P_API, ""),
    )
    coordinator = SuntekDataUpdateCoordinator(
        hass,
        client,
        scan_interval=int(_entry_value(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SuntekRuntimeData(
        entry=entry,
        client=client,
        coordinator=coordinator,
    )
    await coordinator.async_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _async_schedule_media_backup(hass, hass.data[DOMAIN][entry.entry_id])
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


def _async_schedule_media_backup(
    hass: HomeAssistant, runtime: SuntekRuntimeData
) -> None:
    """Schedule optional periodic cloud media backup."""
    entry = runtime.entry
    if not _entry_value(entry, CONF_MEDIA_BACKUP_ENABLED, False):
        return

    interval_minutes = max(
        15,
        int(
            _entry_value(
                entry, CONF_MEDIA_BACKUP_INTERVAL, DEFAULT_MEDIA_BACKUP_INTERVAL
            )
        ),
    )

    async def _async_run_backup(_now) -> None:
        try:
            await async_sync_cloud_media(
                hass,
                runtime,
                limit=int(
                    _entry_value(
                        entry, CONF_MEDIA_BACKUP_LIMIT, DEFAULT_MEDIA_BACKUP_LIMIT
                    )
                ),
                include_images=True,
                include_videos=bool(
                    _entry_value(entry, CONF_MEDIA_BACKUP_INCLUDE_VIDEOS, True)
                ),
            )
        except SuntekApiError as err:
            _LOGGER.warning("Scheduled Suntek cloud media backup failed: %s", err)

    entry.async_on_unload(
        async_track_time_interval(
            hass, _async_run_backup, timedelta(minutes=interval_minutes)
        )
    )


def _async_schedule_frontend(hass: HomeAssistant) -> None:
    """Register frontend resources after Lovelace has initialized."""
    if hass.state == CoreState.running:
        hass.async_create_task(SuntekFrontend(hass).async_register())
        return

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED,
        lambda _event: hass.async_create_task(SuntekFrontend(hass).async_register()),
    )
