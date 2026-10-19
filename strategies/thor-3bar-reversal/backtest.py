"""
Python sim of THOR 3-Bar Reversal v1/v2/v3.

Usage:
    python3 backtest.py path/to/ohlcv.csv
    python3 backtest.py ohlcv.csv --trades-out trades.csv   # then validate.py

CSV format (header required):
    timestamp,open,high,low,close,volume

Notes:
    Approximate replica of the Pine Script logic. Will NOT match TV's
    Strategy Tester exactly because:
      - No bar magnifier (intra-bar fills assume worst-case order).
      - VWAP resets daily on first-bar-of-session, not on TV's session boundary.
      - HTF resample uses pandas resample, not request.security.
      - Commissions/slippage are flat percent, not TV's model.

    Intended for *directional comparison* between v1/v2/v3, not for
    publishing absolute results. A result here is not evidence of an edge
    until validate.py says the sample supports it — see PROTOCOL.md.
"""

import argparse
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def session_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    session = df.index.date
    pv = (typical * df["volume"]).groupby(session).cumsum()
    vv = df["volume"].groupby(session).cumsum()
    return pv / vv


def htf_ema(df: pd.DataFrame, htf: str, length: int) -> pd.Series:
    htf_close = df["close"].resample(htf).last().dropna()
    htf_ema = ema(htf_close, length)
    return htf_ema.reindex(df.index, method="ffill"), htf_close.reindex(df.index, method="ffill")


@dataclass
class Config:
    name: str
    ema_len: int = 50
    htf: str = "15min"
    htf_ema_len: int = 50
    atr_len: int = 14
    vol_len: int = 20
    vol_mult: float = 1.25
    min_body_pct: float = 0.50
    risk_atr: float = 1.25
    target_atr: float = 2.00
    be_trigger: float = 1.00
    max_bars_hold: int = 12
    use_vwap: bool = True
    use_htf: bool = True
    use_be: bool = True
    strict_bar3: bool = True
    # v2 extras
    bar2_depth_pct: Optional[float] = None     # if set: bar2 close in this fraction
    atr_floor_mult: Optional[float] = None     # if set: atr > avg * mult
    bar3_overrun_bar1: bool = False
    # v3 extras
    slope_bars: Optional[int] = None
    slope_min_pct: Optional[float] = None
    strong_slope_pct: Optional[float] = None
    target_boost_atr: float = 0.0
    max_bars_strong: int = 16
    use_trail: bool = False
    trail_atr: float = 1.5
    # fill model
    entry_mode: str = "next_open"   # "next_open" (realistic) | "close" (look-ahead)
    # cost model
    commission_pct: float = 0.0001  # 0.01%
    slippage_ticks: float = 2.0
    tick: float = 0.01


CONFIGS = {
    "v1": Config(name="v1 [Baseline]"),
    "v2": Config(
        name="v2 [Selective]",
        vol_mult=1.50,
        min_body_pct=0.55,
        risk_atr=1.00,
        target_atr=2.50,
        max_bars_hold=10,
        bar2_depth_pct=0.40,
        atr_floor_mult=0.60,
        bar3_overrun_bar1=True,
    ),
    "v3": Config(
        name="v3 [Trend-Strength]",
        risk_atr=1.50,
        target_atr=2.00,
        max_bars_hold=16,
        strict_bar3=False,
        slope_bars=5,
        slope_min_pct=0.05,
        strong_slope_pct=0.20,
        target_boost_atr=1.00,
        max_bars_strong=20,
        use_trail=True,
        trail_atr=1.5,
    ),
}


