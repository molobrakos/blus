import logging
import pathlib
import os

import pydbus
from gi.repository import GLib


from .util import get_profile_manager

_LOGGER = logging.getLogger(__name__)


def register_spp_profile(read_callback):

    try:
        from pydbus import unixfd  # noqa: F401
    except ImportError:
        exit("Requires support for unix fd in pydbus")

    UUID_SPP = "00001101-0000-1000-8000-00805f9b34fb"

    class Profile:
        def __init__(self):
            _LOGGER.debug("Init profile")
            self.fd = None
            self.io_watch_id = None

        def close(self):
            if self.fd:
                _LOGGER.debug("Closing file %d", self.fd)
                GLib.source_remove(self.io_watch_id)
                os.close(self.fd)
                self.fd = None

        def Release(self):
            _LOGGER.debug("Release")

        def NewConnection(self, path, fd, properties):

            _LOGGER.error(
                "New connection on %s with fd=%d. Properties: %s",
                path,
                fd,
                properties,
            )

            self.close()
            self.fd = os.dup(fd)

            def fd_read_callback(fd, conditions):
                _LOGGER.debug("IO callback on fd %d", fd)
                assert self.fd == fd
                read_callback(path, fd)
                return True

            try:
                self.io_watch_id = GLib.io_add_watch(
                    self.fd,
                    GLib.PRIORITY_DEFAULT,
                    GLib.IO_IN | GLib.IO_PRI,
                    fd_read_callback,
                )
            except OSError as e:
                _LOGGER.error("IO Error: %s", e)

        def RequestDisconnection(self, path):
            _LOGGER.debug("RequestDisconnection: %s", path)
            self.close()

        def write(self, value):
            _LOGGER.debug("write io")
            try:
                os.write(self.fd, value.encode("utf8"))
            except ConnectionResetError:
                self.fd = None

    profile_path = "/foo/bar/profile"
    opts = dict(
        AutoConnect=pydbus.Variant("b", True),
        Role=pydbus.Variant("s", "server"),
        Channel=pydbus.Variant("q", 1),
        RequireAuthorization=pydbus.Variant("b", False),
        RequireAuthentication=pydbus.Variant("b", False),
        Name=pydbus.Variant("s", "Foo"),
    )

    _LOGGER.info("Creating Serial Port Profile")

    bus = pydbus.SystemBus()

    bus.register_object(
        profile_path,
        Profile(),
        pathlib.Path(__file__).with_name("spp.xml").read_text(),
    )

    get_profile_manager().RegisterProfile(profile_path, UUID_SPP, opts)

    _LOGGER.info("Registered profile")
