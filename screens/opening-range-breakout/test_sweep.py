"""
Tests for sweep.

Hand-built Signal lists, so every statistic has a known right answer. Run:

    python3 test_sweep.py
"""

import sys

import pandas as pd

from orb_screen import Config, Signal
from sweep import baseline_comparison, summarize

RESULTS: list[tuple[bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((cond, f"{name}{' — ' + detail if detail and not cond else ''}"))


def sig(status: str, entry: float = 100.0, risk: float = 1.0,
        last: float = 100.0, mfe: float = 0.0, mae: float = 0.0) -> Signal:
    """Minimal Signal carrying only the fields summarize() reads."""
    return Signal(
        symbol="T", session="2026-10-22", orh=100.0, orl=99.0,
        breakout_time="2026-10-22 10:00 EDT", entry=entry,
        stop=entry - risk, target=entry + 2 * risk, risk=risk,
        risk_pct=risk / entry * 100, reward=2 * risk, rr=2.0,
        vol=0.0, vol_benchmark=1.0, vol_ratio=2.0, vol_window_bars=20,
        vol_window_crossed_session=False, atr=1.0, is_latest_bar=False,
        last_price=last, status=status, bars_to_resolution=1,
        mfe_r=mfe, mae_r=mae,
    )


CFG2R = Config(rr_multiple=2.0)


def test_empty() -> None:
    s = summarize([], CFG2R)
    check("empty input gives n=0", s["n"] == 0)
    check("empty input gives no expectancy", s["expectancy_r"] is None)
    check("empty input gives no win rate", s["win_rate"] is None)


def test_all_winners() -> None:
    s = summarize([sig("target")] * 10, CFG2R)
    check("10 targets -> n=10", s["n"] == 10)
    check("10 targets -> win rate 1.0", s["win_rate"] == 1.0, str(s["win_rate"]))
    check("10 targets at 2R -> expectancy +2.0R", s["expectancy_r"] == 2.0,
          str(s["expectancy_r"]))


def test_all_losers() -> None:
    s = summarize([sig("stopped")] * 10, CFG2R)
    check("10 stops -> win rate 0.0", s["win_rate"] == 0.0, str(s["win_rate"]))
    check("10 stops -> expectancy -1.0R", s["expectancy_r"] == -1.0,
          str(s["expectancy_r"]))


def test_breakeven_mix_at_2r() -> None:
    """At 2R, one win per two losses is exactly flat."""
    s = summarize([sig("target")] * 5 + [sig("stopped")] * 10, CFG2R)
    check("1:2 win:loss at 2R -> expectancy 0", s["expectancy_r"] == 0.0,
          str(s["expectancy_r"]))
    check("win rate is 1/3", abs(s["win_rate"] - 0.333) < 0.001, str(s["win_rate"]))


def test_rr_changes_expectancy() -> None:
    """Same trades, higher reward multiple, higher expectancy."""
    trades = [sig("target")] * 5 + [sig("stopped")] * 10
    s2 = summarize(trades, Config(rr_multiple=2.0))
    s3 = summarize(trades, Config(rr_multiple=3.0))
    check("same trades at 3R beat 2R", s3["expectancy_r"] > s2["expectancy_r"],
          f"{s3['expectancy_r']} vs {s2['expectancy_r']}")
    check("5 wins at 3R, 10 losses -> +0.333R",
          abs(s3["expectancy_r"] - 0.333) < 0.001, str(s3["expectancy_r"]))


def test_unresolved_excluded_from_expectancy_r() -> None:
    """expectancy_r uses resolved trades only."""
    s = summarize([sig("target")] * 2 + [sig("stopped")] * 2 + [sig("open")] * 96,
                  CFG2R)
    check("unresolved counted separately", s["unresolved"] == 96, str(s["unresolved"]))
    check("expectancy_r ignores unresolved", s["expectancy_r"] == 0.5,
          str(s["expectancy_r"]))
    check("n counts every signal", s["n"] == 100, str(s["n"]))


def test_mark_to_market_includes_unresolved() -> None:
    """An unresolved trade sitting at +0.5R should drag a 2R winner down."""
    trades = [sig("target"), sig("open", entry=100.0, risk=1.0, last=100.5)]
    s = summarize(trades, CFG2R)
    check("mtm averages 2.0 and 0.5 -> 1.25",
          s["expectancy_mtm_r"] == 1.25, str(s["expectancy_mtm_r"]))
    check("resolved-only expectancy stays 2.0",
          s["expectancy_r"] == 2.0, str(s["expectancy_r"]))


def test_mark_to_market_handles_adverse_drift() -> None:
    """Unresolved below entry must register as negative, not be dropped."""
    s = summarize([sig("open", entry=100.0, risk=2.0, last=98.5)], CFG2R)
    check("open trade 1.5 below entry on 2.0 risk -> -0.75R",
          s["expectancy_mtm_r"] == -0.75, str(s["expectancy_mtm_r"]))
    check("no resolved trades -> expectancy_r is None",
          s["expectancy_r"] is None, str(s["expectancy_r"]))


def test_excursion_and_risk_stats() -> None:
    s = summarize(
        [sig("target", mfe=2.5, mae=0.3), sig("stopped", mfe=0.4, mae=1.1)], CFG2R
    )
    check("avg MFE averages the excursions", s["avg_mfe_r"] == 1.45,
          str(s["avg_mfe_r"]))
    check("avg MAE averages the drawdowns", s["avg_mae_r"] == 0.7,
          str(s["avg_mae_r"]))
    check("median risk pct reported", s["median_risk_pct"] == 1.0,
          str(s["median_risk_pct"]))


def test_no_follow_through_treated_as_unresolved() -> None:
    s = summarize([sig("no_follow_through")], CFG2R)
    check("no_follow_through is unresolved", s["unresolved"] == 1)
    check("and leaves expectancy_r undefined", s["expectancy_r"] is None)


def row(stop_mode: str, rr: float, vol_mult: str, n: int, exp: float) -> dict:
    return {"stop_mode": stop_mode, "rr": rr, "vol_mult": vol_mult,
            "n": n, "expectancy_mtm_r": exp}


def test_baseline_compared_within_its_own_group() -> None:
    """A 1.5R filtered cell must not be judged against a 3R baseline."""
    table = pd.DataFrame([
        row("bar_low", 1.5, "BASELINE", 90, 0.10),
        row("bar_low", 1.5, "1.5", 50, 0.20),      # beats ITS baseline
        row("bar_low", 3.0, "BASELINE", 90, 0.50),  # higher, different group
        row("bar_low", 3.0, "1.5", 50, 0.30),      # loses to ITS baseline
    ])
    comps = {(c["stop_mode"], c["rr"]): c for c in
             baseline_comparison(table, "expectancy_mtm_r", min_n=30)}

    check("one comparison per group", len(comps) == 2, str(len(comps)))
    check("1.5R group: filter beats its own baseline",
          comps[("bar_low", 1.5)]["verdict"] == "filter helps")
    check("1.5R group delta is +0.10",
          abs(comps[("bar_low", 1.5)]["delta"] - 0.10) < 1e-9,
          str(comps[("bar_low", 1.5)]["delta"]))
    check("3.0R group: filter loses to its own baseline",
          comps[("bar_low", 3.0)]["verdict"] == "filter does not help")
    check("3.0R group delta is -0.20",
          abs(comps[("bar_low", 3.0)]["delta"] + 0.20) < 1e-9,
          str(comps[("bar_low", 3.0)]["delta"]))


def test_underpowered_filter_cell_cannot_win() -> None:
    """The bug this guard fixes: n=13 beating an n=88 baseline."""
    table = pd.DataFrame([
        row("bar_low", 2.0, "BASELINE", 88, 0.246),
        row("bar_low", 2.0, "1.25", 13, 0.292),  # higher but under-powered
    ])
    comps = baseline_comparison(table, "expectancy_mtm_r", min_n=30)
    check("under-powered cell is not credited with a win", len(comps) == 1)
    check("verdict says no cell reached the threshold",
          comps[0]["verdict"].startswith("no filter cell reached"),
          comps[0]["verdict"])
    check("no delta is claimed", comps[0]["delta"] is None)


def test_underpowered_cell_wins_when_threshold_lowered() -> None:
    table = pd.DataFrame([
        row("bar_low", 2.0, "BASELINE", 88, 0.246),
        row("bar_low", 2.0, "1.25", 13, 0.292),
    ])
    comps = baseline_comparison(table, "expectancy_mtm_r", min_n=10)
    check("lowering min_n lets the small cell compete",
          comps[0]["verdict"] == "filter helps", comps[0]["verdict"])
    check("and reports its small n", comps[0]["n"] == 13, str(comps[0]["n"]))


def test_best_eligible_filter_cell_is_chosen() -> None:
    table = pd.DataFrame([
        row("range_high", 2.0, "BASELINE", 90, 0.00),
        row("range_high", 2.0, "1.25", 70, 0.10),
        row("range_high", 2.0, "1.5", 60, 0.35),   # best eligible
        row("range_high", 2.0, "2.0", 5, 0.90),    # better but under-powered
    ])
    comps = baseline_comparison(table, "expectancy_mtm_r", min_n=30)
    check("picks the best adequately-powered cell",
          comps[0]["vol_mult"] == "1.5", str(comps[0]["vol_mult"]))
    check("ignores the under-powered higher score",
          abs(comps[0]["best_filtered"] - 0.35) < 1e-9,
          str(comps[0]["best_filtered"]))


def test_group_without_baseline_is_skipped() -> None:
    table = pd.DataFrame([row("bar_low", 2.0, "1.5", 50, 0.20)])
    comps = baseline_comparison(table, "expectancy_mtm_r", min_n=30)
    check("a group with no baseline yields no comparison", comps == [])


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
        except Exception as exc:
            RESULTS.append((False, f"{t.__name__} raised {type(exc).__name__}: {exc}"))

    failed = [m for ok, m in RESULTS if not ok]
    for ok, m in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {m}")
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed "
          f"across {len(tests)} tests")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
