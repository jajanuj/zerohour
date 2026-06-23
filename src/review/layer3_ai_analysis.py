import httpx
import json
import logging
from datetime import date
from typing import Optional

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

AI_REVIEW_SYSTEM_PROMPT = """
你是一位量化交易系統的覆盤分析師。
分析原則：
1. 只根據提供的數據，不要假設額外資訊
2. 區分「策略問題」和「市場環境問題」
3. 改進建議必須有數據支撐，不接受「感覺」
4. 如果樣本數不足（< 30 筆），明確說明無法下結論
5. 輸出使用繁體中文，語氣專業但不誇張
"""


async def run_ai_review(
    compliance: dict,
    signal_quality: dict,
    trade: dict,
    rolling_stats: dict,
    market_context: Optional[dict] = None,
) -> str:
    """呼叫 Claude API 進行 AI 覆盤分析。"""
    if not settings.anthropic_api_key:
        return "（AI 覆盤未啟用：未設定 ANTHROPIC_API_KEY）"

    market_ctx = market_context.get("summary", "無額外市場背景") if market_context else "無額外市場背景"

    prompt = f"""
請分析以下今日（{date.today()}）交易覆盤數據：

【Layer 1 規則遵守度】
合規分數：{compliance.get('score', 0)}/100
違規項目：{json.dumps(compliance.get('violations', []), ensure_ascii=False, indent=2)}

【Layer 2 訊號品質】
美股訊號：NASDAQ {signal_quality.get('nasdaq_change_pct', 0):+.2f}%、SOX {signal_quality.get('sox_change_pct', 0):+.2f}%
台股反應：開盤 {signal_quality.get('taiwan_open_change_pct', 0):+.2f}%、收盤 {signal_quality.get('taiwan_close_change_pct', 0):+.2f}%
訊號方向正確：{signal_quality.get('signal_was_correct', False)}
今日損益：{trade.get('pnl_pct', 0):+.2f}%
訊號品質分數：{signal_quality.get('quality_score', 0):.0f}/100

【滾動統計（近 30 天）】
勝率：{rolling_stats.get('win_rate_30d', 0):.1%}
Sharpe Ratio：{rolling_stats.get('sharpe_30d', 0):.2f}
vs 基準（0050 買入持有）：{rolling_stats.get('vs_benchmark_pct', 0):+.2f}%

【市場背景】
{market_ctx}

請提供：
1. **今日交易總結**（2–3 句）
2. **訊號評估**（事後看是好訊號嗎？為什麼？）
3. **需要關注的問題**（如有，否則說明無問題）
4. **改進建議**（若有數據支撐，否則說明樣本不足）
5. **明日注意事項**

格式：使用 Markdown，每個區塊清楚標示。
"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1000,
                    "system": AI_REVIEW_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]
    except Exception as e:
        logger.error(f"AI 覆盤呼叫失敗: {e}")
        return f"AI 覆盤執行失敗：{e}"
