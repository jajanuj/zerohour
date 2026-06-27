"""Async DB helper functions used by Celery tasks and API routes."""
import logging
from datetime import datetime, date, timedelta
from sqlalchemy import select, and_, func, desc

from . import get_session
from .models import (
    MarketPrice,
    TimeDiffSignalRecord,
    TrendSignal,
    OrderRecord,
    FillRecord,
    PositionSnapshot,
    PerformanceSnapshot,
    ReviewReport,
    AgentMarketContext,
    BlackSwanAlertRecord,
    WatchlistItem,
    AgentRunLog,
)

logger = logging.getLogger(__name__)


async def save_market_prices(data: dict) -> None:
    """Save US market price snapshot; skip if symbol already recorded today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_session() as session:
        for key, info in data.items():
            if not info:
                continue
            symbol = info.get("symbol", key)
            existing = await session.execute(
                select(MarketPrice).where(
                    and_(MarketPrice.symbol == symbol, MarketPrice.date >= today_start)
                )
            )
            if existing.scalars().first():
                continue
            session.add(MarketPrice(
                symbol=symbol,
                date=info.get("date") or datetime.utcnow(),
                close=info.get("close", 0),
                change_pct=info.get("change_pct", 0),
                volume=info.get("volume", 0),
                source="yfinance",
            ))
    logger.debug(f"Market prices saved for: {[k for k, v in data.items() if v]}")


async def save_time_diff_signal(
    direction: str,
    confidence: float,
    nasdaq_chg: float,
    sp500_chg: float,
    sox_chg: float,
    trigger_reason: str,
    suggested_action: str = "HOLD",
    suggested_symbol: str = "0050",
) -> int:
    """Save S2 time-diff signal. Returns DB record id."""
    async with get_session() as session:
        record = TimeDiffSignalRecord(
            generated_at=datetime.utcnow(),
            direction=direction,
            confidence=confidence,
            nasdaq_change_pct=nasdaq_chg,
            sp500_change_pct=sp500_chg,
            sox_change_pct=sox_chg,
            trigger_reason=trigger_reason,
            suggested_symbol=suggested_symbol,
            suggested_action=suggested_action,
        )
        session.add(record)
        await session.flush()
        return record.id


async def save_trend_signal(
    symbol: str,
    state: str,
    current_price: float,
    ma200: float,
    distance_pct: float,
    signal_date: datetime,
    is_newly_crossed: bool = False,
) -> None:
    """Save S1 MA200 trend signal."""
    async with get_session() as session:
        session.add(TrendSignal(
            symbol=symbol,
            signal_date=signal_date,
            state=state,
            current_price=current_price,
            ma200=ma200,
            distance_pct=distance_pct,
            is_newly_crossed=is_newly_crossed,
        ))


async def get_open_positions() -> list[dict]:
    """Return latest open position snapshot per symbol (quantity > 0)."""
    async with get_session() as session:
        subq = (
            select(func.max(PositionSnapshot.id))
            .group_by(PositionSnapshot.symbol)
            .scalar_subquery()
        )
        result = await session.execute(
            select(PositionSnapshot).where(
                and_(
                    PositionSnapshot.id.in_(subq),
                    PositionSnapshot.quantity > 0,
                )
            )
        )
        rows = result.scalars().all()
        return [
            {
                "symbol": r.symbol,
                "quantity": float(r.quantity),
                "avg_entry_price": float(r.avg_entry_price),
                "current_price": float(r.current_price) if r.current_price else None,
                "stop_loss_price": float(r.stop_loss_price) if r.stop_loss_price else None,
                "unrealized_pnl": float(r.unrealized_pnl) if r.unrealized_pnl else None,
                "unrealized_pnl_pct": float(r.unrealized_pnl_pct) if r.unrealized_pnl_pct else None,
                "opened_at": r.opened_at,
                "last_updated": r.last_updated,
            }
            for r in rows
        ]


async def open_position(
    signal_id: int,
    symbol: str,
    quantity: float,
    fill_price: float,
    stop_loss_price: float,
) -> None:
    """Record a BUY order and create a position snapshot."""
    now = datetime.utcnow()
    async with get_session() as session:
        order = OrderRecord(
            order_id=f"paper-buy-{now.strftime('%Y%m%d%H%M%S')}",
            symbol=symbol,
            direction="BUY",
            order_type="MARKET",
            quantity=quantity,
            status="FILLED",
            filled_price=fill_price,
            filled_at=now,
            signal_id=signal_id,
            strategy="S3",
            broker="paper",
        )
        session.add(order)
        await session.flush()

        session.add(FillRecord(
            order_id=order.id,
            fill_price=fill_price,
            fill_quantity=quantity,
            commission=0,
            filled_at=now,
        ))

        session.add(PositionSnapshot(
            symbol=symbol,
            quantity=quantity,
            avg_entry_price=fill_price,
            current_price=fill_price,
            stop_loss_price=stop_loss_price,
            peak_price=fill_price,
            unrealized_pnl=0,
            unrealized_pnl_pct=0,
            opened_at=now,
            last_updated=now,
        ))
    logger.info(f"Position opened: BUY {quantity} {symbol} @ {fill_price}")


async def close_position(
    signal_id: int,
    symbol: str,
    fill_price: float,
) -> None:
    """Record a SELL order and close position snapshot (quantity → 0)."""
    now = datetime.utcnow()
    async with get_session() as session:
        # Fetch latest open position
        subq = (
            select(func.max(PositionSnapshot.id))
            .where(PositionSnapshot.symbol == symbol)
            .scalar_subquery()
        )
        result = await session.execute(
            select(PositionSnapshot).where(
                and_(PositionSnapshot.id.in_(subq), PositionSnapshot.quantity > 0)
            )
        )
        pos = result.scalars().first()
        if not pos:
            logger.warning(f"close_position: no open position for {symbol}")
            return

        quantity = float(pos.quantity)
        avg_entry = float(pos.avg_entry_price)
        pnl = (fill_price - avg_entry) * quantity
        pnl_pct = (fill_price - avg_entry) / avg_entry

        order = OrderRecord(
            order_id=f"paper-sell-{now.strftime('%Y%m%d%H%M%S')}",
            symbol=symbol,
            direction="SELL",
            order_type="MARKET",
            quantity=quantity,
            status="FILLED",
            filled_price=fill_price,
            filled_at=now,
            signal_id=signal_id,
            strategy="S3",
            broker="paper",
        )
        session.add(order)
        await session.flush()

        session.add(FillRecord(
            order_id=order.id,
            fill_price=fill_price,
            fill_quantity=quantity,
            commission=0,
            filled_at=now,
        ))

        # Mark position closed
        session.add(PositionSnapshot(
            symbol=symbol,
            quantity=0,
            avg_entry_price=avg_entry,
            current_price=fill_price,
            unrealized_pnl=pnl,
            unrealized_pnl_pct=pnl_pct,
            opened_at=pos.opened_at,
            last_updated=now,
        ))
    logger.info(f"Position closed: SELL {quantity} {symbol} @ {fill_price}, PnL={pnl:.0f}")


async def update_position_price(
    symbol: str,
    current_price: float,
    trailing_stop_pct: float = 0.15,
) -> None:
    """Update unrealized PnL and trailing stop for open position."""
    now = datetime.utcnow()
    async with get_session() as session:
        subq = (
            select(func.max(PositionSnapshot.id))
            .where(PositionSnapshot.symbol == symbol)
            .scalar_subquery()
        )
        result = await session.execute(
            select(PositionSnapshot).where(
                and_(PositionSnapshot.id.in_(subq), PositionSnapshot.quantity > 0)
            )
        )
        pos = result.scalars().first()
        if not pos:
            return

        avg_entry = float(pos.avg_entry_price)
        quantity = float(pos.quantity)
        peak = max(current_price, float(pos.peak_price or current_price))
        trailing_stop = peak * (1 - trailing_stop_pct)
        unrealized_pnl = (current_price - avg_entry) * quantity
        unrealized_pnl_pct = (current_price - avg_entry) / avg_entry

        session.add(PositionSnapshot(
            symbol=symbol,
            quantity=quantity,
            avg_entry_price=avg_entry,
            current_price=current_price,
            stop_loss_price=float(pos.stop_loss_price or 0),
            trailing_stop_price=trailing_stop,
            peak_price=peak,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            opened_at=pos.opened_at,
            last_updated=now,
        ))


async def get_cash_balance(initial_capital: float) -> float:
    """Calculate current cash = initial_capital - buy_cost + sell_proceeds."""
    async with get_session() as session:
        buy_result = await session.execute(
            select(func.sum(OrderRecord.quantity * OrderRecord.filled_price)).where(
                and_(OrderRecord.direction == "BUY", OrderRecord.status == "FILLED")
            )
        )
        sell_result = await session.execute(
            select(func.sum(OrderRecord.quantity * OrderRecord.filled_price)).where(
                and_(OrderRecord.direction == "SELL", OrderRecord.status == "FILLED")
            )
        )
        buy_total = float(buy_result.scalar() or 0)
        sell_total = float(sell_result.scalar() or 0)
        return initial_capital - buy_total + sell_total


async def calculate_win_rate() -> tuple[float, int]:
    """Return (win_rate, total_completed_trades) from sell orders."""
    async with get_session() as session:
        result = await session.execute(
            select(OrderRecord).where(
                and_(OrderRecord.direction == "SELL", OrderRecord.status == "FILLED")
            ).order_by(OrderRecord.filled_at)
        )
        sells = result.scalars().all()
        if not sells:
            return 0.0, 0

        wins = 0
        for sell in sells:
            # Find the position's avg_entry_price from a snapshot before this sell
            pos_result = await session.execute(
                select(PositionSnapshot).where(
                    and_(
                        PositionSnapshot.symbol == sell.symbol,
                        PositionSnapshot.quantity > 0,
                        PositionSnapshot.opened_at <= sell.filled_at,
                    )
                ).order_by(desc(PositionSnapshot.id)).limit(1)
            )
            pos = pos_result.scalars().first()
            if pos and float(sell.filled_price) > float(pos.avg_entry_price):
                wins += 1

        return wins / len(sells) if sells else 0.0, len(sells)


async def save_performance_snapshot(
    initial_capital: float,
    positions_value: float,
    cash: float,
    daily_pnl: float,
) -> None:
    """Save a performance snapshot; skip if one already exists today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_session() as session:
        existing = await session.execute(
            select(PerformanceSnapshot).where(
                PerformanceSnapshot.snapshot_date >= today_start
            )
        )
        if existing.scalars().first():
            return

        total_equity = cash + positions_value
        total_return_pct = (total_equity - initial_capital) / initial_capital

    win_rate, total_trades = await calculate_win_rate()

    async with get_session() as session:
        session.add(PerformanceSnapshot(
            snapshot_date=datetime.utcnow(),
            total_equity=total_equity,
            cash=cash,
            positions_value=positions_value,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_pnl / initial_capital,
            total_return_pct=total_return_pct,
            max_drawdown_pct=0,
            win_rate=win_rate,
            sharpe_ratio=0,
            extra_data={"total_trades": total_trades},
        ))


