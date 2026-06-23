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
    BacktestRequest,
    BacktestResponse,
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
    """取得目前最新訊號狀態（讀取 DB 最新記錄）。"""
    # TODO: 從 DB 讀取最新訊號（Phase D 完成基本骨架，DB 整合在部署後填入）
    return CurrentSignalsResponse()


@router.get("/positions", response_model=list[PositionSchema])
async def get_positions():
    """取得目前所有持倉。"""
    return []


@router.post("/orders", response_model=OrderResponse)
async def create_order(request: OrderRequest):
    """手動建立訂單（需確認 trading_mode）。"""
    if settings.trading_mode == "observe":
        raise HTTPException(status_code=403, detail="系統處於觀察模式，不允許下單")
    # TODO: 整合 OrderManager
    raise HTTPException(status_code=501, detail="下單功能待整合 Broker")


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance():
    """取得績效摘要。"""
    # TODO: 從 DB 讀取 performance_snapshots
    return PerformanceResponse(
        period="ytd",
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        win_rate=0.0,
        total_trades=0,
        sharpe_ratio=0.0,
        profit_factor=0.0,
    )


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
