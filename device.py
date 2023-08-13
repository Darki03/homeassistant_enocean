"""Representation of an EnOcean device."""
import logging


from homeassistant.helpers.entity import DeviceInfo

from homeassistant.helpers.dispatcher import async_dispatcher_connect, dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SIGNAL_RECEIVE_MESSAGE, SIGNAL_SEND_MESSAGE
from .utils import add_one_to_byte_list_num

from .config_schema import (
    CONF_NAME,
    DEFAULT_CONF_ID,
    DEFAULT_NAME,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_SEC_TI_KEY,
    CONF_ADDED_DEVICE,
    CONF_DEVICE_TYPE,
    DOMAIN
)

# Enocean integration specific integrations
from enoceanjob.utils import combine_hex, to_hex_string
from enoceanjob.protocol.constants import RORG, DECRYPT_RESULT, PACKET
from enoceanjob.protocol.packet import SECTeachInPacket, RadioPacket, ChainedMSG, Packet

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
        
        if packet.sender_int == combine_hex(self.dev_id) and packet.rorg != RORG.SEC_ENCAPS:
            self.received_signal_strength(packet.dBm)
            self.value_changed(packet)

    def value_changed(self, packet):
        """Update the internal state of the device when a packet arrives."""
        #To be overrided by platforms

    def received_signal_strength(self, dbm:int =0):
        """Update signal strength"""
        #To be overrided by sensor platform

    def send_command(self, data, optional, packet_type):
        """Send a command via the EnOcean dongle."""

        packet = Packet(packet_type, data=data, optional=optional)
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet)

class EquationHeaterEntity(EnOceanEntity):

    def __init__(self, dev_id, dev_name):
        super().__init__(dev_id, dev_name)
    
    async def async_added_to_hass(self):
        await super().async_added_to_hass()

    def value_changed(self, packet):
        """Async task for parsing message from the heater"""
        self.hass.async_create_task(self._async_parse_telegram(packet))
    
    def create_and_send_secure_packet(self, **kwargs):    
        packet = RadioPacket.create(rorg=RORG.VLD, rorg_func=0x33, rorg_type=0x00, destination = self.dev_id, **kwargs)
        dispatcher_send(self.hass, SIGNAL_SEND_MESSAGE, packet, True)
    
    async def _async_parse_telegram(self, packet: Packet):
        """Parse heater message"""

        # packet.parse_eep(0x33, 0x00)

        MID = packet.parsed['MID']['raw_value']
        
        if MID == 8:
            await self.async_parse_request_status(packet)

        if MID == 9:
            await self.async_parse_heater_parameters(packet)


    async def async_parse_request_status(self, packet: RadioPacket):
        """Parse MID=8 message frome Heater
            Contains INT temperature"""
    
    async def async_parse_heater_parameters(self, packet: RadioPacket):
        """Parse MID=9 message frome Heater
            Contains EM (Energy Mesurement) and FMV"""
    
    async def async_send_gw_request_message(self, **kwargs):
        """Send Gateway request message with indicated kwargs"""
        kwargs.update({'MID': 0})
        self.create_and_send_secure_packet(**kwargs)
        return True
    
    async def async_send_gw_sensor_parameters(self, **kwargs):
        """Send Gateway request message with indicated kwargs"""
        kwargs.update({'MID': 1})
        self.create_and_send_secure_packet(**kwargs)
        return True
    
    async def async_send_gw_program(self, **kwargs):
        """Send Gateway request message with indicated kwargs"""
        kwargs.update({'MID': 2})
        self.create_and_send_secure_packet(**kwargs)
        return True
    
    async def async_send_time_date(self, **kwargs):
        """Send Gateway request message with indicated kwargs"""
        kwargs.update({'MID': 3})
        self.create_and_send_secure_packet(**kwargs)
        return True
    


    

        
 