def run(df: pd.DataFrame, cfg: Config) -> dict:
    df = df.copy()
    df["ema"] = ema(df["close"], cfg.ema_len)
    df["atr"] = atr(df, cfg.atr_len)
    df["atr_avg"] = df["atr"].rolling(20).mean()
    df["vwap"] = session_vwap(df)
    df["vol_sma"] = df["volume"].rolling(cfg.vol_len).mean()
    htf_e, htf_c = htf_ema(df, cfg.htf, cfg.htf_ema_len)
    df["htf_ema"], df["htf_close"] = htf_e, htf_c

    if cfg.slope_bars:
        df["ema_slope"] = (df["ema"] - df["ema"].shift(cfg.slope_bars)) / df["ema"].shift(cfg.slope_bars) * 100
        df["htf_slope"] = (df["htf_ema"] - df["htf_ema"].shift(cfg.slope_bars)) / df["htf_ema"].shift(cfg.slope_bars) * 100

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["body_pct"] = (df["close"] - df["open"]).abs() / rng
    df["body_pct"] = df["body_pct"].fillna(0)

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    bar1_bear = c.shift(2) < o.shift(2)
    bar2_lower = l.shift(1) < l.shift(2)
    bar1_bull = c.shift(2) > o.shift(2)
    bar2_higher = h.shift(1) > h.shift(2)

    if cfg.bar3_overrun_bar1:
        bar3_bull = (c > o) & (c > h.shift(2))
        bar3_bear = (c < o) & (c < l.shift(2))
    elif cfg.strict_bar3:
        bar3_bull = (c > o) & (c > h.shift(1))
        bar3_bear = (c < o) & (c < l.shift(1))
    else:
        bar3_bull = c > o
        bar3_bear = c < o

    long_pattern = bar1_bear & bar2_lower & bar3_bull
    short_pattern = bar1_bull & bar2_higher & bar3_bear

    body_ok = df["body_pct"] >= cfg.min_body_pct
    ema_long = c > df["ema"]
    ema_short = c < df["ema"]
    vol_ok = df["volume"] > df["vol_sma"] * cfg.vol_mult
    # `~` on a Python bool gives an int (~True == -2), which ORs into an
    # always-true mask and silently disables the filter. Branch instead.
    all_true = pd.Series(True, index=df.index)
    vwap_long = (c > df["vwap"]) if cfg.use_vwap else all_true
    vwap_short = (c < df["vwap"]) if cfg.use_vwap else all_true
    htf_long = (df["htf_close"] > df["htf_ema"]) if cfg.use_htf else all_true
    htf_short = (df["htf_close"] < df["htf_ema"]) if cfg.use_htf else all_true

    extra_long = pd.Series(True, index=df.index)
    extra_short = pd.Series(True, index=df.index)

    if cfg.bar2_depth_pct is not None:
        b2_range = (h.shift(1) - l.shift(1)).replace(0, np.nan)
        bar2_lower_zone = (c.shift(1) - l.shift(1)) <= b2_range * cfg.bar2_depth_pct
        bar2_upper_zone = (h.shift(1) - c.shift(1)) <= b2_range * cfg.bar2_depth_pct
        extra_long &= bar2_lower_zone.fillna(False)
        extra_short &= bar2_upper_zone.fillna(False)

    if cfg.atr_floor_mult is not None:
        atr_ok = df["atr"] > df["atr_avg"] * cfg.atr_floor_mult
        extra_long &= atr_ok.fillna(False)
        extra_short &= atr_ok.fillna(False)

    if cfg.slope_bars:
        ema_slope_up = df["ema_slope"] >= cfg.slope_min_pct
        ema_slope_dn = df["ema_slope"] <= -cfg.slope_min_pct
        htf_slope_up = df["htf_slope"] >= cfg.slope_min_pct
        htf_slope_dn = df["htf_slope"] <= -cfg.slope_min_pct
        extra_long &= ema_slope_up & htf_slope_up
        extra_short &= ema_slope_dn & htf_slope_dn

    long_sig = long_pattern & body_ok & ema_long & vol_ok & vwap_long & htf_long & extra_long
    short_sig = short_pattern & body_ok & ema_short & vol_ok & vwap_short & htf_short & extra_short

    # Walk forward.
    #
    # Entry defaults to the OPEN OF THE BAR AFTER the signal bar, which is
    # what Pine's strategy.entry does unless process_orders_on_close is set.
    # "close" fills at the close of the signal bar instead — that close is
    # the thing that produced the signal, so it is not a fill you could have
    # got. It is kept only to measure how much of a result comes from the
    # look-ahead rather than from the edge.
    trades = []
    pos = 0
    entry_px = entry_atr = 0.0
    entry_idx = 0
    stop = target = 0.0
    trail = None
    be_hit = False
    strong = False
    pending = 0                 # order armed by the previous bar's signal
    pending_atr = 0.0
    pending_strong = False

    if cfg.entry_mode not in ("next_open", "close"):
        raise ValueError(f"entry_mode must be next_open or close, got {cfg.entry_mode!r}")
    next_open = cfg.entry_mode == "next_open"
    slip = cfg.slippage_ticks * cfg.tick

    times = df.index.to_list()
    arr = df[["open", "high", "low", "close", "atr"]].to_numpy()
    htf_slope_arr = df["htf_slope"].to_numpy() if cfg.slope_bars else None
    ls = long_sig.to_numpy()
    ss = short_sig.to_numpy()

    def is_strong_trend(side: int, i: int) -> bool:
        sl = htf_slope_arr[i] if htf_slope_arr is not None else float("nan")
        return bool(
            cfg.strong_slope_pct and not np.isnan(sl)
            and (sl >= cfg.strong_slope_pct if side == 1 else sl <= -cfg.strong_slope_pct)
        )

    def open_position(side: int, px: float, a_: float, is_strong: bool):
        """Entry price plus the stop/target sized off the signal-bar ATR."""
        eff_tgt = cfg.target_atr + (cfg.target_boost_atr if is_strong else 0.0)
        if side == 1:
            e = px + slip
            return e, e - a_ * cfg.risk_atr, e + a_ * eff_tgt
        e = px - slip
        return e, e + a_ * cfg.risk_atr, e - a_ * eff_tgt

    for i in range(len(df)):
        o_, h_, l_, c_, a_ = arr[i]

        # 1. Fill the order armed by the previous bar.
        if pos == 0 and pending != 0:
            pos, entry_atr, strong = pending, pending_atr, pending_strong
            entry_idx = i
            entry_px, stop, target = open_position(pos, o_, entry_atr, strong)
            trail, be_hit, pending = None, False, 0

        # 2. Exits for this bar. In next_open mode the entry bar counts: you
        #    are filled at its open, so its own range can take you out.
        if pos != 0:
            bars_held = i - entry_idx
            eff_max = cfg.max_bars_strong if strong else cfg.max_bars_hold
            risk = entry_atr * cfg.risk_atr
            exit_px = None
            exit_reason = None

            if pos == 1:
                if cfg.use_be and h_ >= entry_px + entry_atr * cfg.be_trigger:
                    be_hit = True
                if cfg.use_trail and h_ >= entry_px + entry_atr * 1.0:
                    candidate = h_ - entry_atr * cfg.trail_atr
                    trail = candidate if trail is None else max(trail, candidate)
                eff_stop = entry_px if (cfg.use_be and be_hit) else stop
                if cfg.use_trail and trail is not None:
                    eff_stop = max(eff_stop, trail)

                # Pessimistic ordering: if the bar spans both, assume the stop.
                if l_ <= eff_stop:
                    exit_px, exit_reason = eff_stop - slip, "stop"
                elif h_ >= target:
                    exit_px, exit_reason = target - slip, "target"
                elif bars_held >= eff_max:
                    exit_px, exit_reason = c_ - slip, "time"
            else:
                if cfg.use_be and l_ <= entry_px - entry_atr * cfg.be_trigger:
                    be_hit = True
                if cfg.use_trail and l_ <= entry_px - entry_atr * 1.0:
                    candidate = l_ + entry_atr * cfg.trail_atr
                    trail = candidate if trail is None else min(trail, candidate)
                eff_stop = entry_px if (cfg.use_be and be_hit) else stop
                if cfg.use_trail and trail is not None:
                    eff_stop = min(eff_stop, trail)

                if h_ >= eff_stop:
                    exit_px, exit_reason = eff_stop + slip, "stop"
                elif l_ <= target:
                    exit_px, exit_reason = target + slip, "target"
                elif bars_held >= eff_max:
                    exit_px, exit_reason = c_ + slip, "time"

            if exit_px is not None:
                gross = (exit_px - entry_px) if pos == 1 else (entry_px - exit_px)
                pnl = gross - (entry_px + exit_px) * cfg.commission_pct
                entry_time = times[entry_idx]
                trades.append({
                    "side": "long" if pos == 1 else "short",
                    "entry_time": entry_time,
                    "exit_time": times[i],
                    "session": entry_time.date(),
                    "entry": entry_px, "exit": exit_px,
                    "pnl": pnl,
                    "r": pnl / risk if risk > 0 else np.nan,
                    "bars": bars_held, "reason": exit_reason,
                    "strong": strong,
                })
                pos = 0
                trail, be_hit, strong = None, False, False

        # 3. Arm an order off this bar's signal.
        if pos == 0 and pending == 0 and not np.isnan(a_):
            side = 1 if ls[i] else (-1 if ss[i] else 0)
            if side != 0:
                is_strong = is_strong_trend(side, i)
                if next_open:
                    pending, pending_atr, pending_strong = side, a_, is_strong
                else:
                    pos, entry_atr, strong, entry_idx = side, a_, is_strong, i
                    entry_px, stop, target = open_position(side, c_, a_, is_strong)
                    trail, be_hit = None, False

    return summarize(cfg.name, trades)


