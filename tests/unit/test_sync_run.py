"""sync_run() 常駐 event loop 測試 — 2026-07-07 生產事故修復。

事故：Supabase session pooler 連線耗盡（EMAXCONNSESSION，pool_size 15），
於 run_daily_review 觸發。根因：舊版每次 sync_run() 呼叫都建新 event loop +
dispose(close=False)（不關閉底層連線，避免 'different loop' 錯誤），導致
asyncpg 連線逐次堆積、永不釋放。

修復：Celery worker 用 --pool=solo（單行程單執行緒序列跑任務，見 fly.toml），
sync_run 改為復用單一常駐 loop，連線池交回 SQLAlchemy 正常管理與回收。
"""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from src.database import sync_run


async def _noop(value):
    return value


class TestSyncRun:

    def test_returns_coroutine_result(self):
        assert sync_run(_noop(42)) == 42

    def test_reuses_same_loop_across_calls(self):
        async def _capture_loop_id():
            return id(asyncio.get_running_loop())

        loop_ids = [sync_run(_capture_loop_id()) for _ in range(3)]
        assert len(set(loop_ids)) == 1  # 同一顆 loop，不是每次新建即棄

    def test_many_sequential_calls_do_not_raise(self):
        # 模擬單一 Celery 任務內連續呼叫（tasks.py 單一任務常見 10+ 次）
        for i in range(20):
            assert sync_run(_noop(i)) == i

    def test_db_session_survives_multiple_task_cycles(self):
        # 模擬多個「任務」在同一 worker process 生命週期內依序執行 DB 存取，
        # 都能正常開關 session，不拋 'different loop' 或 'event loop is closed'。
        # 用獨立的記憶體 SQLite engine（不經 src.database.async_engine），
        # 避免依賴本機 .env 的 DATABASE_URL 設定（可能指向生產 Supabase）。
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

        async def _ping():
            async with SessionLocal() as session:
                result = await session.execute(text("SELECT 1"))
                return result.scalar()

        try:
            for _ in range(5):
                assert sync_run(_ping()) == 1
        finally:
            sync_run(engine.dispose())
