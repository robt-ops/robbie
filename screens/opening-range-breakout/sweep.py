"""
Parameter sweep for orb_screen.

Runs the screen over every session in a file, for a grid of thresholds, and
reports what each combination would have produced.

Usage:
    python3 sweep.py --csv ~/Documents/lse-market-data/lse_1m_bars.csv

    python3 sweep.py --csv bars.csv --timeframe 5min \
        --vol-multiples 1.0,1.25,1.5,2.0,2.5 \
        --rr-multiples 1.5,2.0,3.0 \
        --stop-modes range_high,bar_low

    python3 sweep.py --csv bars.csv --signals-out signals.csv

Read this before reading the table
----------------------------------
A grid search reports the best cell it finds, and the best cell in any grid is
optimistically biased. Scan 30 combinations of noise and the top one looks
good by construction. So:

  - The BASELINE row (volume filter off) is the row that matters most. If
    1.5x does not beat it, the filter is costing you setups for nothing.
  - Prefer a broad plateau of decent cells over one tall spike. A spike that
    collapses when the threshold moves one notch is a fit to this sample.
  - `n` is printed on every row. At n < 30 the ranking is close to
    meaningless, and this tool will say so rather than let you read it.
  - Nothing here is out-of-sample. These are in-sample results on whatever
    history the file holds.

Expectancy assumes exits exactly at the stop or target: no slippage, no
commission, no partial fills, and one unit of risk per trade. Real fills are
worse, and the gap is widest on the fastest moves.
"""

import argparse
import itertools
import sys
from dataclasses import asdict, replace
from typing import Optional

import pandas as pd

from orb_screen import Config, Signal, load_csv, regular_session, resample, screen_symbol

MIN_USEFUL_N = 30


def sessions_in(df: pd.DataFrame, cfg: Config) -> list[str]:
    rth = regular_session(df, cfg)
    if rth.empty:
        return []
    return [d.isoformat() for d in sorted(set(rth.index.date))]


def collect_signals(
    frames: dict[str, pd.DataFrame],
    cfg: Config,
    fine_frames: Optional[dict[str, pd.DataFrame]] = None,
) -> list[Signal]:
    """Screen every symbol across every session it has."""
    out: list[Signal] = []
    fine_frames = fine_frames or {}
    for symbol, df in frames.items():
        for session in sessions_in(df, cfg):
            try:
                sig, _ = screen_symbol(
                    df, symbol, cfg, session, fine=fine_frames.get(symbol)
                )
            except Exception:
                continue
            if sig is not None:
                out.append(sig)
    return out


def summarize(signals: list[Signal], cfg: Config) -> dict:
    """Outcome stats for one parameter combination.

    Two expectancies are reported because unresolved trades have to go
    somewhere and neither choice is neutral:

      expectancy_r       resolved trades only (target = +rr, stop = -1).
                         Drops unresolved, which flatters the result when
                         trades that never reached either level were drifting
                         against the position.
      expectancy_mtm_r   unresolved marked to the session's last close.
                         Includes everything, at the cost of treating an
                         arbitrary cutoff as an exit.

    Read them together. A wide gap means the sample leans on unresolved
    trades and neither number is trustworthy.
    """
    n = len(signals)
    if n == 0:
        return {
            "n": 0, "wins": 0, "losses": 0, "unresolved": 0,
            "win_rate": None, "expectancy_r": None, "expectancy_mtm_r": None,
            "pct_ambig": None,
            "avg_mfe_r": None, "avg_mae_r": None, "median_risk_pct": None,
        }

    wins = [s for s in signals if s.status == "target"]
    losses = [s for s in signals if s.status == "stopped"]
    unresolved = [s for s in signals if s.status in ("open", "no_follow_through")]
    resolved = len(wins) + len(losses)

    exp_r = (
        (len(wins) * cfg.rr_multiple - len(losses)) / resolved
        if resolved
        else None
    )

    # Mark-to-market: resolved at their levels, unresolved at the last close.
    mtm = [cfg.rr_multiple] * len(wins) + [-1.0] * len(losses)
    for s in unresolved:
        if s.risk:
            mtm.append((s.last_price - s.entry) / s.risk)

    mfes = [s.mfe_r for s in signals if s.mfe_r is not None]
    maes = [s.mae_r for s in signals if s.mae_r is not None]

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "unresolved": len(unresolved),
        "win_rate": round(len(wins) / resolved, 3) if resolved else None,
        "pct_ambig": (
            round(sum(s.resolved_ambiguously for s in signals) / resolved, 3)
            if resolved else None
        ),
        "expectancy_r": round(exp_r, 3) if exp_r is not None else None,
        "expectancy_mtm_r": round(sum(mtm) / len(mtm), 3) if mtm else None,
        "avg_mfe_r": round(sum(mfes) / len(mfes), 2) if mfes else None,
        "avg_mae_r": round(sum(maes) / len(maes), 2) if maes else None,
        "median_risk_pct": round(
            float(pd.Series([s.risk_pct for s in signals]).median()), 3
        ),
    }


