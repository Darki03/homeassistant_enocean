"""Support for EnOcean devices."""
import voluptuous as vol
import asyncio
import logging

from .services import async_setup_services
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE, CONF_ID
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import device_registry as dr
from homeassistant.const import Platform

from .const import DATA_ENOCEAN, DOMAIN, ENOCEAN_DONGLE, PLATFORMS
from .dongle import EnOceanDongle

from .config_schema import (
    CONF_HEATER,
    CONF_COOLER,
    CONF_SENSOR,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_TARGET,
    CONF_TOLERANCE,
    CONF_RELATED_CLIMATE,
    CONF_MIN_CYCLE_DURATION,
    CONF_SEC_TI_KEY,
    CONF_RLC
)


CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_DEVICE): cv.string})}, extra=vol.ALLOW_EXTRA
)

_LOGGER = logging.getLogger(__name__)
# component setup
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EnOcean component."""

    if not hass.data.get(DOMAIN):
        async_setup_services(hass)

    # support for text-based configuration (legacy)
    if DOMAIN not in config:
        return True

    # there is an entry available for our domain
    if hass.config_entries.async_entries(DOMAIN):
        # We can only have one dongle. If there is already one in the config,
        # there is no need to import the yaml based config.

        # The dongle is configured via the UI. The entities are configured via yaml
        return True

    # no USB dongle (or PiHat) is configured, yet
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up an EnOcean dongle for the given entry."""
    enocean_data = hass.data.setdefault(DATA_ENOCEAN, {})
    
    usb_dongle = EnOceanDongle(hass, config_entry)
    enocean_data[ENOCEAN_DONGLE] = usb_dongle
    # _LOGGER.debug("_hass data enocean: %s", hass.data[DOMAIN])
    _LOGGER.debug("_dongle path is: %s", config_entry.data[CONF_DEVICE])
    await usb_dongle.async_setup()

    # Register update listener
    hass_data = dict(config_entry.data)
    unsub_options_update_listener = config_entry.add_update_listener(options_update_listener)
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][config_entry.entry_id] = hass_data

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={('path',config_entry.data[CONF_DEVICE])},
        identifiers={(DOMAIN, config_entry.data[CONF_DEVICE])},
        manufacturer="EnOcean",
        suggested_area="Gaine_tech",
        name="EnOcean dongle",
        model="TCMXXX",
        sw_version="0.0.1",
        hw_version="1.1.1",
    )
    
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload ENOcean config entry."""
    enocean_dongle = hass.data[DATA_ENOCEAN][ENOCEAN_DONGLE]
    enocean_dongle.unload()
    hass.data.pop(DATA_ENOCEAN)
    return True

#Config Flow options update listener
async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    #Get EnOcean dongle object
    usb_dongle = hass.data[DOMAIN].get(ENOCEAN_DONGLE)
    # TO DO : Detect new devices to send SEC_TI in this case
    if config_entry.options != {}:
        _LOGGER.debug("Options update: %s", config_entry.options)
        devices_config = config_entry.options.get('devices')
        devices_list = list(config_entry.options.get('devices').keys())
        new_device_config = devices_config.get(devices_list[-1])
        usb_dongle.send_sec_ti(new_device_config.get(CONF_SEC_TI_KEY),new_device_config.get(CONF_RLC),new_device_config.get(CONF_ID))
        #hass.async_create_task(hass.config_entries.async_forward_entry_setup(config_entry, "climate"))
    
    # await hass.config_entries.async_reload(config_entry.entry_id)


    # Created dongle if first load or config update
    # if config_entry.options == {} or config_entry.options.get(CONF_DEVICE) != config_entry.data[CONF_DEVICE]:
    
    # _LOGGER.debug("_hass data setup entry: %s", hass.data[DOMAIN])

    # if hass.data[DOMAIN].get(ENOCEAN_DONGLE,{}) != {}:
    #     _LOGGER.debug("_hass data: %s", hass.data[DOMAIN].get(ENOCEAN_DONGLE))
    #     usb_dongle = hass.data[DOMAIN].get(ENOCEAN_DONGLE)
    # else: