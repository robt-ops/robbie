"""
Daily mean reversion — the two hypotheses registered in PREREGISTRATION.md.

Run it:
    python3 daily.py /path/to/daily/*.csv

Nothing here is tunable from the command line, by design. The parameters are
the registered ones; a flag to change them would be a flag to go looking for
a result, and the registration fixed the trial count at 2.

The primary metric is drift-adjusted excess return. A long-only daily
strategy over a rising market shows a profit from drift alone, so every trade
is measured against the mean same-length forward return for the same symbol
across the whole sample: did the entry timing beat an arbitrary day's entry
of the same length in the same instrument?
"""

import os
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "thor-3bar-reversal"))
import stats                                    # noqa: E402
from backtest import CONFIGS, load_ohlcv, run   # noqa: E402

ETF = "SPY QQQ IWM DIA XLF XLE XLK XLV XLI XLP".split()
CAP = "AAPL MSFT NVDA AMZN GOOGL META JPM JNJ XOM WMT".split()

COST_PER_SIDE = 0.0001        # 1 bp, as registered

# H1, Connors' specification
RSI_LEN, RSI_ENTRY, RSI_EXIT = 2, 10, 70
SMA_LEN, MAX_HOLD = 200, 10


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder-smoothed RSI."""
    d = close.diff()
    gain = d.clip(lower=0.0)
    loss = (-d).clip(lower=0.0)
    ag = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    al = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    out = 100.0 - 100.0 / (1.0 + ag / al.replace(0.0, np.nan))
    return out.where(al != 0, 100.0)


def benchmark_curve(open_: pd.Series, max_h: int) -> dict:
    """Mean h-day open-to-open return for this symbol, for each h."""
    o = open_.to_numpy(dtype=float)
    out = {}
    for h in range(1, max_h + 1):
        if h >= len(o):
            break
        r = o[h:] / o[:-h] - 1.0
        r = r[np.isfinite(r)]
        if r.size:
            out[h] = float(r.mean())
    return out


def run_h1(df: pd.DataFrame) -> pd.DataFrame:
    """RSI(2) < 10 above the 200-day SMA. Long only, no stop."""
    c, o = df["close"], df["open"]
    r = rsi(c, RSI_LEN)
    sma = c.rolling(SMA_LEN).mean()
    entry_sig = (r < RSI_ENTRY) & (c > sma) & sma.notna()
    exit_sig = r > RSI_EXIT

    o_arr = o.to_numpy(dtype=float)
    es, xs = entry_sig.to_numpy(), exit_sig.to_numpy()
    dates = df.index

    trades, i, n = [], 0, len(df)
    while i < n - 1:
        if not es[i]:
            i += 1
            continue
        entry_idx = i + 1                      # fill at the next open
        if entry_idx >= n:
            break
        exit_idx = None
        for k in range(entry_idx, n - 1):
            if xs[k]:                          # signal at this close
                exit_idx = k + 1               # fill at the next open
                break
            if k - entry_idx + 1 >= MAX_HOLD:  # hard exit
                exit_idx = k + 1
                break
        if exit_idx is None or exit_idx >= n:
            break
        ep, xp = o_arr[entry_idx], o_arr[exit_idx]
        gross = xp / ep - 1.0
        trades.append({
            "entry_date": dates[entry_idx], "exit_date": dates[exit_idx],
            "h": exit_idx - entry_idx, "side": 1,
            "ret": gross - 2 * COST_PER_SIDE, "gross_ret": gross,
        })
        i = exit_idx                           # no overlapping positions
    return pd.DataFrame(trades)


def run_h2(df: pd.DataFrame) -> pd.DataFrame:
    """THOR 3-bar pattern on daily bars. Pure bracket, no break-even stop."""
    cfg = replace(
        CONFIGS["v1"],
        use_ema=False, use_vwap=False, use_htf=False,
        vol_mult=0.0, min_body_pct=0.0,          # pattern only
        use_be=False, max_bars_hold=10 ** 6,     # pure bracket
        risk_atr=1.25, target_atr=2.00,
        commission_pct=COST_PER_SIDE, slippage_ticks=0.0,
        htf="W", entry_mode="next_open",
    )
    t = run(df, cfg)["trades"]
    if not len(t):
        return pd.DataFrame()
    side = np.where(t["side"] == "long", 1, -1)
    gross = np.where(side == 1,
                     t["exit"] / t["entry"] - 1.0,
                     t["entry"] / t["exit"] - 1.0)
    return pd.DataFrame({
        "entry_date": pd.to_datetime(t["entry_time"]),
        "exit_date": pd.to_datetime(t["exit_time"]),
        "h": t["bars"].clip(lower=1).to_numpy(),
        "side": side,
        "ret": gross - 2 * COST_PER_SIDE,
        "gross_ret": gross,
        "r": t["r"].to_numpy(),
    })


def attach_excess(t: pd.DataFrame, df: pd.DataFrame, sym: str) -> pd.DataFrame:
    """Drift-adjust each trade and normalise by the symbol's daily vol."""
    if not len(t):
        return t
    bench = benchmark_curve(df["open"], int(t["h"].max()))
    daily_vol = float(df["close"].pct_change().std())
    b = t["h"].map(bench)
    # Drift helps a long and hurts a short, so the benchmark takes the side.
    t = t.assign(
        symbol=sym,
        bench=b * t["side"],
        excess=t["ret"] - b * t["side"],
        daily_vol=daily_vol,
    )
    t["excess_sigma"] = t["excess"] / daily_vol
    return t.dropna(subset=["excess"])


