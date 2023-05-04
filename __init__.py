"""Support for EnOcean devices."""
from __future__ import annotations
import voluptuous as vol
import asyncio
import logging
from typing import Any, TypedDict, cast, NamedTuple
from .services import async_setup_services
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE, CONF_ID
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import device_registry as dr
from homeassistant.const import Platform
from enoceanjob.utils import combine_hex


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
    CONF_RLC_GW,
    CONF_SEC_TI_KEY,
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
    await usb_dongle.async_forward_config_entry(config_entry)

    # Register update listener
    hass_data = dict(config_entry.data)
    unsub_options_update_listener = config_entry.add_update_listener(options_update_listener)
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][config_entry.entry_id] = hass_data

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    #Register dongle device
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={('path',config_entry.data[CONF_DEVICE])},
        identifiers={(DOMAIN, config_entry.data[CONF_DEVICE])},
        manufacturer="EnOcean",
        suggested_area="Gaine_tech",
        name=usb_dongle._communicator.app_description,
        model=usb_dongle._communicator.app_description,
        sw_version=usb_dongle._communicator.api_version,
        hw_version=usb_dongle._communicator.app_version,
    )
    
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload ENOcean config entry."""
    enocean_dongle = hass.data[DATA_ENOCEAN][ENOCEAN_DONGLE]
    enocean_dongle.unload()
    hass.data.pop(DATA_ENOCEAN)
    return True

#Config Flow update listener
async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    _LOGGER.debug("Config update: %s", config_entry.data)
    
    #Get EnOcean dongle object
    usb_dongle: EnOceanDongle
    new_device_config : dict[str: Any]
    usb_dongle = hass.data[DOMAIN].get(ENOCEAN_DONGLE)

    #Get added device
    devices_config = config_entry.data.get('devices')
    new_device_id = config_entry.data['added_device']
    new_device_config = devices_config.get(new_device_id)

    # Send secure teach in for secure devices and reload devices
    if new_device_config.get(CONF_SEC_TI_KEY, []) != []:
        await usb_dongle.async_send_sec_ti(new_device_config.get(CONF_SEC_TI_KEY),new_device_config.get(CONF_RLC_GW),new_device_config.get(CONF_ID))
        await usb_dongle.async_forward_config_entry(config_entry)
        await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
        hass.async_create_task(hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS))