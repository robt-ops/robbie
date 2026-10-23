"""
Tests for orb_screen.

Synthetic fixtures only — no network, no market data. Run:

    python3 test_orb_screen.py

Verifies the screen's arithmetic and its edge cases. Most tests zero out the
stop buffer so stop/risk/target are exact integers and a wrong value cannot
hide inside a rounding tolerance; the buffer itself is tested separately.
"""

import sys
from datetime import datetime, timedelta

import pandas as pd

from orb_screen import ET, Config, screen_symbol

# Zero buffer -> stop sits exactly on the broken level, so the arithmetic is
# checkable to the cent.
EXACT = Config(buffer_atr_mult=0.0, min_buffer_pct=0.0)


def session_bars(
    specs: list[tuple[float, float, float, float, float]],
    date: str = "2026-10-22",
    start: str = "09:30",
    minutes: int = 5,
) -> pd.DataFrame:
    """Build evenly spaced ET bars from (open, high, low, close, volume) rows."""
    h, m = (int(x) for x in start.split(":"))
    t0 = datetime.fromisoformat(date).replace(hour=h, minute=m, tzinfo=ET)
    idx = [t0 + timedelta(minutes=minutes * i) for i in range(len(specs))]
    return pd.DataFrame(
        specs, columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex(idx)
    )


def flat_opening(high: float = 100.0, vol: float = 1000.0) -> list[tuple]:
    """Six 5-minute bars (09:30-09:55) whose highest high is `high`."""
    return [(99.0, high - 0.5, 98.5, 99.0, vol)] * 5 + [(99.0, high, 98.5, 99.0, vol)]


RESULTS: list[tuple[bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((cond, f"{name}{' — ' + detail if detail and not cond else ''}"))


def test_clean_breakout_arithmetic() -> None:
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    sig, reason = screen_symbol(df, "TEST", EXACT)

    check("clean breakout produces a signal", sig is not None, str(reason))
    if sig is None:
        return
    check("ORH is the opening-range high", sig.orh == 100.0, f"got {sig.orh}")
    check("entry is the breakout close", sig.entry == 101.0, f"got {sig.entry}")
    check("stop sits on the broken level", sig.stop == 100.0, f"got {sig.stop}")
    check("risk = entry - stop", sig.risk == 1.0, f"got {sig.risk}")
    check("target = entry + 2R", sig.target == 103.0, f"got {sig.target}")
    check("reward is exactly 2x risk", sig.reward == 2 * sig.risk, f"got {sig.reward}")
    check("volume ratio = 2000/1000", sig.vol_ratio == 2.0, f"got {sig.vol_ratio}")
    check("breakout is the latest bar", sig.is_latest_bar is True)
    check(
        "no forward bars -> no_follow_through",
        sig.status == "no_follow_through",
        f"got {sig.status}",
    )


def test_rr_multiple_honoured() -> None:
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    cfg = Config(buffer_atr_mult=0.0, min_buffer_pct=0.0, rr_multiple=3.5)
    sig, _ = screen_symbol(df, "TEST", cfg)
    check(
        "rr_multiple 3.5 -> target = entry + 3.5R",
        sig is not None and sig.target == 101.0 + 3.5,
        f"got {sig.target if sig else None}",
    )


def test_volume_filter_rejects() -> None:
    # 1200 vs a 1000 benchmark = 1.2x, below the 1.5x default.
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 1200.0)])
    sig, reason = screen_symbol(df, "TEST", EXACT)
    check("thin-volume breakout is rejected", sig is None)
    check(
        "rejection names the volume shortfall",
        reason is not None and "volume 1.20x" in reason,
        str(reason),
    )


def test_volume_benchmark_excludes_breakout_bar() -> None:
    """The decisive test for the self-inflation bug.

    Six prior bars at 1000 and a breakout bar at 1500 is exactly 1.5x when the
    benchmark excludes the bar. Include it and the mean becomes 1071.4, the
    ratio 1.40, and this setup would be rejected. Passing proves exclusion.
    """
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 1500.0)])
    sig, reason = screen_symbol(df, "TEST", EXACT)
    check(
        "benchmark excludes the breakout bar (1500/1000 = 1.5x passes)",
        sig is not None,
        str(reason),
    )
    if sig is not None:
        check("benchmark is the prior-bar mean", sig.vol_benchmark == 1000.0,
              f"got {sig.vol_benchmark}")
        check("benchmark window is the 6 prior bars", sig.vol_window_bars == 6,
              f"got {sig.vol_window_bars}")


