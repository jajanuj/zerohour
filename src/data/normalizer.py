import pandas as pd
import numpy as np
from typing import Optional


class DataNormalizer:
    """資料標準化：統一欄位名稱、時區、缺值處理。"""

    @staticmethod
    def normalize_ohlcv(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
        df = df.copy()
        df.columns = [c.lower().strip() for c in df.columns]

        rename_map = {
            "datetime": "date",
            "timestamp": "date",
            "adj close": "close",
            "adj_close": "close",
        }
        df = df.rename(columns=rename_map)

        required = ["date", "open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                df[col] = np.nan

        df = df[required].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)

        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["date", "close"])

        if source:
            df["source"] = source

        return df

    @staticmethod
    def calculate_change_pct(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["change_pct"] = df["close"].pct_change() * 100
        return df

    @staticmethod
    def merge_us_signals(
        nasdaq_df: pd.DataFrame,
        sp500_df: pd.DataFrame,
        sox_df: pd.DataFrame,
    ) -> pd.DataFrame:
        n = nasdaq_df[["date", "close", "change_pct"]].rename(
            columns={"close": "nasdaq_close", "change_pct": "nasdaq_chg"}
        )
        s = sp500_df[["date", "close", "change_pct"]].rename(
            columns={"close": "sp500_close", "change_pct": "sp500_chg"}
        )
        x = sox_df[["date", "close", "change_pct"]].rename(
            columns={"close": "sox_close", "change_pct": "sox_chg"}
        )

        merged = n.merge(s, on="date", how="inner").merge(x, on="date", how="inner")
        return merged.sort_values("date").reset_index(drop=True)
