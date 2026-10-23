# Webull execution surface — live trading is reachable from any Claude session

Verified 2026-10-23 via `get_account_authorization` on the Webull connector.

## Finding

Four accounts are authorized to this AI client. **Three can place real orders.**

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

These are live brokerage accounts, not sandbox accounts.

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

## Making it structural

Two independent fixes; doing both is better than either.

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

## Consequence for the runner

Because live Trading-authorized accounts sit behind the same credentials, a
configuration typo in the runner is a high-consequence failure, not a
nuisance. The runner should **assert at every startup that its target account
is the intended sandbox account and refuse to start otherwise** — enumerate
the accounts, compare against an explicit allowlist of one, and exit non-zero
on mismatch. A config value that is merely *set* correctly is weaker than one
that is *checked* on every run.
