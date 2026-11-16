"""WebSocket-Befehle für die Heizplan Card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import CONF_CLIMATE, DOMAIN, OPTION_KEYS
from .room import HeizplanRoom

DAY_SCHEMA = vol.All(
    cv.ensure_list,
    [
        vol.Schema(
            {
                vol.Required("start"): vol.All(vol.Coerce(int), vol.Range(min=0, max=1439)),
                vol.Required("mode"): cv.string,
            }
        )
    ],
)
WEEK_SCHEMA = vol.Schema({cv.string: DAY_SCHEMA})


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_rooms)
    websocket_api.async_register_command(hass, ws_set_week)
    websocket_api.async_register_command(hass, ws_override)
    websocket_api.async_register_command(hass, ws_cancel_override)
    websocket_api.async_register_command(hass, ws_import)


def _room_dict(hass: HomeAssistant, room: HeizplanRoom) -> dict[str, Any]:
    data = room.as_dict()
    data["sensor"] = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, room.entry.entry_id
    )
    return data


def _room(hass: HomeAssistant, connection, msg) -> HeizplanRoom | None:
    room = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if room is None:
        connection.send_error(msg["id"], "not_found", "Raum nicht gefunden")
    return room


@websocket_api.websocket_command({vol.Required("type"): "heizplan/rooms"})
@callback
def ws_rooms(hass: HomeAssistant, connection, msg) -> None:
    rooms = hass.data.get(DOMAIN, {}).values()
    connection.send_result(msg["id"], [_room_dict(hass, room) for room in rooms])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heizplan/set_week",
        vol.Required("entry_id"): cv.string,
        vol.Required("plan"): cv.string,
        vol.Required("week"): WEEK_SCHEMA,
    }
)
@websocket_api.async_response
async def ws_set_week(hass: HomeAssistant, connection, msg) -> None:
    if (room := _room(hass, connection, msg)) is None:
        return
    try:
        await room.async_set_week(msg["plan"], msg["week"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], _room_dict(hass, room))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heizplan/override",
        vol.Required("entry_id"): cv.string,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Required("until"): cv.datetime,
    }
)
@websocket_api.async_response
async def ws_override(hass: HomeAssistant, connection, msg) -> None:
    if (room := _room(hass, connection, msg)) is None:
        return
    try:
        await room.async_set_override(msg["temperature"], msg["until"])
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], _room_dict(hass, room))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heizplan/cancel_override",
        vol.Required("entry_id"): cv.string,
        vol.Optional("apply", default=True): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_cancel_override(hass: HomeAssistant, connection, msg) -> None:
    if (room := _room(hass, connection, msg)) is None:
        return
    await room.async_cancel_override(msg["apply"])
    connection.send_result(msg["id"], _room_dict(hass, room))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "heizplan/import",
        vol.Required("name"): cv.string,
        vol.Required(CONF_CLIMATE): cv.entity_id,
        vol.Optional("options", default=dict): dict,
        vol.Optional("plans", default=dict): vol.Schema({cv.string: WEEK_SCHEMA}),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_import(hass: HomeAssistant, connection, msg) -> None:
    """Raum aus der Karte anlegen (Übernahme aus dem Scheduler)."""
    rooms = hass.data.get(DOMAIN, {})
    if any(room.climate == msg[CONF_CLIMATE] for room in rooms.values()):
        connection.send_error(msg["id"], "exists", "Für dieses Thermostat gibt es schon einen Raum")
        return
    data = {k: v for k, v in msg["options"].items() if k in OPTION_KEYS and v}
    data[CONF_CLIMATE] = msg[CONF_CLIMATE]
    data["name"] = msg["name"]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    entry = result.get("result")
    room = rooms.get(entry.entry_id) if entry else None
    if room is None:
        connection.send_error(msg["id"], "failed", "Raum konnte nicht angelegt werden")
        return
    for plan, week in msg["plans"].items():
        await room.async_set_week(plan, week)
    connection.send_result(msg["id"], _room_dict(hass, room))
