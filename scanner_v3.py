import os
import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
from itertools import product
import json

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TOKEN_LO")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "CHAT_ID_LO")

exchange = ccxt.bitget({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})

TF_MAP = {"1m": "1m", "5m": "5m", "15m": "15m"}

# ============================================================
# FUNGSI TEKNIKAL
# ============================================================

def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TF_MAP[timeframe], limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except:
        return None

def fetch_historical(symbol, timeframe, since):
    all_ohlcv = []
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TF_MAP[timeframe], since=since, limit=1000)
        while len(ohlcv) > 0:
            all_ohlcv.extend(ohlcv)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TF_MAP[timeframe], since=ohlcv[-1][0] + 1, limit=1000)
        df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
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

# ============================================================
# BACKTEST SINGLE CONFIG
# ============================================================

def backtest_single_config(df_5m, params):
    """
    params = {
        "rsi_window": int,
        "oversold_threshold": int,
        "overbought_threshold": int,
        "tp_pct": float,
        "sl_pct": float,
        "max_hold_bars": int
    }
    """
    df = df_5m.copy()
    df["rsi"] = rsi(df["close"], params["rsi_window"])
    df["ema20"] = ema(df["close"], 20)
    df["trend"] = np.where(df["close"] > df["ema20"], "bullish", "bearish")

    in_position = False
    entry_price = 0
    entry_idx = 0
    direction = None
    trades = []
    wins = 0
    losses = 0

    for i in range(params["rsi_window"], len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        rsi_val = row["rsi"]

        if not in_position:
            oversold_cross = rsi_val < params["oversold_threshold"] and prev_row["rsi"] >= params["oversold_threshold"]
            overbought_cross = rsi_val > params["overbought_threshold"] and prev_row["rsi"] <= params["overbought_threshold"]

            if oversold_cross and row["trend"] == "bullish":
                in_position = True
                direction = "long"
                entry_price = row["close"]
                entry_idx = i
            elif overbought_cross and row["trend"] == "bearish":
                in_position = True
                direction = "short"
                entry_price = row["close"]
                entry_idx = i

        elif in_position:
            bars_held = i - entry_idx
            exit_price = row["close"]
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if direction == "long" else ((entry_price - exit_price) / entry_price) * 100

            hit_tp = pnl_pct >= params["tp_pct"]
            hit_sl = pnl_pct <= -params["sl_pct"]
            hit_time = bars_held >= params["max_hold_bars"]

            if hit_tp or hit_sl or hit_time:
                if pnl_pct > 0:
                    wins += 1
                else:
                    losses += 1
                trades.append(pnl_pct)
                in_position = False

    # Close remaining
    if in_position:
        exit_price = df["close"].iloc[-1]
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if direction == "long" else ((entry_price - exit_price) / entry_price) * 100
        if pnl_pct > 0:
            wins += 1
        else:
            losses += 1
        trades.append(pnl_pct)

    total_trades = len(trades)
    total_pnl = sum(trades)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    return {
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "win_rate": round(win_rate, 1),
    }

# ============================================================
# OPTIMIZATION ENGINE
# ============================================================

def optimize_parameters(symbols, days=3, min_avg_vol=100000):
    """
    Brute force grid search untuk nemu kombinasi parameter terbaik.
    Scoring berdasarkan kombinasi win rate + profit factor.
    """
    print(f"\n{'='*70}")
    print(f"PARAMETER OPTIMIZATION: {len(symbols)} symbols | {days} hari historis")
    print(f"{'='*70}")

    since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    # Grid parameter yang mau di-test
    param_grid = {
        "rsi_window": [7, 10, 14, 21],
        "oversold_threshold": [28, 30, 32, 35],
        "overbought_threshold": [65, 68, 70, 72],
        "tp_pct": [1.5, 2.0, 2.5, 3.0],
        "sl_pct": [1.0, 1.25, 1.5, 2.0],
        "max_hold_bars": [3, 5, 8, 12],
    }

    keys = list(param_grid.keys())
    total_configs = np.prod([len(param_grid[k]) for k in keys])
    print(f"Total parameter combinations: {total_configs}")
    print(f"Symbols to test: {len(symbols)}")

    # Fetch historical data untuk semua symbol
    print(f"\nFetching historical data...")
    all_data = {}
    for sym in symbols:
        df = fetch_historical(sym, "5m", since)
        if df is not None and len(df) > 100 and df["volume"].mean() >= min_avg_vol:
            all_data[sym] = df
        time.sleep(0.3)  # Rate limit safety
    print(f"Loaded {len(all_data)} symbols with enough data")

    if len(all_data) == 0:
        print("ERROR: No symbols with sufficient data. Coba kurangi days atau min_avg_vol.")
        return None

    # Grid search
    results = []
    tested = 0
    start_time = time.time()

    for combo in product(*[param_grid[k] for k in keys]):
        params = dict(zip(keys, combo))

        # Skip conflicting params
        if params["oversold_threshold"] >= params["overbought_threshold"]:
            continue
        if params["tp_pct"] <= params["sl_pct"]:
            continue

        # Test semua symbol
        all_pnls = []
        all_trades = 0
        all_wins = 0

        for sym, df in all_data.items():
            result = backtest_single_config(df, params)
            all_pnls.append(result["total_pnl"])
            all_trades += result["trades"]
            all_wins += result["wins"]

        total_pnl = sum(all_pnls)
        total_trades = all_trades
        win_rate = (all_wins / total_trades * 100) if total_trades > 0 else 0

        # Risk-adjusted score: preferensi profit + win rate
        # Weight: profit 60%, win rate 40%
        score = (total_pnl * 0.6) + (win_rate * 0.4)

        results.append({
            "params": params,
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 1),
            "score": round(score, 2),
        })

        tested += 1
        if tested % 20 == 0:
            elapsed = time.time() - start_time
            eta = (elapsed / tested) * (total_configs - tested)
            print(f"  Tested {tested}/{total_configs} | ETA: {eta/60:.1f}m | Best score: {max([r['score'] for r in results]):.2f}")

    # Sort results
    results.sort(key=lambda x: x["score"], reverse=True)

    # Print top 10
    print(f"\n{'='*70}")
    print(f"TOP 10 PARAMETER CONFIGURATIONS")
    print(f"{'='*70}")
    for i, r in enumerate(results[:10]):
        p = r["params"]
        print(f"\n#{i+1} | Score: {r['score']:.2f}")
        print(f"  RSI: {p['rsi_window']} | Oversold: <{p['oversold_threshold']} | Overbought: >{p['overbought_threshold']}")
        print(f"  TP: {p['tp_pct']}% | SL: {p['sl_pct']}% | Max Hold: {p['max_hold_bars']} bars")
        print(f"  Total PnL: {r['total_pnl']:+.2f}% | Win Rate: {r['win_rate']}% | Trades: {r['total_trades']}")

    # Simpan hasil ke file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"optimization_results_{timestamp}.json"
    with open(filename, "w") as f:
        json.dump({
            "date": timestamp,
            "symbols_tested": len(all_data),
            "days": days,
            "configs_tested": tested,
            "top_10": [{
                "rank": i+1,
                "score": r["score"],
                "params": r["params"],
                "total_pnl": r["total_pnl"],
                "win_rate": r["win_rate"],
                "total_trades": r["total_trades"],
            } for i, r in enumerate(results[:10])],
            "all_results": results,
        }, f, indent=2)
    print(f"\nFull results saved to: {filename}")

    # Rekomendasi
    best = results[0]
    p = best["params"]
    print(f"\n{'='*70}")
    print(f"RECOMMENDED PARAMETERS")
    print(f"{'='*70}")
    print(f"RSI Window: {p['rsi_window']} | Oversold: <{p['oversold_threshold']} | Overbought: >{p['overbought_threshold']}")
    print(f"TP: {p['tp_pct']}% | SL: {p['sl_pct']}% | Max Hold: {p['max_hold_bars']} bars (25m di 5m)")
    print(f"Expected: {best['total_pnl']:+.2f}% total over {best['total_trades']} trades | Win Rate: {best['win_rate']}%")
    print(f"{'='*70}")

    return best["params"]

