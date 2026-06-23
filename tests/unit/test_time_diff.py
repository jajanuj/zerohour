import pytest
from datetime import datetime

from src.signals.time_diff import TimeDiffSignalGenerator, TimeDiffSignal, SignalDirection


class TestTimeDiffSignalGenerator:

    def setup_method(self):
        self.gen = TimeDiffSignalGenerator(
            nasdaq_threshold=1.5,
            require_sox_confirmation=True,
            min_confidence=0.6,
        )

    def test_neutral_when_nasdaq_below_threshold(self):
        signal = self.gen.generate(
            nasdaq_change_pct=1.0,
            sp500_change_pct=0.8,
            sox_change_pct=1.2,
        )
        assert signal.direction == SignalDirection.NEUTRAL

    def test_long_signal_when_all_positive(self):
        signal = self.gen.generate(
            nasdaq_change_pct=2.5,
            sp500_change_pct=1.8,
            sox_change_pct=3.0,
        )
        assert signal.direction == SignalDirection.LONG
        assert signal.confidence > 0.6

    def test_short_signal_when_all_negative(self):
        signal = self.gen.generate(
            nasdaq_change_pct=-2.5,
            sp500_change_pct=-1.8,
            sox_change_pct=-3.0,
        )
        assert signal.direction == SignalDirection.SHORT

    def test_neutral_when_sp500_diverges(self):
        signal = self.gen.generate(
            nasdaq_change_pct=2.0,
            sp500_change_pct=-0.5,
            sox_change_pct=2.5,
        )
        assert signal.direction == SignalDirection.NEUTRAL

    def test_neutral_when_sox_diverges(self):
        signal = self.gen.generate(
            nasdaq_change_pct=2.0,
            sp500_change_pct=1.5,
            sox_change_pct=-1.0,
        )
        assert signal.direction == SignalDirection.NEUTRAL

    def test_returns_timediff_signal_type(self):
        signal = self.gen.generate(
            nasdaq_change_pct=2.0,
            sp500_change_pct=1.5,
            sox_change_pct=2.5,
        )
        assert isinstance(signal, TimeDiffSignal)

    def test_confidence_increases_with_stronger_nasdaq(self):
        signal_weak = self.gen.generate(1.6, 1.2, 2.0)
        signal_strong = self.gen.generate(3.0, 2.5, 4.0)
        if signal_strong.direction != SignalDirection.NEUTRAL:
            assert signal_strong.confidence >= signal_weak.confidence

    def test_sox_confirmation_disabled(self):
        gen_no_sox = TimeDiffSignalGenerator(
            nasdaq_threshold=1.5,
            require_sox_confirmation=False,
            min_confidence=0.5,
        )
        signal = gen_no_sox.generate(
            nasdaq_change_pct=2.0,
            sp500_change_pct=1.5,
            sox_change_pct=-1.0,
        )
        assert signal.direction == SignalDirection.LONG

    def test_suggested_symbol_for_long(self):
        signal = self.gen.generate(2.5, 2.0, 3.0)
        if signal.direction == SignalDirection.LONG:
            assert signal.suggested_symbol == "0050"
            assert signal.suggested_action == "BUY"

    def test_neutral_confidence_is_zero(self):
        signal = self.gen.generate(0.5, 0.3, 0.8)
        assert signal.direction == SignalDirection.NEUTRAL
        assert signal.confidence == 0.0
