"""Async DB helper functions used by Celery tasks and API routes."""
import logging
from datetime import datetime
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
