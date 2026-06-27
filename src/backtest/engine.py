import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from ..signals.ma200_filter import MA200Filter
from ..signals.time_diff import TimeDiffSignalGenerator
from ..signals.aggregator import SignalAggregator, FinalAction
from .metrics import PerformanceMetrics


@dataclass
class BacktestConfig:
    symbol: str = "QQQ"
    start_date: str = "2015-01-01"
    end_date: str = "2025-12-31"
    initial_capital: float = 1_000_000
    commission_pct: float = 0.001
    slippage_pct: float = 0.001
    nasdaq_threshold: float = 1.5
    stop_loss_pct: float = 0.12
    trailing_stop_pct: float = 0.15


@dataclass
class BacktestResult:
    config: BacktestConfig
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_factor: float
    equity_curve: pd.Series
    trade_log: list[dict] = field(default_factory=list)


class BacktestEngine:
    """向量化回測引擎（S1/S2/S3 組合策略）。"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.ma200 = MA200Filter()
        self.time_diff_gen = TimeDiffSignalGenerator(
            nasdaq_threshold=config.nasdaq_threshold
        )
        self.aggregator = SignalAggregator(
            index_stop_loss_pct=config.stop_loss_pct,
            trailing_stop_pct=config.trailing_stop_pct,
        )

    def run(
        self,
        price_data: pd.DataFrame,
        us_signal_data: pd.DataFrame,
    ) -> BacktestResult:
        """
        執行回測。

        Args:
            price_data:      含 date/close 的目標標的日線資料
            us_signal_data:  含 date/nasdaq_chg/sp500_chg/sox_chg 的美股資料
        """
        capital = self.config.initial_capital
        position = 0.0
        entry_price = 0.0
        peak_price = 0.0
        equity_curve = []
        trade_log = []

        merged = pd.merge(price_data, us_signal_data, on="date", how="inner")
        merged = merged.sort_values("date").reset_index(drop=True)

        for i in range(len(merged)):
            row = merged.iloc[i]
            current_price = float(row["close"])
            current_date = row["date"]

            if i < 200:
                equity_curve.append(capital + position * current_price)
                continue

            hist_slice = merged.iloc[max(0, i - 250): i + 1][["date", "close"]]

            trend_sig = self.ma200.calculate(hist_slice, self.config.symbol)
            time_sig = self.time_diff_gen.generate(
                nasdaq_change_pct=float(row.get("nasdaq_chg", 0)),
                sp500_change_pct=float(row.get("sp500_chg", 0)),
                sox_change_pct=float(row.get("sox_chg", 0)),
            )
            combined = self.aggregator.aggregate(trend_sig, time_sig)

            # 停損 / 平倉檢查
            if position > 0:
                if current_price > peak_price:
                    peak_price = current_price

                trailing_stop = peak_price * (1 - self.config.trailing_stop_pct)
                fixed_stop = entry_price * (1 - self.config.stop_loss_pct)
                effective_stop = max(trailing_stop, fixed_stop)

                need_exit = (
                    current_price <= effective_stop
                    or combined.final_action == FinalAction.EXIT_ALL
                )

                if need_exit:
                    cost_basis = position * entry_price
                    proceeds = position * current_price * (1 - self.config.commission_pct)
                    pnl = proceeds - cost_basis
                    exit_reason = (
                        "STOP_LOSS" if current_price <= effective_stop else "TREND_EXIT"
                    )
                    trade_log.append({
                        "date": current_date,
                        "action": "SELL",
                        "price": current_price,
                        "pnl": pnl,
                        "pnl_pct": pnl / cost_basis * 100,
                        "reason": exit_reason,
                    })
                    capital += proceeds
                    position = 0.0
                    entry_price = 0.0
                    peak_price = 0.0

            # 進場
            if position == 0 and combined.final_action == FinalAction.BUY:
                total_cost_rate = 1 + self.config.commission_pct + self.config.slippage_pct
                invest_amount = capital * combined.suggested_position_pct
                shares = invest_amount / (current_price * total_cost_rate)
                cost = shares * current_price * total_cost_rate

                if cost <= capital and shares > 0:
                    capital -= cost
                    position = shares
                    entry_price = current_price
                    peak_price = current_price
                    trade_log.append({
                        "date": current_date,
                        "action": "BUY",
                        "price": current_price,
                        "shares": shares,
                        "reason": combined.reason,
                    })

            equity_curve.append(capital + position * current_price)

        eq_index = merged["date"].iloc[len(merged) - len(equity_curve):]
        equity_series = pd.Series(equity_curve, index=eq_index)

        # Filter to requested date range for metric calculation
        active_series = equity_series.copy()
        active_trades = trade_log.copy()

        if self.config.start_date:
            start_ts = pd.Timestamp(self.config.start_date)
            active_series = active_series[active_series.index >= start_ts]
            active_trades = [
                t for t in trade_log
                if pd.Timestamp(str(t.get("date", "1900-01-01"))) >= start_ts
            ]

        if self.config.end_date:
            end_ts = pd.Timestamp(self.config.end_date)
            active_series = active_series[active_series.index <= end_ts]
            active_trades = [
                t for t in active_trades
                if pd.Timestamp(str(t.get("date", "1900-01-01"))) <= end_ts
            ]

        # Reference capital: portfolio value at the start of the requested period
        ref_capital = float(active_series.iloc[0]) if len(active_series) > 0 else self.config.initial_capital

        metrics = PerformanceMetrics(
            active_series if len(active_series) > 0 else equity_series,
            ref_capital,
        )

        return BacktestResult(
            config=self.config,
            total_return_pct=metrics.total_return_pct,
            annualized_return_pct=metrics.annualized_return_pct,
            max_drawdown_pct=metrics.max_drawdown_pct,
            sharpe_ratio=metrics.sharpe_ratio,
            win_rate=metrics.win_rate(active_trades),
            total_trades=len([t for t in active_trades if t["action"] == "SELL"]),
            profit_factor=metrics.profit_factor(active_trades),
            equity_curve=active_series if len(active_series) > 0 else equity_series,
            trade_log=active_trades,
        )
