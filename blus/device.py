# -*- mode: python; coding: utf-8 -*-

import logging
import time
import datetime

import pydbus
from gi.repository import GLib

from . import __version__
from .util import (
    get_remote_objects,
    get_object_manager,
    bluez_version,
    proxy_for,
    _len,
)
from .const import (
    ADAPTER_IFACE,
    DEVICE_IFACE,
    PROPERTIES_IFACE,
    SERVICE_IFACE,
    CHARACTERISTIC_IFACE,
    DESCRIPTOR_IFACE,
)


_LOGGER = logging.getLogger(__name__)
_LOGGER_SCAN = logging.getLogger(__name__ + ".scan")


DEFAULT_PURGE_TIMEOUT = datetime.timedelta(minutes=5)
PERIODIC_CHECK_INTERVAL = datetime.timedelta(seconds=30)
DEFAULT_THROTTLE = datetime.timedelta(seconds=10)


class DeviceObserver:

    # Subclass this to catch any events

    def discovered(self, manager, path, device):
        self.seen(manager, path, device)

    def seen(self, manager, path, device):
        pass

    def unseen(self, manager, path):
        pass


def is_device(interfaces):
    return DEVICE_IFACE in interfaces


class DeviceManager:
    def __init__(
        self,
        observer,
        device=None,
        purge_timeout=DEFAULT_PURGE_TIMEOUT,
        throttle=DEFAULT_THROTTLE,
    ):

        assert purge_timeout >= PERIODIC_CHECK_INTERVAL

        self.objects = get_remote_objects()
        self.last_seen = {}
        self.observer = observer
        self.purge_timeout = purge_timeout.total_seconds()
        self.throttle = throttle.total_seconds()

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
                _LOGGER.info(
                    "Periodic check, known objects: %d", len(self.objects)
                )
                self.purge_unseen_devices()
            finally:
                GLib.timeout_add_seconds(
                    PERIODIC_CHECK_INTERVAL.total_seconds(), periodic_check
                )

        GLib.idle_add(periodic_check)

    def update_last_seen(self, path):
        self.last_seen[path] = time.time()

    def see_device(self, path):
        if time.time() - self.last_seen[path] < self.throttle:
            # FIXME: might hide state changes of interest
            _LOGGER.debug("Skipping recently seen %s", path)
            return
        self.update_last_seen(path)
        self.observer.seen(self, path, self.get_device(path))

    def discover_device(self, path):
        self.update_last_seen(path)
        self.observer.discovered(self, path, self.get_device(path))

    def purge_unseen_devices(self):
        _LOGGER.debug("last seen length %d", len(self.last_seen))
        for path, last_seen in self.last_seen.items():
            if time.time() - last_seen < self.purge_timeout:
                continue
            _LOGGER.error(
                "Haven't seen %s in %d seconds", path, self.purge_timeout
            )
            if (
                self.objects[path][DEVICE_IFACE]["AddressType"] == "public"
                or self.objects[path][DEVICE_IFACE]["Paired"]
            ):
                _LOGGER.info("Keeping device with public address")
            else:
                _LOGGER.info("Removing device with random address")
                self.adapter.RemoveDevice(path)

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
        return self.objects.get(device_path).get(DEVICE_IFACE)

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

        if self.get_device(path):
            self.discover_device(path)

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

        _LOGGER_SCAN.debug(
            "Properties changed on %s/%s: %s -- %s",
            path,
            interface,
            changed,
            invalidated,
        )

        if self.get_device(path):
            self.see_device(path)

    def _interfaces_removed(self, path, interfaces):
        if path not in self.objects:
            _LOGGER.error("Removed unknown device: %s", path)
            return

        _LOGGER.debug("Interfaces removed on %s", path)

        if DEVICE_IFACE in interfaces:
            self.observer.unseen(self, path)

        for interface in interfaces:
            del self.objects[path][interface]

        # if no interface left
        if not self.objects[path]:
            del self.objects[path]
            del self.last_seen[path]
            _LOGGER.debug("%s removed", path)

    def scan(self, transport="le", device=None):
        """
        Valid values for tranport: "le", "bredr", "auto"
        https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/doc/device-api.txt

        For asyncio this can be run in it's own thread
        But the callback in DeviceObserver needs to be
        bridged with loop.call_soon_threadsafe then
        """

        def start_discovery():

            _LOGGER.debug("Discovery signals for known devices...")
            for path, _interfaces in self.objects.items():
                if self.get_device(path):
                    self.discover_device(path)

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

            discovery_filter = {}
            if transport:
                discovery_filter = dict(
                    Transport=pydbus.Variant("s", transport)
                )

            try:
                _LOGGER.info("discovering...")
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
                _LOGGER.info("Devices currently known: %d", len(self.objects))
                main_loop.quit()
                _LOGGER.info("Scanner kthxbye")

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
