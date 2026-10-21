# Strategy design — what the studies in this repo actually establish

Three pre-registered or attributed studies, zero established edges. That is
the honest status, and the useful output is not a strategy but a set of
design constraints — each one derived from a number measured here, not from
somebody's opinion about trading.

| study | result |
|---|---|
| [THOR 3-bar, 5-min](thor-3bar-reversal/), 11 instruments × 165 sessions | entry signal carries no information |
| [THOR 3-bar, daily](daily-mean-reversion/), 20 symbols × 15.8 years | −7.0 bp drift-adjusted excess |
| [RSI(2) daily](daily-mean-reversion/), pre-registered | +22.0 bp, fails deflated Sharpe by 0.008 |
| [ORB QQQ, out-of-sample](orb-oos/), 909 trades | edge real, needs ~32,490 trades to verify |

---

## 1. Breadth before signal

**The constraint most strategies die on, and almost nobody checks first.**

The ORB test measured a per-share PnL standard deviation of $2.63 against a
mean of $0.0362. Establishing an effect that size at 80% power needs
**≈32,490 trades**. One instrument trading once a day generates ~250 a year,
so the required sample is ~129 years.

No filter fixes this. No longer backtest fixes this.

**CORRECTION (measured after this was first written).** I originally wrote
that "the only lever is more simultaneous instruments." That is wrong. The
required sample is

```
n  ~  (2.49 * SD / mu)^2        and what you actually have is n_effective
```

so there are **three** levers, not one — raise `mu`, cut `SD`, or raise
`n_effective` — and breadth only touches the last.

**Exit geometry is comparable to breadth, and it is free.** Measured on the
QQQ ORB, 909 trades, varying only the target:

| target | mean R | SD R | win% | n for a 0.10R edge | n for its *own* edge |
|---|---|---|---|---|---|
| 1R | −0.070 | 1.026 | 49.2 | **653** | 1,325 |
| 2R | −0.043 | 1.424 | 35.0 | 1,257 | 6,770 |
| 3R | −0.006 | 1.699 | 30.1 | 1,790 | 547,933 |
| 5R | +0.078 | 2.110 | 27.1 | 2,762 | 4,481 |
| 10R | +0.094 | 2.465 | 25.4 | 3,766 | 4,234 |
| hold-to-close | +0.167 | 3.160 | 25.2 | 6,191 | **2,221** |

Tightening the target cuts SD 3.1× and the sample needed for a *fixed* 0.10R
edge by **9.5×** — against 20× for going from 1 to 20 instruments. Same order
of magnitude, no extra data required.

**But you cannot simply tighten the target, because for a momentum strategy
the edge lives in the same tail as the variance.** Look at the mean column:
it falls monotonically as the target tightens, and goes *negative* at 1R and
2R. Truncating the right tail removes the variance and the edge together. For
detecting *this strategy's own* edge, hold-to-close (n=2,221) beats a 10R
target (n=4,234) — the mean grows faster than SD.

So the lever is the **ratio** `mu/SD`, not SD alone. Testing several exit
geometries and keeping the best `mu/SD` is cheap and worth doing first; a
blanket "add a tight target to cut SD" is wrong and would have destroyed the
only positive configuration here.

**And breadth delivers less n_effective than it looks.** Same-day positions
are correlated, so they must be clustered. How much it costs depends on the
design:

- A **fixed diversified basket with intraday-staggered entries** (my 11-symbol
  3-bar data, 10,671 trades over 138 sessions): day-clustered SE is only
  **1.13×** the iid SE, so n_effective ≈ 8,363 of 10,671 — a 22% haircut.
- A **top-N-same-signal cross-section** (e.g. the day's 20 highest
  relative-volume names) is far worse, because every name is selected by the
  same signal in the same market-wide move. An independent replication of that
  design reported a day-clustered t of **1.08** on 5,017 trades, with a 95% CI
  straddling zero.

Breadth is **necessary but not sufficient**, and its value falls as the
same-day selections become more correlated. Always report the day-clustered
interval, never the per-trade one.

So: before writing any signal code, compute how many trades the design can
possibly generate per year, and what per-trade variance you expect. If the
required sample exceeds the available one, the strategy is unverifiable by
construction — stop there.

This is why Zarattini's "stocks in play" paper runs the same ORB idea across
7,000+ names. It is less a different strategy than the same one with a
tractable sample size.

## 2. Measure the signal naked, before anything else

The 3-bar attribution measured the entry through a pure bracket, gross of
costs: **−0.025 R, and +0.003 R inverted.** Flat both ways.

