#!/usr/bin/env python3

"""Prometheus Exporter for Nest Thermostat."""

import json
import logging
import os
import sys
import time
from urllib.parse import urljoin, quote

import prometheus_client
import requests
import requests.auth

ACCESS_TOKEN = os.getenv('NEST_ACCESS_TOKEN')
THERMOSTAT_ID = os.getenv('NEST_THERMOSTAT_ID')
NEST_API = 'https://developer-api.nest.com'
POLL_INTERVAL = 60  # s
PROMETHEUS_PORT = 9111

ambient_temperature_c = prometheus_client.Gauge('nest_ambient_temperature_c',
                                                'Temperature, measured at the device, in half degrees Celsius (0.5°C)')
humidity = prometheus_client.Gauge('nest_humidity',
                                   'Humidity, in percent (%) format, measured at the device, rounded to the nearest 5%')
heating = prometheus_client.Gauge('nest_heating',
                                  'Indicates whether HVAC system is actively heating.')
cooling = prometheus_client.Gauge('nest_cooling',
                                  'Indicates whether HVAC system is actively cooling.')


class BearerAuth(requests.auth.AuthBase):
    """Perform HTTP auth using a "Bearer" token."""
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.headers['Authorization'] = 'Bearer {}'.format(self.token)
        return r


class URLFollower:
    """Follows 307 redirects and re-requests with full headers."""
    def __init__(self, url, max_redirects=3, session=None):
        self.url = url
        self.max_redirects = max_redirects
        self.session = session or requests

    def get(self, *args, **kwargs) -> requests.Response:
        for _ in range(self.max_redirects):
            r = self.session.get(self.url, *args, **kwargs, allow_redirects=False)
            if r.status_code != 307:
                break

            self.url = r.headers['Location']
        else:
            raise RuntimeError('Too many redirects')

        return r


def export_thermostat_state(state):
    ambient_temperature_c.set(state['ambient_temperature_c'])
    humidity.set(state['humidity'])
    heating.set(1 if state['hvac_state'] == 'heating' else 0)
    cooling.set(1 if state['hvac_state'] == 'cooling' else 0)


def with_raise_for_status(req):
    req.raise_for_status()
    return req


def main():
    logging.basicConfig(level=logging.DEBUG)

    if not ACCESS_TOKEN:
        logging.error('NEST_ACCESS_TOKEN not found in environment')
        sys.exit(1)

    if not THERMOSTAT_ID:
        logging.error('NEST_THERMOSTAT_ID not found in environment')
        sys.exit(1)

    access_token_object = json.loads(ACCESS_TOKEN)
    thermostat = URLFollower(urljoin(NEST_API, '/devices/thermostats/{}'.format(quote(THERMOSTAT_ID))))
    auth = BearerAuth(access_token_object['access_token'])

    prometheus_client.start_http_server(PROMETHEUS_PORT)

    logging.info("Polling...")
    while True:
        thermostat_state = with_raise_for_status(thermostat.get(auth=auth)).json()
        logging.debug('thermostat state: %s', json.dumps(thermostat_state))
        export_thermostat_state(thermostat_state)

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
