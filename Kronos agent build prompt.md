# AGENT BUILD PROMPT — Kronos Trading Bot
> Production-ready · Modular · Quant Engineer Standard

---

## ROLE

You are a senior quantitative engineer with 10+ years experience building production trading systems at hedge funds and prop desks. You write clean, typed, testable Python. You think in terms of **risk first, alpha second**.

---

## MISSION

Build a complete, production-ready algorithmic trading bot for Hyperliquid perpetuals **from scratch**. The codebase must be modular, fully typed, thoroughly documented, and deployable via Docker. Every design decision must be justifiable from a risk management perspective.

**Strategy:**
- Universe: BTC, ETH, SOL, LINK, HYPE perpetuals on Hyperliquid
- Signal source: Kronos AI model (transformer-based price forecaster) + technical confirmation (RSI, VWAP, ATR)
- Timeframe: 15-minute candles
- Execution: Signal-only bot (generates alerts to Telegram). No direct order execution in v1.

**Core Principles:**
1. Risk management is non-negotiable — every trade has a defined max loss before entry
2. No magic numbers — all parameters live in config files with documented rationale
3. Fail loudly — errors must surface immediately, never silently swallowed
4. Observable — every decision is logged with full context for post-hoc analysis
5. Testable — every module has unit tests, strategy logic has backtest harness

---

## PROJECT STRUCTURE

Build the following exact directory structure. **Every file listed must be created.**

```
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
│   │   └── schemas.py         # Pydantic models: Candle, OHLCVFrame
│   │
│   ├── indicators/
│   │   ├── __init__.py
│   │   ├── vwap.py            # Session-reset VWAP
│   │   ├── atr.py             # ATR with Wilder smoothing
│   │   ├── rsi.py             # RSI with configurable length
│   │   └── volume.py          # Volume MA + ratio
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── kronos.py          # Kronos model wrapper (load-once singleton)
│   │   ├── filters.py         # Entry condition logic
│   │   └── composer.py        # Combines Kronos + filters → TradeSignal
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── position_sizer.py  # Fixed-fraction sizing
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
│   └── bot.py                 # Main orchestrator
│
├── tests/
│   ├── test_indicators.py
│   ├── test_risk.py
│   ├── test_signals.py
│   └── test_backtest.py
│
├── scripts/
│   └── run_backtest.py
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## MODULE 1 — CONFIG LAYER

### `config/settings.yaml`

```yaml
# ── UNIVERSE ──────────────────────────────────────────
symbols: [BTC, ETH, SOL, LINK, HYPE]
timeframe: "15m"
lookback_candles: 150        # enough for multi-day VWAP history

# ── KRONOS MODEL ──────────────────────────────────────
kronos:
  model_id: "NeoQuasar/Kronos-small"
  pred_len: 4                 # forecast 4 candles = 1h ahead
  threshold_pct: 0.5          # min % change to classify UP/DOWN
  device: "cpu"

# ── INDICATORS ────────────────────────────────────────
indicators:
  rsi_length: 14
  atr_length: 14
  volume_ma_length: 20
  vwap_min_candles: 5         # min candles before VWAP is trusted

# ── ENTRY FILTERS ─────────────────────────────────────
filters:
  long:
    rsi_min: 40
    rsi_max: 70
    require_price_above_vwap: true
    volume_ratio_min: 1.2
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
  min_rr_ratio: 1.5           # reject trades where RR < 1.5

# ── CIRCUIT BREAKERS ──────────────────────────────────
circuit_breakers:
  max_daily_loss_pct: 0.03    # halt if simulated daily loss > 3%
  max_consecutive_losses: 4   # halt after 4 losses in a row
  cooldown_minutes: 120       # resume after 2h

# ── DEDUPLICATION ─────────────────────────────────────
dedup:
  cooldown_candles: 4         # same symbol needs 4 candles (1h) gap
  price_tolerance_pct: 0.005  # signals within 0.5% of prior entry = duplicate

# ── SCHEDULER ─────────────────────────────────────────
scheduler:
  cycle_seconds: 900
  symbol_delay_seconds: 2

