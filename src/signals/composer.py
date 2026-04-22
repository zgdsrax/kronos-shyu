"""Signal composer — combines Kronos + technical filters → TradeSignal."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np

from config.loader import Config
from src.indicators import session_vwap, wilder_atr, rsi, volume_ratio
from src.risk.position_sizer import fixed_fraction_size
from src.risk.sl_tp import atr_based_sltp
from .kronos import KronosPredictor, KronosResult
from .filters import check_long_entry, check_short_entry

__all__ = ["SignalComposer", "TradeSignal", "Direction"]


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class TradeSignal:
    """
    Fully-specified trade signal ready for execution / notification.

    All fields are set — SL, TP, position size, RR ratio, and indicator values
    are computed from the configuration.
    """

    symbol: str
    direction: Direction
    entry_price: float
    sl: float
    tp: float
    position_size_contracts: float
    risk_usd: float
    rr_ratio: float
    rsi: float
    vwap: float
    atr: float
    volume_ratio: float
    kronos_signal: str
    kronos_change_pct: float
    timestamp: str

    def is_valid(self) -> bool:
        """Verify the signal passes minimum viability checks."""
        return (
            self.sl > 0
            and self.tp > 0
            and self.rr_ratio >= self._min_rr()
            and self.position_size_contracts > 0
        )

    def _min_rr(self) -> float:
        return 1.5  # hardcoded minimum — controlled by config in composer


class SignalComposer:
    """
    Combines Kronos model prediction + technical indicators → TradeSignal.

    Usage::

        composer = SignalComposer(config)
        signal = composer.compose("BTC", df, kronos_predictor)
        if signal is not None:
            notifier.send_signal(signal)
    """

    def __init__(self, config: Config):
        self.config = config

    def compose(
        self,
        symbol: str,
        df: np.ndarray,
        kronos: KronosPredictor,
    ) -> Optional[TradeSignal]:
        """
        Build a TradeSignal for the given symbol if all conditions are met.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "BTC").
        df : pd.DataFrame
            OHLCV DataFrame with columns: open, high, low, close, volume, timestamp.
        kronos : KronosPredictor
            Loaded singleton predictor.

        Returns
        -------
        TradeSignal or None if conditions not met.
        """
        if len(df) < 50:
            return None

        # ── Compute indicators ────────────────────────────────────────────
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        timestamps = df["timestamp"]

        vwap_vals = session_vwap(
            high, low, close, volume, timestamps,
            min_candles=self.config.indicators.vwap_min_candles,
        )
        atr_vals = wilder_atr(high, low, close, self.config.indicators.atr_length)
        rsi_vals = rsi(close, self.config.indicators.rsi_length)
        vol_ratio_vals = volume_ratio(volume, self.config.indicators.volume_ma_length)

        # Use the most recent candle's values
        vwap = float(vwap_vals.iloc[-1])
        atr = float(atr_vals.iloc[-1])
        rsi_val = float(rsi_vals.iloc[-1])
        vol_ratio = float(vol_ratio_vals.iloc[-1])
        close_price = float(close.iloc[-1])

        # ── Kronos prediction ─────────────────────────────────────────────
        kronos_result: KronosResult = kronos.predict(df)

        # ── Entry filter ──────────────────────────────────────────────────
        if kronos_result.signal == "UP":
            can_enter, reason = check_long_entry(
                close_price, rsi_val, vwap, vol_ratio, self.config,
            )
            direction = Direction.LONG
        elif kronos_result.signal == "DOWN":
            can_enter, reason = check_short_entry(
                close_price, rsi_val, vwap, vol_ratio, self.config,
            )
            direction = Direction.SHORT
        else:
            return None

        if not can_enter:
            return None

        # ── SL / TP ────────────────────────────────────────────────────────
        try:
            sltp = atr_based_sltp(
                direction=direction.value,
                entry=close_price,
                atr=atr,
                sl_mult=self.config.risk.sl_atr_mult,
                tp_mult=self.config.risk.tp_atr_mult,
                min_rr=self.config.risk.min_rr_ratio,
            )
        except ValueError as exc:
            return None

        # ── Position sizing ────────────────────────────────────────────────
        sizing = fixed_fraction_size(
            account_size=self.config.risk.account_size_usd,
            risk_pct=self.config.risk.risk_per_trade_pct,
            entry=close_price,
            sl=sltp.sl,
            max_position_usd=self.config.risk.max_position_usd,
        )

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            entry_price=round(close_price, 6),
            sl=round(sltp.sl, 6),
            tp=round(sltp.tp, 6),
            position_size_contracts=sizing.position_size_contracts,
            risk_usd=sizing.risk_usd,
            rr_ratio=sltp.rr_ratio,
            rsi=round(rsi_val, 2),
            vwap=round(vwap, 6),
            atr=round(atr, 6),
            volume_ratio=round(vol_ratio, 3),
            kronos_signal=kronos_result.signal,
            kronos_change_pct=round(kronos_result.change_pct, 4),
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        )