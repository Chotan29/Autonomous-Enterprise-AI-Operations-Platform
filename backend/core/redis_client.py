import json
from typing import Any

import redis.asyncio as aioredis

from backend.core.config import settings

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
            encoding="utf-8",
        )
    return _redis_pool


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


class RedisCache:
    """Simple typed cache wrapper."""

    def __init__(self, prefix: str, default_ttl: int = 300):
        self.prefix = prefix
        self.default_ttl = default_ttl

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        r = await get_redis()
        raw = await r.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        r = await get_redis()
        ttl = ttl if ttl is not None else self.default_ttl
        await r.setex(self._key(key), ttl, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        r = await get_redis()
        await r.delete(self._key(key))

    async def exists(self, key: str) -> bool:
        r = await get_redis()
        return bool(await r.exists(self._key(key)))

    async def expire(self, key: str, ttl: int) -> None:
        r = await get_redis()
        await r.expire(self._key(key), ttl)

    async def incr(self, key: str) -> int:
        r = await get_redis()
        return await r.incr(self._key(key))


class RateLimiter:
    """Sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """Returns (allowed, remaining_requests)."""
        r = await get_redis()
        key = f"ratelimit:{identifier}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, self.window_seconds)
        results = await pipe.execute()
        count = results[0]
        remaining = max(0, self.max_requests - count)
        return count <= self.max_requests, remaining


# Pre-configured caches
device_cache = RedisCache(prefix="device", default_ttl=60)
alert_cache = RedisCache(prefix="alert", default_ttl=30)
user_cache = RedisCache(prefix="user", default_ttl=300)
session_cache = RedisCache(prefix="session", default_ttl=3600)
