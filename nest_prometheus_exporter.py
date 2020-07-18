#!/usr/bin/env python3
"""Prometheus Exporter for Nest Thermostat."""
import argparse
import asyncio
import concurrent.futures
import datetime
import email
import hashlib
import json
import logging
import sys
from typing import *

from aiohttp import web
import prometheus_client
import nest

NEST_API = 'https://developer-api.nest.com'
MIN_INTERVAL = datetime.timedelta(seconds=59)  # ~ 1 minute
PROMETHEUS_PORT = 9111

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


def update_thermostat_metrics(thermostat: nest.nest.Thermostat):
    """Update Prometheus thermostat metrics."""
    logging.debug('Updating %s (%s)', thermostat.name, thermostat.device_id)

    id = thermostat.device_id
    device = thermostat._device  # for getting temperate in deg. C

    c = device['ambient_temperature_c']
    f = device['ambient_temperature_f']
    logging.debug('Temperature %.1f°C, %.0f°F (%.1f°C)', c, f, c_to_f(f))

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


def last_modified_headers(dt: datetime.datetime) -> dict:
    last_modified = email.utils.format_datetime(dt, usegmt=True)
    return {
        'Last-Modified': last_modified,
        'ETag': f'"{hashlib.md5(last_modified.encode()).hexdigest()}"',
    }


def read_config(filename: str) -> dict:
    with open(filename) as f:
        return json.load(f)


async def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', default='config.json')
    args = parser.parse_args()

    try:
        global_config = read_config(args.config)
    except (OSError, ValueError) as e:
        print(f'ERROR: Failed to read config: {e}', file=sys.stderr)
        sys.exit(1)

    config: dict = global_config.get('nest')
    if not config:
        print('ERROR: Config is missing "nest" section', file=sys.stderr)
        sys.exit(2)

    access_token: dict = config.get('access_token')
    if not access_token:
        print('ERROR: Config is missing "nest.access_token"', file=sys.stderr)
        sys.exit(2)

    napi = nest.Nest(access_token=access_token['access_token'])
    last_updated: Optional[datetime.datetime] = None

    def _update():
        nonlocal last_updated

        logging.debug('Updating...')
        last_updated = datetime.datetime.now(tz=datetime.timezone.utc)
        for t in napi.thermostats:
            update_thermostat_metrics(t)

    # Force initial update
    _update()

    routes = web.RouteTableDef()

    @routes.get('/')
    async def _index(_: web.Response):
        html = '<a href="/metrics">Metrics</a>'
        return web.Response(text=html, content_type='text/html')

    @routes.get('/metrics')
    async def _metrics(_: web.Request):
        body = prometheus_client.generate_latest()
        return web.Response(
            body=body,
            headers=last_modified_headers(last_updated),
            content_type='text/plain; version=0.0.4',
            charset='utf-8')

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()

    host, port = '127.0.0.1', 9101
    logging.info('Listening on %s:%d', host, port)
    site = web.TCPSite(runner, host, port)
    await site.start()

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        while True:
            await loop.run_in_executor(pool, napi.update_event.wait)
            napi.update_event.clear()
            _update()


if __name__ == '__main__':
    asyncio.run(main())
