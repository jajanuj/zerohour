import pandas as pd
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class DataStore:
    """
    資料存取介面（暫時使用 in-memory 快取）。
    整合 DB 後可替換為 SQLAlchemy 實作。
    """

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}

    def save_ohlcv(self, symbol: str, df: pd.DataFrame) -> None:
        self._cache[symbol] = df.copy()
        logger.debug(f"Saved {len(df)} rows for {symbol}")

    def load_ohlcv(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        df = self._cache.get(symbol)
        if df is None:
            return None

        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        return df.reset_index(drop=True)

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self._cache

    def get_latest_date(self, symbol: str) -> Optional[datetime]:
        df = self._cache.get(symbol)
        if df is None or df.empty:
            return None
        return df["date"].max().to_pydatetime()
