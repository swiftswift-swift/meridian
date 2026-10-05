"""In-process cache and rate limiter, used when Redis is not configured.

These exist so the whole application runs on a laptop with nothing installed. The honest
limitation is that both are per-process: with several API workers each gets its own counters, so
the effective rate limit multiplies by the worker count. That is acceptable for local
development and recorded in docs/backlog.md; Redis is the answer for a real deployment.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

# Above this many tracked callers the limiter prunes stale windows rather than growing forever.
MAX_TRACKED_RATE_LIMIT_KEYS = 10_000


@dataclass(slots=True)
class _Entry:
    value: str
    expires_at: float


class InMemoryCache:
    """A TTL cache with opportunistic expiry.

    Expired keys are dropped on access rather than by a sweeper task: the cache is small, and a
    background task would be one more thing to shut down cleanly.
    """

    def __init__(self, max_entries: int = 2_000) -> None:
        self._entries: dict[str, _Entry] = {}
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                del self._entries[key]
                return None
            return entry.value

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        async with self._lock:
            if len(self._entries) >= self._max_entries:
                self._evict_locked()
            self._entries[key] = _Entry(value=value, expires_at=time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._entries.pop(key, None)

    def _evict_locked(self) -> None:
        """Drop expired entries, then the soonest-to-expire if that was not enough."""
        now = time.monotonic()
        for key in [k for k, v in self._entries.items() if v.expires_at <= now]:
            del self._entries[key]
        if len(self._entries) < self._max_entries:
            return
        oldest = sorted(self._entries.items(), key=lambda item: item[1].expires_at)
        for key, _ in oldest[: max(1, self._max_entries // 10)]:
            del self._entries[key]


class InMemoryRateLimiter:
    """Fixed-window counters.

    A fixed window admits up to twice the limit across a window boundary. A sliding window would
    avoid that, and the trade was taken deliberately: this limit exists to stop runaway clients,
    not to meter a paid quota.
    """

    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        async with self._lock:
            recorded_start, count = self._windows.get(key, (window_start, 0))
            if recorded_start != window_start:
                recorded_start, count = window_start, 0
            if count >= limit:
                retry_after = max(1, recorded_start + window_seconds - now)
                return False, retry_after
            self._windows[key] = (recorded_start, count + 1)
            if len(self._windows) > MAX_TRACKED_RATE_LIMIT_KEYS:
                self._prune_locked(window_start)
        return True, 0

    def _prune_locked(self, current_window: int) -> None:
        for key in [k for k, (start, _) in self._windows.items() if start < current_window]:
            del self._windows[key]
