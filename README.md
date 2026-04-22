# Kronos Trading Bot

Production-ready algorithmic trading bot for Hyperliquid perpetuals using the Kronos AI price forecasting model and technical indicator confirmations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         src/bot.py                              │
│                    Main Orchestrator                            │
└──────────┬──────────┬──────────┬──────────┬──────────┬──────────┘
           │          │          │          │          │
    ┌──────▼──┐ ┌─────▼────┐ ┌──▼───────┐ ┌▼────────┐ ┌──────────┐
    │  data/   │ │ indicators│ │ signals/ │ │  risk/  │ │  state/  │
    │ fetcher  │ │ vwap atr  │ │kronos    │ │position │ │ tracker  │
    │schemas   │ │ rsi vol   │ │filters   │ │sltp     │ │          │
    └──────────┘ └──────────┘ │composer  │ │breaker  │ └──────────┘
                              └──────────┘ └──────────┘
                                              │
                                         ┌────▼────────┐
                                         │ execution/  │
                                         │ notifier   │
                                         └────────────┘
```

---

## Quick Start

### 1. Clone & Configure

```bash
git clone <repo-url>
cd kronos-bot
cp config/settings.yaml config/settings.yaml  # edit as needed
```

Create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
HF_HOME=/app/.cache/huggingface  # optional
```

### 2. Run with Docker

```bash
docker-compose up -d
docker-compose logs -f kronos-bot
```

### 3. Run Locally

```bash
pip install -r requirements.txt
python src/bot.py
```

### 4. Run Backtest

```bash
python src/bot.py --backtest
# or with custom config
python src/bot.py --backtest --config config/settings_prod.yaml
```

---

## Backtest Interpretation

The backtest engine runs a walk-forward simulation (no look-ahead bias) over historical Hyperliquid 15m candle data. It outputs:

| Metric | Description |
|---|---|
| `Trades` | Total number of completed round-trip trades |
| `Win Rate` | Fraction of trades that were profitable |
| `Avg R:R` | Average reward-to-risk ratio of winning trades |
| `Profit Factor` | Gross wins / Gross losses (>1.0 = profitable) |
| `Max Drawdown` | Worst peak-to-trough equity drop |
| `Sharpe` | Risk-adjusted return (annualized) |
| `Sortino` | Downside-risk-adjusted return |
| `Expectancy` | Average return per trade |
| `Total Return` | Cumulative return over the backtest period |

**Important:** Backtest results are not guarantees of future performance. Past performance does not guarantee future results. Markets are non-stationary.

---

## Config Reference

All parameters live in `config/settings.yaml`. Key sections:

### `kronos` — Model configuration
| Parameter | Default | Description |
|---|---|---|
| `model_id` | `"NeoQuasar/Kronos-small"` | HuggingFace model ID |
| `pred_len` | `4` | Number of candles to forecast (4 × 15m = 1h) |
| `threshold_pct` | `0.5` | Min % predicted change to trigger signal |
| `device` | `"cpu"` | Device for inference (`cpu` / `cuda`) |

### `indicators` — Technical indicator parameters
| Parameter | Default | Description |
|---|---|---|
| `rsi_length` | `14` | RSI lookback (Wilder smoothing) |
| `atr_length` | `14` | ATR lookback (Wilder smoothing) |
| `volume_ma_length` | `20` | Volume MA lookback |
| `vwap_min_candles` | `5` | Min candles before VWAP is trusted |

### `risk` — Position sizing & SL/TP
| Parameter | Default | Description |
|---|---|---|
| `account_size_usd` | `10000` | Simulated account size |
| `risk_per_trade_pct` | `0.01` | Max equity risk per trade (1%) |
| `max_position_usd` | `2000` | Hard cap on position notional |
| `sl_atr_mult` | `1.5` | SL = entry ± 1.5 × ATR |
| `tp_atr_mult` | `3.0` | TP = entry ± 3.0 × ATR → RR = 2:1 |
| `min_rr_ratio` | `1.5` | Minimum acceptable RR ratio |

### `circuit_breakers` — Loss control
| Parameter | Default | Description |
|---|---|---|
| `max_daily_loss_pct` | `0.03` | Halt if daily loss exceeds 3% |
| `max_consecutive_losses` | `4` | Halt after 4 consecutive losses |
| `cooldown_minutes` | `120` | Auto-resume after 2 hours |

### `dedup` — Signal deduplication
| Parameter | Default | Description |
|---|---|---|
| `cooldown_candles` | `4` | Same-symbol gap of 4 candles (1h) |
| `price_tolerance_pct` | `0.005` | Entry within 0.5% = duplicate |

---

## Signal Flow

```
Hyperliquid API
     │
     ▼
 HyperliquidFetcher → OHLCVFrame → DataFrame
     │
     ▼
 session_vwap │ wilder_atr │ rsi │ volume_ratio
     │
     ▼
 KronosPredictor (singleton, loaded once at startup)
     │
     ├── "UP"  → check_long_entry()  → composer.compose() → TradeSignal
     ├── "DOWN"→ check_short_entry() → composer.compose() → TradeSignal
     └── "NEUTRAL" → return None

  TradeSignal → dedup check → TelegramNotifier.send_signal() → SignalTracker.register()
                    │
                    ▼
              CircuitBreaker.is_halted() ──► tracker.update() ──► outcomes → record_outcome()
```

---

## Deployment

### Docker

```bash
# Build and start
docker-compose up -d

# One-off backtest via docker-compose
docker-compose run kronos-backtest

# View logs
docker-compose logs -f --tail=100 kronos-bot
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your Telegram chat ID |
| `HF_HOME` | No | HuggingFace cache directory |

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/test_risk.py -v

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

---

## Risk Warning

**This software is for educational and informational purposes only.**

- This bot generates signal notifications to Telegram only — it does NOT execute real trades
- Backtested results do not guarantee future performance
- Cryptocurrency markets are highly volatile and non-stationary
- Never invest more than you can afford to lose
- Always use proper risk management and never over-leverage
- The circuit breaker and position sizing are risk controls, not guarantees against loss

**You are fully responsible for any financial decisions you make.**

---

*Generated for Kronos Trading Bot · Quant Engineer Standard · Production-Ready*