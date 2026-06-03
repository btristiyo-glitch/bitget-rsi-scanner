import os, time, ccxt, pandas as pd, numpy as np, requests, json, signal, logging
from datetime import datetime, timedelta
from itertools import product
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TOKEN_LO")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "CHAT_ID_LO")

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler("scanner.log"), logging.StreamHandler()])
log = logging.getLogger(__name__)

exchange = ccxt.bitget({"enableRateLimit": True, "options": {"defaultType": "swap"}})
RUNNING = True
signal.signal(signal.SIGINT, lambda x,y: globals().update(RUNNING=False))
signal.signal(signal.SIGTERM, lambda x,y: globals().update(RUNNING=False))

def tg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
    except: pass

def rsi(s, w=14):
    d = s.diff(); g = d.where(d>0,0); l = (-d.where(d<0,0))
    ag = g.rolling(w,min_periods=1).mean(); al = l.rolling(w,min_periods=1).mean()
    return 100-(100/(1+ag/(al+1e-10)))

def ema(s,w): return s.ewm(span=w,adjust=False).mean()

def fetch_ohlcv(sym, tf, since):
    try:
        ohlcv = exchange.fetch_ohlcv(sym, tf, since=int(since.timestamp()*1000), limit=1000)
        all_o = ohlcv[:]
        while len(ohlcv)==1000:
            ohlcv = exchange.fetch_ohlcv(sym, tf, since=ohlcv[-1][0]+1, limit=1000)
            all_o.extend(ohlcv)
        df = pd.DataFrame(all_o, columns=["t","o","h","l","c","v"])
        df[["c","v"]] = df[["c","v"]].astype(float); return df
    except: return None

def backtest(df, p):
    df = df.copy()
    df["r"] = rsi(df["c"], p["rsi_window"])
    df["e"] = ema(df["c"],20)
    df["tr"] = np.where(df["c"]>df["e"],"bullish","bearish")
    pos=0; wins=0; trades=[]; ep=0; ei=0; dr=None
    for i in range(p["rsi_window"], len(df)):
        row, prv = df.iloc[i], df.iloc[i-1]
        if not pos:
            oc = row["r"]<p["oversold"] and prv["r"]>=p["oversold"]
            ob = row["r"]>p["overbought"] and prv["r"]<=p["overbought"]
            if oc and row["tr"]=="bullish": pos=1; dr="long"; ep=row["c"]; ei=i
            elif ob and row["tr"]=="bearish": pos=1; dr="short"; ep=row["c"]; ei=i
        elif pos:
            pnl = ((row["c"]-ep)/ep*100) if dr=="long" else ((ep-row["c"])/ep*100)
            if pnl>=p["tp"] or pnl<=-p["sl"] or (i-ei)>=p["hold"]:
                if pnl>0: wins+=1
                trades.append(pnl); pos=0
    if pos:
        pnl = ((df["c"].iloc[-1]-ep)/ep*100) if dr=="long" else ((ep-df["c"].iloc[-1])/ep*100)
        if pnl>0: wins+=1; trades.append(pnl)
    t=len(trades); return {"t":t,"w":wins,"pnl":round(sum(trades),2),"wr":round(wins/t*100,1) if t else 0}

def optimize(days=3):
    log.info("Loading markets...")
    syms = [s for s in exchange.load_markets() if s.endswith("/USDT:USDT") and "3S" not in s and "3L" not in s]
    since = datetime.now()-timedelta(days=days)
    tg(f"🔄 OPTIMIZE START | {len(syms)} syms | {days}d")
    
    data = {}
    for i,s in enumerate(syms):
        if not RUNNING: return None
        df = fetch_ohlcv(s, "5m", since)
        if df is not None and len(df)>100 and df["v"].mean()>=50000:
            data[s]=df
        time.sleep(0.3)
        if (i+1)%30==0: log.info(f"Fetch {i+1}/{len(syms)} ({len(data)} ok)")
    
    if len(data)<5: tg(f"❌ Only {len(data)} symbols"); return None
    
    grid = {"rsi_window":[7,10,14,21], "oversold":[28,30,32,35], "overbought":[65,68,70,72],
            "tp":[1.5,2.0,2.5,3.0], "sl":[1.0,1.25,1.5,2.0], "hold":[3,5,8,12]}
    keys = list(grid.keys())
    total = np.prod([len(grid[k]) for k in keys])
    results = []; tested = 0; start = time.time(); hb = time.time()
    
    for combo in product(*[grid[k] for k in keys]):
        if not RUNNING: break
        p = dict(zip(keys, combo))
        if p["oversold"]>=p["overbought"] or p["tp"]<=p["sl"]: continue
        all_pnl=[]; all_t=0; all_w=0
        for df in data.values():
            r = backtest(df, p)
            all_pnl.append(r["pnl"]); all_t+=r["t"]; all_w+=r["w"]
        tpnl = sum(all_pnl); wr = (all_w/all_t*100) if all_t else 0
        score = tpnl*0.6 + wr*0.4
        results.append({"p":p,"pnl":round(tpnl,2),"t":all_t,"wr":round(wr,1),"s":round(score,2)})
        tested += 1
        
        if tested%300==0:
            best = max([r["s"] for r in results]) if results else 0
            el = (time.time()-start)/60; eta = (el/tested)*(total-tested)
            log.info(f"{tested}/{total} | Best {best:.2f} | ETA {eta:.1f}m")
            tg(f"📊 {tested}/{total} ({round(tested/total*100,1)}%) | Best {best:.2f} | ETA {eta:.1f}m")
        if time.time()-hb>1800: tg("💓 Still optimizing..."); hb=time.time()
    
    results.sort(key=lambda x:x["s"], reverse=True)
    el = (time.time()-start)/60
    r10 = results[:10]
    tg(f"✅ DONE | {tested} configs | {el:.1f}m\n" +
       "\n".join([f"#{i+1} | RSI{p['p']['rsi_window']} OS<{p['p']['oversold']} OB>{p['p']['overbought']} TP{p['p']['tp']}% SL{p['p']['sl']}% Hold{p['p']['hold']} | PnL{p['pnl']:+.2f}% WR{p['wr']}%" for i,p in enumerate(r10[:5])]))
    
    json.dump({"date":str(datetime.now()),"top":r10}, open("best_params.json","w"), indent=2)
    return results[0]["p"]

