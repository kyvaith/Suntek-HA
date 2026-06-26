"""Data update coordinator for Suntek LTE Camera."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SuntekApiError, SuntekCloudClient, online_from_response
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
        try:
            status = await self.client.async_check_online()
        except SuntekApiError as err:
            raise UpdateFailed(str(err)) from err

        return {
            "status": status,
            "online": online_from_response(status),
        }


@dataclass(slots=True)
class SuntekRuntimeData:
    """Runtime objects stored per config entry."""

    client: SuntekCloudClient
    coordinator: SuntekDataUpdateCoordinator

