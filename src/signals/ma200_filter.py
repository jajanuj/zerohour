import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TrendState(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    UNDEFINED = "UNDEFINED"


@dataclass
class MA200Signal:
    symbol: str
    date: pd.Timestamp
    state: TrendState
    current_price: float
    ma200: float
    distance_pct: float
    is_newly_crossed: bool


class MA200Filter:
    """
    200 日移動平均線趨勢過濾系統。

    規則：每月最後一個交易日收盤時判斷。
    收盤價 > 200MA → BULL；< 200MA → BEAR。
    """

    def __init__(self, period: int = 200):
        self.period = period

    def calculate(
        self,
        price_data: pd.DataFrame,
        symbol: str,
        check_date: Optional[pd.Timestamp] = None,
    ) -> MA200Signal:
        if len(price_data) < self.period:
            logger.warning(f"{symbol}: 資料不足 {len(price_data)} 筆，需要至少 {self.period} 筆")
            last_date = price_data["date"].iloc[-1] if not price_data.empty else pd.Timestamp.now()
            return MA200Signal(
                symbol=symbol,
                date=last_date,
                state=TrendState.UNDEFINED,
                current_price=0.0,
                ma200=0.0,
                distance_pct=0.0,
                is_newly_crossed=False,
            )

        df = price_data.copy().sort_values("date").reset_index(drop=True)
        df["ma200"] = df["close"].rolling(self.period).mean()

        if check_date is not None:
            mask = df["date"] == check_date
            if not mask.any():
                raise ValueError(f"找不到日期 {check_date} 的資料")
            idx = df[mask].index[0]
        else:
            idx = df.index[-1]

        current_price = float(df.loc[idx, "close"])
        ma200_val = df.loc[idx, "ma200"]
        date = df.loc[idx, "date"]

        if pd.isna(ma200_val):
            state = TrendState.UNDEFINED
            ma200 = 0.0
            distance_pct = 0.0
        elif current_price > ma200_val:
            state = TrendState.BULL
            ma200 = float(ma200_val)
            distance_pct = (current_price - ma200) / ma200 * 100
        else:
            state = TrendState.BEAR
            ma200 = float(ma200_val)
            distance_pct = (current_price - ma200) / ma200 * 100

        is_newly_crossed = self._check_newly_crossed(df, idx, state)

        return MA200Signal(
            symbol=symbol,
            date=date,
            state=state,
            current_price=current_price,
            ma200=ma200,
            distance_pct=float(distance_pct),
            is_newly_crossed=is_newly_crossed,
        )

    def _check_newly_crossed(
        self,
        df: pd.DataFrame,
        current_idx: int,
        current_state: TrendState,
    ) -> bool:
        if current_idx == 0 or current_state == TrendState.UNDEFINED:
            return False

        loc = df.index.get_loc(current_idx)
        if loc == 0:
            return False

        prev_idx = df.index[loc - 1]
        prev_price = df.loc[prev_idx, "close"]
        prev_ma200 = df.loc[prev_idx, "ma200"]

        if pd.isna(prev_ma200):
            return False

        prev_was_bull = float(prev_price) > float(prev_ma200)
        current_is_bull = current_state == TrendState.BULL
        return prev_was_bull != current_is_bull
