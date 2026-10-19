"""
Search the parameter space without fooling yourself.

Two modes:

  --mode ablation   Start from a base version, switch off one filter at a
                    time, and report what each filter is actually worth.
                    Answers "does this filter earn its place" instead of
                    assuming it does. The all-off row is the raw 3-bar
                    pattern with nothing in front of it.

  --mode costs      Decompose the result into gross edge and each cost
                    component, in R. If the gross edge is already negative,
                    no cost tuning will save it and no filter search is
                    worth running.

  --mode attribution
                    The one that matters. Splits mean R into the entry
                    signal, each exit rule, and costs, so you can see which
                    component is losing the money. Takes one or many csvs.

                    The entry signal is measured through a pure bracket
                    (no break-even stop, no time stop) gross of costs: if
                    that is zero, the signal carries no information and no
                    filter will give it any.

  --mode symbols    Run the same rules across several instruments and pool
                    them. One symbol can be luck; a sign that holds across
                    a basket is a property of the rules. Pass several csvs.

  --mode grid       Enumerate the filter/parameter grid, rank the variants,
                    and then deflate the winner by the number of variants
                    tried — which this script counts for you, because that
                    count is the one number people fudge.

Searching in-sample and reporting the winner's out-of-sample result is the
default posture: pass --holdout 0.3 and the ranking only ever sees the first
70% of sessions.

Usage:
    python3 sweep.py ohlcv.csv --mode ablation
    python3 sweep.py ohlcv.csv --mode grid --holdout 0.3
    python3 sweep.py ohlcv.csv --mode grid --trades-out grid_trades.csv
"""

import argparse
import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

import stats
from backtest import CONFIGS, atr, run, load_ohlcv

# Each filter and what switching it off means. The last entry strips
# everything, leaving the bare 3-bar pattern (the README's "v7" idea).
ABLATIONS = [
    ("baseline (all on)", {}),
    ("no EMA filter", {"use_ema": False}),
    ("no VWAP filter", {"use_vwap": False}),
    ("no HTF filter", {"use_htf": False}),
    ("no volume filter", {"vol_mult": 0.0}),
    ("no body filter", {"min_body_pct": 0.0}),
    ("loose bar 3", {"strict_bar3": False}),
    ("no break-even stop", {"use_be": False}),
    ("pattern only (all off)", {"use_ema": False, "use_vwap": False,
                                "use_htf": False, "vol_mult": 0.0,
                                "min_body_pct": 0.0}),
]

GRID = {
    "use_vwap": [True, False],
    "use_htf": [True, False],
    "strict_bar3": [True, False],
    "vol_mult": [0.0, 1.25, 1.50],
    "min_body_pct": [0.40, 0.55],
    "risk_target": [(1.00, 2.00), (1.25, 2.00), (1.50, 3.00)],
}

SHORT = {"use_vwap": "vwap", "use_htf": "htf", "strict_bar3": "strict",
         "vol_mult": "vol", "min_body_pct": "body"}

# Cost models to price the same signal set through, cheapest last.
COST_MODELS = [
    ("as configured", {}),
    ("no commission", {"commission_pct": 0.0}),
    ("no slippage", {"slippage_ticks": 0.0}),
    ("1 tick, no commission", {"commission_pct": 0.0, "slippage_ticks": 1.0}),
    ("zero costs (gross edge)", {"commission_pct": 0.0, "slippage_ticks": 0.0}),
]


def expand_grid(grid: dict):
    """Every combination, as (label, overrides)."""
    keys = list(grid)
    for combo in itertools.product(*(grid[k] for k in keys)):
        overrides, parts = {}, []
        for k, v in zip(keys, combo):
            if k == "risk_target":
                overrides["risk_atr"], overrides["target_atr"] = v
                parts.append(f"R{v[0]:g}/{v[1]:g}")
            elif isinstance(v, bool):
                parts.append(f"{SHORT[k]}{'+' if v else '-'}")
                overrides[k] = v
            else:
                parts.append(f"{SHORT[k]}{v:g}")
                overrides[k] = v
        yield " ".join(parts), overrides


