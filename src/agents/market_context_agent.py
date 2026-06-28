"""Market Context Agent — 解讀美股收盤背景脈絡對台灣市場的影響。"""
import httpx
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_DEFAULT = {
    "market_driver": "無法分析",
    "taiwan_relevance": "MEDIUM",
    "relevance_reason": "AI 分析未啟用",
    "confidence_modifier": 0.0,
    "key_risks": [],
    "context_summary": "Market Context Agent 未執行",
}


def _get_qqq_news() -> list[str]:
    try:
        import yfinance as yf
        ticker = yf.Ticker("QQQ")
        news = ticker.news or []
        return [item.get("content", {}).get("title", "") or item.get("title", "")
                for item in news[:10] if item]
    except Exception:
        return []


async def run_market_context_agent(
    nasdaq_change_pct: float,
    sp500_change_pct: float,
    sox_change_pct: float,
    news_headlines: list[str] | None = None,
) -> dict:
    """
    分析美股收盤背景脈絡。

    Returns:
        {
            "market_driver": str,
            "taiwan_relevance": "HIGH"|"MEDIUM"|"LOW",
            "relevance_reason": str,
            "confidence_modifier": float,  # -0.20 ~ +0.20
            "key_risks": list[str],
            "context_summary": str,
        }
    """
    from ..config import get_settings
    settings = get_settings()

    if not settings.gemini_api_key:
        return _DEFAULT

    if news_headlines is None:
        news_headlines = _get_qqq_news()

    news_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(news_headlines) if h)
    if not news_text:
        news_text = "無可用新聞"

    prompt = f"""
你是台灣股市分析師，專精解讀美股動向對台灣科技股的影響。
只根據提供數據分析，回覆必須是合法 JSON，不包含任何其他文字。

今日美股收盤（台灣時間 {datetime.now().strftime('%Y-%m-%d')} 凌晨）：
- NASDAQ: {nasdaq_change_pct:+.2f}%
- S&P 500: {sp500_change_pct:+.2f}%
- 費城半導體 SOX: {sox_change_pct:+.2f}%

重大新聞（前 10 則）：
{news_text}

JSON 回覆格式：
{{
    "market_driver": "今日市場主要驅動力（技術面/基本面/宏觀事件）",
    "taiwan_relevance": "HIGH或MEDIUM或LOW",
    "relevance_reason": "與台灣科技股的關聯說明（一句話）",
    "confidence_modifier": 0.0,
    "key_risks": ["風險1", "風險2"],
    "context_summary": "一句話總結"
}}

confidence_modifier 說明：
- 正值（最高+0.20）：台股跟進美股機率更高
- 負值（最低-0.20）：台股可能不跟進或反向
- 0.0：中性，無特別影響
"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 2048},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)
            result["confidence_modifier"] = max(-0.20, min(0.20, float(result.get("confidence_modifier", 0))))
            return result
    except json.JSONDecodeError as e:
        logger.error(f"Market Context Agent JSON parse error: {e}, raw={raw[:200]}")
        return _DEFAULT
    except Exception as e:
        logger.error(f"Market Context Agent error: {e}")
        return _DEFAULT
