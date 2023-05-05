"""This shall be the representation of an EnOcean dongle."""
import glob
import time
import logging
from Crypto.Random import get_random_bytes
from os.path import basename, normpath
from dataclasses import dataclass, field
from enoceanjob.communicators import SerialCommunicator
from homeassistant.helpers.reload import async_setup_reload_service
from enoceanjob.protocol.packet import RadioPacket, SECTeachInPacket, ChainedMSG
from enoceanjob.protocol.constants import RORG, DECRYPT_RESULT, PACKET
from enoceanjob.protocol.security import SLF
from enoceanjob.utils import combine_hex, from_hex_string
import serial

from homeassistant.helpers.dispatcher import async_dispatcher_connect, dispatcher_send, async_dispatcher_send
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE, CONF_DEVICES

from .const import SIGNAL_RECEIVE_MESSAGE, SIGNAL_SEND_MESSAGE, DOMAIN, SIGNAL_EVENT
from .config_schema import CONF_SEC_TI_KEY, CONF_RLC_GW, CONF_RLC_EQ, CONF_EEP
_LOGGER = logging.getLogger(__name__)

#Dataclass for secure data
@dataclass
class SecureSet:

     key: list[int] = field(default_factory = lambda: list(get_random_bytes(16)))
     slf: int = 0x8B
     rlc_gw: list[int] = field(default_factory = lambda: [0x00] * 4)
     rlc_eq: list[int] = field(default_factory = lambda: [0x00] * 4)
     
     def __post_init__(self):
           Sec_SLF = SLF(self.slf)
           if len(self.rlc_gw) < 3: self.rlc_gw = [0x00] * (Sec_SLF.RLC_ALGO + 1)
           self.rlc_gw = self.rlc_gw[-(Sec_SLF.RLC_ALGO + 1):]
           if len(self.rlc_eq) < 3: self.rlc_eq = [0x00] * (Sec_SLF.RLC_ALGO + 1)
           self.rlc_eq = self.rlc_eq[-(Sec_SLF.RLC_ALGO + 1):]
           
     def add_one_to_byte_list(self, RLC):
            if RLC == []:
               return RLC
            if RLC == [0xFF] * len(RLC):
                RLC = [0x00] * len(RLC)
            return list((combine_hex(RLC) + 1).to_bytes(len(RLC), 'big'))

     def incr_rlc_gw(self):
            '''Increments gateway rolling code'''
            self.rlc_gw = self.add_one_to_byte_list(self.rlc_gw)

     def incr_rlc_eq(self):
            '''Increments equipment rolling code'''
            self.rlc_eq = self.add_one_to_byte_list(self.rlc_eq)


