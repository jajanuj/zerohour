"""S4 台股趨勢確認因子 — docs/strategy-s4-spec.md。

定位：S3 的 BUY 倉位調整係數（方案 A）。S3 的進出時點、決策矩陣、
停損停利一律不變，本模組只產出一個乘在 suggested_position_pct 上的係數。

失效保護（§5）：任何資料抓不到 → fail-open ×1.0 + data_ok=False
（呼叫端據此發 Discord 警告）；係數強制夾在 [0.5, 1.0]。
"""
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import httpx

from .ma200_filter import MA200Filter, TrendState

logger = logging.getLogger(__name__)

# TWSE 三大法人買賣金額統計（BFI82U）。實測回傳結構見 strategy-s4-spec.md §2。
TWSE_BFI82U_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"

# §5.3：係數夾限，防止未來改表手滑寫出放大槓桿的值
MODIFIER_FLOOR = 0.5
MODIFIER_CEIL = 1.0


@dataclass
class TaiexConfirmSignal:
    taiex_state: str            # "BULL" / "BEAR" / "UNDEFINED"（沿用 TrendState 值）
    inst_net_5d: float | None   # 三大法人5日合計買賣差額（億元）；None = 無資料
    modifier: float             # §3 係數，已夾限
    reason: str                 # 人話說明，進 Discord 與 log
    # 入庫附載（B4 復用 save_trend_signal(symbol="TAIEX") 所需欄位）
    taiex_price: float = 0.0
    taiex_ma200: float = 0.0
    taiex_distance_pct: float = 0.0
    data_ok: bool = True        # False = 走了 fail-open 路徑（呼叫端需發 Discord 警告）
    conditions: list = field(default_factory=list)


def lookup_modifier(taiex_state: str, inst_net_5d: float | None) -> tuple[float, str]:
    """§3 係數表 v0。net >= 0 視為買超。回傳 (係數, 說明)。"""
    if taiex_state not in ("BULL", "BEAR") or inst_net_5d is None:
        missing = []
        if taiex_state not in ("BULL", "BEAR"):
            missing.append("TAIEX 趨勢")
        if inst_net_5d is None:
            missing.append("法人5日淨額")
        return 1.0, f"S4 無資料（{'、'.join(missing)}），fail-open ×1.00"
    if taiex_state == "BULL":
        if inst_net_5d >= 0:
            return 1.0, f"S4 雙確認：TAIEX 站上 200MA + 法人5日買超 {inst_net_5d:+.0f} 億 ×1.00"
        return 0.75, f"S4：TAIEX 站上 200MA 但法人5日賣超 {inst_net_5d:+.0f} 億 ×0.75"
    side = "買超" if inst_net_5d >= 0 else "賣超"
    return 0.5, f"S4 台美背離：TAIEX 跌破 200MA + 法人5日{side} {inst_net_5d:+.0f} 億 ×0.50"


def clamp_modifier(m: float) -> float:
    """§5.3 夾限 [0.5, 1.0]。"""
    return max(MODIFIER_FLOOR, min(MODIFIER_CEIL, m))


