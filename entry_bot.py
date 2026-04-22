#!/usr/bin/env python3
"""
Hyperliquid Kronos Trading Bot
============================
Kết hợp AI dự báo từ Kronos với RSI, VWAP, ATR
để tạo tín hiệu LONG/SHORT gửi Telegram.

Kronos signal: "UP" | "DOWN" | "NEUTRAL"
"""

import os
import time
import math
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CẤU HÌNH
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
SYMBOLS            = ["BTC", "ETH", "SOL", "LINK", "HYPE"]
TIMEFRAME          = "15m"
PRED_LEN           = 4          # số nến dự báo phía trước
THRESHOLD          = 0.5         # % thay đổi giá để trigger Kronos signal
CYCLE_WAIT         = 900         # 15 phút

# Indicators
RSI_LENGTH         = 14
ATR_LENGTH          = 14
VWAP_CONDITION     = "day"       # tính VWAP theo ngày

# Entry filters
RSI_LONG_MIN,  RSI_LONG_MAX  = 40, 70
RSI_SHORT_MIN, RSI_SHORT_MAX = 30, 60

# TP/SL (ATR multiplier)
SL_MULT  = 1.5
TP_MULT  = 3.0

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(text: str) -> bool:
    """Gửi tin nhắn qua Telegram Bot API"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Chưa cấu hình token/chat_id")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "Markdown"
        }, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[Telegram] Lỗi gửi: {e}")
        return False


def format_price(price: float, symbol: str) -> str:
    """Format giá theo từng loại tài sản"""
    if price is None: return "N/A"
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    else:
        return f"${price:.6f}"


# ============================================================
# HYPERLIQUID DATA
# ============================================================
def get_ohlcv(symbol: str, interval: str = "15m", lookback: int = 100) -> pd.DataFrame | None:
    """
    Lấy dữ liệu OHLCV từ Hyperliquid API.

    Args:
        symbol   : mã cặp giao dịch (BTC, ETH, ...)
        interval : khung thời gian (1m, 15m, 1h, 1d)
        lookback : số nến lấy về

    Returns:
        DataFrame với columns: open, high, low, close, volume
    """
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        end_time   = int(time.time() * 1000)
        start_time = end_time - lookback * 15 * 60 * 1000

        data = info.candles_snapshot(
            name=symbol,
            interval=interval,
            startTime=start_time,
            endTime=end_time
        )

        if not data:
            return None

        df = pd.DataFrame(data)
        # Hyperliquid trả về: t, T, s, i, o, c, h, l, v, n
        df = df.rename(columns={
            "o": "open", "c": "close", "h": "high",
            "l": "low",  "v": "volume"
        })

        # Ép kiểu
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()
        df = df.reset_index(drop=True)
        return df

    except Exception as e:
        print(f"[{symbol}] Hyperliquid error: {e}")
        return None


# ============================================================
# INDICATORS (pandas_ta)
# ============================================================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính RSI(14), VWAP, ATR(14) từ dữ liệu OHLCV.

    Indicators:
        - RSI(14)     : Relative Strength Index
        - VWAP        : Volume Weighted Average Price
        - ATR(14)     : Average True Range
    """
    df = df.copy()

    # RSI(14)
    df["rsi"] = ta.rsi(df["close"], length=RSI_LENGTH)

    # ATR(14)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=ATR_LENGTH)

    # VWAP - cần DatetimeIndex
    # Tạo datetime index tạm từ timestamp (ms)
    if "t" in df.columns:
        dt_index = pd.to_datetime(df["t"], unit="ms")
        df_dt = df.set_index(pd.DatetimeIndex(dt_index))
        df_dt["vwap"] = ta.vwap(df_dt["high"], df_dt["low"], df_dt["close"], df_dt["volume"])
        df = df.copy()
        df["vwap"] = df_dt["vwap"].values
    else:
        # Fallback: manual VWAP
        cumvol = (df["close"] * df["volume"]).cumsum()
        cumvol_w = df["volume"].cumsum()
        df["vwap"] = cumvol / cumvol_w

    return df


