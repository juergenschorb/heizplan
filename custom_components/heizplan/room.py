"""Ein Raum: Wochenpläne, aktiver Plan, Schalten des Thermostats."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIMATE,
    CONF_DEFAULT_MODE,
    CONF_MODE_ENTITY,
    CONF_MODE_HEAT,
    CONF_MODE_VACATION,
    CONF_OFF_INACTIVE,
    CONF_PRESENCE,
    CONF_PRESENCE_AWAY,
    CONF_PRESENCE_HOME,
    CONF_SEASON,
    CONF_WORKDAY,
    DAY_MIN,
    DAYS,
    DEFAULT_MODE,
    DOMAIN,
    HOL,
    PLAN_NORMAL,
    PLAN_VACATION,
    STATE_MANUAL,
    STATE_OFF,
    STORAGE_VERSION,
    WORKDAYS,
)

_LOGGER = logging.getLogger(__name__)

STEP = 15
OFF_MARKER = "__inactive__"
OLD_OFF_MARKER = "__off__"


def normalize_day(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sortieren, bei 0 beginnen, gleiche Nachbarn zusammenfassen."""
    items = sorted(
        (
            {
                "start": max(0, min(DAY_MIN - STEP, int(e["start"]))),
                "mode": str(e["mode"]),
            }
            for e in entries
        ),
        key=lambda e: e["start"],
    )
    if not items:
        return []
    items[0]["start"] = 0
    out: list[dict[str, Any]] = []
    for e in items:
        if out and out[-1]["start"] == e["start"]:
            out[-1]["mode"] = e["mode"]
            continue
        if out and out[-1]["mode"] == e["mode"]:
            continue
        out.append(e)
    # nach dem Ersetzen können wieder gleiche Nachbarn entstehen
    merged: list[dict[str, Any]] = []
    for e in out:
        if merged and merged[-1]["mode"] == e["mode"]:
            continue
        merged.append(e)
    return merged


