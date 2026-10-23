# Opening-Range Breakout Screen

Scans US equity intraday bars for long setups where price closes above the
30-minute opening-range high on expanding volume, then sizes a stop just below
the broken level and a target at a fixed risk multiple.

## Files

| File | Purpose |
|---|---|
| `orb_screen.py` | the screen; importable, and a CLI |
| `test_orb_screen.py` | 17 tests / 41 checks on synthetic fixtures, no network |

## Run

```bash
# multi-symbol CSV (needs a symbol column) — e.g. the live collector's output
python3 orb_screen.py --csv ~/Documents/lse-market-data/lse_1m_bars.csv --show-rejects

# single-symbol CSV
python3 orb_screen.py --csv nvda_1m.csv --ticker NVDA

# 5-minute bars, a specific session, write results out
python3 orb_screen.py --csv bars.csv --timeframe 5min --session 2026-10-22 \
    --csv-out signals.csv

python3 test_orb_screen.py
```

Input needs a header with `timestamp,open,high,low,close,volume`, plus an
optional `symbol`/`ticker` column. Naive timestamps are assumed Eastern;
override with `--input-tz`.

## The three conditions

**1. Breakout above the 30-minute opening-range high.** The opening range is
09:30–10:00 ET; ORH is the highest high within it. The signal is the *first*
bar after the range whose **close** exceeds the ORH.

Close-confirmed is the default so a wick through the level does not trigger.
`--confirm-on high` switches to intrabar, which fires earlier and more often
and is the looser setting, not the better one.

**2. Volume at least 1.5x the 20-period average.** The benchmark is the mean
volume of the 20 bars *strictly before* the breakout bar.

**3. Stop just past the broken level, target at 2R.** Stop is the broken level
minus a buffer; risk is `entry − stop`; target is `entry + 2 × risk`. Entry is
the breakout bar's close.

```
stop  = level − max(buffer_atr_mult × ATR(14), min_buffer_pct × entry)
level = ORH                       # --stop-mode range_high (default)
      | breakout bar's low        # --stop-mode bar_low
```

A pure percentage buffer is too tight on volatile names and too loose on calm
ones, so the buffer is ATR-scaled with a percentage floor. Defaults: `0.10 ×
ATR`, floor 5bp.

## Four decisions worth knowing about

**The volume benchmark excludes the breakout bar.** Including it lets the bar
inflate the benchmark it is judged against — at a 20-bar lookback it
contributes 1/20 of that mean, biasing the measured ratio down and making the
filter quietly weaker than its setting claims. A test pins this: six bars at
1,000 and a breakout at 1,500 is exactly 1.5x when excluded, but 1.40x when
included, so the setup passes only if the exclusion is working.

**The 20-bar window reaches into the prior session** for breakouts early in
the day, deliberately. Same-session-only has just six 5-minute bars available
at 10:00, and they are the heaviest bars of the day, which makes nearly any
later bar look thin by comparison. Every signal carries `vol_window_bars` and
`vol_window_crossed_session` so the benchmark is auditable.

**The volume multiple is timeframe-dependent, and this surprises people.**
The same setup on the same data gave 3.06x on 1-minute bars and 1.38x on
5-minute bars — pass and fail against the same 1.5x threshold. Resampling sums
one spiked minute with four ordinary ones, diluting the spike. So 1.5x is not
one filter; it is a different filter per bar size, and a threshold tuned on
one timeframe does not transfer. Tune on the timeframe you will run.

**Outcome fields are a replay, not a backtest.** `status`, `mfe_r` and `mae_r`
walk the bars after entry to say whether the target or stop came first. When a
single bar touches both, the stop is assumed first — the worst-case intrabar
convention also used in `strategies/thor-3bar-reversal/backtest.py`. No
commissions, no slippage, no partial fills, no position sizing.

## Reading the output

| Column | Meaning |
|---|---|
| `orh` | opening-range high that was broken |
| `entry` / `stop` / `target` | the three levels |
| `risk` / `risk_pct` | per-share risk, and as a percentage of entry |
| `vol_ratio` | breakout volume ÷ 20-bar benchmark |
| `status` | `target`, `stopped`, `open`, `no_follow_through` |
| `mfe_r` / `mae_r` | best and worst excursion after entry, in units of R |
| `is_latest_bar` | **true = the breakout just happened** |
| `last_price` | most recent close in the data |

`is_latest_bar` is the column that separates a live setup from a history
lesson. A signal with `is_latest_bar: false` and `status: target` is a trade
that already ran without you; the screen lists it because the structure
occurred, not because it is actionable. Filter on `is_latest_bar` for a live
scan.

`--show-rejects` prints why each symbol failed, which is usually more
informative than the hits — a list of near-misses at 1.3–1.4x volume tells you
the threshold is doing the work, while rejects reading "no close above ORH"
across the board means the day had no breakouts at all.

## Limitations

- **Long side only.** A short mirror keys off the opening-range low; not
  implemented.
- **No ranking.** The screen finds structure. It does not score quality and
  makes no claim a listed setup is worth taking.
- **Thresholds are untested priors.** 1.5x, 2R, the 0.10 ATR buffer — none are
  fitted to data. The `status` / `mfe_r` / `mae_r` fields exist so you can run
  the screen across past sessions and find out what these settings would
  actually have produced before trusting them.
- **Verified on synthetic fixtures only.** The 41 checks cover the arithmetic
  and the edge cases, and the CLI was exercised end-to-end against a generated
  multi-symbol file. It has not been run against live market data.
- **Gaps and halts are not special-cased.** A symbol halted through the
  opening range, or one that gapped so far the 30-minute range is meaningless,
  gets no special handling.
