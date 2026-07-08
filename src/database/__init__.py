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
            # 報表可觀測性優化（docs/report-optimization-plan.md Phase A）
            "ALTER TABLE trend_signals ADD COLUMN IF NOT EXISTS conditions JSON",
            "ALTER TABLE time_diff_signals ADD COLUMN IF NOT EXISTS conditions JSON",
            "ALTER TABLE time_diff_signals ADD COLUMN IF NOT EXISTS next_step VARCHAR(300)",
            "ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS is_new BOOLEAN DEFAULT FALSE",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # 欄位已是正確型別，或 table 尚未建立（create_all 後即正確）


async def drop_db() -> None:
    from .models import Base
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


_worker_loop: asyncio.AbstractEventLoop | None = None


def sync_run(coro):
    """Run an async coroutine from sync code (Celery worker, --pool=solo)。

    復用單一常駐 event loop，而非每次呼叫都用 asyncio.run() 建新 loop。

    **2026-07-07 生產事故修復**：舊版每次呼叫都 `asyncio.run()`（建新 loop→跑
    →關 loop），並在跑之前 `dispose(close=False)` 清空連線池——`close=False` 是
    因為舊 loop 的連線關不得（會拋 'Future attached to a different loop'），所以
    選擇不關、直接棄置。結果是每次呼叫都可能留下沒真正關閉的 asyncpg 連線，
    在 Celery worker 長駐生命週期內逐日堆積，最終打穿 Supabase session pooler
    的 pool_size 上限（`EMAXCONNSESSION`，觸發於 `run_daily_review`）。

    根本修法：worker process 用 `--pool=solo` 單行程單執行緒序列跑任務（見
    fly.toml），同一顆 loop 全程可安全復用，不需要每次重建。連線池交回
    SQLAlchemy 正常管理（用完歸還池內重用），不再需要 dispose 這道手續。
    """
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
    return _worker_loop.run_until_complete(coro)
