import ccxt
import pandas as pd
import requests
import os

from ta.momentum import RSIIndicator

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
send_test = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={
        "chat_id": CHAT_ID,
        "text": "✅ Tes GitHub Actions berhasil"
    }
)
exchange = ccxt.bitget()

def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": msg
        }
    )

markets = exchange.load_markets()

results = []

for symbol in markets:

    try:

        if ":USDT" not in symbol:
            continue

        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe='5m',
            limit=100
        )

        df = pd.DataFrame(
            ohlcv,
            columns=[
                'time',
                'open',
                'high',
                'low',
                'close',
                'volume'
            ]
        )

        rsi = RSIIndicator(
            df['close'],
            window=4
        ).rsi().iloc[-1]

        if rsi < 10:

            results.append(
                (symbol, round(rsi, 2))
            )

    except:
        pass

results.sort(
    key=lambda x: x[1]
)

if results:

    message = "🚨 RSI(4) < 10\n\n"

    for pair, rsi in results[:20]:

        message += (
            f"{pair}\n"
            f"RSI: {rsi}\n\n"
        )

    send(message)
