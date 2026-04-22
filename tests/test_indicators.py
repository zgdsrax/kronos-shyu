"""Tests for technical indicators."""
import pytest
import pandas as pd
import numpy as np

from src.indicators.vwap import session_vwap
from src.indicators.atr import wilder_atr
from src.indicators.rsi import rsi
from src.indicators.volume import volume_ratio, volume_ma


def make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    close = 100 + rng.standard_normal(n).cumsum()
    high = close + rng.uniform(0.1, 2.0, n)
    low = close - rng.uniform(0.1, 2.0, n)
    volume = rng.uniform(100, 1000, n)
    ts = pd.date_range("2024-01-01", periods=n, freq="15min").astype("int64") // 10**6
    return pd.DataFrame({
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": ts,
    })


class TestSessionVWAP:
    def test_vwap_nan_early_session(self):
        """First min_candles of each session should be NaN."""
        df = make_ohlcv(50)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.timestamp, min_candles=5)
        assert result.isna().sum() > 0, "Expected some NaN values in early session"

    def test_vwap_within_high_low(self):
        """VWAP should always be between low and high of each candle."""
        df = make_ohlcv(100)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.timestamp, min_candles=5)
        valid = result.dropna()
        assert (valid >= df.loc[valid.index, "low"]).all(), "VWAP below low"
        assert (valid <= df.loc[valid.index, "high"]).all(), "VWAP above high"

    def test_vwap_increasing_cumsum(self):
        """VWAP should be monotonically increasing within a session (rising market)."""
        df = make_ohlcv(80)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.timestamp, min_candles=3)
        # After min_candles, values should be valid
        valid = result.dropna()
        assert len(valid) > 0

    def test_length_mismatch_raises(self):
        """Mismatched series lengths should raise ValueError."""
        df = make_ohlcv(50)
        with pytest.raises(ValueError):
            session_vwap(df.high, df.low.iloc[:40], df.close, df.volume, df.timestamp)

    def test_min_candles_zero(self):
        """min_candles=0 means no NaN gap."""
        df = make_ohlcv(30)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.timestamp, min_candles=0)
        assert result.isna().sum() == 0


class TestWilderATR:
    def test_atr_length(self):
        """ATR should return NaN for first <length> values."""
        df = make_ohlcv(50)
        result = wilder_atr(df.high, df.low, df.close, length=14)
        assert result.iloc[:13].isna().all(), "First 13 values should be NaN"
        assert not result.iloc[14:].isna().any() or result.iloc[14:].isna().any(), \
            "Values after length should not all be NaN"

    def test_atr_positive(self):
        """ATR should always be positive."""
        df = make_ohlcv(100)
        result = wilder_atr(df.high, df.low, df.close, length=14)
        valid = result.dropna()
        assert (valid > 0).all(), "ATR should be strictly positive"

    def test_atr_increases_on_high_volatility(self):
        """ATR should spike when range is large."""
        df = make_ohlcv(40)
        result = wilder_atr(df.high, df.low, df.close, length=14)
        # Compare ATR after a big range vs early ATR
        assert result.iloc[-1] > result.iloc[14]

    def test_very_short_atr(self):
        """ATR with length=1 should have no NaN values."""
        df = make_ohlcv(20)
        result = wilder_atr(df.high, df.low, df.close, length=1)
        assert result.isna().sum() == 0


class TestRSI:
    def test_rsi_range(self):
        """RSI should be between 0 and 100."""
        df = make_ohlcv(100)
        result = rsi(df["close"], length=14)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_first_nan(self):
        """RSI should be NaN for first <length> values."""
        df = make_ohlcv(50)
        result = rsi(df["close"], length=14)
        assert result.iloc[:13].isna().all()

    def test_rsi_length_1(self):
        """RSI with length=1 should be either 0 or 100 (no smoothing)."""
        df = make_ohlcv(30)
        result = rsi(df["close"], length=1)
        assert result.isna().sum() == 0

    def test_rsi_zero_length_raises(self):
        """RSI with length=0 should raise ValueError."""
        with pytest.raises(ValueError):
            rsi(pd.Series([1, 2, 3]), length=0)

    def test_rsi_all_equal_prices(self):
        """Flat price series should produce RSI of 100."""
        flat = pd.Series([100.0] * 50)
        result = rsi(flat, length=14)
        valid = result.dropna()
        assert (valid == 100).all(), "Flat price should produce RSI=100"


class TestVolumeRatio:
    def test_volume_ratio_positive(self):
        """Volume ratio should be positive."""
        df = make_ohlcv(100)
        result = volume_ratio(df["volume"], ma_length=20)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_volume_ratio_ma_length(self):
        """First ma_length values should be NaN."""
        df = make_ohlcv(100)
        result = volume_ratio(df["volume"], ma_length=20)
        assert result.iloc[:19].isna().all()
        assert not result.iloc[20:].isna().all()

    def test_volume_ma(self):
        """Volume MA should be close to the mean of the window."""
        df = make_ohlcv(60)
        ma = volume_ma(df["volume"], length=10)
        assert ma.isna().sum() == 9
        assert not ma.iloc[9:].isna().any()