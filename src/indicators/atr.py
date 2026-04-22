"""ATR indicator with Wilder's smoothing (not simple rolling mean)."""
import pandas as pd
import numpy as np


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """
    Average True Range using Wilder's smoothing.

    Wilder's smoothing uses an exponential moving average with alpha = 1/length.
    This is equivalent to: ATR[t] = (ATR[t-1] * (length-1) + TR[t]) / length
    which matches TradingView and institutional platforms.

    Parameters
    ----------
    high, low, close : pd.Series
        OHLC data, aligned index.
    length : int
        ATR lookback period. Default 14 (standard).

    Returns
    -------
    pd.Series
        ATR values; first <length> candles will be NaN.
    """
    if len(high) != len(low) or len(high) != len(close):
        raise ValueError("All OHLC series must have the same length")

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # First ATR = simple SMA of first `length` TR values
    first_atr = tr.iloc[:length].mean()

    # Wilder smoothing: EMA with alpha = 1/length
    alpha = 1.0 / length
    atr = pd.Series(np.nan, index=close.index, dtype=float)
    atr.iloc[length - 1] = first_atr

    for i in range(length, len(atr)):
        atr.iloc[i] = (atr.iloc[i - 1] * (length - 1) + tr.iloc[i]) / length

    return atr