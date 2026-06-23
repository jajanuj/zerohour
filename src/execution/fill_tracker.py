from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class FillRecord:
    order_id: str
    symbol: str
    direction: str
    fill_price: float
    fill_quantity: float
    commission: float
    filled_at: datetime
    strategy: str = ""
    pnl: Optional[float] = None


class FillTracker:
    """成交追蹤器：記錄所有成交明細，計算損益統計。"""

    def __init__(self):
        self._fills: list[FillRecord] = []

    def record(self, fill: FillRecord) -> None:
        self._fills.append(fill)
        logger.info(
            f"FillTracker: {fill.direction} {fill.fill_quantity} {fill.symbol} "
            f"@ {fill.fill_price:.2f} | commission {fill.commission:.2f}"
        )

    def get_all(self) -> list[FillRecord]:
        return list(self._fills)

    def get_by_symbol(self, symbol: str) -> list[FillRecord]:
        return [f for f in self._fills if f.symbol == symbol]

    def total_commission(self) -> float:
        return sum(f.commission for f in self._fills)

    def realized_pnl(self) -> float:
        return sum(f.pnl for f in self._fills if f.pnl is not None)

    def trade_count(self) -> int:
        return len([f for f in self._fills if f.direction == "SELL"])

    def win_rate(self) -> float:
        sells = [f for f in self._fills if f.direction == "SELL" and f.pnl is not None]
        if not sells:
            return 0.0
        wins = [f for f in sells if f.pnl > 0]
        return len(wins) / len(sells)

    def summary(self) -> dict:
        return {
            "total_trades": self.trade_count(),
            "realized_pnl": round(self.realized_pnl(), 2),
            "total_commission": round(self.total_commission(), 2),
            "win_rate": round(self.win_rate(), 4),
        }
