#!/usr/bin/env python3
"""Prometheus Exporter for OpenWeather."""
import argparse
import asyncio
import json
import logging
import math
import sys

import aiohttp
from aiohttp import web
import prometheus_client

PROMETHEUS_PORT = 9102

owm_temperature = prometheus_client.Gauge(
    'owm_temperature', 'Temperature (K)',
    ['location', 'lat', 'long'])
owm_temperature_feels_like = prometheus_client.Gauge(
    'owm_temperature_feels_like', 'Temperature accounting for human perception of weather (K)',
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


class OneCallResponse:
    KELVIN_CELSIUS_OFFSET = -273.15

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
        return self.temp + self.KELVIN_CELSIUS_OFFSET

    @property
    def feels_like(self):
        return self.data['current']['feels_like']

    @property
    def feels_like_c(self):
        return self.feels_like + self.KELVIN_CELSIUS_OFFSET

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


def update_openweather_metrics(onecall: OneCallResponse, location: str):
    def l(metric):
        return metric.labels(location=location, lat=onecall.lat, long=onecall.long)

    l(owm_temperature).set(onecall.temp)
    l(owm_temperature_feels_like).set(onecall.feels_like)
    l(owm_pressure).set(onecall.pressure)
    l(owm_humidity).set(onecall.humidity)

    l(owm_wind_speed).set(onecall.wind_speed)
    l(owm_wind_gust).set(onecall.wind_gust)
    l(owm_wind_degrees).set(onecall.wind_deg)


async def fetch_onecall(s: aiohttp.ClientSession, lat_long: (int, int), appid: str) -> OneCallResponse:
    lat, long = lat_long
    url = f'https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={long}&appid={appid}'
    response = await s.get(url)
    response.raise_for_status()

    data = await response.json()
    return OneCallResponse(data)


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

    config: dict = global_config.get('openweather')
    if not config:
        print('ERROR: Config is missing "oneweather" section', file=sys.stderr)
        sys.exit(2)

    appid: str = config.get('appid')
    if not appid:
        print('ERROR: Config is missing "oneweather.appid"', file=sys.stderr)
        sys.exit(2)

    locations: dict = config.get('locations')
    if not locations:
        print('ERROR: Config is missing "oneweather.locations" section', file=sys.stderr)
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
        while True:
            for location, cfg in locations.items():
                lat, long = cfg['lat'], cfg['long']
                logging.info('Fetching weather for %s (%d, %d)', location, lat, long)
                onecall = await fetch_onecall(s, (lat, long), appid=appid)
                logging.debug('Response: %r', onecall)
                update_openweather_metrics(onecall, location=location)

            await asyncio.sleep(update_interval)


if __name__ == '__main__':
    asyncio.run(main())
