"""Minimal in-process TTL cache for read-heavy, slowly-changing query
results (dashboard analytics) that don't need per-request freshness.

Not a general caching layer: no eviction beyond TTL expiry, no cross-process
invalidation, no locking against duplicate concurrent misses. Deliberately
small — swap for Redis if this ever needs to be shared across worker
processes or the memory footprint becomes worth managing.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

_store: dict[str, tuple[float, object]] = {}


async def cached(key: str, ttl_seconds: float, factory: Callable[[], Awaitable[T]]) -> T:
    """Returns the cached value for `key` if younger than `ttl_seconds`,
    otherwise awaits `factory()`, caches the result, and returns it."""
    now = time.monotonic()
    hit = _store.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]  # type: ignore[return-value]
    value = await factory()
    _store[key] = (now + ttl_seconds, value)
    return value
