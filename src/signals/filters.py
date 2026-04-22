"""Entry condition filters for long and short signals."""
from typing import Tuple

from config.loader import Config


def check_long_entry(
    close: float,
    rsi: float,
    vwap: float,
    volume_ratio: float,
    config: Config,
) -> Tuple[bool, str]:
    """
    Evaluate whether a LONG entry is justified.

    All conditions are AND-gated — every one must pass.

    Parameters
    ----------
    close : float
        Current closing price.
    rsi : float
        Current RSI value.
    vwap : float
        Current session VWAP value (may be NaN).
    volume_ratio : float
        Current volume / volume MA ratio.
    config : Config
        Full configuration object.

    Returns
    -------
    (can_enter: bool, rejection_reason: str)
        Empty string for rejection_reason means pass.
    """
    flt = config.filters.long

    if not (flt.rsi_min <= rsi <= flt.rsi_max):
        return False, f"RSI {rsi:.1f} not in long range [{flt.rsi_min}, {flt.rsi_max}]"

    if flt.require_price_above_vwap:
        if close <= vwap:
            return False, f"price {close:.4f} below/equal VWAP {vwap:.4f}"

    if volume_ratio < flt.volume_ratio_min:
        return False, f"volume ratio {volume_ratio:.2f} below minimum {flt.volume_ratio_min}"

    return True, ""


def check_short_entry(
    close: float,
    rsi: float,
    vwap: float,
    volume_ratio: float,
    config: Config,
) -> Tuple[bool, str]:
    """
    Evaluate whether a SHORT entry is justified.

    All conditions are AND-gated — every one must pass.

    Parameters
    ----------
    close : float
        Current closing price.
    rsi : float
        Current RSI value.
    vwap : float
        Current session VWAP value (may be NaN).
    volume_ratio : float
        Current volume / volume MA ratio.
    config : Config
        Full configuration object.

    Returns
    -------
    (can_enter: bool, rejection_reason: str)
        Empty string for rejection_reason means pass.
    """
    flt = config.filters.short

    if not (flt.rsi_min <= rsi <= flt.rsi_max):
        return False, f"RSI {rsi:.1f} not in short range [{flt.rsi_min}, {flt.rsi_max}]"

    if flt.require_price_below_vwap:
        if close >= vwap:
            return False, f"price {close:.4f} above/equal VWAP {vwap:.4f}"

    if volume_ratio < flt.volume_ratio_min:
        return False, f"volume ratio {volume_ratio:.2f} below minimum {flt.volume_ratio_min}"

    return True, ""