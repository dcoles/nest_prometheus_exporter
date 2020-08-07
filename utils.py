import asyncio
import logging
import time
from contextlib import asynccontextmanager

import aiohttp


async def with_connection_retry(func, *args, backoff=30):
    """Call a function and retry on connection errors."""
    while True:
        try:
            return await func(*args)
        except aiohttp.ClientConnectorError as e:
            logging.error('Connection failed: %s', e)

        await asyncio.sleep(backoff)


@asynccontextmanager
async def span(name, *, level=logging.DEBUG):
    """Log a span of code."""
    logging.log(level, 'START %s', name, extra={'span': name})
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dur = time.perf_counter() - t0
        logging.log(level, f'END %s (dur=%0.3fs)', name, dur, extra={'span': name, 'dur': dur})
