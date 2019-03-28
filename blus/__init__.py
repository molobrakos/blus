# -*- mode: python; coding: utf-8 -*-

__version__ = "0.0.16"

from .util import (
    get_remote_objects,
    get_object_manager,
    proxy_for,
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
