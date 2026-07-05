from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import logging

from .ma200_filter import MA200Filter, TrendState, MA200Signal
from .time_diff import TimeDiffSignalGenerator, TimeDiffSignal, SignalDirection

logger = logging.getLogger(__name__)


class FinalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT_ALL = "EXIT_ALL"


@dataclass
class CombinedSignal:
    final_action: FinalAction
    symbol: str
    trend_signal: MA200Signal
    time_diff_signal: TimeDiffSignal
    reason: str
    suggested_position_pct: float
    stop_loss_pct: float
    trailing_stop_pct: float
    conditions: list = field(default_factory=list)
    next_step: str = ""  # Phase C 填值（docs/report-optimization-plan.md）


class SignalAggregator:
    """
    組合訊號整合器（S1 × S2）。

    決策矩陣：
    BULL  × LONG    → BUY
    BULL  × SHORT   → HOLD
    BULL  × NEUTRAL → HOLD
    BEAR  × 任何    → EXIT_ALL
    UNDEF × 任何    → HOLD
    """

    def __init__(
        self,
        base_position_pct: float = 0.25,
        max_position_pct: float = 0.40,
        index_stop_loss_pct: float = 0.12,
        trailing_stop_pct: float = 0.15,
        ma200_enter_buffer_pct: float = 0.0,
        ma200_exit_buffer_pct: float = 0.0,
    ):
        self.base_position_pct = base_position_pct
        self.max_position_pct = max_position_pct
        self.index_stop_loss_pct = index_stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct
        # 僅供 next_step 文案顯示用，不參與任何決策（report-optimization-plan Phase C）
        self.ma200_enter_buffer_pct = ma200_enter_buffer_pct
        self.ma200_exit_buffer_pct = ma200_exit_buffer_pct

    def aggregate(
        self,
        trend: MA200Signal,
        time_diff: TimeDiffSignal,
        current_positions: Optional[dict] = None,
    ) -> CombinedSignal:
        # 逐條件明細（觀測層，不影響決策矩陣；規格見 docs/report-optimization-plan.md §1.1）
        conditions = [
            {
                "name": "s1_trend",
                "label": "S1 趨勢",
                "passed": trend.state == TrendState.BULL,
                "actual": f"{trend.state.value}（{trend.distance_pct:+.1f}%）",
                "threshold": "BULL",
            },
            {
                "name": "s2_direction",
                "label": "S2 方向",
                "passed": time_diff.direction == SignalDirection.LONG,
                "actual": time_diff.direction.value,
                "threshold": "LONG",
            },
        ]

        if trend.state == TrendState.BEAR:
            return CombinedSignal(
                final_action=FinalAction.EXIT_ALL,
                symbol="ALL",
                trend_signal=trend,
                time_diff_signal=time_diff,
                reason=f"200MA 趨勢轉空（距離 {trend.distance_pct:.1f}%），強制清倉",
                suggested_position_pct=0.0,
                stop_loss_pct=0.0,
                trailing_stop_pct=0.0,
                conditions=conditions,
                next_step=(
                    f"等待 QQQ 收盤重新站上 "
                    f"{trend.ma200 * (1 + self.ma200_enter_buffer_pct):.2f}"
                    f"（MA200 進場緩衝上緣）"
                    if trend.ma200 > 0 else "等待 S1 趨勢轉多"
                ),
            )

        if trend.state == TrendState.UNDEFINED:
            return CombinedSignal(
                final_action=FinalAction.HOLD,
                symbol="",
                trend_signal=trend,
                time_diff_signal=time_diff,
                reason="200MA 資料不足，維持觀望",
                suggested_position_pct=0.0,
                stop_loss_pct=0.0,
                trailing_stop_pct=0.0,
                conditions=conditions,
                next_step="等待 200 日均線資料累積完成",
            )

        if trend.state == TrendState.BULL and time_diff.direction == SignalDirection.LONG:
            position_pct = self.base_position_pct + (
                time_diff.confidence * (self.max_position_pct - self.base_position_pct)
            )
            position_pct = min(position_pct, self.max_position_pct)

            return CombinedSignal(
                final_action=FinalAction.BUY,
                symbol=time_diff.suggested_symbol,
                trend_signal=trend,
                time_diff_signal=time_diff,
                reason=(
                    f"雙重確認：200MA 多頭（{trend.distance_pct:+.1f}%）× "
                    f"時間差 LONG（信心 {time_diff.confidence:.0%}）"
                ),
                suggested_position_pct=round(position_pct, 3),
                stop_loss_pct=self.index_stop_loss_pct,
                trailing_stop_pct=self.trailing_stop_pct,
                conditions=conditions,
                next_step=(
                    f"依建議倉位 {round(position_pct, 3):.0%} 執行，"
                    f"停損 {self.index_stop_loss_pct:.0%}"
                ),
            )

        # 下一步文案：取 S2 第一個未通過的條件（純顯示，不影響決策）
        _failed = next(
            (c for c in time_diff.conditions if c.get("passed") is False), None
        )
        next_step = (
            f"等待 {_failed['label']} 達標（目前 {_failed['actual']}，需 {_failed['threshold']}）"
            if _failed else "等待 S2 訊號轉 LONG"
        )

        return CombinedSignal(
            final_action=FinalAction.HOLD,
            symbol="",
            trend_signal=trend,
            time_diff_signal=time_diff,
            reason=(
                f"趨勢多頭但短線訊號為 {time_diff.direction.value}，"
                f"維持觀望（{time_diff.trigger_reason}）"
            ),
            suggested_position_pct=0.0,
            stop_loss_pct=0.0,
            trailing_stop_pct=0.0,
            conditions=conditions,
            next_step=next_step,
        )
