"""Fixed-fraction position sizing."""
from dataclasses import dataclass


@dataclass
class SizingResult:
    """
    Result of position size calculation.

    Attributes
    ----------
    position_size_contracts : float
        Number of contracts to trade.
    risk_usd : float
        Actual USD amount at risk (may be less than ideal if capped).
    is_capped : bool
        True if max_position_usd hard cap was applied.
    """

    position_size_contracts: float
    risk_usd: float
    is_capped: bool


def fixed_fraction_size(
    account_size: float,
    risk_pct: float,
    entry: float,
    sl: float,
    max_position_usd: float,
) -> SizingResult:
    """
    Fixed-fraction position sizing.

    Computes the number of contracts such that if the stop-loss is hit,
    the loss equals account_size * risk_pct (or the hard cap if smaller).

    Formula::

        risk_usd         = account_size * risk_pct
        risk_per_contract = |entry - sl|
        raw_size         = risk_usd / risk_per_contract

    If raw_size * entry > max_position_usd, cap to max_position_usd / entry.

    Parameters
    ----------
    account_size : float
        Total account size in USD.
    risk_pct : float
        Fraction of account to risk per trade (e.g. 0.01 for 1%).
    entry : float
        Entry price per contract.
    sl : float
        Stop-loss price.
    max_position_usd : float
        Hard maximum position size in USD (prevents over-concentration).

    Returns
    -------
    SizingResult

    Raises
    ------
    ValueError
        If sl is too close to entry (division by near-zero).
    """
    risk_per_contract = abs(entry - sl)
    if risk_per_contract < 1e-8:
        raise ValueError(
            f"SL {sl} too close to entry {entry} — risk_per_contract={risk_per_contract:.2e}"
        )

    risk_usd = account_size * risk_pct
    raw_size = risk_usd / risk_per_contract

    notional = raw_size * entry
    is_capped = notional > max_position_usd
    if is_capped:
        raw_size = max_position_usd / entry

    return SizingResult(
        position_size_contracts=round(raw_size, 4),
        risk_usd=round(risk_per_contract * raw_size, 2),
        is_capped=is_capped,
    )