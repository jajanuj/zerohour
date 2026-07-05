"""台股交易日判斷 — 每日任務非交易日過濾用。

判準：台灣時間（UTC+8，無夏令時）週一~週五，且不在 settings.tw_market_holidays
（逗號分隔的 YYYY-MM-DD 清單，由老闆在環境變數維護國定假日）。

設計取捨：不引入交易所行事曆 API 依賴。週末過濾擋掉絕大多數浪費；
未填假日清單時假日仍會照跑（與過濾前行為相同，只是多耗一次額度），
不會造成漏跑交易日的風險方向錯誤。
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def tw_today() -> date:
    """台灣時間的今天（UTC+8 固定偏移，台灣無夏令時）。"""
    return (datetime.utcnow() + timedelta(hours=8)).date()


def is_tw_trading_day(day: Optional[date] = None, holidays_csv: Optional[str] = None) -> bool:
    """day 預設為台灣今天；holidays_csv 預設讀 settings.tw_market_holidays。"""
    day = day or tw_today()
    if day.weekday() >= 5:  # 週六=5、週日=6
        return False
    if holidays_csv is None:
        from ..config import get_settings
        holidays_csv = get_settings().tw_market_holidays
    holidays = {s.strip() for s in holidays_csv.split(",") if s.strip()}
    return day.isoformat() not in holidays


def skip_if_non_trading_day(task_name: str) -> Optional[dict]:
    """非交易日回傳 skip 結果 dict（任務直接 return 它）；交易日回傳 None。"""
    if is_tw_trading_day():
        return None
    logger.info(f"{task_name}: 台股非交易日（{tw_today().isoformat()}），跳過")
    return {"status": "skipped", "reason": f"non-trading day {tw_today().isoformat()}"}
