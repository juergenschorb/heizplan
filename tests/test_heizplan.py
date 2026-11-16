"""Tests für die Heizplan-Integration."""

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.heizplan.const import DOMAIN
from custom_components.heizplan.room import normalize_day

CLIMATE = "climate.wohnzimmer"
PRESETS = {"preset_modes": ["comfort", "eco", "frost"]}
WEEK = {
    d: [{"start": 0, "mode": "eco"}, {"start": 360, "mode": "comfort"}, {"start": 1320, "mode": "eco"}]
    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
}


def local(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=dt_util.DEFAULT_TIME_ZONE)


@pytest.fixture
def calls(hass: HomeAssistant):
    hass.states.async_set(CLIMATE, "heat", PRESETS)
    return {
        "preset": async_mock_service(hass, "climate", "set_preset_mode"),
        "temp": async_mock_service(hass, "climate", "set_temperature"),
    }


async def setup_room(hass: HomeAssistant, **data) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Wohnzimmer", data={"climate": CLIMATE, **data})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def room(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]


async def go(hass, freezer, when):
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


def test_normalize_day():
    assert normalize_day(
        [{"start": 600, "mode": "eco"}, {"start": 30, "mode": "comfort"}, {"start": 300, "mode": "comfort"}]
    ) == [{"start": 0, "mode": "comfort"}, {"start": 600, "mode": "eco"}]
    assert normalize_day([]) == []


async def test_switches_at_times(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 5, 0))  # Montag
    entry = await setup_room(hass)
    r = room(hass, entry)
    # ohne gespeicherten Plan: Grundmodus Eco
    assert calls["preset"][-1].data == {"entity_id": CLIMATE, "preset_mode": "eco"}
    await r.async_set_week("normal", WEEK)
    assert len(calls["preset"]) == 2 and calls["preset"][-1].data["preset_mode"] == "eco"

    await go(hass, freezer, local(2026, 11, 16, 5, 59))
    assert len(calls["preset"]) == 2  # kein Wechsel, kein Aufruf
    await go(hass, freezer, local(2026, 11, 16, 6, 0))
    assert calls["preset"][-1].data["preset_mode"] == "comfort"
    assert hass.states.get("sensor.heizplan_wohnzimmer").state == "comfort"
    # Wahl von Hand bleibt bis zum nächsten Wechsel stehen
    await go(hass, freezer, local(2026, 11, 16, 12, 0))
    assert len(calls["preset"]) == 3
    await go(hass, freezer, local(2026, 11, 16, 22, 0))
    assert calls["preset"][-1].data["preset_mode"] == "eco"
    st = hass.states.get("sensor.heizplan_wohnzimmer")
    assert st.state == "eco"
    assert st.attributes["next_mode"] == "comfort"
    assert dt_util.parse_datetime(st.attributes["next_change"]) == local(2026, 11, 17, 6, 0)


async def test_restart_catches_up(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 5, 0))
    entry = await setup_room(hass)
    await room(hass, entry).async_set_week("normal", WEEK)
    n = len(calls["preset"])
    # Neustart im selben Zeitraum: nichts setzen
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls["preset"]) == n
    # HA war beim Wechsel aus: nach dem Start nachholen
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.move_to(local(2026, 11, 16, 7, 30))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls["preset"]) == n + 1
    assert calls["preset"][-1].data["preset_mode"] == "comfort"


