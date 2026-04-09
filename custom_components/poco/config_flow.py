from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import DEFAULT_HOST, DOMAIN
from .coordinator import PocoCoordinator

_LOGGER = logging.getLogger(__name__)


class PocoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: (1) host, (2) switch selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = ""
        self._switches: dict[int, str] = {}  # {switch_id: display_label}

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input["host"].strip()
            coordinator = PocoCoordinator(self.hass, host)
            try:
                data = await coordinator.async_fetch_all()
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                await coordinator.async_shutdown()
                if not data:
                    errors["base"] = "no_switches"
                else:
                    await self.async_set_unique_id(host)
                    self._abort_if_unique_id_configured()
                    self._host = host
                    self._switches = {
                        sw_id: f"[{sw_id}] {sw.get('txt') or f'Switch {sw_id}'}"
                        for sw_id, sw in data.items()
                    }
                    return await self.async_step_switches()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("host", default=DEFAULT_HOST): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_switches(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get("switch_ids", [])
            if not selected:
                errors["base"] = "no_switches"
            else:
                return self.async_create_entry(
                    title=f"Poco ({self._host})",
                    data={
                        "host": self._host,
                        "switch_ids": [int(i) for i in selected],
                    },
                )

        options = [
            {"label": label, "value": str(sw_id)}
            for sw_id, label in self._switches.items()
        ]
        return self.async_show_form(
            step_id="switches",
            data_schema=vol.Schema(
                {
                    vol.Required("switch_ids"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )
