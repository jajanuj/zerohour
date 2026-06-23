from dataclasses import dataclass
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
    ):
        self.base_position_pct = base_position_pct
        self.max_position_pct = max_position_pct
        self.index_stop_loss_pct = index_stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct

    def aggregate(
        self,
        trend: MA200Signal,
        time_diff: TimeDiffSignal,
        current_positions: Optional[dict] = None,
    ) -> CombinedSignal:
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
        )
