"""
Opening-range breakout screen.

Scans US equity intraday bars for long setups where price closes above the
30-minute opening-range high on expanding volume, then sizes a stop just
below the broken level and a target at a fixed risk multiple.

Usage:
    # multi-symbol CSV (needs a symbol column)
    python3 orb_screen.py --csv ~/Documents/lse-market-data/lse_1m_bars.csv

    # single-symbol CSV
    python3 orb_screen.py --csv nvda_1m.csv --ticker NVDA

    # resample 1-minute input to 5-minute bars, loosen volume, show near-misses
    python3 orb_screen.py --csv bars.csv --timeframe 5min --vol-multiple 1.3 \
        --show-rejects

CSV format (header required):
    timestamp,open,high,low,close,volume
    plus an optional symbol/ticker column for multi-symbol files.

Screen logic:
    1. Opening range = the first `--opening-minutes` of the regular session
       (09:30 ET). ORH is the highest high in that window, ORL the lowest low.
    2. Breakout = the first bar after the opening range whose CLOSE exceeds
       the ORH. Close-confirmed by default so a wick through the level does
       not trigger; `--confirm-on high` switches to intrabar.
    3. Volume filter = breakout bar volume >= `--vol-multiple` x the mean of
       the `--vol-lookback` bars STRICTLY BEFORE it.
    4. Stop = the broken level minus a buffer. Risk = entry - stop, and the
       target is entry + `--rr-multiple` x risk.

Notes / known limitations:
    - Signals are evaluated per session and only from the end of the opening
      range onward. Running this before 10:00 ET on the current session
      returns nothing, by design rather than by failure.
    - The volume benchmark EXCLUDES the breakout bar. Including it lets the
      bar inflate its own benchmark: at a 20-bar lookback a bar contributes
      1/20 of the mean it is being judged against, which biases the measured
      ratio down and makes the filter quietly weaker than its setting says.
    - That 20-bar window is a plain rolling window and will reach into the
      prior session for breakouts early in the day. This is deliberate: the
      alternative, same-session-only, has just six 5-minute bars available at
      10:00 and they are the structurally heaviest bars of the day, which
      makes almost any later bar look low-volume by comparison. Each signal
      reports `vol_window_bars` and `vol_window_crossed_session` so the
      benchmark is auditable.
    - Outcome fields (`status`, `mfe_r`, `mae_r`) are a bar-level replay, not
      a backtest. When a single bar touches both stop and target the stop is
      assumed first, matching the worst-case intrabar convention used in
      strategies/thor-3bar-reversal/backtest.py. No commissions, no slippage,
      no partial fills.
    - Long-side only. A short mirror would key off the opening-range LOW and
      is not implemented here.
    - This screen identifies structure. It does not rank by quality and makes
      no claim that a listed setup is worth taking.
"""

import argparse
import sys
from dataclasses import asdict, dataclass
from datetime import time
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")


@dataclass
class Config:
    opening_minutes: int = 30
    vol_lookback: int = 20
    vol_multiple: float = 1.5
    rr_multiple: float = 2.0
    stop_mode: str = "range_high"  # "range_high" | "bar_low"
    buffer_atr_mult: float = 0.10
    min_buffer_pct: float = 0.0005  # 5 bps of price
    atr_length: int = 14
    confirm_on: str = "close"  # "close" | "high"
    session_start: time = time(9, 30)
    session_end: time = time(16, 0)