async def test_season_mode_and_vacation(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hass.states.async_set("input_boolean.heizperiode", "off")
    hass.states.async_set("input_select.heizmodus", "Heizen")
    entry = await setup_room(
        hass,
        season_entity="input_boolean.heizperiode",
        mode_entity="input_select.heizmodus",
        mode_heat="Heizen",
        mode_vacation="Urlaub",
    )
    r = room(hass, entry)
    assert r.plan_keys() == ["normal", "urlaub"]
    await r.async_set_week("normal", WEEK)
    await r.async_set_week("urlaub", {d: [{"start": 0, "mode": "frost"}] for d in WEEK})
    assert calls["preset"] == []
    assert hass.states.get("sensor.heizplan_wohnzimmer").state == "off"

    hass.states.async_set("input_boolean.heizperiode", "on")
    await hass.async_block_till_done()
    assert calls["preset"][-1].data["preset_mode"] == "comfort"
    hass.states.async_set("input_select.heizmodus", "Urlaub")
    await hass.async_block_till_done()
    assert calls["preset"][-1].data["preset_mode"] == "frost"
    assert hass.states.get("sensor.heizplan_wohnzimmer").attributes["active_plan"] == "urlaub"
    hass.states.async_set("input_select.heizmodus", "Aus")
    await hass.async_block_till_done()
    n = len(calls["preset"])
    assert hass.states.get("sensor.heizplan_wohnzimmer").state == "off"
    hass.states.async_set("input_select.heizmodus", "Heizen")
    await hass.async_block_till_done()
    assert len(calls["preset"]) == n + 1
    assert calls["preset"][-1].data["preset_mode"] == "comfort"


async def test_holiday(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))  # Montag
    hass.states.async_set("calendar.feiertage", "off")
    entry = await setup_room(hass, workday_entity="calendar.feiertage")
    r = room(hass, entry)
    week = dict(WEEK)
    week["sun"] = [{"start": 0, "mode": "eco"}]
    await r.async_set_week("normal", week)
    assert calls["preset"][-1].data["preset_mode"] == "comfort"
    # Feiertag ohne eigenen Plan: wie Sonntag
    hass.states.async_set("calendar.feiertage", "on")
    await hass.async_block_till_done()
    assert calls["preset"][-1].data["preset_mode"] == "eco"
    await r.async_set_week("normal", {"hol": [{"start": 0, "mode": "frost"}]})
    assert calls["preset"][-1].data["preset_mode"] == "frost"
    assert r.plans["normal"]["mon"] == WEEK["mon"]  # andere Tage bleiben


async def test_workday_sensor_is_inverted(hass: HomeAssistant, freezer, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hass.states.async_set("binary_sensor.workday", "off")
    entry = await setup_room(hass, workday_entity="binary_sensor.workday")
    assert room(hass, entry).is_holiday()


async def test_override(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 5, 30))
    entry = await setup_room(hass)
    r = room(hass, entry)
    await r.async_set_week("normal", WEEK)
    n = len(calls["preset"])
    await r.async_set_override(23.5, local(2026, 11, 16, 7, 0))
    assert calls["temp"][-1].data == {"entity_id": CLIMATE, "temperature": 23.5}
    assert hass.states.get("sensor.heizplan_wohnzimmer").state == "manual"
    await go(hass, freezer, local(2026, 11, 16, 6, 0))
    assert len(calls["preset"]) == n  # Plan pausiert
    # übersteht einen Neustart
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert room(hass, entry).override is not None
    await go(hass, freezer, local(2026, 11, 16, 7, 0))
    assert room(hass, entry).override is None
    assert len(calls["preset"]) == n + 1
    assert calls["preset"][-1].data["preset_mode"] == "comfort"

    # Abbrechen ohne Plan anzuwenden (Preset wurde von Hand gewählt)
    r = room(hass, entry)
    await r.async_set_override(18, local(2026, 11, 16, 9, 0))
    await r.async_cancel_override(apply=False)
    assert len(calls["preset"]) == n + 1
    await go(hass, freezer, local(2026, 11, 16, 7, 5))
    assert len(calls["preset"]) == n + 1


