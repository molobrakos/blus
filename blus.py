# -*- mode: python; coding: utf-8 -*-

import logging
import subprocess
import pathlib
import os

import pydbus
from gi.repository import GLib


__version__ = "0.0.14"


_LOGGER = logging.getLogger(__name__)
_LOGGER_SCAN = logging.getLogger(__name__ + ".scan")


LOGFMT = "%(asctime)s %(levelname)5s (%(threadName)s) [%(name)s] %(message)s"
DATEFMT = "%y-%m-%d %H:%M.%S"

ROOT_PATH = "/"
BUS_NAME = "org.bluez"

PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"

ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
PROFILE_MANAGER_IFACE = "org.bluez.ProfileManager1"

GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_PROFILE_IFACE = "org.bluez.GattProfile1"
SERVICE_IFACE = "org.bluez.GattService1"
CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"
DESCRIPTOR_IFACE = "org.bluez.GattDescriptor1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

BATTERY_IFACE = "org.bluez.Battery1"


def bluez_version():
    out = subprocess.check_output("bluetoothctl -v", shell=True)
    return tuple(map(int, out.split()[-1].split(b".")))


def quality_from_dbm(dbm):
    if dbm is None:
        return None
    elif dbm <= -100:
        return 0
    elif dbm >= -50:
        return 100
    else:
        return 2 * (dbm + 100)


def _len(g):
    """len of generator"""
    return sum(1 for _ in g)


def proxy_for(path=None):
    _LOGGER.debug("Getting proxy object for %s", path)
    bus = pydbus.SystemBus()
    return bus.get(BUS_NAME, path)


def get_profile_manager():
    """located at service root (/org/bluez)"""
    return proxy_for()


def get_agent_manager():
    """located at service root (/org/bluez)"""
    return proxy_for()


def get_object_manager():
    """located at root (/)"""
    return proxy_for(ROOT_PATH)


def get_remote_objects():
    """
    Return all known objects
    """
    _LOGGER.debug("Getting all known remote objects (only needed once)")
    return get_object_manager().GetManagedObjects()


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
        pathlib.Path(__file__).with_name("btspp.xml").read_text(),
    )

    get_profile_manager().RegisterProfile(profile_path, UUID_SPP, opts)

    _LOGGER.info("Registered profile")


class DeviceObserver:

    # Subclass this to catch any events

    def discovered(self, manager, path, device):
        # Override this to catch events
        self.seen(manager, path, device)

    def seen(self, manager, path, device):
        # Override this to catch events
        pass


