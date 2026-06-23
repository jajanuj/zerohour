import pytest
from datetime import datetime, timedelta

from src.risk.stop_loss import StopLossManager, StopLossConfig, Position


class TestStopLossManager:

    def setup_method(self):
        config = StopLossConfig(
            stop_loss_pct=0.12,
            trailing_stop_pct=0.15,
            time_stop_days=5,
        )
        self.mgr = StopLossManager(config)
        self.entry_date = datetime(2024, 1, 1)

    def test_initialize_position(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        assert pos.symbol == "0050"
        assert pos.entry_price == 100.0
        assert pos.stop_loss_price == pytest.approx(88.0, 0.01)
        assert pos.peak_price == 100.0

    def test_fixed_stop_triggered(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        should_exit, reason = self.mgr.should_exit(pos, 87.0, self.entry_date)
        assert should_exit is True
        assert "固定停損" in reason

    def test_no_exit_above_stop(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        should_exit, reason = self.mgr.should_exit(pos, 95.0, self.entry_date)
        assert should_exit is False
        assert reason == ""

    def test_trailing_stop_updates_on_new_high(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        pos = self.mgr.update_trailing_stop(pos, 120.0)
        assert pos.peak_price == 120.0
        expected_trailing = 120.0 * (1 - 0.15)
        assert pos.trailing_stop_price == pytest.approx(expected_trailing, 0.01)

    def test_trailing_stop_triggered(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        pos = self.mgr.update_trailing_stop(pos, 130.0)
        should_exit, reason = self.mgr.should_exit(pos, 110.0, self.entry_date)
        assert should_exit is True
        assert "移動停利" in reason

    def test_trailing_stop_only_goes_up(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        pos = self.mgr.update_trailing_stop(pos, 120.0)
        old_trailing = pos.trailing_stop_price
        pos = self.mgr.update_trailing_stop(pos, 115.0)  # 沒創新高
        assert pos.trailing_stop_price == old_trailing

    def test_time_stop_triggered(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        future_date = self.entry_date + timedelta(days=6)
        should_exit, reason = self.mgr.should_exit(pos, 99.0, future_date)
        assert should_exit is True
        assert "時間停損" in reason

    def test_time_stop_not_triggered_if_profitable(self):
        pos = self.mgr.initialize_position("0050", 100.0, self.entry_date, 1000)
        future_date = self.entry_date + timedelta(days=6)
        should_exit, _ = self.mgr.should_exit(pos, 105.0, future_date)
        assert should_exit is False
