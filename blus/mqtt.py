# -*- mode: python; coding: utf-8 -*-

import logging
from time import time
from json import dumps as dump_json
from os.path import join, expanduser
from os import environ as env
import string
from platform import node as hostname
from hbmqtt.client import MQTTClient, ConnectException, ClientException
import asyncio
import certifi

_LOGGER = logging.getLogger(__name__)


TOPIC_WHITELIST = "_-" + string.ascii_letters + string.digits
TOPIC_SUBSTITUTE = "_"


def make_valid_hass_single_topic_level(s):
    """Transform a multi level topic to a single level.

    >>> make_valid_hass_single_topic_level('foo/bar/baz')
    'foo_bar_baz'

    >>> make_valid_hass_single_topic_level('hello å ä ö')
    'hello______'
    """
    return whitelisted(s, TOPIC_WHITELIST, TOPIC_SUBSTITUTE)


def make_topic(*levels):
    """Create a valid topic.

    >>> make_topic('foo', 'bar')
    'foo/bar'

    >>> make_topic(('foo', 'bar'))
    'foo/bar'
    """
    if len(levels) == 1 and isinstance(levels[0], tuple):
        return make_topic(*levels[0])
    return "/".join(levels)


def read_mqtt_config():
    """Read credentials from ~/.config/mosquitto_pub."""
    fname = join(
        env.get("XDG_CONFIG_HOME", join(expanduser("~"), ".config")),
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


async def run(config):

    logging.getLogger("hbmqtt.client.plugins.packet_logger_plugin").setLevel(
        logging.WARNING
    )

    client_id = "blus_{hostname}_{time}".format(
        hostname=hostname(), time=time()
    )

    mqtt = MQTTClient(client_id=client_id)
    url = config.get("mqtt_url")

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
    except Exception as e:
        exit(e)

    async def mqtt_task():
        try:
            await mqtt.connect(url, cleansession=False, cafile=certifi.where())
            _LOGGER.info("Connected to MQTT server")
        except ConnectException as e:
            exit("Could not connect to MQTT server: %s" % e)
        while True:
            _LOGGER.debug("Waiting for messages")
            try:
                message = await mqtt.deliver_message()
                packet = message.publish_packet
                topic = packet.variable_header.topic_name
                payload = packet.payload.data.decode("ascii")
                _LOGGER.debug("got message on %s: %s", topic, payload)
            except ClientException as e:
                _LOGGER.error("MQTT Client exception: %s", e)

    asyncio.create_task(mqtt_task())  # pylint:disable=no-member


if __name__ == "__main__":
    pass