# ============================================================
# LIVE SCANNER (pake parameter teroptimasi)
# ============================================================

def compute_signal(df_1m, df_5m, df_15m, params):
    score = 0
    signals = []

    def rsi_data(df, tf_name):
        rsi_val = rsi(df["close"], params["rsi_window"]).iloc[-1]
        ema20 = ema(df["close"], 20).iloc[-1]
        price = df["close"].iloc[-1]
        spike_vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].iloc[:-1].mean()
        spike_ratio = round(spike_vol / avg_vol, 1) if avg_vol > 0 else 1
        trend = "bullish" if price > ema20 else "bearish"
        return {"rsi": rsi_val, "price": price, "trend": trend, "spike_ratio": spike_ratio, "ema20": ema20}

    d1 = rsi_data(df_1m, "1m")
    d5 = rsi_data(df_5m, "5m")
    d15 = rsi_data(df_15m, "15m")

    oversold = params["oversold_threshold"]
    overbought = params["overbought_threshold"]

    if d1["rsi"] < oversold:
        score += 2
        signals.append(f"1m oversold (<{oversold})")
    if d5["rsi"] < oversold:
        score += 2
        signals.append(f"5m oversold (<{oversold})")
    if d15["rsi"] < oversold + 5:
        score += 1
        signals.append(f"15m near oversold")
    if d1["rsi"] > overbought:
        score += 2
        signals.append(f"1m overbought (>{overbought})")
    if d5["rsi"] > overbought:
        score += 2
        signals.append(f"5m overbought (>{overbought})")
    if d15["rsi"] > overbought - 5:
        score += 1
        signals.append(f"15m near overbought")

    if d1["trend"] == d5["trend"] == d15["trend"]:
        score += 2
        signals.append("trend aligned")
    if d5["spike_ratio"] > 1.8:
        score += 1
        signals.append(f"vol spike {d5['spike_ratio']}x")
    if d1["rsi"] < oversold and d5["trend"] == "bullish":
        score += 1
        signals.append("pantulan uptrend")
    if d1["rsi"] > overbought and d5["trend"] == "bearish":
        score += 1
        signals.append("koreksi downtrend")

    if d1["rsi"] < oversold or d5["rsi"] < oversold:
        direction = "BUY 🟢"
    elif d1["rsi"] > overbought or d5["rsi"] > overbought:
        direction = "SELL 🔴"
    else:
        direction = "NEUTRAL ⚪"

    if d1["rsi"] < oversold and d5["rsi"] > overbought:
        direction = "CONFLICT ⚠️"
    if d1["rsi"] > overbought and d5["rsi"] < oversold:
        direction = "CONFLICT ⚠️"

    return score, direction, signals, d1, d5, d15

