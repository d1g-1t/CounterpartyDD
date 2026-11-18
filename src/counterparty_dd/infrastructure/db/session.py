from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def build_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
