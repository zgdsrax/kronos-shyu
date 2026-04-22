"""Session-reset VWAP indicator."""
import pandas as pd
import numpy as np


def session_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    timestamps: pd.Series,
    min_candles: int = 5,
) -> pd.Series:
    """
    VWAP with per-UTC-day session reset.

    Each UTC day is treated as an independent session. VWAP accumulates
    from the first candle of the session. NaN is returned for the first
    <min_candles> of each session (so the indicator isn't trusted too early).

    Parameters
    ----------
    high, low, close, volume : pd.Series
        OHLCV data, aligned index.
    timestamps : pd.Series
        Unix-millisecond timestamps aligned with the other series.
    min_candles : int
        Number of candles at session start to mark NaN.

    Returns
    -------
    pd.Series (same length as input)
        VWAP values; NaN for untrusted candles.
    """
    if not (len(high) == len(low) == len(close) == len(volume) == len(timestamps)):
        raise ValueError("All input series must have the same length")

    typical_price = (high + low + close) / 3.0
    dates = pd.to_datetime(timestamps, unit="ms", utc=True).dt.date

    result = pd.Series(np.nan, index=close.index, dtype=float)

    for date, grp in close.groupby(dates, sort=False):
        idx = grp.index
        tp = typical_price.loc[idx].values
        vol = volume.loc[idx].values

        cumsum_pv = np.cumsum(tp * vol)
        cumsum_v = np.cumsum(vol)

        with np.errstate(divide="ignore", invalid="ignore"):
            session_vwap_vals = cumsum_pv / cumsum_v

        # Mark first min_candles as NaN
        if min_candles > 0 and len(session_vwap_vals) > min_candles:
            session_vwap_vals[:min_candles] = np.nan

        result.loc[idx] = session_vwap_vals

    return result