That single number explained every other result: no filter earned its place,
and all 144 grid cells lost. **A filter selects signals; it cannot improve
them.** If the naked signal's interval contains zero, there is nothing for a
filter to select and every downstream experiment is wasted.

Run `sweep.py --mode attribution` before tuning anything.

## 3. Long-only daily results must be drift-adjusted

The RSI(2) study raw: **+44.6 bp** a trade at a 72.7% win rate. Drift-adjusted
against the mean same-length forward return in the same instrument:
**+22.0 bp.** Half the apparent edge was available by entering on any random
day.

Any long-only study over 2011–2026 that reports raw returns is measuring a
rising market. The benchmark is not zero; it is an arbitrary entry of the
same length in the same instrument.

## 4. The benchmark is the alternative you'd actually take

ORB out-of-sample: annualised Sharpe **+0.414**. Buy-and-hold QQQ over the
identical window: **+1.351**. P(strategy − B&H ≤ 0) = 0.905.

A strategy with a positive, real, cost-surviving edge still failed, because
the honest comparison is not "better than nothing" but "better than the thing
I would otherwise do." Every strategy test needs its do-nothing benchmark
computed over the identical window.

## 5. Costs scale against stop width, not notional

The 3-bar config priced commission at 0.01% of notional — $0.07/share on SPY.
Against a 1.25 ATR stop (~$0.82) that is **0.18 R per trade**, and total costs
were 0.23 R. A tighter stop does not reduce risk; it multiplies the cost drag.

Express every cost in R before deciding whether the geometry is viable. A
1R:2R bracket needs a 38.5% win rate to break even before costs, and more
after.

## 6. Two exit rules that measurably destroy money

- **Break-even stops: −0.142 R per trade**, the largest single effect in the
  3-bar system and negative. It surrenders the remaining excursion's option
  value while keeping full losers, and dragged the win rate from 37.5% to
  17.2%. With no edge it is strictly negative. Do not use one.
- **Far targets on skewed brackets.** The ORB's 10R target hit on 22 of 909
  trades (2.4%). 673 were stops. The mean is then a tail statistic, which is
  what made the variance unmanageable in §1.

## 7. Count trials, and write the rules down first

Across these studies: 144 grid cells, 9 ablations, a cost sweep, an inversion
test. Any "discovery" made after that search inherits the trial count, which
is why later work moved to pre-registration on untouched data.

The deflated Sharpe makes the cost explicit. With 144 trials the winner needed
to clear E[max SR] = +0.213 by luck alone; with 2 registered trials it needed
+0.045. **Registering two hypotheses instead of sweeping 144 is worth about
0.17 of Sharpe** — a bigger effect than most filters.

Commit the pre-registration before fetching the data, so the ordering is
checkable in git history rather than asserted.

## 8. Published does not mean tradeable — but also does not mean false

McLean & Pontiff (2016) on 97 predictors: returns 26% lower out-of-sample,
58% lower post-publication. Jacobs & Müller find no reliable post-publication
decline outside the US, so the magnitude is contested.

The ORB test is a concrete instance, and it cuts against the simple decay
story: the gross edge **grew** out-of-sample ($0.070 → $0.0859/share) and
break-even slippage **improved** (2.2¢ → 3.46¢). The paper was not wrong. The
effect was simply too small relative to its variance for anyone trading one
instrument to use.

So read published research as a source of *mechanisms* to test, never as
evidence you can skip testing. And when a test fails, distinguish "the effect
is absent" from "the effect is real and unusable" — they imply completely
different next moves.

---

## What this implies for what to build next

The constraints above rule out most of what retail systematic traders
actually build. What survives them:

- **Cross-sectional, many instruments at once.** §1 is non-negotiable; this
  is the only way to a verifiable sample.
- **A signal with a stated mechanism** — who is on the other side, and why
  they keep taking it. Robot Wealth's framing, and the honest answer for the
  3-bar pattern was "nobody, it's noise."
- **Wide stops relative to costs**, no break-even stop, targets close enough
  that they actually fill.
- **Pre-registered, on data not yet touched**, with the do-nothing benchmark
  computed over the same window.

Concretely, the one candidate still alive here is **RSI(2) daily**, which
passed three of four registered conditions and missed the deflated Sharpe by
0.008. The legitimate way to promote it is a new pre-registration on data this
study never saw — a different period, international names, or a point-in-time
universe — with the universe fixed before fetching. Not a tuned threshold.

## What this does not tell you

None of this says an edge is impossible, and none of it is a result about
markets in general. Four negative or inconclusive studies on a handful of US
instruments over 2011–2026 is a small evidence base. The constraints are
sound because they are arithmetic; the *conclusions about these specific
strategies* are only as good as the samples behind them, each of which is
documented with its own limitations.
