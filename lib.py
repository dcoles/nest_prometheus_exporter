import argparse
import asyncio
import json
import logging
import time
from contextlib import contextmanager

import aiohttp
import aiohttp.web as web
import prometheus_client

router = web.RouteTableDef()


@router.get('/')
async def _index(_: web.Response):
    html = '<a href="/metrics">Metrics</a>'
    return web.Response(text=html, content_type='text/html')


@router.get('/metrics')
async def _metrics(_: web.Request):
    body = prometheus_client.generate_latest()
    return web.Response(
        body=body,
        content_type='text/plain; version=0.0.4',
        charset='utf-8')


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9001)
    parser.add_argument('-c', '--config', type=config, default='config.json')

    return parser.parse_args()


def config(filename: str) -> dict:
    """Read JSON formatted config file."""
    try:
        with open(filename) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise argparse.ArgumentError(f'ERROR: Failed to read config: {e}')


async def prometheus_exporter(run, *args, host='127.0.0.1', port=9001):
    """Start serving a Prometheus exporter."""
    app = web.Application()
    app.router.add_routes(router)
    await start_application(app, host, port)

    await run(*args)


async def start_application(app: web.Application, host: str, port: int):
    """Start `aiohttp` site."""
    runner = web.AppRunner(app)
    await runner.setup()

    if host in ['', '0.0.0.0', '::']:
        url = f'http://127.0.0.1:{port}/metrics'
    else:
        url = f'http://{host}:{port}/metrics'

    logging.info('Listening on %s:%d (%s)', host, port, url)
    site = web.TCPSite(runner, host, port)
    await site.start()

    return site


async def with_connection_retry(func, *args, backoff=30):
    """Call a function and retry on connection errors."""
    while True:
        try:
            return await func(*args)
        except aiohttp.ClientConnectorError as e:
            logging.error('Connection failed: %s', e)

        await asyncio.sleep(backoff)


async def periodic(func, *args, update_interval=60):
    """Call a function periodically"""
    t_next = time.monotonic()
    while True:
        now = time.monotonic()
        while now < t_next:
            await asyncio.sleep(t_next - now)
            now = time.monotonic()

        await func(*args)

        t_next += update_interval


@contextmanager
def span(name, *, level=logging.DEBUG, logger=logging):
    """Log a span of code."""
    logger.log(level, 'START %s', name, extra={'span': name})
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dur = time.perf_counter() - t0
        logging.log(level, f'END %s (dur=%0.3fs)', name, dur, extra={'span': name, 'dur': dur})
