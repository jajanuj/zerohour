"""S3 next_step 文案測試 — docs/report-optimization-plan.md Phase C。

next_step 為純顯示文案，僅由既有數值導出；同時斷言 final_action
確保新增文案沒有動到決策矩陣。
"""
import pandas as pd
from datetime import datetime

from src.signals.aggregator import SignalAggregator, FinalAction
from src.signals.ma200_filter import TrendState, MA200Signal
from src.signals.time_diff import TimeDiffSignal, SignalDirection


def _trend(state, ma200=480.0, distance=5.0):
    return MA200Signal(
        symbol="QQQ", date=pd.Timestamp("2026-01-01"), state=state,
        current_price=500.0, ma200=ma200, distance_pct=distance, is_newly_crossed=False,
    )


def _td(direction, confidence=0.8, conditions=None):
    return TimeDiffSignal(
        generated_at=datetime(2026, 1, 1), direction=direction, confidence=confidence,
        nasdaq_change_pct=2.0, sp500_change_pct=1.5, sox_change_pct=2.5,
        trigger_reason="test", suggested_symbol="0050", suggested_action="BUY",
        conditions=conditions or [],
    )


class TestNextStep:

    def test_bear_shows_reentry_level(self):
        agg = SignalAggregator(ma200_enter_buffer_pct=0.02)
        sig = agg.aggregate(_trend(TrendState.BEAR, ma200=480.0, distance=-3.0),
                            _td(SignalDirection.NEUTRAL))
        assert sig.final_action == FinalAction.EXIT_ALL
        assert "489.60" in sig.next_step  # 480 × 1.02

    def test_bear_without_ma200_falls_back(self):
        agg = SignalAggregator(ma200_enter_buffer_pct=0.02)
        sig = agg.aggregate(_trend(TrendState.BEAR, ma200=0.0, distance=0.0),
                            _td(SignalDirection.NEUTRAL))
        assert sig.next_step == "等待 S1 趨勢轉多"

    def test_undefined_waits_for_data(self):
        agg = SignalAggregator()
        sig = agg.aggregate(_trend(TrendState.UNDEFINED, ma200=0.0, distance=0.0),
                            _td(SignalDirection.NEUTRAL))
        assert sig.final_action == FinalAction.HOLD
        assert "200 日均線" in sig.next_step

    def test_buy_shows_position_and_stop(self):
        agg = SignalAggregator()  # index_stop_loss_pct 預設 0.12
        sig = agg.aggregate(_trend(TrendState.BULL), _td(SignalDirection.LONG))
        assert sig.final_action == FinalAction.BUY
        assert "停損 12%" in sig.next_step

    def test_hold_uses_first_failed_condition(self):
        agg = SignalAggregator()
        conds = [
            {"name": "nasdaq_threshold", "label": "NASDAQ 波動",
             "passed": False, "actual": "+0.80%", "threshold": "±1.5%"},
            {"name": "sp500_aligned", "label": "S&P500 同向",
             "passed": True, "actual": "+0.50%", "threshold": "與 NASDAQ 同向"},
        ]
        sig = agg.aggregate(_trend(TrendState.BULL),
                            _td(SignalDirection.NEUTRAL, 0.0, conditions=conds))
        assert sig.final_action == FinalAction.HOLD
        assert "NASDAQ 波動" in sig.next_step
        assert "+0.80%" in sig.next_step
        assert "±1.5%" in sig.next_step

    def test_hold_fallback_without_conditions(self):
        agg = SignalAggregator()
        sig = agg.aggregate(_trend(TrendState.BULL), _td(SignalDirection.NEUTRAL, 0.0))
        assert sig.next_step == "等待 S2 訊號轉 LONG"

    def test_display_params_do_not_change_decisions(self):
        # 帶與不帶 buffer 參數，四種決策輸出完全一致
        agg_plain = SignalAggregator()
        agg_buf = SignalAggregator(ma200_enter_buffer_pct=0.02, ma200_exit_buffer_pct=0.02)
        cases = [
            (_trend(TrendState.BEAR, distance=-3.0), _td(SignalDirection.LONG)),
            (_trend(TrendState.UNDEFINED, ma200=0.0), _td(SignalDirection.NEUTRAL)),
            (_trend(TrendState.BULL), _td(SignalDirection.LONG)),
            (_trend(TrendState.BULL), _td(SignalDirection.SHORT, 0.7)),
        ]
        for trend, td in cases:
            a = agg_plain.aggregate(trend, td)
            b = agg_buf.aggregate(trend, td)
            assert a.final_action == b.final_action
            assert a.suggested_position_pct == b.suggested_position_pct
            assert a.stop_loss_pct == b.stop_loss_pct