class EnOceanDongle:
    """Representation of an EnOcean dongle.

    The dongle is responsible for receiving the ENOcean frames,
    creating devices if needed, and dispatching messages to platforms.
    """
    

    def __init__(self, hass: core.HomeAssistant, config_entry: ConfigEntry):
        """Initialize the EnOcean dongle."""
        self.config_entry = config_entry
        self._communicator = SerialCommunicator(
            port=config_entry.data[CONF_DEVICE], callback=self.callback
        )
        self.serial_path = config_entry.data[CONF_DEVICE]
        self.devices_data: dict[str, any] = config_entry.data[CONF_DEVICES]
        self.secure_sets: dict[str, SecureSet] = {}
        self.identifier = basename(normpath(config_entry.data[CONF_DEVICE]))
        self.hass = hass
        self._event_data = {"device_id": "dongle", "type": "rlc_updated"}
        self.dispatcher_disconnect_handle = None
        hass.data.setdefault(DOMAIN, {})[self.config_entry.entry_id] = self
    
    async def async_setup(self):
        """Finish the setup of the bridge and supported platforms."""
        self._communicator.start()
        self._communicator.get_dongle_info()
        self.dispatcher_disconnect_handle = async_dispatcher_connect(
            self.hass, SIGNAL_SEND_MESSAGE, self._send_message_callback
        )

    #Update dongle config entry at startup or when a secure device is added
    async def async_forward_config_entry(self, config_entry: ConfigEntry):
        self.devices_data = config_entry.data[CONF_DEVICES]
        for device in config_entry.data[CONF_DEVICES].keys():
            key = config_entry.data[CONF_DEVICES][device][CONF_SEC_TI_KEY]
            rlc_gw = config_entry.data[CONF_DEVICES][device][CONF_RLC_GW]
            rlc_eq = config_entry.data[CONF_DEVICES][device][CONF_RLC_EQ]
            self.secure_sets.update({device: SecureSet(key=key,rlc_gw=rlc_gw,rlc_eq=rlc_eq)})
            

    def unload(self):
        """Disconnect callbacks established at init time."""
        if self.dispatcher_disconnect_handle:
            self.dispatcher_disconnect_handle()
            self.dispatcher_disconnect_handle = None
        self._communicator.stop()

    def _send_message_callback(self, command: RadioPacket, secure: bool = False):
        """Send a command through the EnOcean dongle."""

        #If secure send and a secure set is available for the destination device
        if secure and self.secure_sets.get(command.destination_hex, {} != {}):
            Dev_sec_set: SecureSet = self.secure_sets[command.destination_hex]
            command = command.encrypt(bytearray(Dev_sec_set.key),Dev_sec_set.rlc_gw, Dev_sec_set.slf)
            Dev_sec_set.incr_rlc_gw()
            self.secure_sets[command.destination_hex] = Dev_sec_set
            async_dispatcher_send(self.hass, SIGNAL_EVENT, self.secure_sets)
            if len(command.data) > 15:
                command = ChainedMSG.create_CDM(command,CDM_RORG=RORG.CDM)

        if isinstance(command, list):
            self._communicator.send_list(command)
        else:
            self._communicator.send(command)

    def send_message(self, command):
        """Send a command through the EnOcean dongle (public)."""
        self._communicator.send(command)

    async def async_send_sec_ti(self, Key, RLC, destination):
        '''Send a secure teach-in message'''
        SEC_TI_TELEGRAM = SECTeachInPacket.create_SECTI_chain(Key=Key, RLC=RLC, SLF=0x8B, destination=destination)
        self._communicator.send_list(SEC_TI_TELEGRAM[0])
        time.sleep(0.5)

    @property
    def communicator(self):
        """Set the communicator."""
        return self._communicator

    def callback(self, packet):
        """Handle EnOcean device's callback.

        This is the callback function called by python-enocan whenever there
        is an incoming packet.
        """

        if isinstance(packet, RadioPacket):
            
            #If we received a secure packet and a secure set is defined for the device
            if packet.rorg == RORG.SEC_ENCAPS and self.devices_data.get(packet.sender_hex, {}) != {}:

                _LOGGER.debug("Received secure radio packet: %s", packet)
                Dev_sec_set: SecureSet = self.secure_sets[packet.sender_hex]
                decrypted = packet.decrypt(bytearray(Dev_sec_set.key),Dev_sec_set.rlc_eq, Dev_sec_set.slf)
                Dev_sec_set.rlc_eq = decrypted[2]
                Dev_sec_set.incr_rlc_eq()
                self.secure_sets[packet.sender_hex] = Dev_sec_set
                async_dispatcher_send(self.hass, SIGNAL_EVENT, self.secure_sets)
                if decrypted[1] == DECRYPT_RESULT.OK: 
                    packet = decrypted[0]

                    #If D2-33-00 profile, manage gateway acknowledgement
                    if self.devices_data[packet.sender_hex][CONF_EEP] == 'D2:33:00':
                        EEP = from_hex_string(self.devices_data[packet.sender_hex][CONF_EEP])
                        packet.parse_eep(EEP[1], EEP[2])
                        if (packet.parsed['MID']['raw_value'] == 8 and (packet.parsed['REQ']['raw_value'] == 0 or packet.parsed['REQ']['raw_value'] == 4)) or packet.parsed['MID']['raw_value'] > 8:
                            ack_packet = RadioPacket.create(rorg=RORG.VLD, rorg_func=EEP[1], rorg_type= EEP[2], destination=from_hex_string(packet.sender_hex), MID=0, REQ=15)
                            self._send_message_callback(ack_packet, True)
                

            _LOGGER.debug("Received radio packet: %s", packet)
            dispatcher_send(self.hass, SIGNAL_RECEIVE_MESSAGE, packet)




def detect():
    """Return a list of candidate paths for USB ENOcean dongles.

    This method is currently a bit simplistic, it may need to be
    improved to support more configurations and OS.
    """
    globs_to_test = ["/dev/tty*FTOA2PV*", "/dev/serial/by-id/*EnOcean*", "/dev/serial/by-id/*ESP32S2*"]
    found_paths = []
    for current_glob in globs_to_test:
        found_paths.extend(glob.glob(current_glob))

    return found_paths


def validate_path(path: str):
    """Return True if the provided path points to a valid serial port, False otherwise."""
    try:
        # Creating the serial communicator will raise an exception
        # if it cannot connect
        SerialCommunicator(port=path)
        return True
    except serial.SerialException as exception:
        _LOGGER.warning("Dongle path %s is invalid: %s", path, str(exception))
        return False