def scan_live(params):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] LIVE SCANNER (optimized params)")
    try:
        markets = exchange.load_markets()
    except Exception as e:
        print(f"Gagal load markets: {e}")
        return

    symbols = [s for s in markets if s.endswith("/USDT:USDT") and "3S" not in s and "3L" not in s]
    print(f"Symbols: {len(symbols)}")
    scanned = 0

    for sym in symbols:
        df_1m = fetch_ohlcv(sym, "1m", 30)
        df_5m = fetch_ohlcv(sym, "5m", 60)
        df_15m = fetch_ohlcv(sym, "15m", 60)

        if df_1m is None or df_5m is None or df_15m is None:
            continue
        if df_5m["volume"].mean() < 50000:
            continue

        score, direction, signals, d1, d5, d15 = compute_signal(df_1m, df_5m, df_15m, params)

        if score >= 6:
            emoji = {"BUY 🟢": "🟢", "SELL 🔴": "🔴", "NEUTRAL ⚪": "⚪", "CONFLICT ⚠️": "⚠️"}
            print(f"\n{emoji.get(direction,'⚪')} {sym} | {direction} | Score {score}/10")
            print(f"  1m: RSI {d1['rsi']:.1f} | ${d1['price']:.4f}")
            print(f"  5m: RSI {d5['rsi']:.1f} | ${d5['price']:.4f}")
            print(f"  15m: RSI {d15['rsi']:.1f} | Trend: {d15['trend']}")
            print(f"  Signals: {', '.join(signals)}")

            msg = (
                f"{emoji.get(direction,'⚪')} <b>{sym}</b> | <b>{direction}</b> | Score: {score}/10\n"
                f"━━━━━━━━━━━━━━━\n"
                f"1m: RSI {d1['rsi']:.1f} | ${d1['price']:.4f}\n"
                f"5m: RSI {d5['rsi']:.1f} | ${d5['price']:.4f}\n"
                f"15m: RSI {d15['rsi']:.1f} | Trend: {d15['trend']}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Signals: {', '.join(signals)}\n"
                f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
            )
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
            except:
                pass

        scanned += 1
        if scanned % 50 == 0:
            print(f"  Scanned {scanned}/{len(symbols)}")

    print(f"Selesai. Scanned {scanned} symbols.")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "optimize":
        print("Loading markets for optimization...")
        try:
            markets = exchange.load_markets()
        except:
            print("Gagal load markets")
            sys.exit(1)
        symbols = [s for s in markets if s.endswith("/USDT:USDT") and "3S" not in s and "3L" not in s]
        best_params = optimize_parameters(symbols, days=3, min_avg_vol=50000)
        if best_params:
            print(f"\nStarting live scanner dengan optimized params...")
            while True:
                try:
                    scan_live(best_params)
                except Exception as e:
                    print(f"Error: {e}")
                print(f"Next scan in 300s...")
                time.sleep(300)
    else:
        # Default params (fallback)
        default_params = {
            "rsi_window": 14,
            "oversold_threshold": 32,
            "overbought_threshold": 68,
            "tp_pct": 2.0,
            "sl_pct": 1.25,
            "max_hold_bars": 5,
        }
        while True:
            try:
                scan_live(default_params)
            except Exception as e:
                print(f"Error: {e}")
            print(f"Next scan in 300s...")
            time.sleep(300)
              