@dataclass
class Signal:
    symbol: str
    session: str
    orh: float
    orl: float
    breakout_time: str
    entry: float
    stop: float
    target: float
    risk: float
    risk_pct: float
    reward: float
    rr: float
    vol: float
    vol_benchmark: float
    vol_ratio: float
    vol_window_bars: int
    vol_window_crossed_session: bool
    atr: float
    is_latest_bar: bool
    last_price: float
    status: str  # "target" | "stopped" | "open" | "no_follow_through"
    bars_to_resolution: Optional[int]
    mfe_r: Optional[float]
    mae_r: Optional[float]


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def to_et(df: pd.DataFrame, input_tz: str = "America/New_York") -> pd.DataFrame:
    """Index -> tz-aware America/New_York, sorted, deduplicated."""
    out = df.copy()
    idx = pd.DatetimeIndex(pd.to_datetime(out.index))
    if idx.tz is None:
        idx = idx.tz_localize(ZoneInfo(input_tz))
    out.index = idx.tz_convert(ET)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def regular_session(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Keep only regular-hours bars. Extended-hours prints distort the range."""
    t = df.index.time
    return df[(t >= cfg.session_start) & (t < cfg.session_end)]


def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = df.resample(timeframe, label="left", closed="left").agg(agg)
    return out.dropna(subset=["open", "high", "low", "close"])


def _evaluate_outcome(
    forward: pd.DataFrame, entry: float, stop: float, target: float, risk: float
) -> tuple[str, Optional[int], Optional[float], Optional[float]]:
    """Bar-level replay of what happened after entry.

    Worst-case convention: a bar touching both levels counts as the stop,
    because bar data cannot say which came first.
    """
    if forward.empty:
        return "no_follow_through", None, None, None

    mfe_r = float(forward["high"].max() - entry) / risk
    mae_r = float(entry - forward["low"].min()) / risk

    for i, (_, bar) in enumerate(forward.iterrows(), start=1):
        if bar["low"] <= stop:
            return "stopped", i, mfe_r, mae_r
        if bar["high"] >= target:
            return "target", i, mfe_r, mae_r
    return "open", None, mfe_r, mae_r


def _build_signal(
    frame: pd.DataFrame, today: pd.DataFrame, symbol: str, cfg: Config
) -> tuple[Optional[Signal], Optional[str]]:
    """Core screen for one session.

    `today` holds the session being screened; `frame` holds the same bars plus
    preceding history, so the volume benchmark and ATR can look back past the
    session boundary. Returns (signal, reject_reason) with exactly one set.
    """
    if today.empty:
        return None, "no bars"

    open_ts = today.index[0].normalize() + pd.Timedelta(
        hours=cfg.session_start.hour, minutes=cfg.session_start.minute
    )
    or_end = open_ts + pd.Timedelta(minutes=cfg.opening_minutes)

    opening = today[today.index < or_end]
    after = today[today.index >= or_end]

    if opening.empty:
        return None, "no opening-range bars"
    if after.empty:
        return None, f"opening range not complete (no bars at/after {or_end.time()})"

    orh = float(opening["high"].max())
    orl = float(opening["low"].min())

    trigger = after["close"] if cfg.confirm_on == "close" else after["high"]
    broke = after[trigger > orh]
    if broke.empty:
        return None, f"no {cfg.confirm_on} above ORH {orh:.2f}"

    bo_ts = broke.index[0]
    bo = frame.loc[bo_ts]
    pos = frame.index.get_loc(bo_ts)

    # Volume benchmark: the N bars strictly before the breakout bar.
    prior = frame.iloc[max(0, pos - cfg.vol_lookback) : pos]
    if prior.empty:
        return None, "no prior bars for volume benchmark"
    benchmark = float(prior["volume"].mean())
    if benchmark <= 0:
        return None, "volume benchmark is zero"

    vol_ratio = float(bo["volume"]) / benchmark
    if vol_ratio < cfg.vol_multiple:
        return None, (
            f"volume {vol_ratio:.2f}x < {cfg.vol_multiple:.2f}x "
            f"(bar {bo['volume']:.0f} vs {benchmark:.0f} over {len(prior)} bars)"
        )

    atr_raw = atr(frame, cfg.atr_length).iloc[pos]
    atr_val = float(atr_raw) if np.isfinite(atr_raw) else 0.0

    entry = float(bo["close"])
    level = orh if cfg.stop_mode == "range_high" else float(bo["low"])
    buffer = max(cfg.buffer_atr_mult * atr_val, cfg.min_buffer_pct * entry)
    stop = level - buffer
    risk = entry - stop

    if risk <= 0:
        return None, f"non-positive risk (entry {entry:.2f} <= stop {stop:.2f})"

    target = entry + cfg.rr_multiple * risk
    status, bars_to, mfe_r, mae_r = _evaluate_outcome(
        today[today.index > bo_ts], entry, stop, target, risk
    )

    return (
        Signal(
            symbol=symbol,
            session=today.index[0].date().isoformat(),
            orh=round(orh, 4),
            orl=round(orl, 4),
            breakout_time=bo_ts.strftime("%Y-%m-%d %H:%M %Z"),
            entry=round(entry, 4),
            stop=round(stop, 4),
            target=round(target, 4),
            risk=round(risk, 4),
            risk_pct=round(risk / entry * 100, 3),
            reward=round(target - entry, 4),
            rr=cfg.rr_multiple,
            vol=float(bo["volume"]),
            vol_benchmark=round(benchmark, 1),
            vol_ratio=round(vol_ratio, 2),
            vol_window_bars=len(prior),
            vol_window_crossed_session=bool((prior.index.date != bo_ts.date()).any()),
            atr=round(atr_val, 4),
            is_latest_bar=bool(bo_ts == today.index[-1]),
            last_price=round(float(today["close"].iloc[-1]), 4),
            status=status,
            bars_to_resolution=bars_to,
            mfe_r=round(mfe_r, 2) if mfe_r is not None else None,
            mae_r=round(mae_r, 2) if mae_r is not None else None,
        ),
        None,
    )


def screen_symbol(
    df: pd.DataFrame, symbol: str, cfg: Config, session: Optional[str] = None
) -> tuple[Optional[Signal], Optional[str]]:
    """Screen the latest session, or a specific one via session='YYYY-MM-DD'."""
    rth = regular_session(df, cfg)
    if rth.empty:
        return None, "no regular-hours bars"

    dates = sorted(set(rth.index.date))
    target_date = pd.Timestamp(session).date() if session is not None else dates[-1]
    if target_date not in dates:
        return None, f"no bars for session {target_date}"

    # Drop later sessions so a backfilled run cannot see the future.
    scoped = rth[rth.index.date <= target_date]
    today = scoped[scoped.index.date == target_date]

    start = scoped.index.get_loc(today.index[0])
    history = cfg.vol_lookback + cfg.atr_length
    frame = scoped.iloc[max(0, start - history) :]

    return _build_signal(frame, today, symbol, cfg)


def load_csv(path: str, input_tz: str) -> dict[str, pd.DataFrame]:
    """Load one- or multi-symbol OHLCV CSV into {symbol: frame}."""
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]

    ts_col = next(
        (c for c in ("timestamp", "time", "datetime", "date") if c in raw.columns),
        None,
    )
    if ts_col is None:
        raise ValueError(
            f"{path}: need a timestamp column (timestamp/time/datetime/date), "
            f"found {list(raw.columns)}"
        )

    missing = {"open", "high", "low", "close", "volume"} - set(raw.columns)
    if missing:
        raise ValueError(f"{path}: missing column(s) {sorted(missing)}")

    sym_col = next((c for c in ("symbol", "ticker") if c in raw.columns), None)
    raw = raw.set_index(ts_col)

    if sym_col is None:
        return {"": to_et(raw, input_tz)}
    return {
        str(sym): to_et(g.drop(columns=[sym_col]), input_tz)
        for sym, g in raw.groupby(sym_col)
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Opening-range breakout screen.")
    p.add_argument("--csv", required=True, help="OHLCV CSV path")
    p.add_argument("--ticker", default=None, help="symbol name for a single-symbol CSV")
    p.add_argument("--session", default=None, help="YYYY-MM-DD (default: latest)")
    p.add_argument("--timeframe", default=None, help="resample, e.g. 5min")
    p.add_argument("--input-tz", default="America/New_York", help="tz of naive timestamps")
    p.add_argument("--opening-minutes", type=int, default=30)
    p.add_argument("--vol-lookback", type=int, default=20)
    p.add_argument("--vol-multiple", type=float, default=1.5)
    p.add_argument("--rr-multiple", type=float, default=2.0)
    p.add_argument("--stop-mode", choices=("range_high", "bar_low"), default="range_high")
    p.add_argument("--buffer-atr-mult", type=float, default=0.10)
    p.add_argument("--min-buffer-pct", type=float, default=0.0005)
    p.add_argument("--confirm-on", choices=("close", "high"), default="close")
    p.add_argument("--show-rejects", action="store_true", help="list why each symbol failed")
    p.add_argument("--csv-out", default=None, help="write signals to this path")
    args = p.parse_args(argv)

    cfg = Config(
        opening_minutes=args.opening_minutes,
        vol_lookback=args.vol_lookback,
        vol_multiple=args.vol_multiple,
        rr_multiple=args.rr_multiple,
        stop_mode=args.stop_mode,
        buffer_atr_mult=args.buffer_atr_mult,
        min_buffer_pct=args.min_buffer_pct,
        confirm_on=args.confirm_on,
    )

    frames = load_csv(args.csv, args.input_tz)
    if "" in frames:
        frames = {args.ticker or "SYMBOL": frames.pop("")}

    signals: list[Signal] = []
    rejects: list[tuple[str, str]] = []

    for symbol in sorted(frames):
        df = frames[symbol]
        if args.timeframe:
            df = resample(df, args.timeframe)
        try:
            sig, reason = screen_symbol(df, symbol, cfg, args.session)
        except Exception as exc:  # one bad symbol should not kill the scan
            rejects.append((symbol, f"error: {exc}"))
            continue
        if sig is not None:
            signals.append(sig)
        else:
            rejects.append((symbol, reason or "unknown"))

    if signals:
        table = pd.DataFrame([asdict(s) for s in signals])
        cols = [
            "symbol", "session", "breakout_time", "orh", "entry", "stop",
            "target", "risk", "risk_pct", "rr", "vol_ratio", "status",
            "mfe_r", "mae_r", "is_latest_bar", "last_price",
        ]
        print(table[cols].to_string(index=False))
        if args.csv_out:
            table.to_csv(args.csv_out, index=False)
            print(f"\nwrote {len(table)} signal(s) to {args.csv_out}")
    else:
        print("no setups")

    if args.show_rejects and rejects:
        print("\nrejected:")
        for symbol, reason in rejects:
            print(f"  {symbol:<8} {reason}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
