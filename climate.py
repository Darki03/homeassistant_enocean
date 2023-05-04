"""Representation of HVAC EnOcean device*"""
import voluptuous as vol
import logging
import asyncio

# HA imports
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback, DeviceRegistry

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.dispatcher import dispatcher_send
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_component
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
    CONF_DEVICES,
    EVENT_HOMEASSISTANT_START,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_OFF,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE
)

from .config_schema import CONF_DEVICE_TYPE, CONF_SEC_TI_KEY

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
from enoceanjob.utils import combine_hex, to_hex_string
from enoceanjob.protocol.constants import RORG, DECRYPT_RESULT, PACKET
from enoceanjob.protocol.packet import SECTeachInPacket, RadioPacket, ChainedMSG, Packet
from .device import EnOceanEntity, EquationHeaterEntity
from .const import SIGNAL_SEND_MESSAGE, DOMAIN, ENOCEAN_DONGLE
from .utils import add_one_to_byte_list_num
from .dongle import EnOceanDongle

_LOGGER = logging.getLogger(__name__)


CONF_RLC_GW_INIT = [0x00] * 3
CONF_RLC_SENS_INIT = [0x00] * 3

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(CLIMATE_SCHEMA)


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    _LOGGER.info("Setup entity coming from configuration.yaml named: %s", config.get(CONF_NAME))                               
    await async_setup_reload_service(hass, DOMAIN, PLATFORM)
    async_add_entities([EquationHeater(hass, config)])

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Add climate entities from configuration flow."""
    climate_list = []
    result = config_entry.data

    await async_setup_reload_service(hass, DOMAIN, PLATFORM)

    if result == {}:
        return
    for device in result[CONF_DEVICES].keys():
        if result[CONF_DEVICES][device][CONF_DEVICE_TYPE] == 'climate':
            _LOGGER.info("setup entity-config_entry_data=%s",result[CONF_DEVICES][device])
            climate = EquationHeater(hass, result[CONF_DEVICES][device])
            climate_list.append(climate)

    #Register entity service for reset RLC
    platform = ep.async_get_current_platform()
    platform.async_register_entity_service(
        "reset_rlc",
        {
            vol.Required("rlc", default=[0x00,0x00,0x00]): cv.ensure_list,
        },
        "async_reset_rlc",
    )

    if len(climate_list) != 0:
        async_add_entities(climate_list, True)
        _LOGGER.debug("climate:async_setup_platform exit - created [%d] entitites", len(climate_list))
    else:
        _LOGGER.error("climate:async_setup_platform exit - no climate entities found")
    return True


class EquationHeater(EquationHeaterEntity, ClimateEntity, RestoreEntity):
    """Representation of a Equation Enocean Heater."""

    def __init__(self, hass, config):
        """Initialize the EnOcean Heater device."""
        super().__init__(config.get(CONF_ID), config.get(CONF_NAME))
        self.usb_dongle: EnOceanDongle
        self.usb_dongle = hass.data[DOMAIN].get(ENOCEAN_DONGLE)
        self.dev_id = config.get(CONF_ID)
        self._attr_unique_id = f"{combine_hex(self.dev_id)}-{'heater'}"
        self._attr_name = f"{'Heater'}"
        self._sec_ti_key = config.get(CONF_SEC_TI_KEY)
        self.RLC_GW = CONF_RLC_GW_INIT
        self.RLC_RAD = CONF_RLC_SENS_INIT
        self.hass = hass
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
    def should_poll(self):
        """Return the polling state."""
        return False

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

    
    async def async_will_remove_from_hass(self):
        _LOGGER.debug("Remove entity : %s", self.dev_name)
        self.async_removed_from_registry


    def send_telegram(self, Key, RLC, destination, mid, **kwargs):
        decrypted = RadioPacket.create(rorg=RORG.VLD, rorg_func=0x33, rorg_type=0x00, destination = destination,mid=mid, **kwargs)
        encrypted = decrypted.encrypt(Key,RLC,SLF_TI=0x8B)
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
        _LOGGER.debug("RLC_GW: %s !", to_hex_string(self.RLC_GW))


    async def async_reset_rlc(self, rlc: list):
        _LOGGER.debug("set RLC !")
        self.usb_dongle.send_sec_ti(self._sec_ti_key,self.RLC_GW, self.dev_id)
        self.RLC_RAD = self.RLC_GW
        