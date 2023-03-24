"""Representation of HVAC EnOcean device*"""
import voluptuous as vol
import logging

# HA imports
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.dispatcher import dispatcher_send
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.components.climate.const import (
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_OFF,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    HVAC_MODE_HEAT_COOL
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_ID,
    EVENT_HOMEASSISTANT_START,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_OFF,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE
)

# Climate specific imports
from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from .climate_schema import(
    CLIMATE_SCHEMA,
    CONF_HEATER,
    CONF_COOLER,
    CONF_SENSOR,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_TARGET,
    CONF_TOLERANCE,
    CONF_INITIAL_HVAC_MODE,
    CONF_RELATED_CLIMATE,
    CONF_HVAC_OPTIONS,
    CONF_AUTO_MODE,
    CONF_MIN_CYCLE_DURATION,
    SUPPORT_FLAGS,
    ATTR_HEATER_IDS,
    ATTR_COOLER_IDS,
    ATTR_SENSOR_ID,
    PLATFORM
)

# Enocean integration specific integrations
from enoceanjob.utils import combine_hex
from enoceanjob.protocol.constants import RORG, DECRYPT_RESULT, PACKET
from enoceanjob.protocol.packet import SECTeachInPacket, RadioPacket, ChainedMSG, Packet
from .device import EnOceanEntity
from .const import SIGNAL_SEND_MESSAGE, DOMAIN
from .utils import add_one_to_byte_list_num

_LOGGER = logging.getLogger(__name__)

# DEFAULT_NAME = "EnOcean HVAC"
# CONF_BASE_ID = "base_id"
CONF_RLC_GW_INIT = [0x00] * 3
CONF_RLC_SENS_INIT = [0x00] * 3
# MIN_TEMP = 5
# MAX_TEMP = 28


# PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
#     {
#         vol.Required(CONF_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
#         vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
#         vol.Optional(CONF_BASE_ID, default=[0x00, 0x00, 0x00, 0x00]): vol.All(
#             cv.ensure_list, [vol.Coerce(int)]
#         ),
#     }
# )

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(CLIMATE_SCHEMA)


# def setup_platform(
#     hass: HomeAssistant,
#     config: ConfigType,
#     add_entities: AddEntitiesCallback,
#     discovery_info: DiscoveryInfoType | None = None,
# ) -> None:
#     """Set up the EnOcean HVAC platform."""
#     dev_id = config.get(CONF_ID)
#     dev_name = config.get(CONF_NAME)
#     base_id = config.get(CONF_BASE_ID, [0, 0, 0, 0])
#     add_entities([EquationHeater(dev_id, dev_name, base_id)])

async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    _LOGGER.info("Setup entity coming from configuration.yaml named: %s", config.get(CONF_NAME))                               
    await async_setup_reload_service(hass, DOMAIN, PLATFORM)
    async_add_entities([EquationHeater(hass, config)])

class EquationHeater(EnOceanEntity, ClimateEntity):
    """Representation of a Equation Enocean Heater."""
    _attr_has_entity_name = True

    def __init__(self, hass, config):
        """Initialize the EnOcean Heater device."""
        super().__init__(config.get(CONF_ID), config.get(CONF_NAME))
        self.dev_id = config.get(CONF_ID)
        self._attr_unique_id = f"{combine_hex(self.dev_id)}"
        self.secti = SECTeachInPacket.create_SECTI_chain(SLF=0x8B, destination=config.get(CONF_ID))
        self.RLC_GW = CONF_RLC_GW_INIT
        self.RLC_RAD = CONF_RLC_SENS_INIT
        self.hass = hass
        self._name = config.get(CONF_NAME)
        self._tolerance = config.get(CONF_TOLERANCE)
        self._min_temp = config.get(CONF_MIN_TEMP)
        self._max_temp = config.get(CONF_MAX_TEMP)
        self._initial_hvac_mode = config.get(CONF_INITIAL_HVAC_MODE)
        self._unit = hass.config.units.temperature_unit
        self._hvac_options = config.get(CONF_HVAC_OPTIONS)
        self._auto_mode = config.get(CONF_AUTO_MODE)
        self._hvac_list = []
        self._target_temp = 9
        self._restore_temp = self._target_temp
        self._cur_temp = None
        self._active = False
        self._hvac_action = CURRENT_HVAC_OFF
        self._hvac_list.append(HVAC_MODE_OFF)
        self._hvac_list.append(HVAC_MODE_HEAT)

        if self._initial_hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
        elif self._initial_hvac_mode == HVAC_MODE_HEAT_COOL:
            self._hvac_mode = HVAC_MODE_HEAT_COOL
        elif self._initial_hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
        else:
            self._hvac_mode = HVAC_MODE_OFF
        self._support_flags = SUPPORT_FLAGS

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS
    
    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list


    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1
        
    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp
        
    async def async_added_to_hass(self):
        """Query status after Home Assistant (re)start."""
        await super().async_added_to_hass()
        TMODE = Packet(PACKET.COMMON_COMMAND, data=[0x3E, 0x01])
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, TMODE)
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, self.secti[0])
        self.send_telegram(bytearray(self.secti[1].KEY), self.RLC_GW, self.secti[1].SLF, self.dev_id,0, MID=0, REQ=8)
    
    def send_telegram(self, Key, RLC, SLF, destination, mid, **kwargs):
        decrypted = RadioPacket.create(rorg=RORG.VLD, rorg_func=0x33, rorg_type=0x00, destination = destination,mid=mid, **kwargs)
        encrypted = decrypted.encrypt(Key,RLC,SLF)
        if len(encrypted.data) > 15:
          encrypted = ChainedMSG.create_CDM(encrypted,CDM_RORG=RORG.CDM)
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, encrypted)
    
    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
        elif hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
        elif hvac_mode == HVAC_MODE_OFF:
            self._hvac_mode = HVAC_MODE_OFF
        await self.async_update_ha_state()
        
    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get(ATTR_TEMPERATURE)
        _LOGGER.warning("Setting temperature: %s", int(temperature))
        if temperature is None:
            _LOGGER.error("Wrong temperature: %s", temperature)
            return
        self._target_temp = float(temperature)
        self.send_telegram(bytearray(self.secti[1].KEY), self.RLC_GW, self.secti[1].SLF, self.dev_id,2, MID=2, TSP=temperature)
        self.RLC_GW = add_one_to_byte_list_num(self.RLC_GW)
        await self.async_update_ha_state()

    def value_changed(self, packet):
        if packet.rorg == RORG.SEC_ENCAPS:
           Decode_packet = packet.decrypt(bytearray(self.secti[1].KEY), self.RLC_RAD, self.secti[1].SLF)
           self.RLC_RAD = add_one_to_byte_list_num(self.RLC_RAD)
           if Decode_packet[1] == DECRYPT_RESULT.OK:
               Decode_packet[0].select_eep(0x33, 0x00)
               Decode_packet[0].parse_eep()
               self._cur_temp = Decode_packet[0].parsed['INT']['value']
               if (Decode_packet[0].parsed['MID']['raw_value'] == 8 and (Decode_packet[0].parsed['REQ']['raw_value'] == 0 or Decode_packet[0].parsed['REQ']['raw_value'] == 4)) or Decode_packet[0].parsed['MID']['raw_value'] > 8:
                     self.send_telegram(bytearray(self.secti[1].KEY), self.RLC_GW, self.secti[1].SLF, self.dev_id,0, MID=0, REQ=15)
                     self.RLC_GW = add_one_to_byte_list_num(self.RLC_GW)