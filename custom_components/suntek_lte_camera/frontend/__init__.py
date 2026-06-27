"""Frontend helpers for Suntek LTE Camera."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent
FRONTEND_URL = f"/{DOMAIN}/frontend"
FRONTEND_CARD = "suntek-camera-card.js"
FRONTEND_VERSION = "0.4.1"
FRONTEND_CARD_URL = f"{FRONTEND_URL}/{FRONTEND_CARD}?v={FRONTEND_VERSION}"
MAX_RESOURCE_REGISTRATION_ATTEMPTS = 12


class SuntekFrontend:
    """Register the Suntek dashboard card."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._attempts = 0

    async def async_register(self) -> None:
        """Register static files and Lovelace resources."""
        await self._async_register_static_path()
        await self._async_register_lovelace_resource()

    async def _async_register_static_path(self) -> None:
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(FRONTEND_URL, str(FRONTEND_DIR), True)]
            )
        except RuntimeError as err:
            _LOGGER.debug("Suntek frontend static path already registered: %s", err)

    async def _async_register_lovelace_resource(self) -> None:
        lovelace = self.hass.data.get("lovelace")
        if lovelace is None:
            self._retry_resource_registration("Lovelace is not ready")
            return

        if getattr(lovelace, "mode", None) != "storage":
            _LOGGER.debug("Suntek card resource auto-registration needs storage mode")
            return

        resources = getattr(lovelace, "resources", None)
        if resources is None:
            self._retry_resource_registration("Lovelace resources are not ready")
            return

        if not getattr(resources, "loaded", True):
            await resources.async_load()

        existing = self._existing_resource(resources)
        if existing is None:
            await self._async_create_resource(resources)
            return

        if existing.get("url") != FRONTEND_CARD_URL:
            await self._async_update_resource(resources, existing)

    def _existing_resource(self, resources) -> dict | None:
        card_path = FRONTEND_CARD_URL.split("?", 1)[0]
        for item in resources.async_items():
            if item.get("url", "").split("?", 1)[0] == card_path:
                return item
        return None

    async def _async_create_resource(self, resources) -> None:
        try:
            await resources.async_create_item(
                {
                    "res_type": "module",
                    "url": FRONTEND_CARD_URL,
                }
            )
        except ValueError as err:
            _LOGGER.debug("Suntek card resource was not added: %s", err)

    async def _async_update_resource(self, resources, existing: dict) -> None:
        item_id = existing.get("id")
        if item_id is None:
            _LOGGER.debug("Suntek card resource has no editable id")
            return

        try:
            await resources.async_update_item(
                item_id,
                {
                    "res_type": "module",
                    "url": FRONTEND_CARD_URL,
                },
            )
        except (AttributeError, TypeError, ValueError) as err:
            _LOGGER.debug("Suntek card resource was not updated: %s", err)

    def _retry_resource_registration(self, reason: str) -> None:
        self._attempts += 1
        if self._attempts > MAX_RESOURCE_REGISTRATION_ATTEMPTS:
            _LOGGER.debug("%s; giving up", reason)
            return

        _LOGGER.debug("%s; retrying", reason)
        async_call_later(
            self.hass,
            5,
            lambda _now: self.hass.async_create_task(
                self._async_register_lovelace_resource()
            ),
        )
