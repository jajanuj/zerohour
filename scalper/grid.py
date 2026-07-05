"""
影線區間刷單決策核心（scalper-spec.md §1 v0 規則表）。純函式風格：輸入 tick/五檔事件，
輸出動作列表，不直接碰 broker——Phase 2 回測與 Phase 3 實跑共用同一份決策代碼（§3 設計鐵則）。

模組分工（重要，勿與 risk_guard.py 混淆）：
- GridStrategy（本檔）：策略戰術層——區間內掛哪一邊、逆選擇過濾、單筆停損、
  區間失效時的「戰術暫停」（停到下一根 60 分K完成即自動恢復）。
- RiskGuard（risk_guard.py）：帳戶風控層——熔斷、庫存上限、日曆過濾，
  唯一有權擋下「今天還能不能進場」的模組。GridStrategy 提議進場，
  由呼叫端（runner.py / replay.py）先問過 RiskGuard.can_enter() 才放行。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from .range_engine import RangeEngine


class ActionType(str, Enum):
    PLACE_LIMIT = "PLACE_LIMIT"
    CANCEL = "CANCEL"
    MARKET_EXIT = "MARKET_EXIT"
    HALT = "HALT"
    RESUME = "RESUME"


@dataclass
class GridAction:
    type: ActionType
    price: Optional[float] = None
    direction: Optional[str] = None  # BUY / SELL
    reason: str = ""


@dataclass
class DepthSnapshot:
    ts: datetime
    bid_qty_total: int      # 買方五檔合計量（逆選擇過濾用）
    ask_qty_total: int      # 賣方五檔合計量（逆選擇過濾用）
    best_bid_qty: int = 0   # 買一量（掛買單排隊基準，供 Phase 2 回測用）
    best_ask_qty: int = 0   # 賣一量（掛賣單排隊基準，供 Phase 2 回測用）


@dataclass
class TradePrint:
    ts: datetime
    price: float
    qty: int
    side: str  # "buy_initiated" / "sell_initiated"（內外盤）


class Position(str, Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class GridState:
    position: Position = Position.FLAT
    entry_price: Optional[float] = None
    entry_ts: Optional[datetime] = None
    pending_order_price: Optional[float] = None
    pending_order_direction: Optional[str] = None
    halted: bool = False
    halt_reason: str = ""


class GridStrategy:
    def __init__(
        self,
        tick_size: float,
        depth_qty_threshold: int,
        aggressive_volume_threshold: int,
        aggressive_window_seconds: int,
        stop_loss_ticks: int,
        aggressive_cooldown_seconds: int = 60,
    ):
        self.tick_size = tick_size
        self.depth_qty_threshold = depth_qty_threshold
        self.aggressive_volume_threshold = aggressive_volume_threshold
        self.aggressive_window_seconds = aggressive_window_seconds
        self.stop_loss_ticks = stop_loss_ticks
        self.aggressive_cooldown_seconds = aggressive_cooldown_seconds

        self.range_engine = RangeEngine()
        self.state = GridState()
        self._recent_trades: list[TradePrint] = []
        self._latest_depth: Optional[DepthSnapshot] = None
        self._cooldown_until: Optional[datetime] = None
        self._halted_reference_start: Optional[datetime] = None

    # ---- 事件輸入 ----

    def on_depth(self, depth: DepthSnapshot) -> None:
        self._latest_depth = depth

    def on_trade(self, trade: TradePrint) -> list[GridAction]:
        actions: list[GridAction] = []
        self.range_engine.on_tick(trade.ts, trade.price)
        self._recent_trades.append(trade)
        self._prune_recent_trades(trade.ts)

        reference = self.range_engine.reference

        if self.state.position != Position.FLAT:
            if reference is not None and reference.is_breakout(trade.price):
                exit_direction = "SELL" if self.state.position == Position.LONG else "BUY"
                self.state.halted = True
                self.state.halt_reason = "RANGE_BREAKOUT"
                self._halted_reference_start = reference.source_bar_start
                return [GridAction(
                    ActionType.MARKET_EXIT, direction=exit_direction,
                    reason=f"持倉中價格突破參考區間 [{reference.low:.2f}, {reference.high:.2f}]，平倉",
                )]
            actions += self._check_stop_loss(trade.ts, trade.price)
            return actions

        if self.state.halted:
            resumed, resume_reason = self._check_resume(trade.ts)
            if resumed:
                self.state.halted = False
                self.state.halt_reason = ""
                self._cooldown_until = None
                self._halted_reference_start = None
                actions.append(GridAction(ActionType.RESUME, reason=resume_reason))
            else:
                return actions

        if reference is None:
            return actions

        if reference.is_breakout(trade.price):
            self._cancel_pending(actions, "區間失效前撤單")
            self.state.halted = True
            self.state.halt_reason = "RANGE_BREAKOUT"
            self._halted_reference_start = reference.source_bar_start
            actions.append(GridAction(
                ActionType.HALT,
                reason=f"價格突破參考區間 [{reference.low:.2f}, {reference.high:.2f}]，停機至下一根60分K完成",
            ))
            return actions

        if self._is_aggressive_flow():
            self._cancel_pending(actions, "偵測單邊主動成交量過大，撤單暫停")
            self.state.halted = True
            self.state.halt_reason = "AGGRESSIVE_FLOW"
            self._cooldown_until = trade.ts + timedelta(seconds=self.aggressive_cooldown_seconds)
            actions.append(GridAction(ActionType.HALT, reason="單邊主動成交量過大，暫停"))
            return actions

        direction = "BUY" if trade.price < reference.mid else "SELL"

        if self.state.pending_order_price is not None:
            same_order = (
                self.state.pending_order_direction == direction
                and abs(self.state.pending_order_price - trade.price) < 1e-9
            )
            if same_order:
                return actions
            self._cancel_pending(actions, "價格已變動，撤舊單")

        if self._latest_depth is not None:
            opposite_qty = (
                self._latest_depth.ask_qty_total if direction == "BUY" else self._latest_depth.bid_qty_total
            )
            if opposite_qty < self.depth_qty_threshold:
                return actions  # 對手方太薄，不掛

        actions.append(GridAction(
            ActionType.PLACE_LIMIT,
            price=trade.price,
            direction=direction,
            reason=f"區間{'下半部' if direction == 'BUY' else '上半部'}掛{direction}",
        ))
        self.state.pending_order_price = trade.price
        self.state.pending_order_direction = direction
        return actions

    def on_order_filled(self, ts: datetime, price: float, direction: str) -> list[GridAction]:
        """進場單成交後呼叫：登記持倉並掛 1 tick 反向出場單（停利）。"""
        self.state.position = Position.LONG if direction == "BUY" else Position.SHORT
        self.state.entry_price = price
        self.state.entry_ts = ts
        self.state.pending_order_price = None
        self.state.pending_order_direction = None

        exit_direction = "SELL" if direction == "BUY" else "BUY"
        exit_price = price + self.tick_size if direction == "BUY" else price - self.tick_size
        return [GridAction(
            ActionType.PLACE_LIMIT, price=exit_price, direction=exit_direction,
            reason="成交後掛1tick反向出場單（停利）",
        )]

    def on_position_closed(self) -> None:
        """出場單（停利或市價停損）成交後呼叫，清空持倉狀態。"""
        self.state.position = Position.FLAT
        self.state.entry_price = None
        self.state.entry_ts = None

    # ---- 內部邏輯 ----

    def _check_stop_loss(self, ts: datetime, price: float) -> list[GridAction]:
        if self.state.entry_price is None:
            return []

        if self.state.position == Position.LONG:
            loss_ticks = (self.state.entry_price - price) / self.tick_size
            exit_direction = "SELL"
        else:
            loss_ticks = (price - self.state.entry_price) / self.tick_size
            exit_direction = "BUY"

        if loss_ticks >= self.stop_loss_ticks:
            return [GridAction(
                ActionType.MARKET_EXIT, direction=exit_direction,
                reason=f"反向 {self.stop_loss_ticks} ticks 觸發停損",
            )]
        return []

    def _check_resume(self, ts: datetime) -> tuple[bool, str]:
        if self.state.halt_reason == "RANGE_BREAKOUT":
            ref = self.range_engine.reference
            if ref is not None and ref.source_bar_start != self._halted_reference_start:
                return True, "下一根60分K完成，恢復交易"
            return False, ""
        if self.state.halt_reason == "AGGRESSIVE_FLOW":
            if self._cooldown_until is not None and ts >= self._cooldown_until:
                return True, "冷卻結束，恢復交易"
            return False, ""
        return True, "恢復交易"

    def _cancel_pending(self, actions: list[GridAction], reason: str) -> None:
        if self.state.pending_order_price is not None:
            actions.append(GridAction(
                ActionType.CANCEL, price=self.state.pending_order_price,
                direction=self.state.pending_order_direction, reason=reason,
            ))
            self.state.pending_order_price = None
            self.state.pending_order_direction = None

    def _prune_recent_trades(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.aggressive_window_seconds)
        self._recent_trades = [t for t in self._recent_trades if t.ts >= cutoff]

    def _is_aggressive_flow(self) -> bool:
        buy_vol = sum(t.qty for t in self._recent_trades if t.side == "buy_initiated")
        sell_vol = sum(t.qty for t in self._recent_trades if t.side == "sell_initiated")
        return buy_vol >= self.aggressive_volume_threshold or sell_vol >= self.aggressive_volume_threshold
