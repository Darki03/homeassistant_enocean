"""Config flows for the ENOcean integration."""

import voluptuous as vol
import logging
import re
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from datetime import timedelta, datetime
from homeassistant.const import CONF_DEVICE

from . import dongle
from .const import DOMAIN, ERROR_INVALID_DONGLE_PATH, LOGGER, REGEX_STRING

from .config_schema import (
    get_config_flow_schema,
    CONF_HEATER,
    CONF_COOLER,
    CONF_SENSOR,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_TARGET,
    CONF_TOLERANCE,
    CONF_RELATED_CLIMATE,
    CONF_MIN_CYCLE_DURATION
)
from .helpers import (
are_entities_valid,
string_to_list,
string_to_timedelta,
null_data_cleaner
)

_LOGGER = logging.getLogger(__name__)

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
                return self.create_enocean_entry(user_input)
            errors = {CONF_DEVICE: ERROR_INVALID_DONGLE_PATH}

        bridges = await self.hass.async_add_executor_job(dongle.detect)
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
            dongle.validate_path, dongle_path
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

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Programmable Thermostat option flow."""
    MANUAL_PATH_VALUE = "Custom path"

    def __init__(self, config_entry):
        """Initialize."""
        self._errors = {}
        self._data = {}
        self.config_entry = config_entry
        if self.config_entry.options == {}:
            self._data.update(self.config_entry.data)
        else:
            self._data.update(self.config_entry.options)
        _LOGGER.debug("_data to start options flow: %s", self._data)

    async def async_step_init(self, user_input={}):
        """Propose a list of detected dongles."""
        errors = {}
        if user_input is not None:
            if await self.validate_enocean_conf(user_input):
                return self.async_create_entry(title="", data={CONF_DEVICE: user_input})
            errors = {CONF_DEVICE: ERROR_INVALID_DONGLE_PATH}

        bridges = await self.hass.async_add_executor_job(dongle.detect)
        if len(bridges) == 0:
            return

        bridges.append(self.MANUAL_PATH_VALUE)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(bridges)}),
            errors=errors,
        )
    
    async def validate_enocean_conf(self, user_input) -> bool:
        """Return True if the user_input contains a valid dongle path."""
        dongle_path = user_input[CONF_DEVICE]
        path_is_valid = await self.hass.async_add_executor_job(
            dongle.validate_path, dongle_path
        )
        return path_is_valid