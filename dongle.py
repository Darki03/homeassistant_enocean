"""This shall be the representation of an EnOcean dongle."""
import glob
import logging
from os.path import basename, normpath

from enoceanjob.communicators import SerialCommunicator
from homeassistant.helpers.reload import async_setup_reload_service
from enoceanjob.protocol.packet import RadioPacket
from enoceanjob.utils import combine_hex
import serial

from homeassistant.helpers.dispatcher import async_dispatcher_connect, dispatcher_send
from homeassistant import core
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_DEVICE

from .const import SIGNAL_RECEIVE_MESSAGE, SIGNAL_SEND_MESSAGE, DOMAIN

_LOGGER = logging.getLogger(__name__)

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
        self.identifier = basename(normpath(config_entry.data[CONF_DEVICE]))
        self.hass = hass
        self.dispatcher_disconnect_handle = None
        hass.data.setdefault(DOMAIN, {})[self.config_entry.entry_id] = self
    
    async def async_setup(self):
        """Finish the setup of the bridge and supported platforms."""
        self._communicator.start()
        self._communicator.base_id = [0x00] * 4
        self.dispatcher_disconnect_handle = async_dispatcher_connect(
            self.hass, SIGNAL_SEND_MESSAGE, self._send_message_callback
        )

    def unload(self):
        """Disconnect callbacks established at init time."""
        if self.dispatcher_disconnect_handle:
            self.dispatcher_disconnect_handle()
            self.dispatcher_disconnect_handle = None

    def _send_message_callback(self, command):
        """Send a command through the EnOcean dongle."""
        if isinstance(command, list):
            self._communicator.send_list(command)
        else:
            self._communicator.send(command)

    def send_message(self, command):
        """Send a command through the EnOcean dongle (public)."""
        self._communicator.send(command)

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
