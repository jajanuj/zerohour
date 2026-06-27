"""選股 Pipeline — 整合 4 個 Agent，每週產出 Watchlist。"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 台灣科技供應鏈股票池（0050 主要成分股 + 重要供應鏈股）
DEFAULT_UNIVERSE: list[str] = [
    "2330.TW",  # 台積電
    "2454.TW",  # 聯發科
    "2317.TW",  # 鴻海
    "2308.TW",  # 台達電
    "2382.TW",  # 廣達
    "3008.TW",  # 大立光
    "2303.TW",  # 聯電
    "2379.TW",  # 瑞昱
    "2395.TW",  # 研華
    "3711.TW",  # 日月光投控
    "2357.TW",  # 華碩
    "4938.TW",  # 和碩
    "2344.TW",  # 華邦電
    "5483.TW",  # 中美晶
    "2353.TW",  # 宏碁
]

# Agent 權重（合計 1.0）
WEIGHTS = {
    "fundamental": 0.30,
    "technical": 0.25,
    "catalyst": 0.25,
    "supply_chain": 0.20,
}

SCORE_THRESHOLD = 60.0   # 進入 Watchlist 的最低分數
MAX_WATCHLIST = 8         # 最多推薦數量


@dataclass
class WatchlistEntry:
    symbol: str
    overall_score: float
    recommendation: str  # "STRONG_BUY" | "BUY" | "WATCH"
    thesis: str
    risks: list[str] = field(default_factory=list)
    entry_condition: str = ""
    agent_results: dict = field(default_factory=dict)


async def _analyze_one(symbol: str) -> WatchlistEntry | None:
    """對單一股票執行所有 Agent 分析（可能失敗，回傳 None）。"""
    from .fundamental_agent import analyze_fundamental
    from .catalyst_agent import analyze_catalyst
    from .supply_chain_agent import analyze_supply_chain
    from .technical_agent import analyze_technical

    try:
        # 技術面是同步的，fundamental/catalyst/supply_chain 是 async
        # 先跑 async，再跑 sync
        fund, catal, chain = await asyncio.gather(
            analyze_fundamental(symbol),
            analyze_catalyst(symbol),
            analyze_supply_chain(symbol),
            return_exceptions=True,
        )

        # 處理可能的 Exception
        if isinstance(fund, Exception):
            logger.error(f"{symbol} fundamental error: {fund}")
            fund = None
        if isinstance(catal, Exception):
            logger.error(f"{symbol} catalyst error: {catal}")
            catal = None
        if isinstance(chain, Exception):
            logger.error(f"{symbol} supply_chain error: {chain}")
            chain = None

        # 技術面（同步）
        tech = analyze_technical(symbol)

        # 取各 Agent 分數（若失敗用 50）
        f_score = fund.fundamental_score if fund else 50.0
        t_score = tech.technical_score
        c_score = catal.catalyst_score if catal else 50.0
        s_score = chain.supply_chain_score if chain else 50.0

        overall = (
            f_score * WEIGHTS["fundamental"] +
            t_score * WEIGHTS["technical"] +
            c_score * WEIGHTS["catalyst"] +
            s_score * WEIGHTS["supply_chain"]
        )

        if overall < SCORE_THRESHOLD:
            return None

        # 建構論點
        thesis_parts = []
        if fund and fund.key_strengths:
            thesis_parts.append(f"基本面：{fund.key_strengths[0]}")
        if chain and chain.supply_chain_summary:
            thesis_parts.append(f"供應鏈：{chain.supply_chain_summary}")
        if catal and catal.has_earnings_soon:
            thesis_parts.append(f"催化劑：財報 {catal.days_to_earnings} 天後")
        if tech.signal in ("STRONG_BUY", "BUY"):
            thesis_parts.append(f"技術面：{tech.reason}")
        thesis = "；".join(thesis_parts) or f"{symbol} 綜合評分 {overall:.0f}"

        # 風險彙整
        risks = []
        if catal:
            risks.extend(catal.risks[:2])
        if chain:
            risks.extend(chain.risks[:1])
        risks = list(dict.fromkeys(risks))[:3]  # 去重，最多 3 條

        # 進場條件
        entry_parts = []
        if tech.above_ma200:
            entry_parts.append("價格站上 MA200")
        if catal and catal.has_earnings_soon:
            entry_parts.append(f"財報前 {catal.days_to_earnings} 天布局")
        if tech.signal == "STRONG_BUY":
            entry_parts.append("RSI 健康 + MACD 多頭")
        entry_condition = "；".join(entry_parts) or "等待 S2 時間差訊號確認"

        # 推薦分類
        if overall >= 75:
            recommendation = "STRONG_BUY"
        elif overall >= 62:
            recommendation = "BUY"
        else:
            recommendation = "WATCH"

        return WatchlistEntry(
            symbol=symbol,
            overall_score=round(overall, 1),
            recommendation=recommendation,
            thesis=thesis,
            risks=risks,
            entry_condition=entry_condition,
            agent_results={
                "fundamental": {
                    "score": f_score,
                    "growth_trend": fund.growth_trend if fund else "stable",
                    "summary": fund.summary if fund else "",
                },
                "technical": {
                    "score": t_score,
                    "rsi": tech.rsi,
                    "macd_bullish": tech.macd_bullish,
                    "signal": tech.signal,
                },
                "catalyst": {
                    "score": c_score,
                    "has_earnings_soon": catal.has_earnings_soon if catal else False,
                    "earnings_date": catal.earnings_date if catal else None,
                },
                "supply_chain": {
                    "score": s_score,
                    "us_tech_exposure": chain.us_tech_exposure if chain else "MEDIUM",
                },
            },
        )
    except Exception as e:
        logger.error(f"_analyze_one {symbol} failed: {e}", exc_info=True)
        return None


async def run_stock_selection_pipeline(
    universe: list[str] | None = None,
    max_concurrent: int = 3,
) -> list[WatchlistEntry]:
    """
    執行選股 Pipeline，回傳最高分的 Watchlist。

    Args:
        universe: 股票清單，預設 DEFAULT_UNIVERSE
        max_concurrent: 同時執行的最大股票數（控制 Gemini 呼叫頻率）
    """
    if universe is None:
        universe = DEFAULT_UNIVERSE

    logger.info(f"Starting stock selection pipeline: {len(universe)} stocks")

    results: list[WatchlistEntry] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_analyze(sym: str):
        async with semaphore:
            entry = await _analyze_one(sym)
            if entry:
                results.append(entry)
            # 每支股票之間稍作間隔，避免 Gemini rate limit
            await asyncio.sleep(2)

    await asyncio.gather(*[bounded_analyze(sym) for sym in universe])

    # 按分數排序，取最高 MAX_WATCHLIST 支
    results.sort(key=lambda x: x.overall_score, reverse=True)
    top = results[:MAX_WATCHLIST]

    logger.info(f"Pipeline done: {len(results)} passed threshold, top {len(top)} selected")
    return top
