# Data integrity — ORB out-of-sample study

Run in response to a coordination request listing these priorities: provider
hashes, ET/DST session and VWAP parity, warm-up/history bounds, adjustment
and entitlement status, entry counts separated from partial exit legs.

Two independent providers happen to overlap on QQQ 5-minute bars
(2026-02-23 → 2026-10-16, 12,870 shared timestamps), so parity is measured
rather than assumed.

## Cross-provider parity: the disagreement is real and localised

| bar | field | median | p95 | max | bars >1¢ |
|---|---|---|---|---|---|
| 09:30 (direction + stop) | open | **$0.0400** | $0.5260 | $0.6600 | **118/165** |
| 09:30 | high | $0.0000 | $0.0580 | $1.2400 | 12/165 |
| 09:30 | low | $0.0000 | $0.0000 | $0.5300 | 5/165 |
| **09:35 (entry price)** | **open** | **$0.0000** | **$0.0000** | **$0.0050** | **0/165** |
| 15:55 (session exit) | close | **$0.0500** | $0.2000 | $0.9600 | **145/165** |

All-bar close disagreement: median $0.0000, q99 $0.5875, max $3.7050.

**Reading it:** disagreement concentrates in the two *auction* prints — the
09:30 open and the 15:55 close — where providers legitimately differ on
official-auction versus first/last-trade convention. The bar the strategy
actually transacts on, the **09:35 open, agrees to within half a cent with
zero bars differing by more than 1¢.**

## Does the verdict depend on the provider? No.

Same rules, same window, both feeds:

| feed | trades | mean PnL/share | SD | Sharpe | exits |
|---|---|---|---|---|---|
| Webull (study feed) | 165 | −$0.0914 | $3.482 | −0.022 | 118 stop / 44 close / 3 target |
| Robinhood (split-adj) | 165 | −$0.1227 | $3.406 | −0.239 | 118 stop / 44 close / 3 target |

Agreement across 165 shared sessions: **98.2%** same direction, **98.8%** same
exit reason, per-trade PnL correlation **0.9706**, mean absolute per-trade
difference **$0.1272**.

The 1.8% direction disagreement traces to the 09:30 open: direction is
`sign(close − open)` on that bar, and a median $0.04 disagreement on the open
flips the sign on a handful of near-doji days.

Note also that **both feeds are negative over this sub-window**, consistent
with the main study's finding that the 2026 portion contributed −36% of net
PnL.

## ⚠️ VWAP will not reconcile across these two providers

Volume disagrees by a **median of 103.93%** — roughly a factor of two — with a
max absolute difference of 5.4M shares on a single 5-minute bar. The two
feeds are evidently counting different trade sets (venue coverage, odd lots,
or off-exchange prints).

**Consequence for the VWAP-parity priority: any VWAP computed from one feed
cannot be reconciled against the other, because VWAP is volume-weighted and
the weights differ by ~2×.** Price parity does not imply VWAP parity. A
VWAP-dependent rule must fix one provider and treat VWAP as provider-specific,
or reconcile volume definitions first. The same caution applies to the
`vol_mult` relative-volume filter in `../thor-3bar-reversal/backtest.py`.

## ET / DST session parity — verified

- All **922/922** usable sessions have their first bar at exactly **09:30:00**
  America/New_York.
- Localising the full index to America/New_York yields **0** ambiguous or
  nonexistent timestamps.
- Both **−5:00 (EST)** and **−4:00 (EDT)** offsets are present, so the window
  spans DST transitions in both directions and they are handled.

Bars were stored UTC and converted to America/New_York before any
session grouping, so DST shifts cannot smear the 09:30 bar.

## Warm-up and history bounds

- **ORB: zero warm-up.** Direction and stop come from the 09:30 bar of the
  *same* session; no lookback indicator. No sessions are dropped for warm-up,
  so 914 sessions in the window → 909 trades + 5 doji.
- **RSI(2) daily study:** gated on `sma.notna()` for the 200-day SMA, so the
  first 199 bars per symbol are excluded by construction.
- **Disclosed gap:** the 5-minute 3-bar study uses `ewm`-based EMA(50) and
  ATR(14), which emit values from bar 1 and are therefore biased over roughly
  the first 50 bars of each symbol's series. With ~12,870 bars per symbol the
  effect is <0.4% of the sample and cannot change its conclusion, but it is
  not formally trimmed.

## Adjustment and entitlement status

- **Robinhood:** `adjustment_type="split"` passed explicitly (split-adjusted,
  no dividend adjustment), `bounds="regular"`.
- **Webull:** the API exposes no adjustment parameter; status is therefore
  **unspecified by the provider**. QQQ had no split in 2023-02 → 2026-10, and
  the parity table above bounds any residual difference, so this does not
  affect the result — but it is unverified rather than confirmed.
- **Session scope:** Webull `trading_sessions="RTH"`; Robinhood
  `bounds="regular"`. Both regular-hours only; the ~2× volume gap suggests
  these definitions are *not* identical.
- **Entitlement:** Robinhood and Webull are the connected sources. **IBKR is
  unavailable in this environment**, consistent with your note.

## Entry counts vs partial exit legs

`orb.py` opens at most one position per session and closes it in a single leg
— no scaling in, no scaling out, no partial fills modelled. Therefore
**909 entries = 909 exits = 909 trades**; the trade count is not inflated by
exit legs. Exit mix: 673 stop, 214 close, 22 target.

## Dataset hashes (sha256)

```
9c5792ff780c6493ab6ba63f376197b9db1016301685b052e48fb64a3f240130  qqq_5m_oos.csv   (4,169,968 B)
3258867cd3c40e0d304b1cee3728cf5f8539c0c8ecbaddf8c11d096f54b2cb15  QQQ.csv  (RH)   (742,642 B)
18cf15e0d42117a49c4360091eb939b746bf5f95e26552009395f32432512b9f  spy_5m.csv       (741,015 B)
```

These are hashes of the derived, quality-gated CSVs, not vendor payload
hashes — the providers do not expose content hashes through these APIs, so
upstream immutability cannot be attested from here.
