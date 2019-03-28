import logging


from . import DeviceObserver, DeviceManager
from .util import quality_from_dbm


_LOGGER = logging.getLogger(__name__)


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
