#!/usr/bin/env python3
"""
ETF Bollinger mean-reversion — 5m / 15m / 1H, portfolio level.

Universe : SPY QQQ IWM DIA XLK XLF XLV SCHD
Regime   : longs only if SPY > its 200-day SMA (prior completed daily closes)
Entry    : bar close < lower BB(20, 2.0)  -> market buy at that close
Size     : 5% of total equity per trade, max 4 concurrent positions
TP       : first bar after entry whose HIGH >= 20 SMA basis -> sell at that bar's close
SL       : hard stop 1.5% below entry (intrabar; gap-through fills at open)

Usage
  python etf_bbmr.py backtest --tf 1h  [--cash 100000]   # 1h: ~730d history | 5m/15m: 59d (Yahoo limit)
  python etf_bbmr.py backtest --tf 15m
  python etf_bbmr.py backtest --tf 5m
  python etf_bbmr.py scan --tf 15m --equity 250000 [--apply] [--webhook URL]
     Run right after each bar close for the chosen --tf. State file is per timeframe.
     --apply  records the signalled fills in bbmr_state.json (assumes fill at signal close)
"""
import argparse, json, math, sys, urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

UNIVERSE  = ["SPY","QQQ","IWM","DIA","XLK","XLF","XLV","SCHD","XLE","XLI","XLY","XLP","XLU","XLC","XLB","XLRE","RSP","SMH","EFA","EEM","GLD","TLT","HYG"]
BB_LEN    = 20
BB_K      = 2.0
SMA_LONG  = 200
ALLOC     = 0.05
MAX_POS   = 4
STOP_PCT  = 0.015
TZ        = "America/New_York"
TF_MIN    = {"5m": 5, "15m": 15, "1h": 60}
INTERVAL  = "1h"   # set from --tf


# ── data ────────────────────────────────────────────────────────────
def fetch_bars(period: str) -> dict:
    raw = yf.download(UNIVERSE, period=period, interval=INTERVAL, auto_adjust=False,
                      group_by="ticker", progress=False, prepost=False, threads=True)
    out = {}
    for s in UNIVERSE:
        d = raw[s][["Open", "High", "Low", "Close"]].dropna().copy()
        if d.empty:
            sys.exit(f"No {INTERVAL} data for {s} — check network / Yahoo access.")
        d.index = (d.index.tz_localize("UTC") if d.index.tz is None else d.index).tz_convert(TZ)
        out[s] = d
    return out


