"""safe_change_pct 測試 — docs/report-optimization-plan.md Phase D。

核心防線：`x or 0.0` 擋不住 NaN（NaN 是 truthy，LESSONS 2026-06），
所有指數漲跌幅取值必須走 safe_change_pct。
"""
import math

from src.data.normalizer import safe_change_pct


class TestSafeChangePct:

    def test_none_dict(self):
        assert safe_change_pct(None) == (0.0, True)

    def test_empty_dict(self):
        assert safe_change_pct({}) == (0.0, True)

    def test_missing_key(self):
        assert safe_change_pct({"close": 100.0}) == (0.0, True)

    def test_nan_is_defaulted(self):
        val, defaulted = safe_change_pct({"change_pct": float("nan")})
        assert val == 0.0 and defaulted is True

    def test_inf_is_defaulted(self):
        val, defaulted = safe_change_pct({"change_pct": float("inf")})
        assert val == 0.0 and defaulted is True

    def test_string_garbage(self):
        assert safe_change_pct({"change_pct": "abc"}) == (0.0, True)

    def test_normal_value(self):
        assert safe_change_pct({"change_pct": 1.75}) == (1.75, False)

    def test_negative_value(self):
        assert safe_change_pct({"change_pct": -2.3}) == (-2.3, False)

    def test_zero_is_not_defaulted(self):
        # 真的漲跌 0.0% 是合法值，不能標記為降級
        assert safe_change_pct({"change_pct": 0.0}) == (0.0, False)

    def test_numeric_string_ok(self):
        val, defaulted = safe_change_pct({"change_pct": "1.5"})
        assert val == 1.5 and defaulted is False

    def test_nan_or_pattern_would_fail(self):
        # 反例證明：舊寫法 `x or 0.0` 對 NaN 無效（這正是要修的坑）
        nan = float("nan")
        assert math.isnan(nan or 0.0)
