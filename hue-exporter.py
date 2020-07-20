#!/usr/bin/env python3
"""Prometheus Exporter for Philips Hue."""
import argparse
import asyncio
import json
import logging
import math
import sys

import aiohttp
from aiohttp import web
import prometheus_client

PROMETHEUS_PORT = 9103

hue_temperature_c = prometheus_client.Gauge(
    'hue_temperature_c', 'Temperature (°C)',
    ['sensorid', 'uniqueid'])


def update_zll_temperature_metrics(sensor, sensorid: str):
    def l(metric):
        return metric.labels(sensorid=sensorid, uniqueid=sensor['uniqueid'])

    state = sensor['state']
    config = sensor['config']
    reachable = config['reachable']

    temp = state['temperature'] / 100 if reachable else math.nan  # Fixed point (scaling factor: 100)
    l(hue_temperature_c).set(temp)


class HueAPI:
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

    config: dict = global_config.get('hue')
    if not config:
        print('ERROR: Config is missing "hue" section', file=sys.stderr)
        sys.exit(2)

    ipaddress: str = config.get('ipaddress')
    if not ipaddress:
        print('ERROR: Config is missing "hue.ipaddress"', file=sys.stderr)
        sys.exit(2)

    username: dict = config.get('username')
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

    update_interval = 60  # sec
    async with aiohttp.ClientSession() as s:
        api = HueAPI(s, ipaddress, username)

        while True:
            sensors = await api.sensors()
            for sensorid, sensor in sensors.items():
                if sensor['type'] == 'ZLLTemperature':
                    update_zll_temperature_metrics(sensor, sensorid=sensorid)

            await asyncio.sleep(update_interval)


if __name__ == '__main__':
    asyncio.run(main())
