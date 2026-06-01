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
        "text": "✅ Screening berhasil"
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

        if not symbol.endswith(":USDT"):
    continue

        ohlcv = exchange.fetch_ohlcv(
            symbol,
            timeframe='5m',
            limit=100
        )


        volume = df['volume'].iloc[-1]
close_price = df['close'].iloc[-1]

volume_usdt = volume * close_price

if volume_usdt < 1000000:
    continue
    
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
    (
        symbol,
        round(rsi, 2),
        round(close_price, 6)
    )
)

    except:
        pass

results.sort(
    key=lambda x: x[1]
)

if results:
    send(message)
message = "🚨 Bitget Futures Oversold\n\n"

for pair, rsi, price in results[:5]:

    message += (
        f"📉 {pair}\n"
        f"RSI(4): {rsi}\n"
        f"Harga: {price}\n\n"
)
