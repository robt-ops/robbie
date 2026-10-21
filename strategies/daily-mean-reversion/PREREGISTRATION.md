# Pre-registration — daily mean reversion

**Written and committed before any daily bar was fetched or examined.**
Git history is the evidence; check that this file's commit precedes the
commit that adds any data or results.

The 5-minute study in `../thor-3bar-reversal/` searched its data hard: 144
grid cells, 9 ablations, a cost sweep, an inversion test. Any new hypothesis
tested on *that* data inherits those trials. So this study uses a different
timeframe, a different universe, and fixes every rule in advance.

## Why these two hypotheses

Not chosen by searching. H1 has published prior support; H2 extends an
existing finding to a timeframe it has not been tested on.

### H1 — RSI(2) mean reversion, Connors' specification

The 5-minute work noted that RSI(2)'s original edge was documented on
**daily** bars with a long-term trend filter, and that applying it to 1–5
minute charts mostly captures noise. This tests it where the support is.

- **Universe:** as below.
- **Filter:** close > 200-day SMA (long-term uptrend only).
- **Entry:** RSI(2) < 10 at the close → buy at the **next day's open**.
- **Exit:** RSI(2) > 70 at a close → sell at the **next day's open**;
  hard exit after **10 trading days** held.
- **Direction:** long only. No stop (Connors' version has none).
- **Costs:** 1 bp per side.

### H2 — THOR 3-bar reversal on daily bars

Same pattern as the 5-minute study, on a timeframe not yet tested. The
break-even stop is **omitted** because the 5-minute attribution measured it
at −0.142 R per trade; carrying forward a component already shown harmful
would not be a fair test.

- **Signal:** the existing `backtest.py` pattern, filters stripped.
- **Exit:** pure bracket, 1.25 ATR stop / 2.00 ATR target, no break-even
  stop, no time stop.
- **Direction:** long and short.
- **Costs:** 1 bp per side.

## Universe, fixed now

**Primary — ETFs** (least exposed to survivorship selection):
`SPY QQQ IWM DIA XLF XLE XLK XLV XLI XLP`

**Secondary — large caps** (survivorship-biased; reported separately and
never pooled with the primary set):
`AAPL MSFT NVDA AMZN GOOGL META JPM JNJ XOM WMT`

Chosen for liquidity and sector spread, not for past performance — but
selecting today's large caps and testing backwards still biases a long-only
mean-reversion test upward, because the survivors are the ones that reverted
up. That is why the ETF set is primary and decides the outcome.

**Period:** the longest daily history the data source returns, target ≥10
years. Split-adjusted. The period is whatever is available; it is not chosen
after seeing results.

## Primary metric: drift-adjusted excess return

A long-only daily strategy over a rising market looks profitable from market
drift alone. The metric must remove that, so raw return is **not** the
primary metric.

For each trade on symbol *s* held *h* trading days:

```
excess = trade_return − E[h-day forward return for s over the sample]
```

where the benchmark is the mean *h*-day forward open-to-open return across
**every** day in that symbol's sample. This controls for both drift and
holding period: it asks whether the entry timing beat an arbitrary day's
entry of the same length in the same instrument.

Reported in basis points and divided by the symbol's realized daily
volatility, so instruments are comparable.

Secondary, reported but not deciding: raw mean return, win rate, Sharpe per
trade, and the unadjusted buy-and-hold comparison.

## Decision rule, fixed now

H1 or H2 counts as an edge only if **all** of these hold:

1. Pooled drift-adjusted excess return > 0, with a 95% block-bootstrap CI
   **excluding zero**, clustering on symbol+date.
2. It holds on the **ETF (primary) set on its own** — not only when the
   survivorship-biased large caps are included.
3. Deflated Sharpe ≥ 0.95 at the trial count below.
4. ≥300 trades and ≥20 distinct months represented.

Failing any of the four is a negative result and will be reported as one.

## Trial count: 2

Exactly two hypotheses, one parameter set each. **No tuning.** No threshold
sweeps, no alternative exits, no universe changes, no period changes. If a
hypothesis fails at its registered parameters, it has failed; a nearby
parameter set that works is not a finding and will not be reported as one.

Any later exploration is a separate, clearly-labelled exploratory analysis
with its own trial count, and cannot promote a failed hypothesis.

## Known limitations, acknowledged in advance

- Survivorship bias in the secondary set (mitigated by the ETF set deciding).
- No point-in-time index membership, so even the ETF set reflects today's
  methodology.
- Open-to-open fills assume the open is executable; for liquid ETFs this is
  reasonable, and it is the same discipline as the 5-minute study.
- A single historical period, which 10 years of mostly rising equity markets
  does not make regime-diverse.
