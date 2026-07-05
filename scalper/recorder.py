"""
TickRecorder：盤中逐筆成交 + 五檔掛單落地本地 SQLite，一天一檔（scalper-spec.md §6）。
落地資料只在本地，禁止進 Supabase／git（§2 硬性邊界、§13 禁止事項 7）。
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

DEFAULT_DATA_DIR = Path(__file__).parent / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    side TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS depth (
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    bid_qty_total INTEGER NOT NULL,
    ask_qty_total INTEGER NOT NULL,
    best_bid_qty INTEGER NOT NULL,
    best_ask_qty INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts);
CREATE INDEX IF NOT EXISTS idx_depth_ts ON depth(ts);
"""


class TickRecorder:
    def __init__(self, trading_date: Optional[date] = None, data_dir: Optional[Path] = None):
        self.trading_date = trading_date or date.today()
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / f"ticks_{self.trading_date.strftime('%Y%m%d')}.db"
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record_tick(self, ts: datetime, symbol: str, price: float, qty: int, side: str) -> None:
        self._conn.execute(
            "INSERT INTO ticks (ts, symbol, price, qty, side) VALUES (?, ?, ?, ?, ?)",
            (ts.isoformat(), symbol, price, qty, side),
        )

    def record_depth(
        self, ts: datetime, symbol: str, bid_qty_total: int, ask_qty_total: int,
        best_bid_qty: int, best_ask_qty: int,
    ) -> None:
        self._conn.execute(
            "INSERT INTO depth (ts, symbol, bid_qty_total, ask_qty_total, best_bid_qty, best_ask_qty) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts.isoformat(), symbol, bid_qty_total, ask_qty_total, best_bid_qty, best_ask_qty),
        )

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    def validate(self) -> dict:
        """完整性檢查（scalper-spec.md §6 驗收）：時間戳單調、無 NaN 價格、最大空窗秒數。"""
        cur = self._conn.execute("SELECT ts, price FROM ticks ORDER BY ts")
        rows = cur.fetchall()

        n = len(rows)
        max_gap_seconds = 0.0
        monotonic = True
        nan_count = 0
        prev_ts: Optional[datetime] = None

        for ts_str, price in rows:
            ts = datetime.fromisoformat(ts_str)
            if price != price:  # NaN != NaN，避免多引一個 math import
                nan_count += 1
            if prev_ts is not None:
                if ts < prev_ts:
                    monotonic = False
                gap = (ts - prev_ts).total_seconds()
                max_gap_seconds = max(max_gap_seconds, gap)
            prev_ts = ts

        return {
            "n_ticks": n,
            "monotonic": monotonic,
            "nan_price_count": nan_count,
            "max_gap_seconds": max_gap_seconds,
        }
