"""Tests for backtest engine and metrics."""
import pytest
import pandas as pd
import numpy as np

from src.backtest.engine import BacktestEngine, TradeRecord
from src.backtest.metrics import compute_metrics
from config.loader import Config


def make_config() -> Config:
    """Create a test configuration."""
    from config.loader import (
        KronosConfig, IndicatorsConfig, FiltersConfig, LongFilter, ShortFilter,
        RiskConfig, CircuitBreakersConfig, DedupConfig, SchedulerConfig, TelegramConfig,
    )
    return Config(
        symbols=["BTC"],
        timeframe="15m",
        lookback_candles=150,
        kronos=KronosConfig(model_id="test", pred_len=4, threshold_pct=0.5, device="cpu"),
        indicators=IndicatorsConfig(
            rsi_length=14,
            atr_length=14,
            volume_ma_length=20,
            vwap_min_candles=5,
        ),
        filters=FiltersConfig(
            long=LongFilter(rsi_min=40, rsi_max=70, require_price_above_vwap=True, volume_ratio_min=1.0),
            short=ShortFilter(rsi_min=30, rsi_max=60, require_price_below_vwap=True, volume_ratio_min=1.0),
        ),
        risk=RiskConfig(
            account_size_usd=10_000.0,
            risk_per_trade_pct=0.01,
            max_position_usd=2_000.0,
            sl_atr_mult=1.5,
            tp_atr_mult=3.0,
            min_rr_ratio=1.5,
        ),
        circuit_breakers=CircuitBreakersConfig(
            max_daily_loss_pct=0.03,
            max_consecutive_losses=4,
            cooldown_minutes=120,
        ),
        dedup=DedupConfig(cooldown_candles=4, price_tolerance_pct=0.005),
        scheduler=SchedulerConfig(cycle_seconds=900, symbol_delay_seconds=2),
        telegram=TelegramConfig(),
    )


