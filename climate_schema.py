"""Enocean heater's constant """
import voluptuous as vol
import logging
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_NAME, CONF_ENTITIES, CONF_ID
from homeassistant.components.climate.const import (
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    HVAC_MODE_HEAT_COOL,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_PRESET_MODE)

#Generic
# VERSION = '8.2'
DOMAIN = 'enocean'
PLATFORM = 'climate'
# ISSUE_URL = 'https://github.com/custom-components/climate.programmable_thermostat/issues'
# CONFIGFLOW_VERSION = 4


#Defaults
DEFAULT_TOLERANCE = 0.5
DEFAULT_NAME = 'Enocean Heater'
DEFAULT_MAX_TEMP = 40
DEFAULT_MIN_TEMP = 5
DEFAULT_HVAC_OPTIONS = 7
DEFAULT_AUTO_MODE = 'all'
DEFAULT_MIN_CYCLE_DURATION = ''

#Others
MAX_HVAC_OPTIONS = 8
AUTO_MODE_OPTIONS = ['all', 'heating', 'cooling']
INITIAL_HVAC_MODE_OPTIONS = ['', HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF, HVAC_MODE_HEAT_COOL]
INITIAL_HVAC_MODE_OPTIONS_OPTFLOW = ['null', HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF, HVAC_MODE_HEAT_COOL]
REGEX_STRING = r'((?P<hours>\d+?):(?=(\d+?:\d+?)))?((?P<minutes>\d+?):)?((?P<seconds>\d+?))?$'

#Attributes
ATTR_HEATER_IDS = "heater_ids"
ATTR_COOLER_IDS = "cooler_ids"
ATTR_SENSOR_ID = "sensor_id"


_LOGGER = logging.getLogger(__name__)

CONF_HEATER = 'heater'
CONF_COOLER = 'cooler'
CONF_SENSOR = 'actual_temp_sensor'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET = 'target_temp_sensor'
CONF_TOLERANCE = 'tolerance'
CONF_INITIAL_HVAC_MODE = 'initial_hvac_mode'
CONF_RELATED_CLIMATE = 'related_climate'
CONF_HVAC_OPTIONS = 'hvac_options'
CONF_AUTO_MODE = 'auto_mode'
CONF_MIN_CYCLE_DURATION = 'min_cycle_duration'
CONF_AWAY_PRESET_TEMP = 'away_temp'
CONF_SLEEP_PRESET_TEMP = 'sleep_temp'
CONF_ECO_PRESET_TEMP = 'eco_temp'
CONF_HOME_PRESET_TEMP = 'home_temp'
SUPPORT_FLAGS = (SUPPORT_TARGET_TEMPERATURE | SUPPORT_PRESET_MODE)

CLIMATE_SCHEMA = {
    vol.Optional(CONF_HEATER): cv.entity_ids,
    vol.Optional(CONF_COOLER): cv.entity_ids,
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_TOLERANCE, default=DEFAULT_TOLERANCE): vol.Coerce(float),
    vol.Optional(CONF_RELATED_CLIMATE): cv.entity_ids,
    vol.Optional(CONF_HVAC_OPTIONS, default=DEFAULT_HVAC_OPTIONS): vol.In(range(MAX_HVAC_OPTIONS)),
    vol.Optional(CONF_AUTO_MODE, default=DEFAULT_AUTO_MODE): vol.In(AUTO_MODE_OPTIONS),
    vol.Optional(CONF_INITIAL_HVAC_MODE, default=HVAC_MODE_OFF): vol.In(INITIAL_HVAC_MODE_OPTIONS),
    vol.Optional(CONF_MIN_CYCLE_DURATION): cv.positive_time_period
}
