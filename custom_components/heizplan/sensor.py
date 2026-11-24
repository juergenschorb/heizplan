"""Sensor je Raum: Modus laut Plan."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature
from homeassistant.util import dt as dt_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CLIMATE, DAYS, DOMAIN
from .room import HeizplanRoom


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [HeizplanSensor(room), HeizplanTodaySensor(room), HeizplanNextChangeSensor(room), HeizplanTargetSensor(room)]
    )


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
            "holiday": data["holiday"],
            "next_change": data["next_change"],
            "next_mode": data["next_mode"],
            "override_until": (data["override"] or {}).get("until"),
            "revision": data["revision"],
        }


DAY_NAMES = {"mon": "Mo", "tue": "Di", "wed": "Mi", "thu": "Do", "fri": "Fr", "sat": "Sa", "sun": "So"}


class _HeizplanBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, room: HeizplanRoom, key: str) -> None:
        self._room = room
        self._attr_translation_key = key
        self._attr_unique_id = f"{room.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, room.entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._room.add_listener(self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()


class HeizplanTodaySensor(_HeizplanBase):
    """Plan von heute als Text, die ganze Woche in den Attributen."""

    _attr_icon = "mdi:format-list-bulleted-square"

    def __init__(self, room: HeizplanRoom) -> None:
        super().__init__(room, "today")

    @property
    def native_value(self) -> str | None:
        plan = self._room.active_plan()
        if plan is None:
            return None
        text = self._room.day_text(plan, self._room.day_key(dt_util.now()))
        return text[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"plan": self._room.active_plan()}
        for plan in self._room.plan_keys():
            for day in DAYS:
                attrs[f"{plan}_{DAY_NAMES[day]}"] = self._room.day_text(plan, day)
        return attrs


class HeizplanNextChangeSensor(_HeizplanBase):
    """Zeitpunkt des nächsten Moduswechsels."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, room: HeizplanRoom) -> None:
        super().__init__(room, "next_change")

    @property
    def native_value(self):
        plan = self._room.active_plan()
        change = self._room.next_change(plan, dt_util.now()) if plan else None
        return change[0] if change else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = self._room.active_plan()
        change = self._room.next_change(plan, dt_util.now()) if plan else None
        return {"next_mode": change[1]} if change else None


class HeizplanTargetSensor(_HeizplanBase):
    """Solltemperatur, die der aktuelle Modus am Thermostat bedeutet."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, room: HeizplanRoom) -> None:
        super().__init__(room, "target")

    @property
    def native_value(self) -> float | None:
        mode = self._room.state()
        if mode in ("comfort", "eco", "frost"):
            return self._room.preset_temperature(mode)
        return None
