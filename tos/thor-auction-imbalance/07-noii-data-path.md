# Real auction imbalance data — found, outside thinkorswim

The column pack in this folder was built around a hard constraint: **thinkScript
cannot see auction imbalance**. That constraint is real and unchanged. But the
data itself is reachable — just not from inside TOS.

The Webull connector exposes genuine Nasdaq NOII (Net Order Imbalance
Indicator): the paired/unpaired share counts and the three cross prices that
Nasdaq disseminates ahead of the opening and closing crosses.

## Verification that this is really NOII

Pulled `NVDA`, `AMD`, `TSM`, `QQQ`, `SMCI` on 2026-10-23 and inspected the
`PRE_OPEN` time series for AMD. It matches the Nasdaq dissemination spec on
three independent details:

| Spec behaviour | What the data showed |
|---|---|
| NOII every 10 seconds from 09:25 ET | ticks at 09:25:00, :10, :20 … :28:00 |
| switches to every 1 second at 09:28 ET | 1-second ticks from 09:28:00 to 09:30:00 |
| near/far price not published before 09:28 | `near_price` and `far_price` are `0.0` until 09:28:00, then populate |

Data that reproduces three separate timing rules of the real feed is the real
feed, not a derived approximation.

## Fields

From `get_stock_noii_snapshot`:

| Field | Meaning |
|---|---|
| `paired_shares` | shares that can be matched at the cross price |
| `imbalance_shares` | unpaired shares — the imbalance itself |
| `imbalance_side` | direction code (see "Unresolved" below) |
| `imbalance_ref_price` | reference price the imbalance is measured against |
| `imbalance_near_price` | indicative cross price using on-open + continuous book |
| `imbalance_far_price` | indicative cross price using on-open book only |
| `imbalance_var_indicator` | Nasdaq variance indicator |
| `imbalance_time` | epoch ms of the dissemination |

## Three limits that matter

1. **`category: "US_ETF"` is rejected** by the interface — it returns
   `UNSUPPORTED_CATEGORY` even though the schema advertises it. Pass
   `category: "US_STOCK"` for ETFs instead: `QQQ` returns a full record that
   way. So the ETFs in `universe.txt` are covered, but only via the
   counter-intuitive argument.

2. **`get_stock_noii_bars` drops the share counts.** The time series carries
   only the three prices — no `paired_shares`, no `imbalance_shares`, no
   `imbalance_side`. The imbalance magnitude is available only from the
   snapshot, one point at a time. Building an imbalance *history* therefore
   means polling the snapshot during 09:28–09:30, not fetching bars.

3. **NYSE-listed names are effectively uncovered.** `TSM` returned
   `paired_shares: 111` against `NVDA`'s `915,213`. This is Nasdaq's own
   cross only, not the NYSE primary auction, so for a NYSE listing it measures
   a venue that barely participates. Of the universe this affects `TSM`, and
   `SPY`/`IWM` (NYSE Arca) should be treated as suspect until their paired
   counts are checked against a Nasdaq-listed name on the same morning.

Outside the cross windows the snapshot returns the **previous session's final**
record — NVDA at 09:13 ET today still carried yesterday's 09:29:59 stamp. Always
check `imbalance_time` before treating a snapshot as live.

## Unresolved

`imbalance_side` is an integer, and the mapping to Nasdaq's `B`/`S`/`N`/`O`
codes is undocumented here. Observed so far: `1` whenever
`imbalance_shares` is `0`; `3` on QQQ (28,039 unpaired) and SMCI (18,626
unpaired), in both cases with `near_price` just *below* `ref_price`, which
hints at `3` = sell-side. Two samples pointing the same way is not a decode.
Resolve it by sampling the universe live during a cross and correlating the
code against the sign of `near_price - ref_price`.

`imbalance_var_indicator` read `10` on every symbol sampled; its enum is
likewise unconfirmed.

## What this does and does not change

It does **not** rescue the thinkScript columns. The six `.ts` files still
cannot see any of this, and the capability table in `README.md` stands.

What it changes is that the auction imbalance leg of the original goal is no
longer impossible — it just lives next to TOS rather than inside it. A
monitor that polls these snapshots across the universe at 09:28–09:30 and
15:50–16:00 would deliver the real imbalance ranking the TOS columns can only
proxy, with the `.ts` columns continuing to serve the confirmation role they
were designed for (relative volume, VWAP distance, momentum).
