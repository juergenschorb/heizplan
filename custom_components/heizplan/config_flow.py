"""Einrichtung: ein Eintrag je Raum."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE,
    CONF_DEFAULT_MODE,
    CONF_MODE_ENTITY,
    CONF_MODE_HEAT,
    CONF_MODE_VACATION,
    CONF_OFF_INACTIVE,
    CONF_SEASON,
    CONF_WORKDAY,
    DEFAULT_MODE,
    DOMAIN,
    MODES,
    OPTION_KEYS,
)

CONF_NAME = "name"


def _schema(with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME)] = selector.TextSelector()
    fields.update(
        {
            vol.Required(CONF_CLIMATE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Required(CONF_DEFAULT_MODE, default=DEFAULT_MODE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(MODES),
                    translation_key="mode",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_SEASON): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["input_boolean", "binary_sensor", "switch"]
                )
            ),
            vol.Optional(CONF_MODE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["input_select", "select"])
            ),
            vol.Optional(CONF_MODE_HEAT): selector.TextSelector(),
            vol.Optional(CONF_MODE_VACATION): selector.TextSelector(),
            vol.Optional(CONF_OFF_INACTIVE, default=False): selector.BooleanSelector(),
            vol.Optional(CONF_WORKDAY): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["calendar", "binary_sensor", "input_boolean"]
                )
            ),
        }
    )
    return vol.Schema(fields)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in user_input.items() if k in OPTION_KEYS and v not in ("", None)}


class HeizplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Raum anlegen."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeizplanOptionsFlow()

    def _climate_in_use(self, climate: str) -> bool:
        return any(
            entry.data.get(CONF_CLIMATE) == climate
            for entry in self._async_current_entries()
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._climate_in_use(user_input[CONF_CLIMATE]):
                errors[CONF_CLIMATE] = "climate_in_use"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip(), data=_clean(user_input)
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_schema(True), user_input or {}),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        if self._climate_in_use(import_data[CONF_CLIMATE]):
            return self.async_abort(reason="climate_in_use")
        return self.async_create_entry(
            title=str(import_data[CONF_NAME]).strip(), data=_clean(import_data)
        )


class HeizplanOptionsFlow(OptionsFlow):
    """Thermostat und Bedingungen eines Raums ändern."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        if user_input is not None:
            in_use = any(
                other.entry_id != entry.entry_id
                and other.data.get(CONF_CLIMATE) == user_input[CONF_CLIMATE]
                for other in self.hass.config_entries.async_entries(DOMAIN)
            )
            if in_use:
                errors[CONF_CLIMATE] = "climate_in_use"
            else:
                self.hass.config_entries.async_update_entry(entry, data=_clean(user_input))
                return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _schema(False), user_input or dict(entry.data)
            ),
            errors=errors,
        )
