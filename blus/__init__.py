# -*- mode: python; coding: utf-8 -*-

__version__ = "0.0.17"

from .util import (
    get_remote_objects,
    get_object_manager,
    proxy_for,
    bluez_version,
)
from .const import (
    ADAPTER_IFACE,
    DEVICE_IFACE,
    PROPERTIES_IFACE,
    SERVICE_IFACE,
    CHARACTERISTIC_IFACE,
    DESCRIPTOR_IFACE,
)
from .device import DeviceManager, DeviceObserver


__all__ = [
    "DeviceManager",
    "DeviceObserver",
    "get_remote_objects",
    "get_object_manager",
    "proxy_for",
    "bluez_version",
    "ADAPTER_IFACE",
    "DEVICE_IFACE",
    "PROPERTIES_IFACE",
    "SERVICE_IFACE",
    "CHARACTERISTIC_IFACE",
    "DESCRIPTOR_IFACE",
]
