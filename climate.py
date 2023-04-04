"""Representation of HVAC EnOcean device*"""
import voluptuous as vol
import logging
import asyncio

# HA imports
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback, DeviceRegistry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.dispatcher import dispatcher_send
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.components.climate.const import (
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_OFF,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    PRESET_AWAY,
    PRESET_NONE,
    PRESET_ECO,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_SLEEP,
    PRESET_ACTIVITY,
    HVAC_MODE_HEAT_COOL,
    ATTR_PRESET_MODE
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


CONF_RLC_GW_INIT = [0x00] * 3
CONF_RLC_SENS_INIT = [0x00] * 3

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(CLIMATE_SCHEMA)


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    _LOGGER.info("Setup entity coming from configuration.yaml named: %s", config.get(CONF_NAME))                               
    await async_setup_reload_service(hass, DOMAIN, PLATFORM)
    async_add_entities([EquationHeater(hass, config)])


class EquationHeater(EnOceanEntity, ClimateEntity, RestoreEntity):
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
        self._target_temp = None
        self._restore_temp = self._target_temp
        self._cur_temp = None
        self._active = False
        self._hvac_action = CURRENT_HVAC_OFF
        self._hvac_list.append(HVAC_MODE_OFF)
        self._hvac_list.append(HVAC_MODE_HEAT)
        self._telegram_received = asyncio.Condition()

        if self._initial_hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
        elif self._initial_hvac_mode == HVAC_MODE_HEAT_COOL:
            self._hvac_mode = HVAC_MODE_HEAT_COOL
        elif self._initial_hvac_mode == HVAC_MODE_COOL:
            self._hvac_mode = HVAC_MODE_COOL
        else:
            self._hvac_mode = HVAC_MODE_OFF
        self._support_flags = SUPPORT_FLAGS

        self._preset_mode = PRESET_NONE
        self._saved_target_temp = 5
        self._attributes = {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._attr_unique_id)
            },
            name=self._name,
            manufacturer="Equation" ,
            model="Equation",
            sw_version="3000",
        )

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
    def preset_mode(self):
        return self._preset_mode
    
    @property
    def preset_modes(self):
        return [
            PRESET_NONE,
            PRESET_AWAY,
            PRESET_ECO,
            PRESET_SLEEP,
            PRESET_HOME,
        ]

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
    
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    async def async_added_to_hass(self):
        """Query status after Home Assistant (re)start."""
        await super().async_added_to_hass()

        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if old_state.attributes.get(ATTR_PRESET_MODE) is not None:
                self._preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state
            for x in self.preset_modes:
                if old_state.attributes.get(x + "_temp") is not None:
                     self._attributes[x + "_temp"] = old_state.attributes.get(x + "_temp")
        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                self._target_temp = self.min_temp
            _LOGGER.warning("No previously saved temperature, setting to %s", self._target_temp)


        TMODE = Packet(PACKET.COMMON_COMMAND, data=[0x3E, 0x01])
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, TMODE) #Activate transparent mode
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, self.secti[0]) #Reinit RLC
        await asyncio.sleep(1)
        self.send_telegram(bytearray(self.secti[1].KEY), self.RLC_GW, self.secti[1].SLF, self.dev_id,0, MID=0, REQ=8)
        self.RLC_GW = add_one_to_byte_list_num(self.RLC_GW)
    
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

    async def async_set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        """Test if Preset mode is valid"""
        if not preset_mode in self.preset_modes:
            return
        """if old value is preset_none we store the temp"""
        if self._preset_mode == PRESET_NONE:
            self._saved_target_temp = self._target_temp
        self._preset_mode = preset_mode
        """let's deal with the new value"""
        if self._preset_mode == PRESET_NONE:
            self._target_temp = self._saved_target_temp
        else:
            temp = self._attributes.get(self._preset_mode + "_temp", self._target_temp)
            self._target_temp = float(temp)
            await self.async_set_temperature(temperature=temp)
        self.async_write_ha_state()
        
    def init_presets_temps(self):
        for preset_mode in self.preset_modes:
            self._attributes[preset_mode + "_temp"] = 5

    
    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get(ATTR_TEMPERATURE)
        _LOGGER.warning("Setting temperature: %s", int(temperature))
        if temperature is None:
            _LOGGER.error("Wrong temperature: %s", temperature)
            return
        self._target_temp = float(temperature)
        self.send_telegram(bytearray(self.secti[1].KEY), self.RLC_GW, self.secti[1].SLF, self.dev_id,2, MID=2, TSP=temperature)
        self.RLC_GW = add_one_to_byte_list_num(self.RLC_GW)
        if self._preset_mode != PRESET_NONE:
            self._attributes[self._preset_mode + "_temp"] = self._target_temp
        await self.async_update_ha_state()
        async with self._telegram_received:
            await asyncio.wait_for(self._telegram_received.wait(), timeout=1.0)
            _LOGGER.debug("Acknowledge received !")

    def value_changed(self, packet):
        #Async task for parsing message from the heater
        self.hass.async_create_task(self._async_parse_telegram(packet))

    async def _async_parse_telegram(self, packet):
        _LOGGER.debug("Parsing message from the heater !")
        
        if packet.rorg == RORG.SEC_ENCAPS:
           Decode_packet = packet.decrypt(bytearray(self.secti[1].KEY), self.RLC_RAD, self.secti[1].SLF)
           self.RLC_RAD = add_one_to_byte_list_num(self.RLC_RAD)
           
           if Decode_packet[1] == DECRYPT_RESULT.OK:
               
               Decode_packet[0].select_eep(0x33, 0x00)
               Decode_packet[0].parse_eep()

               if Decode_packet[0].parsed['MID']['raw_value'] == 8:
                    async with self._telegram_received:
                            self._telegram_received.notify()
                    self._cur_temp = Decode_packet[0].parsed['INT']['value']
                    if Decode_packet[0].parsed['HTF']['raw_value'] == 1:
                        _LOGGER.debug("Heater is active !")
                        self._hvac_mode = HVAC_MODE_HEAT
                    else:
                        _LOGGER.debug("Heater is idle !")
                        self._hvac_mode = HVAC_MODE_OFF
               
               if (Decode_packet[0].parsed['MID']['raw_value'] == 8 and (Decode_packet[0].parsed['REQ']['raw_value'] == 0 or Decode_packet[0].parsed['REQ']['raw_value'] == 4)) or Decode_packet[0].parsed['MID']['raw_value'] > 8:
                     self.send_telegram(bytearray(self.secti[1].KEY), self.RLC_GW, self.secti[1].SLF, self.dev_id,0, MID=0, REQ=15)
                     self.RLC_GW = add_one_to_byte_list_num(self.RLC_GW)
               
               await self.async_update_ha_state()