#!/usr/bin/env python3
"""Prometheus Exporter for Philips Hue."""
import argparse
import asyncio
import logging
import math
import sys

import aiohttp
from aiohttp import web
import prometheus_client

from utils import read_config, with_connection_retry, periodic, span

PROMETHEUS_PORT = 9103

hue_sensor_temperature_c = prometheus_client.Gauge(
    'hue_sensor_temperature_c', 'Temperature (°C)',
    ['sensorid', 'uniqueid'])
hue_sensor_lightlevel = prometheus_client.Gauge(
    'hue_sensor_lightlevel', 'Light level (Lux)',
    ['sensorid', 'uniqueid'])
hue_sensor_lightlevel_raw = prometheus_client.Gauge(
    'hue_sensor_lightlevel_raw', 'Light level (raw)',
    ['sensorid', 'uniqueid'])


def update_temperature_metrics(sensor: dict, sensorid: str):
    def l(metric):
        return metric.labels(sensorid=sensorid, uniqueid=sensor['uniqueid'])

    l(hue_sensor_temperature_c).set(get_state(sensor, 'temperature') / 100)  # Fixed point (scaling factor: 100)


def update_lightlevel_metrics(sensor: dict, sensorid: str):
    def l(metric):
        return metric.labels(sensorid=sensorid, uniqueid=sensor['uniqueid'])

    lightlevel_raw = get_state(sensor, 'lightlevel')
    lightlevel_lux = 10**((lightlevel_raw - 1) / 10000)  # 10000 log10(lux) + 1

    l(hue_sensor_lightlevel).set(lightlevel_lux)
    l(hue_sensor_lightlevel_raw).set(lightlevel_raw)


def get_state(sensor: dict, field: str) -> float:
    if not sensor['config']['reachable']:
        return math.nan

    state = sensor['state'][field]
    return state if state is not None else math.nan


class HueAPI:
    ZLL_TEMPERATURE = 'ZLLTemperature'
    ZLL_LIGHTLEVEL = 'ZLLLightLevel'

    def __init__(self, session: aiohttp.ClientSession, ipaddress: str, username: str):
        self.session = session
        self.ipaddress = ipaddress
        self.username = username

    async def sensors(self):
        url = f'http://{self.ipaddress}/api/{self.username}/sensors'
        response = await self.session.get(url)
        response.raise_for_status()

        data = await response.json()
        return data


async def update(api: HueAPI):
    """Update metrics."""
    with span('get hue sensors'):
        sensors = await api.sensors()

    for sensorid, sensor in sensors.items():
        if sensor['type'] == api.ZLL_TEMPERATURE:
            update_temperature_metrics(sensor, sensorid=sensorid)
        elif sensor['type'] == api.ZLL_LIGHTLEVEL:
            update_lightlevel_metrics(sensor, sensorid=sensorid)


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

    config: dict = global_config.get('hue')
    if not config:
        print('ERROR: Config is missing "hue" section', file=sys.stderr)
        sys.exit(2)

    ipaddress: str = config.get('ipaddress')
    if not ipaddress:
        print('ERROR: Config is missing "hue.ipaddress"', file=sys.stderr)
        sys.exit(2)

    username: str = config.get('username')
    if not username:
        print('ERROR: Config is missing "hue.username" section', file=sys.stderr)
        sys.exit(2)

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
            content_type='text/plain; version=0.0.4',
            charset='utf-8')

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()

    host, port = '127.0.0.1', PROMETHEUS_PORT
    url = f'http://{host or "127.0.0.1"}:{port}/metrics'
    logging.info('Listening on %s:%d (%s)', host, port, url)
    site = web.TCPSite(runner, host, port)
    await site.start()

    async with aiohttp.ClientSession() as s:
        api = HueAPI(s, ipaddress, username)
        await with_connection_retry(periodic, update, api)


if __name__ == '__main__':
    asyncio.run(main())
