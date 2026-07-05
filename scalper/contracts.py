"""
股期標的流動性掃描（scalper-spec.md §5，Phase 0 任務 0-4）。

量能排行可離線執行（用歷史 K 棒加總量）；價差/五檔深度排行需在盤中即時取樣——
Shioaji 無法回溯歷史 Level-2 五檔資料，只能在有連線的當下取樣。

⚠️ 方法名與參數（api.kbars、bidask 欄位名）以 Shioaji 官方文件為準，尚未在真實環境驗證。
scan_volume_ranking / export_ranking_csv 是純資料處理，不依賴 shioaji 套件本身
（用 duck-typing 接受任何有 .code 屬性的合約物件與有 kbars() 方法的 api），可離線單元測試。
"""

import csv
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MIN_STOCK_PRICE_FOR_500_TICK = 1000.0  # 股價>1000 的小型股期，1 tick(5元)=500元/口


@dataclass
class ContractLiquidityStats:
    symbol: str
    avg_daily_volume: float
    sample_spread_ticks: Optional[float] = None
    sample_depth_qty: Optional[float] = None


def scan_volume_ranking(api, contracts: list, lookback_days: int = 30) -> list[ContractLiquidityStats]:
    """離線可執行：抓近 N 個交易日的 kbars 加總量，依日均量排序（高到低）。"""
    results: list[ContractLiquidityStats] = []
    end = datetime.now()
    start = end - timedelta(days=lookback_days)

    for contract in contracts:
        try:
            kbars = api.kbars(contract, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
            volumes = list(getattr(kbars, "Volume", []))
            if not volumes:
                continue
            avg_vol = sum(volumes) / max(1, len(volumes))
            results.append(ContractLiquidityStats(symbol=contract.code, avg_daily_volume=avg_vol))
        except Exception as e:
            logger.warning("拉取 %s kbars 失敗: %s", getattr(contract, "code", contract), e)

    return sorted(results, key=lambda r: r.avg_daily_volume, reverse=True)


def sample_depth_live(api, contract, sample_seconds: int = 60) -> ContractLiquidityStats:
    """
    盤中即時取樣（必須在交易時段執行）：訂閱五檔 sample_seconds 秒，
    計算平均價差（絕對價格差）與平均五檔合計深度。
    """
    import shioaji as sj  # 延後 import，離線的 scan_volume_ranking/export_ranking_csv 不受影響

    samples: list[dict] = []

    def _on_bidask(exchange, bidask):
        best_bid = bidask.bid_price[0] if bidask.bid_price else None
        best_ask = bidask.ask_price[0] if bidask.ask_price else None
        if best_bid and best_ask:
            samples.append({
                "spread": best_ask - best_bid,
                "depth": sum(bidask.bid_volume) + sum(bidask.ask_volume),
            })

    api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.BidAsk, version=sj.constant.QuoteVersion.v1)
    api.on_bidask_fop_v1()(_on_bidask)

    time.sleep(sample_seconds)

    if not samples:
        return ContractLiquidityStats(symbol=contract.code, avg_daily_volume=0.0)

    avg_spread = sum(s["spread"] for s in samples) / len(samples)
    avg_depth = sum(s["depth"] for s in samples) / len(samples)
    return ContractLiquidityStats(
        symbol=contract.code,
        avg_daily_volume=0.0,
        sample_spread_ticks=avg_spread,
        sample_depth_qty=avg_depth,
    )


def export_ranking_csv(stats: list[ContractLiquidityStats], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "avg_daily_volume", "sample_spread_ticks", "sample_depth_qty"])
        writer.writeheader()
        for s in stats:
            writer.writerow(asdict(s))
    return out_path
