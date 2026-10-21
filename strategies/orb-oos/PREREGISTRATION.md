# Pre-registration — out-of-sample test of the Zarattini/Aziz QQQ ORB

**Committed before any out-of-sample bar was fetched.** Git history is the
evidence.

## Why this test, and why it is worth doing

Opening Range Breakout was on the original strategy list. Unlike the rest of
that list, it has actual published research behind it, *and* an independent
replication that stress-tested it for costs:

- **Zarattini & Aziz**, "Can Day Trading Really Be Profitable?"
  (SSRN 4416622) — QQQ/TQQQ, Jan 2016 → Feb 2023, reports Sharpe 1.12.
- **Independent replication** (`giovannibrusco/zarattini-2023-orb-qqq`) —
  reproduces Sharpe 1.06 on 1,775 trades, gross edge **$0.070/share**, and
  finds net PnL crosses zero at about **2.2¢/share** of entry slippage
  against a QQQ spread of roughly 1¢. Its bootstrap Sharpe CI was
  **[0.05, 1.41]** against buy-and-hold's **[−0.03, 1.47]** — heavily
  overlapping, so an edge *over buy-and-hold* was never established.

The replication names its own highest-value next step: **out-of-sample
testing for 2023–2026.** That window postdates both the paper's sample and
the replication. Nobody appears to have run it.

This is a better test than anything self-invented, for three reasons:

1. **The rules are not mine.** They were fixed by someone else, published,
   before this data existed. There is no path by which I fitted them.
2. **The window is genuinely out-of-sample** — it postdates the paper
   (Feb 2023), so publication-driven decay, if any, should show up in it.
   McLean & Pontiff (2016) find published predictors return 26% less
   out-of-sample and 58% less post-publication across 97 anomalies.
3. **Trial count is honestly 1.** One strategy, one parameter set, taken
   from the literature.

## Rules — taken verbatim from the paper's specification, not chosen by me

- **Instrument:** QQQ, 5-minute bars, regular trading hours only.
- **Direction:** the 09:30–09:35 bar. Close > open → long. Close < open →
  short. Close == open (doji) → no trade that day.
- **Entry:** the 09:35 open (the second 5-minute bar's open).
- **Stop:** long → the low of the 09:30–09:35 bar; short → its high.
  `R = |entry − stop|`.
- **Target:** 10R.
- **Time exit:** flat at the session's last bar close.
- **Position sizing:** `shares = min(0.01 × equity / R, 4 × equity / entry)`,
  the second term respecting the 4× day-trading buying-power cap.
- **Starting equity:** $25,000.
- One trade per session, no overlap.

### Costs

**Primary cost model** (the replication's stress model, and the one the
verdict is judged on): **$0.02/share on entry, plus an additional
$0.04/share when the exit is a stop.**

Reported alongside, not deciding: zero-cost gross edge, and the break-even
entry slippage in ¢/share. Reporting the same fixed strategy under several
cost assumptions is sensitivity analysis, not a search — no rule changes
between them.

### Explicitly NOT tested

The **NQ confirmation filter** (requiring the 09:25 NQ futures bar to agree
with the QQQ opening bar). Excluded deliberately, and recorded here rather
than quietly dropped: the replication found 76% of that filter's net PnL came
from **2022 alone**, with losses in 2017, 2020 and early 2023. That is a
volatility-regime effect, not a structural one, and its parameters were
selected in-sample. Adding it would be a second trial chasing the weaker half
of the evidence.

## Primary metric

**Mean PnL per share**, net of the primary cost model — the same unit the
replication used, so the numbers are directly comparable to its $0.070/share
gross figure.

Secondary: Sharpe per trade, total net PnL on the stated sizing, win rate,
exit-reason mix, max drawdown, break-even slippage, and per-year PnL
concentration (because the replication's filtered edge failed that test).

## Decision rule, fixed now

The strategy replicates out-of-sample only if **all** of these hold:

1. Mean PnL/share > 0 net of the primary cost model, with a 95%
   block-bootstrap CI (blocks = sessions) **excluding zero**.
2. Sharpe per trade > 0 with a bootstrap CI excluding zero.
3. **It beats buy-and-hold QQQ over the identical window** on a bootstrap
   comparison of Sharpe — the test the replication could not pass in-sample.
   A day-trading strategy that merely matches holding the index has not
   earned its execution risk.
4. ≥300 trades.

Plus one reported-but-not-deciding check: **no single calendar year may
account for >60% of net PnL.** If it does, the result is a regime effect and
will be labelled one, whatever conditions 1–4 say.

Failing any of 1–4 is a negative result and will be reported as one.

## Power, acknowledged in advance

The replication's gross edge is $0.070/share with a t-stat of 1.79 on 1,775
trades — i.e. **the original result is itself not significant at 5%.** An
out-of-sample window of roughly 900 sessions has less power again. If this
test returns "no edge", that is partly a power statement and will be said
plainly rather than dressed up as a refutation. The required sample size for
the observed effect will be computed and reported.

## Known limitations

- Vendor 5-minute bars, not tick data; the open is assumed executable.
- Flat per-share slippage, where real slippage depends on the opening
  auction's liquidity and would be worst on exactly the fast days this
  strategy trades.
- A single instrument. QQQ only, as in the paper.
- The window includes whatever regimes 2023–2026 happened to contain, which
  is not a controlled variable.
