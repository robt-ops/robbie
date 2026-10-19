# THOR 3-Bar Reversal — Versioned Strategies

Each `vN.pine` is a self-contained Pine Script v6 strategy. Paste it into TradingView (Pine Editor → "Add to chart") and run the Strategy Tester to backtest.

## Version map

| Version | Tagline | Core idea | Notable knobs |
|--------:|---------|-----------|---------------|
| **v1** | Baseline | Original v3.3 logic, unchanged. Visual upgrades only. | strict bar 3, 1.25 ATR stop, 2.0 ATR target |
| **v2** | Selective | Higher-quality entries, fewer trades, better R:R. | bar 2 close in lower/upper 40%, bar 3 overruns bar 1, ATR floor, 1.5× volume, 1.0/2.5 ATR |
| **v3** | Trend-Strength | Use trend slope as the quality filter; ride winners further. | EMA + HTF slope required, relaxed bar 3, adaptive target (+1 ATR in strong trend), ATR trailing stop |

## Reading the chart

Same role colors across all versions — only the title / labels / table change. So you can stack two versions on the same chart and instantly tell them apart.

- **Orange** — EMA (50)
- **Blue** — VWAP
- **Purple** — HTF EMA
- **Red line** (during trade) — active stop
- **Green line** (during trade) — target
- **White line** (during trade) — entry / avg price
- **Yellow line** (v3 only) — ATR trailing stop, once armed
- **Green/red tint** — currently in long / short
- **Green/red triangles** — entry signal bar
- **Labels** — show version, price, SL, TP, R:R
- **Top-right table** — live state of every filter (UP/DN/OK/low) so you can see at a glance why a signal did or did not fire

## Backtest workflow

1. Open TradingView → your symbol + timeframe.
2. Pine Editor → paste `v1.pine` → Save → "Add to chart".
3. Open the **Strategy Tester** panel → screenshot or copy the Overview stats (Net Profit, % Profitable, Profit Factor, Max DD, Avg Trade, # of Trades).
4. Repeat for `v2.pine` and `v3.pine` on the same symbol/timeframe.
5. Drop the numbers back in chat — I'll propose `v4` based on what's actually weak.

Before those numbers mean anything, run them through **[PROTOCOL.md](PROTOCOL.md)**.
A Strategy Tester screenshot is not evidence of an edge: 50–100 trades cannot
separate a real edge from luck, and whichever version "wins" was picked out of
however many variants you tried.

### Stats to send back

Per version, this is what I need to tune the next iteration:

```
Symbol / TF:
Date range:
Net Profit:
% Profitable:
Profit Factor:
Max Drawdown:
Avg Trade:
# of Trades:
Largest Losing Trade:
Avg Bars in Winning Trades / Losing Trades:
```

## Validating results

```bash
python3 backtest.py ohlcv.csv --trades-out trades.csv
python3 validate.py trades.csv --trials <variants you tried> --holdout 0.3
```

`validate.py` answers the question the Strategy Tester doesn't:

- **Expectancy, not win rate.** Mean R per trade with a confidence interval.
  These versions take 1.0–1.5 ATR stops against 2.0–3.0 ATR targets, so they
  win well under half their trades by design and a win-rate test tells you
  nothing.
- **Effective sample size.** A session block bootstrap against a naive iid
  one. Intraday trades cluster inside a session, so 200 trades are worth
  fewer than 200 independent bets — this measures how many fewer instead of
  guessing.
- **Deflated Sharpe.** The probability the winner beats what the best of N
  *worthless* variants posts by luck. Pass the honest N via `--trials`.
- **Walk-forward.** A single-use chronological holdout.

It reads any trades csv with a per-trade `r` (or `pnl`) column plus a
`session` or `entry_time` column, so it also works on trades exported from
TradingView's List of Trades.

## Ideas for future versions

Already on deck — pick the direction once we see v1/v2/v3 results:

- **v4 Volatility-Regime** — run v2 logic in low-ATR regimes, v3 in high-ATR regimes (auto-switch).
- **v5 Multi-Target** — scale out 50% at 1R, ride the rest with trail.
- **v6 Time-of-Day** — bucket signals by hour, mute the worst-performing buckets.
- **v7 Bar-Pattern-Only** — drop EMA/VWAP/HTF filters to isolate the raw 3-bar edge.

## File layout

```
strategies/thor-3bar-reversal/
  v1.pine      — Baseline (original v3.3, visual upgrades)
  v2.pine      — Selective (stricter signal, better R:R)
  v3.pine      — Trend-Strength (slope-gated, adaptive target, trailing)
  backtest.py  — approximate Python replica of v1/v2/v3
  validate.py  — is it an edge or is it luck
  stats.py     — bootstrap, deflated Sharpe, power (no scipy)
  PROTOCOL.md  — the standard a result has to clear
  README.md    — this file
```

## Known limits of the Python sim

`backtest.py` approximates the Pine logic and will not match the Strategy
Tester exactly — see its docstring for why. Use it for directional comparison
between versions, not for publishing absolute numbers. The Pine files
themselves are clean on the usual look-ahead traps (`lookahead_off`, bar
magnifier on, `process_orders_on_close` unset); PROTOCOL.md §3 has the audit
and the two open questions it does not settle.
