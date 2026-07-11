"""Gemini API 呼叫記錄 — 寫入 agent_run_logs 表（老闆 2026-07-06 核准）。

背景：agent_run_logs 表與 log_agent_run() 早已存在但從未被接上，
Gemini 用量（免費方案 RPD 上限 20）一直無從查核。本模組提供單一記錄入口，
各 Gemini 呼叫點在成功/失敗時各記一次；記錄失敗只 log 不拋，不影響主流程。
"""
import logging
import time

logger = logging.getLogger(__name__)


def redact_secrets(text: str) -> str:
    """從任意字串移除 Gemini API 金鑰，避免例外訊息外洩機密。

    2026-07-07 生產事故：Gemini 呼叫失敗時的例外字串含請求 URL，金鑰當時仍在
    query string 中，直接外洩進 Discord 週報。主要修法是改用 header 傳金鑰
    （不再進 URL，見各呼叫點），本函式是第二道防線，防止金鑰以任何形式
    重新出現在 log 或使用者可見的錯誤訊息中。
    """
    if not text:
        return text
    try:
        from ..config import get_settings
        key = get_settings().gemini_api_key
    except Exception:
        return text
    if key and key in text:
        text = text.replace(key, "***REDACTED***")
    return text


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
            error_message=redact_secrets(str(error))[:500] if error else None,
        )
    except Exception as e:  # 記錄失敗不得影響 Gemini 呼叫方
        logger.warning(f"Gemini 呼叫記錄失敗（不影響主流程）{run_type}: {e}")
