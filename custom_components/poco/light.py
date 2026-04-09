from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PocoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PocoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PocoLight(coordinator, sw_id)
        for sw_id in entry.data["switch_ids"]
        if sw_id in (coordinator.data or {})
    )


class PocoLight(CoordinatorEntity[PocoCoordinator], LightEntity):
    """A Poco external switch exposed as a Home Assistant light entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PocoCoordinator, switch_id: int) -> None:
        super().__init__(coordinator)
        self._switch_id = switch_id
        sw = coordinator.data[switch_id]

        self._attr_unique_id = f"{coordinator.host}_{switch_id}"
        self._attr_name = sw.get("txt") or f"Switch {switch_id}"

        # Strip trailing ".local" so device name reads "Poco poco-9837" not "Poco poco-9837.local".
        host_label = coordinator.host.removesuffix(".local")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.host)},
            "name": f"Poco {host_label}",
            "manufacturer": "Lumitec",
            "model": "Poco",
        }

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    @property
    def _sw(self) -> dict:
        """Latest switch data from the coordinator."""
        return (self.coordinator.data or {}).get(self._switch_id, {})

    # ------------------------------------------------------------------
    # Color mode
    # ------------------------------------------------------------------

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        # A switch that has never reported a hue value (sentinel -1) is
        # assumed brightness-only.
        if self._sw.get("hue", -1) >= 0:
            return {ColorMode.HS}
        return {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        return next(iter(self.supported_color_modes))

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool | None:
        if not self._sw:
            return None
        return self._sw.get("state", 0) != 0

    @property
    def brightness(self) -> int | None:
        b = self._sw.get("bright", -1)
        return b if b >= 0 else None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        h = self._sw.get("hue", -1)
        s = self._sw.get("sat", -1)
        if h >= 0 and s >= 0:
            # Poco scale: hue 0-255, sat 0-255 → HA: hue 0-360°, sat 0-100%
            return (round(h * 360 / 255, 1), round(s * 100 / 255, 1))
        return None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        hs = kwargs.get(ATTR_HS_COLOR)
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        if hs is not None:
            # HA hue 0-360° → Poco 0-255; HA sat 0-100% → Poco 0-255
            poco_hue = round(hs[0] * 255 / 360)
            poco_sat = round(hs[1] * 255 / 100)
            if brightness is not None:
                poco_bright = int(brightness)
            else:
                # Reuse current brightness; fall back to full brightness.
                cur = self._sw.get("bright", -1)
                poco_bright = cur if cur > 0 else 255
            await self.coordinator.async_send_action(
                self._switch_id,
                8,  # ACT_T2HSB
                hue=poco_hue,
                sat=poco_sat,
                bright=poco_bright,
            )
        elif brightness is not None:
            await self.coordinator.async_send_action(
                self._switch_id,
                10,  # ACT_T2B
                bright=int(brightness),
            )
        else:
            await self.coordinator.async_send_action(self._switch_id, 2)  # ACT_ON

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_action(self._switch_id, 1)  # ACT_OFF
