from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging

from .schemas import (
    CurrentSignalsResponse,
    TrendSignalSchema,
    TimeDiffSignalSchema,
    CombinedSignalSchema,
    PositionSchema,
    OrderRequest,
    OrderResponse,
    PerformanceResponse,
    ReviewReportSchema,
    MarketContextSchema,
    BlackSwanSchema,
    WatchlistItemSchema,
    BacktestRequest,
    BacktestResponse,
    PerformanceHistoryItem,
    SignalHistoryItem,
    BacktestCompareRequest,
    BacktestCompareResponse,
    StrategyResult,
    TaskTriggerResponse,
)
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
settings = get_settings()


@router.get("/health")
async def health_check():
    return {"status": "ok", "mode": settings.trading_mode}


@router.get("/signals/current", response_model=CurrentSignalsResponse)
async def get_current_signals():
    """即時抓取市場資料並生成 S1/S2/S3 訊號。"""
    import asyncio
    from datetime import datetime
    from ..data.fetcher import USMarketFetcher, TWMarketFetcher
    from ..data.normalizer import DataNormalizer
    from ..signals.time_diff import TimeDiffSignalGenerator
    from ..signals.ma200_filter import MA200Filter
    from ..signals.aggregator import SignalAggregator

    try:
        loop = asyncio.get_event_loop()

        fetcher = USMarketFetcher()
        norm = DataNormalizer()

        # S2：時間差訊號（用美股最新收盤漲跌）
        us_data = await loop.run_in_executor(None, fetcher.get_all_signals_data)
        nasdaq_chg = us_data.get("nasdaq", {}).get("change_pct", 0.0) or 0.0
        sp500_chg  = us_data.get("sp500",  {}).get("change_pct", 0.0) or 0.0
        sox_chg    = us_data.get("sox",    {}).get("change_pct", 0.0) or 0.0

        gen = TimeDiffSignalGenerator(
            nasdaq_threshold=settings.us_signal_threshold,
            min_confidence=settings.min_confidence,
        )
        time_diff = gen.generate(nasdaq_chg, sp500_chg, sox_chg)

        # S1：MA200 趨勢（QQQ 2年資料）
        qqq_raw = await loop.run_in_executor(
            None, lambda: fetcher.get_historical("qqq", period="2y")
        )
        qqq_df = norm.normalize_ohlcv(qqq_raw)
        ma_filter = MA200Filter(period=settings.ma_period)
        trend = ma_filter.calculate(qqq_df, "QQQ")

        # S3：組合決策
        agg = SignalAggregator()
        combined = agg.aggregate(trend, time_diff)

        return CurrentSignalsResponse(
            trend=TrendSignalSchema(
                symbol=trend.symbol,
                state=trend.state.value,
                current_price=float(trend.current_price),
                ma200=float(trend.ma200),
                distance_pct=float(trend.distance_pct),
                signal_date=datetime.combine(trend.date, datetime.min.time()),
                is_newly_crossed=trend.is_newly_crossed,
            ),
            time_diff=TimeDiffSignalSchema(
                direction=time_diff.direction.value,
                confidence=float(time_diff.confidence),
                nasdaq_change_pct=nasdaq_chg,
                sp500_change_pct=sp500_chg,
                sox_change_pct=sox_chg,
                trigger_reason=time_diff.trigger_reason,
                generated_at=time_diff.generated_at,
            ),
            combined=CombinedSignalSchema(
                final_action=combined.final_action.value,
                symbol=combined.symbol or "0050",
                suggested_position_pct=float(combined.suggested_position_pct),
                stop_loss_pct=float(combined.stop_loss_pct),
                reason=combined.reason,
            ),
        )

    except Exception as e:
        logger.error(f"get_current_signals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=list[PositionSchema])
async def get_positions():
    """取得目前所有持倉（從 DB 讀取最新快照）。"""
    try:
        from ..database.helpers import get_open_positions
        positions = await get_open_positions()
        return [
            PositionSchema(
                symbol=p["symbol"],
                quantity=p["quantity"],
                avg_entry_price=p["avg_entry_price"],
                current_price=p["current_price"] or p["avg_entry_price"],
                unrealized_pnl=p["unrealized_pnl"] or 0.0,
                unrealized_pnl_pct=p["unrealized_pnl_pct"] or 0.0,
            )
            for p in positions
        ]
    except Exception as e:
        logger.error(f"get_positions error: {e}")
        return []


@router.post("/orders", response_model=OrderResponse)
async def create_order(request: OrderRequest):
    """手動建立訂單（需確認 trading_mode）。"""
    if settings.trading_mode == "observe":
        raise HTTPException(status_code=403, detail="系統處於觀察模式，不允許下單")
    raise HTTPException(status_code=501, detail="手動下單請透過 Celery 訊號任務執行")


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance():
    """取得績效摘要（從 DB 最新快照）。"""
    try:
        from ..database.helpers import get_latest_performance
        perf = await get_latest_performance()
        if not perf:
            return PerformanceResponse(
                period="ytd",
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                win_rate=0.0,
                total_trades=0,
                sharpe_ratio=0.0,
                profit_factor=0.0,
            )
        extra = perf.get("extra_data", {}) or {}
        return PerformanceResponse(
            period="ytd",
            total_return_pct=perf["total_return_pct"],
            max_drawdown_pct=perf["max_drawdown_pct"],
            win_rate=perf["win_rate"],
            total_trades=extra.get("total_trades", 0),
            sharpe_ratio=perf["sharpe_ratio"],
            profit_factor=0.0,
        )
    except Exception as e:
        logger.error(f"get_performance error: {e}")
        return PerformanceResponse(
            period="ytd",
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            total_trades=0,
            sharpe_ratio=0.0,
            profit_factor=0.0,
        )


@router.get("/review/daily/latest", response_model=Optional[ReviewReportSchema])
async def get_daily_review():
    """取得最新每日覆盤報告。"""
    try:
        from ..database.helpers import get_latest_review
        return await get_latest_review("daily")
    except Exception as e:
        logger.error(f"get_daily_review error: {e}")
        return None


@router.get("/review/weekly/latest", response_model=Optional[ReviewReportSchema])
async def get_weekly_review():
    """取得最新週覆盤報告。"""
    try:
        from ..database.helpers import get_latest_review
        return await get_latest_review("weekly")
    except Exception as e:
        logger.error(f"get_weekly_review error: {e}")
        return None


@router.get("/agents/market-context/latest", response_model=Optional[MarketContextSchema])
async def get_market_context():
    """取得最新市場背景 Agent 分析結果。"""
    try:
        from ..database.helpers import get_latest_market_context
        return await get_latest_market_context()
    except Exception as e:
        logger.error(f"get_market_context error: {e}")
        return None


@router.get("/agents/black-swan/status", response_model=Optional[BlackSwanSchema])
async def get_black_swan_status():
    """取得最近 7 天黑天鵝偵測狀態（無警報回傳 null）。"""
    try:
        from ..database.helpers import get_latest_black_swan
        return await get_latest_black_swan()
    except Exception as e:
        logger.error(f"get_black_swan_status error: {e}")
        return None


@router.get("/watchlist", response_model=list[WatchlistItemSchema])
async def get_watchlist():
    """取得目前 Watchlist（選股 Pipeline 輸出）。"""
    try:
        from ..database.helpers import get_watchlist
        return await get_watchlist()
    except Exception as e:
        logger.error(f"get_watchlist error: {e}")
        return []


_ALLOWED_TASKS = {
    "run_daily_review",
    "run_weekly_review",
    "run_market_context",
    "check_black_swan",
    "run_stock_selection",
    "fetch_us_market_data",
    "generate_signal",
    "update_positions",
}


@router.post("/tasks/{task_name}", response_model=TaskTriggerResponse)
async def trigger_task(task_name: str):
    """手動觸發指定 Celery 任務（立即執行）。"""
    if task_name not in _ALLOWED_TASKS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"不允許的任務名稱：{task_name}。允許清單：{sorted(_ALLOWED_TASKS)}")
    try:
        import importlib
        tasks_module = importlib.import_module("src.tasks")
        task_fn = getattr(tasks_module, task_name)
        task_fn.delay()
        return TaskTriggerResponse(status="queued", task=task_name, message="任務已加入 Celery 佇列")
    except Exception as e:
        logger.error(f"trigger_task {task_name} error: {e}")
        return TaskTriggerResponse(status="error", task=task_name, message=str(e))


