import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass
class TimeDiffSignal:
    generated_at: datetime
    direction: SignalDirection
    confidence: float

    nasdaq_change_pct: float
    sp500_change_pct: float
    sox_change_pct: float

    trigger_reason: str
    suggested_symbol: str
    suggested_action: str

    conditions: list = field(default_factory=list)

    entry_window_start: time = field(default_factory=lambda: time(9, 0))
    entry_window_end: time = field(default_factory=lambda: time(9, 30))
    exit_time: time = field(default_factory=lambda: time(13, 25))


class TimeDiffSignalGenerator:
    """
    台美時間差訊號生成器。

    觸發條件（全部需符合）：
    1. NASDAQ 漲跌幅 > ±threshold
    2. S&P 500 方向一致
    3. 費半（SOX）同向（若啟用）
    """

    def __init__(
        self,
        nasdaq_threshold: float = 1.5,
        require_sox_confirmation: bool = True,
        min_confidence: float = 0.6,
    ):
        self.nasdaq_threshold = nasdaq_threshold
        self.require_sox_confirmation = require_sox_confirmation
        self.min_confidence = min_confidence

    def generate(
        self,
        nasdaq_change_pct: float,
        sp500_change_pct: float,
        sox_change_pct: float,
        generated_at: Optional[datetime] = None,
    ) -> TimeDiffSignal:
        generated_at = generated_at or datetime.now()

        # 逐條件明細（純比較/純函數，提前計算不影響決策；規格見
        # docs/report-optimization-plan.md §1.1）
        _sp500_aligned = (sp500_change_pct > 0) == (nasdaq_change_pct > 0)
        _sox_aligned = (sox_change_pct > 0) == (nasdaq_change_pct > 0)
        _confidence_preview = self._calc_confidence(
            nasdaq_change_pct, sp500_change_pct, sox_change_pct, _sox_aligned
        )
        conditions = [
            {
                "name": "nasdaq_threshold",
                "label": "NASDAQ 波動",
                "passed": abs(nasdaq_change_pct) >= self.nasdaq_threshold,
                "actual": f"{nasdaq_change_pct:+.2f}%",
                "threshold": f"±{self.nasdaq_threshold}%",
            },
            {
                "name": "sp500_aligned",
                "label": "S&P500 同向",
                "passed": _sp500_aligned,
                "actual": f"{sp500_change_pct:+.2f}%",
                "threshold": "與 NASDAQ 同向",
            },
            {
                "name": "sox_aligned",
                "label": "SOX 同向",
                "passed": _sox_aligned,
                "actual": f"{sox_change_pct:+.2f}%",
                "threshold": "與 NASDAQ 同向",
            },
            {
                "name": "min_confidence",
                "label": "信心度",
                "passed": _confidence_preview >= self.min_confidence,
                "actual": f"{_confidence_preview:.2f}",
                "threshold": f"≥{self.min_confidence}",
            },
        ]

        nasdaq_abs = abs(nasdaq_change_pct)
        if nasdaq_abs < self.nasdaq_threshold:
            return self._neutral(
                generated_at,
                nasdaq_change_pct,
                sp500_change_pct,
                sox_change_pct,
                reason=f"NASDAQ 漲跌幅 {nasdaq_change_pct:.2f}% 未達門檻 ±{self.nasdaq_threshold}%",
                conditions=conditions,
            )

        direction = SignalDirection.LONG if nasdaq_change_pct > 0 else SignalDirection.SHORT

        sp500_aligned = (sp500_change_pct > 0) == (nasdaq_change_pct > 0)
        if not sp500_aligned:
            return self._neutral(
                generated_at,
                nasdaq_change_pct,
                sp500_change_pct,
                sox_change_pct,
                reason="NASDAQ 與 S&P 500 方向不一致（板塊分化）",
                conditions=conditions,
            )

        sox_aligned = (sox_change_pct > 0) == (nasdaq_change_pct > 0)
        if self.require_sox_confirmation and not sox_aligned:
            return self._neutral(
                generated_at,
                nasdaq_change_pct,
                sp500_change_pct,
                sox_change_pct,
                reason="費半（SOX）方向與 NASDAQ 不一致",
                conditions=conditions,
            )

        confidence = self._calc_confidence(
            nasdaq_change_pct, sp500_change_pct, sox_change_pct, sox_aligned
        )

        if confidence < self.min_confidence:
            return self._neutral(
                generated_at,
                nasdaq_change_pct,
                sp500_change_pct,
                sox_change_pct,
                reason=f"信心度 {confidence:.2f} 低於最低門檻 {self.min_confidence}",
                conditions=conditions,
            )

        suggested_symbol, suggested_action = self._suggest_trade(direction)

        trigger_reason = (
            f"NASDAQ {nasdaq_change_pct:+.2f}% | "
            f"S&P500 {sp500_change_pct:+.2f}% | "
            f"SOX {sox_change_pct:+.2f}% | "
            f"信心度 {confidence:.0%}"
        )

        return TimeDiffSignal(
            generated_at=generated_at,
            direction=direction,
            confidence=confidence,
            nasdaq_change_pct=nasdaq_change_pct,
            sp500_change_pct=sp500_change_pct,
            sox_change_pct=sox_change_pct,
            trigger_reason=trigger_reason,
            suggested_symbol=suggested_symbol,
            suggested_action=suggested_action,
            conditions=conditions,
        )

    def _calc_confidence(
        self,
        nasdaq_pct: float,
        sp500_pct: float,
        sox_pct: float,
        sox_aligned: bool,
    ) -> float:
        base = 0.5
        excess = abs(nasdaq_pct) - self.nasdaq_threshold
        base += min(excess * 0.1, 0.2)
        if sox_aligned:
            base += 0.2
        if abs(sp500_pct) > 1.0 and abs(sox_pct) > 2.0 and sox_aligned:
            base += 0.1
        return min(base, 1.0)

    def _suggest_trade(self, direction: SignalDirection) -> tuple[str, str]:
        if direction == SignalDirection.LONG:
            return "0050", "BUY"
        return "MTX", "SELL"

    def _neutral(
        self,
        generated_at: datetime,
        nasdaq: float,
        sp500: float,
        sox: float,
        reason: str,
        conditions: Optional[list] = None,
    ) -> TimeDiffSignal:
        return TimeDiffSignal(
            generated_at=generated_at,
            direction=SignalDirection.NEUTRAL,
            confidence=0.0,
            nasdaq_change_pct=nasdaq,
            sp500_change_pct=sp500,
            sox_change_pct=sox,
            trigger_reason=reason,
            suggested_symbol="",
            suggested_action="HOLD",
            conditions=conditions or [],
        )
