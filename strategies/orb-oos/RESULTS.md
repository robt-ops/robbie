# Results — ORB out-of-sample, QQQ 2023-03 → 2026-10

Rules and decision rule were fixed in [PREREGISTRATION.md](PREREGISTRATION.md),
committed at `b157748` **before any out-of-sample bar was fetched**. Nothing
was changed after seeing a result.

**Data:** QQQ 5-minute bars, 914 sessions, 2023-03-01 → 2026-10-20, regular
hours, quality-gated (0 bars flagged). 909 trades, 5 doji days skipped.

## Verdict: does not replicate

| condition | result |
|---|---|
| 1. mean PnL/share > 0, CI excludes zero | **FAIL** +$0.0362, CI [−0.1316, +0.2058] |
| 2. Sharpe > 0, CI excludes zero | **FAIL** +0.414, CI [−0.654, +1.339] |
| 3. beats buy-and-hold QQQ | **FAIL** diff CI [−2.421, +0.496] |
| 4. ≥300 trades | **PASS** 909 |

Worst year holds 54.0% of net PnL — under the 60% flag, so not a single-year
artifact.

## But the interesting part is *why* it fails

**The gross edge did not decay.** It got slightly larger:

| | gross edge |
|---|---|
| paper / replication, in-sample (2016–Feb 2023) | $0.070/share |
| **this test, out-of-sample (Mar 2023–Oct 2026)** | **$0.0859/share** |

Break-even entry slippage is **3.46¢/share** here against the replication's
2.2¢ — i.e. *more* robust to costs out-of-sample, not less. On the
publication-decay story (McLean & Pontiff: 26% lower out-of-sample, 58% lower
post-publication), this is a non-result. The signal is still there.

**It fails on variance, not on decay.** Per-share PnL has a standard
deviation of **$2.6275**. Against a mean of $0.0362 that is a t-statistic of
about **0.41**. The sample size required to establish an effect of the
observed size, at 80% power:

> **≈32,490 trades.**

At one trade per session that is roughly **129 years** of trading QQQ. The
strategy cannot be verified in a human career, let alone a backtest.

**And it loses to doing nothing.** Over the identical window:

| | annualised Sharpe |
|---|---|
| ORB strategy | +0.414 |
| **buy & hold QQQ** | **+1.351** |

P(strategy − B&H ≤ 0) = 0.905. Final equity $32,959 from $25,000 over 3.6
years — about 2.2% annualised, while QQQ compounded far faster. The 2026
portion of the sample lost money (−36% of net PnL), which is consistent with
the end-of-sample decay the replication also flagged.

## What this actually establishes

Not "the paper is wrong." The paper's effect is real and still present. The
finding is sharper and more useful than that:

**The effect is too small relative to its variance to be verified or
exploited by anyone trading one instrument once a day.** A 1R-risk,
10R-target bracket produces a payoff distribution so skewed (673 stops, 214
closes, 22 targets) that the mean is swamped by the tail. You would need a
century of data to know whether you had an edge, and meanwhile holding the
index beat it three to one on Sharpe.

## The design conclusion

This is the generalisable part, and it is not an opinion — it falls out of the
arithmetic above.

**Sample size is a design parameter, not an afterthought.** If a strategy
trades one instrument once a day, its maximum achievable sample is ~250
trades a year. With per-trade variance like this, that is permanently
insufficient. The fix is not a better filter or a longer backtest; it is
**more simultaneous instruments.**

Which is, notably, exactly what Zarattini's *other* paper does — the
"stocks in play" version runs the same idea across 7,000+ US stocks and
selects the day's most unusually active names. That is not a different
strategy so much as the same strategy with a tractable sample size.

So: judge a candidate strategy by the sample it can generate *before*
backtesting it. Breadth first, signal second.

## Reproduce

```bash
python3 orb.py /path/to/qqq_5m.csv
```

No flags. The rules are the paper's.

## Limitations

- One instrument, as in the paper. The cross-sectional version is untested here.
- Vendor 5-minute bars; the 09:35 open is assumed executable.
- Flat per-share slippage. Real slippage would be worst on the fast opens
  this strategy trades, so the break-even figure is optimistic.
- The NQ confirmation filter was excluded by pre-registration (reason
  recorded there: in-sample selection, 76% of its PnL from 2022 alone).
