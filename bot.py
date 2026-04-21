#!/usr/bin/env python3
"""
Kronos + Hyperliquid Bot (Multi-Symbol)
- AI predictions for BTC, ETH, HYPE, SOL, ADA, LINK
- Telegram alerts when signal detected
- Paper trading mode
"""

import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model.kronos import KronosPredictor
from hyperliquid.utils import constants
from hyperliquid.info import Info

load_dotenv()

# Config
SYMBOLS = ["BTC", "ETH", "HYPE", "SOL", "ADA", "LINK"]
TIMEFRAME = "15m"
PRED_LEN = 4
THRESHOLD = 0.5  # 0.5% predicted change

# Telegram config from environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CYCLE_WAIT = 900  # 15 minutes

def send_telegram(message):
    """Send alert to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] No config, skipping")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def load_kronos():
    """Load Kronos model"""
    print("Loading Kronos model (downloading if first time)...")
    try:
        from model.kronos import KronosTokenizer, Kronos
        # Build tokenizer with BSQuantizer params (from config, not stored in HF config)
        tokenizer = KronosTokenizer(
            d_in=6, d_model=256, n_heads=4, ff_dim=512,
            n_enc_layers=4, n_dec_layers=4,
            ffn_dropout_p=0.0, attn_dropout_p=0.0, resid_dropout_p=0.0,
            s1_bits=10, s2_bits=10,
            beta=0.05, gamma0=1.0, gamma=1.1, zeta=0.05, group_size=4
        )
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        device = "cpu"  # auto-detect would check torch.cuda.is_available()
        predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
        print("Kronos loaded")
        return predictor
    except Exception as e:
        print(f"Kronos load failed: {e}")
        return None


def get_candles(symbol, interval="15m", limit=100):
    """Fetch candles from Hyperliquid"""
    try:
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        end_time = int(time.time() * 1000)
        start_time = end_time - limit * 15 * 60 * 1000
        data = info.candles_snapshot(name=symbol, interval=interval, startTime=start_time, endTime=end_time)
        if data:
            df = pd.DataFrame(data)
            df = df.rename(columns={"o": "open", "c": "close", "h": "high", "l": "low", "v": "volume"})
            for col in ["open", "close", "high", "low", "volume"]:
                df[col] = df[col].astype(float)
            return df
        return None
    except Exception as e:
        print(f"[{symbol}] Hyperliquid error: {e}")
        return None


def predict(predictor, df, symbol):
    """Get Kronos prediction"""
    if predictor is None:
        return None
    try:
        from model.kronos import KronosPredictor as Pred
        last_ts = pd.to_datetime(df["t"].iloc[-1], unit="ms")
        pred_ts = pd.date_range(start=last_ts + timedelta(minutes=15), periods=PRED_LEN, freq="15min")
        pred_df = predictor.predict(
            df=df,
            x_timestamp=pd.Series(pd.to_datetime(df["t"], unit="ms").values),
            y_timestamp=pred_ts,
            pred_len=PRED_LEN
        )
        if len(pred_df) > 0:
            return pred_df["close"].iloc[-1]
        return None
    except Exception as e:
        print(f"[{symbol}] Prediction error: {e}")
        return None


def format_price(price):
    """Format price nicely"""
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    else:
        return f"${price:.6f}"


def main():
    print("=" * 50)
    print("Kronos-Hyperliquid Multi-Symbol Bot")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print("=" * 50)

    predictor = load_kronos()
    if predictor is None:
        print("Fatal: Kronos failed to load")
        return

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now().strftime("%H:%M")
        print(f"\n[{ts}] Cycle {cycle}")

        signals_found = []
        for symbol in SYMBOLS:
            print(f"  Checking {symbol}...")
            df = get_candles(symbol)
            if df is None or len(df) < 50:
                print(f"  [{symbol}] No data")
                continue

            current_price = float(df["close"].iloc[-1])
            predicted = predict(predictor, df, symbol)

            if predicted:
                change = ((predicted - current_price) / current_price) * 100
                print(f"  [{symbol}] Price: {format_price(current_price)} | Predicted: {format_price(predicted)} ({change:+.2f}%)")

                action = None
                if change > THRESHOLD:
                    action = "LONG"
                elif change < -THRESHOLD:
                    action = "SHORT"

                if action:
                    msg = f"""🔔 Kronos Signal: {action}

Symbol: {symbol}
Price: {format_price(current_price)}
Predicted: {format_price(predicted)} ({change:+.2f}%)
Timeframe: {TIMEFRAME}
Time: {datetime.now().strftime("%H:%M")}"""
                    send_telegram(msg)
                    signals_found.append(f"{symbol}: {action} {change:+.2f}%")

            if symbol != SYMBOLS[-1]:
                time.sleep(2)

        if signals_found:
            print(f"\nSignals this cycle: {len(signals_found)}")
        else:
            print("\nNo signals - sending heartbeat")
            msg = f"""🤖 Kronos Bot - No Signal

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
📊 Symbols checked: {', '.join(SYMBOLS)}
💚 Status: Running (no signals above threshold)

Next check in {CYCLE_WAIT // 60} min"""
            send_telegram(msg)

        print(f"Waiting {CYCLE_WAIT // 60} min...")
        time.sleep(CYCLE_WAIT)


if __name__ == "__main__":
    main()
