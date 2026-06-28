import math
import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

US_SYMBOLS = {
    "nasdaq": "^IXIC",
    "sp500": "^GSPC",
    "sox": "^SOX",
    "qqq": "QQQ",
    "tqqq": "TQQQ",
    "vix": "^VIX",
}

TW_SYMBOLS = {
    "0050": "0050.TW",
    "taiex": "^TWII",
}


class USMarketFetcher:
    """美股市場資料抓取器。"""

    def get_latest_close(self, symbol_key: str) -> dict:
        ticker_code = US_SYMBOLS.get(symbol_key, symbol_key)
        ticker = yf.Ticker(ticker_code)
        hist = ticker.history(period="5d")
        if hist.empty:
            raise ValueError(f"無法取得 {ticker_code} 的資料")

        # Drop any rows where Close is NaN (can happen for indices on weekends)
        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            raise ValueError(f"{ticker_code} 所有資料列 Close 均為 NaN")

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else None
        change_pct = 0.0
        if prev is not None:
            raw = (float(latest["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100
            # Guard NaN / Inf — Pydantic v2 serialises float('nan') → JSON null
            change_pct = raw if math.isfinite(raw) else 0.0

        return {
            "symbol": ticker_code,
            "date": hist.index[-1].to_pydatetime(),
            "close": float(latest["Close"]),
            "change_pct": round(change_pct, 4),
            "volume": int(latest["Volume"]),
        }

    def get_historical(
        self,
        symbol_key: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        period: str = "2y",
    ) -> pd.DataFrame:
        ticker_code = US_SYMBOLS.get(symbol_key, symbol_key)
        ticker = yf.Ticker(ticker_code)

        if start_date and end_date:
            hist = ticker.history(start=start_date, end=end_date)
        else:
            hist = ticker.history(period=period)

        df = hist.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"datetime": "date", "index": "date"})
        for col in ["date", "open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = None
        df = df[["date", "open", "high", "low", "close", "volume"]]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df

    def get_all_signals_data(self) -> dict:
        results = {}
        for key in ["nasdaq", "sp500", "sox", "vix"]:
            try:
                results[key] = self.get_latest_close(key)
            except Exception as e:
                logger.error(f"抓取 {key} 失敗: {e}")
                results[key] = None
        return results


class TWMarketFetcher:
    """台股市場資料抓取器。"""

    def get_historical(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        period: str = "2y",
    ) -> pd.DataFrame:
        ticker_code = TW_SYMBOLS.get(symbol, f"{symbol}.TW")
        ticker = yf.Ticker(ticker_code)
        hist = ticker.history(period=period)
        df = hist.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"datetime": "date", "index": "date"})
        for col in ["date", "open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = None
        df = df[["date", "open", "high", "low", "close", "volume"]]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df
