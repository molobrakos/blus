import logging
import subprocess

import pydbus

from .const import ROOT_PATH, BUS_NAME


_LOGGER = logging.getLogger(__name__)


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
