# THOR / London Strategic Edge pipeline — working context

State of the live pipeline as of 2026-10-23. **All of this lives on the Mac**,
at `~/Documents/lse-market-data`, and is not reachable from a cloud session —
Desktop Commander there resolves to the cloud container (`isMacOS: false`,
`containerName: "vm"`), not the Mac. Editing or backing up these scripts
requires Claude Code running on the Mac itself.

## Environment

| Item | Value |
|---|---|
| Project | `~/Documents/lse-market-data` |
| Venv | `~/Documents/lse-market-data/.venv` |
| Package | `lse-data`, installed and working |
| Auth | `~/.lse/config.json` |

The LSE HTTP API (`api.londonstrategicedge.com`) is reachable from the Mac but
**blocked from cloud sessions** — the agent proxy refuses the CONNECT tunnel
with 403. Any work against it has to run on the Mac.

## Pipeline

**1. Live WebSocket stream** — SPY, QQQ, NVDA, AMD, TSM. price/bid/ask confirmed.

**2. `thor_lse_collector.py`** → `lse_ticks.csv`, `lse_1m_bars.csv`
1-minute indicators: EMA 9, EMA 20, EWO, MACD + signal/histogram, ATR.

**3. `thor_lse_context.py`** → `lse_vwap_volume.csv`, `options_snapshots/`
Regular-session VWAP for 09:30–16:00 ET off LSE 1-minute OHLCV. NVDA and AMD
options snapshots work; **TSM options return no rows.**

**4. `thor_dashboard.py`** — reads the CSVs, refreshes every 2s.
Score bands: 75–100 bullish, 26–74 neutral, 0–25 bearish.

## Standing rules

- Do not overwrite or replace a working collector/context script without
  creating a backup first.
- Options activity is **confirmation behind price/technical structure**, never
  proof of direction on its own.
- Missing inputs are not a signal. TSM showing blank fields and score 50
  NEUTRAL is expected behaviour when its 1-minute indicators have not
  populated — not a bearish or bullish read.

## Planned dashboard v2

75% technical, 25% options confirmation.

- Technical: VWAP, EMA 9/20, EWO, MACD, quote position/spread, ATR/context
- Options: call vs put volume, call vs put premium, near-ATM volume, near-ATM premium
- Classifications: A+ LONG, A LONG, LEAN LONG, WAIT, LEAN SHORT, A SHORT, A+ SHORT

### Three design issues to settle before building v2

**1. Weight renormalization, or missing data becomes bearish.** This is the
TSM rule again, in a place where it is easy to violate by accident. If the
options component is scored `0` when no options rows exist, the blend turns a
data gap into downward pressure: a technical read of 80 becomes
`0.75 × 80 + 0.25 × 0 = 60`, dropping from a LONG band to neutral purely
because options data was absent. TSM options return no rows *today*, so this
fires on a live symbol immediately. Renormalize over available components
instead — with options missing, the score is the technical score at weight
1.0 — and surface a "technical only" marker so the degradation is visible
rather than silent. Same treatment for any absent technical input.

**2. Name the score axis, because two incompatible 0–100 scales now exist.**
The dashboard score is *directional*: 0 bearish, 50 neutral, 100 bullish. The
THOR Auction Score in `04-thor-auction-score.ts` is deliberately
*direction-neutral*: 0–100 conviction, with LONG/SHORT in its own column. A
reading of 20 therefore means "bearish" in one and "weak conviction" in the
other. Give them distinct names before they ever appear in the same view.

**3. A+ needs an agreement gate, not just a higher threshold.** A single
directional axis cannot separate "weakly bullish, every input agreeing" from
"strongly bullish, inputs conflicting" — both land mid-high. If A+ is meant
to denote conviction, band thresholds alone will not deliver it. Gate the
A+/A/LEAN distinction on input agreement on top of the score, the way
`alignPts` works in the TOS score, rather than carving the same axis finer.

## TSM is the weakest symbol in this universe, on both data paths

Worth knowing before tuning anything around it:

- Its options snapshots return no rows (this pipeline).
- Its 1-minute indicators populate slowly, giving blank fields and a default
  50 NEUTRAL (this pipeline).
- It is NYSE-listed, so Nasdaq NOII publishes nothing for it — `side 4`, all
  fields zero (see `noii-capture-2026-10-23-open.md`).

SPY shares the third problem: NYSE Arca listing, no usable NOII, and it fails
in the dangerous direction by returning a populated reference price on 2
paired shares of noise. So of the five dashboard symbols, NVDA, AMD and QQQ
are fully covered across both paths; SPY and TSM are degraded on the
imbalance path, and TSM on this one too.
