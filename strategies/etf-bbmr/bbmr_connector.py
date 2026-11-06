"""
ETF BBMR backtest fed by saved Robinhood connector payloads — no yfinance, no Yahoo.

Usage:  python bbmr_connector.py <dir-of-get_equity_historicals-*.txt>

Reads every get_equity_historicals payload in <dir>: `interval: "hour"` results
become the bar data, the `interval: "day"` SPY result becomes the 200-day regime
filter. Bars with `interpolated: true` are DROPPED — Robinhood pads requested
ranges it has no data for with synthesised flat bars (see README), and leaving
them in silently fabricates history.

Strategy logic is a faithful port of etf_bbmr.py. `tp_at_basis` switches the
take-profit fill between the original (bar close) and a basis-capped limit.
"""
import json, math, glob, sys
import numpy as np, pandas as pd

D = sys.argv[1] if len(sys.argv) > 1 else "."
BB_LEN, BB_K, SMA_LONG = 20, 2.0, 200
ALLOC, MAX_POS, STOP_PCT = 0.05, 4, 0.015
TZ = "America/New_York"
U8  = ["SPY","QQQ","IWM","DIA","XLK","XLF","XLV","SCHD"]
U23 = U8 + ["XLE","XLI","XLY","XLP","XLU","XLC","XLB","XLRE","RSP","SMH","EFA","EEM","GLD","TLT","HYG"]

def bars_to_df(bars):
    rows = [b for b in bars if not b.get("interpolated")]
    d = pd.DataFrame({
        "Open":  [float(b["open_price"])  for b in rows],
        "High":  [float(b["high_price"])  for b in rows],
        "Low":   [float(b["low_price"])   for b in rows],
        "Close": [float(b["close_price"]) for b in rows],
    }, index=pd.to_datetime([b["begins_at"] for b in rows], utc=True).tz_convert(TZ))
    d["basis"] = d.Close.rolling(BB_LEN).mean()
    d["lower"] = d.basis - BB_K * d.Close.rolling(BB_LEN).std(ddof=0)
    return d

# load every saved payload; hourly -> data, daily SPY -> regime
data, daily = {}, None
for f in sorted(glob.glob(f"{D}/mcp-RobinhoodAgentic-get_equity_historicals-*.txt")):
    for r in json.load(open(f))["data"]["results"]:
        if r["interval"] == "hour":
            data[r["symbol"]] = bars_to_df(r["bars"])
        elif r["interval"] == "day" and r["symbol"] == "SPY":
            rows = [b for b in r["bars"] if not b.get("interpolated")]
            daily = pd.Series([float(b["close_price"]) for b in rows],
                              index=pd.to_datetime([b["begins_at"] for b in rows], utc=True).tz_convert(TZ).date)

sma_prev = daily.rolling(SMA_LONG).mean().shift(1)
lut = dict(zip(daily.index, sma_prev.values))
spy = data["SPY"]
spy = spy.assign(sma200=[lut.get(t.date(), np.nan) for t in spy.index])
spy["risk_on"] = spy.Close > spy.sma200
data["SPY"] = spy

def run(universe, tp_at_basis, cash0=100_000.0):
    rows = {s: data[s].to_dict("index") for s in universe}
    idx = sorted(set().union(*[data[s].index for s in universe]))
    cash, pos, trades, curve = cash0, {}, [], []
    for t in idx:
        bars = {s: rows[s][t] for s in universe if t in rows[s]}
        for s in list(pos):
            b, p = bars.get(s), pos[s]
            if b is None or t <= p["t"]: continue
            stop = p["entry"] * (1 - STOP_PCT)
            if b["Low"] <= stop:
                px, why = min(b["Open"], stop), "SL"
            elif b["High"] >= b["basis"]:
                px = max(b["basis"], b["Open"]) if tp_at_basis else b["Close"]
                why = "TP"
            else: continue
            cash += p["sh"] * px
            trades.append(dict(sym=s, entry=p["entry"], exit=px, sh=p["sh"],
                               pnl=p["sh"]*(px-p["entry"]), ret=px/p["entry"]-1, why=why))
            del pos[s]
        for s, p in pos.items():
            if s in bars: p["last"] = bars[s]["Close"]
        equity = cash + sum(p["sh"]*p["last"] for p in pos.values())
        sb = bars.get("SPY")
        if sb is not None and bool(sb["risk_on"]) and len(pos) < MAX_POS:
            cands = sorted((b["Close"]/b["lower"]-1, s) for s, b in bars.items()
                           if s not in pos and not np.isnan(b["lower"]) and b["Close"] < b["lower"])
            for _, s in cands:
                if len(pos) >= MAX_POS: break
                px = bars[s]["Close"]; sh = math.floor(ALLOC*equity/px)
                if sh < 1 or sh*px > cash: continue
                cash -= sh*px; pos[s] = dict(t=t, entry=px, sh=sh, last=px)
        curve.append((t, equity, len(pos)))
    eq = pd.DataFrame(curve, columns=["t","equity","npos"]).set_index("t")
    tr = pd.DataFrame(trades)
    return eq, tr

