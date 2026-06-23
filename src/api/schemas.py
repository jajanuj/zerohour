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
    avg_price: float
    market_value: Optional[float] = None


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
