# Results — daily mean reversion

Hypotheses and decision rule were fixed in [PREREGISTRATION.md](PREREGISTRATION.md),
committed at `7a605bb` **before any daily bar was fetched**. No parameter was
changed after seeing a result.

**Data:** 20 symbols, 2011-01-03 → 2026-10-15, 79,054 daily bars,
split-adjusted, quality-gated (META correctly begins at its 2012 IPO; 346
synthesized pre-IPO bars dropped).

## Verdict

| | H1 RSI(2) | H2 3-bar daily |
|---|---|---|
| 1. excess > 0, CI excludes zero | **PASS** +22.0 bp, CI [+8.5, +35.0] | FAIL −7.0 bp, CI [−16.0, +2.0] |
| 2. holds on ETF set alone | **PASS** | FAIL |
| 3. deflated Sharpe ≥ 0.95 | **FAIL** — 0.942 | FAIL — 0.000 |
| 4. ≥300 trades, ≥20 months | **PASS** 1,175 / 162 | **PASS** 3,289 / 189 |
| **verdict** | **NO EDGE** (by 0.008) | **NO EDGE** |

## H1 — RSI(2) < 10 above the 200-day SMA

ETF set (primary, 1,175 trades, 162 months, median hold 4 days):

| | bp |
|---|---|
| raw mean return | +44.6 |
| drift benchmark (arbitrary same-length entry) | +22.6 |
| **excess** | **+22.0** (+0.169 daily σ) |

Half the raw return is market drift. That is why the metric was registered as
drift-adjusted: at face value this looks like a 72.7% win rate and +44.6 bp a
trade, and half of that is available by entering on any day at random.

Per-symbol excess (bp), ETF set — **9 of 10 positive**:

```
SPY +26   QQQ +17   IWM +44   DIA +17   XLF +28
XLE +30   XLK +32   XLV +19   XLI +25   XLP −12
```

CI on excess under three clusterings:

| clustering | 95% CI (bp) | P(≤0) | blocks |
|---|---|---|---|
| symbol+date (**as registered**) | [+8.5, +35.0] | 0.001 | 1,175 |
| date (market-wide moves) | [+0.6, +42.4] | 0.022 | 613 |
| month | [−2.2, +44.6] | 0.041 | 162 |

The registered clustering is the weakest of the three — it treats each trade
as its own block, which understates uncertainty when many symbols trigger on
the same day. Registering it that way was a methodological mistake. The
stricter clusterings are reported alongside and used **only to qualify** the
result, never to upgrade it.

Large caps gave +42.0 bp excess, significant under all three clusterings —
but that set is survivorship-biased in exactly the direction that flatters a
long-only mean-reversion test, which is why the registration made it
non-deciding.

### Why this is a candidate and not an edge

It fails condition 3 by 0.008, and the CI includes zero under month
clustering. Both say the same thing: real-looking, not established.

Two honest caveats on the deflated Sharpe itself: with only 2 registered
trials, `V[SR]` is estimated from 2 points and is a crude input, so 0.942 is
not a precise number. And the deflation is mild by construction — which is
the reward for registering two hypotheses instead of sweeping 144.

**The result is not being tuned.** A threshold, holding period, or universe
that pushes it over 0.95 would be a 3rd, 4th, 5th trial found by looking, and
the registration fixed the count at 2. Promoting H1 requires **fresh data** —
a different period or a point-in-time universe — under a new pre-registration.
That is the only legitimate next step for it.

## H2 — 3-bar pattern on daily bars

ETF set: 3,289 trades, −7.0 bp excess, CI [−16.0, +2.0], 8 of 10 ETFs
negative, 37.2% win rate against a 38.5% breakeven bracket.

```
SPY +1   QQQ −4   IWM −4   DIA −14   XLF −6
XLE +2   XLK +0   XLV −25   XLI −4   XLP −18
```

This closes the question the 5-minute study opened. That study found the
pattern carries no directional information on 5-minute bars across 11
instruments; on 15.8 years of daily bars across 20 instruments it carries
none either, with the break-even stop already removed and a pure bracket in
its place. The pattern is not timeframe-dependent — it is uninformative.

## What was learned about the method

The drift benchmark was the load-bearing control. Without it H1 reads as
+44.6 bp and H2's large-cap set reads as +14.5 bp, both apparently
profitable. Drift-adjusted, H1 halves and H2's becomes insignificant.

Any long-only daily study over 2011–2026 that reports raw returns is
measuring a rising market.

## Reproduce

```bash
python3 daily.py /path/to/daily/*.csv
```

No flags. The parameters are the registered ones, and a flag to change them
would be a flag to go looking for a result.