@router.get("/performance/history", response_model=list[PerformanceHistoryItem])
async def get_performance_history(days: int = 60):
    """取得最近 N 天的每日資金快照（資金曲線用）。"""
    try:
        from ..database.helpers import get_performance_history
        return await get_performance_history(days)
    except Exception as e:
        logger.error(f"get_performance_history error: {e}")
        return []


@router.get("/signals/history", response_model=list[SignalHistoryItem])
async def get_signal_history(days: int = 30):
    """取得最近 N 天的訊號紀錄。"""
    try:
        from ..database.helpers import get_signal_history
        return await get_signal_history(days)
    except Exception as e:
        logger.error(f"get_signal_history error: {e}")
        return []


@router.post("/backtest/compare", response_model=BacktestCompareResponse)
async def run_backtest_compare(request: BacktestCompareRequest):
    """S1 / S2 / S3 三策略並排回測比較。"""
    from ..backtest.engine import BacktestEngine, BacktestConfig
    from ..data.fetcher import USMarketFetcher, TWMarketFetcher
    from ..data.normalizer import DataNormalizer

    try:
        fetcher = USMarketFetcher()
        tw_fetcher = TWMarketFetcher()
        normalizer = DataNormalizer()

        nasdaq_df = normalizer.normalize_ohlcv(fetcher.get_historical("nasdaq", period="10y"))
        nasdaq_df = normalizer.calculate_change_pct(nasdaq_df)
        sp500_df = normalizer.normalize_ohlcv(fetcher.get_historical("sp500", period="10y"))
        sp500_df = normalizer.calculate_change_pct(sp500_df)
        sox_df = normalizer.normalize_ohlcv(fetcher.get_historical("sox", period="10y"))
        sox_df = normalizer.calculate_change_pct(sox_df)
        us_signals = normalizer.merge_us_signals(nasdaq_df, sp500_df, sox_df)

        price_raw = tw_fetcher.get_historical(request.symbol, period="10y")
        price_df = normalizer.normalize_ohlcv(price_raw)

        results = []
        for strat in ["S1", "S2", "S3"]:
            cfg = BacktestConfig(
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=request.initial_capital,
                nasdaq_threshold=request.nasdaq_threshold,
                strategy=strat,
            )
            res = BacktestEngine(cfg).run(price_df, us_signals)
            results.append(StrategyResult(
                strategy=strat,
                total_return_pct=res.total_return_pct,
                annualized_return_pct=res.annualized_return_pct,
                max_drawdown_pct=res.max_drawdown_pct,
                sharpe_ratio=res.sharpe_ratio,
                win_rate=res.win_rate,
                total_trades=res.total_trades,
                profit_factor=res.profit_factor,
            ))

        return BacktestCompareResponse(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            results=results,
        )
    except Exception as e:
        logger.error(f"backtest compare 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """觸發回測任務。"""
    from ..backtest.engine import BacktestEngine, BacktestConfig
    from ..data.fetcher import USMarketFetcher, TWMarketFetcher
    from ..data.normalizer import DataNormalizer

    try:
        config = BacktestConfig(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            nasdaq_threshold=request.nasdaq_threshold,
        )

        fetcher = USMarketFetcher()
        tw_fetcher = TWMarketFetcher()
        normalizer = DataNormalizer()

        nasdaq_raw = fetcher.get_historical("nasdaq", period="10y")
        sp500_raw = fetcher.get_historical("sp500", period="10y")
        sox_raw = fetcher.get_historical("sox", period="10y")

        nasdaq_df = normalizer.normalize_ohlcv(nasdaq_raw)
        nasdaq_df = normalizer.calculate_change_pct(nasdaq_df)
        sp500_df = normalizer.normalize_ohlcv(sp500_raw)
        sp500_df = normalizer.calculate_change_pct(sp500_df)
        sox_df = normalizer.normalize_ohlcv(sox_raw)
        sox_df = normalizer.calculate_change_pct(sox_df)

        us_signals = normalizer.merge_us_signals(nasdaq_df, sp500_df, sox_df)

        price_raw = tw_fetcher.get_historical("0050", period="10y")
        price_df = normalizer.normalize_ohlcv(price_raw)

        engine = BacktestEngine(config)
        result = engine.run(price_df, us_signals)

        return BacktestResponse(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            total_return_pct=result.total_return_pct,
            annualized_return_pct=result.annualized_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
            win_rate=result.win_rate,
            total_trades=result.total_trades,
            profit_factor=result.profit_factor,
        )

    except Exception as e:
        logger.error(f"回測執行失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))
