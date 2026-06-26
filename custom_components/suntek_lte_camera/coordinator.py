"""Data update coordinator for Suntek LTE Camera."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SuntekApiError,
    SuntekCloudClient,
    device_status_from_response,
    online_from_response,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SuntekDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the lightweight online endpoint."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SuntekCloudClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        failures: list[str] = []

        try:
            cloud_status = await self.client.async_check_online()
        except SuntekApiError as err:
            failures.append(f"cloud status: {err}")
            data["cloud_connected"] = False
            data["cloud_status_error"] = str(err)
            data["online"] = False
        else:
            data["cloud_connected"] = True
            data["cloud_status"] = cloud_status
            data["online"] = online_from_response(cloud_status)

        try:
            device = await self.client.async_query_device()
        except SuntekApiError as err:
            failures.append(f"device metadata: {err}")
            data["device_metadata_error"] = str(err)
        else:
            data["device"] = device
            data["device_status"] = device_status_from_response(device)

        if data.get("cloud_connected") or data.get("device_status"):
            return data

        raise UpdateFailed("; ".join(failures) or "No Suntek data available")


@dataclass(slots=True)
class SuntekRuntimeData:
    """Runtime objects stored per config entry."""

    entry: ConfigEntry
    client: SuntekCloudClient
    coordinator: SuntekDataUpdateCoordinator
    last_media_sync: dict[str, Any] = field(
        default_factory=lambda: {"state": "never"}
    )
