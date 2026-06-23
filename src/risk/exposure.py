import logging

logger = logging.getLogger(__name__)


class ExposureCheck:
    """曝險總量控制。"""

    def __init__(
        self,
        max_single_pct: float = 0.30,
        max_total_pct: float = 0.80,
    ):
        self.max_single_pct = max_single_pct
        self.max_total_pct = max_total_pct

    def check(
        self,
        account_equity: float,
        current_positions: list[dict],
        new_symbol: str,
        new_amount: float,
    ) -> tuple[bool, str]:
        """
        Returns:
            (allowed: bool, reason: str)
        """
        total_invested = sum(p.get("market_value", 0) for p in current_positions)
        symbol_invested = sum(
            p.get("market_value", 0)
            for p in current_positions
            if p.get("symbol") == new_symbol
        )

        new_total = total_invested + new_amount
        new_symbol_total = symbol_invested + new_amount

        if new_symbol_total / account_equity > self.max_single_pct:
            return (
                False,
                f"{new_symbol} 單一標的曝險 {new_symbol_total / account_equity:.1%} 超過 {self.max_single_pct:.0%}",
            )

        if new_total / account_equity > self.max_total_pct:
            return (
                False,
                f"總曝險 {new_total / account_equity:.1%} 超過 {self.max_total_pct:.0%}",
            )

        return True, "通過曝險檢查"


class DailyCircuitBreaker:
    """每日虧損熔斷機制。"""

    def __init__(self, max_daily_loss_pct: float = 0.05):
        self.max_daily_loss_pct = max_daily_loss_pct
        self._triggered = False

    def check(self, daily_pnl_pct: float) -> bool:
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            self._triggered = True
            logger.critical(
                f"每日熔斷觸發：單日虧損 {daily_pnl_pct:.1%}，停止今日所有交易"
            )
        return self._triggered

    def reset(self) -> None:
        self._triggered = False

    @property
    def is_triggered(self) -> bool:
        return self._triggered
