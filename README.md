<img src="icon.svg" width="96" align="right" alt="Heizplan">

# Heizplan

Home-Assistant-Integration für Wochenpläne je Raum. Sie schaltet ein Raumthermostat (z. B. Versatile Thermostat oder Better Thermostat) zu festen Zeiten zwischen **Komfort**, **Eco** und **Frostschutz** um. Bedient wird sie mit der [Heizplan Card](https://github.com/juergenschorb/claude-homeassistant).

Die Integration ersetzt die Scheduler-Komponente für die Heizplan Card: Statt vieler einzelner Zeitpläne gibt es genau einen Plan je Raum, gespeichert in Home Assistant.

## Funktionen

- Ein Eintrag je Raum mit Thermostat, Wochenplan Mo–So und optional einem eigenen Tag „Feiertag“
- Optional zweiter Plan „Urlaub“, umgeschaltet über eine Auswahl (z. B. Aus / Heizen / Urlaub)
- Optional Heizperiode: der Plan läuft nur, wenn ein Schalter an ist
- Manuelle Temperatur bis zu einer Uhrzeit, danach übernimmt wieder der Plan
- Nach einem Neustart von Home Assistant wird ein verpasster Wechsel nachgeholt
- War das Thermostat beim Wechsel nicht erreichbar, wird der Modus gesetzt, sobald es wieder da ist
- Zwischen zwei Wechselpunkten bleibt eine Wahl von Hand am Thermostat stehen
- Thermostat tauschen: *Einstellungen → Geräte & Dienste → Heizplan → Raum → Konfigurieren*. Der Plan bleibt erhalten.

## Installation

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/juergenschorb/heizplan`, Typ **Integration**
2. „Heizplan“ in HACS herunterladen und Home Assistant neu starten
3. Heizplan Card ab Version 0.6.0 installieren bzw. aktualisieren

## Räume anlegen

**Aus der Karte (empfohlen bei vorhandenen Plänen):** Läuft ein Raum bisher über den Scheduler, zeigt die Heizplan Card den Knopf **„Raum in Heizplan übernehmen“**. Er legt den Raum mit dem bisherigen Wochenplan und den Einstellungen der Karte an und entfernt die Zeitpläne aus dem Scheduler. Dafür muss man als Administrator angemeldet sein.

**Von Hand:** *Einstellungen → Geräte & Dienste → Integration hinzufügen → Heizplan*.

| Feld | Bedeutung |
|---|---|
| Raum | Name, z. B. „Wohnzimmer“ |
| Raumthermostat | `climate`-Entität, die geschaltet wird |
| Grundmodus | Modus für Tage ohne gespeicherten Plan |
| Heizperiode | Schalter; Plan läuft nur bei „an“ |
| Heizmodus | Auswahl-Entität |
| Option „Heizen“ / „Urlaub“ | Optionstexte der Auswahl für Normal- und Urlaubsplan |
| Thermostat ausschalten, wenn kein Plan aktiv ist | Schaltet das Thermostat bei Heizmodus „Aus“ oder außerhalb der Heizperiode aus und danach wieder ein |
| Feiertage | Feiertagskalender (`calendar`, an = Feiertag) oder Arbeitstag-Sensor (aus = Feiertag) |

In der Karte kann als Entität weiter das Thermostat stehen. Wer das Thermostat später tauschen will, ohne die Karte anzufassen, wählt in der Karte stattdessen den Raum (`sensor.heizplan_<raum>`).

## Entität

Je Raum gibt es `sensor.heizplan_<raum>` mit dem Modus laut Plan:

| Zustand | Bedeutung |
|---|---|
| `comfort`, `eco`, `frost` | Modus des aktiven Plans |
| `off` | kein Plan aktiv (Heizung aus, außerhalb der Heizperiode) |
| `manual` | manuelle Temperatur läuft |

Attribute: `active_plan`, `next_change`, `next_mode`, `override_until`, `climate`.

## So wird geschaltet

- Zu jedem Wechselpunkt, beim Speichern eines Plans und sobald ein Plan aktiv wird (Heizperiode an, Heizmodus gewechselt, Feiertag beginnt), ruft die Integration `climate.set_preset_mode` auf.
- Kennt das Thermostat kein Preset `frost`, aber `away`, wird für Frostschutz `away` gesetzt (Better Thermostat).
- Ist kein Plan aktiv, schaltet die Integration nichts. Mit der Option „Thermostat ausschalten, wenn kein Plan aktiv ist“ schaltet sie das Thermostat einmal aus und wieder ein, sobald ein Plan aktiv wird. Ein Thermostat, das du selbst ausgeschaltet hast, schaltet sie nicht ein.
- Feiertag gilt Mo–Fr. Ohne eigenen Feiertagsplan gilt der Sonntag.

## Stand

Version 0.2.2. Mit automatischen Tests geprüft, noch nicht in einer echten Home-Assistant-Instanz.
