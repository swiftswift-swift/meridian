"""Redis-backed cache and rate limiter.

Used when REDIS_URL is set. Both degrade to returning "allowed" or "miss" if Redis becomes
unreachable mid-flight: a cache outage must not take the product down, and a rate limiter that
fails closed would turn a Redis blip into a total outage. The trade is stated in
docs/runbook.md.
"""

from __future__ import annotations

import time

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


class RedisCache:
    def __init__(self, client: Redis, *, namespace: str = "meridian:cache") -> None:
        self._client = client
        self._namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    async def get(self, key: str) -> str | None:
        try:
            value = await self._client.get(self._key(key))
        except RedisError as exc:
            logger.warning("cache.unavailable", operation="get", error=str(exc))
            return None
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            await self._client.set(self._key(key), value, ex=ttl_seconds)
        except RedisError as exc:
            logger.warning("cache.unavailable", operation="set", error=str(exc))

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(self._key(key))
        except RedisError as exc:
            logger.warning("cache.unavailable", operation="delete", error=str(exc))


class RedisRateLimiter:
    """Fixed-window counters shared across every API process."""

    def __init__(self, client: Redis, *, namespace: str = "meridian:ratelimit") -> None:
        self._client = client
        self._namespace = namespace

    async def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        redis_key = f"{self._namespace}:{key}:{window_start}"
        try:
            pipeline = self._client.pipeline()
            pipeline.incr(redis_key)
            # Expiry is set on every increment rather than only the first: a SET without a TTL
            # after a Redis restart would leave the counter permanently stuck at the limit.
            pipeline.expire(redis_key, window_seconds + 1)
            count, _ = await pipeline.execute()
        except RedisError as exc:
            logger.warning("ratelimit.unavailable", error=str(exc))
            return True, 0

        if int(count) > limit:
            return False, max(1, window_start + window_seconds - now)
        return True, 0