async def get_today_signal() -> dict | None:
    """Return today's latest time-diff signal record."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_session() as session:
        # Also get latest trend signal
        trend_result = await session.execute(
            select(TrendSignal).order_by(desc(TrendSignal.id)).limit(1)
        )
        trend = trend_result.scalars().first()

        result = await session.execute(
            select(TimeDiffSignalRecord).where(
                TimeDiffSignalRecord.generated_at >= today_start
            ).order_by(desc(TimeDiffSignalRecord.id)).limit(1)
        )
        sig = result.scalars().first()
        if not sig:
            return None
        return {
            "id": sig.id,
            "direction": sig.direction,
            "confidence": float(sig.confidence or 0),
            "nasdaq_change_pct": float(sig.nasdaq_change_pct or 0),
            "sp500_change_pct": float(sig.sp500_change_pct or 0),
            "sox_change_pct": float(sig.sox_change_pct or 0),
            "trigger_reason": sig.trigger_reason,
            "suggested_action": sig.suggested_action,
            "trend_state": trend.state if trend else "UNKNOWN",
        }


async def get_today_orders() -> list[dict]:
    """Return orders created today."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_session() as session:
        result = await session.execute(
            select(OrderRecord).where(
                and_(
                    OrderRecord.created_at >= today_start,
                    OrderRecord.status == "FILLED",
                )
            ).order_by(OrderRecord.created_at)
        )
        rows = result.scalars().all()
        return [
            {
                "direction": r.direction,
                "symbol": r.symbol,
                "quantity": float(r.quantity),
                "filled_price": float(r.filled_price or 0),
                "filled_at": r.filled_at,
                "pnl_pct": 0.0,
            }
            for r in rows
        ]