def sweep(
    frames: dict[str, pd.DataFrame],
    vol_multiples: list[float],
    rr_multiples: list[float],
    stop_modes: list[str],
    base: Config,
    sides: tuple[str, ...] = ("long",),
    fine_frames: Optional[dict[str, pd.DataFrame]] = None,
) -> tuple[pd.DataFrame, dict[tuple, list[Signal]]]:
    """Grid over the thresholds, plus a volume-filter-off baseline per cell."""
    rows: list[dict] = []
    collected: dict[tuple, list[Signal]] = {}

    # vol_multiple 0 passes every breakout: the no-filter control.
    vol_grid = sorted(set([0.0] + list(vol_multiples)))

    for side, stop_mode, rr, vm in itertools.product(
        sides, stop_modes, rr_multiples, vol_grid
    ):
        cfg = replace(
            base, side=side, stop_mode=stop_mode, rr_multiple=rr, vol_multiple=vm
        )
        signals = collect_signals(frames, cfg, fine_frames)
        collected[(side, stop_mode, rr, vm)] = signals
        rows.append(
            {
                "side": side,
                "stop_mode": cfg.stop_mode,
                "rr": rr,
                "vol_mult": "BASELINE" if vm == 0.0 else f"{vm:g}",
                **summarize(signals, cfg),
            }
        )

    return pd.DataFrame(rows), collected


def baseline_comparison(
    table: pd.DataFrame, sort_col: str, min_n: int
) -> list[dict]:
    """Does the volume filter beat no filter, compared like for like?

    One comparison per (stop_mode, rr) group. Comparing the best filtered cell
    against the best baseline cell across different reward multiples is
    meaningless — a 1.5R filtered result and a 3R baseline are not the same
    experiment — so each group is judged against its own baseline, and only
    cells meeting `min_n` are eligible to win.
    """
    out: list[dict] = []
    keys = [c for c in ("side", "stop_mode", "rr") if c in table.columns]
    for key, grp in table.groupby(keys, sort=False):
        label = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        side = label.get("side", "long")
        stop_mode, rr = label["stop_mode"], label["rr"]
        base_rows = grp[grp["vol_mult"] == "BASELINE"]
        filt = grp[(grp["vol_mult"] != "BASELINE") & (grp["n"] >= min_n)]
        if base_rows.empty or base_rows.iloc[0][sort_col] is None:
            continue
        base_val = base_rows.iloc[0][sort_col]
        base_n = int(base_rows.iloc[0]["n"])
        if pd.isna(base_val):
            continue

        eligible = filt.dropna(subset=[sort_col])
        if eligible.empty:
            out.append({
                "side": side, "stop_mode": stop_mode, "rr": rr,
                "baseline": base_val, "baseline_n": base_n,
                "best_filtered": None, "vol_mult": None, "n": None,
                "delta": None, "verdict": f"no filter cell reached n>={min_n}",
            })
            continue

        best = eligible.loc[eligible[sort_col].idxmax()]
        delta = best[sort_col] - base_val
        out.append({
            "side": side, "stop_mode": stop_mode, "rr": rr,
            "baseline": base_val, "baseline_n": base_n,
            "best_filtered": best[sort_col], "vol_mult": best["vol_mult"],
            "n": int(best["n"]), "delta": delta,
            "verdict": "filter helps" if delta > 0 else "filter does not help",
        })
    return out