def make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with trend."""
    rng = np.random.default_rng(seed)
    close = 100 + rng.standard_normal(n).cumsum() * 0.5
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    volume = rng.uniform(500, 1500, n)
    ts = pd.date_range("2024-01-01", periods=n, freq="15min").astype("int64") // 10**6
    return pd.DataFrame({
        "open": close - rng.uniform(0.05, 0.2, n),
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": ts,
    })


class TestBacktestEngine:
    def test_engine_empty_df(self):
        """Engine should return empty list for df with < min_candles."""
        cfg = make_config()
        engine = BacktestEngine(cfg)
        df = make_ohlcv(n=30)
        result = engine.run("BTC", df)
        assert result == []

    def test_engine_returns_trade_records(self):
        """Engine should return a list of TradeRecord objects."""
        cfg = make_config()
        engine = BacktestEngine(cfg)
        df = make_ohlcv(n=200, seed=99)
        result = engine.run("BTC", df)
        assert isinstance(result, list)
        for t in result:
            assert isinstance(t, TradeRecord)
            assert t.symbol == "BTC"

    def test_engine_trade_fields(self):
        """TradeRecords should have all required fields populated."""
        cfg = make_config()
        engine = BacktestEngine(cfg)
        df = make_ohlcv(n=200, seed=7)
        result = engine.run("BTC", df)
        if result:
            t = result[0]
            assert t.direction in ("LONG", "SHORT")
            assert t.entry_price > 0
            assert t.sl > 0
            assert t.tp > 0
            assert t.entry_candle >= 50

    def test_engine_no_look_ahead(self):
        """All trades should have entry_candle < exit_candle."""
        cfg = make_config()
        engine = BacktestEngine(cfg)
        df = make_ohlcv(n=200, seed=13)
        result = engine.run("BTC", df)
        for t in result:
            if t.exit_candle is not None:
                assert t.entry_candle < t.exit_candle, \
                    f"exit_candle {t.exit_candle} <= entry_candle {t.entry_candle}"

    def test_engine_results_list(self):
        """Multiple runs should return independent lists."""
        cfg = make_config()
        engine = BacktestEngine(cfg)
        df = make_ohlcv(n=200)
        r1 = engine.run("BTC", df)
        r2 = engine.run("BTC", df)
        assert r1 is not r2


class TestComputeMetrics:
    def test_compute_metrics_empty(self):
        """Empty trade list should return error."""
        result = compute_metrics([])
        assert "error" in result

    def test_compute_metrics_all_wins(self):
        """All winning trades should give win_rate=1.0."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10,
                exit_candle=15, exit_price=102, result="TP",
                pnl_pct=0.02,
            )
            for _ in range(5)
        ]
        m = compute_metrics(trades)
        assert m["total_trades"] == 5
        assert m["win_rate"] == 1.0
        assert m["win_count"] == 5
        assert m["loss_count"] == 0

    def test_compute_metrics_all_losses(self):
        """All losing trades should give win_rate=0.0."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10,
                exit_candle=15, exit_price=97, result="SL",
                pnl_pct=-0.03,
            )
            for _ in range(4)
        ]
        m = compute_metrics(trades)
        assert m["win_rate"] == 0.0
        assert m["loss_count"] == 4

    def test_compute_metrics_winners_and_losers(self):
        """Mixed trades should have positive expectancy for net profitable."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10,
                exit_candle=15, exit_price=103, result="TP",
                pnl_pct=0.03,
            ),  # win +3%
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=20,
                exit_candle=25, exit_price=97, result="SL",
                pnl_pct=-0.03,
            ),  # loss -3%
        ]
        m = compute_metrics(trades)
        assert m["total_trades"] == 2
        assert m["win_rate"] == 0.5
        assert m["expectancy_pct"] == 0.0  # +3% - 3% / 2 = 0

    def test_max_drawdown_mixed(self):
        """Max drawdown should be negative or zero."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10,
                exit_candle=15, exit_price=101, result="TP", pnl_pct=0.01,
            ),
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=102, sl=100, tp=105, entry_candle=20,
                exit_candle=25, exit_price=99, result="SL", pnl_pct=-0.03,
            ),
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=99, sl=97, tp=102, entry_candle=30,
                exit_candle=35, exit_price=101, result="TP", pnl_pct=0.02,
            ),
        ]
        m = compute_metrics(trades)
        assert m["max_drawdown_pct"] <= 0

    def test_sharpe_defined(self):
        """Sharpe ratio should be computed (may be 0 for insufficient data)."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10,
                exit_candle=15, exit_price=101, result="TP", pnl_pct=0.01,
            )
            for _ in range(10)
        ]
        m = compute_metrics(trades)
        assert "sharpe_ratio" in m

    def test_total_return_sum(self):
        """Total return should match the cumulative product of (1 + pnl_pct)."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10 + i * 10,
                exit_candle=15 + i * 10, exit_price=100, result="TP",
                pnl_pct=0.02,
            )
            for i in range(3)
        ]
        m = compute_metrics(trades)
        expected = (1.02 ** 3) - 1
        assert abs(m["total_return_pct"] - expected) < 0.0001

    def test_sortino_defined(self):
        """Sortino ratio should be computed."""
        trades = [
            TradeRecord(
                symbol="BTC", direction="LONG",
                entry_price=100, sl=98, tp=103, entry_candle=10,
                exit_candle=15, exit_price=101, result="TP", pnl_pct=0.01,
            )
            for _ in range(10)
        ]
        m = compute_metrics(trades)
        assert "sortino_ratio" in m


class TestBacktestIntegration:
    def test_backtest_produces_results(self):
        """Full integration test: backtest should run end-to-end without errors."""
        cfg = make_config()
        engine = BacktestEngine(cfg)
        df = make_ohlcv(n=300, seed=999)
        trades = engine.run("BTC", df)
        m = compute_metrics(trades)
        assert isinstance(m, dict)
        assert "total_trades" in m