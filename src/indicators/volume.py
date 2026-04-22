"""Volume indicator — MA ratio and spike detection."""
import pandas as pd


def volume_ma(volume: pd.Series, length: int = 20) -> pd.Series:
    """
    Rolling volume moving average (simple MA).

    Parameters
    ----------
    volume : pd.Series
    length : int

    Returns
    -------
    pd.Series
    """
    return volume.rolling(window=length, min_periods=length).mean()


def volume_ratio(volume: pd.Series, ma_length: int = 20) -> pd.Series:
    """
    Current volume / rolling mean volume.

    Values > 1.0 indicate above-average volume.
    Values > 1.2 indicate significantly elevated volume (confirmation threshold).

    Parameters
    ----------
    volume : pd.Series
    ma_length : int

    Returns
    -------
    pd.Series
        Volume ratio; first <ma_length> candles are NaN.
    """
    if ma_length < 1:
        raise ValueError(f"ma_length must be >= 1, got {ma_length}")

    ma = volume_ma(volume, ma_length)
    return volume / ma