async def test_unavailable_thermostat_is_retried(hass: HomeAssistant, freezer, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hass.states.async_set(CLIMATE, "unavailable")
    await setup_room(hass)
    assert calls["preset"] == []
    hass.states.async_set(CLIMATE, "heat", PRESETS)
    await hass.async_block_till_done()
    assert calls["preset"][-1].data["preset_mode"] == "eco"


async def test_frost_maps_to_away(hass: HomeAssistant, freezer, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hass.states.async_set(CLIMATE, "heat", {"preset_modes": ["comfort", "eco", "away"]})
    await setup_room(hass, default_mode="frost")
    assert calls["preset"][-1].data["preset_mode"] == "away"


async def test_change_thermostat_keeps_plan(hass: HomeAssistant, freezer, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hass.states.async_set("climate.neu", "heat", PRESETS)
    entry = await setup_room(hass)
    await room(hass, entry).async_set_week("normal", WEEK)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"climate": "climate.neu", "default_mode": "eco"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    r = room(hass, entry)
    assert r.climate == "climate.neu"
    assert r.plans["normal"] == WEEK
    assert calls["preset"][-1].data == {"entity_id": "climate.neu", "preset_mode": "comfort"}


async def test_config_flow(hass: HomeAssistant, calls):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Bad", "climate": CLIMATE, "default_mode": "eco"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bad"
    await hass.async_block_till_done()
    # zweiter Raum mit demselben Thermostat wird abgelehnt
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Bad 2", "climate": CLIMATE, "default_mode": "eco"}
    )
    assert result["errors"] == {"climate": "climate_in_use"}


async def test_websocket(hass: HomeAssistant, hass_ws_client, calls):
    # ohne eingefrorene Zeit: das Anmelde-Token des Test-Clients wäre sonst abgelaufen
    hass.states.async_set("climate.bad", "heat", PRESETS)
    entry = await setup_room(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "heizplan/rooms"})
    msg = await client.receive_json()
    assert msg["success"]
    (data,) = msg["result"]
    assert data["climate"] == CLIMATE and data["sensor"] == "sensor.heizplan_wohnzimmer"

    await client.send_json_auto_id(
        {"type": "heizplan/set_week", "entry_id": entry.entry_id, "plan": "normal", "week": WEEK}
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["plans"]["normal"]["mon"] == WEEK["mon"]
    assert calls["preset"][-1].data["preset_mode"] in ("comfort", "eco")

    until = (dt_util.now() + timedelta(hours=2)).isoformat()
    await client.send_json_auto_id(
        {"type": "heizplan/override", "entry_id": entry.entry_id, "temperature": 22, "until": until}
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["override"]["temperature"] == 22
    await client.send_json_auto_id({"type": "heizplan/cancel_override", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["override"] is None

    # Übernahme aus der Karte legt einen Raum mit Plänen an
    await client.send_json_auto_id(
        {
            "type": "heizplan/import",
            "name": "Bad",
            "climate": "climate.bad",
            "options": {"default_mode": "frost", "season_entity": "", "unbekannt": 1},
            "plans": {"normal": {d: [{"start": 0, "mode": "comfort"}] for d in WEEK}},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["name"] == "Bad" and msg["result"]["default_mode"] == "frost"
    assert msg["result"]["plans"]["normal"]["mon"] == [{"start": 0, "mode": "comfort"}]
    assert calls["preset"][-1].data == {"entity_id": "climate.bad", "preset_mode": "comfort"}
    await client.send_json_auto_id(
        {"type": "heizplan/import", "name": "Bad", "climate": "climate.bad"}
    )
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "exists"


async def test_remove_entry_deletes_storage(hass: HomeAssistant, hass_storage, freezer, calls):
    entry = await setup_room(hass)
    await room(hass, entry).async_set_week("normal", WEEK)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"heizplan.{entry.entry_id}" not in hass_storage


async def test_off_when_inactive(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    attrs = {**PRESETS, "hvac_modes": ["off", "heat"]}
    hass.states.async_set(CLIMATE, "heat", attrs)
    hass.states.async_set("input_boolean.heizperiode", "on")
    entry = await setup_room(hass, season_entity="input_boolean.heizperiode", off_when_inactive=True)
    assert hvac == [] and len(calls["preset"]) == 1

    hass.states.async_set("input_boolean.heizperiode", "off")
    await hass.async_block_till_done()
    assert hvac[-1].data == {"entity_id": CLIMATE, "hvac_mode": "off"}
    hass.states.async_set(CLIMATE, "off", attrs)
    # nur einmal ausschalten, auch über Minuten und einen Neustart hinweg
    await go(hass, freezer, local(2026, 11, 16, 8, 5))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(hvac) == 1

    hass.states.async_set("input_boolean.heizperiode", "on")
    await hass.async_block_till_done()
    assert hvac[-1].data == {"entity_id": CLIMATE, "hvac_mode": "heat"}
    assert len(calls["preset"]) == 2 and calls["preset"][-1].data["preset_mode"] == "eco"


async def test_inactive_without_option_leaves_thermostat(hass: HomeAssistant, freezer, calls):
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set("input_boolean.heizperiode", "off")
    await setup_room(hass, season_entity="input_boolean.heizperiode")
    assert hvac == [] and calls["preset"] == []


async def test_unknown_conditions_do_nothing(hass: HomeAssistant, freezer, calls):
    """Kurz nach dem Start fehlt der Zustand der Heizperiode: nicht ausschalten."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set(CLIMATE, "heat", {**PRESETS, "hvac_modes": ["off", "heat"]})
    await setup_room(hass, season_entity="input_boolean.heizperiode", off_when_inactive=True)
    assert hvac == [] and calls["preset"] == []
    hass.states.async_set("input_boolean.heizperiode", "unavailable")
    await hass.async_block_till_done()
    assert hvac == [] and calls["preset"] == []
    hass.states.async_set("input_boolean.heizperiode", "on")
    await hass.async_block_till_done()
    assert hvac == [] and len(calls["preset"]) == 1


async def test_turned_off_is_restored_after_option_removed(hass: HomeAssistant, freezer, calls):
    """Hat die Integration ausgeschaltet, schaltet sie wieder ein, auch ohne die Option."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 8, 0))
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    attrs = {**PRESETS, "hvac_modes": ["off", "heat"]}
    hass.states.async_set(CLIMATE, "heat", attrs)
    hass.states.async_set("input_boolean.heizperiode", "off")
    entry = await setup_room(hass, season_entity="input_boolean.heizperiode", off_when_inactive=True)
    assert hvac[-1].data["hvac_mode"] == "off"
    hass.states.async_set(CLIMATE, "off", attrs)
    hass.config_entries.async_update_entry(
        entry, data={"climate": CLIMATE, "season_entity": "input_boolean.heizperiode"}
    )
    await hass.async_block_till_done()
    hass.states.async_set("input_boolean.heizperiode", "on")
    await hass.async_block_till_done()
    assert hvac[-1].data["hvac_mode"] == "heat"
    assert calls["preset"][-1].data["preset_mode"] == "eco"


async def test_option_turns_on_at_change(hass: HomeAssistant, freezer: FrozenDateTimeFactory, calls):
    """Mit der Option gehört Ein/Aus der Integration: beim Wechsel wieder einschalten."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 5, 0))
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set(CLIMATE, "off", {**PRESETS, "hvac_modes": ["off", "heat"]})
    await setup_room(hass, off_when_inactive=True)
    assert hvac[-1].data == {"entity_id": CLIMATE, "hvac_mode": "heat"}


async def test_without_option_manual_off_stays(hass: HomeAssistant, freezer, calls):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(2026, 11, 16, 5, 0))
    hvac = async_mock_service(hass, "climate", "set_hvac_mode")
    hass.states.async_set(CLIMATE, "off", {**PRESETS, "hvac_modes": ["off", "heat"]})
    await setup_room(hass)
    assert hvac == [] and len(calls["preset"]) == 1
