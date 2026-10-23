# Closing-cross NOII capture — 2026-10-23

Two samples of the 20 usable universe symbols across the closing-cross
window (SPY, IWM and TSM excluded — see `07-noii-data-path.md`).

| Sample | Stamps | Cadence | Indicative prices |
|---|---|---|---|
| 1 | 15:52:10 – 15:52:40 ET | 10 seconds | **not published** (`0.0`, `var_indicator 0`) |
| 2 | 15:56:37 – 15:57:08 ET | 1 second | published |

The closing cross mirrors the opening cross's two-phase structure: a
10-second early phase carrying share counts only, then a 1-second phase once
the indicative prices begin publishing. That is why sample 1 could not be
used to check the direction decode — there was no near price to compare
against the reference — and why a second sample was needed.

## Both unknown enums are now resolved

**`imbalance_side` holds on `PRE_CLOSE`.** All 20 sample-2 records are
consistent with the opening-cross decode: `2` = buy with `near >= ref`,
`3` = sell with `near <= ref`, `1` = no imbalance with zero unpaired shares
and `near == ref`. Zero violations. The encoding is not window-specific.

**`imbalance_var_indicator` decodes as the deviation of the near price from
the reference price:**

```
var_indicator = 10                        when |near - ref| / ref  <  1%
              = floor(|near - ref| / ref * 100)   otherwise
```

Matched on all 20 records, including both symbols that bracket the 1%
threshold — NXPI at 0.92% reads `10`, SMCI at 1.12% reads `1`. Those two
straddling the boundary are what make this a decode rather than a guess.

| Symbol | deviation | `var_indicator` |
|---|---|---|
| ADI | 4.04% | `4` |
| AMAT | 2.79% | `2` |
| AVGO | 1.42% | `1` |
| ASML | 1.37% | `1` |
| MRVL | 1.28% | `1` |
| SMCI | 1.12% | `1` |
| NXPI | 0.92% | `10` |

This matches Nasdaq's documented variance indicator, where `L` denotes a
deviation under 1% and the digits `1`–`9` denote whole-percent bands. Webull
encodes `L` as `10`. A `0` means the indicative price is not published yet,
which is the entire early phase.

## The finding that constrains how this data can be used

**Nine of twenty symbols changed direction between 15:52 and 15:57.**

| Symbol | 15:52 | 15:57 |
|---|---|---|
| INTC | SELL 961,392 | BUY 30,859 |
| NVDA | BUY 238,570 | SELL 694,149 |
| KLAC | SELL 460,053 | BUY 27,020 |
| QCOM | SELL 212,134 | BUY 44,777 |
| QQQ | SELL 45,302 | none 0 |
| TXN | BUY 25,950 | SELL 10,033 |
| MU | SELL 36,085 | BUY 27,237 |
| ASML | SELL 276 | BUY 9,079 |
| MRVL | SELL 83,578 | BUY 86,472 |

Held direction: AMD, AVGO, ADI, LRCX, AMAT, ARM, ON, NXPI, SMCI, SMH, SOXX —
and several of those collapsed in magnitude anyway (AMD 143,553 → 4,410;
ARM 13,317 → **14**).

The aggregate lopsidedness dissolved too: 3 buy / 17 sell at 15:52 became
7 buy / 12 sell / 1 none at 15:57.

So the early closing-cross print is **a provisional state, not a signal**.
Reading direction off it at 15:52 would have been wrong on nearly half the
universe five minutes later, and the cases that flipped include the largest
imbalances in the sample. Any use of closing NOII should wait for the
1-second phase, and should treat even that as live state rather than a
forecast.

## Opening cross vs closing cross

| | open 09:28 | close 15:52 | close 15:57 |
|---|---|---|---|
| buy-side | 6 | 3 | 7 |
| sell-side | 6 | 17 | 12 |
| no imbalance | 8 | 0 | 1 |
| total paired | 2.73M | 18.87M | — |

Closing-cross paired volume ran **6.9x** the opening cross, which is the
expected ordering for these two auctions and a further sign the feed is
behaving like the real thing.

The eight symbols with no imbalance at 09:28 were all directional by 15:52.
That is the on-close book filling through the session, not a change in
sentiment, and it is a reason not to read a `side 1` at the open as
meaningful balance.

## NVDA

Worth isolating because it moved the most and in both directions:

| Window | Side | Unpaired | Near vs ref |
|---|---|---|---|
| 09:28 open | SELL | 91,848 | 210.00 vs 210.87 (−0.41%) |
| 15:52 close | BUY | 238,570 | not published |
| 15:57 close | SELL | 694,149 | 210.00 vs 210.83 (−0.39%) |

It carried the universe's largest sell imbalance at the open, the largest buy
imbalance in the early closing phase, then the largest sell imbalance again
into the 1-second phase — 694,149 unpaired on 7.45M paired. The 09:28 and
15:57 indicative discounts are nearly identical (−0.41% and −0.39%) despite
pointing through an entire session.

One session, no follow-through measured. Recorded as field behaviour.
