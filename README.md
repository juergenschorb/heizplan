<img src="icon.svg" width="96" align="right" alt="Heizplan">

# Heizplan

Home-Assistant-Integration für Wochenpläne je Raum. Sie schaltet ein Raumthermostat (z. B. Versatile Thermostat oder Better Thermostat) zu festen Zeiten zwischen **Komfort**, **Eco** und **Frostschutz** um. Bedient wird sie mit der [Heizplan Card](https://github.com/juergenschorb/claude-homeassistant).

Statt vieler einzelner Zeitpläne gibt es genau einen Plan je Raum, gespeichert in Home Assistant. Die Scheduler-Komponente wird nicht gebraucht.

## Anzeige in der Integration (ab 0.5.0)

Auf der Geräteseite jedes Raums gibt es zusätzlich:

- **Plan heute**: die Zeiten von heute als Text, z. B. `00:00 Eco 17 °C · 06:30 Komfort 21,5 °C · 22:00 Eco 17 °C`. In den Attributen steht die ganze Woche (`normal_Mo` … `normal_So`, ebenso für den zweiten Plan).
- **Nächster Wechsel**: Zeitpunkt des nächsten Moduswechsels, im Attribut der neue Modus.
- **Solltemperatur**: Temperatur des aktuellen Modus. Sie wird aus den Preset-Zahlen des Thermostats gelesen (Versatile Thermostat, Better Thermostat); fehlen sie, bleibt der Wert leer und der Plan zeigt nur die Modi.

## Funktionen

- Ein Eintrag je Raum mit Thermostat, Wochenplan Mo–So; an Feiertagen (Mo–Fr) gilt der Sonntag
- Optional zweiter Plan „Urlaub“, umgeschaltet über eine Auswahl (z. B. Aus / Heizen / Urlaub)
- Optional Heizperiode: der Plan läuft nur, wenn ein Schalter an ist
- Manuelle Temperatur bis zu einer Uhrzeit, danach übernimmt wieder der Plan
- Nach einem Neustart von Home Assistant wird ein verpasster Wechsel nachgeholt
- War das Thermostat beim Wechsel nicht erreichbar, wird der Modus gesetzt, sobald es wieder da ist
- Zwischen zwei Wechselpunkten bleibt eine Wahl von Hand am Thermostat stehen
- Thermostat tauschen: *Einstellungen → Geräte & Dienste → Heizplan → Raum → Konfigurieren*. Der Plan bleibt erhalten.

## Installation

Seit Home Assistant 2026.11 ist HACS als „Marketplace“ eingebaut. Ein vorhandenes HACS wird beim Update automatisch übernommen.

1. *Einstellungen → Marketplace* → **Add from link** → `https://github.com/juergenschorb/heizplan`
2. „Heizplan“ installieren. Updates erscheinen unter *Einstellungen → Updates*; nach einem Update Home Assistant neu starten
3. Heizplan Card ab Version 0.6.0 installieren bzw. aktualisieren

## Räume anlegen

*Einstellungen → Geräte & Dienste → Integration hinzufügen → Heizplan*.

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
| Anwesenheit | Auswahl-Entität mit dem Modus der Etage, z. B. Normal / Urlaub / Abwesend |
| Option „Abwesend“ | Optionstext für „niemand da“: es gilt der Urlaubs-/Abwesend-Plan |
| Option „Urlaub zuhause“ | Optionstext für „frei, aber zuhause“: Mo–Fr gilt der Plan vom Sonntag |

In der Karte kann als Entität weiter das Thermostat stehen. Wer das Thermostat später tauschen will, ohne die Karte anzufassen, wählt in der Karte stattdessen den Raum (`sensor.heizplan_<raum>`).

### Etage in der Raumliste (ab 0.3.2)

Liegt das Thermostat in einem Bereich, der einer Etage zugeordnet ist, stellt die Integration die Etage dem Namen voran, z. B. „DG · Bad“ und „OG · Bad“. Dadurch ist die Liste unter *Geräte & Dienste → Heizplan* nach Etage sortiert, und gleichnamige Räume lassen sich unterscheiden. In den Karten und im Namen der Entität bleibt es beim reinen Raumnamen. Beim Umbenennen genügt der Raumname, die Etage wird automatisch ergänzt und folgt, wenn sich Bereich oder Etage ändern.

## Heizmodus und Anwesenheit

Der Heizmodus ist der Hauptschalter, die Anwesenheit verfeinert nur, solange geheizt wird:

| Heizmodus | Anwesenheit | Es gilt |
|---|---|---|
| nicht „Heizen“ und nicht „Urlaub“ (z. B. aus) | egal | kein Plan |
| „Urlaub“ | egal | Urlaubs-/Abwesend-Plan |
| „Heizen“ | „Abwesend“ | Urlaubs-/Abwesend-Plan |
| „Heizen“ | „Urlaub zuhause“ | Normalplan, Mo–Fr wie Sonntag |
| „Heizen“ | sonst | Normalplan |

Alle Felder sind optional. Ohne Heizmodus und Anwesenheit gilt immer der Normalplan.

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
- Ist kein Plan aktiv, schaltet die Integration nichts. Mit der Option „Thermostat ausschalten, wenn kein Plan aktiv ist“ schaltet sie das Thermostat einmal aus und wieder ein, sobald ein Plan aktiv wird. Mit dieser Option gehört Ein/Aus der Integration: steht das Thermostat bei einem Wechselpunkt auf „Aus“, schaltet sie es ein. Ohne die Option fasst sie Ein/Aus nicht an, ein ausgeschaltetes Thermostat bleibt aus.
- Haben Heizperiode oder Heizmodus keinen Zustand (z. B. kurz nach dem Start von Home Assistant), schaltet die Integration nichts.
- An Feiertagen (Mo–Fr) gilt der Plan vom Sonntag. Einen eigenen Feiertagsplan gibt es nicht.

## Stand

Version 0.3.1. Mit automatischen Tests geprüft, noch nicht in einer echten Home-Assistant-Instanz.
