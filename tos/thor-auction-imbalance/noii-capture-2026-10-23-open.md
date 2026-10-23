# Opening-cross NOII capture — 2026-10-23, 09:28–09:29 ET

Live sample of all 23 universe symbols taken during the opening-cross
dissemination window, to decode `imbalance_side` and measure coverage.
Snapshot stamps run 09:28:24 → 09:29:27 ET, so these are sequential reads
across the window rather than one simultaneous slice.

| Symbol | side | unpaired | paired | ref | near | near − ref |
|---|---|---|---|---|---|---|
| NVDA | 3 | 91,848 | 894,091 | 210.87 | 210.00 | −0.87 |
| AVGO | 3 | 9,399 | 183,014 | 321.10 | 321.00 | −0.10 |
| LRCX | 3 | 16,340 | 142,272 | 226.65 | 226.15 | −0.50 |
| KLAC | 3 | 14,201 | 87,772 | 147.07 | 147.00 | −0.07 |
| ASML | 3 | 2,258 | 14,911 | 1551.08 | 1550.00 | −1.08 |
| ADI | 3 | 321 | 22,876 | 381.77 | 381.72 | −0.05 |
| QQQ | 2 | 24,445 | 139,143 | 702.45 | 703.50 | +1.05 |
| SMH | 2 | 7,965 | 30,252 | 522.91 | 523.58 | +0.67 |
| SOXX | 2 | 5,991 | 24,718 | 475.04 | 475.54 | +0.50 |
| MRVL | 2 | 4,203 | 125,351 | 223.74 | 224.09 | +0.35 |
| ARM | 2 | 4,372 | 44,432 | 210.30 | 211.01 | +0.71 |
| INTC | 2 | 8,070 | 403,406 | 86.00 | 86.00 | 0.00 |
| AMD | 1 | 0 | 129,411 | 510.50 | 510.50 | 0 |
| MU | 1 | 0 | 123,296 | 861.71 | 861.71 | 0 |
| QCOM | 1 | 0 | 95,915 | 171.61 | 171.61 | 0 |
| TXN | 1 | 0 | 35,144 | 277.72 | 277.72 | 0 |
| AMAT | 1 | 0 | 64,195 | 374.55 | 374.55 | 0 |
| SMCI | 1 | 0 | 118,217 | 33.70 | 33.70 | 0 |
| ON | 1 | 0 | 38,699 | 72.50 | 72.50 | 0 |
| NXPI | 1 | 0 | 13,861 | 235.36 | 235.36 | 0 |
| SPY | 1 | 0 | **2** | 760.64 | 760.64 | 0 |
| TSM | 4 | 0 | 0 | 0.0 | 0.0 | — |
| IWM | 4 | 0 | 0 | 0.0 | 0.0 | — |

## `imbalance_side` decoded

| Code | Meaning | Evidence |
|---|---|---|
| `1` | no imbalance | 9/9 names have `unpaired = 0` and `near == ref` |
| `2` | **buy** imbalance | 6/6 have `near ≥ ref`; 5 strictly above, INTC tied |
| `3` | **sell** imbalance | 6/6 have `near < ref`, no exceptions |
| `4` | no data for this symbol | all fields zero, `var_indicator` `0` not `10` |

Twelve directional samples split 6 buy / 6 sell, and the sign of
`near − ref` separates the two codes with zero contradictions. INTC's exact
tie is consistent with a buy imbalance against a book deep enough at 86.00
to absorb it, not a counterexample.

This supersedes the weaker guess recorded earlier from two same-direction
samples. Note that QQQ carried `side 3` on 2026-10-22 and `side 2` today —
the code tracks the day's book, so a single symbol sampled twice proves
nothing about the encoding. Only the cross-sectional contrast does.

## Coverage follows listing venue

Nasdaq NOII covers Nasdaq-listed securities, and the sample matches that
exactly:

- **Nasdaq-listed** — all 20 equities plus QQQ, SMH and SOXX returned live
  records. The ETFs are covered because they are Nasdaq listings, not
  because ETFs generally work.
- **NYSE / NYSE Arca** — `TSM` (NYSE) and `IWM` (Arca) returned `side 4`,
  every field zero, `var_indicator 0`. Nothing is published.
- `SPY` (Arca) is the trap: it returned a *populated* ref price of 760.64
  with `side 1`, which looks like a valid "no imbalance" reading. It is
  really 2 paired shares — noise from Nasdaq's own book, while SPY's actual
  opening auction happens on Arca where this feed cannot see it. A naive
  reader would record "SPY: no imbalance at 760.64" and be wrong.

So `universe.txt` splits: 20 symbols usable for auction imbalance, and
`SPY`, `IWM`, `TSM` must be excluded — SPY explicitly, because it fails
loudly enough to look like success.

## What the capture showed about the open

The semis split against their own ETFs. The big components carried sell
imbalances — NVDA most of all, 91,848 unpaired to sell with the indicative
cross 0.41% below reference — while QQQ, SMH and SOXX all carried buy
imbalances with indicative prices above reference. MRVL, ARM and INTC leaned
buy against that.

Worth noting only as a sample of what the field combination looks like on a
real morning. One morning is not a pattern, and nothing here was tested
against what the tape then did.
