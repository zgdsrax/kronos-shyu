"""ATR-based stop-loss and take-profit calculator."""
from dataclasses import dataclass


@dataclass
class SLTP:
    """
    Stop-loss and take-profit levels with RR ratio.

    Attributes
    ----------
    sl : float
        Stop-loss price.
    tp : float
        Take-profit price.
    rr_ratio : float
        Reward-to-risk ratio: |tp - entry| / |entry - sl|
    """

    sl: float
    tp: float
    rr_ratio: float


def atr_based_sltp(
    direction: str,
    entry: float,
    atr: float,
    sl_mult: float = 1.5,
    tp_mult: float = 3.0,
    min_rr: float = 1.5,
) -> SLTP:
    """
    Compute SL and TP based on ATR distance from entry.

    For LONG:  SL = entry - sl_mult * atr
               TP = entry + tp_mult * atr

    For SHORT: SL = entry + sl_mult * atr
               TP = entry - tp_mult * atr

    The RR ratio is validated against min_rr — raises ValueError if violated.

    Parameters
    ----------
    direction : str
        "LONG" or "SHORT".
    entry : float
        Entry price.
    atr : float
        Current ATR value.
    sl_mult : float
        ATR multiplier for stop-loss. Default 1.5.
    tp_mult : float
        ATR multiplier for take-profit. Default 3.0.
    min_rr : float
        Minimum acceptable RR ratio. Raises ValueError if below this.

    Returns
    -------
    SLTP

    Raises
    ------
    ValueError
        If direction is invalid or resulting RR < min_rr.
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be 'LONG' or 'SHORT', got '{direction}'")

    if atr <= 0:
        raise ValueError(f"ATR must be positive, got {atr}")

    if direction == "LONG":
        sl = entry - sl_mult * atr
        tp = entry + tp_mult * atr
    else:
        sl = entry + sl_mult * atr
        tp = entry - tp_mult * atr

    rr = abs(tp - entry) / abs(entry - sl)
    if rr < min_rr:
        raise ValueError(
            f"RR ratio {rr:.4f} below minimum {min_rr} "
            f"(sl_mult={sl_mult}, tp_mult={tp_mult})"
        )

    return SLTP(
        sl=round(sl, 6),
        tp=round(tp, 6),
        rr_ratio=round(rr, 2),
    )