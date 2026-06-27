"""Config flow for Suntek LTE Camera."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SuntekApiError, SuntekCloudClient
from .const import (
    CONF_CLOUD_DEVICE_ID,
    CONF_DEVICE_ID,
    CONF_LOGIN,
    CONF_MEDIA_BACKUP_ENABLED,
    CONF_MEDIA_BACKUP_INCLUDE_VIDEOS,
    CONF_MEDIA_BACKUP_INTERVAL,
    CONF_MEDIA_BACKUP_LIMIT,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_P2P_API,
    CONF_P2P_DID,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_ADDR,
    CONF_WAKE_COOLDOWN,
    DEFAULT_MEDIA_BACKUP_INTERVAL,
    DEFAULT_MEDIA_BACKUP_LIMIT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVER_ADDR,
    DEFAULT_WAKE_COOLDOWN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SuntekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Suntek LTE Camera."""

    VERSION = 1

    def __init__(self) -> None:
        self._login = ""
        self._password = ""
        self._devices: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial sign-in step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            values = _clean_input(user_input)
            if not values.get(CONF_LOGIN):
                errors[CONF_LOGIN] = "required"
            if not values.get(CONF_PASSWORD):
                errors[CONF_PASSWORD] = "required"

            if not errors:
                self._login = values[CONF_LOGIN]
                self._password = values[CONF_PASSWORD]
                try:
                    self._devices = await self._async_discover_devices()
                except SuntekApiError as err:
                    _LOGGER.debug("Suntek device validation failed: %s", err)
                    errors["base"] = _flow_error_from_exception(err)
                else:
                    return await self.async_step_select_device()

        return self.async_show_form(
            step_id="user",
            data_schema=_login_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user pick the camera returned by the cloud."""
        if not self._login:
            return await self.async_step_user()

        device_options = _device_options(self._devices)
        if user_input is not None:
            device_id = str(user_input[CONF_DEVICE_ID]).strip()
            device = _device_by_id(self._devices, device_id)

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            title = _device_title(device)
            return self.async_create_entry(
                title=title,
                data={
                    CONF_LOGIN: self._login,
                    CONF_PASSWORD: self._password,
                    CONF_DEVICE_ID: device_id,
                    CONF_CLOUD_DEVICE_ID: device.get(CONF_CLOUD_DEVICE_ID, device_id),
                    CONF_P2P_DID: device.get(CONF_P2P_DID, device_id),
                    CONF_P2P_API: device.get(CONF_P2P_API, ""),
                    CONF_NAME: title,
                    CONF_SERVER_ADDR: device.get(CONF_SERVER_ADDR, DEFAULT_SERVER_ADDR),
                    CONF_WAKE_COOLDOWN: DEFAULT_WAKE_COOLDOWN,
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                },
            )

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICE_ID, default=next(iter(device_options))
                    ): vol.In(device_options)
                }
            ),
        )

    async def _async_discover_devices(self) -> list[dict[str, str]]:
        """Discover devices without blocking setup when the cloud is vague."""
        session = async_get_clientsession(self.hass)
        client = SuntekCloudClient(
            session=session,
            device_id=self._login,
            server_addr=DEFAULT_SERVER_ADDR,
            password=self._password,
        )
        devices = await client.async_discover_devices()
        return _normalise_devices(devices, self._login)

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SuntekOptionsFlow(config_entry)


class SuntekOptionsFlow(config_entries.OptionsFlow):
    """Handle Suntek options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_clean_input(user_input))

        values = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(values),
        )


def _login_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_LOGIN, default=values.get(CONF_LOGIN, "")): str,
            vol.Required(CONF_PASSWORD, default=values.get(CONF_PASSWORD, "")): str,
        }
    )


