"""
執行 S3 組合策略回測。

使用方式：
    python scripts/run_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.engine import BacktestEngine, BacktestConfig
from src.data.fetcher import USMarketFetcher, TWMarketFetcher
from src.data.normalizer import DataNormalizer


def main():
    config = BacktestConfig(
        symbol="0050",
        start_date="2015-01-01",
        end_date="2024-12-31",
        initial_capital=1_000_000,
        nasdaq_threshold=1.5,
        stop_loss_pct=0.12,
        trailing_stop_pct=0.15,
    )

    print(f"Running backtest: {config.symbol} {config.start_date} ~ {config.end_date}")

    fetcher = USMarketFetcher()
    tw_fetcher = TWMarketFetcher()
    norm = DataNormalizer()

    print("Fetching US market data...")
    nasdaq = norm.calculate_change_pct(norm.normalize_ohlcv(fetcher.get_historical("nasdaq", period="10y")))
    sp500 = norm.calculate_change_pct(norm.normalize_ohlcv(fetcher.get_historical("sp500", period="10y")))
    sox = norm.calculate_change_pct(norm.normalize_ohlcv(fetcher.get_historical("sox", period="10y")))
    us_signals = norm.merge_us_signals(nasdaq, sp500, sox)

    print("Fetching TW market data...")
    tw_prices = norm.normalize_ohlcv(tw_fetcher.get_historical("0050", period="10y"))

    print("Running engine...")
    engine = BacktestEngine(config)
    result = engine.run(tw_prices, us_signals)

    print("\n===== Backtest Results =====")
    print(f"Total Return:       {result.total_return_pct:+.2f}%")
    print(f"Annualized Return:  {result.annualized_return_pct:+.2f}%")
    print(f"Max Drawdown:       {result.max_drawdown_pct:.2f}%")
    print(f"Sharpe Ratio:       {result.sharpe_ratio:.3f}")
    print(f"Win Rate:           {result.win_rate:.1%}")
    print(f"Total Trades:       {result.total_trades}")
    print(f"Profit Factor:      {result.profit_factor:.3f}")


if __name__ == "__main__":
    main()
