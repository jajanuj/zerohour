"""
悲觀成交模型與回測引擎（scalper-spec.md §7）。假設**禁止放寬**：
1) 掛單時記錄 queue_ahead = 該價位當時的排隊量（買單用買一量、賣單用賣一量）
2) 之後同價位每筆成交消耗 queue_ahead，歸零後才算輪到我
3) 成交價「穿過」（嚴格優於）掛單價才視為立即成交；只是「碰到」不算
4) 下單/撤單各加 order_ack_delay_ms 延遲，延遲期間的成交不算數（不得用未來資訊佔便宜）

run_backtest() 把 GridStrategy + RiskGuard + PessimisticFillSimulator 串起來，
跑一段已排序的 (TradePrint, DepthSnapshot) 事件流，輸出逐筆 TradeRecord 與匯總統計。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Union

from .grid import ActionType, DepthSnapshot, GridStrategy, TradePrint
from .risk_guard import RiskGuard


@dataclass
class RestingOrder:
    order_id: str
    direction: str  # BUY / SELL
    price: float
    qty: int
    placed_ts: datetime
    queue_ahead: int


class PessimisticFillSimulator:
    def __init__(self, order_ack_delay_ms: int = 300):
        self.order_ack_delay_ms = order_ack_delay_ms
        self._resting: dict[str, RestingOrder] = {}
        self._next_id = 1

    def submit(self, direction: str, price: float, qty: int, placed_ts: datetime, queue_ahead: int) -> str:
        order_id = f"fill-{self._next_id}"
        self._next_id += 1
        self._resting[order_id] = RestingOrder(order_id, direction, price, qty, placed_ts, max(0, queue_ahead))
        return order_id

    def cancel(self, order_id: str) -> None:
        self._resting.pop(order_id, None)

    def cancel_at_price(self, direction: str, price: float) -> None:
        for order_id, order in list(self._resting.items()):
            if order.direction == direction and abs(order.price - price) < 1e-9:
                del self._resting[order_id]

    def cancel_by_direction(self, direction: str) -> None:
        for order_id, order in list(self._resting.items()):
            if order.direction == direction:
                del self._resting[order_id]

    def on_trade_print(self, ts: datetime, price: float, qty: int) -> list[tuple[str, float, datetime]]:
        """回傳這筆成交造成的掛單成交列表 [(order_id, fill_price, fill_ts), ...]。"""
        filled: list[tuple[str, float, datetime]] = []
        for order_id, order in list(self._resting.items()):
            elapsed_ms = (ts - order.placed_ts).total_seconds() * 1000
            if elapsed_ms < self.order_ack_delay_ms:
                continue  # 下單延遲期間，行情變化不算數

            is_price_through = (
                (order.direction == "BUY" and price < order.price)
                or (order.direction == "SELL" and price > order.price)
            )
            is_same_price = abs(price - order.price) < 1e-9

            if is_price_through:
                filled.append((order_id, order.price, ts))
                del self._resting[order_id]
            elif is_same_price:
                order.queue_ahead -= qty
                if order.queue_ahead <= 0:
                    filled.append((order_id, order.price, ts))
                    del self._resting[order_id]
        return filled


@dataclass
class TradeRecord:
    entry_ts: datetime
    exit_ts: datetime
    direction: str
    entry_price: float
    exit_price: float
    ticks_pnl: float
    fees: float
    tax: float
    net_pnl: float
    exit_reason: str  # TP / SL / RANGE_BREAK / EOD


@dataclass
class BacktestResult:
    trades: list[TradeRecord] = field(default_factory=list)
    n_trades: int = 0
    win_rate: float = 0.0
    avg_win_ticks: float = 0.0
    avg_loss_ticks: float = 0.0
    net_pnl: float = 0.0
    max_daily_drawdown: float = 0.0
    daily_pnl: dict = field(default_factory=dict)


def summarize(trades: list[TradeRecord]) -> BacktestResult:
    if not trades:
        return BacktestResult()

    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]

    daily_pnl: dict[date, float] = {}
    for t in trades:
        d = t.exit_ts.date()
        daily_pnl[d] = daily_pnl.get(d, 0.0) + t.net_pnl

    max_dd = min(daily_pnl.values()) if daily_pnl else 0.0
    max_dd = min(max_dd, 0.0)

    return BacktestResult(
        trades=trades,
        n_trades=len(trades),
        win_rate=len(wins) / len(trades),
        avg_win_ticks=(sum(t.ticks_pnl for t in wins) / len(wins)) if wins else 0.0,
        avg_loss_ticks=(sum(t.ticks_pnl for t in losses) / len(losses)) if losses else 0.0,
        net_pnl=sum(t.net_pnl for t in trades),
        max_daily_drawdown=max_dd,
        daily_pnl=daily_pnl,
    )


def compute_cost(price: float, qty: int, fee_per_side: float, tax_rate: float, contract_multiplier: float) -> float:
    """單邊成本：手續費 + 期交稅（契約價值 × tax_rate）。進出各收一次，呼叫端各算一邊。"""
    contract_value = price * qty * contract_multiplier
    return fee_per_side + contract_value * tax_rate


def run_backtest(
    events: list[Union[TradePrint, DepthSnapshot]],
    grid: GridStrategy,
    risk_guard: RiskGuard,
    tick_size: float,
    tick_value: float,
    fee_per_side: float,
    tax_rate: float,
    contract_multiplier: float = 100.0,
    order_ack_delay_ms: int = 300,
) -> BacktestResult:
    """
    重放一段已依時間排序的事件流（TradePrint 與 DepthSnapshot 混合）。
    簡化假設（v0，待 Phase 2 用真實資料校正）：
    - queue_ahead 用最近一次 DepthSnapshot 的 best_bid_qty/best_ask_qty 估計
    - MARKET_EXIT（停損/區間失效）假設以觸發當下的成交價完全成交（無滑價）——
      這是保護性出場的簡化假設，偏保守中性，不會虛增獲利
    """
    fill_sim = PessimisticFillSimulator(order_ack_delay_ms=order_ack_delay_ms)
    trades: list[TradeRecord] = []
    latest_depth: Optional[DepthSnapshot] = None
    pending_entry: Optional[dict] = None  # {"order_id", "direction", "price", "placed_ts"}

    for event in events:
        if isinstance(event, DepthSnapshot):
            latest_depth = event
            grid.on_depth(event)
            continue

        trade = event
        allowed, _reason = risk_guard.can_enter(trade.ts)

        actions = grid.on_trade(trade)

        for action in actions:
            if action.type == ActionType.PLACE_LIMIT and grid.state.position.value == "FLAT" and pending_entry is None:
                if not allowed:
                    continue  # RiskGuard 擋下進場，忽略這次掛單提議
                queue_ahead = 0
                if latest_depth is not None:
                    queue_ahead = (
                        latest_depth.best_bid_qty if action.direction == "BUY" else latest_depth.best_ask_qty
                    )
                order_id = fill_sim.submit(action.direction, action.price, 1, trade.ts, queue_ahead)
                pending_entry = {"order_id": order_id, "direction": action.direction, "price": action.price, "placed_ts": trade.ts}

            elif action.type == ActionType.CANCEL:
                if pending_entry is not None and pending_entry["direction"] == action.direction:
                    fill_sim.cancel(pending_entry["order_id"])
                    pending_entry = None
                fill_sim.cancel_at_price(action.direction, action.price)

            elif action.type == ActionType.MARKET_EXIT:
                entry_price = grid.state.entry_price
                entry_ts = grid.state.entry_ts
                exit_price = trade.price
                fill_sim.cancel_by_direction(action.direction)  # 清掉已無效的停利掛單
                trades.append(_build_trade_record(
                    entry_ts, trade.ts, action.direction, entry_price, exit_price,
                    tick_size, tick_value, fee_per_side, tax_rate, contract_multiplier,
                    exit_reason="SL" if grid.state.halt_reason != "RANGE_BREAKOUT" else "RANGE_BREAK",
                ))
                risk_guard.record_exit_pnl(trade.ts, trades[-1].net_pnl)
                grid.on_position_closed()

        # 成交撮合：先處理進場單
        if pending_entry is not None:
            filled = fill_sim.on_trade_print(trade.ts, trade.price, trade.qty)
            for order_id, fill_price, fill_ts in filled:
                if order_id == pending_entry["order_id"]:
                    direction = pending_entry["direction"]
                    pending_entry = None
                    risk_guard.record_entry(fill_ts)
                    exit_actions = grid.on_order_filled(fill_ts, fill_price, direction)
                    for exit_action in exit_actions:
                        if exit_action.type == ActionType.PLACE_LIMIT:
                            queue_ahead = 0
                            if latest_depth is not None:
                                queue_ahead = (
                                    latest_depth.best_bid_qty if exit_action.direction == "BUY"
                                    else latest_depth.best_ask_qty
                                )
                            fill_sim.submit(exit_action.direction, exit_action.price, 1, fill_ts, queue_ahead)
        else:
            # 持倉中：檢查停利單是否成交
            filled = fill_sim.on_trade_print(trade.ts, trade.price, trade.qty)
            for order_id, fill_price, fill_ts in filled:
                if grid.state.position.value != "FLAT" and grid.state.entry_price is not None:
                    direction = "SELL" if grid.state.position.value == "LONG" else "BUY"
                    trades.append(_build_trade_record(
                        grid.state.entry_ts, fill_ts, direction, grid.state.entry_price, fill_price,
                        tick_size, tick_value, fee_per_side, tax_rate, contract_multiplier,
                        exit_reason="TP",
                    ))
                    risk_guard.record_exit_pnl(fill_ts, trades[-1].net_pnl)
                    grid.on_position_closed()

    return summarize(trades)


def _build_trade_record(
    entry_ts: datetime, exit_ts: datetime, exit_direction: str,
    entry_price: float, exit_price: float,
    tick_size: float, tick_value: float, fee_per_side: float, tax_rate: float, contract_multiplier: float,
    exit_reason: str,
) -> TradeRecord:
    entry_direction = "BUY" if exit_direction == "SELL" else "SELL"

    if entry_direction == "BUY":
        ticks_pnl = (exit_price - entry_price) / tick_size
    else:
        ticks_pnl = (entry_price - exit_price) / tick_size

    fees = fee_per_side * 2
    tax = (
        compute_cost(entry_price, 1, 0.0, tax_rate, contract_multiplier)
        + compute_cost(exit_price, 1, 0.0, tax_rate, contract_multiplier)
    )
    gross_pnl = ticks_pnl * tick_value
    net_pnl = gross_pnl - fees - tax

    return TradeRecord(
        entry_ts=entry_ts, exit_ts=exit_ts, direction=entry_direction,
        entry_price=entry_price, exit_price=exit_price,
        ticks_pnl=ticks_pnl, fees=fees, tax=tax, net_pnl=net_pnl, exit_reason=exit_reason,
    )
