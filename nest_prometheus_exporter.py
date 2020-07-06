#!/usr/bin/env python3

"""Prometheus Exporter for Nest Thermostat."""

import asyncio
import datetime
import email
import hashlib
import json
import logging
import os
import sys
from urllib.parse import urljoin, quote

import aiohttp
from aiohttp import web
import prometheus_client

ACCESS_TOKEN = os.getenv('NEST_ACCESS_TOKEN')
THERMOSTAT_ID = os.getenv('NEST_THERMOSTAT_ID')
NEST_API = 'https://developer-api.nest.com'
MIN_INTERVAL = datetime.timedelta(seconds=59)  # ~ 1 minute
PROMETHEUS_PORT = 9111

last_connection = prometheus_client.Gauge(
    'nest_last_connection',
    'Unix timestamp (seconds) of the last successful interaction with the Nest service')
ambient_temperature_c = prometheus_client.Gauge(
    'nest_ambient_temperature_c',
    'Temperature, measured at the device, in half degrees Celsius (0.5°C)')
humidity = prometheus_client.Gauge(
    'nest_humidity',
    'Humidity, in percent (%) format, measured at the device, rounded to the nearest 5%')
heating = prometheus_client.Gauge(
    'nest_heating',
    'Indicates whether HVAC system is actively heating')
cooling = prometheus_client.Gauge(
    'nest_cooling',
    'Indicates whether HVAC system is actively cooling')
target_temperature_high_c = prometheus_client.Gauge(
    'nest_target_temperature_high_c',
    'Maximum target temperature, displayed in half degrees Celsius (0.5°C)')
target_temperature_low_c = prometheus_client.Gauge(
    'nest_target_temperature_low_c',
    'Minimum target temperature, displayed in half degrees Celsius (0.5°C)')


def update_metrics(state):
    """Update Prometheus metrics."""
    last_connection.set(parse_timestamp(state['last_connection']).timestamp())
    ambient_temperature_c.set(state['ambient_temperature_c'])
    humidity.set(state['humidity'])
    heating.set(1 if state['hvac_state'] == 'heating' else 0)
    cooling.set(1 if state['hvac_state'] == 'cooling' else 0)
    target_temperature_high_c.set(
        state['target_temperature_high_c'] if state['hvac_mode'] == 'heat-cool'
        else state['target_temperature_c'] if state['hvac_mode'] == 'cool'
        else float('nan'))
    target_temperature_low_c.set(
        state['target_temperature_low_c'] if state['hvac_mode'] == 'heat-cool'
        else state['target_temperature_c'] if state['hvac_mode'] == 'heat'
        else float('nan'))


def parse_timestamp(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)


class ThermostatCollector:
    def __init__(self, thermostat_id: str, access_token: str):
        self.thermostat_id = thermostat_id
        self.access_token = access_token

        self._lock = asyncio.Lock()
        self._state = {}
        self._last_updated = None

    async def get_latest_state(self):
        """Get latest thermostat state.

        If called more frequently than once per minute, this will return cached data.
        """
        async with self._lock:
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            if self._last_updated and self._last_updated + MIN_INTERVAL > now:
                # Already updated recently
                return self._state, self._last_updated

            logging.info('Updating thermostat state (last updated: %s)', self._last_updated)
            headers = {'Authorization': f'Bearer {self.access_token}'}
            url = urljoin(NEST_API, f'/devices/thermostats/{quote(THERMOSTAT_ID)}')

            async with aiohttp.ClientSession(headers=headers) as session:
                resp = await get(session, url)

            self._state = await resp.json()
            self._last_updated = datetime.datetime.now(tz=datetime.timezone.utc)

            return self._state, self._last_updated


async def get(session: aiohttp.ClientSession, url: str, max_redirects=10):
    """GET URL, following any redirects, including session headers."""
    request_info = None
    history = []

    for _ in range(max_redirects):
        resp = await session.get(url, allow_redirects=False)
        request_info = resp.request_info
        history.append(resp)
        resp.raise_for_status()

        if resp.status // 100 != 3:  # 3xx
            break

        url = resp.headers['Location']
        history.append(url)
    else:
        raise aiohttp.TooManyRedirects(request_info, tuple(history))

    return resp


def last_modified_headers(dt: datetime.datetime) -> dict:
    last_modified = email.utils.format_datetime(dt, usegmt=True)
    return {
        'Last-Modified': last_modified,
        'ETag': f'"{hashlib.md5(last_modified.encode()).hexdigest()}"',
    }


def main():
    logging.basicConfig(level=logging.DEBUG)

    if not ACCESS_TOKEN:
        logging.error('NEST_ACCESS_TOKEN not found in environment')
        sys.exit(1)

    if not THERMOSTAT_ID:
        logging.error('NEST_THERMOSTAT_ID not found in environment')
        sys.exit(1)

    try:
        access_token_obj = json.loads(ACCESS_TOKEN)
    except ValueError as e:
        logging.error('Failed to parse access token: %s', e)
        sys.exit(1)

    routes = web.RouteTableDef()
    collector = ThermostatCollector(THERMOSTAT_ID, access_token_obj['access_token'])

    @routes.get('/state')
    async def _state(_: web.Response):
        state, last_updated = await collector.get_latest_state()

        return web.json_response(state, headers=last_modified_headers(last_updated))

    @routes.get('/metrics')
    async def _metrics(_: web.Request):
        state, last_updated = await collector.get_latest_state()
        update_metrics(state)

        body = prometheus_client.generate_latest()
        return web.Response(
            body=body,
            headers=last_modified_headers(last_updated),
            content_type='text/plain; version=0.0.4',
            charset='utf-8')

    app = web.Application()
    app.add_routes(routes)
    web.run_app(app, host='127.0.0.1', port=9101)


if __name__ == '__main__':
    main()