def drop_open_bar(d: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Only act on fully closed candles."""
    if d.empty:
        return d
    start = d.index[-1]
    end = min(start + pd.Timedelta(minutes=TF_MIN[INTERVAL]), start.normalize() + pd.Timedelta(hours=16))
    return d.iloc[:-1] if end > now else d


def add_bands(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["basis"] = d.Close.rolling(BB_LEN).mean()
    d["lower"] = d["basis"] - BB_K * d.Close.rolling(BB_LEN).std(ddof=0)  # = TradingView ta.stdev
    return d


def add_regime(spy_h: pd.DataFrame, period: str) -> pd.DataFrame:
    daily = yf.download("SPY", period=period, interval="1d", auto_adjust=False, progress=False)["Close"]
    if isinstance(daily, pd.DataFrame):
        daily = daily.iloc[:, 0]
    sma_prev = daily.rolling(SMA_LONG).mean().shift(1)          # SMA of completed days only
    lut = dict(zip(pd.to_datetime(daily.index).date, sma_prev.values))
    spy_h = spy_h.copy()
    spy_h["sma200"] = [lut.get(ts.date(), np.nan) for ts in spy_h.index]
    spy_h["risk_on"] = spy_h.Close > spy_h.sma200
    return spy_h


def load(period_h: str, period_d: str, live: bool) -> dict:
    data = fetch_bars(period_h)
    if live:
        now = pd.Timestamp.now(tz=TZ)
        data = {s: drop_open_bar(d, now) for s, d in data.items()}
    data = {s: add_bands(d) for s, d in data.items()}
    data["SPY"] = add_regime(data["SPY"], period_d)
    return data


# ── portfolio backtest ──────────────────────────────────────────────
def backtest(cash0: float):
    data = load("730d" if INTERVAL == "1h" else "59d", "5y", live=False)
    idx = sorted(set().union(*[d.index for d in data.values()]))
    rows = {s: data[s].to_dict("index") for s in UNIVERSE}

    cash, pos, trades, curve = cash0, {}, [], []
    for t in idx:
        bars = {s: rows[s][t] for s in UNIVERSE if t in rows[s]}

        # exits (stop checked first = conservative when both hit same bar)
        for s in list(pos):
            b, p = bars.get(s), pos[s]
            if b is None or t <= p["t"]:
                continue
            stop = p["entry"] * (1 - STOP_PCT)
            if b["Low"] <= stop:
                px, why = min(b["Open"], stop), "SL"
            elif b["High"] >= b["basis"]:
                px, why = b["Close"], "TP"
            else:
                continue
            cash += p["sh"] * px
            trades.append(dict(sym=s, entry_t=p["t"], exit_t=t, entry=p["entry"], exit=px,
                               shares=p["sh"], pnl=p["sh"] * (px - p["entry"]),
                               ret=px / p["entry"] - 1, why=why,
                               bars=sum(1 for x in rows[s] if p["t"] < x <= t)))
            del pos[s]

        for s, p in pos.items():
            if s in bars:
                p["last"] = bars[s]["Close"]
        equity = cash + sum(p["sh"] * p["last"] for p in pos.values())

        # entries
        spy = bars.get("SPY")
        if spy is not None and bool(spy["risk_on"]) and len(pos) < MAX_POS:
            cands = sorted((b["Close"] / b["lower"] - 1, s) for s, b in bars.items()
                           if s not in pos and not np.isnan(b["lower"]) and b["Close"] < b["lower"])
            for _, s in cands:                      # deepest break first
                if len(pos) >= MAX_POS:
                    break
                px = bars[s]["Close"]
                sh = math.floor(ALLOC * equity / px)
                if sh < 1 or sh * px > cash:
                    continue
                cash -= sh * px
                pos[s] = dict(t=t, entry=px, sh=sh, last=px)

        curve.append((t, equity, len(pos)))

    eq = pd.DataFrame(curve, columns=["t", "equity", "npos"]).set_index("t")
    tr = pd.DataFrame(trades)
    tr.to_csv(f"bbmr_trades_{INTERVAL}.csv", index=False)
    eq.to_csv(f"bbmr_equity_{INTERVAL}.csv")

    dd = (eq.equity / eq.equity.cummax() - 1).min()
    spy = data["SPY"].Close
    print(f"Timeframe     {INTERVAL}")
    print(f"Period        {eq.index[0]:%Y-%m-%d} -> {eq.index[-1]:%Y-%m-%d}")
    print(f"Total return  {eq.equity.iloc[-1] / cash0 - 1:+.2%}   (SPY B&H {spy.iloc[-1] / spy.iloc[BB_LEN] - 1:+.2%})")
    print(f"Max drawdown  {dd:.2%}")
    print(f"Avg exposure  {eq.npos.mean() * ALLOC:.1%}   bars w/ 4 open: {(eq.npos == MAX_POS).mean():.1%}")
    print(f"Risk-on bars  {data['SPY'].risk_on.mean():.1%}")
    if tr.empty:
        print("No trades.")
        return
    w = tr[tr.pnl > 0]
    l = tr[tr.pnl <= 0]
    print(f"Trades        {len(tr)}   win {len(w) / len(tr):.1%}   TP {sum(tr.why == 'TP')}  SL {sum(tr.why == 'SL')}")
    print(f"Avg trade     {tr.ret.mean():+.2%}   avg win {w.ret.mean():+.2%}   avg loss {l.ret.mean() if len(l) else 0:+.2%}")
    print(f"Profit factor {w.pnl.sum() / -l.pnl.sum() if l.pnl.sum() else float('inf'):.2f}   avg hold {tr.bars.mean():.1f} bars")
    print("\nBy symbol:")
    print(tr.groupby("sym").agg(n=("ret", "size"), win=("pnl", lambda x: (x > 0).mean()),
                                avg_ret=("ret", "mean"), pnl=("pnl", "sum")).round(4).to_string())


# ── live scan ───────────────────────────────────────────────────────
def scan(equity: float, apply: bool, webhook: str | None):
    state_f = Path(f"bbmr_state_{INTERVAL}.json")
    state = json.loads(state_f.read_text()) if state_f.exists() else {"positions": {}}
    pos = state["positions"]
    data = load("60d" if INTERVAL == "1h" else "10d", "2y", live=True)
    spy = data["SPY"].iloc[-1]
    risk_on = bool(spy.risk_on)
    actions = []

    print(f"Last closed bar {data['SPY'].index[-1]:%Y-%m-%d %H:%M} ET | SPY {spy.Close:.2f} vs 200D {spy.sma200:.2f} "
          f"-> {'RISK-ON' if risk_on else 'RISK-OFF (no new longs)'}")

    # exits
    for s, p in list(pos.items()):
        d = data[s][data[s].index > pd.Timestamp(p["t"])]
        stop = p["entry"] * (1 - STOP_PCT)
        for t, b in d.iterrows():
            if b.Low <= stop:
                actions.append(dict(action="sell", reason="SL", ticker=s, shares=p["shares"],
                                    price=round(min(b.Open, stop), 2), bar=str(t)))
                break
            if b.High >= b.basis:
                actions.append(dict(action="sell", reason="TP", ticker=s, shares=p["shares"],
                                    price=round(b.Close, 2), bar=str(t)))
                break
    sold = {a["ticker"] for a in actions}

    # entries
    held = {s for s in pos if s not in sold}
    slots = MAX_POS - len(held)
    if risk_on and slots > 0:
        cands = []
        for s in UNIVERSE:
            if s in held:
                continue
            b = data[s].iloc[-1]
            if not np.isnan(b.lower) and b.Close < b.lower:
                cands.append((b.Close / b.lower - 1, s, b))
        for _, s, b in sorted(cands)[:slots]:
            sh = math.floor(ALLOC * equity / b.Close)
            if sh < 1:
                continue
            actions.append(dict(action="buy", ticker=s, shares=sh, price=round(b.Close, 2),
                                stop=round(b.Close * (1 - STOP_PCT), 2), bar=str(data[s].index[-1])))

    # report
    for s, p in pos.items():
        if s not in sold:
            b = data[s].iloc[-1]
            print(f"  HOLD {s:5} {p['shares']} @ {p['entry']:.2f} | last {b.Close:.2f} | TP>= {b.basis:.2f} | SL {p['entry'] * (1 - STOP_PCT):.2f}")
    for a in actions:
        print("  " + json.dumps(a))
    if not actions:
        print("  No action.")

    if webhook:
        for a in actions:
            req = urllib.request.Request(webhook, data=json.dumps(a).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)

    if apply:
        for a in actions:
            if a["action"] == "sell":
                pos.pop(a["ticker"], None)
            else:
                pos[a["ticker"]] = dict(t=a["bar"], entry=a["price"], shares=a["shares"])
        state_f.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest"); b.add_argument("--cash", type=float, default=100_000)
    s = sub.add_parser("scan"); s.add_argument("--equity", type=float, required=True)
    for x in (b, s):
        x.add_argument("--tf", choices=list(TF_MIN), default="1h")
    s.add_argument("--apply", action="store_true"); s.add_argument("--webhook")
    a = ap.parse_args()
    INTERVAL = a.tf
    backtest(a.cash) if a.cmd == "backtest" else scan(a.equity, a.apply, a.webhook)
