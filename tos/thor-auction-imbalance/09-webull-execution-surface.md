# Broker connector execution surface

Verified 2026-10-23 via `get_account_authorization` on the Webull connector,
with the venue roles confirmed by the account owner.

## Finding

Four accounts are authorized to this AI client. **Three can place orders.**

| Account | Authorization |
|---|---|
| `CUT2BJ73` | **Trading** |
| `CUY7RJG3` | **Trading** |
| `CUY9WXY2` | **Trading** |
| `5IU76425` | Non-Trading |

Webull's own description of the categories:

> **Non-Trading** — Access market data, account information, portfolio
> insights, and watchlist management. No trading orders can be executed.
>
> **Trading** — Includes all Non-Trading capabilities, plus the ability to
> place, modify, and cancel orders.

**`get_account_authorization` does not distinguish paper from live.** It
reports only the Trading / Non-Trading category, so a `Trading` row says an
order can be placed — not that real money is behind it. Do not infer venue
type from this endpoint.

Per the account owner, the venue roles are:

| Connector | Role |
|---|---|
| Webull | **paper trading** — the THOR sandbox runner's venue |
| RobinhoodAgentic | intended venue for automated trading, once built |
| Interactive_Brokers | in use, intentional |

So the order-placing authorization on all three is deliberate, not a
misconfiguration. The connector permissions below are recorded as *where* the
controls live, not as a change to make.

## Why the runner's guards do not cover this

The THOR sandbox runner on the Mac has production execution disabled, a stop
file, position and loss limits, and submission switched off. Those protect the
**runner's** code path.

The MCP connector is a **second, independent path** to the same accounts. Any
Claude session holding this connector can call `place_stock_instruction` or
`place_option_single_instruction` directly, with no sandbox, no runner, and
none of its guards in the way. Today the only thing preventing that is that no
session has made the call — convention, not enforcement.

This is not theoretical. The **Daily Catalyst Sheet** scheduled task is
enabled, fires weekdays at 7:40 AM CT, and has the WEBULL connector attached.
Its prompt instructs "NEVER place, modify or cancel orders, alerts or
watchlists", which is the right instruction — but an instruction to a model is
not a block.

## Where the controls live

Recorded for reference. Not a change to make — the current setup is
intentional. This is where to reach for if a specific path ever needs closing.

1. **Connector tool permissions** — at https://claude.ai/customize/connectors,
   open the Webull connector and set the order-placing tools to not-allowed:
   `place_stock_instruction`, `place_option_single_instruction`,
   `place_option_strategy_instruction`, `place_algo_instruction`,
   `place_crypto_instruction`, `place_futures_instruction`,
   `place_event_instruction`, `revoke_instruction`. Read-only tools
   (quotes, bars, NOII, positions, balances) are unaffected, so the
   auction-imbalance work in this folder keeps working.

2. **Account authorization** — on Webull's side, drop the three accounts to
   Non-Trading for AI clients, keeping a separate account for anything that
   genuinely needs order entry.

## Where the startup assertion actually matters

Webull being the paper venue means a wrong-account typo in the THOR runner is
a bookkeeping problem, not a money problem. The startup assertion is still
worth having there — it keeps sandbox results attributable to one account —
but it is not urgent.

It becomes load-bearing on **RobinhoodAgentic**, which is the intended
automated-trading venue. Whatever runs there should **assert at every startup
that its target account matches an explicit allowlist and exit non-zero
otherwise**, rather than trusting a config value to be right. Robinhood's
surface is also wider than Webull's in one respect worth knowing before
building against it: alongside `place_equity_order`, `place_option_order` and
`place_crypto_order` it exposes `exercise_option` and `cancel_option_exercise`,
so an automated path there can take assignment actions, not only open and
close positions.
