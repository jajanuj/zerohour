"""台股交易日判斷測試（每日任務非交易日過濾）。"""
from datetime import date

from src.data.market_calendar import is_tw_trading_day


class TestIsTwTradingDay:

    def test_weekday_is_trading_day(self):
        # 2026-07-06 是週一
        assert is_tw_trading_day(date(2026, 7, 6), holidays_csv="") is True

    def test_saturday_is_not(self):
        assert is_tw_trading_day(date(2026, 7, 4), holidays_csv="") is False

    def test_sunday_is_not(self):
        assert is_tw_trading_day(date(2026, 7, 5), holidays_csv="") is False

    def test_holiday_in_list_is_not(self):
        assert is_tw_trading_day(
            date(2026, 10, 9), holidays_csv="2026-10-09,2026-10-10"
        ) is False

    def test_holiday_list_with_spaces(self):
        assert is_tw_trading_day(
            date(2026, 10, 9), holidays_csv=" 2026-10-09 , 2026-10-10 "
        ) is False

    def test_weekday_not_in_holiday_list(self):
        assert is_tw_trading_day(
            date(2026, 7, 6), holidays_csv="2026-10-09"
        ) is True

    def test_empty_holiday_csv(self):
        assert is_tw_trading_day(date(2026, 7, 7), holidays_csv="") is True
