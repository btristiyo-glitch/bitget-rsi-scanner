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

        # Hanya futures USDT-M
        if not symbol.endswith(":USDT"):
            continue

        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe="5m",
            limit=100
        )

        if len(ohlcv) < 20:
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

        # RSI(4)
        rsi = RSIIndicator(
            df["close"],
            window=4
        ).rsi().iloc[-1]

        if pd.isna(rsi):
            continue

        # Filter RSI
        if rsi >= 10:
            continue

        # Volume candle terakhir
        volume = float(df["volume"].iloc[-1])
        volume_usdt = volume * close_price

        # Minimal volume 500k USDT
        if volume_usdt < 500000:
            continue

        base_coin = symbol.split("/")[0]

        chart_url = (
            f"https://www.bitget.com/futures/usdt/{base_coin}USDT"
        )

        results.append({
            "symbol": symbol,
            "rsi": round(float(rsi), 2),
            "price": close_price,
            "volume": int(volume_usdt),
            "chart": chart_url
        })

    except Exception:
        continue

results = sorted(
    results,
    key=lambda x: x["rsi"]
)

if results:

    message = "🚨 BITGET FUTURES RSI OVERSOLD\n\n"

    for item in results[:10]:

        message += (
            f"📉 {item['symbol']}\n"
            f"RSI(4): {item['rsi']}\n"
            f"Harga: {item['price']}\n"
            f"Vol 5m: ${item['volume']:,}\n"
            f"Chart:\n{item['chart']}\n\n"
        )

    send(message)
