"""
Decide whether a backtest result is an edge or luck.

Usage:
    python3 backtest.py ohlcv.csv --trades-out trades.csv
    python3 validate.py trades.csv --trials 12

    python3 validate.py trades.csv --holdout 0.3     # walk-forward split

`--trials` is the honest number of variants you have tried on this data —
every parameter set, every filter, every symbol sweep, not just the three
that got written down. The deflated Sharpe is only as honest as that number.

Input csv needs a per-trade R column (`r`) or a `pnl` column, plus either a
`session` or an `entry_time` column so trades can be grouped into sessions.
A `variant` column splits the report; without one everything is one variant.
"""

import argparse
import math

import numpy as np
import pandas as pd

import stats


def load_trades(path: str) -> pd.DataFrame:
    t = pd.read_csv(path)
    t.columns = [c.lower() for c in t.columns]

    if "r" not in t.columns:
        if "pnl" not in t.columns:
            raise SystemExit("csv needs an 'r' or a 'pnl' column")
        print("! No 'r' column — falling back to raw pnl. Per-trade R is the\n"
              "  better unit: it normalizes across symbols and volatility.")
        t["r"] = t["pnl"]

    if "session" not in t.columns:
        if "entry_time" not in t.columns:
            raise SystemExit("csv needs a 'session' or an 'entry_time' column")
        t["session"] = pd.to_datetime(t["entry_time"]).dt.date

    if "variant" not in t.columns:
        t["variant"] = "all"

    t = t.dropna(subset=["r"])
    if t.empty:
        raise SystemExit("no usable trades in csv")
    return t


def describe(name: str, t: pd.DataFrame, n_boot: int, seed: int,
             alpha: float) -> dict:
    r = t["r"].to_numpy(dtype=float)
    n = r.size

    out = {"name": name, "n": n, "sessions": t["session"].nunique()}

    if n < 2 or r.std(ddof=1) == 0:
        out["degenerate"] = True
        out["mean_r"] = float(r.mean())
        return out

    m = stats.sharpe_moments(r)
    out.update(m)

    block = stats.block_bootstrap_mean(r, t["session"], n_boot=n_boot,
                                       seed=seed, alpha=alpha)
    iid = stats.block_bootstrap_mean(r, np.arange(n), n_boot=n_boot,
                                     seed=seed, alpha=alpha)
    out["block"] = block
    out["iid"] = iid
    out["n_eff"] = stats.effective_sample_size(n, iid["se"], block["se"])
    out["n_needed"] = stats.n_for_expectancy(m["mean"], m["sd"], alpha=alpha)
    out["mean_r"] = m["mean"]
    return out