# ── TELEGRAM ──────────────────────────────────────────
telegram:
  parse_mode: "HTML"
  send_no_signal: false       # never spam no-signal messages
  send_daily_summary: true
  summary_hour_utc: 0
```

### Config Loading Pattern

```python
from pathlib import Path
import yaml
from pydantic import BaseModel

class Config(BaseModel):
    # Nested Pydantic models matching YAML structure
    ...

def load_config(path: Path = Path("config/settings.yaml")) -> Config:
    with open(path) as f:
        return Config(**yaml.safe_load(f))
```

---

## MODULE 2 — DATA LAYER

### `src/data/schemas.py`

```python
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
```

### `src/data/fetcher.py`

```python
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import logging

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
    def fetch(self, symbol: str) -> OHLCVFrame | None:
        """Fetch candles. Retries 3× with 2s backoff. Raises on malformed data."""
        ...

    def fetch_all(self, symbols: list[str]) -> dict[str, OHLCVFrame | None]:
        """Fetch all symbols with per-symbol error isolation."""
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.fetch(sym)
                self._failure_counts[sym] = 0
            except Exception as e:
                logger.error(f"[{sym}] Fetch failed after 3 retries: {e}")
                self._failure_counts[sym] = self._failure_counts.get(sym, 0) + 1
                results[sym] = None
        return results
```

---

## MODULE 3 — INDICATOR LAYER

**Principle:** All indicators must be **pure functions**. Input: `pd.Series`. Output: `pd.Series`. No side effects. All NaN propagation must be explicit.

### `src/indicators/vwap.py`

```python
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
    Returns NaN for first <min_candles> of each session.
    """
    typical_price = (high + low + close) / 3
    dates = pd.to_datetime(timestamps, unit="ms").dt.date
    vwap = pd.Series(np.nan, index=close.index)

    for date, grp in close.groupby(dates):
        idx = grp.index
        tp = typical_price.loc[idx]
        vol = volume.loc[idx]
        result = (tp * vol).cumsum() / vol.cumsum()
        result.iloc[:min_candles] = np.nan
        vwap.loc[idx] = result.values

    return vwap
```

### `src/indicators/atr.py`

```python
def wilder_atr(high, low, close, length: int = 14) -> pd.Series:
    """
    ATR using Wilder's smoothing (not simple rolling mean).
    Consistent with TradingView / institutional platforms.
    """
    ...
```

### `src/indicators/rsi.py`

```python
def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """
    RSI using Wilder's smoothing.
    Returns [0, 100]. NaN for first <length> candles.
    """
    ...
```

### `src/indicators/volume.py`

```python
def volume_ratio(volume: pd.Series, ma_length: int = 20) -> pd.Series:
    """
    current_volume / rolling_mean(volume, ma_length).
    Values > 1.2 = elevated volume (confirmation threshold).
    """
    ...
```

---

## MODULE 4 — SIGNAL LAYER

### `src/signals/kronos.py` — Singleton Pattern

```python
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class KronosResult:
    signal: str               # "UP" | "DOWN" | "NEUTRAL"
    predicted_close: Optional[float]
    change_pct: float         # single source of truth for predicted % change

class KronosPredictor:
    """
    Singleton. Model loaded ONCE at startup. Never reload mid-session.
    """
    _instance: Optional['KronosPredictor'] = None

    def __new__(cls, config) -> 'KronosPredictor':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def load(self, config) -> None:
        if self._loaded:
            return
        logger.info("Loading Kronos model — once at startup")
        try:
            # initialize tokenizer + model + predictor
            self._loaded = True
        except Exception as e:
            logger.critical(f"Kronos model load failed: {e}")
            raise SystemExit(1)

    def predict(self, df, pred_len: int, threshold_pct: float) -> KronosResult:
        ...
```

### `src/signals/composer.py` — Trade Signal Type

```python
from dataclasses import dataclass
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
        return (
            self.sl > 0
            and self.tp > 0
            and self.rr_ratio >= 1.5
            and self.position_size_contracts > 0
        )
```

### `src/signals/filters.py`

```python
def check_long_entry(
    close: float, rsi: float, vwap: float,
    volume_ratio: float, config
) -> tuple[bool, str]:
    """
    Returns (can_enter, rejection_reason).
    All conditions are AND-gated.
    """
    if close <= vwap:
        return False, "price below VWAP"
    if not (config.rsi_min <= rsi <= config.rsi_max):
        return False, f"RSI {rsi:.1f} out of range"
    if volume_ratio < config.volume_ratio_min:
        return False, f"volume ratio {volume_ratio:.2f} below threshold"
    return True, ""
```

---

## MODULE 5 — RISK LAYER

> **Build this first. Test this most.**

### `src/risk/position_sizer.py`

```python
from dataclasses import dataclass

@dataclass
class SizingResult:
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

    Formula:
        risk_usd = account_size * risk_pct
        risk_per_contract = |entry - sl|
        size = risk_usd / risk_per_contract

    max_position_usd is a hard cap regardless of formula output.
    """
    risk_usd = account_size * risk_pct
    risk_per_contract = abs(entry - sl)

    if risk_per_contract < 1e-8:
        raise ValueError("SL too close to entry — division by near-zero")

    raw_size = risk_usd / risk_per_contract
    is_capped = (raw_size * entry) > max_position_usd
    if is_capped:
        raw_size = max_position_usd / entry

    return SizingResult(
        position_size_contracts=round(raw_size, 4),
        risk_usd=round(risk_per_contract * raw_size, 2),
        is_capped=is_capped,
    )
