from enum import Enum
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class OverrideType(str, Enum):
    SKIP_SIGNAL = "跳過系統訊號"
    EARLY_EXIT = "提前出場"
    DELAYED_EXIT = "延遲出場"
    SIZE_CHANGE = "更改倉位大小"
    MANUAL_ENTRY = "手動進場（無訊號）"


class OverrideTracker:
    """人為干預追蹤器。"""

    def __init__(self):
        self._overrides: list[dict] = []

    def log_override(
        self,
        override_type: OverrideType,
        reason: str,
        system_recommendation: dict,
        actual_action: dict,
    ) -> int:
        record = {
            "id": len(self._overrides) + 1,
            "override_type": override_type.value,
            "reason": reason,
            "system_recommendation": system_recommendation,
            "actual_action": actual_action,
            "override_at": datetime.utcnow().isoformat(),
            "actual_pnl_pct": None,
            "counterfactual_pnl_pct": None,
            "helped": None,
        }
        self._overrides.append(record)
        logger.info(f"人為干預記錄：{override_type.value} | {reason}")
        return record["id"]

    def evaluate_override(self, override_id: int, actual_pnl: float, counterfactual_pnl: float) -> None:
        for o in self._overrides:
            if o["id"] == override_id:
                o["actual_pnl_pct"] = actual_pnl
                o["counterfactual_pnl_pct"] = counterfactual_pnl
                o["helped"] = actual_pnl > counterfactual_pnl
                break

    def monthly_report(self) -> dict:
        total = len(self._overrides)
        evaluated = [o for o in self._overrides if o["helped"] is not None]
        helped = sum(1 for o in evaluated if o["helped"])
        return {
            "total_overrides": total,
            "evaluated": len(evaluated),
            "helped_count": helped,
            "hurt_count": len(evaluated) - helped,
            "help_rate": helped / len(evaluated) if evaluated else 0.0,
        }
