"""
60 分 K 聚合與參考區間狀態機（scalper-spec.md §1 參考區間定義）。

規則：用「前一根已完成」的 60 分 K 高低點做參考區間；當根 K 進行中不重算。
跨日時捨棄前一交易日的區間——隔夜跳空常態，不把昨天的區間帶進今天，
今天第一根 K 完成前不交易（見 §7 過關條件對應的保守假設）。
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class Bar:
    start: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class ReferenceRange:
    low: float
    high: float
    source_bar_start: datetime

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0

    def is_breakout(self, price: float) -> bool:
        return price > self.high or price < self.low


class BarAggregator:
    """把逐筆成交聚合成 N 分 K，一根跨期才 emit 剛完成的那根。"""

    def __init__(self, bar_minutes: int = 60):
        self.bar_minutes = bar_minutes
        self._current: Optional[Bar] = None

    def _bucket_start(self, ts: datetime) -> datetime:
        minute_bucket = (ts.minute // self.bar_minutes) * self.bar_minutes
        return ts.replace(minute=minute_bucket % 60, second=0, microsecond=0)

    def on_tick(self, ts: datetime, price: float) -> Optional[Bar]:
        bucket = self._bucket_start(ts)
        completed: Optional[Bar] = None

        if self._current is None:
            self._current = Bar(start=bucket, open=price, high=price, low=price, close=price)
        elif bucket != self._current.start:
            completed = self._current
            self._current = Bar(start=bucket, open=price, high=price, low=price, close=price)
        else:
            self._current.high = max(self._current.high, price)
            self._current.low = min(self._current.low, price)
            self._current.close = price

        return completed

    @property
    def current_bar(self) -> Optional[Bar]:
        return self._current


class RangeEngine:
    def __init__(self, bar_minutes: int = 60):
        self.bar_minutes = bar_minutes
        self.aggregator = BarAggregator(bar_minutes)
        self.reference: Optional[ReferenceRange] = None
        self._current_date: Optional[date] = None

    def on_tick(self, ts: datetime, price: float) -> Optional[Bar]:
        if self._current_date is not None and ts.date() != self._current_date:
            self.reference = None
            self.aggregator = BarAggregator(self.bar_minutes)
        self._current_date = ts.date()

        completed = self.aggregator.on_tick(ts, price)
        if completed is not None:
            self.reference = ReferenceRange(low=completed.low, high=completed.high, source_bar_start=completed.start)
        return completed
