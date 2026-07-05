from datetime import datetime

import pytest

from scalper.broker import OrderStatus, ShioajiBrokerAdapter, SimBrokerAdapter


class TestSimBrokerAdapter:
    def test_place_limit_is_pending(self):
        broker = SimBrokerAdapter()
        order = broker.place_limit("MXFR1", "BUY", 100.0, 1)
        assert order.status == OrderStatus.PENDING
        assert broker.list_open_orders() == [order]

    def test_fill_updates_position(self):
        broker = SimBrokerAdapter()
        order = broker.place_limit("MXFR1", "BUY", 100.0, 1)
        broker.fill(order.order_id, 100.0, datetime.now())
        assert broker.list_positions()["MXFR1"] == 1
        assert broker.list_open_orders() == []

    def test_cancel_pending_order(self):
        broker = SimBrokerAdapter()
        order = broker.place_limit("MXFR1", "SELL", 100.0, 1)
        assert broker.cancel(order.order_id) is True
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_already_filled_order_fails(self):
        broker = SimBrokerAdapter()
        order = broker.place_limit("MXFR1", "BUY", 100.0, 1)
        broker.fill(order.order_id, 100.0, datetime.now())
        assert broker.cancel(order.order_id) is False

    def test_cancel_all_by_symbol(self):
        broker = SimBrokerAdapter()
        broker.place_limit("MXFR1", "BUY", 100.0, 1)
        broker.place_limit("MXFR2", "BUY", 200.0, 1)
        n = broker.cancel_all(symbol="MXFR1")
        assert n == 1
        assert len(broker.list_open_orders()) == 1

    def test_market_exit_fills_immediately_and_updates_position(self):
        broker = SimBrokerAdapter()
        order = broker.market_exit("MXFR1", "SELL", 1, ref_price=105.0)
        assert order.status == OrderStatus.FILLED
        assert broker.list_positions()["MXFR1"] == -1


class TestShioajiBrokerAdapterBlocked:
    """Phase 0-3 全程禁止真金下單（A7 未核准），每個下單方法都必須 raise。"""

    def test_all_trading_methods_raise(self):
        adapter = ShioajiBrokerAdapter(api_key="x", secret_key="y", simulation=True)
        with pytest.raises(NotImplementedError):
            adapter.place_limit("MXFR1", "BUY", 100.0, 1)
        with pytest.raises(NotImplementedError):
            adapter.cancel("any")
        with pytest.raises(NotImplementedError):
            adapter.cancel_all()
        with pytest.raises(NotImplementedError):
            adapter.market_exit("MXFR1", "SELL", 1, 100.0)
        with pytest.raises(NotImplementedError):
            adapter.list_open_orders()
        with pytest.raises(NotImplementedError):
            adapter.list_positions()
