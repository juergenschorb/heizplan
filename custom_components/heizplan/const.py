"""Konstanten für Heizplan."""

DOMAIN = "heizplan"
# Trennt im Titel eines Raums die Etage vom Raumnamen ("DG · Bad")
TITLE_SEP = " · "

CONF_CLIMATE = "climate"
CONF_SEASON = "season_entity"
CONF_MODE_ENTITY = "mode_entity"
CONF_MODE_HEAT = "mode_heat"
CONF_MODE_VACATION = "mode_vacation"
CONF_WORKDAY = "workday_entity"
CONF_PRESENCE = "presence_entity"
CONF_PRESENCE_AWAY = "presence_away"
CONF_PRESENCE_HOME = "presence_home"
CONF_DEFAULT_MODE = "default_mode"
CONF_OFF_INACTIVE = "off_when_inactive"

OPTION_KEYS = (
    CONF_CLIMATE,
    CONF_SEASON,
    CONF_MODE_ENTITY,
    CONF_MODE_HEAT,
    CONF_MODE_VACATION,
    CONF_WORKDAY,
    CONF_PRESENCE,
    CONF_PRESENCE_AWAY,
    CONF_PRESENCE_HOME,
    CONF_DEFAULT_MODE,
    CONF_OFF_INACTIVE,
)

MODES = ("comfort", "eco", "frost")
DEFAULT_MODE = "eco"

PLAN_NORMAL = "normal"
PLAN_VACATION = "urlaub"

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WORKDAYS = DAYS[:5]
HOL = "hol"
DAY_MIN = 1440

STATE_OFF = "off"
STATE_MANUAL = "manual"

STORAGE_VERSION = 1
