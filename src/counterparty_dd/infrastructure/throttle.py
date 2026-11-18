from typing import Protocol

from redis.asyncio import Redis


class LoginThrottle(Protocol):
    async def blocked(self, key: str) -> bool: ...

    async def failed(self, key: str) -> None: ...

    async def reset(self, key: str) -> None: ...


class RedisLoginThrottle:
    def __init__(self, redis: Redis, attempts: int, window_seconds: int) -> None:
        self._redis = redis
        self._attempts = attempts
        self._window = window_seconds

    @staticmethod
    def _key(key: str) -> str:
        return f"cdd:login:{key}"

    async def blocked(self, key: str) -> bool:
        value = await self._redis.get(self._key(key))
        return value is not None and int(value) >= self._attempts

    async def failed(self, key: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(self._key(key))
            pipe.expire(self._key(key), self._window, nx=True)
            await pipe.execute()

    async def reset(self, key: str) -> None:
        await self._redis.delete(self._key(key))


class MemoryLoginThrottle:
    def __init__(self, attempts: int) -> None:
        self._attempts = attempts
        self.counters: dict[str, int] = {}

    async def blocked(self, key: str) -> bool:
        return self.counters.get(key, 0) >= self._attempts

    async def failed(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    async def reset(self, key: str) -> None:
        self.counters.pop(key, None)
