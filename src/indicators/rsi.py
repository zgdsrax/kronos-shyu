"""RSI indicator with Wilder's smoothing."""
import pandas as pd
import numpy as np


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """
    Relative Strength Index using Wilder's smoothing.

    Wilder's smoothing: EMA with alpha = 1/length.
    RSI = 100 - (100 / (1 + RS)), where RS = avg_gain / avg_loss.

    Parameters
    ----------
    close : pd.Series
        Closing prices.
    length : int
        RSI lookback period. Default 14 (standard).

    Returns
    -------
    pd.Series
        RSI values in [0, 100]; first <length> candles are NaN.
    """
    if length < 1:
        raise ValueError(f"RSI length must be >= 1, got {length}")

    delta = close.diff()

    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    # First average = simple mean of first `length` values
    avg_gain = gains.iloc[:length].mean()
    avg_loss = losses.iloc[:length].mean()

    result = pd.Series(np.nan, index=close.index, dtype=float)
    result.iloc[length - 1] = 0.0  # placeholder, computed below

    alpha = 1.0 / length

    # Walk forward with Wilder smoothing
    for i in range(length, len(close)):
        avg_gain = (avg_gain * (length - 1) + gains.iloc[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses.iloc[i]) / length

        if avg_loss == 0:
            rsi_val = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100.0 - (100.0 / (1.0 + rs))

        result.iloc[i] = rsi_val

    return result