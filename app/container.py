"""The single composition root.

Every concrete adapter is chosen here and nowhere else. A reader who wants to know what this
deployment actually does -- which model, which queue, which cache -- reads this file and stops.

No module-level instance exists. The API creates one per application, the worker creates its
own, and a test creates one per case, which is what makes tests independent without monkey
patching.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from app.domain.ports import CachePort, ClockPort, RateLimiterPort
from app.infra.db import Database
from app.settings import EmbeddingProvider, LlmProvider, Settings, ToolsMode

logger = structlog.get_logger(__name__)


class SystemClock:
    """The real clock. Tests substitute a frozen one through ClockPort."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return asyncio.get_event_loop().time()


@dataclass(slots=True)
class ServiceContainer:
    """Owns every long-lived collaborator and the shutdown order between them."""

    settings: Settings
    database: Database
    clock: ClockPort
    cache: CachePort
    rate_limiter: RateLimiterPort
    _redis: Any = None
    _closed: bool = False

    @classmethod
    async def create(cls, settings: Settings) -> ServiceContainer:
        settings.ensure_directories()
        database = Database.from_settings(settings)

        redis_client: Any = None
        cache: CachePort
        rate_limiter: RateLimiterPort

        if settings.redis_url:
            redis_client = await cls._connect_redis(settings.redis_url)

        if redis_client is not None:
            # Imported lazily so a deployment without Redis never loads the client library.
            from app.adapters.cache.redis_cache import RedisCache, RedisRateLimiter  # noqa: PLC0415

            cache = RedisCache(redis_client)
            rate_limiter = RedisRateLimiter(redis_client)
        else:
            from app.adapters.cache.memory_cache import (  # noqa: PLC0415
                InMemoryCache,
                InMemoryRateLimiter,
            )

            cache = InMemoryCache()
            rate_limiter = InMemoryRateLimiter()

        container = cls(
            settings=settings,
            database=database,
            clock=SystemClock(),
            cache=cache,
            rate_limiter=rate_limiter,
            _redis=redis_client,
        )
        container._log_configuration()
        return container

    @staticmethod
    async def _connect_redis(url: str) -> Any:
        """Connect to Redis, or return None and carry on without it.

        A configured-but-absent Redis is the normal case on a developer machine that has not
        started Docker. Falling back with one warning beats refusing to boot.
        """
        try:
            from redis.asyncio import Redis  # noqa: PLC0415
            from redis.exceptions import RedisError  # noqa: PLC0415

            client: Any = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            await client.ping()
        except (ImportError, OSError, RedisError, TimeoutError) as exc:
            logger.warning(
                "redis.unavailable",
                url=url,
                error=str(exc),
                consequence="using the in-process queue and in-memory cache instead",
            )
            return None
        logger.info("redis.connected", url=url)
        return client

    def _log_configuration(self) -> None:
        """One line stating what this process will actually do.

        Worth its space: the commonest confusion when a demo behaves oddly is not knowing
        whether it is on the scripted model or a real one.
        """
        logger.info(
            "container.ready",
            app_env=self.settings.app_env.value,
            llm_provider=self.settings.llm_provider.value,
            model=(
                "scripted"
                if self.settings.llm_provider is LlmProvider.SCRIPTED
                else self.settings.openai_model
            ),
            embeddings=self.settings.embedding_provider.value,
            tools_mode=self.settings.tools_mode.value,
            queue="redis" if self._redis is not None else "in-process",
            offline=self.settings.offline,
        )

    @property
    def redis(self) -> Any:
        return self._redis

    @property
    def has_redis(self) -> bool:
        return self._redis is not None

    def describe_providers(self) -> dict[str, Any]:
        """Shown on the Settings page so a user can see what is wired without reading logs."""
        scripted = self.settings.llm_provider is LlmProvider.SCRIPTED
        return {
            "llm_provider": self.settings.llm_provider.value,
            "model": "scripted-demo" if scripted else self.settings.openai_model,
            "scripted": scripted,
            "embedding_provider": self.settings.embedding_provider.value,
            "embeddings_offline": self.settings.embedding_provider is EmbeddingProvider.HASH,
            "tools_mode": self.settings.tools_mode.value,
            "tools_live": self.settings.tools_mode is ToolsMode.LIVE,
            "queue": "redis" if self.has_redis else "in-process",
            "cache": "redis" if self.has_redis else "in-memory",
            "fully_offline": self.settings.offline,
        }

    async def aclose(self) -> None:
        """Release resources in reverse dependency order, tolerating partial failure.

        A shutdown path that raises on the first problem leaves later resources leaked, which is
        how a worker ends up holding a database connection after Ctrl+C.
        """
        if self._closed:
            return
        self._closed = True
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as exc:  # noqa: BLE001 - shutdown must continue regardless
                logger.warning("redis.close_failed", error=str(exc))
        try:
            await self.database.dispose()
        except Exception as exc:  # noqa: BLE001 - as above
            logger.warning("database.dispose_failed", error=str(exc))
        logger.info("container.closed")
