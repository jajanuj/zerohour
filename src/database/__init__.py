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
    from sqlalchemy import text
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # portfolio_positions schema migration：支援碎股 + 幣別欄
        for stmt in [
            "ALTER TABLE portfolio_positions ALTER COLUMN shares TYPE NUMERIC(14,5) USING shares::numeric",
            "ALTER TABLE portfolio_positions ALTER COLUMN avg_cost TYPE NUMERIC(12,4) USING avg_cost::numeric",
            "ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'TWD'",
            "ALTER TABLE portfolio_positions ADD COLUMN IF NOT EXISTS market VARCHAR(5) DEFAULT 'TW'",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # 欄位已是正確型別，或 table 尚未建立（create_all 後即正確）


async def drop_db() -> None:
    from .models import Base
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def sync_run(coro):
    """Run an async coroutine from sync code (e.g., Celery tasks).

    每次呼叫先 dispose engine pool，避免 asyncio.run() 建新 event loop 後
    舊 pool 連線仍綁在前一個 loop 導致 'Future attached to a different loop'。
    """
    async def _run():
        # close=False：只清空 pool，不主動關舊連線（舊連線綁舊 loop，關閉會報錯）
        await async_engine.dispose(close=False)
        return await coro
    return asyncio.run(_run())
