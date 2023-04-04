"""Support for EnOcean devices."""
import voluptuous as vol
import asyncio
import logging

from .services import async_setup_services
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import device_registry as dr

from .const import DATA_ENOCEAN, DOMAIN, ENOCEAN_DONGLE, PLATFORMS
from .dongle import EnOceanDongle

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

    # Dongle path update listener
    hass_data = dict(config_entry.data)
    unsub_options_update_listener = config_entry.add_update_listener(options_update_listener)
    hass_data["unsub_options_update_listener"] = unsub_options_update_listener
    hass.data[DOMAIN][config_entry.entry_id] = hass_data

    usb_dongle = EnOceanDongle(hass, config_entry)
    await usb_dongle.async_setup()
    enocean_data[ENOCEAN_DONGLE] = usb_dongle
    _LOGGER.debug("_dongle path is: %s", config_entry.data[CONF_DEVICE])

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

async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    await hass.config_entries.async_reload(config_entry.entry_id)