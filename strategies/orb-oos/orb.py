"""
Out-of-sample test of the Zarattini/Aziz QQQ opening-range breakout.

Rules are the registered ones (see PREREGISTRATION.md) and are not
configurable: they were fixed by the paper before this data existed, and a
flag to change them would be a flag to go looking for a result.

    python3 orb.py /path/to/qqq_5m.csv
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "thor-3bar-reversal"))
import stats  # noqa: E402

OOS_START = "2023-03-01"      # the paper's sample ends Feb 2023
START_EQUITY = 25_000.0
TARGET_R = 10.0
ENTRY_SLIP = 0.02             # $/share, primary cost model
STOP_EXTRA = 0.04             # $/share additional, on stop exits
RISK_FRAC = 0.01
LEVERAGE_CAP = 4.0
TRADING_DAYS = 252


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df[df.index >= OOS_START]


def run_orb(df: pd.DataFrame, entry_slip: float = ENTRY_SLIP,
            stop_extra: float = STOP_EXTRA, compound: bool = True) -> pd.DataFrame:
    equity = START_EQUITY
    out = []

    for day, g in df.groupby(df.index.date):
        t = g.index.time
        is_open = [i for i, x in enumerate(t) if x.hour == 9 and x.minute == 30]
        if not is_open or len(g) < 3:
            continue
        i0 = is_open[0]
        if i0 + 1 >= len(g):
            continue

        o, h, l, c = (g["open"].iloc[i0], g["high"].iloc[i0],
                      g["low"].iloc[i0], g["close"].iloc[i0])
        if c > o:
            side = 1
        elif c < o:
            side = -1
        else:
            out.append({"date": day, "side": 0, "reason": "doji",
                        "pnl_share": 0.0, "shares": 0, "pnl": 0.0,
                        "equity": equity, "R": np.nan})
            continue

        entry = float(g["open"].iloc[i0 + 1])
        stop = float(l) if side == 1 else float(h)
        R = abs(entry - stop)
        if R <= 0:
            continue
        target = entry + side * TARGET_R * R

        path = g.iloc[i0 + 1:]
        exit_px, reason = None, None
        for j in range(len(path)):
            hi, lo = float(path["high"].iloc[j]), float(path["low"].iloc[j])
            hit_stop = (lo <= stop) if side == 1 else (hi >= stop)
            hit_tgt = (hi >= target) if side == 1 else (lo <= target)
            if hit_stop and hit_tgt:
                exit_px, reason = stop, "stop"       # pessimistic
                break
            if hit_stop:
                exit_px, reason = stop, "stop"
                break
            if hit_tgt:
                exit_px, reason = target, "target"
                break
        if exit_px is None:
            exit_px, reason = float(path["close"].iloc[-1]), "close"

        cost = entry_slip + (stop_extra if reason == "stop" else 0.0)
        pnl_share = side * (exit_px - entry) - cost

        eq = equity if compound else START_EQUITY
        shares = int(min(RISK_FRAC * eq / R, LEVERAGE_CAP * eq / entry))
        pnl = shares * pnl_share
        equity += pnl

        out.append({"date": day, "side": side, "entry": entry, "stop": stop,
                    "exit": exit_px, "R": R, "reason": reason,
                    "pnl_share": pnl_share, "shares": shares, "pnl": pnl,
                    "equity": equity})

    return pd.DataFrame(out)


def sharpe_from_daily(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    if r.size < 2 or r.std(ddof=1) == 0:
        return np.nan
    return float(r.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 orb.py qqq_5m.csv")
    df = load(sys.argv[1])
    sessions = df.index.normalize().nunique()

    print("ORB OUT-OF-SAMPLE TEST — registered rules, no tuning")
    print("=" * 78)
    print(f"QQQ 5-minute, {sessions} sessions, "
          f"{df.index.min().date()} → {df.index.max().date()}")
    print(f"Window starts {OOS_START}; the paper's sample ends Feb 2023.")

    t = run_orb(df)
    traded = t[t["side"] != 0].copy()
    n_doji = int((t["side"] == 0).sum())

    print(f"\n{len(traded)} trades, {n_doji} doji days skipped")
    print(f"exit mix: {traded['reason'].value_counts().to_dict()}")

    ps = traded["pnl_share"].to_numpy(dtype=float)
    print(f"\n{'PRIMARY — mean PnL per share, net of the registered costs':<60}")
    b = stats.block_bootstrap_mean(ps, traded["date"].astype(str), n_boot=10000)
    print(f"  mean        ${b['mean']:+.4f}/share")
    print(f"  95% CI      [${b['ci_lo']:+.4f}, ${b['ci_hi']:+.4f}]")
    print(f"  P(≤0)       {b['p_le_zero']:.3f}")
    print(f"  paper/replication gross reference: $0.070/share")

    # gross, and break-even slippage
    g = run_orb(df, entry_slip=0.0, stop_extra=0.0)
    g = g[g["side"] != 0]
    gross = float(g["pnl_share"].mean())
    print(f"\n  gross of all costs   ${gross:+.4f}/share")
    stop_frac = float((traded["reason"] == "stop").mean())
    be = gross / (1.0 + stop_frac * (STOP_EXTRA / ENTRY_SLIP)) if gross > 0 else 0.0
    print(f"  break-even entry slippage  "
          + (f"{be * 100:.2f}¢/share" if gross > 0 else "n/a (gross ≤ 0)")
          + "   [replication found ~2.2¢]")

    # strategy vs buy-and-hold
    daily = traded.set_index(pd.to_datetime(traded["date"]))
    strat_ret = (daily["pnl"] / daily["equity"].shift(1).fillna(START_EQUITY)).to_numpy()
    closes = df.groupby(df.index.date)["close"].last()
    bh_ret = closes.pct_change().dropna().to_numpy()

    s_sr, b_sr = sharpe_from_daily(strat_ret), sharpe_from_daily(bh_ret)
    print(f"\n{'SHARPE (annualised)':<60}")
    print(f"  strategy        {s_sr:+.3f}   [paper 1.12, replication 1.06 in-sample]")
    print(f"  buy & hold QQQ  {b_sr:+.3f}   over the identical window")

    rng = np.random.default_rng(0)
    diffs, s_boot = [], []
    n_s, n_b = len(strat_ret), len(bh_ret)
    for _ in range(5000):
        a = sharpe_from_daily(strat_ret[rng.integers(0, n_s, n_s)])
        bb = sharpe_from_daily(bh_ret[rng.integers(0, n_b, n_b)])
        if np.isfinite(a):
            s_boot.append(a)
            if np.isfinite(bb):
                diffs.append(a - bb)
    s_lo, s_hi = np.percentile(s_boot, [2.5, 97.5])
    d_lo, d_hi = np.percentile(diffs, [2.5, 97.5])
    print(f"  strategy Sharpe 95% CI  [{s_lo:+.3f}, {s_hi:+.3f}]")
    print(f"  (strategy − B&H) 95% CI [{d_lo:+.3f}, {d_hi:+.3f}]"
          f"   P(diff ≤ 0) {np.mean(np.array(diffs) <= 0):.3f}")

    # per-year concentration
    traded["year"] = pd.to_datetime(traded["date"]).dt.year
    by_year = traded.groupby("year")["pnl"].sum()
    total = by_year.sum()
    print(f"\n{'PnL BY YEAR (concentration check)':<60}")
    for y, v in by_year.items():
        share = v / total * 100 if total != 0 else np.nan
        print(f"  {y}   ${v:>12,.0f}   {share:>6.1f}%")
    worst = (by_year / total * 100).max() if total != 0 else np.nan
    print(f"  final equity ${traded['equity'].iloc[-1]:,.0f} "
          f"from ${START_EQUITY:,.0f}")

    # power
    sd = float(np.std(ps, ddof=1))
    need = stats.n_for_expectancy(abs(b["mean"]), sd) if b["mean"] != 0 else np.inf
    print(f"\n  per-share SD ${sd:.4f}; detecting an effect of this size needs "
          f"≈{need:.0f} trades\n  (have {len(traded)})")

    # ------------------------------------------------------------ verdict
    print("\n" + "=" * 78)
    print("DECISION RULE (fixed in PREREGISTRATION.md, all four required)")
    c1 = b["mean"] > 0 and b["ci_lo"] > 0
    c2 = np.isfinite(s_sr) and s_sr > 0 and s_lo > 0
    c3 = d_lo > 0
    c4 = len(traded) >= 300
    print(f"  1. mean PnL/share > 0, CI excludes zero   {'PASS' if c1 else 'FAIL'}"
          f"   ${b['mean']:+.4f} [{b['ci_lo']:+.4f}, {b['ci_hi']:+.4f}]")
    print(f"  2. Sharpe > 0, CI excludes zero           {'PASS' if c2 else 'FAIL'}"
          f"   {s_sr:+.3f} [{s_lo:+.3f}, {s_hi:+.3f}]")
    print(f"  3. beats buy & hold QQQ                   {'PASS' if c3 else 'FAIL'}"
          f"   diff CI [{d_lo:+.3f}, {d_hi:+.3f}]")
    print(f"  4. ≥300 trades                            {'PASS' if c4 else 'FAIL'}"
          f"   {len(traded)}")
    print(f"\n  → {'REPLICATES' if all([c1,c2,c3,c4]) else 'DOES NOT REPLICATE'}"
          f" out-of-sample at the registered rules")
    if np.isfinite(worst):
        print(f"\n  concentration: worst year holds {worst:.1f}% of net PnL"
              f"  ({'FLAG — regime effect' if worst > 60 else 'ok, <60%'})")
    print()


if __name__ == "__main__":
    main()
