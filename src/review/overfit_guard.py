import pandas as pd
import logging

logger = logging.getLogger(__name__)

MIN_TRADES_BEFORE_CHANGE = 30


class OverfitGuard:
    """
    防止根據近期表現過度調整策略參數。

    三道防線：
    1. 樣本數門檻（≥ 30 筆）
    2. 時間窗口驗證
    3. 外樣本測試提醒
    """

    def validate_parameter_change(
        self,
        param_name: str,
        old_value: float,
        new_value: float,
        trade_history: pd.DataFrame,
        change_reason: str,
    ) -> dict:
        result: dict = {
            "approved": False,
            "warnings": [],
            "required_actions": [],
        }

        n_trades = len(trade_history)
        if n_trades < MIN_TRADES_BEFORE_CHANGE:
            result["warnings"].append(
                f"樣本數不足：現有 {n_trades} 筆，需至少 {MIN_TRADES_BEFORE_CHANGE} 筆才能調整參數"
            )
            return result

        if not change_reason or len(change_reason) < 10:
            result["warnings"].append("變更原因描述過短，請詳述數據依據")
            return result

        result["required_actions"].extend([
            "執行時間窗口驗證：用新參數回測「問題期之前」的數據",
            "執行外樣本測試：使用 2015–2019 數據（未用於設計策略的時段）",
        ])

        result["approved"] = True
        logger.info(
            f"參數變更請求：{param_name} {old_value} → {new_value} | {change_reason}"
        )
        return result
