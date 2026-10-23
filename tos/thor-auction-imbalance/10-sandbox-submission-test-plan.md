# Sandbox submission test plan — exercising the safeguards that have never run

For the Mac-side session to run. This cannot be run from a cloud session.

## Why this exists

Every runner verification so far (27 tests, then 36, plus three authenticated
polling cycles) ran with **submission disabled** and zero orders submitted.
That is the correct default and the right safety posture.

It also means the safeguards built around orders have never seen one. Position
limits, the daily-loss limit, duplicate suppression across restarts, and
pending-order reconciliation all operate on order state. With no order ever
created, those paths have been exercised only by unit tests — never
end-to-end against real order IDs, real fills, or a real restart with
in-flight state.

"No orders were placed" is simultaneously the safety guarantee and the gap in
coverage. The point of this plan is to close the gap **in the sandbox only**.

## Precondition — do this before enabling submission

Three live Webull accounts are authorized to place real orders
(see `09-webull-execution-surface.md`). So before any submission is switched
on:

1. Enumerate accounts and record which one the runner targets.
2. Assert that target is **not** `CUT2BJ73`, `CUY7RJG3`, or `CUY9WXY2`.
3. Add that assertion to the runner's startup path so it refuses to start on
   mismatch, rather than relying on the config being right.
4. Confirm the connector's order-placing tools are disabled for ordinary
   sessions, so this test is the only route to an order.

Do not proceed while any of the four is unresolved.

## Test matrix

Each row needs a real sandbox order to exist, which is the whole point. Record
for each: order IDs created, the safeguard's observed decision, and the log
lines proving it.

| # | Safeguard | How to exercise | Pass condition |
|---|---|---|---|
| 1 | Position limit | Submit orders up to the limit, then one more | Final order refused, reason logged, no order at broker |
| 2 | No pyramiding | Submit one order, then a second signal on the same symbol | Second refused as an add to an existing position |
| 3 | No shorts | Emit a short signal on a symbol with no position | Refused before submission |
| 4 | Duplicate suppression across restarts | Submit on a signal, kill the runner, restart, replay the same signal | No second order; suppression keyed on persisted state, not memory |
| 5 | Pending-order reconciliation | Submit an order that will not fill (limit far from market), restart mid-flight | Runner adopts the pending order; does not duplicate it or lose track of it |
| 6 | Cash / exposure limit | **Lower the limit** so one small order breaches it | Order refused, breach logged with the computed exposure |
| 7 | Daily-loss limit | **Lower the threshold** below an already-realized small loss | Trading halts for the day; restart does not clear the halt |
| 8 | Stop file | Create the stop file mid-cycle | Polling stops within one cycle; nothing submitted after |

Rows 6 and 7 deliberately move the threshold rather than engineering a real
loss or a large position. Lowering a limit until the current state breaches it
tests the same branch with far less risk, and is the only practical way to
reach the daily-loss path on a sandbox account in one session.

Row 5 is the one most likely to find a genuine bug, because it is the only
test where state exists *outside* the process at the moment it dies. Run it
more than once, killing at different points: after submit but before the
broker acknowledges, and after acknowledgement but before the local record is
written.

## Teardown

1. Cancel every sandbox order the run created; confirm none remain open.
2. Set submission back to disabled and confirm via a polling cycle.
3. Restore any threshold lowered for rows 6 and 7 to its real value.
4. Verify zero orders exist on the three live Trading accounts — not as a
   formality, but because the whole run hinged on account targeting.

## What a pass means

A pass means the safeguards work against real order state, which the test
suites alone could not establish. It does **not** mean the runner is ready for
real money — that is a separate decision, and nothing in this plan tests
strategy quality, slippage, or sizing against live fills.