def _options_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_WAKE_COOLDOWN,
                default=values.get(CONF_WAKE_COOLDOWN, DEFAULT_WAKE_COOLDOWN),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10)),
            vol.Optional(
                CONF_MEDIA_BACKUP_ENABLED,
                default=values.get(CONF_MEDIA_BACKUP_ENABLED, False),
            ): bool,
            vol.Optional(
                CONF_MEDIA_BACKUP_INTERVAL,
                default=values.get(
                    CONF_MEDIA_BACKUP_INTERVAL, DEFAULT_MEDIA_BACKUP_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=15)),
            vol.Optional(
                CONF_MEDIA_BACKUP_LIMIT,
                default=values.get(CONF_MEDIA_BACKUP_LIMIT, DEFAULT_MEDIA_BACKUP_LIMIT),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
            vol.Optional(
                CONF_MEDIA_BACKUP_INCLUDE_VIDEOS,
                default=values.get(CONF_MEDIA_BACKUP_INCLUDE_VIDEOS, True),
            ): bool,
        }
    )


def _normalise_devices(
    devices: list[dict[str, str]], fallback_id: str
) -> list[dict[str, str]]:
    normalised: list[dict[str, str]] = []
    seen: set[str] = set()

    for device in devices:
        device_id = str(
            device.get(CONF_DEVICE_ID)
            or device.get("id")
            or device.get("imei")
            or fallback_id
        ).strip()
        if not device_id or device_id in seen:
            continue

        seen.add(device_id)
        name = str(device.get(CONF_NAME) or device_id).strip()
        cloud_device_id = str(
            device.get(CONF_CLOUD_DEVICE_ID)
            or device.get("cloud_id")
            or device.get("deviceid")
            or device_id
        ).strip()
        p2p_did = str(
            device.get(CONF_P2P_DID)
            or device.get(CONF_CLOUD_DEVICE_ID)
            or device.get("deviceid")
            or cloud_device_id
        ).strip()
        normalised.append(
            {
                CONF_DEVICE_ID: device_id,
                CONF_CLOUD_DEVICE_ID: cloud_device_id,
                CONF_P2P_DID: p2p_did,
                CONF_P2P_API: str(device.get(CONF_P2P_API) or "").strip(),
                CONF_NAME: name,
                CONF_SERVER_ADDR: str(
                    device.get(CONF_SERVER_ADDR) or DEFAULT_SERVER_ADDR
                ).strip(),
            }
        )

    if normalised:
        return normalised

    fallback_id = fallback_id.strip()
    return [
        {
            CONF_DEVICE_ID: fallback_id,
            CONF_CLOUD_DEVICE_ID: fallback_id,
            CONF_P2P_DID: fallback_id,
            CONF_P2P_API: "",
            CONF_NAME: fallback_id,
            CONF_SERVER_ADDR: DEFAULT_SERVER_ADDR,
        }
    ]


def _device_options(devices: list[dict[str, str]]) -> dict[str, str]:
    return {device[CONF_DEVICE_ID]: _device_label(device) for device in devices}


def _device_by_id(devices: list[dict[str, str]], device_id: str) -> dict[str, str]:
    for device in devices:
        if device[CONF_DEVICE_ID] == device_id:
            return device
    return {
        CONF_DEVICE_ID: device_id,
        CONF_NAME: device_id,
        CONF_SERVER_ADDR: DEFAULT_SERVER_ADDR,
    }


def _device_label(device: dict[str, str]) -> str:
    device_id = device[CONF_DEVICE_ID]
    name = device.get(CONF_NAME) or device_id
    return name if name == device_id else f"{name} ({device_id})"


def _device_title(device: dict[str, str]) -> str:
    return device.get(CONF_NAME) or device[CONF_DEVICE_ID]


def _clean_input(values: dict[str, Any]) -> dict[str, Any]:
    """Trim string inputs."""
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        cleaned[key] = value.strip() if isinstance(value, str) else value
    return cleaned


def _flow_error_from_exception(err: SuntekApiError) -> str:
    message = str(err).lower()
    if "illegal device" in message or "not found" in message:
        return "invalid_device"
    if "timeout" in message:
        return "cannot_connect"
    return "cannot_validate"
