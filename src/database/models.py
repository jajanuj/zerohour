from sqlalchemy import (
    Column, String, Float, Integer, Boolean,
    DateTime, JSON, ForeignKey, Index, Numeric, Date, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime


class Base(DeclarativeBase):
    pass


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        Index("ix_market_prices_symbol_date", "symbol", "date", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    date = Column(DateTime, nullable=False)
    open = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    close = Column(Numeric(12, 4), nullable=False)
    volume = Column(Integer)
    change_pct = Column(Numeric(8, 4))
    source = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class TrendSignal(Base):
    __tablename__ = "trend_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    signal_date = Column(DateTime, nullable=False)
    state = Column(String(10), nullable=False)
    current_price = Column(Numeric(12, 4))
    ma200 = Column(Numeric(12, 4))
    distance_pct = Column(Numeric(8, 4))
    is_newly_crossed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TimeDiffSignalRecord(Base):
    __tablename__ = "time_diff_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generated_at = Column(DateTime, nullable=False)
    direction = Column(String(10), nullable=False)
    confidence = Column(Numeric(4, 3))
    nasdaq_change_pct = Column(Numeric(8, 4))
    sp500_change_pct = Column(Numeric(8, 4))
    sox_change_pct = Column(Numeric(8, 4))
    trigger_reason = Column(String(500))
    suggested_symbol = Column(String(20))
    suggested_action = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)


class OrderRecord(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, nullable=False)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(5), nullable=False)
    order_type = Column(String(20), nullable=False)
    quantity = Column(Numeric(12, 4), nullable=False)
    limit_price = Column(Numeric(12, 4))
    stop_price = Column(Numeric(12, 4))
    status = Column(String(20), nullable=False)
    filled_price = Column(Numeric(12, 4))
    filled_at = Column(DateTime)
    signal_id = Column(Integer, ForeignKey("time_diff_signals.id"), nullable=True)
    strategy = Column(String(10))
    broker = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)
    fills = relationship("FillRecord", back_populates="order")


class FillRecord(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    fill_price = Column(Numeric(12, 4), nullable=False)
    fill_quantity = Column(Numeric(12, 4), nullable=False)
    commission = Column(Numeric(10, 4), default=0)
    filled_at = Column(DateTime, nullable=False)
    order = relationship("OrderRecord", back_populates="fills")


class PositionSnapshot(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    quantity = Column(Numeric(12, 4), nullable=False)
    avg_entry_price = Column(Numeric(12, 4), nullable=False)
    current_price = Column(Numeric(12, 4))
    stop_loss_price = Column(Numeric(12, 4))
    trailing_stop_price = Column(Numeric(12, 4))
    peak_price = Column(Numeric(12, 4))
    unrealized_pnl = Column(Numeric(12, 4))
    unrealized_pnl_pct = Column(Numeric(8, 4))
    opened_at = Column(DateTime)
    last_updated = Column(DateTime, default=datetime.utcnow)


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, nullable=False, unique=True)
    total_equity = Column(Numeric(15, 4))
    cash = Column(Numeric(15, 4))
    positions_value = Column(Numeric(15, 4))
    daily_pnl = Column(Numeric(12, 4))
    daily_return_pct = Column(Numeric(8, 4))
    total_return_pct = Column(Numeric(8, 4))
    max_drawdown_pct = Column(Numeric(8, 4))
    win_rate = Column(Numeric(5, 4))
    sharpe_ratio = Column(Numeric(8, 4))
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── 覆盤相關表格（§12）──────────────────────────────────────────

class ReviewReport(Base):
    __tablename__ = "review_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_date = Column(Date, nullable=False, unique=True)
    review_type = Column(String(20), nullable=False)
    compliance_score = Column(Numeric(5, 2))
    signal_quality_score = Column(Numeric(5, 2))
    ai_analysis = Column(Text)
    net_pnl = Column(Numeric(12, 4))
    tax_cost = Column(Numeric(10, 4))
    stability_score = Column(Numeric(5, 2))
    market_regime = Column(String(30))
    created_at = Column(DateTime, default=datetime.utcnow)


class ManualOverride(Base):
    __tablename__ = "manual_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    override_type = Column(String(50), nullable=False)
    reason = Column(Text, nullable=False)
    system_recommendation = Column(JSON)
    actual_action = Column(JSON)
    actual_pnl_pct = Column(Numeric(8, 4))
    counterfactual_pnl_pct = Column(Numeric(8, 4))
    helped = Column(Boolean)
    override_at = Column(DateTime, nullable=False)


class EdgeDecayAlert(Base):
    __tablename__ = "edge_decay_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_date = Column(Date, nullable=False)
    metric = Column(String(50), nullable=False)
    value = Column(Numeric(8, 4))
    threshold = Column(Numeric(8, 4))
    action_taken = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    parameters = Column(JSON, nullable=False)
    change_reason = Column(String(500), nullable=False)
    supporting_data = Column(JSON)
    expected_improvement = Column(String(200))
    actual_improvement = Column(String(200))
    activated_at = Column(DateTime)
    deactivated_at = Column(DateTime)
    created_by = Column(String(50), default="system")
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Multi-Agent 相關表格（§13）────────────────────────────────────

class AgentMarketContext(Base):
    __tablename__ = "agent_market_contexts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    context_date = Column(Date, nullable=False, unique=True)
    market_driver = Column(Text)
    taiwan_relevance = Column(String(10))
    relevance_reason = Column(Text)
    confidence_modifier = Column(Numeric(4, 3))
    key_risks = Column(JSON)
    context_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class BlackSwanAlertRecord(Base):
    __tablename__ = "black_swan_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detected_at = Column(DateTime, nullable=False)
    severity = Column(String(20), nullable=False)
    triggers = Column(JSON)
    action_taken = Column(String(100))
    resolved_at = Column(DateTime)
    resolved_by = Column(String(50))


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    overall_score = Column(Numeric(5, 2))
    recommendation = Column(String(10))
    thesis = Column(Text)
    risks = Column(JSON)
    entry_condition = Column(Text)
    agent_results = Column(JSON)
    status = Column(String(20), default="active")
    generated_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentRunLog(Base):
    __tablename__ = "agent_run_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_type = Column(String(50), nullable=False)
    symbol = Column(String(20))
    tokens_used = Column(Integer)
    cost_usd = Column(Numeric(8, 6))
    duration_ms = Column(Integer)
    success = Column(Boolean)
    error_message = Column(Text)
    run_at = Column(DateTime, default=datetime.utcnow)
