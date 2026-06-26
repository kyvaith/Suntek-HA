"""Config flow for Suntek LTE Camera."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    CONF_DEVICE_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_ADDR,
    CONF_STILL_IMAGE_URL_TEMPLATE,
    CONF_STREAM_URL_TEMPLATE,
    CONF_WAKE_BEFORE_STREAM,
    CONF_WAKE_COOLDOWN,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVER_ADDR,
    DEFAULT_WAKE_COOLDOWN,
    DOMAIN,
)


class SuntekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Suntek LTE Camera."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = _clean_input(user_input)
            if not user_input[CONF_DEVICE_ID]:
                errors[CONF_DEVICE_ID] = "required"
            else:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                title = user_input.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

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
            data_schema=_schema(values, options_only=True),
        )


def _schema(
    values: dict[str, Any], *, options_only: bool = False
) -> vol.Schema:
    """Return the setup/options schema."""
    fields: dict[Any, Any] = {}
    if not options_only:
        fields[vol.Required(CONF_DEVICE_ID, default=values.get(CONF_DEVICE_ID, ""))] = str
        fields[vol.Optional(CONF_NAME, default=values.get(CONF_NAME, DEFAULT_NAME))] = str

    fields.update(
        {
            vol.Optional(
                CONF_PASSWORD, default=values.get(CONF_PASSWORD, "")
            ): str,
            vol.Optional(
                CONF_SERVER_ADDR,
                default=values.get(CONF_SERVER_ADDR, DEFAULT_SERVER_ADDR),
            ): str,
            vol.Optional(
                CONF_STREAM_URL_TEMPLATE,
                default=values.get(CONF_STREAM_URL_TEMPLATE, ""),
            ): str,
            vol.Optional(
                CONF_STILL_IMAGE_URL_TEMPLATE,
                default=values.get(CONF_STILL_IMAGE_URL_TEMPLATE, ""),
            ): str,
            vol.Optional(
                CONF_WAKE_BEFORE_STREAM,
                default=values.get(CONF_WAKE_BEFORE_STREAM, True),
            ): bool,
            vol.Optional(
                CONF_WAKE_COOLDOWN,
                default=values.get(CONF_WAKE_COOLDOWN, DEFAULT_WAKE_COOLDOWN),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10)),
        }
    )
    return vol.Schema(fields)


def _clean_input(values: dict[str, Any]) -> dict[str, Any]:
    """Trim string inputs."""
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        cleaned[key] = value.strip() if isinstance(value, str) else value
    return cleaned

