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

## Results on real data

Tested on **11 instruments × 165 sessions** of real 5-minute bars
(2026-02-23 → 2026-10-16): SPY, QQQ, IWM, AAPL, MSFT, NVDA, TSLA, AMD, META,
AMZN, GOOGL. ~141,000 bars, synthesized gap-fill bars dropped, next-bar-open
fills.

On SPY alone, v1/v2/v3 give mean R of −0.405 / −0.179 / +0.058. v3's `+0.058`
is on 31 trades and is indistinguishable from zero.

### It is not SPY-specific

`sweep.py --mode symbols`, raw pattern with no filters:

| | trades | symbol-sessions | mean R | 95% CI | positive on |
|---|---|---|---|---|---|
| with filters | 1,526 | 1,041 | −0.304 | [−0.345, −0.264] | **0 of 11** |
| pattern only | 12,746 | 1,815 | −0.288 | [−0.303, −0.272] | **0 of 11** |

Not an underpowered null — a tight, confidently negative interval on every
instrument tested.

### Where the money goes

`sweep.py --mode attribution` splits mean R into signal, exits, and costs:

| component | N | mean R | Δ | win% | 95% CI |
|---|---|---|---|---|---|
| entry signal (pure bracket, gross) | 9,161 | −0.025 | | 37.5 | [−0.051, −0.000] |
| + break-even stop | 11,679 | −0.167 | **−0.142** | 17.2 | [−0.184, −0.151] |
| + time stop | 12,767 | −0.159 | +0.009 | 21.0 | [−0.174, −0.144] |
| + costs = as configured | 12,746 | −0.288 | −0.129 | 20.3 | [−0.303, −0.272] |
| *same bracket, inverted signal* | 9,041 | *+0.003* | | *38.6* | *[−0.023, +0.029]* |

Breakeven win rate for the 1.25/2.0 ATR bracket is 38.5%.

Three conclusions, in order of importance:

**1. The entry signal carries no information.** Through a pure bracket, gross
of costs, it returns −0.025 R at a 37.5% win rate — landing on the 38.5%
breakeven. Inverted it returns +0.003 R. Flat in both directions is noise,
not a backwards edge. **A filter selects signals; it cannot improve them.**
This is why no filter earned its place and why all 144 grid cells lost: there
was nothing underneath to select from.

**2. The break-even stop costs 0.142 R per trade** — the largest single
effect in the system, and negative. Moving the stop to entry after a
favorable excursion surrenders the remaining option value and keeps full
losers; with no edge, that is strictly negative. It also drags the win rate
from 37.5% to 17.2%.

**3. Costs add another 0.129 R**, mostly the 0.01%-of-notional commission
($0.07/share on SPY ≈ 0.18 R against a 1.25 ATR stop, roughly 14× a realistic
retail fill). The Pine files use `commission_value=0.01` percent, so the
Strategy Tester numbers carry the same overstatement.

Reproduce:

```bash
python3 sweep.py bars/*.csv --mode attribution
python3 sweep.py bars/*.csv --mode symbols
```

### What to do with this

Run `--mode attribution` before tuning anything. Drop the break-even stop and
fix the commission assumption regardless. But the signal needs **replacing,
not filtering** — the v4–v6 ideas below all add filters or adjust exits on top
of an entry with no measured information, so none of them can work.

Caveat: 165 sessions is below the ≥300 the protocol asks for, and this is one
timeframe. The finding is "no edge in the 3-bar pattern on 5-minute bars
across 11 liquid US names", not a claim about every timeframe.

## Validating results

```bash
python3 backtest.py ohlcv.csv --trades-out trades.csv
python3 validate.py trades.csv --trials <variants you tried> --holdout 0.3
```

`sweep.py` searches without fooling you:

| mode | question it answers |
|---|---|
| `--mode attribution` | **Start here.** Splits mean R into signal, each exit rule, and costs. Also reports the signal inverted. |
| `--mode costs` | Is the edge negative *before* costs? |
| `--mode symbols` | Does the sign hold across a basket, or flip around zero? |
| `--mode ablation` | Does each filter earn its place, or just cost you trades? |
| `--mode grid` | Ranks the grid, then deflates the winner by the trial count it counted itself. |

Run `attribution` first. If the entry signal's interval contains zero, every
other mode is wasted effort — there is nothing for a filter to select.

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

These were drafted before the attribution above showed the entry signal has
no measured information. v4–v6 add filters or adjust exits, so none of them
can create an edge that isn't there; they are kept only as a record.

- **v4 Volatility-Regime** — run v2 logic in low-ATR regimes, v3 in high-ATR regimes (auto-switch).
- **v5 Multi-Target** — scale out 50% at 1R, ride the rest with trail.
- **v6 Time-of-Day** — bucket signals by hour, mute the worst-performing buckets.
- ~~**v7 Bar-Pattern-Only**~~ — done, via `sweep.py --mode ablation`. The raw
  pattern is negative gross of costs on SPY 5-min, so this is answered rather
  than pending.

## File layout

```
strategies/thor-3bar-reversal/
  v1.pine      — Baseline (original v3.3, visual upgrades)
  v2.pine      — Selective (stricter signal, better R:R)
  v3.pine      — Trend-Strength (slope-gated, adaptive target, trailing)
  backtest.py  — approximate Python replica of v1/v2/v3
  sweep.py     — cost decomposition, filter ablation, deflated grid search
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
magnifier on, `process_orders_on_close` unset); PROTOCOL.md §4 has the audit
and the two open questions it does not settle.
