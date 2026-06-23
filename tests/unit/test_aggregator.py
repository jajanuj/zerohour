import pytest
from datetime import datetime
import pandas as pd

from src.signals.ma200_filter import MA200Signal, TrendState
from src.signals.time_diff import TimeDiffSignal, SignalDirection
from src.signals.aggregator import SignalAggregator, CombinedSignal, FinalAction


def make_trend_signal(state: TrendState, distance_pct: float = 5.0) -> MA200Signal:
    return MA200Signal(
        symbol="QQQ",
        date=pd.Timestamp("2024-01-01"),
        state=state,
        current_price=450.0,
        ma200=430.0,
        distance_pct=distance_pct,
        is_newly_crossed=False,
    )


def make_time_diff_signal(direction: SignalDirection, confidence: float = 0.8) -> TimeDiffSignal:
    return TimeDiffSignal(
        generated_at=datetime.now(),
        direction=direction,
        confidence=confidence,
        nasdaq_change_pct=2.5,
        sp500_change_pct=1.8,
        sox_change_pct=3.0,
        trigger_reason="test signal",
        suggested_symbol="0050",
        suggested_action="BUY" if direction == SignalDirection.LONG else "SELL",
    )


class TestSignalAggregator:

    def setup_method(self):
        self.agg = SignalAggregator()

    def test_bear_trend_always_exits(self):
        trend = make_trend_signal(TrendState.BEAR, distance_pct=-5.0)
        time_diff = make_time_diff_signal(SignalDirection.LONG)
        result = self.agg.aggregate(trend, time_diff)
        assert result.final_action == FinalAction.EXIT_ALL

    def test_undefined_trend_holds(self):
        trend = make_trend_signal(TrendState.UNDEFINED)
        time_diff = make_time_diff_signal(SignalDirection.LONG)
        result = self.agg.aggregate(trend, time_diff)
        assert result.final_action == FinalAction.HOLD

    def test_bull_plus_long_buys(self):
        trend = make_trend_signal(TrendState.BULL)
        time_diff = make_time_diff_signal(SignalDirection.LONG)
        result = self.agg.aggregate(trend, time_diff)
        assert result.final_action == FinalAction.BUY

    def test_bull_plus_short_holds(self):
        trend = make_trend_signal(TrendState.BULL)
        time_diff = make_time_diff_signal(SignalDirection.SHORT)
        result = self.agg.aggregate(trend, time_diff)
        assert result.final_action == FinalAction.HOLD

    def test_bull_plus_neutral_holds(self):
        trend = make_trend_signal(TrendState.BULL)
        time_diff = make_time_diff_signal(SignalDirection.NEUTRAL, confidence=0.0)
        result = self.agg.aggregate(trend, time_diff)
        assert result.final_action == FinalAction.HOLD

    def test_buy_position_within_max(self):
        trend = make_trend_signal(TrendState.BULL)
        time_diff = make_time_diff_signal(SignalDirection.LONG, confidence=1.0)
        result = self.agg.aggregate(trend, time_diff)
        assert result.suggested_position_pct <= self.agg.max_position_pct

    def test_returns_combined_signal(self):
        trend = make_trend_signal(TrendState.BULL)
        time_diff = make_time_diff_signal(SignalDirection.LONG)
        result = self.agg.aggregate(trend, time_diff)
        assert isinstance(result, CombinedSignal)

    def test_bear_exit_zeroes_position(self):
        trend = make_trend_signal(TrendState.BEAR)
        time_diff = make_time_diff_signal(SignalDirection.NEUTRAL)
        result = self.agg.aggregate(trend, time_diff)
        assert result.suggested_position_pct == 0.0
        assert result.stop_loss_pct == 0.0