def test_no_breakout() -> None:
    df = session_bars(flat_opening() + [(99.0, 99.8, 98.0, 99.2, 5000.0)])
    sig, reason = screen_symbol(df, "TEST", EXACT)
    check("no close above ORH -> no signal", sig is None)
    check("rejection names the ORH", reason is not None and "ORH 100.00" in reason,
          str(reason))


def test_wick_through_level_does_not_trigger() -> None:
    """High pokes above ORH, close falls back below."""
    df = session_bars(flat_opening() + [(99.5, 100.8, 99.0, 99.4, 3000.0)])

    sig, _ = screen_symbol(df, "TEST", EXACT)
    check("close-confirmed mode ignores the wick", sig is None)

    intrabar = Config(buffer_atr_mult=0.0, min_buffer_pct=0.0, confirm_on="high")
    sig2, reason2 = screen_symbol(df, "TEST", intrabar)
    check(
        "intrabar mode triggers but the risk guard rejects a close below stop",
        sig2 is None and reason2 is not None and "non-positive risk" in reason2,
        str(reason2),
    )


def test_outcome_target_hit() -> None:
    df = session_bars(
        flat_opening()
        + [(100.2, 101.5, 99.8, 101.0, 2000.0), (101.0, 103.5, 100.9, 103.2, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", EXACT)
    check("target reached -> status 'target'", sig is not None and sig.status == "target",
          f"got {sig.status if sig else None}")
    check("resolution on the first forward bar",
          sig is not None and sig.bars_to_resolution == 1,
          f"got {sig.bars_to_resolution if sig else None}")


def test_outcome_stopped() -> None:
    df = session_bars(
        flat_opening()
        + [(100.2, 101.5, 99.8, 101.0, 2000.0), (100.9, 101.0, 99.5, 99.8, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", EXACT)
    check("stop breached -> status 'stopped'", sig is not None and sig.status == "stopped",
          f"got {sig.status if sig else None}")


def test_outcome_ambiguous_bar_counts_as_stop() -> None:
    """A bar touching both levels resolves to the stop (worst case)."""
    df = session_bars(
        flat_opening()
        + [(100.2, 101.5, 99.8, 101.0, 2000.0), (101.0, 104.0, 99.0, 102.0, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", EXACT)
    check(
        "bar hitting stop and target counts as stopped",
        sig is not None and sig.status == "stopped",
        f"got {sig.status if sig else None}",
    )


def test_outcome_still_open() -> None:
    df = session_bars(
        flat_opening()
        + [(100.2, 101.5, 99.8, 101.0, 2000.0), (101.0, 102.0, 100.5, 101.8, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", EXACT)
    check("neither level touched -> 'open'", sig is not None and sig.status == "open",
          f"got {sig.status if sig else None}")
    check("MFE reported in R", sig is not None and sig.mfe_r == 1.0,
          f"got {sig.mfe_r if sig else None}")


def test_opening_range_incomplete() -> None:
    """Scanning before the range closes must say so, not invent a signal."""
    df = session_bars(flat_opening()[:4])
    sig, reason = screen_symbol(df, "TEST", EXACT)
    check("partial opening range -> no signal", sig is None)
    check(
        "rejection explains the range is incomplete",
        reason is not None and "not complete" in reason,
        str(reason),
    )


def test_extended_hours_excluded_from_range() -> None:
    """A 09:00 print at 200 must not become the ORH."""
    pre = session_bars([(199.0, 200.0, 198.0, 199.0, 50.0)], start="09:00")
    rth = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    df = pd.concat([pre, rth])
    sig, reason = screen_symbol(df, "TEST", EXACT)
    check("pre-market bar is excluded", sig is not None, str(reason))
    check("ORH ignores the 09:00 print", sig is not None and sig.orh == 100.0,
          f"got {sig.orh if sig else None}")


def test_later_sessions_not_visible() -> None:
    """Screening an earlier session must not see the next day's bars."""
    day1 = session_bars(
        flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)], date="2026-10-21"
    )
    day2 = session_bars(
        flat_opening(high=120.0) + [(120.2, 130.0, 119.0, 129.0, 9000.0)],
        date="2026-10-22",
    )
    df = pd.concat([day1, day2])

    sig, _ = screen_symbol(df, "TEST", EXACT, session="2026-10-21")
    check("requested session is the one screened",
          sig is not None and sig.session == "2026-10-21",
          f"got {sig.session if sig else None}")
    check("next session's rally does not resolve the trade",
          sig is not None and sig.status == "no_follow_through",
          f"got {sig.status if sig else None}")

    latest, _ = screen_symbol(df, "TEST", EXACT)
    check("default screens the latest session",
          latest is not None and latest.session == "2026-10-22",
          f"got {latest.session if latest else None}")


def test_prior_session_feeds_volume_benchmark() -> None:
    """Early breakouts borrow the prior session for the 20-bar window."""
    day1 = session_bars([(99.0, 99.5, 98.5, 99.0, 1000.0)] * 20, date="2026-10-21")
    day2 = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)],
                        date="2026-10-22")
    df = pd.concat([day1, day2])
    sig, reason = screen_symbol(df, "TEST", EXACT)
    check("signal found with cross-session window", sig is not None, str(reason))
    if sig is not None:
        check("window fills to the full lookback", sig.vol_window_bars == 20,
              f"got {sig.vol_window_bars}")
        check("cross-session borrowing is flagged",
              sig.vol_window_crossed_session is True)


def test_stop_mode_bar_low() -> None:
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    cfg = Config(buffer_atr_mult=0.0, min_buffer_pct=0.0, stop_mode="bar_low")
    sig, _ = screen_symbol(df, "TEST", cfg)
    check("bar_low mode stops at the breakout bar's low",
          sig is not None and sig.stop == 99.8, f"got {sig.stop if sig else None}")
    check("wider stop widens risk to 1.2",
          sig is not None and abs(sig.risk - 1.2) < 1e-9,
          f"got {sig.risk if sig else None}")
    check("target still 2R from the wider stop",
          sig is not None and abs(sig.target - (101.0 + 2.4)) < 1e-9,
          f"got {sig.target if sig else None}")


def test_percentage_buffer_applied() -> None:
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    cfg = Config(buffer_atr_mult=0.0, min_buffer_pct=0.01)  # 1% of entry
    sig, _ = screen_symbol(df, "TEST", cfg)
    check("1% buffer drops the stop below the level",
          sig is not None and abs(sig.stop - (100.0 - 1.01)) < 1e-9,
          f"got {sig.stop if sig else None}")


def test_naive_timestamps_localised() -> None:
    from orb_screen import to_et

    naive = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    naive.index = naive.index.tz_localize(None)
    sig, reason = screen_symbol(to_et(naive), "TEST", EXACT)
    check("tz-naive input is treated as ET", sig is not None, str(reason))


# ---------------------------------------------------------------- short side

SHORT = Config(buffer_atr_mult=0.0, min_buffer_pct=0.0, side="short")


def flat_opening_short(low: float = 100.0, vol: float = 1000.0) -> list[tuple]:
    """Six bars whose lowest low is `low` — the mirror of flat_opening()."""
    return [(101.0, 101.5, low + 0.5, 101.0, vol)] * 5 + [
        (101.0, 101.5, low, 101.0, vol)
    ]


def test_short_breakdown_arithmetic() -> None:
    """Exact mirror of test_clean_breakout_arithmetic."""
    df = session_bars(flat_opening_short() + [(99.8, 100.2, 98.5, 99.0, 2000.0)])
    sig, reason = screen_symbol(df, "TEST", SHORT)

    check("short breakdown produces a signal", sig is not None, str(reason))
    if sig is None:
        return
    check("side is recorded as short", sig.side == "short", sig.side)
    check("ORL is the opening-range low", sig.orl == 100.0, f"got {sig.orl}")
    check("entry is the breakdown close", sig.entry == 99.0, f"got {sig.entry}")
    check("stop sits ABOVE the broken level", sig.stop == 100.0, f"got {sig.stop}")
    check("risk = stop - entry (positive)", sig.risk == 1.0, f"got {sig.risk}")
    check("target is BELOW entry by 2R", sig.target == 97.0, f"got {sig.target}")
    check("reward reported positive", sig.reward == 2.0, f"got {sig.reward}")
    check("risk_pct is positive", sig.risk_pct > 0, f"got {sig.risk_pct}")


def test_short_ignores_upside_breakout() -> None:
    """A session that breaks UP must yield no short signal."""
    df = session_bars(flat_opening() + [(100.2, 101.5, 99.8, 101.0, 2000.0)])
    sig, reason = screen_symbol(df, "TEST", SHORT)
    check("upside breakout gives no short", sig is None)
    check("rejection names the ORL, not the ORH",
          reason is not None and "ORL" in reason, str(reason))


def test_long_ignores_downside_breakdown() -> None:
    df = session_bars(flat_opening_short() + [(99.8, 100.2, 98.5, 99.0, 2000.0)])
    sig, _ = screen_symbol(df, "TEST", EXACT)
    check("downside breakdown gives no long", sig is None)


def test_short_outcome_target_hit() -> None:
    """Price falling to the target is a WIN for a short."""
    df = session_bars(
        flat_opening_short()
        + [(99.8, 100.2, 98.5, 99.0, 2000.0), (99.0, 99.1, 96.8, 96.9, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", SHORT)
    check("falling to target is a short win",
          sig is not None and sig.status == "target",
          f"got {sig.status if sig else None}")


def test_short_outcome_stopped() -> None:
    """Price rising through the stop is a LOSS for a short."""
    df = session_bars(
        flat_opening_short()
        + [(99.8, 100.2, 98.5, 99.0, 2000.0), (99.1, 100.6, 99.0, 100.4, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", SHORT)
    check("rising through stop is a short loss",
          sig is not None and sig.status == "stopped",
          f"got {sig.status if sig else None}")


def test_short_excursions_are_direction_correct() -> None:
    """A favourable move DOWN must register as MFE, not MAE.

    This is the test that catches an inverted sign, which would otherwise
    report short losses as wins.
    """
    df = session_bars(
        flat_opening_short()
        + [(99.8, 100.2, 98.5, 99.0, 2000.0), (99.0, 99.2, 98.0, 98.2, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", SHORT)
    check("1.0 down on 1.0 risk -> MFE 1.0R",
          sig is not None and sig.mfe_r == 1.0, f"got {sig.mfe_r if sig else None}")
    check("0.2 up on 1.0 risk -> MAE 0.2R",
          sig is not None and abs(sig.mae_r - 0.2) < 1e-9,
          f"got {sig.mae_r if sig else None}")


def test_short_ambiguous_bar_counts_as_stop() -> None:
    df = session_bars(
        flat_opening_short()
        + [(99.8, 100.2, 98.5, 99.0, 2000.0), (99.0, 101.0, 96.0, 97.0, 900.0)]
    )
    sig, _ = screen_symbol(df, "TEST", SHORT)
    check("short bar hitting both levels counts as stopped",
          sig is not None and sig.status == "stopped",
          f"got {sig.status if sig else None}")


def test_short_bar_extreme_stop_uses_bar_high() -> None:
    df = session_bars(flat_opening_short() + [(99.8, 100.2, 98.5, 99.0, 2000.0)])
    cfg = Config(buffer_atr_mult=0.0, min_buffer_pct=0.0, side="short",
                 stop_mode="bar_extreme")
    sig, _ = screen_symbol(df, "TEST", cfg)
    check("bar_extreme stops at the breakdown bar's HIGH",
          sig is not None and sig.stop == 100.2, f"got {sig.stop if sig else None}")
    check("wider stop -> risk 1.2",
          sig is not None and abs(sig.risk - 1.2) < 1e-9,
          f"got {sig.risk if sig else None}")
    check("target 2R below entry",
          sig is not None and abs(sig.target - (99.0 - 2.4)) < 1e-9,
          f"got {sig.target if sig else None}")


def test_short_buffer_raises_stop() -> None:
    df = session_bars(flat_opening_short() + [(99.8, 100.2, 98.5, 99.0, 2000.0)])
    cfg = Config(buffer_atr_mult=0.0, min_buffer_pct=0.01, side="short")
    sig, _ = screen_symbol(df, "TEST", cfg)
    check("1% buffer lifts the short stop above the level",
          sig is not None and abs(sig.stop - (100.0 + 0.99)) < 1e-9,
          f"got {sig.stop if sig else None}")


def test_short_volume_filter_applies() -> None:
    df = session_bars(flat_opening_short() + [(99.8, 100.2, 98.5, 99.0, 1200.0)])
    sig, reason = screen_symbol(df, "TEST", SHORT)
    check("thin-volume breakdown is rejected", sig is None)
    check("rejection names the shortfall",
          reason is not None and "volume 1.20x" in reason, str(reason))


def test_stop_mode_aliases_resolve() -> None:
    check("range_high aliases to range_edge",
          Config(stop_mode="range_high").stop_mode == "range_edge")
    check("bar_low aliases to bar_extreme",
          Config(stop_mode="bar_low").stop_mode == "bar_extreme")
    check("confirm_on high aliases to extreme",
          Config(confirm_on="high").confirm_on == "extreme")


def test_invalid_side_rejected() -> None:
    try:
        Config(side="sideways")
        check("invalid side raises", False, "no exception")
    except ValueError:
        check("invalid side raises", True)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
        except Exception as exc:
            RESULTS.append((False, f"{t.__name__} raised {type(exc).__name__}: {exc}"))

    failed = [msg for ok, msg in RESULTS if not ok]
    for ok, msg in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed "
          f"across {len(tests)} tests")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
