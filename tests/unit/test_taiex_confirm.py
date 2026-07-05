"""S4 台股趨勢確認因子測試 — docs/strategy-s4-spec.md §6。

覆蓋：§3 係數表全部 5 列、TWSE 部分天數失敗、假日跳過、^TWII 資料不足、
係數夾限、時間預算。TWSE HTTP 一律 mock，不打真網路。
"""
import pandas as pd
from datetime import datetime, timedelta

from src.data.normalizer import DataNormalizer
from src.signals.taiex_confirm import (
    TaiexConfirmFilter,
    TaiexConfirmSignal,
    lookup_modifier,
    clamp_modifier,
)


# ── 測試用假件 ──────────────────────────────────────────────────────

def make_taiex_df(n=250, price=20000.0, last=None):
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    closes = [price] * n
    if last is not None:
        closes[-1] = last
    return pd.DataFrame({"date": dates, "close": closes})


class FakeFetcher:
    def __init__(self, df):
        self.df = df

    def get_historical(self, symbol, period="2y", **kwargs):
        return self.df


class BrokenFetcher:
    def get_historical(self, symbol, period="2y", **kwargs):
        raise RuntimeError("yfinance down")


def ok_day(diff_ntd: int) -> dict:
    """實測 BFI82U 回傳結構（strategy-s4-spec.md §2）：合計列在最後、金額千分位字串、單位元。"""
    return {
        "stat": "OK",
        "fields": ["單位名稱", "買進金額", "賣出金額", "買賣差額"],
        "data": [
            ["自營商(自行買賣)", "1", "1", "0"],
            ["投信", "1", "1", "0"],
            ["合計", "1", "1", f"{diff_ntd:,}"],
        ],
    }


def holiday() -> dict:
    return {"stat": "很抱歉，沒有符合條件的資料!", "hints": "單位：元"}


class ScriptedHttp:
    """依序回放回應；遇 Exception 項則 raise。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, url, params, timeout):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_filter(df, http_responses, **kw):
    return TaiexConfirmFilter(
        fetcher=FakeFetcher(df),
        normalizer=DataNormalizer(),
        http_get=ScriptedHttp(http_responses),
        **kw,
    )


# ── §3 係數表（純函數） ─────────────────────────────────────────────

class TestLookupModifier:

    def test_bull_buy(self):
        m, r = lookup_modifier("BULL", 500.0)
        assert m == 1.0 and "雙確認" in r

    def test_bull_sell(self):
        m, _ = lookup_modifier("BULL", -500.0)
        assert m == 0.75

    def test_bear_buy(self):
        m, r = lookup_modifier("BEAR", 500.0)
        assert m == 0.5 and "背離" in r

    def test_bear_sell(self):
        m, _ = lookup_modifier("BEAR", -500.0)
        assert m == 0.5

    def test_no_data_fail_open(self):
        assert lookup_modifier("UNDEFINED", 500.0)[0] == 1.0
        assert lookup_modifier("BULL", None)[0] == 1.0
        assert "fail-open" in lookup_modifier("BULL", None)[1]

    def test_net_zero_counts_as_buy(self):
        assert lookup_modifier("BULL", 0.0)[0] == 1.0


class TestClampModifier:

    def test_clamp(self):
        assert clamp_modifier(0.3) == 0.5   # §5.3 下限
        assert clamp_modifier(1.5) == 1.0   # §5.3 上限（防手滑放大槓桿）
        assert clamp_modifier(0.75) == 0.75


# ── 端到端（mock 資料源） ───────────────────────────────────────────

class TestTaiexConfirmFilter:

    def test_bull_buy_full_position(self):
        f = make_filter(make_taiex_df(last=22000.0), [ok_day(2_500_000_000)] * 5)
        sig = f.calculate()
        assert sig.taiex_state == "BULL"
        assert sig.inst_net_5d == 125.0  # 5 × 25e8 元 = 125 億
        assert sig.modifier == 1.0
        assert sig.data_ok is True

    def test_bear_sell_half_position(self):
        f = make_filter(make_taiex_df(last=18000.0), [ok_day(-2_500_000_000)] * 5)
        sig = f.calculate()
        assert sig.taiex_state == "BEAR"
        assert sig.modifier == 0.5

    def test_holiday_days_are_skipped(self):
        http = ScriptedHttp([holiday(), holiday()] + [ok_day(1_000_000_000)] * 5)
        f = TaiexConfirmFilter(
            fetcher=FakeFetcher(make_taiex_df(last=22000.0)),
            normalizer=DataNormalizer(),
            http_get=http,
        )
        sig = f.calculate()
        assert sig.inst_net_5d == 50.0  # 5 × 10e8 = 50 億
        assert http.calls == 7          # 2 假日 + 5 交易日
        assert sig.data_ok is True

    def test_partial_http_failure_fails_open(self):
        f = make_filter(
            make_taiex_df(last=22000.0),
            [ok_day(1), ok_day(1), RuntimeError("timeout")],
        )
        sig = f.calculate()
        assert sig.inst_net_5d is None
        assert sig.modifier == 1.0
        assert sig.data_ok is False

    def test_walkback_exhausted_fails_open(self):
        f = make_filter(make_taiex_df(last=22000.0), [holiday()] * 10)
        sig = f.calculate()
        assert sig.inst_net_5d is None
        assert sig.modifier == 1.0

    def test_insufficient_taiex_data_fails_open(self):
        # ^TWII 不足 200 根 → UNDEFINED → fail-open（即使法人資料正常）
        f = make_filter(make_taiex_df(n=100), [ok_day(1_000_000_000)] * 5)
        sig = f.calculate()
        assert sig.taiex_state == "UNDEFINED"
        assert sig.modifier == 1.0
        assert sig.data_ok is False

    def test_fetcher_exception_fails_open(self):
        f = TaiexConfirmFilter(
            fetcher=BrokenFetcher(),
            normalizer=DataNormalizer(),
            http_get=ScriptedHttp([ok_day(1_000_000_000)] * 5),
        )
        sig = f.calculate()
        assert sig.taiex_state == "UNDEFINED"
        assert sig.modifier == 1.0

    def test_budget_exhausted_fails_open(self):
        f = make_filter(
            make_taiex_df(last=22000.0),
            [ok_day(1_000_000_000)] * 5,
            total_budget_s=0.0,  # 預算歸零 → 立即放棄
        )
        sig = f.calculate()
        assert sig.inst_net_5d is None
        assert sig.modifier == 1.0

    def test_malformed_response_fails_open(self):
        f = make_filter(
            make_taiex_df(last=22000.0),
            [{"stat": "OK", "data": [["怪列", "x"]]}],  # 無合計列
        )
        sig = f.calculate()
        assert sig.inst_net_5d is None
        assert sig.modifier == 1.0

    def test_conditions_structure(self):
        f = make_filter(make_taiex_df(last=22000.0), [ok_day(2_500_000_000)] * 5)
        sig = f.calculate()
        names = [c["name"] for c in sig.conditions]
        assert names == ["taiex_vs_ma200", "inst_net_5d"]
        assert all(
            set(c.keys()) == {"name", "label", "passed", "actual", "threshold"}
            for c in sig.conditions
        )
        assert sig.conditions[0]["passed"] is True
        assert sig.conditions[1]["passed"] is True

    def test_conditions_none_when_no_data(self):
        f = make_filter(make_taiex_df(n=100), [RuntimeError("down")])
        sig = f.calculate()
        assert sig.conditions[0]["passed"] is None
        assert sig.conditions[1]["passed"] is None
