import pytest

from src.execution.brokers.paper import PaperBroker
from src.execution.brokers.base import Order, OrderType, OrderStatus


def make_market_order(symbol: str, qty: float, price: float, direction: str) -> Order:
    return Order(
        order_id="",
        symbol=symbol,
        quantity=qty,
        order_type=OrderType.MARKET,
        direction=direction,
        limit_price=price,
    )


class TestPaperBroker:

    def setup_method(self):
        self.broker = PaperBroker(initial_capital=1_000_000)

    def test_buy_reduces_capital(self):
        order = make_market_order("0050", 100, 150.0, "BUY")
        self.broker.submit_order(order)
        balance = self.broker.get_account_balance()
        assert balance["cash"] == pytest.approx(1_000_000 - 100 * 150.0, rel=0.01)

    def test_buy_creates_position(self):
        order = make_market_order("0050", 100, 150.0, "BUY")
        self.broker.submit_order(order)
        positions = self.broker.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "0050"
        assert positions[0]["quantity"] == 100

    def test_sell_removes_position(self):
        buy = make_market_order("0050", 100, 150.0, "BUY")
        self.broker.submit_order(buy)
        sell = make_market_order("0050", 100, 155.0, "SELL")
        self.broker.submit_order(sell)
        positions = self.broker.get_positions()
        assert len(positions) == 0

    def test_sell_increases_capital(self):
        buy = make_market_order("0050", 100, 150.0, "BUY")
        self.broker.submit_order(buy)
        sell = make_market_order("0050", 100, 160.0, "SELL")
        self.broker.submit_order(sell)
        balance = self.broker.get_account_balance()
        assert balance["cash"] > 1_000_000

    def test_filled_order_has_price(self):
        order = make_market_order("0050", 100, 150.0, "BUY")
        filled = self.broker.submit_order(order)
        assert filled.status == OrderStatus.FILLED
        assert filled.filled_price == 150.0

    def test_cancel_order(self):
        order = make_market_order("0050", 100, 150.0, "BUY")
        order.order_type = OrderType.LIMIT
        filled = self.broker.submit_order(order)
        result = self.broker.cancel_order(filled.order_id)
        assert result is True

    def test_account_balance_total(self):
        order = make_market_order("0050", 100, 150.0, "BUY")
        self.broker.submit_order(order)
        balance = self.broker.get_account_balance()
        assert balance["total"] == pytest.approx(
            balance["cash"] + balance["positions_value"], rel=0.001
        )
