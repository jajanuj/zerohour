"""基本面選股 Agent — yfinance 取得財務數據，Gemini 分析護城河與成長性。"""
import httpx
import json
import logging
import time
from dataclasses import dataclass

from ..gemini_usage import record_gemini_call

logger = logging.getLogger(__name__)


@dataclass
class FundamentalResult:
    symbol: str
    fundamental_score: float  # 0-100
    moat_score: float
    growth_score: float
    valuation_score: float
    growth_trend: str  # "accelerating" | "stable" | "decelerating"
    key_strengths: list[str]
    key_concerns: list[str]
    summary: str


def _fetch_financials(symbol: str) -> dict:
    """從 yfinance 取得基本面數據，容錯處理缺漏欄位。"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        return {
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cashflow": info.get("freeCashflow"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "company_name": info.get("longName") or info.get("shortName") or symbol,
        }
    except Exception as e:
        logger.warning(f"fundamentals fetch {symbol} error: {e}")
        return {"company_name": symbol}


async def analyze_fundamental(symbol: str) -> FundamentalResult:
    """
    分析股票基本面：護城河、成長性、估值。
    使用 yfinance 取得數據，Gemini 進行分析評分。
    """
    from ...config import get_settings
    settings = get_settings()

    _default = FundamentalResult(
        symbol=symbol,
        fundamental_score=50.0,
        moat_score=50.0,
        growth_score=50.0,
        valuation_score=50.0,
        growth_trend="stable",
        key_strengths=[],
        key_concerns=["資料不足"],
        summary="無法取得足夠財務數據",
    )

    fin = _fetch_financials(symbol)

    # 若沒有 Gemini，使用純量化評分
    if not settings.gemini_api_key:
        return _quantitative_fallback(symbol, fin)

    # 整理可用數據呈現給 Gemini
    def fmt(v, pct=False, x=False):
        if v is None:
            return "N/A"
        if pct:
            return f"{v*100:.1f}%"
        if x:
            return f"{v:.1f}x"
        return f"{v:.2f}"

    prompt = f"""
你是台灣股市基本面分析師。分析以下股票的基本面，只根據提供的數據，回覆必須是合法 JSON。

股票代號：{symbol}
公司名稱：{fin.get('company_name', symbol)}
產業：{fin.get('sector', 'N/A')} / {fin.get('industry', 'N/A')}

財務數據：
- 本益比（trailing PE）：{fmt(fin.get('pe_ratio'), x=True)}
- 預估本益比（forward PE）：{fmt(fin.get('forward_pe'), x=True)}
- PEG Ratio：{fmt(fin.get('peg_ratio'))}
- 股價淨值比：{fmt(fin.get('price_to_book'), x=True)}
- 股東權益報酬率 ROE：{fmt(fin.get('roe'), pct=True)}
- 營收成長率（YoY）：{fmt(fin.get('revenue_growth'), pct=True)}
- 獲利成長率（YoY）：{fmt(fin.get('earnings_growth'), pct=True)}
- 毛利率：{fmt(fin.get('gross_margin'), pct=True)}
- 營業利益率：{fmt(fin.get('operating_margin'), pct=True)}
- 負債股東權益比：{fmt(fin.get('debt_to_equity'))}
- 自由現金流：{fin.get('free_cashflow')}
- 市值：{fin.get('market_cap')}

請根據上述數據（N/A 表示無法取得，根據產業知識合理推測）：

JSON 格式回覆：
{{
    "moat_score": 0到100的整數,
    "moat_description": "護城河說明（一句話）",
    "growth_score": 0到100的整數,
    "growth_trend": "accelerating或stable或decelerating",
    "valuation_score": 0到100的整數,
    "valuation_comment": "估值評估（一句話）",
    "fundamental_score": 0到100的整數,
    "key_strengths": ["優勢1", "優勢2"],
    "key_concerns": ["疑慮1", "疑慮2"],
    "summary": "基本面一句話總結"
}}
"""

    _t0 = time.monotonic()
    _logged = False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 600},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            await record_gemini_call("fundamental_agent", symbol, _t0, data=data)
            _logged = True
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            r = json.loads(raw)
            return FundamentalResult(
                symbol=symbol,
                fundamental_score=float(r.get("fundamental_score", 50)),
                moat_score=float(r.get("moat_score", 50)),
                growth_score=float(r.get("growth_score", 50)),
                valuation_score=float(r.get("valuation_score", 50)),
                growth_trend=r.get("growth_trend", "stable"),
                key_strengths=r.get("key_strengths", []),
                key_concerns=r.get("key_concerns", []),
                summary=r.get("summary", ""),
            )
    except Exception as e:
        if not _logged:
            await record_gemini_call("fundamental_agent", symbol, _t0, error=e)
        logger.error(f"fundamental_agent {symbol} Gemini error: {e}")
        return _quantitative_fallback(symbol, fin)


def _quantitative_fallback(symbol: str, fin: dict) -> FundamentalResult:
    """當 Gemini 不可用時，純量化評分（0–100）。"""
    score = 50.0
    strengths = []
    concerns = []

    roe = fin.get("roe")
    if roe is not None:
        if roe > 0.20:
            score += 10
            strengths.append(f"ROE {roe*100:.1f}% 優秀")
        elif roe > 0.10:
            score += 5
        elif roe < 0:
            score -= 10
            concerns.append("ROE 為負")

    rev_growth = fin.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth > 0.20:
            score += 10
            strengths.append(f"營收成長 {rev_growth*100:.1f}%")
        elif rev_growth > 0.05:
            score += 5
        elif rev_growth < 0:
            score -= 5
            concerns.append(f"營收衰退 {rev_growth*100:.1f}%")

    pe = fin.get("pe_ratio")
    if pe is not None and pe > 0:
        if pe < 15:
            score += 5
            strengths.append(f"PE {pe:.1f}x 便宜")
        elif pe > 50:
            score -= 5
            concerns.append(f"PE {pe:.1f}x 偏貴")

    gm = fin.get("gross_margin")
    if gm is not None:
        if gm > 0.40:
            score += 8
            strengths.append(f"毛利率 {gm*100:.1f}% 高")
        elif gm < 0.10:
            score -= 5
            concerns.append("毛利率偏低")

    return FundamentalResult(
        symbol=symbol,
        fundamental_score=max(0, min(100, score)),
        moat_score=50.0,
        growth_score=50.0,
        valuation_score=50.0,
        growth_trend="stable",
        key_strengths=strengths,
        key_concerns=concerns or ["數據不足"],
        summary=f"量化評分 {score:.0f}/100（Gemini 未啟用）",
    )
