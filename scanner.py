import os
import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import requests
from dotenv import load_dotenv
from collections import deque

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TOKEN_LO")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "CHAT_ID_LO")

exchange = ccxt.bitget({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})

TF_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
}

def fetch_ohlcv(symbol, timeframe, limit=60):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TF_MAP[timeframe], limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except:
        return None

def rsi(series, window=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window, min_periods=1).mean()
    avg_loss = loss.rolling(window, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def ema(series, window):
    return series.ewm(span=window, adjust=False).mean()

def volume_spike(df, multiplier=2.0):
    avg_vol = df["volume"].iloc[:-1].mean()
    current_vol = df["volume"].iloc[-1]
    return current_vol > avg_vol * multiplier, current_vol / avg_vol

def detect_market_structure(df):
    ema20 = ema(df["close"], 20)
    price = df["close"].iloc[-1]
    trend = "bullish" if price > ema20.iloc[-1] else "bearish"
    return trend, ema20.iloc[-1]

def compute_confluence(df_1m, df_5m, df_15m):
    score = 0
    signals = []

    def rsi_data(df, tf_name):
        rsi_val = rsi(df["close"], 14).iloc[-1]
        ema20 = ema(df["close"], 20).iloc[-1]
        price = df["close"].iloc[-1]
        spike, ratio = volume_spike(df)
        trend = "bullish" if price > ema20 else "bearish"
        return {"rsi": rsi_val, "price": price, "trend": trend, "spike": spike, "vol_ratio": round(ratio, 1), "ema20": ema20}

    d1 = rsi_data(df_1m, "1m")
    d5 = rsi_data(df_5m, "5m")
    d15 = rsi_data(df_15m, "15m")

    # RSI oversold (BUY signal)
    if d1["rsi"] < 30:
        score += 2
        signals.append("1m oversold")
    if d5["rsi"] < 35:
        score += 2
        signals.append("5m oversold")
    if d15["rsi"] < 40:
        score += 1
        signals.append("15m oversold")

    # RSI overbought (SELL signal)
    if d1["rsi"] > 70:
        score += 2
        signals.append("1m overbought")
    if d5["rsi"] > 65:
        score += 2
        signals.append("5m overbought")
    if d15["rsi"] > 60:
        score += 1
        signals.append("15m overbought")

    # Trend alignment (filter)
    if d1["trend"] == d5["trend"] == d15["trend"]:
        score += 2
        signals.append("trend aligned")

    # Volume spike konfirmasi
    if d5["spike"]:
        score += 1
        signals.append("volume spike 5m x" + str(d5["vol_ratio"]))

    # Sinyal khusus: RSI 1m oversold + trend 5m bullish = pantulan kuat
    if d1["rsi"] < 30 and d5["trend"] == "bullish":
        score += 1
        signals.append("pantulan dalam uptrend")

    # Sinyal khusus: RSI 1m overbought + trend 5m bearish = koreksi kuat
    if d1["rsi"] > 70 and d5["trend"] == "bearish":
        score += 1
        signals.append("koreksi dalam downtrend")

    # Tentukan direction
    if d1["rsi"] < 30 or d5["rsi"] < 35:
        direction = "BUY 🟢"
    elif d1["rsi"] > 70 or d5["rsi"] > 65:
        direction = "SELL 🔴"
    else:
        direction = "NEUTRAL ⚪"

    return score, direction, signals, d1, d5, d15

def send_telegram(symbol, direction, score, signals, d1, d5, d15):
    emoji = {
        "BUY 🟢": "🟢",
        "SELL 🔴": "🔴",
        "NEUTRAL ⚪": "⚪",
    }
    msg = (
        f"{emoji.get(direction,'⚪')} <b>{symbol}</b> | <b>{direction}</b> | Score: {score}/10\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1m: RSI {d1['rsi']:.1f} | Price ${d1['price']:.4f} | Vol x{d1['vol_ratio']}\n"
        f"5m: RSI {d5['rsi']:.1f} | Price ${d5['price']:.4f} | Vol x{d5['vol_ratio']}\n"
        f"15m: RSI {d15['rsi']:.1f} | Trend: {d15['trend']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Signals: {', '.join(signals)}\n"
        f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
    except:
        pass

def scan_all():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning Bitget USDT-M futures...")
    try:
        markets = exchange.load_markets()
    except Exception as e:
        print(f"Gagal load markets: {e}")
        return

    symbols = [s for s in markets if s.endswith("/USDT:USDT")]
    print(f"Total symbols: {len(symbols)}")
    scanned = 0

    for sym in symbols:
        df_1m = fetch_ohlcv(sym, "1m", 30)
        df_5m = fetch_ohlcv(sym, "5m", 60)
        df_15m = fetch_ohlcv(sym, "15m", 60)

        if df_1m is None or df_5m is None or df_15m is None:
            continue

        # Minimal volume filter
        avg_vol_5m = df_5m["volume"].mean()
        if avg_vol_5m < 50000:
            continue

        score, direction, signals, d1, d5, d15 = compute_confluence(df_1m, df_5m, df_15m)

        if score >= 6:
            send_telegram(sym, direction, score, signals, d1, d5, d15)
            print(f"  {direction} {sym} | Score {score}")

        scanned += 1
        if scanned % 50 == 0:
            print(f"  Scanned {scanned}/{len(symbols)}")

    print(f"Selesai. Scanned {scanned} symbols.\n")

if __name__ == "__main__":
    while True:
        scan_all()
        time.sleep(300)  # scan tiap 5 menit
            f"📉 {item['symbol']}\n"
            f"RSI(4): {item['rsi']}\n"
            f"Harga: {item['price']}\n"
            f"Vol 5m: ${item['volume']:,}\n"
            f"Chart:\n{item['chart']}\n\n"
        )

    send(message)
