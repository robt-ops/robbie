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
   way. Which ETFs return anything is a separate question, settled by
   listing venue in limit 3 below.

2. **`get_stock_noii_bars` drops the share counts.** The time series carries
   only the three prices — no `paired_shares`, no `imbalance_shares`, no
   `imbalance_side`. The imbalance magnitude is available only from the
   snapshot, one point at a time. Building an imbalance *history* therefore
   means polling the snapshot during 09:28–09:30, not fetching bars.

3. **Coverage follows listing venue — Nasdaq listings only.** Confirmed
   against the full universe during the 2026-10-23 opening cross (see
   `noii-capture-2026-10-23-open.md`): all 20 Nasdaq-listed names returned
   live records, including the ETFs `QQQ`, `SMH` and `SOXX`, which work
   because they are Nasdaq listings and not because ETFs generally do.
   `TSM` (NYSE) and `IWM` (Arca) returned `side 4` with every field zeroed.

   `SPY` (Arca) is the trap: it returns a *populated* ref price with
   `side 1`, which reads as a legitimate "no imbalance". It is actually 2
   paired shares of noise, while SPY's real opening auction runs on Arca
   where this feed cannot see it. Exclude `SPY`, `IWM` and `TSM` from any
   imbalance ranking — SPY especially, because it fails in a way that looks
   like success.

Outside the cross windows the snapshot returns the **previous session's final**
record — NVDA at 09:13 ET today still carried yesterday's 09:29:59 stamp. Always
check `imbalance_time` before treating a snapshot as live.

## `imbalance_side` decoded

Resolved by sampling all 23 universe symbols live during the 2026-10-23
opening cross and correlating the code against the sign of
`near_price - ref_price`:

| Code | Meaning |
|---|---|
| `1` | no imbalance |
| `2` | **buy** imbalance |
| `3` | **sell** imbalance |
| `4` | no data for this symbol |

Twelve directional samples split 6 buy / 6 sell, separated by the sign of
`near - ref` with no contradictions. Full table in
`noii-capture-2026-10-23-open.md`.

## Still unresolved

`imbalance_var_indicator` read `10` on every covered symbol and `0` on the
two uncovered ones, so it distinguishes "has data" from "has none" but its
enum is otherwise unconfirmed. Nasdaq's variance indicator encodes how far
the near price sits from the current reference, which would make it useful
for sizing conviction — worth decoding, but it carries no information in
this sample because it never varied.

## What this does and does not change

It does **not** rescue the thinkScript columns. The six `.ts` files still
cannot see any of this, and the capability table in `README.md` stands.

What it changes is that the auction imbalance leg of the original goal is no
longer impossible — it just lives next to TOS rather than inside it. A
monitor that polls these snapshots across the universe at 09:28–09:30 and
15:50–16:00 would deliver the real imbalance ranking the TOS columns can only
proxy, with the `.ts` columns continuing to serve the confirmation role they
were designed for (relative volume, VWAP distance, momentum).
