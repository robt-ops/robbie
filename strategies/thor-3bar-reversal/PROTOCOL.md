# Backtest protocol — intraday

A Strategy Tester screenshot is not evidence. This is the standard a result
has to clear before it earns a `v(N+1)`, and the order to do it in.

The short version: **"easiest to code" and "worth coding" are different
rankings.** The cleanest-coding setups — single threshold, close-of-bar
entry, no intra-bar path — are exactly the ones whose ambiguous choices got
hidden inside them. A strategy that looks clean usually just hid its
assumptions somewhere you are not looking.

---

## 1. Attribute before you tune

Before pre-registering a search, find out whether there is anything to search
for. Measure the entry signal on its own — through a pure bracket, no
break-even stop, no time stop, gross of all costs — and compare it against the
cost drag it would have to clear:

```bash
python3 sweep.py bars/*.csv --mode attribution
```

If that interval contains zero, or the edge is smaller than costs, the signal
carries no tradeable information and **no filter can give it any**: a filter
selects signals, it does not improve them. Replacing the signal is the only
move. Skipping this step is how a dead signal absorbs weeks of filter tuning.

Test the signal inverted in the same breath. Flat both ways is noise;
reliably negative is a backwards edge worth pre-registering on fresh data.

Then attribute the rest. Each exit rule gets its own line, and any rule
costing you more than it returns goes before anything else is tuned.

## 2. Pre-register, before you look

Write this down first. Anything decided *after* seeing results is fitting,
not testing.

```
Entry rule:
Exit rule:
Stop:
Instruments:
Timeframe:
Date range:
Filters (time-of-day, regime, volatility):
Variants I will try (count them):
```

The variant count is the number that goes into `--trials`. It is the honest
total of everything tried on this data — every parameter tweak, every filter
on/off, every symbol in the sweep — not the three that got written down. If
you scan 20 instruments × 10 variants you *will* find something; the only
defense is counting the 200.

Regime and time-of-day filters are themselves free parameters. Three regime
definitions × five time windows is fifteen more trials, and one of them will
look good by chance.

## 3. Fill model

| | |
|---|---|
| Market entry | next bar's open, never the signal bar's close |
| Stop orders | fill at `max(stop, open)` on a gap through; stops are not limits |
| Both stop and target inside one bar | assume the stop |
| Slippage | ≥1 tick, 2 on breakouts |
| Costs | commission + spread, **per side, per instrument** |

The signal-bar close is the thing that *produced* the signal. Filling there
is the single most common source of fake intraday edges. `backtest.py`
defaults to `--entry next_open` for this reason; `--entry close` exists only
to measure how much of a result comes from the look-ahead:

```bash
python3 backtest.py ohlcv.csv --entry next_open
python3 backtest.py ohlcv.csv --entry close     # the difference is the leak
```

## 4. Pine settings

| Setting | Why | v1 / v2 / v3 |
|---|---|---|
| `process_orders_on_close` unset (false) | otherwise fills at the signal-bar close | ✅ not set |
| `lookahead=barmerge.lookahead_off` | `lookahead_on` leaks future HTF bars | ✅ set on both `request.security` calls |
| `use_bar_magnifier=true` | resolves bars where stop *and* target are in range | ✅ set |
| `slippage` / `commission_*` set | TradingView defaults to zero cost | ✅ 2 ticks, 0.01% |

Two things are **not** settled by that table and are worth knowing:

- **Intrabar HTF mutation.** `lookahead_off` is not look-ahead — historical
  bars only see data available at the time. But during a *forming* HTF bar
  the value still updates, so the filter can read differently live than it
  did in the test. Offsetting the HTF series by `[1]` gives a stable,
  fully-closed value. Decide which you want; don't leave it accidental.
- **Repainting signals.** Anything evaluated on a bar that is still forming
  can flip before the close. Confirm signals on closed bars only.

## 5. Data quality

Split-adjusted. RTH only. Drop halt bars. Filter prints more than X ATR from
the prior close. Watch the opening bar specifically — after-hours volume
contaminates it, and the opening bar is where a disproportionate share of
intraday signals fire.

## 6. Metric and sample size

**Power against mean R per trade (expectancy), not win rate.** Breakout and
ORB systems win 35–45% of the time and make their money on payoff asymmetry;
a win-rate test says nothing about whether they work. `validate.py` reports
mean R, its standard error, and the trade count needed to detect the edge
you actually observed.

Win-rate sample sizes, for reference, at α=0.05 and 80% power:

| Edge | One-sided | Two-sided |
|---|---|---|
| 55% vs 50% | 616 | 783 |
| 60% vs 50% | 152 | 194 |

R-based requirements depend on R variance and are usually larger. Either
way: hundreds of trades is the floor, and that is *before* any parameter
fitting inflates it.

**Trade count overstates your sample.** Intraday trades cluster inside a
session, so N trades are worth fewer than N independent bets. Don't guess
the discount — measure it. `validate.py` runs a block bootstrap resampling
whole sessions alongside a naive iid bootstrap and reports the ratio:

```
clustering: block SE is 1.16× the iid SE  →  917 trades ≈ 685 independent bets
```

If the block interval is much wider, the clustering is real and the naive
confidence interval was lying to you.

## 7. Selection

Pre-registration alone is not enough; you still picked a winner. Deflate it.
`validate.py` reports the deflated Sharpe ratio: the probability the true
Sharpe beats `E[max SR]`, the Sharpe the best of `--trials` *worthless*
variants would post by luck alone.

```bash
python3 validate.py trades.csv --trials 200
```

DSR ≥ 0.95 survives. 0.90–0.95 is a candidate, not a result. Below 0.90, the
winner is consistent with having been picked out of noise.

`V[SR]` is estimated across the variants in the file, so feed it every
variant you ran, not just the survivors. Estimated from three, it is itself
noisy — treat the number as indicative at that count.

## 8. Walk-forward

```bash
python3 validate.py trades.csv --trials 200 --holdout 0.3
```

**Single-use.** Every time you tune after reading it, the holdout becomes
in-sample and stops being evidence. If you have already looked twice, you
need new data, not a new split.

## 9. Paper, then size

≥100 live or paper trades. Compare realized slippage against the model
before sizing up. If realized slippage is materially worse than assumed, the
backtest was measuring a market that doesn't exist.

---

## Running it

```bash
python3 sweep.py bars/*.csv --mode attribution        # is there a signal at all
python3 backtest.py ohlcv.csv --trades-out trades.csv
python3 validate.py trades.csv --trials <honest count> --holdout 0.3
```

`backtest.py` is an approximate replica of the Pine logic (see its
docstring) — good for directional comparison between versions, not for
publishing absolute numbers. `validate.py` works on any trades csv with a
per-trade `r` (or `pnl`) column and a `session` or `entry_time` column, so
you can also point it at trades exported from TradingView's List of Trades.

## What this does not fix

The protocol tells you whether a *backtestable* rule has an edge. It cannot
rescue a rule that can't be backtested from bar data at all — tick scalping
and tape reading have no retail edge to find and no way to test for one, and
anything needing an order-imbalance feed isn't available on TradingView
regardless of how the test is set up.
