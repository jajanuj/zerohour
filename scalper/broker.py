"""
統一下單介面：SimBrokerAdapter（Phase 0-3 使用，純記憶體模擬撮合）與
ShioajiBrokerAdapter（Phase 4 真金專用）。與 src/execution/brokers/ 完全獨立，
不共用介面——scalper/ 禁止 import src.（見 scalper-spec.md §2 硬性邊界）。

§13 禁止事項 5：真金下單代碼路徑在 Phase 0-3 必須硬編碼 raise，直到 A7 核准。
ShioajiBrokerAdapter 的每個下單方法目前一律 raise NotImplementedError。
"""

import itertools
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass
class BrokerOrder:
    order_id: str
    symbol: str
    direction: str  # BUY / SELL
    price: float
    qty: int
    status: OrderStatus = OrderStatus.PENDING
    filled_price: Optional[float] = None
    filled_ts: Optional[datetime] = None


class BrokerAdapter(ABC):
    @abstractmethod
    def place_limit(self, symbol: str, direction: str, price: float, qty: int) -> BrokerOrder: ...

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def cancel_all(self, symbol: Optional[str] = None) -> int: ...

    @abstractmethod
    def market_exit(self, symbol: str, direction: str, qty: int, ref_price: float) -> BrokerOrder: ...

    @abstractmethod
    def list_open_orders(self, symbol: Optional[str] = None) -> list[BrokerOrder]: ...

    @abstractmethod
    def list_positions(self) -> dict[str, int]: ...


class SimBrokerAdapter(BrokerAdapter):
    """
    Phase 0-3 純記憶體模擬撮合：市價單立即用 ref_price 成交；限價單維持 PENDING，
    由 replay.py 的悲觀成交模型或人工呼叫 fill() 觸發成交。
    """

    def __init__(self):
        self._orders: dict[str, BrokerOrder] = {}
        self._id_counter = itertools.count(1)
        self._positions: dict[str, int] = {}

    def place_limit(self, symbol: str, direction: str, price: float, qty: int) -> BrokerOrder:
        order_id = f"sim-{next(self._id_counter)}"
        order = BrokerOrder(order_id=order_id, symbol=symbol, direction=direction, price=price, qty=qty)
        self._orders[order_id] = order
        return order

    def cancel(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.status != OrderStatus.PENDING:
            return False
        order.status = OrderStatus.CANCELLED
        return True

    def cancel_all(self, symbol: Optional[str] = None) -> int:
        n = 0
        for order in self._orders.values():
            if order.status == OrderStatus.PENDING and (symbol is None or order.symbol == symbol):
                order.status = OrderStatus.CANCELLED
                n += 1
        return n

    def market_exit(self, symbol: str, direction: str, qty: int, ref_price: float) -> BrokerOrder:
        order_id = f"sim-{next(self._id_counter)}"
        order = BrokerOrder(
            order_id=order_id, symbol=symbol, direction=direction, price=ref_price, qty=qty,
            status=OrderStatus.FILLED, filled_price=ref_price, filled_ts=datetime.now(),
        )
        self._orders[order_id] = order
        self._apply_position(symbol, direction, qty)
        return order

    def fill(self, order_id: str, filled_price: float, filled_ts: datetime) -> Optional[BrokerOrder]:
        order = self._orders.get(order_id)
        if order is None or order.status != OrderStatus.PENDING:
            return None
        order.status = OrderStatus.FILLED
        order.filled_price = filled_price
        order.filled_ts = filled_ts
        self._apply_position(order.symbol, order.direction, order.qty)
        return order

    def _apply_position(self, symbol: str, direction: str, qty: int) -> None:
        delta = qty if direction == "BUY" else -qty
        self._positions[symbol] = self._positions.get(symbol, 0) + delta

    def list_open_orders(self, symbol: Optional[str] = None) -> list[BrokerOrder]:
        return [
            o for o in self._orders.values()
            if o.status == OrderStatus.PENDING and (symbol is None or o.symbol == symbol)
        ]

    def list_positions(self) -> dict[str, int]:
        return dict(self._positions)


class ShioajiBrokerAdapter(BrokerAdapter):
    """Phase 4 真金下單專用。Phase 0-3 全程不得啟用——見 scalper-spec.md A7、§13。"""

    _BLOCKED_MSG = (
        "真金下單需 scalper-spec.md A7 核准後才實作，目前硬性拒絕。"
        "Phase 0-3 請使用 SimBrokerAdapter。"
    )

    def __init__(self, api_key: str, secret_key: str, simulation: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.simulation = simulation
        self._api = None

    def place_limit(self, symbol: str, direction: str, price: float, qty: int) -> BrokerOrder:
        raise NotImplementedError(self._BLOCKED_MSG)

    def cancel(self, order_id: str) -> bool:
        raise NotImplementedError(self._BLOCKED_MSG)

    def cancel_all(self, symbol: Optional[str] = None) -> int:
        raise NotImplementedError(self._BLOCKED_MSG)

    def market_exit(self, symbol: str, direction: str, qty: int, ref_price: float) -> BrokerOrder:
        raise NotImplementedError(self._BLOCKED_MSG)

    def list_open_orders(self, symbol: Optional[str] = None) -> list[BrokerOrder]:
        raise NotImplementedError(self._BLOCKED_MSG)

    def list_positions(self) -> dict[str, int]:
        raise NotImplementedError(self._BLOCKED_MSG)
