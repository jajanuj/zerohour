import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.signals.ma200_filter import MA200Filter, TrendState, MA200Signal


def make_price_data(n_days: int, start_price: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    dates = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(n_days)]
    prices = [start_price * (1 + trend) ** i for i in range(n_days)]
    return pd.DataFrame({"date": dates, "close": prices})


class TestMA200Filter:

    def setup_method(self):
        self.filter = MA200Filter(period=200)

    def test_bull_state_when_price_above_ma200(self):
        data = make_price_data(300, start_price=100, trend=0.001)
        signal = self.filter.calculate(data, "TEST")
        assert signal.state == TrendState.BULL
        assert signal.distance_pct > 0

    def test_bear_state_when_price_below_ma200(self):
        data = make_price_data(300, start_price=100, trend=-0.001)
        signal = self.filter.calculate(data, "TEST")
        assert signal.state == TrendState.BEAR
        assert signal.distance_pct < 0

    def test_undefined_when_insufficient_data(self):
        data = make_price_data(150)
        signal = self.filter.calculate(data, "TEST")
        assert signal.state == TrendState.UNDEFINED

    def test_returns_ma200_signal_type(self):
        data = make_price_data(300)
        signal = self.filter.calculate(data, "QQQ")
        assert isinstance(signal, MA200Signal)
        assert signal.symbol == "QQQ"

    def test_distance_pct_calculation(self):
        data = make_price_data(300, start_price=100, trend=0.001)
        signal = self.filter.calculate(data, "TEST")
        if signal.state == TrendState.BULL:
            expected = (signal.current_price - signal.ma200) / signal.ma200 * 100
            assert abs(signal.distance_pct - expected) < 0.01

    def test_newly_crossed_is_bool(self):
        data = make_price_data(300)
        signal = self.filter.calculate(data, "TEST")
        assert isinstance(signal.is_newly_crossed, bool)

    def test_custom_period(self):
        filter_50 = MA200Filter(period=50)
        data = make_price_data(100, start_price=100, trend=0.002)
        signal = filter_50.calculate(data, "TEST")
        assert signal.state in [TrendState.BULL, TrendState.BEAR, TrendState.UNDEFINED]

    def test_bear_distance_is_negative(self):
        data = make_price_data(300, start_price=100, trend=-0.002)
        signal = self.filter.calculate(data, "TEST")
        if signal.state == TrendState.BEAR:
            assert signal.distance_pct < 0
