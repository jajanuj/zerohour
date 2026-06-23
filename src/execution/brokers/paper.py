import uuid
from datetime import datetime
from typing import Optional
import logging

from .base import BaseBroker, Order, OrderType, OrderStatus

logger = logging.getLogger(__name__)


class PaperBroker(BaseBroker):
    """
    模擬帳戶（Paper Trading）。

    不連接真實券商，模擬市價單即時成交。
    """

    def __init__(self, initial_capital: float = 1_000_000):
        self.capital = initial_capital
        self.positions: dict[str, dict] = {}
        self.orders: dict[str, Order] = {}
        self.trade_history: list[dict] = []

    def submit_order(self, order: Order) -> Order:
        order.order_id = str(uuid.uuid4())
        order.status = OrderStatus.SUBMITTED
        order.broker = "paper"

        if order.order_type == OrderType.MARKET:
            fill_price = order.limit_price or 0.0
            order.status = OrderStatus.FILLED
            order.filled_price = fill_price
            order.filled_at = datetime.now()
            self._update_position(order)

        self.orders[order.order_id] = order
        logger.info(
            f"[PAPER] {order.order_id[:8]}: "
            f"{order.direction} {order.quantity} {order.symbol} "
            f"@ {order.filled_price} → {order.status.value}"
        )
        return order

    def _update_position(self, order: Order) -> None:
        if order.filled_price is None:
            return

        if order.direction == "BUY":
            cost = order.quantity * order.filled_price
            self.capital -= cost
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                total_qty = pos["quantity"] + order.quantity
                pos["avg_price"] = (
                    pos["avg_price"] * pos["quantity"] + cost
                ) / total_qty
                pos["quantity"] = total_qty
            else:
                self.positions[order.symbol] = {
                    "quantity": order.quantity,
                    "avg_price": order.filled_price,
                }
            self.trade_history.append({
                "action": "BUY",
                "symbol": order.symbol,
                "quantity": order.quantity,
                "price": order.filled_price,
                "at": order.filled_at,
            })

        elif order.direction == "SELL":
            if order.symbol in self.positions:
                proceeds = order.quantity * order.filled_price
                self.capital += proceeds
                pos = self.positions[order.symbol]
                pnl = (order.filled_price - pos["avg_price"]) * order.quantity
                pos["quantity"] -= order.quantity
                if pos["quantity"] <= 0:
                    del self.positions[order.symbol]
                self.trade_history.append({
                    "action": "SELL",
                    "symbol": order.symbol,
                    "quantity": order.quantity,
                    "price": order.filled_price,
                    "pnl": pnl,
                    "at": order.filled_at,
                })

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    def get_order_status(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_positions(self) -> list[dict]:
        return [{"symbol": k, **v} for k, v in self.positions.items()]

    def get_account_balance(self) -> dict:
        positions_value = sum(
            p["quantity"] * p["avg_price"] for p in self.positions.values()
        )
        return {
            "cash": round(self.capital, 2),
            "positions_value": round(positions_value, 2),
            "total": round(self.capital + positions_value, 2),
        }
