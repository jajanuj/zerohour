import uuid
from datetime import datetime
from typing import Optional
import logging

from .brokers.base import BaseBroker, Order, OrderType, OrderStatus
from ..risk.stop_loss import StopLossManager, StopLossConfig, Position
from ..risk.exposure import ExposureCheck, DailyCircuitBreaker

logger = logging.getLogger(__name__)


class OrderManager:
    """
    訂單管理器。

    協調訊號 → 風控 → 下單 → 停損監控的完整流程。
    """

    def __init__(
        self,
        broker: BaseBroker,
        stop_loss_config: Optional[StopLossConfig] = None,
        max_single_pct: float = 0.30,
        max_total_pct: float = 0.80,
    ):
        self.broker = broker
        self.stop_mgr = StopLossManager(stop_loss_config or StopLossConfig())
        self.exposure = ExposureCheck(max_single_pct, max_total_pct)
        self.circuit_breaker = DailyCircuitBreaker()
        self._open_positions: dict[str, Position] = {}

    def execute_buy(
        self,
        symbol: str,
        quantity: float,
        price: float,
        strategy: str = "S3",
    ) -> Optional[Order]:
        if self.circuit_breaker.is_triggered:
            logger.warning("熔斷已觸發，拒絕下單")
            return None

        balance = self.broker.get_account_balance()
        positions = self.broker.get_positions()

        invest_amount = quantity * price
        allowed, reason = self.exposure.check(
            balance["total"], positions, symbol, invest_amount
        )
        if not allowed:
            logger.warning(f"曝險檢查不通過：{reason}")
            return None

        order = Order(
            order_id="",
            symbol=symbol,
            quantity=quantity,
            order_type=OrderType.MARKET,
            direction="BUY",
            limit_price=price,
            strategy=strategy,
        )

        filled = self.broker.submit_order(order)
        if filled.status == OrderStatus.FILLED and filled.filled_price:
            pos = self.stop_mgr.initialize_position(
                symbol=symbol,
                entry_price=filled.filled_price,
                entry_date=filled.filled_at or datetime.now(),
                quantity=quantity,
            )
            self._open_positions[symbol] = pos
            logger.info(f"開倉 {symbol}，停損線 {pos.stop_loss_price:.2f}")

        return filled

    def execute_sell(
        self,
        symbol: str,
        quantity: float,
        price: float,
        reason: str = "",
        strategy: str = "S3",
    ) -> Optional[Order]:
        order = Order(
            order_id="",
            symbol=symbol,
            quantity=quantity,
            order_type=OrderType.MARKET,
            direction="SELL",
            limit_price=price,
            strategy=strategy,
        )
        filled = self.broker.submit_order(order)
        if filled.status == OrderStatus.FILLED:
            self._open_positions.pop(symbol, None)
            logger.info(f"平倉 {symbol} | 原因: {reason}")
        return filled

    def check_stop_loss(self, symbol: str, current_price: float) -> Optional[str]:
        pos = self._open_positions.get(symbol)
        if pos is None:
            return None

        pos = self.stop_mgr.update_trailing_stop(pos, current_price)
        self._open_positions[symbol] = pos

        should_exit, reason = self.stop_mgr.should_exit(pos, current_price, datetime.now())
        if should_exit:
            self.execute_sell(symbol, pos.quantity, current_price, reason=reason)
            return reason
        return None

    def reset_daily(self) -> None:
        self.circuit_breaker.reset()
