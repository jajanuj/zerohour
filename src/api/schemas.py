from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class TrendSignalSchema(BaseModel):
    symbol: str
    state: str
    current_price: float
    ma200: float
    distance_pct: float
    signal_date: datetime
    is_newly_crossed: bool


class TimeDiffSignalSchema(BaseModel):
    direction: str
    confidence: float
    nasdaq_change_pct: float
    sp500_change_pct: float
    sox_change_pct: float
    trigger_reason: str
    generated_at: datetime


class CombinedSignalSchema(BaseModel):
    final_action: str
    symbol: str
    suggested_position_pct: float
    stop_loss_pct: float
    reason: str


class CurrentSignalsResponse(BaseModel):
    trend: Optional[TrendSignalSchema] = None
    time_diff: Optional[TimeDiffSignalSchema] = None
    combined: Optional[CombinedSignalSchema] = None


class PositionSchema(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


class ReviewReportSchema(BaseModel):
    review_date: str
    review_type: str
    compliance_score: Optional[float] = None
    signal_quality_score: Optional[float] = None
    ai_analysis: Optional[str] = None
    market_regime: Optional[str] = None
    stability_score: Optional[float] = None
    net_pnl: Optional[float] = None


class OrderRequest(BaseModel):
    symbol: str
    direction: str = Field(pattern="^(BUY|SELL)$")
    order_type: str = Field(default="MARKET")
    quantity: float = Field(gt=0)
    strategy: str = Field(default="S3")
    limit_price: Optional[float] = None


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    direction: str
    quantity: float
    status: str
    filled_price: Optional[float] = None
    filled_at: Optional[datetime] = None


class PerformanceResponse(BaseModel):
    period: str
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    sharpe_ratio: float
    profit_factor: float


class MarketContextSchema(BaseModel):
    context_date: str
    market_driver: str
    taiwan_relevance: str
    relevance_reason: str
    confidence_modifier: float
    key_risks: list[str] = []
    context_summary: str


class BlackSwanSchema(BaseModel):
    detected_at: str
    severity: str
    triggers: list[str] = []
    action_taken: str


class WatchlistItemSchema(BaseModel):
    symbol: str
    overall_score: float
    recommendation: str
    thesis: str
    risks: list[str] = []
    entry_condition: str = ""
    agent_results: dict = {}
    generated_at: str = ""
    expires_at: str = ""


class BacktestRequest(BaseModel):
    strategy: str = Field(default="S3")
    symbol: str = Field(default="QQQ")
    start_date: str = Field(default="2015-01-01")
    end_date: str = Field(default="2025-12-31")
    initial_capital: float = Field(default=1_000_000)
    nasdaq_threshold: float = Field(default=1.5)


class BacktestResponse(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_factor: float


class PerformanceHistoryItem(BaseModel):
    date: str
    total_equity: float
    total_return_pct: float
    daily_pnl: float


class SignalHistoryItem(BaseModel):
    date: str
    direction: str
    confidence: float
    nasdaq_change_pct: float
    sp500_change_pct: float
    sox_change_pct: float
    suggested_action: str
    trigger_reason: str
    trend_state: str
    ma200_distance: float


class BacktestCompareRequest(BaseModel):
    symbol: str = Field(default="0050")
    start_date: str = Field(default="2020-01-01")
    end_date: str = Field(default="2026-01-01")
    initial_capital: float = Field(default=1_000_000)
    nasdaq_threshold: float = Field(default=1.5)


class StrategyResult(BaseModel):
    strategy: str
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_factor: float


class BacktestCompareResponse(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    results: list[StrategyResult]


class TaskTriggerResponse(BaseModel):
    status: str
    task: str
    message: str = ""