def summarize(name: str, trades: list) -> dict:
    if not trades:
        return {"name": name, "n": 0, "net": 0, "pf": 0, "win%": 0, "avg": 0,
                "maxdd": 0, "avg_r": 0, "sd_r": 0, "trades": pd.DataFrame()}
    t = pd.DataFrame(trades)
    pnl = t["pnl"]
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    eq = pnl.cumsum()
    dd = (eq.cummax() - eq).max()
    return {
        "name": name,
        "n": len(t),
        "net": pnl.sum(),
        "pf": wins / losses if losses > 0 else np.inf,
        "win%": (pnl > 0).mean() * 100,
        "avg": pnl.mean(),
        "maxdd": dd,
        "avg_r": t["r"].mean(),
        "sd_r": t["r"].std(ddof=1) if len(t) > 1 else 0.0,
        "trades": t,
        "longs": (t["side"] == "long").sum(),
        "shorts": (t["side"] == "short").sum(),
        "by_reason": t["reason"].value_counts().to_dict(),
    }


def load_ohlcv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def run_all(df: pd.DataFrame, entry_mode: str = "next_open") -> list:
    rows = []
    for cfg in CONFIGS.values():
        rows.append(run(df, replace(cfg, entry_mode=entry_mode)))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="OHLCV csv: timestamp,open,high,low,close,volume")
    ap.add_argument("--entry", choices=["next_open", "close"], default="next_open",
                    help="fill at next bar's open (default, realistic) or at the "
                         "signal bar's close (look-ahead; for comparison only)")
    ap.add_argument("--trades-out", metavar="PATH",
                    help="write every trade to this csv, for validate.py")
    args = ap.parse_args()

    df = load_ohlcv(args.csv)
    print(f"Loaded {len(df):,} bars  {df.index.min()} → {df.index.max()}")
    print(f"Entry fill: {args.entry}")
    print()

    rows = run_all(df, entry_mode=args.entry)

    hdr = (f"{'Version':<22}{'N':>6}{'Net $':>12}{'PF':>8}{'Win%':>8}"
           f"{'Avg R':>8}{'SD R':>8}{'MaxDD $':>12}{'Long/Short':>14}")
    print(hdr)
    for r in rows:
        ls_short = f"{r.get('longs', 0)}/{r.get('shorts', 0)}"
        print(f"{r['name']:<22}{r['n']:>6}{r['net']:>12.2f}{r['pf']:>8.2f}"
              f"{r['win%']:>8.1f}{r['avg_r']:>8.3f}{r['sd_r']:>8.3f}"
              f"{r['maxdd']:>12.2f}{ls_short:>14}")
    print()
    print("Exit reasons by version:")
    for r in rows:
        print(f"  {r['name']:<22} {r.get('by_reason', {})}")

    if args.trades_out:
        frames = []
        for r in rows:
            t = r["trades"]
            if len(t):
                t = t.copy()
                t.insert(0, "variant", r["name"])
                frames.append(t)
        if frames:
            pd.concat(frames, ignore_index=True).to_csv(args.trades_out, index=False)
            print()
            print(f"Wrote trades → {args.trades_out}")
            print(f"Next: python3 validate.py {args.trades_out}")
        else:
            print("\nNo trades — nothing written.")


if __name__ == "__main__":
    main()
