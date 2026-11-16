"""Heizplan: Wochenpläne je Raum für Raumthermostate."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.typing import ConfigType

from .const import CONF_CLIMATE, DOMAIN, TITLE_SEP
from .room import HeizplanRoom
from .websocket import async_register_websocket

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket(hass)
    return True


def room_name(title: str) -> str:
    """Raumname ohne vorangestellte Etage ("DG · Bad" -> "Bad")."""
    return title.rsplit(TITLE_SEP, 1)[-1].strip()


def floor_name(hass: HomeAssistant, climate: str | None) -> str | None:
    """Etage des Thermostats: Thermostat -> Bereich -> Etage."""
    entity = er.async_get(hass).async_get(climate) if climate else None
    if entity is None:
        return None
    area_id = entity.area_id
    if not area_id and entity.device_id:
        device = dr.async_get(hass).async_get(entity.device_id)
        area_id = device.area_id if device else None
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    if area is None or not area.floor_id:
        return None
    floor = fr.async_get(hass).async_get_floor(area.floor_id)
    return floor.name if floor else None


def wanted_title(hass: HomeAssistant, entry: ConfigEntry) -> str:
    name = room_name(entry.title)
    floor = floor_name(hass, entry.data.get(CONF_CLIMATE))
    return f"{floor}{TITLE_SEP}{name}" if floor else name


@callback
def _sync_title(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Etage in den Titel schreiben, damit die Raumliste nach Etage sortiert ist."""
    title = wanted_title(hass, entry)
    if title != entry.title:
        hass.config_entries.async_update_entry(entry, title=title)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _sync_title(hass, entry)
    room = HeizplanRoom(hass, entry)
    await room.async_load()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = room
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await room.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    @callback
    def _registry_changed(event: Event) -> None:
        # Bereich oder Etage geändert: Titel nachziehen (lädt den Raum über den Update-Listener neu)
        _sync_title(hass, entry)

    for event_type in (
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
        ar.EVENT_AREA_REGISTRY_UPDATED,
        fr.EVENT_FLOOR_REGISTRY_UPDATED,
    ):
        entry.async_on_unload(hass.bus.async_listen(event_type, _registry_changed))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        room: HeizplanRoom = hass.data[DOMAIN].pop(entry.entry_id)
        await room.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await HeizplanRoom(hass, entry).async_remove()
