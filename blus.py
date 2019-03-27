# -*- mode: python; coding: utf-8 -*-

import logging
import subprocess

import pydbus
from gi.repository import GLib


__version__ = "0.0.13"


_LOGGER = logging.getLogger(__name__)
_LOGGER_SCAN = logging.getLogger(__name__ + ".scan")


LOGFMT = "%(asctime)s %(levelname)5s (%(threadName)s) [%(name)s] %(message)s"
DATEFMT = "%y-%m-%d %H:%M.%S"

ROOT_PATH = "/"
BUS_NAME = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
PROFILE_MANAGER_IFACE = "org.bluez.ProfileManager1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"


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
    bus = pydbus.SystemBus()
    proxy = bus.get(BUS_NAME, path)
    return proxy


def profile_manager():
    """located at service root (/org/bluez)"""
    return proxy_for()


def agent_manager():
    """located at service root (/org/bluez)"""
    return proxy_for()


def object_manager():
    """located at root (/)"""
    return proxy_for(ROOT_PATH)


def get_objects(*interface):
    """
    Return all known objects matching any interface in parameter interface
    """
    return (
        (path, interfaces)
        for path, interfaces
        in object_manager().GetManagedObjects().items()
        if not interface
        or any(candidate in interfaces
               for candidate in interface)
    )


def get_adapters():
    """shorthand"""
    return get_objects(ADAPTER_IFACE)


def get_devices():
    """shorthand"""
    return get_objects(DEVICE_IFACE)


def get_adapter():
    """return first adapter"""
    return next(get_adapters(), None)


def _get_branch(interface, branch, path):
    """shorthand"""
    return [
        (path, interfaces)
        for path, interfaces
        in get_objects(interface)
        if not path
        or path == interfaces[interface][branch]
    ]


def get_services(device=None):
    """shorthand"""
    return _get_branch(SERVICE_FACE, "Device", device)


def get_characteristics(service=None):
    """shorthand"""
    return _get_branch(CHARACTERISTIC_IFACE, "Service", service)


def get_descriptors(characteristic=None):
    """shorthand"""
    return _get_branch(DESCRIPTOR_FACE, "Characteristic", characteristic)


class DeviceObserver:

    # Subclass this to catch any events

    def discovered(self, path, device):
        # Override this to catch events
        pass

    def seen(self, path, device):
        # Override this to catch events
        pass


class DeviceManager:

    # This device manager keeps a dict of all known/seen
    # devices and notifies one connected observer.
    # Subclass this for any other behaviour

    def __init__(self, observer):
        self.devices = {}
        self.observer = observer

        def periodic_check():
            try:
                _LOGGER.debug(
                    "Periodic check, known devices: %d", len(self.devices)
                )
            finally:
                GLib.timeout_add_seconds(10, periodic_check)

        GLib.idle_add(periodic_check)

    def added(self, path, device):
        if path in self.devices:
            _LOGGER.error("Device already known: %s", path)
            return
        self.devices[path] = device
        self.observer.discovered(path, device)
        _LOGGER.debug("Added %s. Total known %d", path, len(self.devices))

    def changed(self, path, changed, invalidated):
        if path not in self.devices:
            _LOGGER.error("unknown device %s changed", path)
            return
        if invalidated:
            _LOGGER.debug("invalidated for %s: %s", path, invalidated)
            for key in invalidated:
                del self.devices[path][key]
        if changed:
            self.devices[path].update(changed)
            _LOGGER_SCAN.debug("%s properties changed", path)

        device = self.devices[path]

        alias = device.get("Alias", path)
        mac = device.get("Address")
        q = quality_from_dbm(device.get("RSSI"))
        if q is not None:
            _LOGGER_SCAN.debug("Seeing %s (%3s%%): %s", mac, q, alias)

        self.observer.seen(path, self.devices[path])

    def removed(self, path):
        if path not in self.devices:
            _LOGGER.error("Removed unknown device: %s", path)
            return
        del self.devices[path]


def scan(manager, transport="le", adapter_interface=None):
    # For asyncio this can be run in it's own thread
    # But the callback in DeviceObserver needs to be
    # bridged with loop.call_soon_threadsafe then

    _LOGGER.info("%s %s %s", __name__, __version__, __file__)
    _LOGGER.info("%s: %s", pydbus.__name__, pydbus.__file__)
    _LOGGER.info("Bluez version: %d.%d", *bluez_version())

    _LOGGER.debug("Total known objects: %d", _len(get_objects()))
    _LOGGER.debug("Known adapters: %d", _len(get_adapters()))
    _LOGGER.debug("Total known devices: %d", _len(get_devices()))

    adapter = get_adapter()

    if not adapter:
        exit("No adapter found")

    # for now, use first found adapter
    path, _ = adapter

    adapter = proxy_for(path)

    _LOGGER.info(
        "Adapter %s (%s) on %s is powered %s",
        adapter.Name,
        adapter.Address,
        path,
        ("off", "on")[adapter.Powered],
    )

    def properties_changed(_sender, path, _iface, _signal, interfaces):
        if interfaces[0] != DEVICE_IFACE:
            _LOGGER.error("unknown %s %s", path, interfaces)
            return
        changed = interfaces[1]
        manager.changed(path, changed, None)

    def interfaces_added(path, interfaces):
        if DEVICE_IFACE not in interfaces:
            _LOGGER.error(
                "Unknown interface added on path %s: %s", path, interfaces
            )
            # e.g. /org/bluez/hci0/dev_11_22_33_44_55_66/fd1 (MediaTransport1)
            return
        device = interfaces[DEVICE_IFACE]
        _LOGGER.debug("Added %s: %s", path, device["Alias"])
        manager.added(path, device)

    def interfaces_removed(path, interfaces):
        manager.removed(path)

    def start_discovery():
        _LOGGER.debug("adding known interfaces ...")

        for path, interfaces in get_objects():
            interfaces_added(path, interfaces)

        _LOGGER.debug("... known interfaces added")
        _LOGGER.info("discovering...")
        if transport:
            discovery_filter = dict(Transport=pydbus.Variant("s", transport))
        else:
            discovery_filter = {}
        # discovery_filter = {"Transport": "le"}
        # discovery_filter = {"Transport": "bredr"}
        # discovery_filter = {"Transport": "auto"}
        adapter.SetDiscoveryFilter(discovery_filter)
        adapter.StartDiscovery()
        _LOGGER.info("done")
        return False

    def run():
        main_loop = GLib.MainLoop()
        try:
            _LOGGER.info("Running main loop")
            main_loop.run()
        except KeyboardInterrupt:
            _LOGGER.info("Keyboard interrupt, exiting")
            raise
        except Exception:
            _LOGGER.exception("Got exception")
            raise
        finally:
            main_loop.quit()
            pass

    GLib.idle_add(start_discovery)

    with object_manager().InterfacesAdded.connect(
        interfaces_added
    ), object_manager().InterfacesRemoved.connect(
        interfaces_removed
    ), pydbus.SystemBus().subscribe(
        iface=PROPERTIES_IFACE,
        signal="PropertiesChanged",
        arg0=DEVICE_IFACE,
        signal_fired=properties_changed,
    ):
        run()


if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG)

    class Observer(DeviceObserver):
        def seen(self, path, device):
            print("Discovered", path)

        def discovered(self, path, device):
            print("Seeing", path)

    scan(DeviceManager(Observer()))
