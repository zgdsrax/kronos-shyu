// ─────────────────────────────────────────────
// PROMPT DATA
// ─────────────────────────────────────────────

const MODULES = [
  {
    id: "overview",
    tag: "OVERVIEW",
    color: "#e2b96a",
    title: "Project Overview & Philosophy",
    content: `# ROLE
You are a senior quantitative engineer with 10+ years experience building production trading systems at hedge funds and prop desks. You write clean, typed, testable Python. You think in terms of risk first, alpha second.

# MISSION
Build a complete, production-ready algorithmic trading bot for Hyperliquid perpetuals from scratch. The codebase must be modular, fully typed, thoroughly documented, and deployable via Docker. Every design decision must be justifiable from a risk management perspective.

# STRATEGY
- Universe: BTC, ETH, SOL, LINK, HYPE perpetuals on Hyperliquid
- Signal source: Kronos AI model (transformer-based price forecaster) + technical confirmation (RSI, VWAP, ATR)
- Timeframe: 15-minute candles
- Signal logic: Kronos UP/DOWN + price vs VWAP + RSI range filter + volume confirmation
- Execution: Signal-only bot (generates alerts to Telegram). No direct order execution in v1.
- Risk layer: ATR-based dynamic SL/TP, position sizing by % equity risk, daily drawdown circuit breaker

# CORE PRINCIPLES
1. Risk management is non-negotiable — every trade has a defined max loss before entry
2. No magic numbers — all parameters live in config files with documented rationale
3. Fail loudly — errors must surface immediately, never silently swallowed
4. Observable — every decision is logged with full context for post-hoc analysis
5. Testable — every module has unit tests, strategy logic has backtest harness`
  },
  {
    id: "structure",
    tag: "STRUCTURE",
    color: "#54a0ff",
    title: "Project Structure",
    content: `# DIRECTORY LAYOUT

Build the following exact directory structure. Every file listed must be created.

\`\`\`
kronos-bot/
│
├── config/
│   ├── settings.yaml          # All tunable parameters (never hardcode)
│   └── logging.yaml           # Logging configuration
│
├── src/
│   ├── __init__.py
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py         # Hyperliquid OHLCV fetch + retry logic
│   │   └── schemas.py         # Pydantic models: Candle, OHLCV, MarketSnapshot
│   │
│   ├── indicators/
│   │   ├── __init__.py
│   │   ├── vwap.py            # Session-reset VWAP
│   │   ├── atr.py             # ATR with proper Wilder smoothing
│   │   ├── rsi.py             # RSI with configurable length
│   │   └── volume.py          # Volume MA + ratio
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── kronos.py          # Kronos model wrapper (load-once singleton)
│   │   ├── filters.py         # Entry condition logic (VWAP, RSI, volume filters)
│   │   └── composer.py        # Combines Kronos + filters → TradeSignal
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── position_sizer.py  # Kelly / Fixed-fraction sizing
│   │   ├── sl_tp.py           # ATR-based SL/TP calculator
│   │   └── circuit_breaker.py # Daily loss limit, consecutive loss limit
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   └── notifier.py        # Telegram alert formatter + sender
│   │
│   ├── state/
│   │   ├── __init__.py
│   │   └── tracker.py         # Open signal tracker, dedup, P&L simulation
│   │
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py          # Walk-forward backtest loop
│   │   └── metrics.py         # Sharpe, Sortino, max DD, win rate, avg RR
│   │
│   └── bot.py                 # Main orchestrator — ties all modules together
│
├── tests/
│   ├── test_indicators.py
│   ├── test_risk.py
│   ├── test_signals.py
│   └── test_backtest.py
│
├── scripts/
│   └── run_backtest.py        # CLI entrypoint for backtesting
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── README.md
\`\`\``
  },
  {
    id: "config",
    tag: "CONFIG",
    color: "#a29bfe",
    title: "Configuration Layer",
    content: `# config/settings.yaml

Build a complete YAML config. All numeric parameters must have an inline comment explaining their rationale.

\`\`\`yaml
# ── UNIVERSE ──────────────────────────────────────────
symbols: [BTC, ETH, SOL, LINK, HYPE]
timeframe: "15m"
lookback_candles: 150        # enough for 5-day VWAP history

# ── KRONOS MODEL ──────────────────────────────────────
kronos:
  model_id: "NeoQuasar/Kronos-small"
  pred_len: 4                 # forecast 4 candles = 1h ahead
  threshold_pct: 0.5          # min % change to classify as UP/DOWN (not NEUTRAL)
  device: "cpu"

# ── INDICATORS ────────────────────────────────────────
indicators:
  rsi_length: 14
  atr_length: 14
  volume_ma_length: 20
  vwap_min_candles: 5         # min candles in session before VWAP is trusted

# ── ENTRY FILTERS ─────────────────────────────────────
filters:
  long:
    rsi_min: 40
    rsi_max: 70
    require_price_above_vwap: true
    volume_ratio_min: 1.2     # current vol must be 1.2x 20-period avg
  short:
    rsi_min: 30
    rsi_max: 60
    require_price_below_vwap: true
    volume_ratio_min: 1.2

# ── RISK MANAGEMENT ───────────────────────────────────
risk:
  account_size_usd: 10000
  risk_per_trade_pct: 0.01    # max 1% equity per trade
  max_position_usd: 2000      # hard cap regardless of sizing formula
  sl_atr_mult: 1.5            # SL = entry ± 1.5 × ATR
  tp_atr_mult: 3.0            # TP = entry ± 3.0 × ATR → RR = 2:1
  min_rr_ratio: 1.5           # reject trades where TP/SL < 1.5

# ── CIRCUIT BREAKERS ──────────────────────────────────
circuit_breakers:
  max_daily_loss_pct: 0.03    # halt if simulated daily loss > 3%
  max_consecutive_losses: 4   # halt after 4 losses in a row
  cooldown_minutes: 120       # resume after 2h cooldown

# ── DEDUPLICATION ─────────────────────────────────────
dedup:
  cooldown_candles: 4         # same symbol needs 4 candles (1h) before new signal
  price_tolerance_pct: 0.005  # signals within 0.5% of prior entry are duplicates

# ── SCHEDULER ─────────────────────────────────────────
scheduler:
  cycle_seconds: 900          # 15 minutes
  symbol_delay_seconds: 2     # stagger between symbols to avoid API burst

# ── TELEGRAM ──────────────────────────────────────────
telegram:
  parse_mode: "HTML"
  send_no_signal: false       # never spam no-signal messages
  send_daily_summary: true
  summary_hour_utc: 0         # send summary at 00:00 UTC
\`\`\`

# CONFIG LOADING PATTERN

In \`src/bot.py\`, load config using:
\`\`\`python
from pathlib import Path
import yaml
from pydantic import BaseModel

class Config(BaseModel):
    # Nested Pydantic models matching YAML structure
    ...

def load_config(path: Path = Path("config/settings.yaml")) -> Config:
    with open(path) as f:
        return Config(**yaml.safe_load(f))
\`\`\``
  },
  {
    id: "data",
    tag: "DATA",
    color: "#00d2d3",
    title: "Data Layer",
    content: `# src/data/schemas.py

Define all data contracts with Pydantic:

\`\`\`python
from pydantic import BaseModel, field_validator
from datetime import datetime
import pandas as pd

class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator('high')
    def high_gte_low(cls, v, info):
        if 'low' in info.data and v < info.data['low']:
            raise ValueError('high must be >= low')
        return v

class OHLCVFrame(BaseModel):
    symbol: str
    timeframe: str
    candles: list[Candle]

    def to_dataframe(self) -> pd.DataFrame:
        ...
\`\`\`

# src/data/fetcher.py

\`\`\`python
import time
import logging
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

logger = logging.getLogger(__name__)

class HyperliquidFetcher:
    """Fetches OHLCV candles from Hyperliquid with retry logic and validation."""

    def __init__(self, lookback: int = 150, interval: str = "15m"):
        self.lookback = lookback
        self.interval = interval
        self._failure_counts: dict[str, int] = {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def fetch(self, symbol: str) -> Optional[OHLCVFrame]:
        """
        Fetch candles for symbol. Retries 3× with 2s backoff.
        Returns None only after all retries exhausted.
        Raises on malformed data.
        """
        ...

    def fetch_all(self, symbols: list[str]) -> dict[str, Optional[OHLCVFrame]]:
        """Fetch all symbols with per-symbol error isolation."""
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.fetch(sym)
                self._failure_counts[sym] = 0
            except Exception as e:
                logger.error(f"[{sym}] Fetch failed: {e}")
                self._failure_counts[sym] = self._failure_counts.get(sym, 0) + 1
                results[sym] = None
        return results
\`\`\``
  },
  {
    id: "indicators",
    tag: "INDICATORS",
    color: "#ff9f43",
    title: "Indicator Layer",
    content: `# PRINCIPLE: All indicators must be pure functions.
# Input: pd.Series or pd.DataFrame. Output: pd.Series.
# No side effects. All NaN propagation must be explicit.

# src/indicators/vwap.py

\`\`\`python
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
    Compute VWAP with per-UTC-day session reset.

    Parameters
    ----------
    min_candles : int
        Minimum candles within a session before VWAP is considered valid.
        Returns NaN for candles before this threshold.

    Returns
    -------
    pd.Series of VWAP values, NaN for unreliable early-session values.
    """
    typical_price = (high + low + close) / 3
    dates = pd.to_datetime(timestamps, unit="ms").dt.date

    vwap = pd.Series(np.nan, index=close.index)

    for date, grp in close.groupby(dates):
        idx = grp.index
        tp = typical_price.loc[idx]
        vol = volume.loc[idx]

        cum_tp_vol = (tp * vol).cumsum()
        cum_vol = vol.cumsum()

        result = cum_tp_vol / cum_vol
        # Mask unreliable early-session values
        result[result.index[:min_candles]] = np.nan
        vwap.loc[idx] = result.values

    return vwap
\`\`\`

# src/indicators/atr.py

\`\`\`python
def wilder_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
) -> pd.Series:
    """
    ATR using Wilder's smoothing (not simple rolling mean).
    Standard for TradingView / most institutional platforms.
    First value uses simple mean; subsequent use EMA with alpha=1/length.
    """
    ...
\`\`\`

# src/indicators/rsi.py

\`\`\`python
def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """
    RSI using Wilder's smoothing for consistency with industry standard.
    Returns values in [0, 100]. NaN for first <length> candles.
    """
    ...
\`\`\`

# src/indicators/volume.py

\`\`\`python
def volume_ratio(volume: pd.Series, ma_length: int = 20) -> pd.Series:
    """
    Returns current_volume / rolling_mean(volume, ma_length).
    Values > 1.2 indicate elevated volume (confirmation threshold).
    """
    ...
\`\`\``
  },
  {
    id: "signals",
    tag: "SIGNALS",
    color: "#ff6b6b",
    title: "Signal Layer",
    content: `# src/signals/kronos.py — SINGLETON PATTERN

\`\`\`python
from __future__ import annotations
import logging
from typing import Optional
import pandas as pd
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class KronosResult:
    signal: str          # "UP" | "DOWN" | "NEUTRAL"
    predicted_close: Optional[float]
    change_pct: float    # predicted % change from current close

class KronosPredictor:
    """
    Singleton wrapper around Kronos model.
    Model is loaded ONCE at instantiation. Never reload mid-session.
    """
    _instance: Optional[KronosPredictor] = None

    def __new__(cls, config: dict) -> KronosPredictor:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def load(self, config: dict) -> None:
        if self._loaded:
            return
        logger.info("Loading Kronos model — this happens once at startup")
        try:
            # load tokenizer + model + predictor here
            self._loaded = True
            logger.info("Kronos model loaded successfully")
        except Exception as e:
            logger.critical(f"Kronos model load failed: {e}")
            raise SystemExit(1)

    def predict(self, df: pd.DataFrame, pred_len: int, threshold_pct: float) -> KronosResult:
        """Run prediction. Returns KronosResult with signal + metadata."""
        ...
\`\`\`

# src/signals/composer.py — TRADE SIGNAL TYPE

\`\`\`python
from dataclasses import dataclass
from typing import Optional
from enum import Enum

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

@dataclass(frozen=True)
class TradeSignal:
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
        """Sanity check before sending alert."""
        return (
            self.sl > 0
            and self.tp > 0
            and self.rr_ratio >= 1.5
            and self.position_size_contracts > 0
        )
\`\`\`

# src/signals/filters.py — ENTRY LOGIC

\`\`\`python
def check_long_entry(
    close: float,
    rsi: float,
    vwap: float,
    volume_ratio: float,
    config: FilterConfig,
) -> tuple[bool, str]:
    """
    Returns (can_enter, rejection_reason).
    rejection_reason is empty string on success.
    All conditions are AND-gated.
    """
    if close <= vwap:
        return False, "price below VWAP"
    if not (config.rsi_min <= rsi <= config.rsi_max):
        return False, f"RSI {rsi:.1f} out of range [{config.rsi_min}, {config.rsi_max}]"
    if volume_ratio < config.volume_ratio_min:
        return False, f"volume ratio {volume_ratio:.2f} < {config.volume_ratio_min}"
    return True, ""
\`\`\``
  },
  {
    id: "risk",
    tag: "RISK",
    color: "#ee5a24",
    title: "Risk Management Layer",
    content: `# THIS IS THE MOST CRITICAL MODULE. Build it first. Test it most.

# src/risk/position_sizer.py

\`\`\`python
from dataclasses import dataclass

@dataclass
class SizingResult:
    position_size_contracts: float
    risk_usd: float
    is_capped: bool              # True if max_position_usd cap was applied

def fixed_fraction_size(
    account_size: float,
    risk_pct: float,             # e.g. 0.01 for 1%
    entry: float,
    sl: float,
    max_position_usd: float,
) -> SizingResult:
    """
    Fixed-fraction position sizing. Industry standard for retail/prop.

    Formula:
        risk_usd = account_size * risk_pct
        risk_per_contract = |entry - sl|
        size = risk_usd / risk_per_contract

    The max_position_usd cap is a hard stop regardless of formula output.
    """
    risk_usd = account_size * risk_pct
    risk_per_contract = abs(entry - sl)

    if risk_per_contract < 1e-8:
        raise ValueError("SL too close to entry — division by near-zero")

    raw_size = risk_usd / risk_per_contract
    position_value = raw_size * entry
    is_capped = position_value > max_position_usd

    if is_capped:
        raw_size = max_position_usd / entry

    return SizingResult(
        position_size_contracts=round(raw_size, 4),
        risk_usd=round(risk_per_contract * raw_size, 2),
        is_capped=is_capped,
    )
\`\`\`

# src/risk/circuit_breaker.py

\`\`\`python
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    Halts signal generation when loss thresholds are breached.
    Resets daily at 00:00 UTC.
    """

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self._daily_loss_usd: float = 0.0
        self._consecutive_losses: int = 0
        self._halted_until: Optional[datetime] = None
        self._last_reset_date: date = datetime.utcnow().date()

    def record_outcome(self, pnl_usd: float) -> None:
        """Call this when a simulated trade closes."""
        self._maybe_reset_daily()
        if pnl_usd < 0:
            self._daily_loss_usd += abs(pnl_usd)
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def is_halted(self, account_size: float) -> tuple[bool, str]:
        """Returns (halted, reason). Check before every signal."""
        now = datetime.utcnow()
        if self._halted_until and now < self._halted_until:
            remaining = (self._halted_until - now).seconds // 60
            return True, f"Circuit breaker active — {remaining}min remaining"

        daily_loss_pct = self._daily_loss_usd / account_size
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            self._trigger_halt(f"daily loss {daily_loss_pct:.1%} >= limit")
            return True, "Daily loss limit breached"

        if self._consecutive_losses >= self.config.max_consecutive_losses:
            self._trigger_halt(f"{self._consecutive_losses} consecutive losses")
            return True, f"{self._consecutive_losses} consecutive losses"

        return False, ""

    def _trigger_halt(self, reason: str) -> None:
        self._halted_until = datetime.utcnow() + timedelta(
            minutes=self.config.cooldown_minutes
        )
        logger.warning(f"⚠️ CIRCUIT BREAKER TRIGGERED: {reason}. Halted for {self.config.cooldown_minutes}min")
\`\`\`

# src/risk/sl_tp.py

\`\`\`python
from dataclasses import dataclass

@dataclass
class SLTP:
    sl: float
    tp: float
    rr_ratio: float

def atr_based_sltp(
    direction: str,     # "LONG" | "SHORT"
    entry: float,
    atr: float,
    sl_mult: float = 1.5,
    tp_mult: float = 3.0,
    min_rr: float = 1.5,
) -> SLTP:
    """
    SL/TP based on ATR multiples.
    Raises ValueError if resulting RR < min_rr.
    """
    if direction == "LONG":
        sl = entry - sl_mult * atr
        tp = entry + tp_mult * atr
    else:
        sl = entry + sl_mult * atr
        tp = entry - tp_mult * atr

    rr = abs(tp - entry) / abs(entry - sl)
    if rr < min_rr:
        raise ValueError(f"RR {rr:.2f} below minimum {min_rr}")

    return SLTP(sl=round(sl, 6), tp=round(tp, 6), rr_ratio=round(rr, 2))
\`\`\``
  },
  {
    id: "state",
    tag: "STATE",
    color: "#6c5ce7",
    title: "State & Deduplication",
    content: `# src/state/tracker.py

\`\`\`python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class OpenSignal:
    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    timestamp: datetime
    candle_count: int = 0          # incremented each cycle

@dataclass
class SignalTracker:
    """
    Tracks open signals per symbol.
    Responsibilities:
      1. Deduplication — prevents re-entry on same signal
      2. Virtual P&L tracking — feeds into circuit breaker
      3. Signal lifecycle — detect SL/TP hits
    """
    cooldown_candles: int
    price_tolerance_pct: float
    _open: dict[str, OpenSignal] = field(default_factory=dict)

    def is_duplicate(self, symbol: str, direction: str, entry: float) -> bool:
        """
        Returns True if a signal should be suppressed as duplicate.
        Conditions: same symbol + direction + entry within tolerance + within cooldown.
        """
        if symbol not in self._open:
            return False
        prev = self._open[symbol]
        same_direction = prev.direction == direction
        price_close = abs(prev.entry_price - entry) / prev.entry_price < self.price_tolerance_pct
        within_cooldown = prev.candle_count < self.cooldown_candles
        return same_direction and price_close and within_cooldown

    def update(self, current_prices: dict[str, float]) -> list[dict]:
        """
        Advance state by one candle. Check if any open signals hit SL/TP.
        Returns list of closed signal outcomes for circuit breaker.
        """
        outcomes = []
        to_close = []

        for sym, sig in self._open.items():
            price = current_prices.get(sym)
            if price is None:
                continue
            sig.candle_count += 1

            if sig.direction == "LONG":
                if price <= sig.sl:
                    outcomes.append({"symbol": sym, "result": "SL", "pnl_pct": (sig.sl - sig.entry_price) / sig.entry_price})
                    to_close.append(sym)
                elif price >= sig.tp:
                    outcomes.append({"symbol": sym, "result": "TP", "pnl_pct": (sig.tp - sig.entry_price) / sig.entry_price})
                    to_close.append(sym)
            else:
                if price >= sig.sl:
                    outcomes.append({"symbol": sym, "result": "SL", "pnl_pct": (sig.entry_price - sig.sl) / sig.entry_price})
                    to_close.append(sym)
                elif price <= sig.tp:
                    outcomes.append({"symbol": sym, "result": "TP", "pnl_pct": (sig.entry_price - sig.tp) / sig.entry_price})
                    to_close.append(sym)

        for sym in to_close:
            logger.info(f"[{sym}] Signal closed: {self._open[sym].direction} → {outcomes[-1]['result']}")
            del self._open[sym]

        return outcomes
\`\`\``
  },
  {
    id: "backtest",
    tag: "BACKTEST",
    color: "#00b894",
    title: "Backtesting Engine",
    content: `# src/backtest/engine.py

\`\`\`python
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import logging

logger = logging.getLogger(__name__)

@dataclass
class TradeRecord:
    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    entry_candle: int
    exit_candle: Optional[int] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None    # "TP" | "SL" | "TIMEOUT"
    pnl_pct: float = 0.0
    rr_achieved: float = 0.0

class BacktestEngine:
    """
    Walk-forward backtest. No look-ahead. Each candle processes only data available up to that point.

    METHODOLOGY:
    - For each candle i: compute indicators on candles [0..i]
    - Run signal logic
    - If signal: record entry at close[i]
    - Forward scan from i+1 to find SL/TP hit or timeout at max_hold_candles
    - NO reentry while trade is open on same symbol
    """

    def __init__(self, config, max_hold_candles: int = 8):
        self.config = config
        self.max_hold_candles = max_hold_candles

    def run(self, symbol: str, df: pd.DataFrame) -> list[TradeRecord]:
        """Run full backtest on historical OHLCV DataFrame."""
        trades = []
        open_trade: Optional[TradeRecord] = None
        min_candles = max(self.config.indicators.rsi_length, 50)

        for i in range(min_candles, len(df)):
            window = df.iloc[:i+1].copy()

            # Close open trade if needed
            if open_trade is not None:
                open_trade, closed = self._check_exit(open_trade, window.iloc[-1], i)
                if closed:
                    trades.append(closed)
                    open_trade = None
                continue  # don't re-enter same candle trade closed

            # Compute indicators on window
            indicators = self._compute_indicators(window)
            if indicators is None:
                continue

            # Get signal
            signal = self._get_signal(symbol, window, indicators)
            if signal is None:
                continue

            # Open trade
            open_trade = TradeRecord(
                symbol=symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                sl=signal.sl,
                tp=signal.tp,
                entry_candle=i,
            )

        return trades
\`\`\`

# src/backtest/metrics.py

\`\`\`python
import numpy as np
import pandas as pd

def compute_metrics(trades: list[TradeRecord]) -> dict:
    """
    Compute standard quant performance metrics.
    Returns dict with all metrics for reporting.
    """
    if not trades:
        return {"error": "no trades"}

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    equity_curve = pd.Series(pnls).add(1).cumprod()
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max

    daily_ret = pd.Series(pnls)
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252 * 96) if daily_ret.std() > 0 else 0

    return {
        "total_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_win_pct": np.mean(wins) if wins else 0,
        "avg_loss_pct": np.mean(losses) if losses else 0,
        "avg_rr": abs(np.mean(wins) / np.mean(losses)) if losses and wins else 0,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses else float("inf"),
        "max_drawdown_pct": drawdown.min(),
        "sharpe_ratio": sharpe,
        "expectancy_pct": np.mean(pnls),
        "total_return_pct": equity_curve.iloc[-1] - 1,
    }
\`\`\``
  },
  {
    id: "orchestrator",
    tag: "ORCHESTRATOR",
    color: "#fd79a8",
    title: "Main Orchestrator",
    content: `# src/bot.py — MAIN ENTRY POINT

\`\`\`python
#!/usr/bin/env python3
"""
Kronos Trading Bot — Main Orchestrator
=======================================
Wires all modules together. All business logic lives in submodules.
This file only coordinates the flow.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from src.data.fetcher import HyperliquidFetcher
from src.indicators.vwap import session_vwap
from src.indicators.atr import wilder_atr
from src.indicators.rsi import rsi
from src.indicators.volume import volume_ratio
from src.signals.kronos import KronosPredictor
from src.signals.composer import SignalComposer
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.position_sizer import fixed_fraction_size
from src.risk.sl_tp import atr_based_sltp
from src.state.tracker import SignalTracker
from src.execution.notifier import TelegramNotifier
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import compute_metrics
from config.loader import load_config

logger = logging.getLogger("kronos_bot")

def run_live(config) -> None:
    """Main live trading loop."""

    # ── Startup: load model ONCE ──────────────────────
    kronos = KronosPredictor(config.kronos)
    kronos.load(config.kronos)

    # ── Init all stateful components ──────────────────
    fetcher = HyperliquidFetcher(config)
    composer = SignalComposer(config)
    circuit = CircuitBreaker(config.circuit_breakers)
    tracker = SignalTracker(config.dedup)
    notifier = TelegramNotifier(config.telegram)

    logger.info(f"Bot started | Symbols: {config.symbols} | TF: {config.timeframe}")
    notifier.send_startup_message(config.symbols)

    cycle = 0

    while True:
        cycle += 1
        logger.info(f"─── Cycle {cycle} @ {time.strftime('%H:%M:%S UTC', time.gmtime())} ───")

        # ── Fetch all data ────────────────────────────
        frames = fetcher.fetch_all(config.symbols)
        current_prices = {
            sym: float(frame.candles[-1].close)
            for sym, frame in frames.items()
            if frame is not None
        }

        # ── Update tracker (detect SL/TP hits) ───────
        outcomes = tracker.update(current_prices)
        for outcome in outcomes:
            circuit.record_outcome(outcome["pnl_pct"] * config.risk.account_size_usd)
            notifier.send_outcome(outcome)

        # ── Check circuit breaker ─────────────────────
        halted, reason = circuit.is_halted(config.risk.account_size_usd)
        if halted:
            logger.warning(f"🚨 HALTED: {reason}")
            time.sleep(config.scheduler.cycle_seconds)
            continue

        # ── Process each symbol ───────────────────────
        for symbol, frame in frames.items():
            if frame is None:
                continue

            df = frame.to_dataframe()
            if len(df) < 50:
                logger.warning(f"[{symbol}] Insufficient data ({len(df)} candles)")
                continue

            try:
                signal = composer.compose(symbol, df, kronos)
            except Exception as e:
                logger.error(f"[{symbol}] Signal composition error: {e}", exc_info=True)
                continue

            if signal is None:
                logger.info(f"[{symbol}] No signal")
                continue

            if not signal.is_valid():
                logger.warning(f"[{symbol}] Signal failed validation: {signal}")
                continue

            if tracker.is_duplicate(symbol, signal.direction, signal.entry_price):
                logger.info(f"[{symbol}] Duplicate signal suppressed")
                continue

            # ── Send alert ────────────────────────────
            notifier.send_signal(signal)
            tracker.register(signal)
            logger.info(f"[{symbol}] ✅ ALERT SENT: {signal.direction} @ {signal.entry_price:.4f}")

            time.sleep(config.scheduler.symbol_delay_seconds)

        logger.info(f"Cycle {cycle} complete. Sleeping {config.scheduler.cycle_seconds}s")
        time.sleep(config.scheduler.cycle_seconds)


def run_backtest(config) -> None:
    """Backtest mode — no Telegram sends."""
    logger.info("Running in BACKTEST mode")
    engine = BacktestEngine(config)
    fetcher = HyperliquidFetcher(config, lookback=500)
    kronos = KronosPredictor(config.kronos)
    kronos.load(config.kronos)

    for symbol in config.symbols:
        frame = fetcher.fetch(symbol)
        if frame is None:
            logger.error(f"[{symbol}] Cannot backtest — no data")
            continue

        df = frame.to_dataframe()
        trades = engine.run(symbol, df)
        metrics = compute_metrics(trades)

        print(f"\\n{'─'*50}")
        print(f"[BACKTEST] {symbol}")
        print(f"  Trades:        {metrics['total_trades']}")
        print(f"  Win Rate:      {metrics['win_rate']:.1%}")
        print(f"  Avg RR:        {metrics['avg_rr']:.2f}")
        print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"  Max Drawdown:  {metrics['max_drawdown_pct']:.1%}")
        print(f"  Sharpe:        {metrics['sharpe_ratio']:.2f}")
        print(f"  Expectancy:    {metrics['expectancy_pct']:.2%}/trade")


def main():
    parser = argparse.ArgumentParser(description="Kronos Trading Bot")
    parser.add_argument("--backtest", action="store_true", help="Run in backtest mode")
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    args = parser.parse_args()

    config = load_config(Path(args.config))

    if args.backtest:
        run_backtest(config)
    else:
        run_live(config)


if __name__ == "__main__":
    main()
\`\`\``
  },
  {
    id: "tests",
    tag: "TESTS",
    color: "#b8e994",
    title: "Tests & Quality Gates",
    content: `# TESTING REQUIREMENTS

Every module must have corresponding unit tests. No module is considered complete without tests.

# tests/test_indicators.py

\`\`\`python
import pytest
import pandas as pd
import numpy as np
from src.indicators.vwap import session_vwap
from src.indicators.atr import wilder_atr

def make_candles(n=100, seed=42) -> pd.DataFrame:
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    high = close + np.abs(np.random.randn(n)) * 0.5
    low = close - np.abs(np.random.randn(n)) * 0.5
    volume = np.random.uniform(100, 1000, n)
    timestamps = pd.date_range("2024-01-01", periods=n, freq="15min").astype(int) // 10**6
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume, "t": timestamps})

class TestVWAP:
    def test_resets_each_day(self):
        df = make_candles(200)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.t)
        # VWAP should reset — values at start of day 2 should not equal continuation of day 1
        assert not result.isna().all()

    def test_nan_for_early_session(self):
        df = make_candles(50)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.t, min_candles=5)
        # First 5 candles of each session = NaN
        assert result.isna().sum() > 0

    def test_vwap_between_low_and_high(self):
        df = make_candles(100)
        result = session_vwap(df.high, df.low, df.close, df.volume, df.t)
        valid = result.dropna()
        assert (valid >= df.loc[valid.index, "low"]).all()
        assert (valid <= df.loc[valid.index, "high"]).all()

class TestRisk:
    def test_position_size_respects_risk_pct(self):
        from src.risk.position_sizer import fixed_fraction_size
        result = fixed_fraction_size(10000, 0.01, entry=50000, sl=49000, max_position_usd=2000)
        assert result.risk_usd <= 10000 * 0.01 * 1.01  # within 1% tolerance

    def test_max_position_cap_applied(self):
        from src.risk.position_sizer import fixed_fraction_size
        result = fixed_fraction_size(10000, 0.01, entry=50000, sl=49999, max_position_usd=500)
        assert result.is_capped
        assert result.position_size_contracts * 50000 <= 501

    def test_rr_ratio_minimum_enforced(self):
        from src.risk.sl_tp import atr_based_sltp
        with pytest.raises(ValueError):
            atr_based_sltp("LONG", 100, atr=1.0, sl_mult=3.0, tp_mult=1.0, min_rr=1.5)
\`\`\`

# CODE QUALITY REQUIREMENTS

Add to pyproject.toml:
\`\`\`toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "N", "UP", "ANN"]

[tool.mypy]
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short -q"
\`\`\`

CI check before any deploy:
\`\`\`bash
ruff check src/ tests/
mypy src/
pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80
\`\`\``
  },
  {
    id: "deploy",
    tag: "DEPLOY",
    color: "#74b9ff",
    title: "Deployment",
    content: `# Dockerfile

\`\`\`dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install deps in layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Health check — verify config loads
RUN python -c "from config.loader import load_config; load_config()"

# Non-root user
RUN adduser --disabled-password --gecos '' botuser
USER botuser

CMD ["python", "src/bot.py"]
\`\`\`

# docker-compose.yml

\`\`\`yaml
version: "3.9"

services:
  kronos-bot:
    build: .
    container_name: kronos_bot
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    environment:
      - TZ=UTC
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
\`\`\`

# .env (template — never commit real values)

\`\`\`
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
\`\`\`

# requirements.txt

\`\`\`
hyperliquid-python-sdk>=0.6.0
pandas>=2.0.0
pandas-ta>=0.3.14b
pydantic>=2.0.0
pyyaml>=6.0
tenacity>=8.2.0
python-dotenv>=1.0.0
requests>=2.31.0
numpy>=1.24.0

# Dev only
pytest>=7.4.0
pytest-cov>=4.1.0
ruff>=0.1.0
mypy>=1.5.0
\`\`\`

# README.md — Required Sections

1. Architecture diagram (ASCII or mermaid)
2. Quick start (clone → configure .env → docker-compose up)
3. Backtest usage: \`python src/bot.py --backtest\`
4. Config reference — every parameter explained
5. Risk warning disclaimer`
  },
];

