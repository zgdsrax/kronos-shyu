#!/usr/bin/env python3
"""
run_backtest.py — Run a backtest from the command line.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --symbols BTC ETH
    python scripts/run_backtest.py --config config/settings.yaml
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.loader import load_config
from src.data.fetcher import HyperliquidFetcher
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import compute_metrics


def main():
    parser = argparse.ArgumentParser(description="Run Kronos backtest")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Override symbols from config",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    symbols = args.symbols or config.symbols

    print(f"Running backtest for: {symbols}")
    print(f"Config: {args.config}")
    print()

    fetcher = HyperliquidFetcher(
        symbols=symbols,
        timeframe=config.timeframe,
        lookback=500,
    )
    engine = BacktestEngine(config)

    for symbol in symbols:
        frame = fetcher.fetch(symbol)
        if frame is None:
            print(f"[{symbol}] No data — skipping")
            continue

        df = frame.to_dataframe()
        print(f"[{symbol}] {len(df)} candles loaded")

        trades = engine.run(symbol, df)
        m = compute_metrics(trades)

        print(f"\n{'─' * 50}")
        print(f"[{symbol}] backtest results")
        if "error" in m:
            print(f"  {m['error']}")
        else:
            for key, label in [
                ("total_trades", "Trades"),
                ("win_rate", "Win Rate"),
                ("avg_rr", "Avg R:R"),
                ("profit_factor", "Profit Factor"),
                ("max_drawdown_pct", "Max DD"),
                ("sharpe_ratio", "Sharpe"),
                ("sortino_ratio", "Sortino"),
                ("expectancy_pct", "Expectancy"),
                ("total_return_pct", "Total Return"),
            ]:
                val = m.get(key)
                if isinstance(val, float):
                    if key in ("win_rate", "max_drawdown_pct", "expectancy_pct", "total_return_pct"):
                        print(f"  {label:<18} {val:+.2%}")
                    else:
                        print(f"  {label:<18} {val:.4f}")
                elif isinstance(val, int):
                    print(f"  {label:<18} {val}")


if __name__ == "__main__":
    main()