def evaluate(df: pd.DataFrame, base, label: str, overrides: dict,
             entry_mode: str) -> dict:
    cfg = replace(base, name=label, entry_mode=entry_mode, **overrides)
    res = run(df, cfg)
    t = res["trades"]
    out = {"label": label, "n": res["n"], "trades": t}
    if res["n"] == 0:
        out.update(mean_r=np.nan, sharpe=np.nan, sessions=0)
        return out
    r = t["r"].dropna().to_numpy()
    out["sessions"] = t["session"].nunique()
    out["mean_r"] = float(r.mean()) if r.size else np.nan
    out["sharpe"] = (float(r.mean() / r.std(ddof=1))
                     if r.size > 1 and r.std(ddof=1) > 0 else np.nan)
    return out


def split_sessions(t: pd.DataFrame, holdout: float):
    sessions = sorted(t["session"].unique())
    cut = int(len(sessions) * (1 - holdout))
    return set(sessions[:cut]), set(sessions[cut:])


def mean_r_on(t: pd.DataFrame, keep: set):
    sub = t[t["session"].isin(keep)]["r"].dropna()
    return (float(sub.mean()) if len(sub) else np.nan), len(sub)


PATTERN_ONLY = {"use_ema": False, "use_vwap": False, "use_htf": False,
                "vol_mult": 0.0, "min_body_pct": 0.0}


def run_symbols(args) -> None:
    """Same rules, many instruments, pooled with clustering respected."""
    import os

    base = CONFIGS[args.base]
    variants = [("with filters", {}), ("pattern only", PATTERN_ONLY)]
    rows, pooled = [], {k: [] for k, _ in variants}

    for path in args.csv:
        sym = os.path.splitext(os.path.basename(path))[0].upper()
        df = load_ohlcv(path)
        row = {"symbol": sym, "sessions": df.index.normalize().nunique()}
        for vlabel, ov in variants:
            d = evaluate(df, base, vlabel, ov, args.entry)
            row[vlabel] = d
            t = d["trades"]
            if len(t):
                t = t.copy()
                t["symbol"] = sym
                # Cluster on symbol+session: two symbols on one day are not
                # one bet, and one symbol across a day is not many.
                t["block"] = sym + "|" + t["session"].astype(str)
                pooled[vlabel].append(t)
        rows.append(row)

    print(f"\n{len(args.csv)} instruments   base {base.name}   entry {args.entry}")
    print(f"\n{'symbol':<8}{'sess':>6}"
          f"{'filtered N':>12}{'mean R':>9}"
          f"{'pattern N':>12}{'mean R':>9}")
    print("─" * 60)
    for row in rows:
        f_, p_ = row["with filters"], row["pattern only"]
        fm = "—" if np.isnan(f_["mean_r"]) else f"{f_['mean_r']:+.3f}"
        pm = "—" if np.isnan(p_["mean_r"]) else f"{p_['mean_r']:+.3f}"
        print(f"{row['symbol']:<8}{row['sessions']:>6}"
              f"{f_['n']:>12}{fm:>9}{p_['n']:>12}{pm:>9}")

    print("\n" + "─" * 60)
    print("POOLED")
    for vlabel, _ in variants:
        if not pooled[vlabel]:
            continue
        t = pd.concat(pooled[vlabel], ignore_index=True)
        r = t["r"].dropna()
        b = stats.block_bootstrap_mean(r.to_numpy(), t.loc[r.index, "block"],
                                       n_boot=5000, seed=0)
        n_pos = sum(1 for row in rows
                    if not np.isnan(row[vlabel]["mean_r"])
                    and row[vlabel]["mean_r"] > 0)
        print(f"\n  {vlabel}")
        print(f"    {b['n']:,} trades over {b['n_blocks']:,} symbol-sessions")
        print(f"    mean R {b['mean']:+.4f}   95% CI "
              f"[{b['ci_lo']:+.4f}, {b['ci_hi']:+.4f}]   SE {b['se']:.4f}")
        print(f"    P(mean R ≤ 0) = {b['p_le_zero']:.3f}")
        print(f"    positive on {n_pos} of {len(rows)} instruments")

    print()
    print("  A sign that flips around zero across the basket is noise. One that"
          "\n  holds on every instrument is a property of the rules —"
          " in whichever direction.")
    print()


