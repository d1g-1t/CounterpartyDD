from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from counterparty_dd.core.clock import Clock, utc_now
from counterparty_dd.core.config import Settings
from counterparty_dd.infrastructure.db.session import build_engine, build_session_factory
from counterparty_dd.infrastructure.throttle import LoginThrottle, RedisLoginThrottle


@dataclass(slots=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    throttle: LoginThrottle
    clock: Clock
    redis: Redis | None = None

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        await self.engine.dispose()


def build_container(settings: Settings, clock: Clock = utc_now) -> Container:
    engine = build_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    return Container(
        settings=settings,
        engine=engine,
        session_factory=build_session_factory(engine),
        throttle=RedisLoginThrottle(redis, settings.login_attempts, settings.login_window_seconds),
        clock=clock,
        redis=redis,
    )
