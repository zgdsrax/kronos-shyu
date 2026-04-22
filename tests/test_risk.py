"""Tests for risk management modules."""
import pytest

from src.risk.position_sizer import fixed_fraction_size, SizingResult
from src.risk.sl_tp import atr_based_sltp, SLTP
from src.risk.circuit_breaker import CircuitBreaker
from config.loader import CircuitBreakersConfig, Config


class TestFixedFractionSize:
    def test_position_size_within_risk(self):
        """Computed risk should not exceed account * risk_pct * 1.01 (1% tolerance)."""
        result = fixed_fraction_size(
            account_size=10_000,
            risk_pct=0.01,
            entry=50_000,
            sl=49_000,
            max_position_usd=2_000,
        )
        assert result.risk_usd <= 10_000 * 0.01 * 1.01, \
            f"risk_usd {result.risk_usd} exceeds 1% of account"

    def test_max_position_cap(self):
        """When notional exceeds max_position_usd, is_capped=True and notional <= cap."""
        result = fixed_fraction_size(
            account_size=10_000,
            risk_pct=0.01,
            entry=50_000,
            sl=49_999,  # tiny risk per contract
            max_position_usd=500,
        )
        assert result.is_capped, "Should be capped"
        assert result.position_size_contracts * 50_000 <= 501, \
            "Notional should be within $1 of cap"

    def test_sl_too_close_to_entry_raises(self):
        """SL too close to entry (risk_per_contract ~ 0) should raise ValueError."""
        with pytest.raises(ValueError):
            fixed_fraction_size(
                account_size=10_000,
                risk_pct=0.01,
                entry=50_000,
                sl=49_999.99,
                max_position_usd=2000,
            )

    def test_zero_risk_pct_raises(self):
        """Zero risk_pct should raise (would produce zero size)."""
        with pytest.raises(ZeroDivisionError):
            fixed_fraction_size(
                account_size=10_000,
                risk_pct=0.0,
                entry=50_000,
                sl=49_000,
                max_position_usd=2000,
            )

    def test_uncapped_size_is_positive(self):
        """Normal uncapped trade should return positive size and risk."""
        result = fixed_fraction_size(
            account_size=10_000,
            risk_pct=0.01,
            entry=50_000,
            sl=49_500,
            max_position_usd=2000,
        )
        assert result.position_size_contracts > 0
        assert result.risk_usd > 0
        assert not result.is_capped

    def test_result_attributes(self):
        """SizingResult should have all required fields."""
        result = fixed_fraction_size(
            account_size=10_000,
            risk_pct=0.01,
            entry=50_000,
            sl=49_500,
            max_position_usd=2000,
        )
        assert hasattr(result, "position_size_contracts")
        assert hasattr(result, "risk_usd")
        assert hasattr(result, "is_capped")
        assert isinstance(result, SizingResult)


