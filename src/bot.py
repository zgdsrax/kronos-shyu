#!/usr/bin/env python3
"""
Kronos Trading Bot — Main Orchestrator

All business logic lives in submodules. This file only coordinates flow:
    1. Load config + setup logging
    2. Load Kronos model ONCE
    3. Initialize subsystems (fetcher, composer, circuit breaker, tracker, notifier)
    4. Run live cycle loop OR backtest

Usage:
    python src/bot.py                  # live mode
    python src/bot.py --backtest       # backtest mode
    python src/bot.py --config config/settings_prod.yaml
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from logging.handlers import TimedRotatingFileHandler

from config.loader import load_config, Config
from src.data.fetcher import HyperliquidFetcher
from src.signals.kronos import KronosPredictor
from src.signals.composer import SignalComposer
from src.risk.circuit_breaker import CircuitBreaker
from src.state.tracker import SignalTracker
from src.execution.notifier import TelegramNotifier
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import compute_metrics

logger = logging.getLogger("kronos_bot")


def setup_logging(log_config_path: Path | None = None) -> None:
    """Configure logging with file (daily rotate) + console handlers."""
    logger.setLevel(logging.DEBUG)

    # Try to load logging.yaml for structured config, fall back to basic config
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    if log_config_path and log_config_path.exists():
        with open(log_config_path) as f:
            log_cfg = yaml.safe_load(f)
        # Apply via basicConfig would be simpler, but we use dictConfig
        import logging.config
        logging.config.dictConfig(log_cfg)
    else:
        # Fallback basic config
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S UTC",
        )
        fh = TimedRotatingFileHandler(
            "logs/kronos_bot.log",
            when="midnight",
            backupCount=7,
            utc=True,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)

        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

        logging.getLogger("kronos_bot").addHandler(fh)
        logging.getLogger("kronos_bot").addHandler(sh)
        logging.getLogger("kronos_bot").setLevel(logging.DEBUG)


def run_live(config: Config) -> None:
    """Main live trading loop."""
    logger.info("=" * 60)
    logger.info("KRONOS BOT — LIVE MODE")
    logger.info("Symbols: %s | Timeframe: %s", config.symbols, config.timeframe)
    logger.info("=" * 60)

    # ── Load Kronos ONCE ─────────────────────────────────────────────────
    kronos = KronosPredictor(config.kronos)
    kronos.load(config.kronos)

    # ── Initialize subsystems ────────────────────────────────────────────
    fetcher = HyperliquidFetcher(
        symbols=config.symbols,
        timeframe=config.timeframe,
        lookback=config.lookback_candles,
    )
    composer = SignalComposer(config)
    circuit = CircuitBreaker(config.circuit_breakers)
    tracker = SignalTracker(
        cooldown_candles=config.dedup.cooldown_candles,
        price_tolerance_pct=config.dedup.price_tolerance_pct,
    )
    notifier = TelegramNotifier(config)

    logger.info("All subsystems initialized")

    cycle = 0
    while True:
        cycle += 1
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        logger.info("─── Cycle %d @ %s ───", cycle, now_str)

        try:
            frames = fetcher.fetch_all()
        except Exception as exc:
            logger.error("Fetcher error: %s", exc, exc_info=True)
            time.sleep(config.scheduler.cycle_seconds)
            continue

        current_prices: dict[str, float] = {
            sym: float(f.latest_price)
            for sym, f in frames.items()
            if f is not None
        }

        # ── Update open signals (check SL/TP hits) ───────────────────────
        for outcome in tracker.update(current_prices):
            pnl_usd = outcome["pnl_pct"] * config.risk.account_size_usd
            circuit.record_outcome(pnl_usd)
            notifier.send_outcome(outcome)

        # ── Circuit breaker check ─────────────────────────────────────────
        halted, reason = circuit.is_halted(config.risk.account_size_usd)
        if halted:
            logger.warning("🚨 HALTED: %s", reason)
            notifier.send_circuit_breaker_alert(reason)
            time.sleep(config.scheduler.cycle_seconds)
            continue

        # ── Process each symbol ───────────────────────────────────────────
        for symbol, frame in frames.items():
            if frame is None:
                logger.warning("[%s] No data — skipping", symbol)
                continue

            if len(frame.candles) < 50:
                logger.warning("[%s] Only %d candles — skipping", symbol, len(frame.candles))
                continue

            try:
                df = frame.to_dataframe()
                signal = composer.compose(symbol, df, kronos)
            except Exception as exc:
                logger.error("[%s] Compose error: %s", symbol, exc, exc_info=True)
                continue

            if signal is None:
                continue

            if not signal.is_valid():
                logger.warning("[%s] Invalid signal (is_valid=False) — suppressing", symbol)
                continue

            if tracker.is_duplicate(
                symbol, signal.direction.value, signal.entry_price
            ):
                logger.info("[%s] Duplicate signal suppressed", symbol)
                continue

            # ── Send signal to Telegram ──────────────────────────────────
            notifier.send_signal(signal)
            tracker.register(signal)
            logger.info(
                "[%s] ✅ Signal sent: %s @ %.4f  SL=%.4f TP=%.4f  RR=1:%.1f",
                symbol,
                signal.direction.value,
                signal.entry_price,
                signal.sl,
                signal.tp,
                signal.rr_ratio,
            )

            time.sleep(config.scheduler.symbol_delay_seconds)

        logger.info("─── Cycle %d complete ───", cycle)
        time.sleep(config.scheduler.cycle_seconds)


def run_backtest(config: Config) -> None:
    """Run backtest over all configured symbols."""
    logger.info("=" * 60)
    logger.info("KRONOS BOT — BACKTEST MODE")
    logger.info("Symbols: %s | Timeframe: %s", config.symbols, config.timeframe)
    logger.info("=" * 60)

    # Kronos model is loaded but not used for signal generation in backtest
    # (simplified RSI-based signals are used for backtest to avoid model dependency)
    kronos = KronosPredictor(config.kronos)
    try:
        kronos.load(config.kronos)
    except Exception as exc:
        logger.warning("Kronos model not available for backtest: %s", exc)

    fetcher = HyperliquidFetcher(
        symbols=config.symbols,
        timeframe=config.timeframe,
        lookback=500,  # Need more history for backtest
    )
    engine = BacktestEngine(config)

    all_trades = {}
    for symbol in config.symbols:
        logger.info("Backtesting %s...", symbol)

        try:
            frame = fetcher.fetch(symbol)
        except Exception as exc:
            logger.error("[%s] Fetch failed: %s", symbol, exc)
            continue

        if frame is None:
            logger.error("[%s] No data returned — skipping", symbol)
            continue

        df = frame.to_dataframe()
        logger.info("[%s] %d candles loaded", symbol, len(df))

        trades = engine.run(symbol, df)
        all_trades[symbol] = trades

        m = compute_metrics(trades)
        if "error" in m:
            logger.info("[%s] %s", symbol, m["error"])
        else:
            print(f"\n{'─' * 55}")
            print(f"[BACKTEST] {symbol}")
            print(f"  {'Trades:':<22} {m['total_trades']}")
            print(f"  {'Win Rate:':<22} {m['win_rate']:.1%}")
            print(f"  {'Avg Win:':<22} {m['avg_win_pct']:+.2%}")
            print(f"  {'Avg Loss:':<22} {m['avg_loss_pct']:+.2%}")
            print(f"  {'Avg R:R:':<22} {m['avg_rr']:.2f}")
            print(f"  {'Profit Factor:':<22} {m['profit_factor']}")
            print(f"  {'Max Drawdown:':<22} {m['max_drawdown_pct']:+.1%}")
            print(f"  {'Sharpe:':<22} {m['sharpe_ratio']:.2f}")
            print(f"  {'Sortino:':<22} {m['sortino_ratio']:.2f}")
            print(f"  {'Expectancy/trade:':<22} {m['expectancy_pct']:+.3%}")
            print(f"  {'Total Return:':<22} {m['total_return_pct']:+.2%}")

    # Aggregate summary across all symbols
    total = sum(len(t) for t in all_trades.values())
    if total == 0:
        logger.warning("No trades across any symbol — backtest produced no signals")
        return

    print(f"\n{'═' * 55}")
    print(f"[AGGREGATE SUMMARY] ({total} total trades)")
    aggregate_metrics = compute_metrics(
        [t for trades in all_trades.values() for t in trades]
    )
    for key in ["total_trades", "win_rate", "avg_rr", "max_drawdown_pct",
               "sharpe_ratio", "sortino_ratio", "expectancy_pct", "total_return_pct"]:
        if key in aggregate_metrics:
            val = aggregate_metrics[key]
            if isinstance(val, float):
                print(f"  {key:<22} {val:+.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kronos Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run in backtest mode instead of live",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to config YAML file (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--logging-config",
        default="config/logging.yaml",
        help="Path to logging YAML config",
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}")
        sys.exit(1)

    log_cfg_path = Path(args.logging_config) if Path(args.logging_config).exists() else None
    setup_logging(log_cfg_path)

    try:
        config = load_config(cfg_path)
    except Exception as exc:
        logger.critical("Config load failed: %s", exc)
        sys.exit(1)

    logger.info("Config loaded from %s", cfg_path)

    if args.backtest:
        run_backtest(config)
    else:
        try:
            run_live(config)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as exc:
            logger.critical("Fatal error: %s", exc, exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    main()