```

### `src/risk/sl_tp.py`

```python
from dataclasses import dataclass

@dataclass
class SLTP:
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
    Raises ValueError if resulting RR < min_rr.
    """
    if direction == "LONG":
        sl, tp = entry - sl_mult * atr, entry + tp_mult * atr
    else:
        sl, tp = entry + sl_mult * atr, entry - tp_mult * atr

    rr = abs(tp - entry) / abs(entry - sl)
    if rr < min_rr:
        raise ValueError(f"RR {rr:.2f} below minimum {min_rr}")

    return SLTP(sl=round(sl, 6), tp=round(tp, 6), rr_ratio=round(rr, 2))
```

### `src/risk/circuit_breaker.py`

```python
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """
    Halts signal generation when loss thresholds are breached.
    Resets daily at 00:00 UTC.
    """

    def __init__(self, config):
        self.config = config
        self._daily_loss_usd: float = 0.0
        self._consecutive_losses: int = 0
        self._halted_until: Optional[datetime] = None

    def record_outcome(self, pnl_usd: float) -> None:
        if pnl_usd < 0:
            self._daily_loss_usd += abs(pnl_usd)
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def is_halted(self, account_size: float) -> tuple[bool, str]:
        now = datetime.utcnow()
        if self._halted_until and now < self._halted_until:
            mins = (self._halted_until - now).seconds // 60
            return True, f"Circuit breaker active — {mins}min remaining"

        if self._daily_loss_usd / account_size >= self.config.max_daily_loss_pct:
            self._trigger_halt("daily loss limit breached")
            return True, "Daily loss limit breached"

        if self._consecutive_losses >= self.config.max_consecutive_losses:
            self._trigger_halt(f"{self._consecutive_losses} consecutive losses")
            return True, f"{self._consecutive_losses} consecutive losses"

        return False, ""

    def _trigger_halt(self, reason: str) -> None:
        self._halted_until = datetime.utcnow() + timedelta(minutes=self.config.cooldown_minutes)
        logger.warning(f"⚠️ CIRCUIT BREAKER: {reason}. Halted {self.config.cooldown_minutes}min")
```

---

## MODULE 6 — STATE TRACKER

### `src/state/tracker.py`

```python
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
    candle_count: int = 0

@dataclass
class SignalTracker:
    """
    Responsibilities:
    1. Deduplication — prevent re-entry on same signal
    2. Virtual P&L — feeds circuit breaker
    3. Lifecycle — detect SL/TP hits each cycle
    """
    cooldown_candles: int
    price_tolerance_pct: float
    _open: dict[str, OpenSignal] = field(default_factory=dict)

    def is_duplicate(self, symbol: str, direction: str, entry: float) -> bool:
        if symbol not in self._open:
            return False
        prev = self._open[symbol]
        return (
            prev.direction == direction
            and abs(prev.entry_price - entry) / prev.entry_price < self.price_tolerance_pct
            and prev.candle_count < self.cooldown_candles
        )

    def register(self, signal) -> None:
        self._open[signal.symbol] = OpenSignal(
            symbol=signal.symbol, direction=signal.direction,
            entry_price=signal.entry_price, sl=signal.sl,
            tp=signal.tp, timestamp=datetime.utcnow(),
        )

    def update(self, current_prices: dict[str, float]) -> list[dict]:
        """Advance one candle. Returns list of closed trade outcomes."""
        outcomes, to_close = [], []

        for sym, sig in self._open.items():
            price = current_prices.get(sym)
            if price is None:
                continue
            sig.candle_count += 1

            hit_sl = (sig.direction == "LONG" and price <= sig.sl) or \
                     (sig.direction == "SHORT" and price >= sig.sl)
            hit_tp = (sig.direction == "LONG" and price >= sig.tp) or \
                     (sig.direction == "SHORT" and price <= sig.tp)

            if hit_sl or hit_tp:
                result = "TP" if hit_tp else "SL"
                ref = sig.tp if hit_tp else sig.sl
                pnl = (ref - sig.entry_price) / sig.entry_price
                if sig.direction == "SHORT":
                    pnl = -pnl
                outcomes.append({"symbol": sym, "result": result, "pnl_pct": pnl})
                to_close.append(sym)
                logger.info(f"[{sym}] {sig.direction} closed: {result} pnl={pnl:.2%}")

        for sym in to_close:
            del self._open[sym]

        return outcomes
```

---

## MODULE 7 — BACKTEST ENGINE

### `src/backtest/engine.py`

```python
from dataclasses import dataclass
from typing import Optional
import pandas as pd

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

class BacktestEngine:
    """
    Walk-forward backtest. No look-ahead.
    Each candle i uses only data available at candles [0..i].
    No re-entry while trade is open on same symbol.
    """

    def __init__(self, config, max_hold_candles: int = 8):
        self.config = config
        self.max_hold_candles = max_hold_candles   # 8 × 15min = 2h timeout

    def run(self, symbol: str, df: pd.DataFrame) -> list[TradeRecord]:
        trades = []
        open_trade: Optional[TradeRecord] = None
        min_candles = 50

        for i in range(min_candles, len(df)):
            window = df.iloc[:i + 1].copy()

            if open_trade is not None:
                open_trade = self._check_exit(open_trade, window.iloc[-1], i, trades)
                continue

            signal = self._get_signal(symbol, window)
            if signal is None:
                continue

            open_trade = TradeRecord(
                symbol=symbol, direction=signal.direction,
                entry_price=signal.entry_price, sl=signal.sl,
                tp=signal.tp, entry_candle=i,
            )

        return trades
```

### `src/backtest/metrics.py`

```python
import numpy as np
import pandas as pd

def compute_metrics(trades: list) -> dict:
    if not trades:
        return {"error": "no trades"}

    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    equity = pd.Series(pnls).add(1).cumprod()
    drawdown = (equity - equity.cummax()) / equity.cummax()
    sharpe = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252 * 96) if np.std(pnls) > 0 else 0

    return {
        "total_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_win_pct": np.mean(wins) if wins else 0,
        "avg_loss_pct": np.mean(losses) if losses else 0,
        "avg_rr": abs(np.mean(wins) / np.mean(losses)) if wins and losses else 0,
        "profit_factor": abs(sum(wins) / sum(losses)) if losses else float("inf"),
        "max_drawdown_pct": drawdown.min(),
        "sharpe_ratio": sharpe,
        "expectancy_pct": np.mean(pnls),
        "total_return_pct": equity.iloc[-1] - 1,
    }
```

---

## MODULE 8 — MAIN ORCHESTRATOR

### `src/bot.py`

```python
#!/usr/bin/env python3
"""
Kronos Trading Bot — Main Orchestrator
All business logic lives in submodules. This file only coordinates flow.
"""

import argparse
import logging
import time
from pathlib import Path

from src.data.fetcher import HyperliquidFetcher
from src.signals.kronos import KronosPredictor
from src.signals.composer import SignalComposer
from src.risk.circuit_breaker import CircuitBreaker
from src.state.tracker import SignalTracker
from src.execution.notifier import TelegramNotifier
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import compute_metrics
from config.loader import load_config

logger = logging.getLogger("kronos_bot")


def run_live(config) -> None:

    # ── Load model ONCE ──────────────────────────────
    kronos = KronosPredictor(config.kronos)
    kronos.load(config.kronos)

    fetcher    = HyperliquidFetcher(config)
    composer   = SignalComposer(config)
    circuit    = CircuitBreaker(config.circuit_breakers)
    tracker    = SignalTracker(config.dedup)
    notifier   = TelegramNotifier(config.telegram)

    logger.info(f"Bot started | {config.symbols} | {config.timeframe}")
    cycle = 0

    while True:
        cycle += 1
        logger.info(f"─── Cycle {cycle} @ {time.strftime('%H:%M:%S UTC', time.gmtime())} ───")

        frames = fetcher.fetch_all(config.symbols)
        current_prices = {
            sym: float(f.candles[-1].close)
            for sym, f in frames.items() if f
        }

        # Update open signals, collect SL/TP outcomes
        for outcome in tracker.update(current_prices):
            circuit.record_outcome(outcome["pnl_pct"] * config.risk.account_size_usd)
            notifier.send_outcome(outcome)

        # Check circuit breaker before processing signals
        halted, reason = circuit.is_halted(config.risk.account_size_usd)
        if halted:
            logger.warning(f"🚨 HALTED: {reason}")
            time.sleep(config.scheduler.cycle_seconds)
            continue

        for symbol, frame in frames.items():
            if frame is None or len(frame.candles) < 50:
                continue

            try:
                signal = composer.compose(symbol, frame.to_dataframe(), kronos)
            except Exception as e:
                logger.error(f"[{symbol}] Compose error: {e}", exc_info=True)
                continue

            if signal is None or not signal.is_valid():
                continue

            if tracker.is_duplicate(symbol, signal.direction, signal.entry_price):
                logger.info(f"[{symbol}] Duplicate suppressed")
                continue

            notifier.send_signal(signal)
            tracker.register(signal)
            logger.info(f"[{symbol}] ✅ {signal.direction} @ {signal.entry_price:.4f}")
            time.sleep(config.scheduler.symbol_delay_seconds)

        time.sleep(config.scheduler.cycle_seconds)


def run_backtest(config) -> None:
    logger.info("BACKTEST MODE")
    kronos = KronosPredictor(config.kronos)
    kronos.load(config.kronos)
    engine = BacktestEngine(config)
    fetcher = HyperliquidFetcher(config, lookback=500)

    for symbol in config.symbols:
        frame = fetcher.fetch(symbol)
        if frame is None:
            logger.error(f"[{symbol}] No data for backtest")
            continue

        trades = engine.run(symbol, frame.to_dataframe())
        m = compute_metrics(trades)

        print(f"\n{'─'*50}")
        print(f"[BACKTEST] {symbol}")
        print(f"  Trades:        {m['total_trades']}")
        print(f"  Win Rate:      {m['win_rate']:.1%}")
        print(f"  Avg RR:        {m['avg_rr']:.2f}")
        print(f"  Profit Factor: {m['profit_factor']:.2f}")
        print(f"  Max Drawdown:  {m['max_drawdown_pct']:.1%}")
        print(f"  Sharpe:        {m['sharpe_ratio']:.2f}")
        print(f"  Expectancy:    {m['expectancy_pct']:.2%}/trade")


def main():
    parser = argparse.ArgumentParser(description="Kronos Trading Bot")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--config", default="config/settings.yaml")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    run_backtest(config) if args.backtest else run_live(config)


if __name__ == "__main__":
    main()
```

---

## MODULE 9 — LOGGING

### Setup in `src/bot.py` (top of file)

```python
import logging
from logging.handlers import TimedRotatingFileHandler

def setup_logging() -> None:
    logger = logging.getLogger("kronos_bot")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    # File: rotate daily, keep 7 days
    fh = TimedRotatingFileHandler("logs/kronos_bot.log", when="midnight", backupCount=7, utc=True)
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    # Console: INFO and above
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    sh.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(sh)
```

---

## MODULE 10 — TESTS

Every module must have unit tests. **No module is complete without tests.**

### `tests/test_indicators.py`

```python
import pytest
import pandas as pd
import numpy as np
from src.indicators.vwap import session_vwap
from src.indicators.atr import wilder_atr

def make_candles(n=100, seed=42) -> pd.DataFrame:
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    high  = close + np.abs(np.random.randn(n)) * 0.5
    low   = close - np.abs(np.random.randn(n)) * 0.5
    vol   = np.random.uniform(100, 1000, n)
    ts    = pd.date_range("2024-01-01", periods=n, freq="15min").astype(int) // 10**6
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": vol, "t": ts})

def test_vwap_nan_early_session():
    df = make_candles(50)
    result = session_vwap(df.high, df.low, df.close, df.volume, df.t, min_candles=5)
    assert result.isna().sum() > 0

def test_vwap_between_high_low():
    df = make_candles(100)
    result = session_vwap(df.high, df.low, df.close, df.volume, df.t)
    valid = result.dropna()
    assert (valid >= df.loc[valid.index, "low"]).all()
    assert (valid <= df.loc[valid.index, "high"]).all()
```

### `tests/test_risk.py`

```python
import pytest
from src.risk.position_sizer import fixed_fraction_size
from src.risk.sl_tp import atr_based_sltp

def test_position_size_within_risk():
    r = fixed_fraction_size(10000, 0.01, entry=50000, sl=49000, max_position_usd=2000)
    assert r.risk_usd <= 10000 * 0.01 * 1.01

def test_max_position_cap():
    r = fixed_fraction_size(10000, 0.01, entry=50000, sl=49999, max_position_usd=500)
    assert r.is_capped
    assert r.position_size_contracts * 50000 <= 501

def test_rr_minimum_enforced():
    with pytest.raises(ValueError):
        atr_based_sltp("LONG", 100, atr=1.0, sl_mult=3.0, tp_mult=1.0, min_rr=1.5)

def test_long_sltp_correct_direction():
    r = atr_based_sltp("LONG", 100, atr=1.0)
    assert r.sl < 100 < r.tp

def test_short_sltp_correct_direction():
    r = atr_based_sltp("SHORT", 100, atr=1.0)
    assert r.tp < 100 < r.sl
```

---

## MODULE 11 — DEPLOYMENT

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verify config loads at build time
RUN python -c "from config.loader import load_config; load_config()"

RUN adduser --disabled-password --gecos '' botuser
USER botuser

CMD ["python", "src/bot.py"]
```

### `docker-compose.yml`

```yaml
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
```

### `requirements.txt`

```
hyperliquid-python-sdk>=0.6.0
pandas>=2.0.0
pandas-ta>=0.3.14b
pydantic>=2.0.0
pyyaml>=6.0
tenacity>=8.2.0
python-dotenv>=1.0.0
requests>=2.31.0
numpy>=1.24.0

# Dev
pytest>=7.4.0
pytest-cov>=4.1.0
ruff>=0.1.0
mypy>=1.5.0
```

### `pyproject.toml`

```toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "N", "UP", "ANN"]

[tool.mypy]
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short -q"
```

---

## CODE QUALITY GATES

Run before every deploy:

```bash
ruff check src/ tests/
mypy src/
pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80
```

---

## USAGE

```bash
# Live mode
python src/bot.py

# Backtest mode
python src/bot.py --backtest

# Custom config
python src/bot.py --config config/settings_prod.yaml

# Docker
docker-compose up -d
docker-compose logs -f kronos-bot
```

---

## README REQUIRED SECTIONS

1. Architecture diagram (ASCII or mermaid)
2. Quick start: clone → configure `.env` → `docker-compose up`
3. Backtest usage and interpreting output
4. Config reference — every parameter explained
5. Risk warning disclaimer

---

*Generated for Kronos Trading Bot · Quant Engineer Standard · Production-Ready*
