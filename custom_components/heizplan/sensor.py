"""Sensor je Raum: Modus laut Plan."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CLIMATE, DOMAIN
from .room import HeizplanRoom


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([HeizplanSensor(hass.data[DOMAIN][entry.entry_id])])


class HeizplanSensor(SensorEntity):
    """Aktueller Modus des Plans (comfort / eco / frost / off / manual)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_translation_key = "plan"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, room: HeizplanRoom) -> None:
        self._room = room
        self._attr_unique_id = room.entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.entry.entry_id)},
            name=f"Heizplan {room.name}",
            manufacturer="Heizplan",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._room.add_listener(self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._room.state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._room.as_dict()
        return {
            "entry_id": data["entry_id"],
            CONF_CLIMATE: data[CONF_CLIMATE],
            "active_plan": data["active_plan"],
            "next_change": data["next_change"],
            "next_mode": data["next_mode"],
            "override_until": (data["override"] or {}).get("until"),
            "revision": data["revision"],
        }