# ============================================================
# KRONOS SIGNAL
# ============================================================
def get_kronos_signal(df: pd.DataFrame, symbol: str):
    """
    Gọi Kronos model để dự báo và trả về signal UP/DOWN/NEUTRAL.

    Args:
        df     : DataFrame OHLCV (cần ít nhất 50 dòng)
        symbol : mã giao dịch

    Returns:
        str: "UP" | "DOWN" | "NEUTRAL"
        float: giá dự báo cuối cùng hoặc None
    """
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from model.kronos import KronosTokenizer, Kronos, KronosPredictor

        # Load tokenizer + model (đã cached)
        tokenizer = KronosTokenizer(
            d_in=6, d_model=256, n_heads=4, ff_dim=512,
            n_enc_layers=4, n_dec_layers=4,
            ffn_dropout_p=0.0, attn_dropout_p=0.0, resid_dropout_p=0.0,
            s1_bits=10, s2_bits=10,
            beta=0.05, gamma0=1.0, gamma=1.1, zeta=0.05, group_size=4
        )
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

        # Timestamps
        last_ts  = pd.to_datetime(df["t"].iloc[-1], unit="ms")
        pred_ts  = pd.date_range(start=last_ts + timedelta(minutes=15),
                                  periods=PRED_LEN, freq="15min")

        pred_df = predictor.predict(
            df=df,
            x_timestamp=pd.Series(pd.to_datetime(df["t"], unit="ms").values),
            y_timestamp=pred_ts,
            pred_len=PRED_LEN
        )

        if pred_df is None or len(pred_df) == 0:
            return "NEUTRAL", None

        current_price = float(df["close"].iloc[-1])
        predicted_price = float(pred_df["close"].iloc[-1])
        change_pct = ((predicted_price - current_price) / current_price) * 100

        if change_pct > THRESHOLD:
            return "UP", predicted_price
        elif change_pct < -THRESHOLD:
            return "DOWN", predicted_price
        else:
            return "NEUTRAL", predicted_price

    except Exception as e:
        print(f"[{symbol}] Kronos signal error: {e}")
        return "NEUTRAL", None


# ============================================================
# ENTRY LOGIC
# ============================================================
def check_entry_signal(df: pd.DataFrame, kronos_sig: str) -> dict | None:
    """
    Kiểm tra điều kiện vào lệnh dựa trên:
      - Kronos signal (UP/DOWN/NEUTRAL)
      - Giá vs VWAP
      - RSI zone

    Args:
        df         : DataFrame đã có RSI, VWAP, ATR
        kronos_sig : "UP" | "DOWN" | "NEUTRAL"

    Returns:
        dict với keys: direction, entry_price, sl, tp, rsi, vwap, atr
        hoặc None nếu không có signal
    """
    last = df.iloc[-1]
    close  = float(last["close"])
    rsi    = float(last["rsi"])
    vwap   = float(last["vwap"])
    atr    = float(last["atr"])

    # Kiểm tra NaN
    if math.isnan(rsi) or math.isnan(vwap) or math.isnan(atr):
        print(f"  Indicators NaN - RSI:{rsi:.2f} VWAP:{vwap:.4f} ATR:{atr:.4f}")
        return None

    direction = None

    # ---- LONG conditions ----
    if kronos_sig == "UP":
        above_vwap  = close > vwap
        rsi_ok      = RSI_LONG_MIN <= rsi <= RSI_LONG_MAX
        if above_vwap and rsi_ok:
            direction = "LONG"

    # ---- SHORT conditions ----
    elif kronos_sig == "DOWN":
        below_vwap = close < vwap
        rsi_ok     = RSI_SHORT_MIN <= rsi <= RSI_SHORT_MAX
        if below_vwap and rsi_ok:
            direction = "SHORT"

    if direction is None:
        return None

    # TP/SL bằng ATR
    if direction == "LONG":
        sl = close - SL_MULT * atr
        tp = close + TP_MULT * atr
    else:  # SHORT
        sl = close + SL_MULT * atr
        tp = close - TP_MULT * atr

    return {
        "direction":   direction,
        "entry_price": close,
        "sl":          sl,
        "tp":          tp,
        "rsi":         rsi,
        "vwap":        vwap,
        "atr":         atr,
    }


# ============================================================
# FORMAT ALERT
# ============================================================
def format_alert(symbol: str, sig: dict, kronos_sig: str,
                 predicted_price: float | None,
                 change_pct: float = 0.0) -> str:
    """Tạo tin nhắn Telegram format Markdown đẹp"""

    emoji_map = {"UP": "🟢", "DOWN": "🔴", "NEUTRAL": "⚪"}
    emoji_dir = {"LONG": "📈", "SHORT": "📉"}
    emoji_ai  = {"UP": "🚀 Tăng giá", "DOWN": "🔻 Giảm giá", "NEUTRAL": "➡️ Trung lập"}

    direction = sig["direction"]
    entry     = sig["entry_price"]
    sl        = sig["sl"]
    tp        = sig["tp"]
    rsi       = sig["rsi"]
    vwap      = sig["vwap"]
    atr       = sig["atr"]

    direction_text = "LONG" if direction == "LONG" else "SHORT"
    border = "═" * 40

    if direction == "LONG":
        alert_title = "🟢 TÍN HIỆU LONG KÍCH HOẠT 🟢"
        emoji = "📈"
    else:
        alert_title = "🔴 TÍN HIỆU SHORT KÍCH HOẠT 🔴"
        emoji = "📉"

    change_str = f"{change_pct:+.2f}%" if change_pct else ""

    return f"""{border}
{alert_title}
{border}

{emoji} <b>Cặp giao dịch:</b> {symbol}-PERP

🤖 <b>AI Dự báo:</b> {emoji_ai.get(kronos_sig, 'N/A')}
   {f"Mức thay đổi: {change_str}" if change_str else ""}

💰 <b>Giá Entry:</b> {format_price(entry, symbol)}

🎯 <b>Take Profit (TP):</b> {format_price(tp, symbol)}
🛑 <b>Stop Loss (SL):</b> {format_price(sl, symbol)}

📊 <b>Thông số:</b>
   RSI(14): {rsi:.1f}
   VWAP: {format_price(vwap, symbol)}
   ATR(14): {format_price(atr, symbol)}

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}
{border}"""


