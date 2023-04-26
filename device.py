"""Representation of an EnOcean device."""
import logging

from enoceanjob.protocol.packet import Packet, RadioPacket
from enoceanjob.protocol.constants import RORG
from enoceanjob.utils import combine_hex, to_hex_string
from homeassistant.helpers.entity import DeviceInfo

from homeassistant.helpers.dispatcher import async_dispatcher_connect, dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SIGNAL_RECEIVE_MESSAGE, SIGNAL_SEND_MESSAGE

from .config_schema import (
    CONF_NAME,
    DEFAULT_CONF_ID,
    DEFAULT_NAME,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_SEC_TI_KEY,
    CONF_RLC,
    CONF_ADDED_DEVICE,
    CONF_DEVICE_TYPE,
    DOMAIN
)

_LOGGER = logging.getLogger(__name__)


class EnOceanEntity(Entity):
    """Parent class for all entities associated with the EnOcean component."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, dev_id, dev_name="EnOcean device"):
        """Initialize the device."""
        self.dev_id = dev_id
        self.dev_name = dev_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.dev_name}")},
            name=self.dev_name,
            manufacturer="Test" ,
            model="Test",
            sw_version="0.0.1",
            #via_device=(DOMAIN, )
        )

    async def async_added_to_hass(self):
        """Register callbacks."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_RECEIVE_MESSAGE, self._message_received_callback
            )
        )

    def _message_received_callback(self, packet: RadioPacket):
        """Handle incoming packets."""
        
        if packet.sender_int == combine_hex(self.dev_id):# and packet.rorg != RORG.SEC_ENCAPS:
            self.received_signal_strength(packet.dBm)
            self.value_changed(packet)

    def value_changed(self, packet):
        """Update the internal state of the device when a packet arrives."""
        #To be overrided by platforms

    def received_signal_strength(self, dbm:int =0):
        """Update signal strength"""

    def send_command(self, data, optional, packet_type):
        """Send a command via the EnOcean dongle."""

        packet = Packet(packet_type, data=data, optional=optional)
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet)

class EquationHeaterEntity(EnOceanEntity, RestoreEntity):

    def __init__(self, dev_id, dev_name, config: ConfigEntry):
        super().__init__(dev_id, dev_name)
        self._sectikey = config.data.get(CONF_SEC_TI_KEY)
        self._RLC_GW = [0x00] * 3
        self._RLC_RAD = [0x00] * 3
        self._attributes = {}
    
    async def async_added_to_hass(self):
        await super().async_added_to_hass()

    def _message_received_callback(self, packet):
        """Async task for parsing message from the heater"""
        self.hass.async_create_task(self._async_parse_telegram(packet))
    
    @property
    def rlc_gw(self):
        return self._RLC_GW
    
    @property
    def rlc_rad(self):
        return self._RLC_RAD
        
    async def _async_parse_telegram(self, packet: Packet):
        """Parse heater message"""
        _LOGGER.debug("Parsing message from the heater !")
        
 