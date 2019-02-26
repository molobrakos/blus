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

__version__ = "0.0.4"

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


class Interface:
    def __init__(self, path, interface):
        self.path = path
        self.obj = interface_for(path, interface)

    def get(self, prop):
        return self.obj.get(prop)

    def set(self, prop, val):
        self.obj.set(prop, val)


class Device(Interface):
    def __init__(self, path):
        super().__init__(path, DEVICE_IFACE)

    def get(self, prop):
        return self.obj.get(prop)

    def set(self, prop, val):
        self.obj.set(prop, val)

    @property
    def name(self):
        return self.get("Name")

    @property
    def alias(self):
        return self.get("Alias")

    @property
    def address(self):
        return self.get("Address")

    @property
    def uuids(self):
        return self.get("UUIDs")

    @property
    def address_type(self):
        return self.get("AddressType")

    @property
    def is_trusted(self):
        return self.get("Trusted") == 1

    @is_trusted.setter
    def is_trusted(self, val):
        return self.set("Trusted", val)

    @property
    def is_paired(self):
        return self.get("Paired") == 1

    @property
    def is_connected(self):
        return self.get("Connected") == 1

    @property
    def is_services_resolved(self):
        return self.get("ServicesResolved") == 1

    def remove(self):
        raise NotImplementedError("Use adapter.Remove for now")

    def pair(self):
        if self.is_paired:
            _LOGGER.info("Already paired to %s", self.path)
            return
        try:
            _LOGGER.info("Pairing with %s", self.path)
            self.obj.Pair()
        except dbus.exceptions.DBusException as e:
            _LOGGER.error("Failed to pair with %s: %s", self.path, e)

    def disconnect(self):
        if not self.is_connected:
            _LOGGER.info("Not connected to %s, skipping disconnect", self.path)
            return
        try:
            _LOGGER.info("Disconnecting from %s", self.path)
            self.obj.Disconnect()
        except dbus.exceptions.DBusException as e:
            _LOGGER.error("Failed to disconnect from %s: %s", self.path, e)

    def connect(self, uuid=None):

        if self.is_connected:
            _LOGGER.info("Already connected to %s", self.path)
            return
        try:
            if uuid:
                _LOGGER.info("Connecting to profile %s", uuid)
                self.obj.ConnectProfile(uuid)
            else:
                _LOGGER.info("Connecting to %s", self.path)
                # FIXME: This blocks
                self.obj.Connect()
        except dbus.exceptions.DBusException as e:
            _LOGGER.error("Failed to connect to %s: %s", self.path, e)


class Adapter(Interface):

    # FIXME: Expose methods from object interface as well

    def __init__(self, path):
        super().__init__(path, ADAPTER_IFACE)

    @property
    def name(self):
        return self.get("Name")

    @property
    def alias(self):
        return self.get("Alias")

    @property
    def address(self):
        return self.get("Address")

    @property
    def pairable(self):
        return self.get("Pairable")

    @pairable.setter
    def pairable(self, state):
        self.set("Pairable", dbus.Boolean(state))

    @property
    def powered(self):
        return self.get("Powered")

    @powered.setter
    def powered(self, state):
        self.set("Powered", dbus.Boolean(state))

    @property
    def discoverable(self):
        return self.get("Discoverable")

    @discoverable.setter
    def discoverable(self, state):
        self.set("Discoverable", dbus.Boolean(state))

    def remove(self, path):
        try:
            self.obj.RemoveDevice(path)
        except dbus.exceptions.DBusException as e:
            _LOGGER.error("Failed to unpair with %s: %s", path, e)

    @property
    def discovering(self):
        return self.get("Discovering")

    def start_discovery(self):
        # https://github.com/RadiusNetworks/bluez/blob/master/doc/adapter-api.txt
        discovery_filter = {}
        # discovery_filter = {"Transport": "bredr"}
        # discovery_filter = {"Transport": "le"}
        # discovery_filter = {"Transport": "auto"}
        try:
            self.obj.SetDiscoveryFilter(discovery_filter)
            _LOGGER.info("starting discovery ...")
            self.obj.StartDiscovery()
            _LOGGER.info("... discovery started")
        except dbus.exceptions.DBusException as e:
            if e.get_dbus_name() == "org.bluez.Error.InProgress":
                _LOGGER.debug("Discovery already in progress")
            else:
                _LOGGER.error("Could not start discovery: %s", e)


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

    def added(self, path, device):
        if path in self.devices:
            _LOGGER.error("Device already known: %s", path)
            return
        self.devices[path] = device
        self.observer.discovered(path, device)

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

        device = self.devices[path]

        alias = device.get("Alias", path)
        mac = device.get("Address")
        q = quality_from_dbm(device.get("RSSI"))
        if q is not None:
            _LOGGER_SCAN.debug("Seeing %32s (%s) (%3s%%)", alias, mac, q)

        self.observer.seen(path, self.devices[path])

    def removed(self, path):
        if path not in self.devices:
            _LOGGER.error("Removed unknown device: %s", path)
            return
        del self.devices[path]


def scan(manager, adapter_interface=None):

    # For asyncio this can be run in it's own thread
    # But the callback in DeviceObserver needs to be
    # bridged with loop.call_soon_threadsafe then

    if threading.current_thread() != threading.main_thread():
        threading.current_thread().name = "bt-scanner"

    _LOGGER.info("Bluez version: %d.%d", *bluez_version())

    adapters = all_objects(ADAPTER_IFACE)
    _LOGGER.debug("Known adapters: %d", len(all_objects(ADAPTER_IFACE)))

    if not adapters:
        exit("No adapter found")

    # for now, use first found adapter
    path, _ = adapters[0]
    adapter = Adapter(path)

    _LOGGER.info(
        "Adapter %s (%s) is powered %s",
        adapter.name,
        adapter.address,
        ("off", "on")[adapter.powered],
    )

    def properties_changed(interface, changed, invalidated, path):
        if interface != DEVICE_IFACE:
            _LOGGER.error(
                "unknown interface changed on %s: %s", path, interface
            )
            return
        manager.changed(path, changed, invalidated)

    def interfaces_added(path, interfaces):
        if DEVICE_IFACE not in interfaces:
            _LOGGER.error(
                "Unknown interface added on path %s: %s", path, interfaces
            )
            return
        device = interfaces[DEVICE_IFACE]
        manager.added(path, device)

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

    adapter.start_discovery()

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

    scan(DeviceManager(Observer()))
