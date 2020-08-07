#!/usr/bin/env python3
"""Prometheus Exporter for OpenWeather."""
import asyncio
import logging
import math
import sys
from functools import partial
from urllib.parse import quote
from typing import *

import aiohttp
import prometheus_client

from lib import parse_args, prometheus_exporter, with_connection_retry, periodic, span

UPDATE_INTERVAL = 300  # sec
KELVIN_CELSIUS_OFFSET = -273.15

logger = logging.getLogger(__name__)

owm_temperature = prometheus_client.Gauge(
    'owm_temperature', 'Temperature (K)',
    ['location', 'lat', 'long'])
owm_temperature_c = prometheus_client.Gauge(
    'owm_temperature_c', 'Temperature (°C)',
    ['location', 'lat', 'long'])
owm_temperature_feels_like = prometheus_client.Gauge(
    'owm_temperature_feels_like', 'Temperature accounting for human perception of weather (K)',
    ['location', 'lat', 'long'])
owm_temperature_feels_like_c = prometheus_client.Gauge(
    'owm_temperature_feels_like_c', 'Temperature accounting for human perception of weather (°C)',
    ['location', 'lat', 'long'])
owm_pressure = prometheus_client.Gauge(
    'owm_pressure', 'Atmospheric pressure (hPa)',
    ['location', 'lat', 'long'])
owm_humidity = prometheus_client.Gauge(
    'owm_humidity', 'Humidity (%)',
    ['location', 'lat', 'long'])
owm_wind_speed = prometheus_client.Gauge(
    'owm_wind_speed', 'Wind speed (m/s)',
    ['location', 'lat', 'long'])
owm_wind_gust = prometheus_client.Gauge(
    'owm_wind_gust', 'Wind gust (m/s)',
    ['location', 'lat', 'long'])
owm_wind_degrees = prometheus_client.Gauge(
    'owm_wind_degrees', 'Wind direction (degrees)',
    ['location', 'lat', 'long'])


async def run(config):
    config = config.get('openweather')
    if not config:
        print('ERROR: Config is missing "openweather" section', file=sys.stderr)
        sys.exit(2)

    appid = config.get('appid')
    if not appid:
        print('ERROR: Config is missing "openweather.appid"', file=sys.stderr)
        sys.exit(2)

    async with aiohttp.ClientSession() as s:
        openweather = OpenWeather(s, appid=config['appid'])
        await with_connection_retry(
            partial(periodic, update, openweather, config['locations'], update_interval=UPDATE_INTERVAL))


class OpenWeather:
    class OneCallResponse:
        def __init__(self, data):
            self.data = data

        @property
        def lat(self):
            return self.data['lat']

        @property
        def long(self):
            return self.data['lon']

        @property
        def temp(self):
            return self.data['current']['temp']

        @property
        def temp_c(self):
            return self.temp + KELVIN_CELSIUS_OFFSET

        @property
        def feels_like(self):
            return self.data['current']['feels_like']

        @property
        def feels_like_c(self):
            return self.feels_like + KELVIN_CELSIUS_OFFSET

        @property
        def pressure(self):
            return self.data['current']['pressure']

        @property
        def humidity(self):
            return self.data['current']['humidity']

        @property
        def wind_speed(self):
            return self.data['current']['wind_speed']

        @property
        def wind_gust(self):
            return self.data['current'].get('wind_gust', math.nan)

        @property
        def wind_deg(self):
            return self.data['current']['wind_deg']

        def __str__(self):
            return f'{self.temp_c:0.1f}°C (at {self.lat}, {self.long})'

        def __repr__(self):
            return f'{self.__class__.__name__}({self.data!r})'

    def __init__(self, session: aiohttp.ClientSession, appid: str):
        self.session = session
        self.appid = appid

    async def onecall(self, lat_long: (int, int)) -> OneCallResponse:
        lat, long = lat_long
        appid = quote(self.appid)

        url = f'https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={long}&appid={appid}'
        response = await self.session.get(url)
        response.raise_for_status()

        data = await response.json()
        return self.OneCallResponse(data)


async def update(openweather: OpenWeather, locations: Dict[str, Dict]):
    for location, cfg in locations.items():
        lat, long = cfg['lat'], cfg['long']

        logger.info('Fetching weather for %s (%d, %d)', location, lat, long)
        with span('get oneweather onecall', logger=logger):
            onecall = await openweather.onecall((lat, long))

        logger.debug('Response: %r', onecall)
        update_openweather_metrics(onecall, location=location)


def update_openweather_metrics(onecall: OpenWeather.OneCallResponse, location: str):
    def l(metric):
        return metric.labels(location=location, lat=onecall.lat, long=onecall.long)

    l(owm_temperature).set(onecall.temp)
    l(owm_temperature_c).set(onecall.temp_c)
    l(owm_temperature_feels_like).set(onecall.feels_like)
    l(owm_temperature_feels_like_c).set(onecall.feels_like_c)
    l(owm_pressure).set(onecall.pressure)
    l(owm_humidity).set(onecall.humidity)

    l(owm_wind_speed).set(onecall.wind_speed)
    l(owm_wind_gust).set(onecall.wind_gust)
    l(owm_wind_degrees).set(onecall.wind_deg)


if __name__ == '__main__':
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(prometheus_exporter(run, args.config, host=args.host, port=args.port))
