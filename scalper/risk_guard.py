"""
帳戶層級風控守門員（scalper-spec.md §1 熔斷/庫存上限/日曆過濾，A3 參數）。

唯一有權擋下「今天還能不能再進場」的模組。與 grid.py 的戰術層暫停（區間失效、
主動量過大冷卻，停完自動恢復）分工不同：這裡管的是帳戶層的熔斷，
觸發後需要人工介入或等下一個交易日才恢復——見 grid.py 模組頂部說明。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


def is_settlement_day(d: date) -> bool:
    """股期結算日：每月第三個週三。"""
    if d.weekday() != 2:  # 0=Monday ... 2=Wednesday
        return False
    wednesday_count = sum(1 for day in range(1, d.day + 1) if date(d.year, d.month, day).weekday() == 2)
    return wednesday_count == 3


@dataclass
class RiskGuardState:
    trading_date: Optional[date] = None
    cumulative_pnl: float = 0.0
    consecutive_losses: int = 0
    day_halted: bool = False
    day_halt_reason: str = ""
    pause_until: Optional[datetime] = None
    open_lots: int = 0


class RiskGuard:
    def __init__(
        self,
        daily_loss_limit: float,
        consecutive_loss_pause: int,
        consecutive_loss_pause_minutes: int,
        max_inventory_lots: int,
        session_start: str = "09:05",
        session_end: str = "13:15",
        blackout_dates: Optional[set] = None,
    ):
        self.daily_loss_limit = abs(daily_loss_limit)
        self.consecutive_loss_pause = consecutive_loss_pause
        self.consecutive_loss_pause_minutes = consecutive_loss_pause_minutes
        self.max_inventory_lots = max_inventory_lots
        self.session_start = session_start
        self.session_end = session_end
        self.blackout_dates = blackout_dates or set()
        self.state = RiskGuardState()

    def reset_for_new_day(self, ts: datetime) -> None:
        self.state = RiskGuardState(trading_date=ts.date())

    def _ensure_day(self, ts: datetime) -> None:
        if self.state.trading_date != ts.date():
            self.reset_for_new_day(ts)

    def is_calendar_blocked(self, ts: datetime) -> Optional[str]:
        d = ts.date()
        if is_settlement_day(d):
            return "股期結算日不出勤"
        if d in self.blackout_dates:
            return "黑天鵝警報/除權息日不出勤"
        return None

    def is_within_session(self, ts: datetime) -> bool:
        hhmm = ts.strftime("%H:%M")
        return self.session_start <= hhmm <= self.session_end

    def can_enter(self, ts: datetime) -> tuple[bool, str]:
        self._ensure_day(ts)

        calendar_block = self.is_calendar_blocked(ts)
        if calendar_block:
            return False, calendar_block

        if not self.is_within_session(ts):
            return False, "非交易時段"

        if self.state.day_halted:
            return False, self.state.day_halt_reason

        if self.state.pause_until is not None and ts < self.state.pause_until:
            return False, f"連續虧損冷卻中，至 {self.state.pause_until.strftime('%H:%M:%S')}"

        if self.state.open_lots >= self.max_inventory_lots:
            return False, f"庫存已達上限 {self.max_inventory_lots} 口"

        return True, "允許進場"

    def record_entry(self, ts: datetime, qty: int = 1) -> None:
        self._ensure_day(ts)
        self.state.open_lots += qty

    def record_exit_pnl(self, ts: datetime, net_pnl: float, qty: int = 1) -> None:
        self._ensure_day(ts)
        self.state.open_lots = max(0, self.state.open_lots - qty)
        self.state.cumulative_pnl += net_pnl

        if net_pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

        if self.state.cumulative_pnl <= -self.daily_loss_limit:
            self.state.day_halted = True
            self.state.day_halt_reason = f"日虧損達熔斷線 {self.daily_loss_limit:.0f} 元，今日停機"

        if self.state.consecutive_losses >= self.consecutive_loss_pause:
            self.state.pause_until = ts + timedelta(minutes=self.consecutive_loss_pause_minutes)