def _default_http_get(url: str, params: dict, timeout: float) -> dict:
    resp = httpx.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class TaiexConfirmFilter:
    """S4 訊號計算器。fetcher / normalizer / http_get 可注入供測試 mock（§6）。"""

    def __init__(
        self,
        fetcher=None,
        normalizer=None,
        http_get: Optional[Callable[[str, dict, float], dict]] = None,
        ma_period: int = 200,
        per_call_timeout: float = 10.0,
        total_budget_s: float = 30.0,
        max_walkback_days: int = 10,
    ):
        if fetcher is None:
            from ..data.fetcher import TWMarketFetcher
            fetcher = TWMarketFetcher()
        if normalizer is None:
            from ..data.normalizer import DataNormalizer
            normalizer = DataNormalizer()
        self._fetcher = fetcher
        self._normalizer = normalizer
        self._http_get = http_get or _default_http_get
        self.ma_period = ma_period
        self.per_call_timeout = per_call_timeout
        self.total_budget_s = total_budget_s
        self.max_walkback_days = max_walkback_days

    # ── 子指標 1：TAIEX vs 200MA ───────────────────────────────────

    def _fetch_taiex_trend(self) -> tuple[str, float, float, float]:
        """回傳 (state, price, ma200, distance_pct)；任何失敗 → UNDEFINED。"""
        try:
            raw = self._fetcher.get_historical("taiex", period="2y")
            df = self._normalizer.normalize_ohlcv(raw)
            sig = MA200Filter(period=self.ma_period).calculate(df, "^TWII")
            price = float(sig.current_price)
            ma200 = float(sig.ma200)
            dist = float(sig.distance_pct)
            if not all(math.isfinite(v) for v in (price, ma200, dist)):
                return TrendState.UNDEFINED.value, 0.0, 0.0, 0.0
            return sig.state.value, price, ma200, dist
        except Exception as e:
            logger.warning(f"S4 TAIEX 趨勢抓取失敗: {e}")
            return TrendState.UNDEFINED.value, 0.0, 0.0, 0.0

    # ── 子指標 2：三大法人 5 日淨額 ─────────────────────────────────

    def _fetch_inst_net_5d(self) -> float | None:
        """近 5 個交易日合計買賣差額（億元）。

        從今天往回逐日呼叫 BFI82U：stat 非 OK（假日）跳過續走；
        HTTP 失敗/逾時/結構異常/超出預算或回看上限 → None（無資料，§2）。
        """
        deadline = time.monotonic() + self.total_budget_s
        total = 0.0
        days_got = 0
        probe = datetime.now()
        for _ in range(self.max_walkback_days):
            if days_got >= 5:
                break
            if time.monotonic() >= deadline:
                logger.warning("S4 TWSE 法人資料超出總時間預算，視為無資料")
                return None
            date_str = probe.strftime("%Y%m%d")
            probe -= timedelta(days=1)
            try:
                data = self._http_get(
                    TWSE_BFI82U_URL,
                    {"dayDate": date_str, "type": "day", "response": "json"},
                    self.per_call_timeout,
                )
            except Exception as e:
                logger.warning(f"S4 TWSE BFI82U {date_str} 抓取失敗: {e}")
                return None
            if not isinstance(data, dict) or data.get("stat") != "OK":
                continue  # 非交易日（實測 stat = "很抱歉，沒有符合條件的資料!"）
            try:
                rows = data["data"]
                total_row = next(r for r in rows if r[0] == "合計")
                diff = float(str(total_row[3]).replace(",", ""))
                if not math.isfinite(diff):
                    return None
            except Exception as e:
                logger.warning(f"S4 TWSE BFI82U {date_str} 結構異常: {e}")
                return None
            total += diff
            days_got += 1
        if days_got < 5:
            logger.warning(f"S4 法人資料僅取得 {days_got}/5 個交易日，視為無資料")
            return None
        return total / 1e8  # 元 → 億元

    # ── 主流程 ─────────────────────────────────────────────────────

    def calculate(self) -> TaiexConfirmSignal:
        state, price, ma200, dist = self._fetch_taiex_trend()
        net = self._fetch_inst_net_5d()

        modifier, reason = lookup_modifier(state, net)
        modifier = clamp_modifier(modifier)
        data_ok = state in ("BULL", "BEAR") and net is not None

        conditions = [
            {
                "name": "taiex_vs_ma200",
                "label": "TAIEX vs 200MA",
                "passed": (state == "BULL") if state in ("BULL", "BEAR") else None,
                "actual": f"{price:.0f}" if price > 0 else "無資料",
                "threshold": f"MA200 {ma200:.0f}" if ma200 > 0 else "站上 200MA",
            },
            {
                "name": "inst_net_5d",
                "label": "法人5日淨額",
                "passed": (net >= 0) if net is not None else None,
                "actual": f"{net:+.0f} 億" if net is not None else "無資料",
                "threshold": "買超（≥0）",
            },
        ]

        return TaiexConfirmSignal(
            taiex_state=state,
            inst_net_5d=net,
            modifier=modifier,
            reason=reason,
            taiex_price=price,
            taiex_ma200=ma200,
            taiex_distance_pct=dist,
            data_ok=data_ok,
            conditions=conditions,
        )
