#!/usr/bin/env python3
"""
Kronos + Hyperliquid Bot
- AI predictions from Kronos model
- Telegram alerts when entry signal detected
- Paper trading mode (no real trades)
"""

import os
import time
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from kronos import KronosPredictor
from hyperliquid.utils import constants
from hyperliquid.info import Info
import requests

load_dotenv()

# Config
SYMBOL = "BTC"
TIMEFRAME = "15m"
PRED_LEN = 4
THRESHOLD = 0.5  # 0.5% predicted change
TELEGRAM_BOT_TOKEN = "8796391383:AAG3RNsFSC1StHsKiHdVxqqE-h6AtkDw4T4"
TELEGRAM_CHAT_ID = "427107923"


def send_telegram(message):
    """Send alert to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM] No config, skipping: {message}")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def load_kronos():
    """Load Kronos model"""
    print("Loading Kronos model (first time downloads if needed)...")
    try:
        predictor = KronosPredictor("NeoQuasar/Kronos-small", device="cuda")
        print("Kronos loaded")
        return predictor
    except Exception as e:
        print(f"Kronos load failed: {e}")
        return None


def get_candles(symbol, interval="15m", limit=100):
    """Fetch candles from Hyperliquid"""
    try:
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        data = info.candles(symbol, interval=interval, limit=limit)
        if data:
            return pd.DataFrame(data)
        return None
    except Exception as e:
        print(f"Hyperliquid error: {e}")
        return None


def predict(predictor, df):
    """Get Kronos prediction"""
    if predictor is None:
        return None
    
    try:
        last_ts = pd.to_datetime(df["t"].iloc[-1], unit="ms")
        pred_ts = pd.date_range(start=last_ts + timedelta(minutes=15), periods=PRED_LEN, freq="15min")
        
        pred_df = predictor.predict(
            df=df,
            x_timestamp=pd.to_datetime(df["t"], unit="ms"),
            y_timestamp=pred_ts,
            pred_len=PRED_LEN
        )
        
        if len(pred_df) > 0:
            return pred_df["close"].iloc[-1]
        return None
    except Exception as e:
        print(f"Prediction error: {e}")
        return None


def main():
    print("=" * 50)
    print("Kronos-Hyperliquid Bot (Paper Trading)")
    print("=" * 50)
    
    # Load model
    predictor = load_kronos()
    
    while True:
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S")}] Fetching {SYMBOL} {TIMEFRAME}...")
            df = get_candles(SYMBOL, TIMEFRAME)
            
            if df is None or len(df) < 50:
                print("No data, waiting...")
                time.sleep(60)
                continue
            
            current_price = float(df["c"].iloc[-1])
            print(f"Current price: ${current_price:.2f}")
            
            # Get prediction
            predicted = predict(predictor, df)
            
            if predicted:
                change_pct = ((predicted - current_price) / current_price) * 100
                print(f"Predicted: ${predicted:.2f} ({change_pct:+.2f}%)")
                
                if change_pct > THRESHOLD:
                    msg = f"""🔔 *KRONOS SIGNAL*
                        
Price: ${current_price:.2f}
Predicted: ${predicted:.2f} ({change_pct:+.2f}%)
Action: *LONG*
Time: {datetime.now().strftime('%Y-%m-d %H:%M:%S")}"""
                    send_telegram(msg)
                    print("Alert sent!")
                    
                elif change_pct < -THRESHOLD:
                    msg = f"""🔔 *KRONOS SIGNAL*
                        
Price: ${current_price:.2f}
Predicted: ${predicted:.2f} ({change_pct:+.2f}%)
Action: *SHORT*
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S")}"""
                    send_telegram(msg)
                    print("Alert sent!")
                    
                else:
                    print("No signal")
            
            print("Waiting 15 minutes...")
            time.sleep(900)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
