"""Config flows for the ENOcean integration."""

import voluptuous as vol
import logging
import copy
import asyncio
import re
from typing import Any, TypedDict, cast
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send, dispatcher_send
from datetime import timedelta, datetime
from homeassistant.const import CONF_DEVICE, CONF_DEVICES, CONF_ID
from homeassistant.config_entries import ConfigEntry
from .dongle import detect, validate_path, EnOceanDongle, SecureSet
from enoceanjob.protocol.packet import SECTeachInPacket

from .const import DOMAIN, ERROR_INVALID_DONGLE_PATH, LOGGER, PLATFORMS, SIGNAL_SEND_MESSAGE

from .config_schema import (
    CONF_NAME,
    DEFAULT_CONF_ID,
    DEFAULT_NAME,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_SEC_TI_KEY,
    CONF_RLC_GW,
    CONF_RLC_EQ, 
    CONF_ADDED_DEVICE,
    CONF_DEVICE_TYPE,
    CONF_EEP,
    HEATER_MODEL,
    CONF_HEATER_MODEL
)

from enoceanjob.utils import to_hex_string

PLATFORMS_DICT = {ptf:ptf for ptf in PLATFORMS}

from .helpers import (
are_entities_valid,
string_to_list,
string_to_timedelta,
null_data_cleaner
)

_LOGGER = logging.getLogger(__name__)

#Implements the integrations config_flow:
#EnOcean dongle configuration
@config_entries.HANDLERS.register(DOMAIN)
class EnOceanFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the enOcean config flows."""

    VERSION = 1
    MANUAL_PATH_VALUE = "Custom path"

    def __init__(self):
        """Initialize the EnOcean config flow."""
        self.dongle_path = None
        self.discovery_info = None

    async def async_step_import(self, data=None):
        """Import a yaml configuration."""

        if not await self.validate_enocean_conf(data):
            LOGGER.warning(
                "Cannot import yaml configuration: %s is not a valid dongle path",
                data[CONF_DEVICE],
            )
            return self.async_abort(reason="invalid_dongle_path")
        data[CONF_DEVICES] = {}
        return self.create_enocean_entry(data)

    async def async_step_user(self, user_input=None):
        """Handle an EnOcean config flow start."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return await self.async_step_detect()

    async def async_step_detect(self, user_input=None):
        """Propose a list of detected dongles."""
        errors = {}
        if user_input is not None:
            if user_input[CONF_DEVICE] == self.MANUAL_PATH_VALUE:
                return await self.async_step_manual(None)
            if await self.validate_enocean_conf(user_input):
                user_input[CONF_DEVICES] = {}
                return self.create_enocean_entry(user_input)
            errors = {CONF_DEVICE: ERROR_INVALID_DONGLE_PATH}

        bridges = await self.hass.async_add_executor_job(detect)
        if len(bridges) == 0:
            return await self.async_step_manual(user_input)

        bridges.append(self.MANUAL_PATH_VALUE)
        return self.async_show_form(
            step_id="detect",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(bridges)}),
            errors=errors,
        )

    async def async_step_manual(self, user_input=None):
        """Request manual USB dongle path."""
        default_value = None
        errors = {}
        if user_input is not None:
            if await self.validate_enocean_conf(user_input):
                user_input[CONF_DEVICES] = {}
                return self.create_enocean_entry(user_input)
            default_value = user_input[CONF_DEVICE]
            errors = {CONF_DEVICE: ERROR_INVALID_DONGLE_PATH}

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE, default=default_value): str}
            ),
            errors=errors,
        )

    async def validate_enocean_conf(self, user_input) -> bool:
        """Return True if the user_input contains a valid dongle path."""
        dongle_path = user_input[CONF_DEVICE]
        path_is_valid = await self.hass.async_add_executor_job(
            validate_path, dongle_path
        )
        return path_is_valid

    def create_enocean_entry(self, user_input):
        """Create an entry for the provided configuration."""
        return self.async_create_entry(title="EnOcean", data=user_input)
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)
        # if config_entry.unique_id is not None:
        #     return OptionsFlowHandler(config_entry)
        # else:
        #     return EmptyOptions(config_entry)