# The ladder: each rung adds one component to the one above it, so the
# difference between consecutive rungs is that component's contribution.
LADDER = [
    ("entry signal (pure bracket, gross)",
     {"use_be": False, "max_bars_hold": 10 ** 6,
      "commission_pct": 0.0, "slippage_ticks": 0.0}),
    ("+ break-even stop",
     {"max_bars_hold": 10 ** 6, "commission_pct": 0.0, "slippage_ticks": 0.0}),
    ("+ time stop",
     {"commission_pct": 0.0, "slippage_ticks": 0.0}),
    ("+ costs  = as configured", {}),
]


def pooled_r(dfs: dict, base, overrides: dict, entry_mode: str,
             n_boot: int = 4000) -> dict:
    """Pool one config's trades across instruments, clustering on symbol+session."""
    frames = []
    for sym, df in dfs.items():
        t = run(df, replace(base, entry_mode=entry_mode, **overrides))["trades"]
        if not len(t):
            continue
        t = t.copy()
        t["block"] = sym + "|" + t["session"].astype(str)
        frames.append(t)
    if not frames:
        return {"n": 0, "mean": np.nan}
    t = pd.concat(frames, ignore_index=True)
    r = t["r"].dropna()
    out = stats.block_bootstrap_mean(r.to_numpy(), t.loc[r.index, "block"],
                                     n_boot=n_boot, seed=0)
    out["win"] = float((t["pnl"] > 0).mean() * 100)
    return out


