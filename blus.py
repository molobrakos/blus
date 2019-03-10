# -*- mode: python; coding: utf-8 -*-

import logging
import subprocess

import pydbus
from gi.repository import GObject


__version__ = "0.0.9"


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


def proxy_for(path=None):
    bus = pydbus.SystemBus()
    proxy = bus.get(BUS_NAME, path)
    return proxy


def profile_manager():
    return proxy_for()


def agent_manager():
    return proxy_for()


def object_manager():
    return proxy_for(ROOT_PATH)


def all_objects(interface=None):
    return [
        (path, interfaces)
        for path, interfaces in object_manager().GetManagedObjects().items()
        if interface in interfaces or interface is None
    ]


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
            _LOGGER.debug("%s properties changed:", path)
            # for k, v in changed.items():
            #    _LOGGER.debug("> %s = %s", k, v)
            self.devices[path].update(changed)

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


def scan(manager, adapter_interface=None):
    # For asyncio this can be run in it's own thread
    # But the callback in DeviceObserver needs to be
    # bridged with loop.call_soon_threadsafe then

    _LOGGER.info("%s %s %s", __name__, __version__, __file__)
    _LOGGER.info("Bluez version: %d.%d", *bluez_version())

    adapters = all_objects(ADAPTER_IFACE)
    _LOGGER.debug("Total known objects: %d", len(all_objects()))
    _LOGGER.debug("Known adapters: %d", len(all_objects(ADAPTER_IFACE)))
    _LOGGER.debug("Total known devices: %d", len(all_objects(DEVICE_IFACE)))

    if not adapters:
        exit("No adapter found")

    # for now, use first found adapter
    path, _ = adapters[0]

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
        # device = proxy_for(path)
        _LOGGER.debug("Added %s: %s", path, device["Alias"])
        manager.added(path, device)

    def interfaces_removed(path, interfaces):
        manager.removed(path)

    def start_discovery():
        _LOGGER.debug("adding known interfaces ...")
        for path, interfaces in all_objects(DEVICE_IFACE):
            interfaces_added(path, interfaces)
        _LOGGER.debug("... known interfaces added")
        _LOGGER.info("discovering...")
        discovery_filter = {}
        # discovery_filter = {"Transport": "bredr"}
        # discovery_filter = {"Transport": "le"}
        # discovery_filter = {"Transport": "auto"}
        adapter.SetDiscoveryFilter(discovery_filter)
        adapter.StartDiscovery()
        _LOGGER.info("done")
        return False

    def run():
        main_loop = GObject.MainLoop()
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
            # FIXME: disconnect signals etc
            main_loop.quit()
            pass

    GObject.idle_add(start_discovery)

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

    class Observer(DeviceObserver):
        def seen(self, path, device):
            print("Discovered", path)

        def discovered(self, path, device):
            print("Seeing", path)

    scan(DeviceManager(Observer()))