async def get_week_signals() -> list[dict]:
    """Return time-diff signals from this Mon through today."""
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    week_start = datetime.combine(monday, datetime.min.time())
    async with get_session() as session:
        result = await session.execute(
            select(TimeDiffSignalRecord).where(
                TimeDiffSignalRecord.generated_at >= week_start
            ).order_by(TimeDiffSignalRecord.generated_at)
        )
        rows = result.scalars().all()
        return [
            {
                "date": r.generated_at.date().isoformat(),
                "direction": r.direction,
                "confidence": float(r.confidence or 0),
                "nasdaq_change_pct": float(r.nasdaq_change_pct or 0),
                "suggested_action": r.suggested_action,
            }
            for r in rows
        ]


async def get_week_orders() -> list[dict]:
    """Return orders from this Mon through today."""
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    week_start = datetime.combine(monday, datetime.min.time())
    async with get_session() as session:
        result = await session.execute(
            select(OrderRecord).where(
                and_(
                    OrderRecord.created_at >= week_start,
                    OrderRecord.status == "FILLED",
                )
            ).order_by(OrderRecord.created_at)
        )
        rows = result.scalars().all()
        return [
            {
                "direction": r.direction,
                "symbol": r.symbol,
                "quantity": float(r.quantity),
                "filled_price": float(r.filled_price or 0),
                "filled_at": r.filled_at,
            }
            for r in rows
        ]


