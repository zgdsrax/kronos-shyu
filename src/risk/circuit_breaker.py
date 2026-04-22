"""Circuit breaker — halts signal generation when loss thresholds are breached."""
from datetime import datetime, timedelta, date
from typing import Optional

import logging

from config.loader import CircuitBreakersConfig

logger = logging.getLogger("kronos_bot.risk.circuit_breaker")


class CircuitBreaker:
    """
    Halts signal generation when simulated loss thresholds are breached.

    Resets:
    - Daily P&L reset at 00:00 UTC (start of each UTC day)
    - Consecutive loss counter resets on any winning trade

    A halted bot will automatically resume after cooldown_minutes, or at the
    start of the next UTC day — whichever comes first.
    """

    def __init__(self, config: CircuitBreakersConfig):
        self.config = config
        self._daily_loss_usd: float = 0.0
        self._consecutive_losses: int = 0
        self._halted_until: Optional[datetime] = None
        self._last_reset_date: Optional[date] = None

    def record_outcome(self, pnl_usd: float) -> None:
        """
        Record a trade outcome (profit or loss) to update circuit state.

        Parameters
        ----------
        pnl_usd : float
            Signed P&L in USD. Positive = profit, negative = loss.
        """
        if pnl_usd < 0:
            self._daily_loss_usd += abs(pnl_usd)
            self._consecutive_losses += 1
            logger.info(
                "  Loss recorded: pnl=%.2f USD | daily_loss=%.2f | consecutive=%d",
                pnl_usd,
                self._daily_loss_usd,
                self._consecutive_losses,
            )
        else:
            if self._consecutive_losses > 0:
                logger.info(
                    "  Win recorded — consecutive loss streak (%d) reset to 0",
                    self._consecutive_losses,
                )
            self._consecutive_losses = 0

    def is_halted(self, account_size: float) -> tuple[bool, str]:
        """
        Check whether signal generation should be halted.

        Checks in order:
        1. Currently in a cooldown period (from prior breach)
        2. Daily loss limit exceeded
        3. Consecutive loss limit exceeded

        Parameters
        ----------
        account_size : float
            Account size in USD (used to compute loss percentage).

        Returns
        -------
        (is_halted: bool, reason: str)
            is_halted=True means do NOT generate signals.
        """
        now = datetime.utcnow()

        # Daily reset — start of each UTC day
        today = now.date()
        if self._last_reset_date is None or self._last_reset_date < today:
            if self._last_reset_date is not None:
                logger.info(
                    "Circuit breaker daily reset (was %s losses, %.2f USD loss)",
                    self._consecutive_losses,
                    self._daily_loss_usd,
                )
            self._daily_loss_usd = 0.0
            self._consecutive_losses = 0
            self._last_reset_date = today
            self._halted_until = None

        # Check cooldown
        if self._halted_until is not None and now < self._halted_until:
            remaining_secs = (self._halted_until - now).total_seconds()
            remaining_mins = int(remaining_secs // 60)
            return True, f"Circuit breaker active — {remaining_mins}min remaining"

        # Daily loss limit
        daily_loss_pct = self._daily_loss_usd / account_size
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            self._trigger_halt(f"daily loss {daily_loss_pct:.1%} >= {self.config.max_daily_loss_pct:.1%} limit")
            return True, "Daily loss limit breached"

        # Consecutive loss limit
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            self._trigger_halt(
                f"{self._consecutive_losses} consecutive losses >= limit {self.config.max_consecutive_losses}"
            )
            return True, f"{self._consecutive_losses} consecutive losses"

        return False, ""

    def _trigger_halt(self, reason: str) -> None:
        """Internal — activate cooldown period and log."""
        self._halted_until = datetime.utcnow() + timedelta(minutes=self.config.cooldown_minutes)
        logger.warning(
            "⚠️  CIRCUIT BREAKER TRIGGERED: %s. Halted for %dmin.",
            reason,
            self.config.cooldown_minutes,
        )

    @property
    def state(self) -> dict:
        """Current state snapshot (useful for debugging / monitoring)."""
        return {
            "daily_loss_usd": round(self._daily_loss_usd, 2),
            "consecutive_losses": self._consecutive_losses,
            "halted_until": self._halted_until.isoformat() if self._halted_until else None,
        }