class HeizplanRoom:
    """Hält die Pläne eines Raums und schaltet das Thermostat."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.plans: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.override: dict[str, Any] | None = None
        self._last: list[Any] | None = None
        # True, solange diese Integration das Thermostat ausgeschaltet hat
        self._turned_off = False
        self.revision = 0
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._lock = asyncio.Lock()

    # ---------- Konfiguration ----------
    def conf(self, key: str) -> Any:
        value = self.entry.data.get(key)
        return value if value not in ("", None) else None

    @property
    def name(self) -> str:
        return self.entry.title

    @property
    def climate(self) -> str:
        return self.entry.data[CONF_CLIMATE]

    @property
    def default_mode(self) -> str:
        return self.conf(CONF_DEFAULT_MODE) or DEFAULT_MODE

    def plan_keys(self) -> list[str]:
        keys = [PLAN_NORMAL]
        if (self.conf(CONF_MODE_ENTITY) and self.conf(CONF_MODE_VACATION)) or (
            self.conf(CONF_PRESENCE) and self.conf(CONF_PRESENCE_AWAY)
        ):
            keys.append(PLAN_VACATION)
        return keys

    # ---------- Laden, Starten, Stoppen ----------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.plans = data.get("plans") or {}
        self.override = data.get("override")
        self._last = data.get("last")
        self._turned_off = bool(data.get("turned_off"))
        if self._last and self._last[-1] == OLD_OFF_MARKER:  # Stand aus 0.2.0–0.2.2
            self._turned_off = True
            self._last = None

    def _data(self) -> dict[str, Any]:
        return {
            "plans": self.plans,
            "override": self.override,
            "last": self._last,
            "turned_off": self._turned_off,
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._data, 1)

    async def async_start(self) -> None:
        self._unsubs.append(async_track_time_change(self.hass, self._tick, second=0))
        watched = [
            e
            for e in (
                self.conf(CONF_SEASON),
                self.conf(CONF_MODE_ENTITY),
                self.conf(CONF_WORKDAY),
                self.conf(CONF_PRESENCE),
            )
            if e
        ]
        if watched:
            self._unsubs.append(
                async_track_state_change_event(self.hass, watched, self._changed)
            )
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.climate], self._climate_changed
            )
        )
        await self.async_evaluate()

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        await self._store.async_remove()

    @callback
    def add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def _tick(self, now: datetime) -> None:
        await self.async_evaluate()

    async def _changed(self, event: Event) -> None:
        await self.async_evaluate()

    async def _climate_changed(self, event: Event) -> None:
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        gone = (None, STATE_UNAVAILABLE, STATE_UNKNOWN)
        was_gone = old is None or old.state in gone
        if was_gone and new is not None and new.state not in gone:
            await self.async_evaluate()

    # ---------- Plan ----------
    def _state(self, entity_id: str | None) -> str | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    def conditions_ready(self) -> bool:
        """Heizperiode und Heizmodus haben einen Zustand (nicht kurz nach dem Start)."""
        for entity_id in (
            self.conf(CONF_SEASON),
            self.conf(CONF_MODE_ENTITY),
            self.conf(CONF_PRESENCE),
        ):
            if entity_id and self._state(entity_id) in (
                None,
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                return False
        return True

    def active_plan(self) -> str | None:
        """Plan, der gerade gilt, oder None (Heizung aus / außerhalb Heizperiode)."""
        season = self.conf(CONF_SEASON)
        if season and self._state(season) != "on":
            return None
        mode_entity = self.conf(CONF_MODE_ENTITY)
        if mode_entity:
            current = self._state(mode_entity)
            vacation = self.conf(CONF_MODE_VACATION)
            if vacation and current == vacation:
                return PLAN_VACATION
            heat = self.conf(CONF_MODE_HEAT)
            if heat and current != heat:
                return None
        # Heizung läuft: bei Abwesenheit gilt der Urlaubs-/Abwesend-Plan
        away = self.conf(CONF_PRESENCE_AWAY)
        if away and self._state(self.conf(CONF_PRESENCE)) == away:
            return PLAN_VACATION
        return PLAN_NORMAL

    def is_holiday(self) -> bool:
        """Feiertag heute: Kalender "on", Arbeitstag-Sensor "off" oder Urlaub zuhause."""
        home = self.conf(CONF_PRESENCE_HOME)
        if home and self._state(self.conf(CONF_PRESENCE)) == home:
            return True
        workday = self.conf(CONF_WORKDAY)
        if not workday:
            return False
        state = self._state(workday)
        return state == ("on" if workday.startswith("calendar.") else "off")

    def day_key(self, when: datetime, now: datetime | None = None) -> str:
        now = now or dt_util.now()
        key = DAYS[when.weekday()]
        if key in WORKDAYS and when.date() == now.date() and self.is_holiday():
            return HOL
        return key

    def entries(self, plan: str, day: str) -> list[dict[str, Any]]:
        if day == HOL:  # ein Feiertag läuft immer wie der Sonntag
            day = "sun"
        found = self.plans.get(plan, {}).get(day)
        if found:
            return found
        return [{"start": 0, "mode": self.default_mode}]

    def slot_at(self, plan: str, when: datetime, now: datetime | None = None) -> dict[str, Any]:
        entries = self.entries(plan, self.day_key(when, now))
        minute = when.hour * 60 + when.minute
        current = entries[0]
        for entry in entries:
            if entry["start"] <= minute:
                current = entry
        return current

    def next_change(self, plan: str, now: datetime) -> tuple[datetime, str] | None:
        """Nächster Zeitpunkt, zu dem der Plan den Modus wechselt."""
        mode = self.slot_at(plan, now)["mode"]
        minute = now.hour * 60 + now.minute
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for offset in range(8):
            day = midnight + timedelta(days=offset)
            for entry in self.entries(plan, self.day_key(day, now)):
                if offset == 0 and entry["start"] <= minute:
                    continue
                if entry["mode"] != mode:
                    return day + timedelta(minutes=entry["start"]), entry["mode"]
        return None

    def preset_for(self, mode: str) -> str:
        """Better Thermostat kennt kein "frost": dann "away"."""
        state = self.hass.states.get(self.climate)
        presets = (state.attributes.get("preset_modes") if state else None) or []
        if mode == "frost" and presets and "frost" not in presets and "away" in presets:
            return "away"
        return mode

    def override_until(self) -> datetime | None:
        if not self.override:
            return None
        return dt_util.parse_datetime(str(self.override.get("until")))

    def state(self) -> str:
        if self.override:
            return STATE_MANUAL
        plan = self.active_plan()
        if plan is None:
            return STATE_OFF
        return self.slot_at(plan, dt_util.now())["mode"]

    # ---------- Schalten ----------
    async def async_evaluate(self, force: bool = False, apply: bool = True) -> None:
        """Modus setzen, wenn ein neuer Zeitraum begonnen hat.

        Zwischen zwei Wechselpunkten bleibt eine Wahl von Hand am Thermostat stehen.
        """
        async with self._lock:
            now = dt_util.now()
            if self.override:
                until = self.override_until()
                if until is None or now >= until:
                    self.override = None
                    self.revision += 1
                    force = True
                    self._save()
                else:
                    self._notify()
                    return
            if not self.conditions_ready():
                # Zustand von Heizperiode/Heizmodus unbekannt: nichts schalten
                self._notify()
                return
            plan = self.active_plan()
            if plan is None:
                # kein Plan aktiv: auf Wunsch das Thermostat einmal ausschalten
                marker = [self.climate, OFF_MARKER]
                if self._last != marker:
                    if not self.conf(CONF_OFF_INACTIVE):
                        self._last = marker
                        self._save()
                    elif await self._set_hvac("off"):
                        self._last = marker
                        self._turned_off = True
                        self._save()
                self._notify()
                return
            slot = self.slot_at(plan, now)
            ident = [
                self.climate,
                plan,
                now.date().isoformat(),
                self.day_key(now),
                slot["start"],
                slot["mode"],
            ]
            if force or ident != self._last:
                # wieder einschalten, wenn diese Integration ausgeschaltet hat; mit der
                # Option "ausschalten, wenn kein Plan aktiv" bei jedem Wechsel
                if self._turned_off or self.conf(CONF_OFF_INACTIVE):
                    if not await self._heat_on():
                        self._notify()
                        return
                    if self._turned_off:
                        self._turned_off = False
                        self._save()
                if not apply or await self._apply(slot["mode"]):
                    self._last = ident
                    self._save()
            self._notify()

    async def _set_hvac(self, hvac_mode: str) -> bool:
        state = self.hass.states.get(self.climate)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        if state.state == hvac_mode:
            return True
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.climate, "hvac_mode": hvac_mode},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: Betriebsart %s nicht gesetzt: %s", self.name, hvac_mode, err)
            return False
        return True

    async def _heat_on(self) -> bool:
        """Thermostat wieder einschalten, das diese Integration ausgeschaltet hat."""
        state = self.hass.states.get(self.climate)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        if state.state != "off":
            return True
        modes = state.attributes.get("hvac_modes") or []
        target = next((m for m in ("heat", "auto", "heat_cool") if m in modes), "heat")
        return await self._set_hvac(target)

    async def _apply(self, mode: str) -> bool:
        state = self.hass.states.get(self.climate)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False  # später erneut, sobald das Thermostat wieder da ist
        try:
            await self.hass.services.async_call(
                "climate",
                "set_preset_mode",
                {"entity_id": self.climate, "preset_mode": self.preset_for(mode)},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: Modus %s nicht gesetzt: %s", self.name, mode, err)
            return False
        return True

    # ---------- Änderungen von außen ----------
    async def async_set_week(self, plan: str, week: dict[str, list[dict[str, Any]]]) -> None:
        stored = dict(self.plans.get(plan, {}))
        stored.pop(HOL, None)  # eigener Feiertag aus Versionen vor 0.3.1
        for day, entries in week.items():
            if day == HOL:
                continue
            if day not in DAYS:
                raise ValueError(f"Unbekannter Tag: {day}")
            norm = normalize_day(entries)
            if norm:
                stored[day] = norm
            else:
                stored.pop(day, None)
        self.plans[plan] = stored
        self.revision += 1
        self._save()
        await self.async_evaluate(force=True)

    async def async_set_override(self, temperature: float, until: datetime) -> None:
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": self.climate, "temperature": temperature},
            blocking=True,
        )
        self.override = {
            "temperature": temperature,
            "until": dt_util.as_local(until).isoformat(),
        }
        self.revision += 1
        self._save()
        self._notify()

    async def async_cancel_override(self, apply: bool = True) -> None:
        self.override = None
        self.revision += 1
        self._save()
        await self.async_evaluate(force=True, apply=apply)

    def as_dict(self) -> dict[str, Any]:
        now = dt_util.now()
        plan = self.active_plan()
        change = self.next_change(plan, now) if plan else None
        return {
            "entry_id": self.entry.entry_id,
            "name": self.name,
            CONF_CLIMATE: self.climate,
            CONF_SEASON: self.conf(CONF_SEASON),
            CONF_MODE_ENTITY: self.conf(CONF_MODE_ENTITY),
            CONF_MODE_HEAT: self.conf(CONF_MODE_HEAT),
            CONF_MODE_VACATION: self.conf(CONF_MODE_VACATION),
            CONF_WORKDAY: self.conf(CONF_WORKDAY),
            CONF_PRESENCE: self.conf(CONF_PRESENCE),
            CONF_PRESENCE_AWAY: self.conf(CONF_PRESENCE_AWAY),
            CONF_PRESENCE_HOME: self.conf(CONF_PRESENCE_HOME),
            "holiday": self.is_holiday(),
            "holiday_day": False,  # kein eigener Feiertag-Plan: Feiertag = Sonntag
            CONF_DEFAULT_MODE: self.default_mode,
            CONF_OFF_INACTIVE: bool(self.conf(CONF_OFF_INACTIVE)),
            "plan_keys": self.plan_keys(),
            "plans": self.plans,
            "override": self.override,
            "active_plan": plan,
            "next_change": change[0].isoformat() if change else None,
            "next_mode": change[1] if change else None,
            "revision": self.revision,
        }