def scan(p):
    try: markets = exchange.load_markets()
    except: return
    syms = [s for s in markets if s.endswith("/USDT:USDT") and "3S" not in s and "3L" not in s]
    for sym in syms:
        d1 = fetch_ohlcv(sym,"1m",datetime.now()-timedelta(hours=1))
        d5 = fetch_ohlcv(sym,"5m",datetime.now()-timedelta(hours=5))
        d15 = fetch_ohlcv(sym,"15m",datetime.now()-timedelta(hours=15))
        if any(x is None for x in [d1,d5,d15]) or d5["v"].mean()<50000: continue
        
        def rd(df):
            rv = rsi(df["c"],p["rsi_window"]).iloc[-1]
            e = ema(df["c"],20).iloc[-1]
            pr = df["c"].iloc[-1]
            sr = round(df["v"].iloc[-1]/df["v"].iloc[:-1].mean(),1)
            return {"rsi":rv,"price":pr,"trend":"bullish" if pr>e else "bearish","spike":sr}
        
        r1,r5,r15 = rd(d1),rd(d5),rd(d15)
        os, ob = p["oversold"], p["overbought"]
        sc, sig = 0, []
        
        if r1["rsi"]<os: sc+=2; sig.append(f"1m OS<{os}")
        if r5["rsi"]<os: sc+=2; sig.append(f"5m OS<{os}")
        if r15["rsi"]<os+5: sc+=1; sig.append("15m near OS")
        if r1["rsi"]>ob: sc+=2; sig.append(f"1m OB>{ob}")
        if r5["rsi"]>ob: sc+=2; sig.append(f"5m OB>{ob}")
        if r15["rsi"]>ob-5: sc+=1; sig.append("15m near OB")
        if r1["trend"]==r5["trend"]==r15["trend"]: sc+=2; sig.append("trend aligned")
        if r5["spike"]>1.8: sc+=1; sig.append(f"vol x{r5['spike']}")
        
        if r1["rsi"]<os or r5["rsi"]<os: dr = "BUY 🟢"
        elif r1["rsi"]>ob or r5["rsi"]>ob: dr = "SELL 🔴"
        else: dr = "NEUTRAL ⚪"
        if r1["rsi"]<os and r5["rsi"]>ob: dr = "CONFLICT ⚠️"
        if r1["rsi"]>ob and r5["rsi"]<os: dr = "CONFLICT ⚠️"
        
        if sc>=6:
            em = {"BUY 🟢":"🟢","SELL 🔴":"🔴","NEUTRAL ⚪":"⚪","CONFLICT ⚠️":"⚠️"}
            log.info(f"{em.get(dr,'⚪')} {sym} | {dr} | Score {sc}/10")
            tg(f"{em.get(dr,'⚪')} <b>{sym}</b> | {dr} | {sc}/10\n━━━\n1m: RSI {r1['rsi']:.1f} ${r1['price']:.4f}\n5m: RSI {r5['rsi']:.1f} ${r5['price']:.4f}\n15m: RSI {r15['rsi']:.1f} {r15['trend']}\n{', '.join(sig)}\n{datetime.now().strftime('%H:%M:%S')}")

if __name__=="__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="optimize":
        days = int(sys.argv[2]) if len(sys.argv)>2 else 3
        p = optimize(days)
        if p:
            log.info(f"Best: {p}")
            tg(f"🚀 Scanner started with RSI{p['rsi_window']} OS<{p['oversold']} OB>{p['overbought']} TP{p['tp']}% SL{p['sl']}%")
            while RUNNING:
                try: scan(p)
                except Exception as e: log.error(e); tg(f"⚠️ {str(e)[:100]}")
                time.sleep(300)
    elif len(sys.argv)>1 and sys.argv[1]=="scan":
        try: p = json.load(open("best_params.json"))["top"][0]["p"]
        except: p = {"rsi_window":14,"oversold":32,"overbought":68,"tp":2.0,"sl":1.25,"hold":5}
        while RUNNING:
            try: scan(p)
            except Exception as e: log.error(e)
            time.sleep(300)
    else:
        print("python scan.py optimize [days]  # optimasi + live\npython scan.py scan              # live aja")
