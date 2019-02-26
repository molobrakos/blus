# -*- mode: python; coding: utf-8 -*-

import logging
import subprocess
import threading

try:
    import dbus
except ImportError:
    exit("No dbus found. " "Run: sudo apt-get install python3-dbus")

import dbus.mainloop.glib
import dbus.service
from gi.repository import GObject
from dbus import PROPERTIES_IFACE

# FIXME: consider pydbus? https://github.com/LEW21/pydbus

__version__ = "0.0.3"

_LOGGER = logging.getLogger(__name__)
_LOGGER_SCAN = logging.getLogger(__name__ + ".scan")

LOGFMT = "%(asctime)s %(levelname)5s (%(threadName)s) [%(name)s] %(message)s"
DATEFMT = "%y-%m-%d %H:%M.%S"

SERVICE = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
PROFILE_MANAGER_IFACE = "org.bluez.ProfileManager1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)


def bluez_version():
    out = subprocess.check_output("bluetoothctl -v", shell=True)
    return tuple(map(int, out.split()[1].split(b".")))


def quality_from_dbm(dbm):
    if dbm is None:
        return None
    elif dbm <= -100:
        return 0
    elif dbm >= -50:
        return 100
    else:
        return 2 * (dbm + 100)


def all_objects(interface=None):
    object_manager = interface_for("/", OBJECT_MANAGER_IFACE)
    return [
        (path, interfaces)
        for path, interfaces in object_manager.GetManagedObjects().items()
        if interface in interfaces or interface is None
    ]


def interface_for(path, interface):

    bus = dbus.SystemBus()
    obj = bus.get_object(SERVICE, path)
    obj = dbus.Interface(obj, interface)

    properties = dbus.Interface(obj, PROPERTIES_IFACE)

    def get(prop):
        return properties.Get(interface, prop)

    def set(prop, val):
        properties.Set(interface, prop, val)

    obj.get = get
    obj.set = set

    return obj


class DeviceObserver:
    # Subclass this to catch events

    def discovered(self, path, device):
        # Override this to catch events
        pass

    def seen(self, path, device):
        # Override this to catch events
        pass


class DeviceManager:
    def __init__(self, observer):
        self.devices = {}
        self.observer = observer

    def see(self, path):
        if path not in self.devices:
            _LOGGER.error("seeing unknown device: %s", path)
            return
        device = self.devices[path]
        q = quality_from_dbm(device.get("RSSI"))
        if q is not None:
            _LOGGER_SCAN.debug("See %s: %2s%%", path, q)
        self.observer.seen(path, self.devices[path])

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

    def added(self, path, device):
        if path in self.devices:
            _LOGGER.error("Device already known: %s", path)
            return
        self.devices[path] = device
        self.observer.discovered(path, device)

    def removed(self, path):
        if path not in self.devices:
            _LOGGER.error("Removed unknown device: %s", path)
            return
        del self.devices[path]


def scan(observer, adapter_interface=None):

    # For asyncio this can be run in it's own thread
    # But the callback in DeviceObserver needs to be
    # bridged with loop.call_soon_threadsafe then

    if threading.current_thread() != threading.main_thread():
        threading.current_thread().name = "bt-scanner"

    manager = DeviceManager(observer)

    _LOGGER.info("Bluez version: %d.%d", *bluez_version())

    adapters = all_objects(ADAPTER_IFACE)
    _LOGGER.debug("Known adapters: %d", len(all_objects(ADAPTER_IFACE)))

    if not adapters:
        exit("No adapter found")

    # for now, use first found adapter
    path, interface = adapters[0]
    adapter = interface_for(path, ADAPTER_IFACE)

    name = adapter.get("Name")
    mac = adapter.get("Address")
    powered = adapter.get("Powered")

    _LOGGER.info(
        "Adapter %s (%s) is powered %s", name, mac, ("off", "on")[powered]
    )

    def properties_changed(interface, changed, invalidated, path):
        if interface != DEVICE_IFACE:
            _LOGGER.error(
                "unknown interface changed on %s: %s", path, interface
            )
            return
        manager.changed(path, changed, invalidated)
        manager.see(path)

    def interfaces_added(path, interfaces):
        if DEVICE_IFACE not in interfaces:
            return
        device = interfaces[DEVICE_IFACE]
        manager.added(path, device)
        manager.see(path)

    def interfaces_removed(path, interfaces):
        manager.removed(path)

    def add_callback(
        callback, signal_name, dbus_interface=OBJECT_MANAGER_IFACE, **kwargs
    ):
        bus = dbus.SystemBus()
        return bus.add_signal_receiver(
            callback,
            bus_name=SERVICE,
            dbus_interface=dbus_interface,
            signal_name=signal_name,
            **kwargs
        )

    add_callback(interfaces_added, "InterfacesAdded")
    add_callback(interfaces_removed, "InterfacesRemoved")
    add_callback(properties_changed, "PropertiesChanged", path_keyword="path")
    add_callback(
        properties_changed,
        "PropertiesChanged",
        dbus_interface=dbus.PROPERTIES_IFACE,
        arg0=DEVICE_IFACE,
        path_keyword="path",
    )

    _LOGGER.debug("Total known objects: %d", len(all_objects()))
    _LOGGER.debug("Total known devices: %d", len(all_objects(DEVICE_IFACE)))

    _LOGGER.debug("adding known interfaces ...")
    for path, interfaces in all_objects(DEVICE_IFACE):
        interfaces_added(path, interfaces)
    _LOGGER.debug("... known interfaces added")

    discovery_filter = {"Transport": "auto"}
    try:
        adapter.SetDiscoveryFilter(discovery_filter)
        _LOGGER.info("starting discovery ...")
        adapter.StartDiscovery()
        _LOGGER.info("... discovery started")
    except dbus.exceptions.DBusException as e:
        if e.get_dbus_name() == "org.bluez.Error.InProgress":
            _LOGGER.debug("Discovery already in progress")
        else:
            _LOGGER.error("Could not start discovery: %s", e)
            return

    try:
        main_loop = GObject.MainLoop()
        _LOGGER.info("Running main loop")
        main_loop.run()
    except KeyboardInterrupt:
        _LOGGER.info("Exiting")
        raise
    except Exception:
        raise
    finally:
        # FIXME: disconnect signals etc
        pass


if __name__ == "__main__":

    class Observer(DeviceObserver):
        def seen(self, path, device):
            print("Seeing", path)

    scan(Observer())
