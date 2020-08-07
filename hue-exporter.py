#!/usr/bin/env python3
"""Prometheus Exporter for Philips Hue."""
import asyncio
import logging
import math

import aiohttp
import prometheus_client

from lib import parse_args, prometheus_exporter, with_connection_retry, periodic, span

hue_sensor_temperature_c = prometheus_client.Gauge(
    'hue_sensor_temperature_c', 'Temperature (°C)',
    ['sensorid', 'uniqueid'])
hue_sensor_lightlevel = prometheus_client.Gauge(
    'hue_sensor_lightlevel', 'Light level (Lux)',
    ['sensorid', 'uniqueid'])
hue_sensor_lightlevel_raw = prometheus_client.Gauge(
    'hue_sensor_lightlevel_raw', 'Light level (raw)',
    ['sensorid', 'uniqueid'])


async def run(config: dict):
    config = config.get('hue')
    if not config:
        raise RuntimeError('Config is missing "hue" section')

    ipaddress: str = config.get('ipaddress')
    if not ipaddress:
        raise RuntimeError('Config is missing "hue.ipaddress"')

    username: str = config.get('username')
    if not username:
        raise RuntimeError('Config is missing "hue.username" section')

    async with aiohttp.ClientSession() as s:
        api = HueAPI(s, config['ipaddress'], config['username'])
        await with_connection_retry(periodic, update, api)


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
    with span('get hue sensors', logger=logging):
        sensors = await api.sensors()

    for sensorid, sensor in sensors.items():
        if sensor['type'] == api.ZLL_TEMPERATURE:
            update_temperature_metrics(sensor, sensorid=sensorid)
        elif sensor['type'] == api.ZLL_LIGHTLEVEL:
            update_lightlevel_metrics(sensor, sensorid=sensorid)


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


if __name__ == '__main__':
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(prometheus_exporter(run, args.config, host=args.host, port=args.port))
