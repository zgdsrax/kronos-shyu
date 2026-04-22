"""Signal tracker — deduplication, open trade management, virtual P&L."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import logging

from config.loader import DedupConfig

logger = logging.getLogger("kronos_bot.state.tracker")


@dataclass
class OpenSignal:
    """
    Represents an open (unresolved) trade signal.

    Attributes
    ----------
    symbol : str
        Trading pair symbol.
    direction : str
        "LONG" or "SHORT".
    entry_price : float
    sl : float
    tp : float
    timestamp : datetime
    candle_count : int
        Number of cycles (candles) this trade has been open.
    """

    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    timestamp: datetime
    candle_count: int = 0


@dataclass
class SignalTracker:
    """
    Tracks open signals, enforces deduplication, and simulates trade outcomes.

    Responsibilities:
    1. Deduplication — prevent re-entry on same symbol within cooldown window
    2. Virtual P&L — feeds circuit breaker with simulated outcomes
    3. Lifecycle — detect SL/TP hits each cycle

    Parameters
    ----------
    cooldown_candles : int
        Minimum candle count before same-symbol signal is allowed again.
    price_tolerance_pct : float
        If entry price is within this % of prior entry, treat as duplicate.
    """

    cooldown_candles: int
    price_tolerance_pct: float
    _open: Dict[str, OpenSignal] = field(default_factory=dict)

    def is_duplicate(
        self, symbol: str, direction: str, entry: float
    ) -> bool:
        """
        Check whether a new signal for this symbol should be suppressed.

        Conditions for duplicate:
        - Same symbol is currently in the open dict
        - Same direction
        - Entry price within price_tolerance_pct of prior entry
        - Candle count < cooldown_candles

        Parameters
        ----------
        symbol, direction, entry
            New signal attributes.

        Returns
        -------
        bool
            True = suppress this signal.
        """
        if symbol not in self._open:
            return False

        prev = self._open[symbol]
        if prev.direction != direction:
            return False

        price_change = abs(prev.entry_price - entry) / prev.entry_price
        if price_change >= self.price_tolerance_pct:
            return False

        if prev.candle_count >= self.cooldown_candles:
            # Cooldown expired — clear and allow
            del self._open[symbol]
            return False

        return True

    def register(self, signal) -> None:
        """
        Record a new open signal.

        Parameters
        ----------
        signal : TradeSignal
        """
        self._open[signal.symbol] = OpenSignal(
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=signal.entry_price,
            sl=signal.sl,
            tp=signal.tp,
            timestamp=datetime.utcnow(),
        )
        logger.info(
            "[%s] Signal registered: %s @ %.4f (SL=%.4f TP=%.4f)",
            signal.symbol,
            signal.direction.value,
            signal.entry_price,
            signal.sl,
            signal.tp,
        )

    def update(self, current_prices: Dict[str, float]) -> List[dict]:
        """
        Advance all open signals by one candle.

        Checks each open signal against current prices to detect:
        - SL hit (loss)
        - TP hit (profit)
        - Timeout (max hold candles exceeded)

        Parameters
        ----------
        current_prices : dict[str, float]
            Latest price for each tracked symbol.

        Returns
        -------
        List[dict]
            List of closed trade outcomes, each with:
            symbol, result ("SL" | "TP"), pnl_pct, entry_price, exit_price
        """
        outcomes: List[dict] = []
        to_close: List[str] = []

        for sym, sig in list(self._open.items()):
            price = current_prices.get(sym)
            if price is None:
                # No price update available — increment candle count but don't close
                sig.candle_count += 1
                continue

            sig.candle_count += 1

            # Check exit conditions
            if sig.direction == "LONG":
                hit_sl = price <= sig.sl
                hit_tp = price >= sig.tp
            else:
                hit_sl = price >= sig.sl
                hit_tp = price <= sig.tp

            if hit_sl or hit_tp:
                result = "TP" if hit_tp else "SL"
                ref_price = sig.tp if hit_tp else sig.sl

                # P&L in percent — LONG: (exit - entry) / entry
                if sig.direction == "LONG":
                    pnl_pct = (ref_price - sig.entry_price) / sig.entry_price
                else:
                    pnl_pct = (sig.entry_price - ref_price) / sig.entry_price

                outcomes.append({
                    "symbol": sym,
                    "result": result,
                    "pnl_pct": round(pnl_pct, 6),
                    "entry_price": sig.entry_price,
                    "exit_price": round(ref_price, 6),
                })
                to_close.append(sym)
                logger.info(
                    "[%s] %s closed by %s: entry=%.4f exit=%.4f pnl=%+.2f%%",
                    sym,
                    sig.direction,
                    result,
                    sig.entry_price,
                    ref_price,
                    pnl_pct * 100,
                )

        for sym in to_close:
            del self._open[sym]

        return outcomes

    @property
    def open_signals(self) -> Dict[str, OpenSignal]:
        """Return a copy of currently open signals."""
        return dict(self._open)

    @property
    def open_count(self) -> int:
        return len(self._open)