class TestATRBasedSLTP:
    def test_rr_minimum_enforced(self):
        """Should raise ValueError if resulting RR < min_rr."""
        with pytest.raises(ValueError, match="RR"):
            atr_based_sltp(
                direction="LONG",
                entry=100,
                atr=1.0,
                sl_mult=5.0,   # huge SL = tiny RR
                tp_mult=1.0,
                min_rr=1.5,
            )

    def test_long_sltp_correct_direction(self):
        """LONG: SL < entry < TP."""
        result = atr_based_sltp(
            direction="LONG",
            entry=100,
            atr=1.0,
            sl_mult=1.5,
            tp_mult=3.0,
        )
        assert result.sl < 100 < result.tp, \
            f"SL={result.sl}, entry=100, TP={result.tp}"

    def test_short_sltp_correct_direction(self):
        """SHORT: TP < entry < SL."""
        result = atr_based_sltp(
            direction="SHORT",
            entry=100,
            atr=1.0,
            sl_mult=1.5,
            tp_mult=3.0,
        )
        assert result.tp < 100 < result.sl, \
            f"SL={result.sl}, entry=100, TP={result.tp}"

    def test_rr_ratio_correct(self):
        """RR ratio should be tp_mult / sl_mult."""
        result = atr_based_sltp(
            direction="LONG",
            entry=100,
            atr=1.0,
            sl_mult=1.5,
            tp_mult=3.0,
        )
        assert result.rr_ratio == pytest.approx(2.0), \
            f"Expected RR=2.0, got {result.rr_ratio}"

    def test_invalid_direction_raises(self):
        """Invalid direction string should raise ValueError."""
        with pytest.raises(ValueError):
            atr_based_sltp(
                direction="FLAT",
                entry=100,
                atr=1.0,
            )

    def test_negative_atr_raises(self):
        """Negative ATR should raise ValueError."""
        with pytest.raises(ValueError):
            atr_based_sltp(
                direction="LONG",
                entry=100,
                atr=-1.0,
            )

    def test_zero_atr_raises(self):
        """Zero ATR should raise ValueError."""
        with pytest.raises(ValueError):
            atr_based_sltp(
                direction="LONG",
                entry=100,
                atr=0.0,
            )

    def test_sltp_rounded(self):
        """SL and TP should be rounded to 6 decimal places."""
        result = atr_based_sltp(
            direction="LONG",
            entry=100.123456789,
            atr=0.987654321,
            sl_mult=1.5,
            tp_mult=3.0,
        )
        # Check that it's a float with reasonable precision
        assert isinstance(result.sl, float)
        assert isinstance(result.tp, float)


class TestCircuitBreaker:
    def _make_config(self) -> CircuitBreakersConfig:
        return CircuitBreakersConfig(
            max_daily_loss_pct=0.03,
            max_consecutive_losses=4,
            cooldown_minutes=10,
        )

    def test_initial_not_halted(self):
        """New circuit breaker should not be halted."""
        cb = CircuitBreaker(self._make_config())
        halted, _ = cb.is_halted(10_000)
        assert not halted

    def test_single_loss_tracking(self):
        """Single losing trade should increment consecutive losses."""
        cb = CircuitBreaker(self._make_config())
        cb.record_outcome(-50.0)
        assert cb._consecutive_losses == 1
        assert cb._daily_loss_usd == 50.0

    def test_win_resets_consecutive_losses(self):
        """A winning trade should reset consecutive loss counter."""
        cb = CircuitBreaker(self._make_config())
        cb.record_outcome(-50.0)
        cb.record_outcome(-50.0)
        cb.record_outcome(100.0)  # win
        assert cb._consecutive_losses == 0, "Win should reset consecutive losses"

    def test_max_consecutive_losses_halts(self):
        """Exceeding max_consecutive_losses should halt the bot."""
        cb = CircuitBreaker(self._make_config())
        for _ in range(4):
            cb.record_outcome(-10.0)
        halted, reason = cb.is_halted(10_000)
        assert halted
        assert "consecutive losses" in reason.lower()

    def test_daily_loss_limit_halts(self):
        """Exceeding max_daily_loss_pct should halt the bot."""
        cb = CircuitBreaker(self._make_config())
        # 3% of 10_000 = 300 USD
        cb.record_outcome(-400.0)
        halted, reason = cb.is_halted(10_000)
        assert halted
        assert "daily loss" in reason.lower()

    def test_state_snapshot(self):
        """State should reflect current circuit breaker status."""
        cb = CircuitBreaker(self._make_config())
        cb.record_outcome(-75.0)
        state = cb.state
        assert state["daily_loss_usd"] == 75.0
        assert state["consecutive_losses"] == 1
        assert "halted_until" in state

    def test_cooldown_after_trigger(self):
        """After triggering, is_halted should remain True during cooldown period."""
        cb = CircuitBreaker(self._make_config())
        # Force halt
        cb._trigger_halt("test")
        halted1, _ = cb.is_halted(10_000)
        assert halted1
        # Immediate second check should still be halted
        halted2, _ = cb.is_halted(10_000)
        assert halted2