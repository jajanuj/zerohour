from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class StopLossConfig:
    stop_loss_pct: float = 0.12
    trailing_stop_pct: float = 0.15
    time_stop_days: int = 5


@dataclass
class Position:
    symbol: str
    entry_price: float
    entry_date: datetime
    quantity: float
    peak_price: float
    stop_loss_price: float
    trailing_stop_price: float


class StopLossManager:
    """
    停損管理器。

    三種出場觸發：
    1. 固定停損：現價 ≤ 進場價 × (1 - stop_loss_pct)
    2. 移動停利：現價 ≤ 高點 × (1 - trailing_stop_pct)
    3. 時間停損：持倉 N 天仍虧損
    """

    def __init__(self, config: StopLossConfig):
        self.config = config

    def initialize_position(
        self,
        symbol: str,
        entry_price: float,
        entry_date: datetime,
        quantity: float,
    ) -> Position:
        stop_price = entry_price * (1 - self.config.stop_loss_pct)
        return Position(
            symbol=symbol,
            entry_price=entry_price,
            entry_date=entry_date,
            quantity=quantity,
            peak_price=entry_price,
            stop_loss_price=round(stop_price, 2),
            trailing_stop_price=round(stop_price, 2),
        )

    def update_trailing_stop(self, position: Position, current_price: float) -> Position:
        if current_price > position.peak_price:
            position.peak_price = current_price
            new_trailing = current_price * (1 - self.config.trailing_stop_pct)
            position.trailing_stop_price = max(
                position.trailing_stop_price,
                round(new_trailing, 2),
            )
            logger.debug(
                f"{position.symbol}: 新高 {current_price:.2f}，移動停利 → {position.trailing_stop_price:.2f}"
            )
        return position

    def should_exit(
        self,
        position: Position,
        current_price: float,
        current_date: datetime,
    ) -> tuple[bool, str]:
        if current_price <= position.stop_loss_price:
            loss_pct = (current_price - position.entry_price) / position.entry_price * 100
            return True, f"觸發固定停損 {loss_pct:.1f}%（停損線 {position.stop_loss_price:.2f}）"

        if current_price <= position.trailing_stop_price:
            gain_pct = (position.peak_price - position.entry_price) / position.entry_price * 100
            return True, (
                f"觸發移動停利（高點 {position.peak_price:.2f}，"
                f"曾獲利 {gain_pct:.1f}%，停利線 {position.trailing_stop_price:.2f}）"
            )

        days_held = (current_date - position.entry_date).days
        if days_held >= self.config.time_stop_days:
            pnl_pct = (current_price - position.entry_price) / position.entry_price * 100
            if pnl_pct <= 0:
                return True, f"時間停損：持倉 {days_held} 天仍虧損 {pnl_pct:.1f}%"

        return False, ""
