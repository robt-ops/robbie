"""
Python sim of THOR 3-Bar Reversal v1/v2/v3.

Usage:
    python3 backtest.py path/to/ohlcv.csv

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
    publishing absolute results.
"""

import sys
from dataclasses import dataclass, field
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
    vwap_long = (~cfg.use_vwap) | (c > df["vwap"])
    vwap_short = (~cfg.use_vwap) | (c < df["vwap"])
    htf_long = (~cfg.use_htf) | (df["htf_close"] > df["htf_ema"])
    htf_short = (~cfg.use_htf) | (df["htf_close"] < df["htf_ema"])

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

    # Walk forward
    trades = []
    pos = 0
    entry_px = entry_atr = entry_idx = 0.0
    stop = target = 0.0
    trail = None
    be_hit = False
    strong = False

    slip = cfg.slippage_ticks * cfg.tick

    times = df.index.to_list()
    arr = df[["open", "high", "low", "close", "atr"]].to_numpy()
    htf_slope_arr = df["htf_slope"].to_numpy() if cfg.slope_bars else None
    ls = long_sig.to_numpy()
    ss = short_sig.to_numpy()

    for i in range(len(df)):
        o_, h_, l_, c_, a_ = arr[i]

        if pos == 0:
            if ls[i] and not np.isnan(a_):
                pos = 1
                entry_px = c_ + slip
                entry_atr = a_
                entry_idx = i
                stop = entry_px - a_ * cfg.risk_atr
                strong = bool(cfg.strong_slope_pct and htf_slope_arr is not None
                              and not np.isnan(htf_slope_arr[i])
                              and htf_slope_arr[i] >= cfg.strong_slope_pct)
                eff_tgt = cfg.target_atr + (cfg.target_boost_atr if strong else 0.0)
                target = entry_px + a_ * eff_tgt
                trail = None
                be_hit = False
            elif ss[i] and not np.isnan(a_):
                pos = -1
                entry_px = c_ - slip
                entry_atr = a_
                entry_idx = i
                stop = entry_px + a_ * cfg.risk_atr
                strong = bool(cfg.strong_slope_pct and htf_slope_arr is not None
                              and not np.isnan(htf_slope_arr[i])
                              and htf_slope_arr[i] <= -cfg.strong_slope_pct)
                eff_tgt = cfg.target_atr + (cfg.target_boost_atr if strong else 0.0)
                target = entry_px - a_ * eff_tgt
                trail = None
                be_hit = False
            continue

        # In a position — process exits on this bar
        bars_held = i - entry_idx
        eff_max = cfg.max_bars_strong if strong else cfg.max_bars_hold

        if pos == 1:
            # Break-even latch
            if cfg.use_be and bars_held >= 1 and h_ >= entry_px + entry_atr * cfg.be_trigger:
                be_hit = True
            # Trailing
            if cfg.use_trail and h_ >= entry_px + entry_atr * 1.0:
                candidate = h_ - entry_atr * cfg.trail_atr
                trail = candidate if trail is None else max(trail, candidate)
            eff_stop = entry_px if (cfg.use_be and be_hit) else stop
            if cfg.use_trail and trail is not None:
                eff_stop = max(eff_stop, trail)

            # Pessimistic fill order: stop before target if both hit
            exit_px = None
            exit_reason = None
            if l_ <= eff_stop:
                exit_px = eff_stop - slip
                exit_reason = "stop"
            elif h_ >= target:
                exit_px = target - slip
                exit_reason = "target"
            elif bars_held >= eff_max:
                exit_px = c_ - slip
                exit_reason = "time"

            if exit_px is not None:
                pnl = (exit_px - entry_px) - (entry_px + exit_px) * cfg.commission_pct
                trades.append({
                    "side": "long",
                    "entry_time": times[int(entry_idx)],
                    "exit_time": times[i],
                    "entry": entry_px, "exit": exit_px,
                    "pnl": pnl, "bars": bars_held, "reason": exit_reason,
                    "strong": strong,
                })
                pos = 0; trail = None; be_hit = False; strong = False

        else:  # pos == -1
            if cfg.use_be and bars_held >= 1 and l_ <= entry_px - entry_atr * cfg.be_trigger:
                be_hit = True
            if cfg.use_trail and l_ <= entry_px - entry_atr * 1.0:
                candidate = l_ + entry_atr * cfg.trail_atr
                trail = candidate if trail is None else min(trail, candidate)
            eff_stop = entry_px if (cfg.use_be and be_hit) else stop
            if cfg.use_trail and trail is not None:
                eff_stop = min(eff_stop, trail)

            exit_px = None
            exit_reason = None
            if h_ >= eff_stop:
                exit_px = eff_stop + slip
                exit_reason = "stop"
            elif l_ <= target:
                exit_px = target + slip
                exit_reason = "target"
            elif bars_held >= eff_max:
                exit_px = c_ + slip
                exit_reason = "time"

            if exit_px is not None:
                pnl = (entry_px - exit_px) - (entry_px + exit_px) * cfg.commission_pct
                trades.append({
                    "side": "short",
                    "entry_time": times[int(entry_idx)],
                    "exit_time": times[i],
                    "entry": entry_px, "exit": exit_px,
                    "pnl": pnl, "bars": bars_held, "reason": exit_reason,
                    "strong": strong,
                })
                pos = 0; trail = None; be_hit = False; strong = False

    return summarize(cfg.name, trades)


def summarize(name: str, trades: list) -> dict:
    if not trades:
        return {"name": name, "n": 0, "net": 0, "pf": 0, "win%": 0, "avg": 0, "maxdd": 0}
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
        "longs": (t["side"] == "long").sum(),
        "shorts": (t["side"] == "short").sum(),
        "by_reason": t["reason"].value_counts().to_dict(),
    }


def main():
    if len(sys.argv) < 2:
        print("usage: python3 backtest.py path/to/ohlcv.csv")
        sys.exit(1)
    path = sys.argv[1]
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    print(f"Loaded {len(df):,} bars  {df.index.min()} → {df.index.max()}")
    print()

    rows = []
    for key, cfg in CONFIGS.items():
        rows.append(run(df, cfg))

    print(f"{'Version':<22}{'N':>6}{'Net $':>12}{'PF':>8}{'Win%':>8}{'Avg $':>10}{'MaxDD $':>12}{'Long/Short':>14}")
    for r in rows:
        ls_short = f"{r.get('longs', 0)}/{r.get('shorts', 0)}"
        print(f"{r['name']:<22}{r['n']:>6}{r['net']:>12.2f}{r['pf']:>8.2f}{r['win%']:>8.1f}{r['avg']:>10.2f}{r['maxdd']:>12.2f}{ls_short:>14}")
    print()
    print("Exit reasons by version:")
    for r in rows:
        print(f"  {r['name']:<22} {r.get('by_reason', {})}")


if __name__ == "__main__":
    main()
