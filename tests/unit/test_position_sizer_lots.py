"""PositionSizer 整張（lot_size>1）超買修復測試 — 2026-07-06 老闆核准。

修復前：資金不足一張時 `max(1, ...)` 仍強制買滿 1 張（超買）。
修復後：不足一張 → blocked；足夠時無條件捨去到整張並對齊投入金額。
"""
import pytest

from src.risk.position_sizer import PositionSizer


class TestPositionSizerLots:

    def setup_method(self):
        self.sizer = PositionSizer(max_position_pct=0.30, max_total_exposure_pct=0.80)

    def test_blocked_when_cannot_afford_one_lot(self):
        # 10 萬資金 × 30% = 3 萬可投；一張 = 500 × 1000 = 50 萬 → 必須封鎖，不得強制買 1 張
        result = self.sizer.calculate(
            account_equity=100_000,
            current_exposure=0,
            suggested_pct=0.30,
            current_price=500.0,
            lot_size=1000,
        )
        assert result["blocked"] is True
        assert result["lots"] == 0
        assert result["shares"] == 0.0
        assert "資金不足" in result["reason"]

    def test_floors_to_whole_lots(self):
        # 100 萬 × 20% = 20 萬；一張 = 150 × 1000 = 15 萬 → 1.33 張 → 1 張，不得進位
        result = self.sizer.calculate(
            account_equity=1_000_000,
            current_exposure=0,
            suggested_pct=0.20,
            current_price=150.0,
            lot_size=1000,
        )
        assert result["blocked"] is False
        assert result["lots"] == 1
        assert result["shares"] == 1000.0
        assert result["invest_amount"] == pytest.approx(150_000)

    def test_multiple_lots(self):
        # 100 萬 × 30% = 30 萬；一張 = 50 × 1000 = 5 萬 → 6 張整
        result = self.sizer.calculate(
            account_equity=1_000_000,
            current_exposure=0,
            suggested_pct=0.30,
            current_price=50.0,
            lot_size=1000,
        )
        assert result["lots"] == 6
        assert result["shares"] == 6000.0

    def test_lot_size_one_keeps_fractional_shares(self):
        # 零股/ETF 路徑（lot_size=1）行為不變：允許小數股數
        result = self.sizer.calculate(
            account_equity=1_000_000,
            current_exposure=0,
            suggested_pct=0.10,
            current_price=137.0,
        )
        assert result["blocked"] is False
        assert result["shares"] == pytest.approx(100_000 / 137.0, rel=0.01)
