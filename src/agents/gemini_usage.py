"""Gemini API 呼叫記錄 — 寫入 agent_run_logs 表（老闆 2026-07-06 核准）。

背景：agent_run_logs 表與 log_agent_run() 早已存在但從未被接上，
Gemini 用量（免費方案 RPD 上限 20）一直無從查核。本模組提供單一記錄入口，
各 Gemini 呼叫點在成功/失敗時各記一次；記錄失敗只 log 不拋，不影響主流程。
"""
import logging
import time

logger = logging.getLogger(__name__)


async def record_gemini_call(
    run_type: str,
    symbol: str | None,
    started_monotonic: float,
    data: dict | None = None,
    error: Exception | None = None,
) -> None:
    """記錄一次 Gemini API 呼叫。

    data：成功時傳 Gemini 回應 JSON（自動取 usageMetadata.totalTokenCount）。
    error：失敗時傳例外。兩者擇一。
    """
    try:
        from ..database.helpers import log_agent_run

        tokens = 0
        if data:
            try:
                tokens = int((data.get("usageMetadata") or {}).get("totalTokenCount") or 0)
            except (TypeError, ValueError):
                tokens = 0
        await log_agent_run(
            run_type=run_type,
            symbol=symbol,
            tokens_used=tokens,
            success=error is None,
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            error_message=str(error)[:500] if error else None,
        )
    except Exception as e:  # 記錄失敗不得影響 Gemini 呼叫方
        logger.warning(f"Gemini 呼叫記錄失敗（不影響主流程）{run_type}: {e}")