def _floats(raw: str) -> list[float]:
    return [float(x) for x in raw.split(",") if x.strip()]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Parameter sweep for orb_screen.")
    p.add_argument("--csv", required=True)
    p.add_argument("--ticker", default=None, help="symbol name for a single-symbol CSV")
    p.add_argument("--timeframe", default=None, help="resample, e.g. 5min")
    p.add_argument("--input-tz", default="America/New_York")
    p.add_argument("--vol-multiples", default="1.25,1.5,2.0,2.5")
    p.add_argument("--rr-multiples", default="1.5,2.0,3.0")
    p.add_argument("--sides", default="long", help="long, short, or long,short")
    p.add_argument("--no-fine-resolution", action="store_true",
                   help="replay outcomes on signal bars, not input bars")
    p.add_argument("--stop-modes", default="range_edge,bar_extreme")
    p.add_argument("--opening-minutes", type=int, default=30)
    p.add_argument("--vol-lookback", type=int, default=20)
    p.add_argument("--confirm-on", choices=("close", "high"), default="close")
    p.add_argument("--sort", default="expectancy_mtm_r", help="column to rank by")
    p.add_argument("--min-n", type=int, default=MIN_USEFUL_N,
                   help=f"cells below this n are shown but not ranked "
                        f"(default {MIN_USEFUL_N})")
    p.add_argument("--signals-out", default=None,
                   help="write every signal from the best cell to this path")
    args = p.parse_args(argv)

    base = Config(
        opening_minutes=args.opening_minutes,
        vol_lookback=args.vol_lookback,
        confirm_on=args.confirm_on,
    )

    frames = load_csv(args.csv, args.input_tz)
    if "" in frames:
        frames = {args.ticker or "SYMBOL": frames.pop("")}

    fine_frames: dict[str, pd.DataFrame] = {}
    if args.timeframe:
        if not args.no_fine_resolution:
            fine_frames = dict(frames)
        frames = {s: resample(df, args.timeframe) for s, df in frames.items()}

    all_sessions = sorted({d for df in frames.values() for d in sessions_in(df, base)})
    print(
        f"{len(frames)} symbol(s) x {len(all_sessions)} session(s) "
        f"({all_sessions[0]} .. {all_sessions[-1]})" if all_sessions else "no sessions"
    )
    print(f"timeframe: {args.timeframe or 'as supplied'}\n")

    table, collected = sweep(
        frames,
        _floats(args.vol_multiples),
        _floats(args.rr_multiples),
        args.stop_modes.split(","),
        base,
        tuple(x.strip() for x in args.sides.split(",") if x.strip()),
        fine_frames,
    )

    # Only adequately-powered cells are eligible to be ranked. A cell with
    # n=13 topping an n=88 baseline is the exact noise this guard exists for.
    rankable = table[(table["n"] >= args.min_n)].dropna(subset=[args.sort])
    underpowered = table.drop(rankable.index)

    if not rankable.empty:
        ranked = rankable.sort_values(args.sort, ascending=False)
        print(f"RANKED (n >= {args.min_n})")
        print(ranked.to_string(index=False))
    else:
        ranked = rankable
        print(
            f"!! NO cell reached n >= {args.min_n}. Nothing here is rankable; "
            f"the grid below is printed for inspection only.\n"
        )

    if not underpowered.empty:
        print(f"\nNOT RANKED (n < {args.min_n} — too few trades to read)")
        print(underpowered.sort_values("n", ascending=False).to_string(index=False))

    print(f"\nbaseline check (like for like, per stop_mode x rr, n >= {args.min_n}):")
    comparisons = baseline_comparison(table, args.sort, args.min_n)
    if not comparisons:
        print("  no baseline available to compare against")
    else:
        helped = 0
        for c in comparisons:
            if c["delta"] is None:
                print(f"  {c['side']:<5} {c['stop_mode']:<12} rr={c['rr']:<4} "
                      f"baseline {c['baseline']:+.3f}R (n={c['baseline_n']}) "
                      f"— {c['verdict']}")
                continue
            helped += c["delta"] > 0
            print(f"  {c['side']:<5} {c['stop_mode']:<12} rr={c['rr']:<4} "
                  f"baseline {c['baseline']:+.3f}R (n={c['baseline_n']})  "
                  f"best filter {c['vol_mult']}x {c['best_filtered']:+.3f}R "
                  f"(n={c['n']})  {c['delta']:+.3f}R — {c['verdict']}")
        decided = [c for c in comparisons if c["delta"] is not None]
        if decided:
            print(f"\n  filter beat no-filter in {helped}/{len(decided)} comparisons")
            if helped == 0:
                print("  -> on this sample the volume condition only costs setups")

    if args.signals_out and not ranked.empty:
        top = ranked.iloc[0]
        key = (
            top["side"],
            top["stop_mode"],
            float(top["rr"]),
            0.0 if top["vol_mult"] == "BASELINE" else float(top["vol_mult"]),
        )
        sigs = collected.get(key, [])
        if sigs:
            pd.DataFrame([asdict(s) for s in sigs]).to_csv(args.signals_out, index=False)
            print(f"\nwrote {len(sigs)} signal(s) from the top cell to {args.signals_out}")

    print(
        "\nReminder: in-sample, grid-selected, and the top cell is "
        "optimistically biased. Prefer a plateau over a spike."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