class EmptyOptions(config_entries.OptionsFlow):
    """A class for default options. Not sure why this is required."""

    def __init__(self, config_entry):
        """Just set the config_entry parameter."""
        self.config_entry = config_entry

#Implements the EnOcean integration option flow
class OptionsFlowHandler(config_entries.OptionsFlow):
    """EnOcean integration option flow."""
    MANUAL_PATH_VALUE = "Custom path"

    def __init__(self, config_entry: ConfigEntry):
        """Initialize."""
        self._errors = {}
        self._data = {}
        self._created_device: dict[str, Any] = {}
        self._config_entry = config_entry

        #Copy start config
        self._data = self._config_entry.data.copy()
        self._data[CONF_DEVICES] = copy.deepcopy(self._config_entry.data[CONF_DEVICES])

        

    async def async_step_init(self, user_input={}):
        self._errors = {}

        if user_input is not None:
            if climate_step_valid(self, user_input):
                user_input[CONF_ID] = eval(user_input[CONF_ID])
                user_input[CONF_DEVICE_TYPE] = 'climate'
                user_input.update({CONF_SEC_TI_KEY: list(bytearray.fromhex("869FAB7D296C9E48CEBFF34DF637358A"))})
                user_input.update({CONF_RLC_GW: [0x00] * 4})
                user_input.update({CONF_RLC_EQ: [0x00] * 4})
                user_input.update({CONF_EEP: 'D2:33:00'})
                enocean_id = to_hex_string(user_input[CONF_ID])
                self._data[CONF_DEVICES][enocean_id] = user_input
                Dev_sec_set = SecureSet(key=user_input.get(CONF_SEC_TI_KEY),
                                        rlc_gw=user_input.get(CONF_RLC_GW),
                                        rlc_eq=user_input.get(CONF_RLC_EQ))
                SEC_TI_TELEGRAM = SECTeachInPacket.create_SECTI_chain(Key=Dev_sec_set.key, RLC=Dev_sec_set.rlc_gw, SLF=0x8B, destination=user_input.get(CONF_ID))
                dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, SEC_TI_TELEGRAM[0])
                await asyncio.sleep(0.5)

                # _LOGGER.debug("_data to update config entry: %s", self._data)
                self.hass.config_entries.async_update_entry(self._config_entry, data=self._data)
                await self.hass.config_entries.async_reload(self._config_entry.entry_id)

                return self.async_create_entry(title="", data={})
            return await self.show_config_climate(user_input)
        _LOGGER.info("Show climate form before validation")
        return await self.show_config_climate(user_input)

    async def show_config_climate(self, user_input):
        """ Show form for config flow """
        _LOGGER.info("Show climate form")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_ID, default=DEFAULT_CONF_ID): str,
                vol.Required(CONF_HEATER_MODEL, default='virtuoso'): vol.In(HEATER_MODEL),
                vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): int,
                vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): int,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str}),
            errors=self._errors
        )

def climate_step_valid(self, user_input):
    return True

    # async def async_step_init(self, user_input={}):
    #     """Propose a list of detected dongles."""
    #     errors = {}
    #     if user_input is not None:
    #         if await self.validate_enocean_conf(user_input):
    #             return self.async_create_entry(title="", data={CONF_DEVICE: user_input})
    #         errors = {CONF_DEVICE: ERROR_INVALID_DONGLE_PATH}

    #     bridges = await self.hass.async_add_executor_job(dongle.detect)
    #     if len(bridges) == 0:
    #         return

    #     bridges.append(self.MANUAL_PATH_VALUE)
    #     return self.async_show_form(
    #         step_id="init",
    #         data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(bridges)}),
    #         errors=errors,
    #     )
    
    # async def validate_enocean_conf(self, user_input) -> bool:
    #     """Return True if the user_input contains a valid dongle path."""
    #     dongle_path = user_input[CONF_DEVICE]
    #     path_is_valid = await self.hass.async_add_executor_job(
    #         dongle.validate_path, dongle_path
    #     )
    #     return path_is_valid