// ─────────────────────────────────────────────
// COMPONENT
// ─────────────────────────────────────────────

export default function App() {
  const [active, setActive] = useState("overview");
  const [copied, setCopied] = useState(false);
  const [codeView, setCodeView] = useState(false);

  const current = MODULES.find(m => m.id === active);

  const FULL_PROMPT = MODULES.map(m =>
    `${"═".repeat(60)}\n[${m.tag}] ${m.title}\n${"═".repeat(60)}\n\n${m.content}`
  ).join("\n\n");

  const copy = () => {
    navigator.clipboard.writeText(FULL_PROMPT);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const renderContent = (text) =>
    text.split("\n").map((line, i) => {
      const isH1 = line.startsWith("# ");
      const isH2 = line.startsWith("## ");
      const isCode = line.startsWith("```") || line.startsWith("  ") && line.length > 4;
      const isBullet = line.startsWith("- ");
      const isNum = /^\d+\./.test(line);
      const isParam = line.includes(":") && !line.startsWith(" ") && line.length < 80;

      let color = "#8da3be", fw = 400, fs = 12.5;

      if (isH1) { color = current.color; fw = 800; fs = 15; }
      else if (isH2) { color = "#c9d6e3"; fw = 700; fs = 13; }
      else if (line.startsWith("```")) { color = "#3d5a7a"; fs = 11; }
      else if (isBullet || isNum) { color = "#a8bdd4"; }
      else if (line.includes("PRINCIPLE") || line.includes("REQUIRED") || line.includes("CONSTRAINT")) {
        color = current.color; fw = 600;
      }
      else if (line.trim() === "") return <div key={i} style={{ height: 6 }} />;

      return (
        <div key={i} style={{
          color, fontWeight: fw, fontSize: fs,
          lineHeight: 1.8,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          paddingLeft: (isBullet || isNum) ? 16 : 0,
        }}>
          {line || "\u00A0"}
        </div>
      );
    });

  return (
    <div style={{
      height: "100vh", display: "flex", flexDirection: "column",
      background: "#070b11",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      color: "#8da3be",
      overflow: "hidden",
    }}>

      {/* ── Top bar ── */}
      <div style={{
        background: "#090e18",
        borderBottom: "1px solid #111d2e",
        padding: "13px 24px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexShrink: 0,
        boxShadow: "0 1px 20px rgba(0,0,0,0.5)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {["#ff5f57", "#febc2e", "#28c840"].map(c => (
              <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />
            ))}
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#c9d6e3", letterSpacing: -0.3 }}>
              Kronos Trading Bot
            </div>
            <div style={{ fontSize: 10, color: "#3a5a7a", letterSpacing: 1.5 }}>
              AGENT BUILD PROMPT · PRODUCTION-READY · QUANT STANDARD
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{
            fontSize: 10, padding: "4px 12px", borderRadius: 20,
            background: "#0d1a2e", border: "1px solid #1a3a5a",
            color: "#3a7abd",
          }}>
            {MODULES.length} modules · {Object.keys(MODULES).length > 0 ? `${Math.round(FULL_PROMPT.length / 3.8).toLocaleString()} tokens` : ""}
          </div>
          <button onClick={copy} style={{
            background: copied ? "#081a0e" : "#0a1628",
            color: copied ? "#00e676" : "#54a0ff",
            border: `1px solid ${copied ? "#00c853" : "#1a4a9a"}`,
            borderRadius: 7, padding: "7px 16px",
            fontSize: 11, fontWeight: 700, cursor: "pointer",
            fontFamily: "inherit", letterSpacing: 0.5,
            transition: "all 0.2s",
          }}>
            {copied ? "✓ Copied" : "⬜ Copy Full Prompt"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Sidebar ── */}
        <div style={{
          width: 200, background: "#080c16",
          borderRight: "1px solid #0f1a2a",
          overflowY: "auto", flexShrink: 0,
          padding: "12px 0",
        }}>
          {MODULES.map(m => (
            <div
              key={m.id}
              onClick={() => setActive(m.id)}
              style={{
                padding: "9px 16px",
                cursor: "pointer",
                borderLeft: `2px solid ${active === m.id ? m.color : "transparent"}`,
                background: active === m.id ? `${m.color}0d` : "transparent",
                transition: "all 0.12s",
              }}
            >
              <div style={{
                fontSize: 9, letterSpacing: 1.5, textTransform: "uppercase",
                color: active === m.id ? m.color : "#2a4a6a",
                fontWeight: 700, marginBottom: 2,
              }}>
                {m.tag}
              </div>
              <div style={{
                fontSize: 11, color: active === m.id ? "#c9d6e3" : "#3d5a7a",
                lineHeight: 1.4,
              }}>
                {m.title}
              </div>
            </div>
          ))}
        </div>

        {/* ── Main panel ── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Module header */}
          <div style={{
            background: "#090e18",
            borderBottom: "1px solid #111d2e",
            padding: "12px 24px",
            display: "flex", alignItems: "center", justifyContent: "space-between",
            flexShrink: 0,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 8, height: 8, borderRadius: "50%",
                background: current.color,
                boxShadow: `0 0 8px ${current.color}`,
              }} />
              <span style={{ color: current.color, fontSize: 10, letterSpacing: 2, fontWeight: 700 }}>
                {current.tag}
              </span>
              <span style={{ color: "#2a4a6a" }}>·</span>
              <span style={{ color: "#8da3be", fontSize: 12 }}>{current.title}</span>
            </div>
            <div style={{ fontSize: 10, color: "#2a4a6a" }}>
              {MODULES.findIndex(m => m.id === active) + 1} / {MODULES.length}
            </div>
          </div>

          {/* Content */}
          <div style={{
            flex: 1, overflowY: "auto",
            padding: "24px 32px 48px",
            background: "#070b11",
          }}>
            {renderContent(current.content)}
          </div>

          {/* Bottom nav */}
          <div style={{
            background: "#090e18",
            borderTop: "1px solid #111d2e",
            padding: "10px 24px",
            display: "flex", justifyContent: "space-between", alignItems: "center",
            flexShrink: 0,
          }}>
            <button
              onClick={() => {
                const idx = MODULES.findIndex(m => m.id === active);
                if (idx > 0) setActive(MODULES[idx - 1].id);
              }}
              disabled={MODULES.findIndex(m => m.id === active) === 0}
              style={{
                background: "transparent", border: "1px solid #1a2a3a",
                color: "#3a6a9a", borderRadius: 6, padding: "6px 14px",
                fontSize: 11, cursor: "pointer", fontFamily: "inherit",
                opacity: MODULES.findIndex(m => m.id === active) === 0 ? 0.3 : 1,
              }}
            >
              ← Prev
            </button>

            <div style={{ display: "flex", gap: 6 }}>
              {MODULES.map((m, i) => (
                <div
                  key={m.id}
                  onClick={() => setActive(m.id)}
                  style={{
                    width: active === m.id ? 20 : 6,
                    height: 6, borderRadius: 3,
                    background: active === m.id ? m.color : "#1a2a3a",
                    cursor: "pointer",
                    transition: "all 0.2s",
                  }}
                />
              ))}
            </div>

            <button
              onClick={() => {
                const idx = MODULES.findIndex(m => m.id === active);
                if (idx < MODULES.length - 1) setActive(MODULES[idx + 1].id);
              }}
              disabled={MODULES.findIndex(m => m.id === active) === MODULES.length - 1}
              style={{
                background: "transparent", border: "1px solid #1a2a3a",
                color: "#3a6a9a", borderRadius: 6, padding: "6px 14px",
                fontSize: 11, cursor: "pointer", fontFamily: "inherit",
                opacity: MODULES.findIndex(m => m.id === active) === MODULES.length - 1 ? 0.3 : 1,
              }}
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