async def save_review_report(
    review_date: date,
    review_type: str,
    compliance_score: float = 0,
    signal_quality_score: float = 0,
    ai_analysis: str = "",
    net_pnl: float = 0,
    stability_score: float = 0,
    market_regime: str = "",
) -> None:
    """Upsert a ReviewReport. Weekly review uses Mon date to avoid unique collision."""
    async with get_session() as session:
        existing = await session.execute(
            select(ReviewReport).where(ReviewReport.review_date == review_date)
        )
        report = existing.scalars().first()
        if report:
            report.review_type = review_type
            report.compliance_score = compliance_score
            report.signal_quality_score = signal_quality_score
            report.ai_analysis = ai_analysis
            report.net_pnl = net_pnl
            report.stability_score = stability_score
            report.market_regime = market_regime
        else:
            session.add(ReviewReport(
                review_date=review_date,
                review_type=review_type,
                compliance_score=compliance_score,
                signal_quality_score=signal_quality_score,
                ai_analysis=ai_analysis,
                net_pnl=net_pnl,
                stability_score=stability_score,
                market_regime=market_regime,
            ))


async def get_latest_review(review_type: str) -> dict | None:
    """Return latest ReviewReport of the given type."""
    async with get_session() as session:
        result = await session.execute(
            select(ReviewReport).where(
                ReviewReport.review_type == review_type
            ).order_by(desc(ReviewReport.review_date)).limit(1)
        )
        row = result.scalars().first()
        if not row:
            return None
        return {
            "review_date": row.review_date.isoformat(),
            "review_type": row.review_type,
            "compliance_score": float(row.compliance_score or 0),
            "signal_quality_score": float(row.signal_quality_score or 0),
            "ai_analysis": row.ai_analysis or "",
            "market_regime": row.market_regime or "",
            "stability_score": float(row.stability_score or 0),
            "net_pnl": float(row.net_pnl or 0),
        }


# ── Phase 2 Agent helpers ─────────────────────────────────────────────


async def save_market_context(context_date: date, result: dict) -> None:
    """Upsert AgentMarketContext for the given date."""
    async with get_session() as session:
        existing = await session.execute(
            select(AgentMarketContext).where(AgentMarketContext.context_date == context_date)
        )
        row = existing.scalars().first()
        if row:
            row.market_driver = result.get("market_driver")
            row.taiwan_relevance = result.get("taiwan_relevance")
            row.relevance_reason = result.get("relevance_reason")
            row.confidence_modifier = result.get("confidence_modifier", 0)
            row.key_risks = result.get("key_risks", [])
            row.context_summary = result.get("context_summary")
        else:
            session.add(AgentMarketContext(
                context_date=context_date,
                market_driver=result.get("market_driver"),
                taiwan_relevance=result.get("taiwan_relevance"),
                relevance_reason=result.get("relevance_reason"),
                confidence_modifier=result.get("confidence_modifier", 0),
                key_risks=result.get("key_risks", []),
                context_summary=result.get("context_summary"),
            ))


async def get_latest_market_context() -> dict | None:
    """Return latest AgentMarketContext as dict."""
    async with get_session() as session:
        result = await session.execute(
            select(AgentMarketContext).order_by(desc(AgentMarketContext.context_date)).limit(1)
        )
        row = result.scalars().first()
        if not row:
            return None
        return {
            "context_date": row.context_date.isoformat(),
            "market_driver": row.market_driver or "",
            "taiwan_relevance": row.taiwan_relevance or "MEDIUM",
            "relevance_reason": row.relevance_reason or "",
            "confidence_modifier": float(row.confidence_modifier or 0),
            "key_risks": row.key_risks or [],
            "context_summary": row.context_summary or "",
        }