def pooled(t: pd.DataFrame, col: str = "excess") -> dict:
    """CI under three clusterings; the widest decides."""
    v = t[col].to_numpy(dtype=float)
    out = {}
    for name, blocks in [
        ("symbol+date (as registered)",
         t["symbol"] + "|" + t["entry_date"].dt.strftime("%Y-%m-%d")),
        ("date (market-wide moves)",
         t["entry_date"].dt.strftime("%Y-%m-%d")),
        ("month", t["entry_date"].dt.strftime("%Y-%m")),
    ]:
        out[name] = stats.block_bootstrap_mean(v, blocks, n_boot=5000, seed=0)
    return out


def report(label: str, t: pd.DataFrame, universe: str) -> dict:
    print(f"\n── {label}  ·  {universe}")
    if not len(t):
        print("   no trades")
        return {}
    months = t["entry_date"].dt.to_period("M").nunique()
    print(f"   {len(t):,} trades   {t['symbol'].nunique()} symbols   "
          f"{months} distinct months   median hold {int(t['h'].median())}d")
    print(f"   raw mean return     {t['ret'].mean() * 1e4:+8.1f} bp"
          f"   (gross {t['gross_ret'].mean() * 1e4:+.1f} bp)")
    print(f"   drift benchmark     {t['bench'].mean() * 1e4:+8.1f} bp"
          f"   ← what an arbitrary same-length entry returned")
    print(f"   EXCESS              {t['excess'].mean() * 1e4:+8.1f} bp"
          f"   ({t['excess_sigma'].mean():+.3f} daily sigma)")
    print(f"   win rate (raw)      {(t['ret'] > 0).mean() * 100:8.1f} %"
          f"   excess-positive {(t['excess'] > 0).mean() * 100:.1f} %")

    cis = pooled(t)
    print("   95% CI on excess (bp):")
    widest = None
    for name, b in cis.items():
        lo, hi = b["ci_lo"] * 1e4, b["ci_hi"] * 1e4
        print(f"       {name:<28} [{lo:+8.1f}, {hi:+8.1f}]"
              f"   P(≤0) {b['p_le_zero']:.3f}   blocks {b['n_blocks']:,}")
        if widest is None or (hi - lo) > widest[1]:
            widest = (b, hi - lo, name)
    reg = cis["symbol+date (as registered)"]
    b = widest[0]
    v = t["excess"].to_numpy(dtype=float)
    return {"n": len(t), "months": months, "mean": float(t["excess"].mean()),
            "reg_lo": reg["ci_lo"], "reg_hi": reg["ci_hi"],
            "reg_p": reg["p_le_zero"],
            "wid_lo": b["ci_lo"], "wid_hi": b["ci_hi"], "wid_p": b["p_le_zero"],
            "widest": widest[2], "trades": t,
            "sharpe": float(v.mean() / v.std(ddof=1)) if v.std(ddof=1) else 0.0,
            "moments": stats.sharpe_moments(v)}


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit("usage: python3 daily.py /path/to/daily/*.csv")

    data = {}
    for p in paths:
        sym = os.path.splitext(os.path.basename(p))[0].upper()
        data[sym] = load_ohlcv(p)

    print("DAILY MEAN REVERSION — registered hypotheses, no tuning")
    print("=" * 78)
    spans = [(df.index.min(), df.index.max()) for df in data.values()]
    print(f"{len(data)} symbols   {min(s[0] for s in spans).date()} → "
          f"{max(s[1] for s in spans).date()}   "
          f"{sum(len(d) for d in data.values()):,} bars")

    results = {}
    for hlabel, fn in [("H1  RSI(2) < 10, close > SMA200", run_h1),
                       ("H2  3-bar pattern, pure bracket", run_h2)]:
        per_sym = {}
        for sym, df in data.items():
            t = attach_excess(fn(df), df, sym)
            if len(t):
                per_sym[sym] = t

        print("\n" + "=" * 78)
        print(hlabel)

        for uname, members in [("ETF set (PRIMARY — decides)", ETF),
                               ("large caps (survivorship-biased)", CAP)]:
            sub = [per_sym[s] for s in members if s in per_sym]
            if not sub:
                continue
            t = pd.concat(sub, ignore_index=True)
            results[(hlabel, uname)] = report(hlabel.split()[0], t, uname)

        # per-symbol excess, ETF set only
        print(f"\n   per-symbol excess (bp), ETF set:")
        line = []
        for s in ETF:
            if s in per_sym:
                line.append(f"{s} {per_sym[s]['excess'].mean() * 1e4:+.0f}")
        print("       " + "   ".join(line))

    # ------------------------------------------------------- decision rule
    print("\n" + "=" * 78)
    print("DECISION RULE (fixed in PREREGISTRATION.md, all four required)")

    hyps = ["H1  RSI(2) < 10, close > SMA200",
            "H2  3-bar pattern, pure bracket"]
    primary = "ETF set (PRIMARY — decides)"

    # V[SR] across the registered trials, for the deflated Sharpe. Two
    # hypotheses were registered, so n_trials = 2 and the deflation is mild
    # -- which is the point of registering in advance.
    sharpes = [results[(h, primary)]["sharpe"] for h in hyps
               if results.get((h, primary))]
    sr_var = float(np.var(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
    n_trials = 2

    for hlabel in hyps:
        d = results.get((hlabel, primary))
        print(f"\n  {hlabel}")
        if not d:
            print("    no trades on the primary set → FAIL")
            continue

        # Condition 1 is judged exactly as registered: symbol+date clustering.
        c1 = d["mean"] > 0 and d["reg_lo"] > 0
        # Condition 2: the ETF set carries it on its own, not only with the
        # survivorship-biased large caps. On the primary set this is the same
        # test as (1) -- the registration made the ETF set the primary, so
        # the two conditions coincide here rather than being independent.
        c2 = c1
        m = d["moments"]
        dsr = stats.deflated_sharpe_ratio(m["sharpe"], sr_var, n_trials,
                                          m["n"], m["skew"], m["kurtosis"])
        c3 = dsr["dsr"] >= 0.95
        c4 = d["n"] >= 300 and d["months"] >= 20

        print(f"    1. excess > 0, CI excludes zero   {'PASS' if c1 else 'FAIL'}"
              f"   {d['mean'] * 1e4:+.1f} bp,"
              f" CI [{d['reg_lo'] * 1e4:+.1f}, {d['reg_hi'] * 1e4:+.1f}]"
              f" as registered")
        print(f"    2. holds on the ETF set alone     {'PASS' if c2 else 'FAIL'}"
              f"   (same test as 1: the ETF set IS the primary)")
        print(f"    3. deflated Sharpe ≥ 0.95         {'PASS' if c3 else 'FAIL'}"
              f"   DSR {dsr['dsr']:.3f}"
              f"  (SR/trade {m['sharpe']:+.4f}, {n_trials} trials)")
        print(f"    4. ≥300 trades, ≥20 months        {'PASS' if c4 else 'FAIL'}"
              f"   {d['n']:,} trades, {d['months']} months")
        verdict = "EDGE" if (c1 and c2 and c3 and c4) else "NO EDGE"
        print(f"    → {verdict} at the registered parameters")

        # Stricter clustering than registered: disclosed, never used to
        # upgrade a result -- only to qualify one.
        if c1:
            held = d["wid_lo"] > 0
            print(f"    ROBUSTNESS (stricter than registered, disclosed):")
            print(f"      under {d['widest']} clustering the CI is"
                  f" [{d['wid_lo'] * 1e4:+.1f}, {d['wid_hi'] * 1e4:+.1f}],"
                  f" P(≤0) {d['wid_p']:.3f}")
            print(f"      → {'still excludes zero' if held else 'INCLUDES ZERO'}."
                  + ("" if held else " Treat as a candidate, not a result."))
    print()


if __name__ == "__main__":
    main()
