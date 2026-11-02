# ETF BBMR — Backtest Review (2026-11-02)

Review of the first three `etf_bbmr.py` backtest runs plus one live scan, from the
session of 2026-11-02. **The script itself is not yet in this repo** — see
[Getting the source in here](#getting-the-source-in-here).

Universe across all runs: `DIA IWM QQQ SCHD SPY XLF XLK XLV`. Max 4 concurrent
positions. Regime filter: SPY vs its 200-day.

## Results as reported

| | 1h | 15m | 5m |
|---|---|---|---|
| Period | 2023-12-05 → 2026-11-02 | 2026-08-11 → 2026-11-02 | 2026-08-11 → 2026-11-02 |
| Calendar span | ~1063 days | ~83 days | ~83 days |
| Total return | **+5.27%** | −0.24% | +0.33% |
| SPY buy & hold | +66.13% | −1.12% | −1.48% |
| Max drawdown | −1.17% | −0.67% | −0.81% |
| Profit factor | 1.34 | 0.90 | 1.10 |
| Trades | 716 | 208 | 593 |
| Win rate | 66.6% | 57.7% | 63.4% |
| Avg trade | +0.15% | −0.03% | +0.01% |
| Avg win / avg loss | +0.87% / −1.29% | +0.38% / −0.58% | +0.20% / −0.31% |
| Avg hold | 8.4 bars | 12.7 bars | 11.4 bars |
| Avg exposure | 5.9% | 8.7% | 7.4% |
| Bars at 4 open | 14.3% | 23.3% | 17.6% |
| Risk-on bars | 92.3% | 100.0% | 100.0% |
| Exits: TP / SL | 540 / 176 | 190 / 18 | 581 / 12 |

Live scan, 15m, last closed bar 2026-11-02 10:45 ET:
`SPY 760.99 vs 200D 728.85 -> RISK-ON`, no setups, no orders placed.

### Internal consistency

The reported stats are arithmetically coherent — win rate, average win/loss,
profit factor and average trade all reconcile to within rounding on all three
runs. Whatever else is wrong, the summary math is not.

## Findings

### 1. The backtests ran on ~$100k; the scan ran on $250k

Summing the per-symbol P&L and dividing by the reported total return gives the
equity the backtest actually used:

| TF | Σ per-symbol P&L | Total return | Implied equity |
|---|---|---|---|
| 1h | $5,187.74 | +5.27% | ~$98,400 |
| 15m | −$236.06 | −0.24% | ~$98,400 |
| 5m | $329.88 | +0.33% | ~$100,000 |

All three land on ~$100k (the shortfall is rounding in the reported percentage).
But the scan was invoked as `--equity 250000`. So `backtest` is either ignoring
`--equity` or defaulting to $100k, and the two subcommands are not describing the
same system. **Verify which before reading any sizing-dependent number.**

For liquid ETFs at these sizes the P&L impact is probably small, but it means
"$250k" appears nowhere in the results.

### 2. The stop is barely in the sample

Derived from win rate and exit counts, assuming every SL exit is a loss:

| TF | Winners | Losers | Losers via SL | **Losers via "TP"** | Share of TP exits |
|---|---|---|---|---|---|
| 1h | 477 | 239 | 176 | 63 | 11.7% |
| 15m | 120 | 88 | 18 | **70** | **36.8%** |
| 5m | 376 | 217 | 12 | **205** | **35.3%** |

Two problems.

**The `TP` label hides a losing exit path.** On the short timeframes a third of
"take profit" exits are losses. That is the expected behaviour of a mean-reversion
target — if the exit is a re-cross of the middle band, the band can drift down to
meet the position and fill it below entry. It is not a bug, but reporting it as
`TP` makes the exit mix unreadable and untunable.

**On 5m the stop fired 12 times in 593 trades (2%).** Risk control is effectively
absent from that sample, which is why max drawdown reads a tame −0.81%. The 15m
run is not much better at 8.7%. Those drawdown figures describe a strategy that
exits on band re-cross and happens to have a stop attached.

The 1h run is the only one where the stop is genuinely exercised (176 of 716).

### 3. The 1h edge is real but untested in risk-off

`Risk-on bars 92.3%` over a window where SPY ran +66.13%. The 200-day filter was
on almost continuously, so the strategy has barely been observed in the regime the
stop exists for. Treat −1.17% max DD as a floor, not an estimate.

Opportunity cost is also stark: +5.27% over ~2.9 years (~1.8%/yr) against +66.13%
buy & hold. At 5.9% average exposure the return on deployed capital is far higher,
but the strategy is idle ~94% of the time, and `bars w/ 4 open 14.3%` means it is
also turning signals away while at capacity.

### 4. 15m and 5m have ~3 months of data

Both short-timeframe runs cover 2026-08-11 → 2026-11-02. Not enough to judge
either way, and not comparable to the 1h run.

Note: the 1h run spans ~1063 calendar days, which exceeds the commonly cited
~730-day yfinance cap for 60-minute bars. Either the cap is per-request and the
script chunks, or it caches. Worth confirming — it determines whether the 1h
history is reproducible from a cold cache.

### 5. Minor: the buy & hold baseline is inconsistent

The 15m and 5m runs cover the same stated period but report SPY buy & hold as
−1.12% and −1.48%. Probably first-to-last available bar differing per feed.
Small, but it means the benchmark is computed from the sample rather than from a
fixed date range.

## Open questions — need the source

1. **Are commissions and slippage modelled?** Decisive for 5m, where the average
   win is +0.20%. A cent or two per side plausibly erases it. Unanswerable from
   the output alone.
2. **Does `backtest` accept `--equity`?** See finding 1.
3. **What does `--apply` do?** Writes an order file, or hits a broker API? It was
   run live once with `--apply` and placed nothing, so the behaviour is still
   unobserved.

## Recommendations

1. **Move the live scan to 1h.** 15m is the one timeframe that lost money, and it
   is the one the scan was pointed at.
2. **Split the `TP` exit in reporting** into "target hit above entry" and "band
   re-cross below entry." One label currently conceals a losing exit.
3. **Print equity, costs and bar count in the backtest header**, so a run is
   self-describing and findings 1 and 4 cannot recur silently.
4. **Leave 5m alone** until costs are confirmed and the sample is longer.
5. **Do not cut IWM yet.** It is the worst symbol on both short timeframes
   (−$595.65 on 5m, −$316.10 on 15m) but positive on 1h (+$581.53), and the short
   runs are ~75 and ~31 trades over 3 months.

## Getting the source in here

`etf_bbmr.py` currently lives only at `~/Downloads/etf_bbmr.py` on a local
machine. It should be committed beside this file so the runs above are
reproducible and the open questions can be closed.

```
strategies/etf-bbmr/
  README.md      — this review
  etf_bbmr.py    — not yet committed
```

## Reproducing the runs

```bash
source ~/venvs/trading/bin/activate
export PYTHONWARNINGS=ignore          # silences the pandas 3.1 inplace warnings
python etf_bbmr.py backtest --tf 1h
```

The warning spam in the original session is yfinance 1.7.0 calling `inplace=` on
pandas 3.1.0, which deprecated it (PDEP-8). Cosmetic, and fixed upstream in
yfinance eventually; `PYTHONWARNINGS=ignore` is the cheap workaround.
