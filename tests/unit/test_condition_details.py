"""逐條件明細（conditions）測試 — docs/report-optimization-plan.md Phase B。

只驗證觀測層輸出；同時斷言決策輸出（direction/state/final_action）以確保
加入 conditions 沒有改變任何決策邏輯。
"""
import pandas as pd
from datetime import datetime, timedelta

from src.signals.time_diff import TimeDiffSignalGenerator, SignalDirection, TimeDiffSignal
from src.signals.ma200_filter import MA200Filter, TrendState, MA200Signal
from src.signals.aggregator import SignalAggregator, FinalAction


def _cond(conds, name):
    return next(c for c in conds if c["name"] == name)


def make_flat_data(n_days=250, price=100.0, last_price=None):
    dates = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(n_days)]
    prices = [price] * n_days
    if last_price is not None:
        prices[-1] = last_price
    return pd.DataFrame({"date": dates, "close": prices})


# ── S2：TimeDiffSignalGenerator ──────────────────────────────────────

class TestS2Conditions:

    def setup_method(self):
        self.gen = TimeDiffSignalGenerator(
            nasdaq_threshold=1.5, require_sox_confirmation=True, min_confidence=0.6,
        )

    def test_below_threshold_has_full_condition_list(self):
        sig = self.gen.generate(1.0, 0.8, 1.2)
        assert sig.direction == SignalDirection.NEUTRAL
        assert len(sig.conditions) == 4
        assert _cond(sig.conditions, "nasdaq_threshold")["passed"] is False
        assert _cond(sig.conditions, "sp500_aligned")["passed"] is True
        assert _cond(sig.conditions, "sox_aligned")["passed"] is True

    def test_sp500_misaligned(self):
        sig = self.gen.generate(2.0, -0.5, 2.5)
        assert sig.direction == SignalDirection.NEUTRAL
        assert "S&P 500" in sig.trigger_reason
        assert _cond(sig.conditions, "nasdaq_threshold")["passed"] is True
        assert _cond(sig.conditions, "sp500_aligned")["passed"] is False

    def test_sox_misaligned(self):
        sig = self.gen.generate(2.0, 1.0, -0.5)
        assert sig.direction == SignalDirection.NEUTRAL
        assert _cond(sig.conditions, "sox_aligned")["passed"] is False

    def test_low_confidence_condition(self):
        gen = TimeDiffSignalGenerator(
            nasdaq_threshold=1.5, require_sox_confirmation=False, min_confidence=0.6,
        )
        sig = gen.generate(1.6, 1.0, -0.5)  # sox 反向但未強制 → 信心 0.51 < 0.6
        assert sig.direction == SignalDirection.NEUTRAL
        assert "信心度" in sig.trigger_reason
        assert _cond(sig.conditions, "min_confidence")["passed"] is False

    def test_all_pass_long(self):
        sig = self.gen.generate(2.5, 1.8, 3.0)
        assert sig.direction == SignalDirection.LONG
        assert len(sig.conditions) == 4
        assert all(c["passed"] is True for c in sig.conditions)
        # condition 中的信心度顯示值必須與實際 confidence 一致（同一純函數）
        assert _cond(sig.conditions, "min_confidence")["actual"] == f"{sig.confidence:.2f}"

    def test_condition_dict_keys(self):
        sig = self.gen.generate(2.5, 1.8, 3.0)
        for c in sig.conditions:
            assert set(c.keys()) == {"name", "label", "passed", "actual", "threshold"}


# ── S1：MA200Filter ─────────────────────────────────────────────────

class TestS1Conditions:

    def test_insufficient_data_single_condition(self):
        f = MA200Filter(period=200)
        sig = f.calculate(make_flat_data(150), "TEST")
        assert sig.state == TrendState.UNDEFINED
        assert len(sig.conditions) == 1
        c = sig.conditions[0]
        assert c["name"] == "data_sufficient" and c["passed"] is False

    def test_normal_path_two_conditions(self):
        f = MA200Filter(period=200)
        sig = f.calculate(make_flat_data(300, last_price=110.0), "TEST")
        assert sig.state == TrendState.BULL
        names = [c["name"] for c in sig.conditions]
        assert names == ["data_sufficient", "price_vs_ma200"]
        assert _cond(sig.conditions, "price_vs_ma200")["passed"] is True

    def test_buffer_band_inside_keeps_prev_state(self):
        # 價格略低於 MA200 但在 2% 緩衝帶內 → 維持 BULL；band passed=True
        f = MA200Filter(period=200, exit_buffer_pct=0.02, enter_buffer_pct=0.02)
        sig = f.calculate(
            make_flat_data(250, last_price=99.0), "TEST", prev_state=TrendState.BULL,
        )
        assert sig.state == TrendState.BULL
        band = _cond(sig.conditions, "buffer_band")
        assert band["passed"] is True
        assert _cond(sig.conditions, "price_vs_ma200")["passed"] is False  # 原始比較確實在線下

    def test_buffer_band_broken_flips_state(self):
        f = MA200Filter(period=200, exit_buffer_pct=0.02, enter_buffer_pct=0.02)
        sig = f.calculate(
            make_flat_data(250, last_price=95.0), "TEST", prev_state=TrendState.BULL,
        )
        assert sig.state == TrendState.BEAR
        assert _cond(sig.conditions, "buffer_band")["passed"] is False

    def test_no_buffer_condition_without_prev_state(self):
        f = MA200Filter(period=200, exit_buffer_pct=0.02, enter_buffer_pct=0.02)
        sig = f.calculate(make_flat_data(250, last_price=99.0), "TEST")
        assert all(c["name"] != "buffer_band" for c in sig.conditions)


# ── S3：SignalAggregator ────────────────────────────────────────────

def _trend(state, distance=5.0):
    return MA200Signal(
        symbol="QQQ", date=pd.Timestamp("2026-01-01"), state=state,
        current_price=500.0, ma200=480.0, distance_pct=distance, is_newly_crossed=False,
    )


def _td(direction, confidence=0.8):
    return TimeDiffSignal(
        generated_at=datetime(2026, 1, 1), direction=direction, confidence=confidence,
        nasdaq_change_pct=2.0, sp500_change_pct=1.5, sox_change_pct=2.5,
        trigger_reason="test", suggested_symbol="0050", suggested_action="BUY",
    )


class TestS3Conditions:

    def setup_method(self):
        self.agg = SignalAggregator()

    def test_bear_exit_all(self):
        sig = self.agg.aggregate(_trend(TrendState.BEAR, -3.0), _td(SignalDirection.LONG))
        assert sig.final_action == FinalAction.EXIT_ALL
        assert _cond(sig.conditions, "s1_trend")["passed"] is False
        assert _cond(sig.conditions, "s2_direction")["passed"] is True

    def test_undefined_hold(self):
        sig = self.agg.aggregate(_trend(TrendState.UNDEFINED, 0.0), _td(SignalDirection.NEUTRAL))
        assert sig.final_action == FinalAction.HOLD
        assert len(sig.conditions) == 2

    def test_bull_long_buy(self):
        sig = self.agg.aggregate(_trend(TrendState.BULL), _td(SignalDirection.LONG))
        assert sig.final_action == FinalAction.BUY
        assert all(c["passed"] is True for c in sig.conditions)

    def test_bull_neutral_hold(self):
        sig = self.agg.aggregate(_trend(TrendState.BULL), _td(SignalDirection.NEUTRAL, 0.0))
        assert sig.final_action == FinalAction.HOLD
        assert _cond(sig.conditions, "s1_trend")["passed"] is True
        assert _cond(sig.conditions, "s2_direction")["passed"] is False
