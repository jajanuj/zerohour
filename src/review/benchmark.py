import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BenchmarkComparator:
    """策略 vs 買入持有 0050 的表現比較。"""

    def compare(
        self,
        strategy_equity_curve: pd.Series,
        benchmark_prices: pd.Series,
        initial_capital: float = 1_000_000,
    ) -> dict:
        """
        Args:
            strategy_equity_curve: 策略淨值曲線（indexed by date）
            benchmark_prices:       0050 收盤價序列（indexed by date）
            initial_capital:        初始資金

        Returns:
            比較報告 dict
        """
        if strategy_equity_curve.empty or benchmark_prices.empty:
            return {"error": "資料不足"}

        strategy_return = float(
            (strategy_equity_curve.iloc[-1] / initial_capital - 1) * 100
        )
        bm_return = float(
            (benchmark_prices.iloc[-1] / benchmark_prices.iloc[0] - 1) * 100
        )
        excess_return = strategy_return - bm_return

        if excess_return > 3:
            verdict = "✅ 策略跑贏基準"
        elif excess_return > 0:
            verdict = "⚠️ 策略接近基準，考量成本後需評估是否值得"
        else:
            verdict = "❌ 策略跑輸基準，須重新檢視策略根本邏輯"

        return {
            "strategy_return_pct": round(strategy_return, 2),
            "benchmark_return_pct": round(bm_return, 2),
            "excess_return_pct": round(excess_return, 2),
            "verdict": verdict,
        }
