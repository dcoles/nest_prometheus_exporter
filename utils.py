import asyncio
import json
import logging
import time
from contextlib import contextmanager

import aiohttp


def read_config(filename: str) -> dict:
    """Read JSON formatted config file."""
    with open(filename) as f:
        return json.load(f)


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
def span(name, *, level=logging.DEBUG):
    """Log a span of code."""
    logging.log(level, 'START %s', name, extra={'span': name})
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dur = time.perf_counter() - t0
        logging.log(level, f'END %s (dur=%0.3fs)', name, dur, extra={'span': name, 'dur': dur})


