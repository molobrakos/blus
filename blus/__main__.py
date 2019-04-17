"""
Simple bluez command line interface with MQTT gateway

Usage:
  blus (-h | --help)
  blus --version
  blus [-v|-vv] [options]
  blus [-v|-vv] [options] scan
  blus [-v|-vv] [options] mqtt

Options:
  -h --help             Show this message
  -v,-vv                Increase verbosity
  -d                    More debugging
  --version             Show version
"""

import logging

import docopt

from . import DeviceObserver, DeviceManager, __version__
from .util import quality_from_dbm
from . import mqtt


_LOGGER = logging.getLogger(__name__)


def mqtt_gw(args):

    import asyncio

    loop = asyncio.get_event_loop()
    loop.set_debug(args["-d"])
    try:
        loop.run_until_complete(mqtt.run())
    except KeyboardInterrupt:
        _LOGGER.debug("KeyboardInterrupt, exiting")


def scan():
    class Observer(DeviceObserver):
        def seen(self, manager, path, device):
            alias = device.get("Alias", path)
            mac = device.get("Address")
            q = quality_from_dbm(device.get("RSSI"))
            print(alias, mac, "on", path, q, "%")

    try:
        DeviceManager(Observer()).scan()
    except KeyboardInterrupt:
        pass


def main():
    args = docopt.docopt(__doc__, version=__version__)

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
    logging.getLogger("blus.device.scan").setLevel(logging.WARNING)

    if args["mqtt"]:
        mqtt_gw(args)
    else:
        scan()


if __name__ == "__main__":
    main()
