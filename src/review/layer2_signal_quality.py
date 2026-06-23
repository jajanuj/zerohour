from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class SignalQualityReport:
    trade_date: date
    signal_confidence: float
    nasdaq_change_pct: float
    sox_change_pct: float
    taiwan_open_change_pct: float
    taiwan_close_change_pct: float
    tracking_error_pct: float
    trade_pnl_pct: float
    signal_was_correct: bool
    tracking_failure_reason: Optional[str]
    quality_score: float


def analyze_signal_quality(
    signal: dict,
    market_data: dict,
    trade: dict,
) -> SignalQualityReport:
    """
    分析今日訊號品質。

    signal_was_correct：美股漲跌方向 == 台股開盤方向。
    quality_score：方向正確 60 分，tracking error 越小越高分。
    """
    nasdaq_dir = 1 if signal.get("nasdaq_change_pct", 0) > 0 else -1
    tw_open = market_data.get("taiwan_open_change_pct", 0.0)
    tw_close = market_data.get("taiwan_close_change_pct", 0.0)
    taiwan_dir = 1 if tw_open > 0 else -1

    signal_was_correct = nasdaq_dir == taiwan_dir
    tracking_error = abs(signal.get("nasdaq_change_pct", 0) - tw_open)

    quality_score = 60.0 if signal_was_correct else 20.0
    quality_score += max(0.0, 40.0 - tracking_error * 10.0)
    quality_score = min(100.0, quality_score)

    return SignalQualityReport(
        trade_date=date.today(),
        signal_confidence=signal.get("confidence", 0.0),
        nasdaq_change_pct=signal.get("nasdaq_change_pct", 0.0),
        sox_change_pct=signal.get("sox_change_pct", 0.0),
        taiwan_open_change_pct=tw_open,
        taiwan_close_change_pct=tw_close,
        tracking_error_pct=tracking_error,
        trade_pnl_pct=trade.get("pnl_pct", 0.0),
        signal_was_correct=signal_was_correct,
        tracking_failure_reason=(
            None if signal_was_correct else "待人工標記或 AI 分析"
        ),
        quality_score=round(quality_score, 1),
    )