def run_attribution(args) -> None:
    import os

    base = CONFIGS[args.base]
    # Strip the filters: attribution is about the signal and the exits, and
    # the filters only change which signals you take, not what they are worth.
    base = replace(base, **PATTERN_ONLY)

    dfs = {os.path.splitext(os.path.basename(p))[0].upper(): load_ohlcv(p)
           for p in args.csv}
    sessions = sum(df.index.normalize().nunique() for df in dfs.values())
    print(f"\n{len(dfs)} instrument(s)   {sessions} symbol-sessions   "
          f"base {CONFIGS[args.base].name} with filters stripped")
    print(f"entry {args.entry}   signals: raw 3-bar pattern\n")

    levels = [(label, pooled_r(dfs, base, ov, args.entry))
              for label, ov in LADDER]

    print(f"{'component':<38}{'N':>8}{'mean R':>10}{'Δ':>9}{'win%':>7}"
          f"{'95% CI':>20}")
    print("─" * 92)
    prev = None
    for label, d in levels:
        if d["n"] == 0:
            print(f"{label:<38}{'—':>8}")
            continue
        delta = "" if prev is None else f"{d['mean'] - prev:+.3f}"
        ci = f"[{d['ci_lo']:+.3f}, {d['ci_hi']:+.3f}]"
        print(f"{label:<38}{d['n']:>8,}{d['mean']:>+10.3f}{delta:>9}"
              f"{d['win']:>7.1f}{ci:>20}")
        prev = d["mean"]

    # Same pure bracket, opposite side. A signal with real information
    # loses when inverted; one with none is flat both ways.
    inverted = pooled_r(dfs, base, {**LADDER[0][1], "invert": True}, args.entry)
    if inverted["n"]:
        ci = f"[{inverted['ci_lo']:+.3f}, {inverted['ci_hi']:+.3f}]"
        print(f"{'  (same bracket, inverted signal)':<38}{inverted['n']:>8,}"
              f"{inverted['mean']:>+10.3f}{'':>9}{inverted['win']:>7.1f}{ci:>20}")

    signal = levels[0][1]
    breakeven = 1.0 / (1.0 + base.target_atr / base.risk_atr) * 100
    print(f"\nBreakeven win rate for the {base.risk_atr:g}/{base.target_atr:g}"
          f" ATR bracket: {breakeven:.1f}%")

    # What the signal would have to beat to be worth trading at all.
    cost_drag = abs(levels[-1][1]["mean"] - levels[-2][1]["mean"]) \
        if levels[-1][1]["n"] and levels[-2][1]["n"] else 0.0

    print("\nReading it:")
    if signal["n"]:
        spans_zero = signal["ci_lo"] <= 0 <= signal["ci_hi"]
        too_small = abs(signal["mean"]) < cost_drag
        flat_inverted = (inverted["n"] and
                         inverted["ci_lo"] <= 0 <= inverted["ci_hi"])
        if spans_zero or too_small:
            print(f"  • The entry signal is {signal['mean']:+.3f} R"
                  f" (CI {signal['ci_lo']:+.3f} to {signal['ci_hi']:+.3f}),"
                  f" against {cost_drag:.3f} R of costs.")
            print("    It carries no tradeable directional information, and no"
                  " filter on top of\n    it can create any — a filter selects"
                  " signals, it does not improve them.")
            if flat_inverted:
                print(f"    Inverting it gives {inverted['mean']:+.3f} R, also"
                      " flat, which confirms the\n    signal is noise rather"
                      " than a backwards edge. Replace it, don't tune it.")
            elif inverted["n"] and inverted["mean"] > cost_drag:
                print(f"    But inverted it gives {inverted['mean']:+.3f} R,"
                      " which clears costs. Worth pursuing\n    as its own"
                      " pre-registered hypothesis on fresh data.")
        else:
            side = "positive" if signal["mean"] > 0 else "negative"
            print(f"  • The entry signal is {side} at {signal['mean']:+.3f} R,"
                  f" clear of both zero and the\n    {cost_drag:.3f} R cost"
                  " drag.")

    worst = min(
        ((levels[i][0], levels[i][1]["mean"] - levels[i - 1][1]["mean"])
         for i in range(1, len(levels))
         if levels[i][1]["n"] and levels[i - 1][1]["n"]),
        key=lambda kv: kv[1], default=None)
    if worst and worst[1] < -0.01:
        print(f"  • Biggest single loss: {worst[0].lstrip('+ ')}"
              f" at {worst[1]:+.3f} R per trade. Fix that before anything else.")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+",
                    help="OHLCV csv. --mode symbols takes several; the other "
                         "modes use the first.")
    ap.add_argument("--mode", choices=["ablation", "grid", "costs", "symbols",
                                       "attribution"],
                    default="ablation")
    ap.add_argument("--base", default="v1", choices=list(CONFIGS),
                    help="config the sweep starts from (default v1)")
    ap.add_argument("--entry", choices=["next_open", "close"], default="next_open")
    ap.add_argument("--holdout", type=float, default=None, metavar="FRAC",
                    help="rank on the first (1-FRAC) of sessions only and "
                         "report the winner's result on the rest")
    ap.add_argument("--min-trades", type=int, default=30,
                    help="variants below this are listed but never ranked")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--trades-out", metavar="PATH",
                    help="write every variant's trades for validate.py")
    args = ap.parse_args()

    if args.mode == "symbols":
        run_symbols(args)
        return
    if args.mode == "attribution":
        run_attribution(args)
        return

    df = load_ohlcv(args.csv[0])
    base = CONFIGS[args.base]
    sessions_total = df.index.normalize().nunique()
    print(f"\n{len(df):,} bars   {sessions_total} sessions   "
          f"{df.index.min()} → {df.index.max()}")
    print(f"base {base.name}   entry {args.entry}")

    specs = {"ablation": ABLATIONS,
             "costs": COST_MODELS}.get(args.mode) or list(expand_grid(GRID))
    results = [evaluate(df, base, label, ov, args.entry) for label, ov in specs]

    # -------------------------------------------------------------- ablation
    if args.mode == "ablation":
        print(f"\n{'variant':<26}{'N':>6}{'sess':>6}{'mean R':>10}"
              f"{'Δ vs base':>11}{'Sharpe/tr':>11}")
        print("─" * 70)
        base_r = results[0]["mean_r"]
        for d in results:
            delta = ("" if d is results[0] or np.isnan(d["mean_r"])
                     else f"{d['mean_r'] - base_r:+.3f}")
            mr = "—" if np.isnan(d["mean_r"]) else f"{d['mean_r']:+.3f}"
            sh = "—" if np.isnan(d["sharpe"]) else f"{d['sharpe']:+.3f}"
            print(f"{d['label']:<26}{d['n']:>6}{d['sessions']:>6}{mr:>10}"
                  f"{delta:>11}{sh:>11}")
        print("\nA filter earns its place only if switching it off makes mean R"
              " clearly worse.\nΔ near zero means it is costing you trades and"
              " buying nothing.")

    # ----------------------------------------------------------------- costs
    elif args.mode == "costs":
        a = atr(df, base.atr_len)
        risk = base.risk_atr * float(a.median())
        px = float(df["close"].median())
        slip = base.slippage_ticks * base.tick * 2
        comm = px * 2 * base.commission_pct
        print(f"\nmedian ATR({base.atr_len}) ${float(a.median()):.3f}"
              f"   median price ${px:.2f}"
              f"   risk at {base.risk_atr:g} ATR ${risk:.3f}/share")
        print(f"configured costs: slippage ${slip:.3f} = {slip / risk:.3f} R"
              f"   commission ${comm:.3f} = {comm / risk:.3f} R"
              f"   total {(slip + comm) / risk:.3f} R")

        print(f"\n{'cost model':<28}{'N':>6}{'mean R':>10}{'win%':>8}"
              f"{'Sharpe/tr':>11}")
        print("─" * 63)
        for d in results:
            t = d["trades"]
            win = (t["pnl"] > 0).mean() * 100 if len(t) else float("nan")
            mr = "—" if np.isnan(d["mean_r"]) else f"{d['mean_r']:+.3f}"
            sh = "—" if np.isnan(d["sharpe"]) else f"{d['sharpe']:+.3f}"
            print(f"{d['label']:<28}{d['n']:>6}{mr:>10}{win:>8.1f}{sh:>11}")

        gross = results[-1]["mean_r"]
        net = results[0]["mean_r"]
        print(f"\ncost drag: {net:+.3f} net − {gross:+.3f} gross"
              f" = {net - gross:+.3f} R per trade")
        breakeven = 1.0 / (1.0 + base.target_atr / base.risk_atr) * 100
        actual = (results[-1]["trades"]["pnl"] > 0).mean() * 100
        print(f"breakeven win rate at {base.risk_atr:g}/{base.target_atr:g} ATR:"
              f" {breakeven:.1f}%   observed gross: {actual:.1f}%")
        if gross <= 0:
            print("\n→ The gross edge is NOT positive. Costs are not the problem"
                  " and cost tuning\n  cannot fix this. Stop tuning filters;"
                  " the signal itself does not work here.")
        else:
            print(f"\n→ Gross edge is positive ({gross:+.3f} R) but"
                  f" {net - gross:+.3f} R of costs"
                  f" {'leaves' if net > 0 else 'erases'} it."
                  "\n  The lever is a wider stop or a cheaper venue, not"
                  " another filter.")
        print()

    # ------------------------------------------------------------------ grid
    else:
        rankable = [d for d in results
                    if d["n"] >= args.min_trades and not np.isnan(d["sharpe"])]
        print(f"\n{len(results)} variants evaluated, "
              f"{len(rankable)} with ≥{args.min_trades} trades")

        if not rankable:
            print("\nNothing cleared the trade-count floor. No ranking, and no"
                  " winner to deflate.\n")
            return

        if args.holdout is not None:
            if not 0.0 < args.holdout < 1.0:
                raise SystemExit("--holdout must be between 0 and 1")
            all_trades = pd.concat([d["trades"] for d in rankable])
            is_keep, oos_keep = split_sessions(all_trades, args.holdout)
            for d in rankable:
                d["is_r"], d["is_n"] = mean_r_on(d["trades"], is_keep)
                d["oos_r"], d["oos_n"] = mean_r_on(d["trades"], oos_keep)
            rankable = [d for d in rankable if not np.isnan(d["is_r"])]
            rankable.sort(key=lambda d: -d["is_r"])
            print(f"ranked on the first {1 - args.holdout:.0%} of sessions; "
                  f"out-of-sample column was not used for ranking\n")
            print(f"{'#':>3} {'variant':<42}{'IS mean R':>11}{'IS n':>6}"
                  f"{'OOS mean R':>12}{'OOS n':>7}")
            print("─" * 82)
            for i, d in enumerate(rankable[:args.top], 1):
                oos = "—" if np.isnan(d["oos_r"]) else f"{d['oos_r']:+.3f}"
                print(f"{i:>3} {d['label']:<42}{d['is_r']:>+11.3f}"
                      f"{d['is_n']:>6}{oos:>12}{d['oos_n']:>7}")
            best = rankable[0]
        else:
            rankable.sort(key=lambda d: -d["sharpe"])
            print()
            print(f"{'#':>3} {'variant':<42}{'N':>6}{'sess':>6}"
                  f"{'mean R':>10}{'Sharpe/tr':>11}")
            print("─" * 78)
            for i, d in enumerate(rankable[:args.top], 1):
                print(f"{i:>3} {d['label']:<42}{d['n']:>6}{d['sessions']:>6}"
                      f"{d['mean_r']:>+10.3f}{d['sharpe']:>+11.3f}")
            best = rankable[0]

        # ------------------------------------------------- deflate the winner
        r = best["trades"]["r"].dropna().to_numpy()
        m = stats.sharpe_moments(r)
        sr_var = float(np.var([d["sharpe"] for d in rankable], ddof=1))
        n_trials = len(results)
        dsr = stats.deflated_sharpe_ratio(m["sharpe"], sr_var, n_trials,
                                          m["n"], m["skew"], m["kurtosis"])

        print("\n" + "─" * 78)
        print("DEFLATING THE WINNER")
        print()
        print(f"  winner               : {best['label']}")
        print(f"  Sharpe/trade         : {m['sharpe']:+.4f}  on {m['n']} trades")
        print(f"  trials counted       : {n_trials}   (every grid cell, "
              "not just the ranked ones)")
        print(f"  V[SR] across trials  : {sr_var:.6f}")
        print(f"  E[max SR] under null : {dsr['sr_star']:+.4f}")
        print(f"  Deflated Sharpe      : {dsr['dsr']:.3f}")
        print()
        if dsr["dsr"] >= 0.95:
            print("  → survives deflation at the 95% level.")
        elif dsr["dsr"] >= 0.90:
            print("  → marginal. A candidate, not a result.")
        else:
            print("  → does not survive. The winner of this grid is what you"
                  " would expect\n    to find in noise after "
                  f"{n_trials} tries.")
        print()
        print(f"  Any later sweep adds to that {n_trials}. The count resets"
              " only with new data.")
        print()

    if args.trades_out:
        frames = []
        for d in results:
            t = d["trades"]
            if len(t):
                t = t.copy()
                t.insert(0, "variant", d["label"])
                frames.append(t)
        if frames:
            pd.concat(frames, ignore_index=True).to_csv(args.trades_out, index=False)
            print(f"Wrote trades → {args.trades_out}")
            print(f"Next: python3 validate.py {args.trades_out} "
                  f"--trials {len(results)}")


if __name__ == "__main__":
    main()
