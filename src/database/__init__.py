import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from ..config import get_settings

settings = get_settings()

async_engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=2,
    pool_timeout=30,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from .models import Base
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    from .models import Base
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def sync_run(coro):
    """Run an async coroutine from sync code (e.g., Celery tasks)."""
    return asyncio.run(coro)
