import pytest

from src.risk.position_sizer import PositionSizer


class TestPositionSizer:

    def setup_method(self):
        self.sizer = PositionSizer(
            max_position_pct=0.30,
            max_total_exposure_pct=0.80,
        )
        self.equity = 1_000_000

    def test_basic_calculation(self):
        result = self.sizer.calculate(
            account_equity=self.equity,
            current_exposure=0,
            suggested_pct=0.25,
            current_price=100.0,
        )
        assert result["blocked"] is False
        assert result["invest_amount"] == pytest.approx(250_000, rel=0.01)

    def test_blocked_when_exposure_exceeded(self):
        result = self.sizer.calculate(
            account_equity=self.equity,
            current_exposure=850_000,
            suggested_pct=0.25,
            current_price=100.0,
        )
        assert result["blocked"] is True

    def test_capped_at_max_position_pct(self):
        result = self.sizer.calculate(
            account_equity=self.equity,
            current_exposure=0,
            suggested_pct=0.50,
            current_price=100.0,
        )
        assert result["invest_amount"] <= self.equity * 0.30 + 1

    def test_invalid_price_blocked(self):
        result = self.sizer.calculate(
            account_equity=self.equity,
            current_exposure=0,
            suggested_pct=0.25,
            current_price=0.0,
        )
        assert result["blocked"] is True

    def test_shares_calculation(self):
        result = self.sizer.calculate(
            account_equity=self.equity,
            current_exposure=0,
            suggested_pct=0.10,
            current_price=50.0,
        )
        assert result["blocked"] is False
        expected_shares = result["invest_amount"] / 50.0
        assert result["shares"] == pytest.approx(expected_shares, rel=0.01)

    def test_lots_for_tw_stock(self):
        result = self.sizer.calculate(
            account_equity=self.equity,
            current_exposure=0,
            suggested_pct=0.20,
            current_price=150.0,
            lot_size=1000,
        )
        assert result["lots"] >= 1
        assert isinstance(result["lots"], int)