def format_no_signal(symbol: str, kronos_sig: str, rsi: float,
                     vwap: float, close: float, reason: str = "") -> str:
    """Tin nhắn khi không có signal"""
    vwap_status = "✓ Trên VWAP" if close > vwap else "✗ Dưới VWAP"
    rsi_status  = "Quá mua" if rsi > 70 else ("Quá bán" if rsi < 30 else "Trung lập")

    return f"""🤖 Kronos Bot - No Signal

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
📊 {symbol}-PERP

AI Signal: {kronos_sig}
RSI(14): {rsi:.1f} ({rsi_status})
VWAP: {format_price(vwap, symbol)}
Giá: {format_price(close, symbol)}
Lý do: {reason or 'Không thỏa điều kiện Entry'}"""

# ============================================================
# MAIN LOOP
# ============================================================
def run_cycle():
    """Chạy một cycle kiểm tra tất cả symbols"""
    ts = datetime.now().strftime("%H:%M")
    print(f"\n{'='*50}")
    print(f"[{ts}] Kronos+RSI+VWAP+ATR Bot Cycle")
    print(f"{'='*50}")

    for symbol in SYMBOLS:
        print(f"\n  [{symbol}] Fetching data...")
        df = get_ohlcv(symbol, TIMEFRAME)

        if df is None or len(df) < 50:
            print(f"  [{symbol}] Không lấy được dữ liệu")
            continue

        # Tính indicators
        df = compute_indicators(df)

        # Lấy Kronos signal
        kronos_sig, predicted_price = get_kronos_signal(df, symbol)

        last = df.iloc[-1]
        close = float(last["close"])
        rsi   = float(last["rsi"])
        vwap  = float(last["vwap"])
        atr   = float(last["atr"])

        change_pct = 0.0
        if predicted_price:
            change_pct = ((predicted_price - close) / close) * 100

        print(f"  [{symbol}] Close:{format_price(close,symbol)} "
              f"RSI:{rsi:.1f} VWAP:{format_price(vwap,symbol)} "
              f"ATR:{format_price(atr,symbol)} → Kronos:{kronos_sig} {change_pct:+.2f}%")

        # Kiểm tra entry
        sig = check_entry_signal(df, kronos_sig)

        if sig:
            msg = format_alert(symbol, sig, kronos_sig, predicted_price, change_pct)
            sent = send_telegram(msg)
            if sent:
                print(f"  [{symbol}] ✅ ALERT SENT: {sig['direction']} @ {format_price(sig['entry_price'], symbol)}")
        else:
            # Gửi no-signal heartbeat mỗi cycle
            reason = "Không thỏa điều kiện Entry"
            if kronos_sig == "NEUTRAL":
                reason = "Kronos signal = NEUTRAL"
            elif kronos_sig == "UP" and close <= vwap:
                reason = "Giá <= VWAP (LONG cần giá trên VWAP)"
            elif kronos_sig == "DOWN" and close >= vwap:
                reason = "Giá >= VWAP (SHORT cần giá dưới VWAP)"
            msg = format_no_signal(symbol, kronos_sig, rsi, vwap, close, reason)
            send_telegram(msg)
            print(f"  [{symbol}] ⏭ No signal ({reason})")

        # Delay giữa symbols để tránh rate limit
        if symbol != SYMBOLS[-1]:
            time.sleep(2)


def main():
    print("=" * 50)
    print("Kronos+RSI+VWAP+ATR Trading Bot")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"Timeframe: {TIMEFRAME}")
    print("=" * 50)

    cycle = 0
    while True:
        cycle += 1
        try:
            run_cycle()
        except Exception as e:
            print(f"[ERROR] Cycle {cycle} failed: {e}")

        print(f"\n⏳ Chờ {CYCLE_WAIT // 60} phút...")
        time.sleep(CYCLE_WAIT)


if __name__ == "__main__":
    main()
