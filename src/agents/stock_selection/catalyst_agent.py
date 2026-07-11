"""催化劑選股 Agent — 識別近期業績/新聞觸發事件。"""
import httpx
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..gemini_usage import record_gemini_call, redact_secrets

logger = logging.getLogger(__name__)


@dataclass
class CatalystResult:
    symbol: str
    catalyst_score: float  # 0-100
    has_earnings_soon: bool
    earnings_date: str | None
    days_to_earnings: int | None
    catalysts: list[str]
    risks: list[str]
    summary: str


def _get_upcoming_earnings(symbol: str) -> tuple[str | None, int | None]:
    """取得最近財報日期，回傳 (date_str, days_to_earnings)。"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None:
            return None, None
        # calendar 可能是 dict 或 DataFrame
        if isinstance(cal, dict):
            earn_dates = cal.get("Earnings Date")
            if earn_dates and len(earn_dates) > 0:
                ed = earn_dates[0]
                if hasattr(ed, 'date'):
                    ed = ed.date()
                days = (ed - datetime.now().date()).days
                if 0 <= days <= 45:
                    return str(ed), days
        else:
            # DataFrame
            try:
                row = cal.loc["Earnings Date"]
                if row is not None:
                    ed = row.iloc[0] if hasattr(row, 'iloc') else row
                    if hasattr(ed, 'date'):
                        ed = ed.date()
                    days = (ed - datetime.now().date()).days
                    if 0 <= days <= 45:
                        return str(ed), days
            except (KeyError, IndexError, TypeError):
                pass
    except Exception as e:
        logger.debug(f"earnings fetch {symbol}: {e}")
    return None, None


def _get_recent_news(symbol: str) -> list[str]:
    """取得最近 3 則新聞標題。"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
        return [
            item.get("content", {}).get("title", "") or item.get("title", "")
            for item in news[:5] if item
        ]
    except Exception:
        return []


async def analyze_catalyst(symbol: str) -> CatalystResult:
    """
    分析股票近期催化劑：財報時間、業績指引、市場消息。
    """
    from ...config import get_settings
    settings = get_settings()

    earnings_date, days_to_earnings = _get_upcoming_earnings(symbol)
    has_earnings_soon = days_to_earnings is not None and days_to_earnings <= 30
    news_headlines = _get_recent_news(symbol)

    _default = CatalystResult(
        symbol=symbol,
        catalyst_score=50.0,
        has_earnings_soon=has_earnings_soon,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
        catalysts=["財報即將公布" if has_earnings_soon else "無明顯催化劑"],
        risks=[],
        summary="催化劑評估：中性",
    )

    if not settings.gemini_api_key:
        # 純量化評分
        score = 50.0
        catalysts = []
        if has_earnings_soon and days_to_earnings is not None:
            if days_to_earnings <= 14:
                score += 20
                catalysts.append(f"財報 {days_to_earnings} 天後（重要催化劑）")
            elif days_to_earnings <= 30:
                score += 10
                catalysts.append(f"財報 {days_to_earnings} 天後")
        return CatalystResult(
            symbol=symbol,
            catalyst_score=min(100, score),
            has_earnings_soon=has_earnings_soon,
            earnings_date=earnings_date,
            days_to_earnings=days_to_earnings,
            catalysts=catalysts or ["無近期催化劑"],
            risks=[],
            summary=f"催化劑評分：{min(100, score):.0f}/100",
        )

    news_text = "\n".join(f"- {h}" for h in news_headlines if h) or "- 無近期新聞"
    earnings_info = f"財報預計 {earnings_date}（{days_to_earnings} 天後）" if has_earnings_soon else "無近期財報"

    prompt = f"""
你是台灣股市催化劑分析師。評估以下股票的近期催化劑與風險，回覆必須是合法 JSON。

股票代號：{symbol}

財報資訊：{earnings_info}

最近新聞：
{news_text}

JSON 格式回覆：
{{
    "catalyst_score": 0到100的整數,
    "catalysts": ["催化劑1", "催化劑2"],
    "risks": ["風險1", "風險2"],
    "summary": "催化劑評估一句話總結"
}}

評分標準：
- 80+：強力催化劑（即將財報+業績指引上調+正面消息）
- 60-80：有催化劑（財報在即或有正面新聞）
- 40-60：中性（無特別催化劑）
- 40以下：逆風（負面消息或財報下修風險）
"""

    _t0 = time.monotonic()
    _logged = False
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": settings.gemini_api_key,
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 400},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            await record_gemini_call("catalyst_agent", symbol, _t0, data=data)
            _logged = True
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            r = json.loads(raw)
            return CatalystResult(
                symbol=symbol,
                catalyst_score=float(r.get("catalyst_score", 50)),
                has_earnings_soon=has_earnings_soon,
                earnings_date=earnings_date,
                days_to_earnings=days_to_earnings,
                catalysts=r.get("catalysts", []),
                risks=r.get("risks", []),
                summary=r.get("summary", ""),
            )
    except Exception as e:
        if not _logged:
            await record_gemini_call("catalyst_agent", symbol, _t0, error=e)
        logger.error(f"catalyst_agent {symbol} error: {redact_secrets(str(e))}")
        return _default