def report(label, universe, tp_at_basis):
    eq, tr = run(universe, tp_at_basis)
    sc = data["SPY"].Close
    bh = sc.iloc[-1]/sc.iloc[0] - 1                      # bug 2 fixed: bar 0, not bar BB_LEN
    dd = (eq.equity/eq.equity.cummax() - 1).min()
    print(f"\n{'='*74}\n{label}\n{'='*74}")
    print(f"Period        {eq.index[0]:%Y-%m-%d} -> {eq.index[-1]:%Y-%m-%d}  ({len(eq)} bars)")
    print(f"Total return  {eq.equity.iloc[-1]/100_000-1:+.2%}   (SPY B&H {bh:+.2%})")
    print(f"Max drawdown  {dd:.2%}")
    print(f"Avg exposure  {eq.npos.mean()*ALLOC:.1%}   bars w/ 4 open: {(eq.npos==MAX_POS).mean():.1%}")
    print(f"Risk-on bars  {data['SPY'].risk_on.mean():.1%}")
    if tr.empty: print("No trades."); return eq, tr
    w, l = tr[tr.pnl > 0], tr[tr.pnl <= 0]
    tp = tr[tr.why == "TP"]; tp_loss = tp[tp.pnl <= 0]
    print(f"Trades        {len(tr)}   win {len(w)/len(tr):.1%}   TP {len(tp)}  SL {sum(tr.why=='SL')}")
    print(f"Avg trade     {tr.ret.mean():+.2%}   avg win {w.ret.mean():+.2%}   avg loss {(l.ret.mean() if len(l) else 0):+.2%}")
    pf = w.pnl.sum()/-l.pnl.sum() if len(l) and l.pnl.sum() else float('inf')
    print(f"Profit factor {pf:.2f}")
    print(f"TP exits that LOST money: {len(tp_loss)} of {len(tp)} ({(len(tp_loss)/len(tp) if len(tp) else 0):.1%})")
    print(f"Symbols traded: {tr.sym.nunique()} of {len(universe)}  -> {sorted(tr.sym.unique())}")
    return eq, tr

print(f"Loaded {len(data)} hourly symbols; daily SPY {len(daily)} bars "
      f"({min(daily.index)} -> {max(daily.index)})")
r = {}
r["8f"]  = report("A.  8 symbols  — faithful (TP fills at bar CLOSE)",  U8,  False)
r["23f"] = report("B. 23 symbols  — faithful (TP fills at bar CLOSE)",  U23, False)
r["8x"]  = report("C.  8 symbols  — FIXED (TP fills at max(basis,Open))", U8,  True)
r["23x"] = report("D. 23 symbols  — FIXED (TP fills at max(basis,Open))", U23, True)

print(f"\n{'='*74}\nPer-symbol, variant B (23 symbols, faithful)\n{'='*74}")
tr = r["23f"][1]
g = tr.groupby("sym").agg(n=("ret","size"), win=("pnl", lambda x:(x>0).mean()),
                          avg_ret=("ret","mean"), pnl=("pnl","sum")).sort_values("pnl", ascending=False)
print(g.round(4).to_string())