class DeviceManager:
    def __init__(self, observer, device=None):

        self.objects = get_remote_objects()
        self.observer = observer

        _LOGGER.info("%s %s %s", __name__, __version__, __file__)
        _LOGGER.info("%s: %s", pydbus.__name__, pydbus.__file__)
        _LOGGER.info("Bluez version: %d.%d", *bluez_version())

        _LOGGER.info("Total known objects: %d", len(self.objects))
        _LOGGER.info("Known adapters: %d", _len(self.adapters))
        _LOGGER.info("Total known devices: %d", _len(self.devices))

        adapter = self.get_adapter(device)

        if not adapter:
            exit("No adapter found")

        path, _ = adapter
        self.adapter = proxy_for(path)

        _LOGGER.info(
            "Adapter %s (%s) on %s is powered %s",
            self.adapter.Name,
            self.adapter.Address,
            path,
            ("off", "on")[self.adapter.Powered],
        )

        def periodic_check():
            try:
                _LOGGER.debug(
                    "Periodic check, known objects: %d", len(self.objects)
                )
            finally:
                GLib.timeout_add_seconds(10, periodic_check)

        GLib.idle_add(periodic_check)

    def get_objects(self, *interface):
        """
        Return all objects in list of objects matching any interface in
        parameter interface
        """
        return (
            (path, interfaces)
            for path, interfaces in self.objects.items()
            if not interface
            or any(candidate in interfaces for candidate in interface)
        )

    @property
    def adapters(self):
        """shorthand"""
        return self.get_objects(ADAPTER_IFACE)

    @property
    def devices(self):
        """shorthand"""
        return self.get_objects(DEVICE_IFACE)

    def get_device(self, device_path):
        return next(
            (
                interfaces
                for path, interfaces in self.devices
                if path == device_path
            ),
            [],
        ).get(DEVICE_IFACE)

    def get_adapter(self, device=None):
        """return first adapter"""
        return next(
            (
                (path, interface)
                for path, interface in self.adapters
                if not device or device in path
            ),
            None,
        )

    def _get_branch(self, interface, parent_name, parent_path):
        """shorthand"""
        return (
            (path, interfaces[interface])
            for path, interfaces in self.get_objects(interface)
            if not parent_path
            or parent_path == interfaces[interface][parent_name]
        )

    def services(self, device=None):
        """shorthand"""
        return self._get_branch(SERVICE_IFACE, "Device", device)

    def characteristics(self, service=None):
        """shorthand"""
        return self._get_branch(CHARACTERISTIC_IFACE, "Service", service)

    def descriptors(self, characteristic=None):
        """shorthand"""
        return self._get_branch(
            DESCRIPTOR_IFACE, "Characteristic", characteristic
        )

    def _interfaces_added(self, path, interfaces):

        _LOGGER.debug("Interfaces added on %s", path)

        if path in self.objects:
            _LOGGER.error("Interface added on known object: %s", path)
            if any(
                interface in self.objects[path] for interface in interfaces
            ):
                _LOGGER.error(
                    "Interface already known: %s %s", path, interfaces
                )
                return

            self.objects[path].update(interfaces)
        else:
            self.objects[path] = interfaces

        device = interfaces.get(DEVICE_IFACE)
        if device:
            self.observer.discovered(self, path, device)

        _LOGGER.debug("Added %s. Total known %d", path, len(self.objects))

    def _properties_changed(self, _sender, path, _iface, _signal, changed):
        interface, changed, invalidated = changed
        if path not in self.objects:
            _LOGGER.error("unknown object %s changed", path)
            return

        if invalidated:
            _LOGGER.debug("invalidated for %s: %s", path, invalidated)
            for key in invalidated:
                del self.objects[path][interface][key]

        if changed:
            self.objects[path][interface].update(changed)
            _LOGGER_SCAN.debug("%s properties changed: %s", path, changed)

        _LOGGER_SCAN.debug(
            "Properties changed on %s/%s: %s -- %s",
            path,
            interface,
            changed,
            invalidated,
        )

        device = self.objects[path].get(DEVICE_IFACE)
        if device:
            self.observer.seen(self, path, device)

    def _interfaces_removed(self, path, interfaces):
        if path not in self.objects:
            _LOGGER.error("Removed unknown device: %s", path)
            return

        _LOGGER.debug("Interfaces removed on %s", path)

        for interface in interfaces:
            del self.objects[path][interface]

        if not len(self.objects[path]):
            _LOGGER.debug("No interfaces left, removing object at %s", path)
            del self.objects[path]

    def scan(self, transport="le", device=None):

        # Valid values for tranport is
        # "le", "bredr", "auto"
        # https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/doc/device-api.txt

        # For asyncio this can be run in it's own thread
        # But the callback in DeviceObserver needs to be
        # bridged with loop.call_soon_threadsafe then

        def start_discovery():

            _LOGGER.debug("adding known interfaces ...")
            # for path, interfaces in objects:
            #    self.objects[path] = interfaces
            _LOGGER.debug("... known interfaces added")

            _LOGGER.debug("Discovery signals for known devices...")
            for path, interfaces in self.objects.items():
                device = interfaces.get(DEVICE_IFACE)
                if device:
                    self.observer.discovered(self, path, device)

            def _relevant_interfaces(interfaces):
                irrelevant_interfaces = {
                    "org.freedesktop.DBus.Properties",
                    "org.freedesktop.DBus.Introspectable",
                }
                return set(interfaces) - irrelevant_interfaces

            for path, interfaces in self.objects.items():
                _LOGGER.debug(
                    "%-45s: %s",
                    path,
                    ", ".join(_relevant_interfaces(interfaces.keys())),
                )

            _LOGGER.info("discovering...")
            if transport:
                discovery_filter = dict(
                    Transport=pydbus.Variant("s", transport)
                )
            else:
                discovery_filter = {}

            try:
                self.adapter.SetDiscoveryFilter(discovery_filter)
                self.adapter.StartDiscovery()
                _LOGGER.info("... discovery started")
            except GLib.Error as e:
                _LOGGER.error("Could not start discovery: %s", e)

            return False

        def run_loop():
            main_loop = GLib.MainLoop()
            try:
                _LOGGER.info("Running main loop")
                main_loop.run()
            except KeyboardInterrupt:
                _LOGGER.debug("Keyboard interrupt, exiting")
                raise
            except Exception:
                _LOGGER.exception("Got exception")
                raise
            finally:
                main_loop.quit()
                pass

        GLib.idle_add(start_discovery)

        object_manager = get_object_manager()
        bus = pydbus.SystemBus()

        with object_manager.InterfacesAdded.connect(
            self._interfaces_added
        ), object_manager.InterfacesRemoved.connect(
            self._interfaces_removed
        ), bus.subscribe(
            iface=PROPERTIES_IFACE,
            signal="PropertiesChanged",
            arg0=DEVICE_IFACE,
            signal_fired=self._properties_changed,
        ), bus.subscribe(
            iface=PROPERTIES_IFACE,
            signal="PropertiesChanged",
            arg0=DESCRIPTOR_IFACE,
            signal_fired=self._properties_changed,
        ):
            run_loop()


if __name__ == "__main__":

    LOG_LEVEL = logging.DEBUG
    LOG_FMT = (
        "%(asctime)s %(levelname)5s (%(threadName)s) [%(name)s] %(message)s"
    )
    DATE_FMT = "%y-%m-%d %H:%M.%S"

    try:
        import coloredlogs

        coloredlogs.install(level=LOG_LEVEL, datefmt=DATE_FMT, fmt=LOG_FMT)
    except ImportError:
        _LOGGER.debug("no colored logs. pip install coloredlogs?")
        logging.basicConfig(level=LOG_LEVEL, datefmt=DATE_FMT, format=LOG_FMT)

    logging.captureWarnings(True)

    class Observer(DeviceObserver):
        def seen(self, manager, path, device):
            alias = device.get("Alias", path)
            mac = device.get("Address")
            q = quality_from_dbm(device.get("RSSI"))

            print(alias, mac, "on", path, q, "%")

            from pprint import pprint

            pprint(device)

    try:
        DeviceManager(Observer()).scan()
    except KeyboardInterrupt:
        pass
