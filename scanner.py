import ccxt
import pandas as pd
import ccxt
import pandas as pd
import requests
import os

from ta.momentum import RSIIndicator

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

exchange = ccxt.bitget({
    "enableRateLimit": True
})

def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": msg,
            "disable_web_page_preview": True
        },
        timeout=20
    )

markets = exchange.load_markets()

results = []

for symbol in markets:

    try:

        if not symbol.endswith(":USDT"):
            continue

        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe="5m",
            limit=100
        )

        if len(ohlcv) < 30:
            continue

        df = pd.DataFrame(
            ohlcv,
            columns=[
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        close_price = float(df["close"].iloc[-1])
        open_price = float(df["open"].iloc[-1])

        rsi_series = RSIIndicator(
            df["close"],
            window=4
        ).rsi()

        rsi_now = float(rsi_series.iloc[-1])
        rsi_prev = float(rsi_series.iloc[-2])

        if pd.isna(rsi_now) or pd.isna(rsi_prev):
            continue

        # RSI oversold
        if rsi_now >= 15:
            continue

        # RSI mulai naik
        if rsi_now <= rsi_prev:
            continue

        # Candle hijau
        if close_price <= open_price:
            continue

        # Volume
        volume_now = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].tail(20).mean())

        if volume_now <= avg_volume:
            continue

        volume_usdt = volume_now * close_price

        if volume_usdt < 500000:
            continue

        # Scoring
        score = 0

        score += max(0, 15 - rsi_now) * 5

        rsi_rebound = rsi_now - rsi_prev
        score += rsi_rebound * 20

        volume_ratio = volume_now / avg_volume
        score += volume_ratio * 10

        chart_url = (
            f"https://www.bitget.com/futures/usdt/"
            f"{symbol.split('/')[0]}USDT"
        )

        results.append({
            "symbol": symbol,
            "score": round(score, 2),
            "rsi": round(rsi_now, 2),
            "price": close_price,
            "volume": int(volume_usdt),
            "chart": chart_url
        })

    except Exception:
        continue

results = sorted(
    results,
    key=lambda x: x["score"],
    reverse=True
)

if results:

    message = "🚀 BITGET SCALPING SCANNER\n\n"

    for item in results[:5]:

        message += (
            f"⭐ Score: {item['score']}\n"
            f"Pair: {item['symbol']}\n"
            f"RSI(4): {item['rsi']}\n"
            f"Harga: {item['price']}\n"
            f"Vol 5m: ${item['volume']:,}\n"
            f"{item['chart']}\n\n"
        )

    send(message)
