#!/usr/bin/env python3
"""Prometheus Exporter for Nest Thermostat."""

import asyncio
import concurrent.futures
import datetime
import logging
import sys

import nest
import prometheus_client

from lib import parse_args, prometheus_exporter

NEST_API = 'https://developer-api.nest.com'
MIN_INTERVAL = datetime.timedelta(seconds=59)  # ~ 1 minute

logger = logging.getLogger(__name__)

last_connection = prometheus_client.Gauge(
    'nest_last_connection',
    'Unix timestamp (seconds) of the last successful interaction with the Nest service',
    ['thermostat_id'])
is_online = prometheus_client.Gauge(
    'nest_is_online',
    'Device connection status with the Nest Service (1 for online, 0 for offline)',
    ['thermostat_id'])
ambient_temperature_c = prometheus_client.Gauge(
    'nest_ambient_temperature_c',
    'Temperature, measured at the device, in half degrees Celsius (0.5°C)',
    ['thermostat_id'])
ambient_temperature_f = prometheus_client.Gauge(
    'nest_ambient_temperature_f',
    'Temperature, measured at the device, in whole degrees Fahrenheit (°F)',
    ['thermostat_id'])
humidity = prometheus_client.Gauge(
    'nest_humidity',
    'Humidity, in percent (%) format, measured at the device, rounded to the nearest 5%',
    ['thermostat_id'])
heating = prometheus_client.Gauge(
    'nest_heating',
    'Indicates whether HVAC system is actively heating',
    ['thermostat_id'])
cooling = prometheus_client.Gauge(
    'nest_cooling',
    'Indicates whether HVAC system is actively cooling',
    ['thermostat_id'])
target_temperature_high_c = prometheus_client.Gauge(
    'nest_target_temperature_high_c',
    'Maximum target temperature, displayed in half degrees Celsius (0.5°C)',
    ['thermostat_id'])
target_temperature_low_c = prometheus_client.Gauge(
    'nest_target_temperature_low_c',
    'Minimum target temperature, displayed in half degrees Celsius (0.5°C)',
    ['thermostat_id'])
target_temperature_high_f = prometheus_client.Gauge(
    'nest_target_temperature_high_f',
    'Maximum target temperature, displayed in whole degrees Fahrenheit (°F)',
    ['thermostat_id'])
target_temperature_low_f = prometheus_client.Gauge(
    'nest_target_temperature_low_f',
    'Minimum target temperature, displayed in whole degrees Fahrenheit (°F)',
    ['thermostat_id'])
time_to_target = prometheus_client.Gauge(
    'nest_time_to_target',
    'The time, in minutes, that it will take for the structure to reach the target temperature',
    ['thermostat_id'])


async def run(config):
    config = config.get('nest')
    if not config:
        print('ERROR: Config is missing "nest" section', file=sys.stderr)
        sys.exit(2)

    access_token = config.get('access_token')
    if not access_token:
        print('ERROR: Config is missing "nest.access_token"', file=sys.stderr)
        sys.exit(2)

    napi = nest.Nest(access_token=config['access_token']['access_token'])

    def _update():
        logger.debug('Updating nest state')
        for t in napi.thermostats:
            update_thermostat_metrics(t)

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        while True:
            await loop.run_in_executor(pool, napi.update_event.wait)
            napi.update_event.clear()
            _update()


def update_thermostat_metrics(thermostat: nest.nest.Thermostat):
    """Update Prometheus thermostat metrics."""
    logger.debug('Updating %s (%s)', thermostat.name, thermostat.device_id)

    id = thermostat.device_id
    device = thermostat._device  # for getting temperate in deg. C

    c = device['ambient_temperature_c']
    f = device['ambient_temperature_f']
    logger.debug('Temperature %.1f°C, %.0f°F (%.1f°C)', c, f, c_to_f(f))

    last_connection.labels(thermostat_id=id).set(
        parse_timestamp(thermostat.last_connection).timestamp())
    is_online.labels(thermostat_id=id).set(1 if thermostat.online else 0)

    ambient_temperature_c.labels(thermostat_id=id).set(device['ambient_temperature_c'])
    ambient_temperature_f.labels(thermostat_id=id).set(device['ambient_temperature_f'])
    humidity.labels(thermostat_id=id).set(thermostat.humidity)
    heating.labels(thermostat_id=id).set(1 if thermostat.hvac_state == 'heating' else 0)
    cooling.labels(thermostat_id=id).set(1 if thermostat.hvac_state == 'cooling' else 0)
    target_temperature_high_c.labels(thermostat_id=id).set(device['target_temperature_high_c'])
    target_temperature_low_c.labels(thermostat_id=id).set(device['target_temperature_low_c'])
    target_temperature_high_f.labels(thermostat_id=id).set(device['target_temperature_high_f'])
    target_temperature_low_f.labels(thermostat_id=id).set(device['target_temperature_low_f'])
    time_to_target.labels(thermostat_id=id).set(int(thermostat.time_to_target[1:]))


def c_to_f(temp_f):
    return (temp_f - 32) / 1.8


def parse_timestamp(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)


if __name__ == '__main__':
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(prometheus_exporter(run, args.config, host=args.host, port=args.port))
