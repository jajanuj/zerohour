import pandas as pd
import numpy as np
from typing import Optional


class PerformanceMetrics:
    """回測績效指標計算。"""

    def __init__(self, equity_curve: pd.Series, initial_capital: float):
        self.equity = equity_curve.dropna()
        self.initial = initial_capital

    @property
    def total_return_pct(self) -> float:
        if self.equity.empty:
            return 0.0
        return float((self.equity.iloc[-1] / self.initial - 1) * 100)

    @property
    def annualized_return_pct(self) -> float:
        if len(self.equity) < 2:
            return 0.0
        n_years = len(self.equity) / 252
        if n_years <= 0:
            return 0.0
        total = self.equity.iloc[-1] / self.initial
        return float((total ** (1 / n_years) - 1) * 100)

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity.empty:
            return 0.0
        rolling_max = self.equity.cummax()
        drawdown = (self.equity - rolling_max) / rolling_max * 100
        return float(drawdown.min())

    @property
    def sharpe_ratio(self) -> float:
        if len(self.equity) < 2:
            return 0.0
        returns = self.equity.pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        return float(returns.mean() / returns.std() * np.sqrt(252))

    @property
    def volatility_pct(self) -> float:
        if len(self.equity) < 2:
            return 0.0
        returns = self.equity.pct_change().dropna()
        return float(returns.std() * np.sqrt(252) * 100)

    def win_rate(self, trade_log: list[dict]) -> float:
        sells = [t for t in trade_log if t.get("action") == "SELL" and "pnl" in t]
        if not sells:
            return 0.0
        wins = [t for t in sells if t["pnl"] > 0]
        return len(wins) / len(sells)

    def profit_factor(self, trade_log: list[dict]) -> float:
        sells = [t for t in trade_log if t.get("action") == "SELL" and "pnl" in t]
        gross_profit = sum(t["pnl"] for t in sells if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in sells if t["pnl"] < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return round(gross_profit / gross_loss, 4)

    def to_dict(self, trade_log: Optional[list[dict]] = None) -> dict:
        trade_log = trade_log or []
        return {
            "total_return_pct": round(self.total_return_pct, 2),
            "annualized_return_pct": round(self.annualized_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "volatility_pct": round(self.volatility_pct, 2),
            "win_rate": round(self.win_rate(trade_log), 4),
            "profit_factor": round(self.profit_factor(trade_log), 4),
        }