async def save_black_swan_alert(
    severity: str,
    triggers: list[str],
    action_taken: str,
) -> int:
    """Save BlackSwanAlertRecord if severity > NONE. Returns record id."""
    async with get_session() as session:
        record = BlackSwanAlertRecord(
            detected_at=datetime.utcnow(),
            severity=severity,
            triggers=triggers,
            action_taken=action_taken,
        )
        session.add(record)
        await session.flush()
        return record.id


async def get_latest_black_swan() -> dict | None:
    """Return the latest BlackSwanAlertRecord within last 7 days, or None."""
    cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - timedelta(days=7)
    async with get_session() as session:
        result = await session.execute(
            select(BlackSwanAlertRecord)
            .where(BlackSwanAlertRecord.detected_at >= cutoff)
            .order_by(desc(BlackSwanAlertRecord.detected_at))
            .limit(1)
        )
        row = result.scalars().first()
        if not row:
            return None
        return {
            "detected_at": row.detected_at.isoformat(),
            "severity": row.severity,
            "triggers": row.triggers or [],
            "action_taken": row.action_taken or "",
        }


async def save_watchlist(items: list[dict]) -> None:
    """
    Replace active watchlist with new items.
    Deactivate old items, insert new ones.
    """
    now = datetime.utcnow()
    expires = now + timedelta(days=8)  # 下次掃描前有效（7天+緩衝）
    async with get_session() as session:
        # Mark all existing active items as expired
        result = await session.execute(
            select(WatchlistItem).where(WatchlistItem.status == "active")
        )
        for old in result.scalars().all():
            old.status = "expired"
        # Insert new items
        for item in items:
            session.add(WatchlistItem(
                symbol=item["symbol"],
                overall_score=item["overall_score"],
                recommendation=item["recommendation"],
                thesis=item["thesis"],
                risks=item.get("risks", []),
                entry_condition=item.get("entry_condition", ""),
                agent_results=item.get("agent_results", {}),
                status="active",
                generated_at=now,
                expires_at=expires,
            ))


async def get_watchlist() -> list[dict]:
    """Return active watchlist items sorted by score desc."""
    async with get_session() as session:
        result = await session.execute(
            select(WatchlistItem)
            .where(WatchlistItem.status == "active")
            .order_by(desc(WatchlistItem.overall_score))
        )
        rows = result.scalars().all()
        return [
            {
                "symbol": r.symbol,
                "overall_score": float(r.overall_score or 0),
                "recommendation": r.recommendation or "",
                "thesis": r.thesis or "",
                "risks": r.risks or [],
                "entry_condition": r.entry_condition or "",
                "agent_results": r.agent_results or {},
                "generated_at": r.generated_at.isoformat() if r.generated_at else "",
                "expires_at": r.expires_at.isoformat() if r.expires_at else "",
            }
            for r in rows
        ]


async def log_agent_run(
    run_type: str,
    symbol: str | None,
    tokens_used: int,
    success: bool,
    duration_ms: int = 0,
    error_message: str | None = None,
) -> None:
    """Log an agent run with token usage."""
    cost = tokens_used * 0.00000015  # gemini-2.5-flash 估算成本
    async with get_session() as session:
        session.add(AgentRunLog(
            run_type=run_type,
            symbol=symbol,
            tokens_used=tokens_used,
            cost_usd=cost,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        ))


async def get_latest_performance() -> dict | None:
    """Return the most recent performance snapshot."""
    async with get_session() as session:
        result = await session.execute(
            select(PerformanceSnapshot).order_by(desc(PerformanceSnapshot.snapshot_date)).limit(1)
        )
        row = result.scalars().first()
        if not row:
            return None
        return {
            "total_equity": float(row.total_equity or 0),
            "cash": float(row.cash or 0),
            "positions_value": float(row.positions_value or 0),
            "daily_pnl": float(row.daily_pnl or 0),
            "daily_return_pct": float(row.daily_return_pct or 0),
            "total_return_pct": float(row.total_return_pct or 0),
            "max_drawdown_pct": float(row.max_drawdown_pct or 0),
            "win_rate": float(row.win_rate or 0),
            "sharpe_ratio": float(row.sharpe_ratio or 0),
            "extra_data": row.extra_data or {},
            "snapshot_date": row.snapshot_date,
        }
