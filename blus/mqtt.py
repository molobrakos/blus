# -*- mode: python; coding: utf-8 -*-

import logging
import time
import json
import string
import datetime
import platform
import os
import threading
import asyncio

import certifi

from . import DeviceObserver, DeviceManager
from .util import quality_from_dbm

_LOGGER = logging.getLogger(__name__)


THROTTLE = datetime.timedelta(seconds=10)

TOPIC_WHITELIST = "_-" + string.ascii_letters + string.digits
TOPIC_SUBSTITUTE = "_"


def read_mqtt_config():
    """Read credentials from ~/.config/mosquitto_pub."""
    fname = os.path.join(
        os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        ),
        "mosquitto_pub",
    )
    try:
        with open(fname) as f:
            d = dict(
                line.replace("-", "").split() for line in f.read().splitlines()
            )
            return dict(
                host=d["h"],
                port=d["p"],
                username=d["username"],
                password=d["pw"],
            )
    except KeyError as error:
        exit("Could not parse MQTT config in %s: %s" % (fname, error))
    except FileNotFoundError:
        exit("Could not find MQTT config: %s" % fname)


def is_mainthread():
    return threading.current_thread() == threading.main_thread()


def topic_for_path(path):
    return "/".join(["blus", platform.node(), path.split("/")[-1]])


async def run(config=None):

    loop = asyncio.get_event_loop()

    try:
        import websockets
        from websockets.handshake import InvalidHandshake  # noqa
    except ImportError:
        _LOGGER.warning(
            "Applying workaround for "
            "https://github.com/beerfactory/hbmqtt/issues/138"
        )
        websockets.handshake.InvalidHandshake = (
            websockets.exceptions.InvalidHandshake
        )

    from hbmqtt.client import MQTTClient, ConnectException, ClientException

    logging.getLogger("hbmqtt.client.plugins.packet_logger_plugin").setLevel(
        logging.WARNING
    )

    client_id = "blus_{hostname}_{time}".format(
        hostname=platform.node(), time=time.time()
    )

    mqtt = MQTTClient(client_id=client_id)

    def publish(path, payload):
        topic = topic_for_path(path)
        _LOGGER.debug("Publishing on %s: %s", topic, payload)

        async def publish_task():
            try:
                await mqtt.publish(
                    topic, payload.encode("utf-8"), retain=False
                )
            except Exception as e:
                _LOGGER.error("Failed to publish: %s", e)

        loop.create_task(publish_task())

    class Observer(DeviceObserver):
        def async_seen(self, manager, path, device):
            assert is_mainthread()
            _LOGGER.debug("async seen %s", path)
            if "RSSI" in device:
                device["_quality"] = quality_from_dbm(device["RSSI"])
            payload = json.dumps(device)
            publish(path, payload)

        def async_unseen(self, manager, path):
            _LOGGER.debug("async unseen %s", path)
            publish(path, None)

        def seen(self, manager, path, device):
            assert not is_mainthread()
            loop.call_soon_threadsafe(self.async_seen, manager, path, device)

        def unseen(self, manager, path):
            assert not is_mainthread()
            loop.call_soon_threadsafe(self.async_unseen, manager, path)

    async def scanner_task():
        def scanner_thread():
            assert not is_mainthread()
            try:
                _LOGGER.debug("scanner started")
                DeviceManager(Observer()).scan()
            finally:
                _LOGGER.debug("scanner thread kthxbye")

        try:
            await loop.run_in_executor(None, scanner_thread)
        finally:
            _LOGGER.info("Scanner task: kthxbye")

    _LOGGER.debug("Using MQTT url from mosquitto_pub")
    mqtt_config = read_mqtt_config()
    try:
        username = mqtt_config["username"]
        password = mqtt_config["password"]
        host = mqtt_config["host"]
        port = mqtt_config["port"]
        url = "mqtts://{username}:{password}@{host}:{port}".format(
            username=username, password=password, host=host, port=port
        )

        await mqtt.connect(url, cleansession=False, cafile=certifi.where())
        _LOGGER.info("Connected to MQTT server")
    except ConnectException as e:
        _LOGGER.error("Could not connect to MQTT server: %s", e)
        return
    except Exception as e:
        _LOGGER.error("Could not read credentials: %s", e)
        return

    async def mqtt_task():
        while True:
            _LOGGER.debug("Waiting for messages")
            try:
                message = await mqtt.deliver_message()
                packet = message.publish_packet
                topic = packet.variable_header.topic_name
                payload = packet.payload.data.decode("ascii")
                _LOGGER.debug("got message on %s: %s", topic, payload)
                # FIXME: handle commands?
            except ClientException as e:
                _LOGGER.error("MQTT Client exception: %s", e)
            except asyncio.CancelledError:
                _LOGGER.debug("mqtt cancelled, disconnecting")
                await mqtt.disconnect()
                _LOGGER.info("mqtt disconnected")
                raise

    await asyncio.gather(scanner_task(), mqtt_task())