def print_variant(d: dict, alpha: float) -> None:
    print(f"── {d['name']}")
    if d.get("degenerate"):
        print(f"   {d['n']} trade(s) — too few to say anything.\n")
        return

    pct = int(round((1 - alpha) * 100))
    b, i_ = d["block"], d["iid"]

    print(f"   trades {d['n']}  over {d['sessions']} sessions"
          f"   ({d['n'] / d['sessions']:.1f} per session)")
    print(f"   mean R {d['mean']:+.4f}   SD {d['sd']:.3f}"
          f"   Sharpe/trade {d['sharpe']:+.4f}")
    print(f"   skew {d['skew']:+.2f}   kurtosis {d['kurtosis']:.2f}"
          f"  {'(fat-tailed)' if d['kurtosis'] > 4 else ''}")
    print(f"   {pct}% CI on mean R")
    print(f"       session blocks  [{b['ci_lo']:+.4f}, {b['ci_hi']:+.4f}]"
          f"   SE {b['se']:.4f}   P(mean R ≤ 0) = {b['p_le_zero']:.3f}")
    print(f"       naive iid       [{i_['ci_lo']:+.4f}, {i_['ci_hi']:+.4f}]"
          f"   SE {i_['se']:.4f}")

    widening = b["se"] / i_["se"] if i_["se"] else float("nan")
    print(f"   clustering: block SE is {widening:.2f}× the iid SE"
          f"  →  {d['n']} trades ≈ {d['n_eff']:.0f} independent bets")
    if widening < 1.05:
        print("       (no measurable clustering at this trade count)")

    need = d["n_needed"]
    print(f"   power: detecting a {d['mean']:+.4f} R edge at this dispersion needs")
    if math.isinf(need):
        print("       — infinite: the observed edge is not positive")
    else:
        verdict = "enough" if d["n_eff"] >= need else "NOT enough"
        print(f"       ≈{need:.0f} independent trades (one-sided, 80% power)"
              f"  →  have ≈{d['n_eff']:.0f}: {verdict}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trades", help="trades csv from backtest.py --trades-out")
    ap.add_argument("--trials", type=int, default=None,
                    help="honest count of variants tried on this data "
                         "(default: number of variants in the csv)")
    ap.add_argument("--sr-variance", type=float, default=None,
                    help="override V[SR] across trials for the deflated Sharpe")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--boot", type=int, default=10_000, help="bootstrap replicates")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--holdout", type=float, default=None, metavar="FRAC",
                    help="split sessions chronologically and report the last "
                         "FRAC as out-of-sample. Look at this ONCE.")
    args = ap.parse_args()

    t = load_trades(args.trades)
    variants = list(t["variant"].unique())

    print()
    print(f"{len(t):,} trades   {t['session'].nunique()} sessions"
          f"   {len(variants)} variant(s) in file")
    print("=" * 78)
    print()

    results = []
    for v in variants:
        d = describe(v, t[t["variant"] == v], args.boot, args.seed, args.alpha)
        results.append(d)
        print_variant(d, args.alpha)

    # ---------------------------------------------------------- selection bias
    usable = [d for d in results if not d.get("degenerate")]
    print("─" * 78)
    print("SELECTION BIAS")
    print()

    if not usable:
        print("  Nothing with enough trades to deflate.\n")
        return

    best = max(usable, key=lambda d: d["sharpe"])
    n_trials = args.trials if args.trials is not None else len(variants)

    if args.sr_variance is not None:
        sr_var = args.sr_variance
        src = "supplied"
    elif len(usable) >= 2:
        sr_var = float(np.var([d["sharpe"] for d in usable], ddof=1))
        src = f"measured across the {len(usable)} variants in this file"
    else:
        print("  Only one variant here, so V[SR] across trials cannot be\n"
              "  estimated from the file. Re-run with every variant you tried,\n"
              "  or pass --sr-variance. Skipping the deflated Sharpe: an\n"
              "  undeflated one would overstate the result.\n")
        return

    dsr = stats.deflated_sharpe_ratio(
        best["sharpe"], sr_var, n_trials, best["n"],
        best["skew"], best["kurtosis"])

    psr0 = stats.probabilistic_sharpe_ratio(
        best["sharpe"], 0.0, best["n"], best["skew"], best["kurtosis"])

    print(f"  best by Sharpe/trade : {best['name']}  ({best['sharpe']:+.4f})")
    print(f"  trials counted       : {n_trials}"
          f"{'  (from the csv — override with --trials)' if args.trials is None else ''}")
    print(f"  V[SR] across trials  : {sr_var:.6f}  ({src})")
    print(f"  E[max SR] under null : {dsr['sr_star']:+.4f}"
          "   ← what the best of that many worthless variants posts by luck")
    print()
    print(f"  PSR vs 0             : {psr0:.3f}   P(true Sharpe > 0), ignoring selection")
    print(f"  Deflated Sharpe      : {dsr['dsr']:.3f}   P(true Sharpe > E[max SR])")
    print()
    if dsr["dsr"] >= 0.95:
        print("  → survives deflation at the 95% level.")
    elif dsr["dsr"] >= 0.90:
        print("  → marginal. Treat as a candidate, not a result.")
    else:
        print("  → does not survive deflation. The winner is consistent with"
              " having been\n    picked out of noise.")

    if args.trials is None:
        print()
        print("  NOTE: trials was taken from the csv, which counts only the"
              " variants that\n  made it into the file. Every parameter tweak,"
              " filter and symbol you tried\n  belongs in that number. Pass the"
              " real count with --trials.")
    if len(usable) < 10 and args.sr_variance is None:
        print()
        print(f"  NOTE: V[SR] from {len(usable)} variants is itself a noisy"
              " estimate, and it drives\n  E[max SR] directly. Treat the"
              " deflated Sharpe as indicative at this count.")
    print()

    # ---------------------------------------------------------- walk-forward
    if args.holdout is not None:
        if not 0.0 < args.holdout < 1.0:
            raise SystemExit("--holdout must be between 0 and 1")
        print("─" * 78)
        print(f"WALK-FORWARD SPLIT  (last {args.holdout:.0%} of sessions held out)")
        print()
        sessions = sorted(t["session"].unique())
        cut = int(len(sessions) * (1 - args.holdout))
        if cut < 1 or cut >= len(sessions):
            raise SystemExit("not enough sessions to split")
        is_sessions = set(sessions[:cut])
        print(f"  in-sample     {sessions[0]} → {sessions[cut - 1]}  ({cut} sessions)")
        print(f"  out-of-sample {sessions[cut]} → {sessions[-1]}"
              f"  ({len(sessions) - cut} sessions)")
        print()
        print(f"  {'variant':<24}{'IS mean R':>12}{'IS n':>7}"
              f"{'OOS mean R':>13}{'OOS n':>8}")
        for v in variants:
            tv = t[t["variant"] == v]
            is_r = tv[tv["session"].isin(is_sessions)]["r"]
            oos_r = tv[~tv["session"].isin(is_sessions)]["r"]
            is_m = f"{is_r.mean():+.4f}" if len(is_r) else "—"
            oos_m = f"{oos_r.mean():+.4f}" if len(oos_r) else "—"
            print(f"  {str(v):<24}{is_m:>12}{len(is_r):>7}{oos_m:>13}{len(oos_r):>8}")
        print()
        print("  This split is single-use. Every time you tune after reading it,"
              " it becomes\n  in-sample and stops being evidence.")
        print()


if __name__ == "__main__":
    main()
