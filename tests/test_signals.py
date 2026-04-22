"""Tests for signal layer — filters, composer, Kronos wrapper."""
import pytest
from unittest.mock import MagicMock
import pandas as pd
import numpy as np

from src.signals.filters import check_long_entry, check_short_entry
from src.signals.composer import SignalComposer, TradeSignal, Direction
from src.signals.kronos import KronosResult, KronosPredictor
from config.loader import Config


def make_config() -> Config:
    """Create a test configuration."""
    from config.loader import (
        KronosConfig, IndicatorsConfig, FiltersConfig, LongFilter, ShortFilter,
        RiskConfig, CircuitBreakersConfig, DedupConfig, SchedulerConfig, TelegramConfig,
    )
    return Config(
        symbols=["BTC", "ETH"],
        timeframe="15m",
        lookback_candles=150,
        kronos=KronosConfig(model_id="test", pred_len=4, threshold_pct=0.5, device="cpu"),
        indicators=IndicatorsConfig(rsi_length=14, atr_length=14, volume_ma_length=20, vwap_min_candles=5),
        filters=FiltersConfig(
            long=LongFilter(rsi_min=40, rsi_max=70, require_price_above_vwap=True, volume_ratio_min=1.2),
            short=ShortFilter(rsi_min=30, rsi_max=60, require_price_below_vwap=True, volume_ratio_min=1.2),
        ),
        risk=RiskConfig(
            account_size_usd=10000.0,
            risk_per_trade_pct=0.01,
            max_position_usd=2000.0,
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


class TestFilters:
    def test_long_entry_passes_all_conditions(self):
        """Long entry should pass when all conditions are met."""
        cfg = make_config()
        can_enter, reason = check_long_entry(
            close=105.0,
            rsi=55.0,
            vwap=100.0,
            volume_ratio=1.5,
            config=cfg,
        )
        assert can_enter is True
        assert reason == ""

    def test_long_entry_fails_below_vwap(self):
        """Price below VWAP should reject long entry."""
        cfg = make_config()
        can_enter, reason = check_long_entry(
            close=95.0,
            rsi=55.0,
            vwap=100.0,
            volume_ratio=1.5,
            config=cfg,
        )
        assert can_enter is False
        assert "vwap" in reason.lower()

    def test_long_entry_fails_outside_rsi_range(self):
        """RSI outside [40, 70] should reject long entry."""
        cfg = make_config()
        can_enter, reason = check_long_entry(
            close=105.0,
            rsi=80.0,  # too high
            vwap=100.0,
            volume_ratio=1.5,
            config=cfg,
        )
        assert can_enter is False
        assert "rsi" in reason.lower()

    def test_long_entry_fails_low_volume(self):
        """Volume ratio below minimum should reject long entry."""
        cfg = make_config()
        can_enter, reason = check_long_entry(
            close=105.0,
            rsi=55.0,
            vwap=100.0,
            volume_ratio=0.8,
            config=cfg,
        )
        assert can_enter is False
        assert "volume" in reason.lower()

    def test_short_entry_passes_all_conditions(self):
        """Short entry should pass when all conditions are met."""
        cfg = make_config()
        can_enter, reason = check_short_entry(
            close=95.0,
            rsi=45.0,
            vwap=100.0,
            volume_ratio=1.5,
            config=cfg,
        )
        assert can_enter is True
        assert reason == ""

    def test_short_entry_fails_above_vwap(self):
        """Price above VWAP should reject short entry."""
        cfg = make_config()
        can_enter, reason = check_short_entry(
            close=105.0,
            rsi=45.0,
            vwap=100.0,
            volume_ratio=1.5,
            config=cfg,
        )
        assert can_enter is False
        assert "vwap" in reason.lower()


class TestTradeSignal:
    def test_trade_signal_is_valid(self):
        """Valid signal should have is_valid=True."""
        signal = TradeSignal(
            symbol="BTC",
            direction=Direction.LONG,
            entry_price=100.0,
            sl=98.5,
            tp=104.5,
            position_size_contracts=1.0,
            risk_usd=100.0,
            rr_ratio=2.0,
            rsi=55.0,
            vwap=99.0,
            atr=1.0,
            volume_ratio=1.5,
            kronos_signal="UP",
            kronos_change_pct=1.0,
            timestamp="2024-01-01 00:00:00 UTC",
        )
        assert signal.is_valid() is True

    def test_trade_signal_invalid_zero_sl(self):
        """Zero SL should make signal invalid."""
        signal = TradeSignal(
            symbol="BTC",
            direction=Direction.LONG,
            entry_price=100.0,
            sl=0.0,
            tp=104.5,
            position_size_contracts=1.0,
            risk_usd=100.0,
            rr_ratio=2.0,
            rsi=55.0,
            vwap=99.0,
            atr=1.0,
            volume_ratio=1.5,
            kronos_signal="UP",
            kronos_change_pct=1.0,
            timestamp="2024-01-01 00:00:00 UTC",
        )
        assert signal.is_valid() is False

    def test_trade_signal_invalid_low_rr(self):
        """RR below 1.5 should make signal invalid."""
        signal = TradeSignal(
            symbol="BTC",
            direction=Direction.LONG,
            entry_price=100.0,
            sl=99.0,
            tp=100.5,
            position_size_contracts=1.0,
            risk_usd=50.0,
            rr_ratio=1.0,
            rsi=55.0,
            vwap=99.0,
            atr=1.0,
            volume_ratio=1.5,
            kronos_signal="UP",
            kronos_change_pct=0.5,
            timestamp="2024-01-01 00:00:00 UTC",
        )
        assert signal.is_valid() is False

    def test_trade_signal_frozen(self):
        """TradeSignal should be a frozen dataclass."""
        signal = TradeSignal(
            symbol="BTC",
            direction=Direction.LONG,
            entry_price=100.0,
            sl=98.5,
            tp=104.5,
            position_size_contracts=1.0,
            risk_usd=100.0,
            rr_ratio=2.0,
            rsi=55.0,
            vwap=99.0,
            atr=1.0,
            volume_ratio=1.5,
            kronos_signal="UP",
            kronos_change_pct=1.0,
            timestamp="2024-01-01 00:00:00 UTC",
        )
        with pytest.raises(Exception):  # frozen dataclass
            signal.entry_price = 200.0


class TestSignalComposer:
    def test_compose_returns_none_for_insufficient_data(self):
        """Composer should return None when df has fewer than 50 candles."""
        cfg = make_config()
        composer = SignalComposer(cfg)
        df = pd.DataFrame({"close": [1, 2, 3]})
        mock_kronos = MagicMock()
        result = composer.compose("BTC", df, mock_kronos)
        assert result is None

    def test_compose_returns_none_for_neutral_kronos(self):
        """Neutral Kronos signal should produce None."""
        cfg = make_config()
        composer = SignalComposer(cfg)

        # Create enough rows
        n = 60
        df = pd.DataFrame({
            "open": np.linspace(100, 110, n),
            "high": np.linspace(101, 111, n),
            "low": np.linspace(99, 109, n),
            "close": np.linspace(100, 110, n),
            "volume": np.ones(n) * 1000,
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min").astype("int64") // 10**6,
        })

        mock_kronos = MagicMock()
        mock_kronos.predict.return_value = KronosResult(
            signal="NEUTRAL",
            predicted_close=110.0,
            change_pct=0.1,
            confidence=0.1,
        )

        result = composer.compose("BTC", df, mock_kronos)
        assert result is None

    def test_compose_creates_valid_signal(self):
        """Valid UP signal should produce a valid TradeSignal."""
        cfg = make_config()
        composer = SignalComposer(cfg)

        n = 80
        df = pd.DataFrame({
            "open": np.linspace(100, 110, n),
            "high": np.linspace(101, 111, n),
            "low": np.linspace(99, 109, n),
            "close": np.linspace(100, 110, n),
            "volume": np.ones(n) * 1000,
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min").astype("int64") // 10**6,
        })

        mock_kronos = MagicMock()
        mock_kronos.predict.return_value = KronosResult(
            signal="UP",
            predicted_close=115.0,
            change_pct=1.5,
            confidence=1.5,
        )

        result = composer.compose("BTC", df, mock_kronos)
        assert result is not None
        assert isinstance(result, TradeSignal)
        assert result.direction == Direction.LONG
        assert result.sl < result.entry_price < result.tp


class TestKronosResult:
    def test_kronos_result_fields(self):
        """KronosResult should have all required fields."""
        result = KronosResult(
            signal="UP",
            predicted_close=110.0,
            change_pct=1.0,
            confidence=1.0,
        )
        assert result.signal == "UP"
        assert result.predicted_close == 110.0
        assert result.change_pct == 1.0
        assert result.confidence == 1.0

    def test_kronos_result_frozen(self):
        """KronosResult should be a frozen dataclass."""
        result = KronosResult(
            signal="DOWN",
            predicted_close=90.0,
            change_pct=-2.0,
            confidence=2.0,
        )
        with pytest.raises(Exception):
            result.signal = "UP"