"""
Walk-forward backtest engine.

No look-ahead bias: each candle i uses only data available at candles [0..i].
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

from config.loader import Config
from src.indicators import session_vwap, wilder_atr, rsi, volume_ratio
from src.risk.position_sizer import fixed_fraction_size
from src.risk.sl_tp import atr_based_sltp
from src.signals.filters import check_long_entry, check_short_entry
from src.signals.composer import Direction

__all__ = ["BacktestEngine", "TradeRecord"]


@dataclass
class TradeRecord:
    """
    Record of a single backtest trade.

    Attributes
    ----------
    symbol : str
    direction : str
    entry_price : float
    sl : float
    tp : float
    entry_candle : int
        Candle index at entry.
    exit_candle : Optional[int]
        Candle index at exit (None if still open).
    exit_price : Optional[float]
        Exit price (None if still open).
    result : Optional[str]
        "TP" | "SL" | "TIMEOUT" | None
    pnl_pct : float
        Profit/loss as a fraction (e.g. 0.02 = +2%).
    rsi : float
        RSI value at entry (for analysis).
    """

    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    entry_candle: int
    exit_candle: Optional[int] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None
    pnl_pct: float = 0.0
    rsi: float = 0.0
    vwap: float = 0.0
    atr: float = 0.0
    volume_ratio: float = 0.0


class BacktestEngine:
    """
    Walk-forward backtest engine with no look-ahead bias.

    For each symbol, iterates through the DataFrame candle-by-candle.
    At each candle, the strategy only has access to prior + current data.

    Features:
    - Walk-forward (no look-ahead)
    - No re-entry while position is open on same symbol
    - Max hold timeout (8 candles = 2h for 15m timeframe)
    - Virtual P&L tracking
    """

    def __init__(self, config: Config, max_hold_candles: int = 8):
        self.config = config
        self.max_hold_candles = max_hold_candles
        self.min_candles = 50  # Need at least this many for indicators to stabilize

    def run(self, symbol: str, df: pd.DataFrame) -> List[TradeRecord]:
        """
        Run the backtest for a single symbol.

        Parameters
        ----------
        symbol : str
        df : pd.DataFrame
            OHLCV DataFrame with columns: open, high, low, close, volume, timestamp.

        Returns
        -------
        List[TradeRecord]
        """
        if len(df) < self.min_candles:
            return []

        trades: List[TradeRecord] = []
        open_trade: Optional[TradeRecord] = None

        # Pre-compute all indicators on the full DataFrame (no look-ahead — we
        # compute all at once but only use up to candle i at each step)
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

        # Add to dataframe for easy iloc access
        df = df.copy()
        df["vwap"] = vwap_vals.values
        df["atr"] = atr_vals.values
        df["rsi"] = rsi_vals.values
        df["volume_ratio"] = vol_ratio_vals.values

        # Also add a row index for clarity
        df = df.reset_index(drop=True)

        # Walk forward candle by candle
        for i in range(self.min_candles, len(df)):
            # Use only data up to and including candle i
            current = df.iloc[i]
            close_price = float(current["close"])
            rsi_val = float(current["rsi"])
            vwap_val = float(current["vwap"])
            atr_val = float(current["atr"])
            vol_ratio = float(current["volume_ratio"])

            # Skip if indicators are NaN
            if pd.isna(vwap_val) or pd.isna(atr_val) or pd.isna(rsi_val):
                continue

            if open_trade is not None:
                # Check exit conditions
                open_trade = self._check_exit(open_trade, current, i, trades)
            else:
                # Try to generate a signal
                signal = self._generate_signal(
                    symbol, close_price, rsi_val, vwap_val, atr_val, vol_ratio
                )
                if signal is not None:
                    open_trade = TradeRecord(
                        symbol=symbol,
                        direction=signal["direction"],
                        entry_price=signal["entry_price"],
                        sl=signal["sl"],
                        tp=signal["tp"],
                        entry_candle=i,
                        rsi=signal["rsi"],
                        vwap=signal["vwap"],
                        atr=signal["atr"],
                        volume_ratio=signal["volume_ratio"],
                    )

        # Close any remaining open trade as TIMEOUT
        if open_trade is not None:
            last_price = float(df.iloc[-1]["close"])
            open_trade.exit_candle = len(df) - 1
            open_trade.exit_price = last_price
            open_trade.result = "TIMEOUT"
            open_trade.pnl_pct = self._calc_pnl(open_trade, last_price)
            trades.append(open_trade)

        return trades

    def _generate_signal(
        self,
        symbol: str,
        close_price: float,
        rsi_val: float,
        vwap_val: float,
        atr_val: float,
        vol_ratio: float,
    ) -> Optional[dict]:
        """
        Attempt to generate a signal at the current candle.

        Uses Kronos signal but filters by technical conditions.
        Since Kronos model may not be available in backtest, we use a simplified
        signal generation (Kronos UP/DOWN based on RSI trend direction).

        Returns None if conditions not met.
        """
        # Simple signal: RSI-based directional bias (stand-in for Kronos in backtest)
        # In production, Kronos would provide the actual signal
        if rsi_val < 45:
            direction = "LONG"
            can_enter, _ = check_long_entry(close_price, rsi_val, vwap_val, vol_ratio, self.config)
        elif rsi_val > 55:
            direction = "SHORT"
            can_enter, _ = check_short_entry(close_price, rsi_val, vwap_val, vol_ratio, self.config)
        else:
            return None

        if not can_enter:
            return None

        try:
            sltp = atr_based_sltp(
                direction=direction,
                entry=close_price,
                atr=atr_val,
                sl_mult=self.config.risk.sl_atr_mult,
                tp_mult=self.config.risk.tp_atr_mult,
                min_rr=self.config.risk.min_rr_ratio,
            )
        except ValueError:
            return None

        return {
            "direction": direction,
            "entry_price": close_price,
            "sl": sltp.sl,
            "tp": sltp.tp,
            "rsi": rsi_val,
            "vwap": vwap_val,
            "atr": atr_val,
            "volume_ratio": vol_ratio,
        }

    def _check_exit(
        self,
        trade: TradeRecord,
        current: pd.Series,
        candle_idx: int,
        trades: List[TradeRecord],
    ) -> Optional[TradeRecord]:
        """
        Check whether an open trade should be closed.

        Returns the same trade with updated fields if closed, or None if still open.
        """
        price = float(current["close"])

        if trade.direction == "LONG":
            hit_sl = price <= trade.sl
            hit_tp = price >= trade.tp
        else:
            hit_sl = price >= trade.sl
            hit_tp = price <= trade.tp

        age = candle_idx - trade.entry_candle
        hit_timeout = age >= self.max_hold_candles

        if hit_sl:
            trade.exit_candle = candle_idx
            trade.exit_price = trade.sl
            trade.result = "SL"
            trade.pnl_pct = self._calc_pnl(trade, trade.sl)
            trades.append(trade)
            return None
        elif hit_tp:
            trade.exit_candle = candle_idx
            trade.exit_price = trade.tp
            trade.result = "TP"
            trade.pnl_pct = self._calc_pnl(trade, trade.tp)
            trades.append(trade)
            return None
        elif hit_timeout:
            trade.exit_candle = candle_idx
            trade.exit_price = price
            trade.result = "TIMEOUT"
            trade.pnl_pct = self._calc_pnl(trade, price)
            trades.append(trade)
            return None

        return trade

    @staticmethod
    def _calc_pnl(trade: TradeRecord, exit_price: float) -> float:
        """Calculate P&L percentage for a trade."""
        if trade.direction == "LONG":
            return (exit_price - trade.entry_price) / trade.entry_price
        else:
            return (trade.entry_price - exit_price) / trade.entry_price