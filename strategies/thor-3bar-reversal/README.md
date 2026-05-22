# THOR 3-Bar Reversal — Versioned Strategies

Each `vN.pine` is a self-contained Pine Script v6 strategy. Paste it into TradingView (Pine Editor → "Add to chart") and run the Strategy Tester to backtest.

## Version map

| Version | Tagline | Core idea | Notable knobs |
|--------:|---------|-----------|---------------|
| **v1** | Baseline | Original v3.3 logic, unchanged. Visual upgrades only. | strict bar 3, 1.25 ATR stop, 2.0 ATR target |
| **v2** | Selective | Higher-quality entries, fewer trades, better R:R. | bar 2 close in lower/upper 40%, bar 3 overruns bar 1, ATR floor, 1.5× volume, 1.0/2.5 ATR |
| **v3** | Trend-Strength | Use trend slope as the quality filter; ride winners further. | EMA + HTF slope required, relaxed bar 3, adaptive target (+1 ATR in strong trend), ATR trailing stop |

## Reading the chart

Same role colors across all versions — only the title / labels / table change. So you can stack two versions on the same chart and instantly tell them apart.

- **Orange** — EMA (50)
- **Blue** — VWAP
- **Purple** — HTF EMA
- **Red line** (during trade) — active stop
- **Green line** (during trade) — target
- **White line** (during trade) — entry / avg price
- **Yellow line** (v3 only) — ATR trailing stop, once armed
- **Green/red tint** — currently in long / short
- **Green/red triangles** — entry signal bar
- **Labels** — show version, price, SL, TP, R:R
- **Top-right table** — live state of every filter (UP/DN/OK/low) so you can see at a glance why a signal did or did not fire

## Backtest workflow

1. Open TradingView → your symbol + timeframe.
2. Pine Editor → paste `v1.pine` → Save → "Add to chart".
3. Open the **Strategy Tester** panel → screenshot or copy the Overview stats (Net Profit, % Profitable, Profit Factor, Max DD, Avg Trade, # of Trades).
4. Repeat for `v2.pine` and `v3.pine` on the same symbol/timeframe.
5. Drop the numbers back in chat — I'll propose `v4` based on what's actually weak.

### Stats to send back

Per version, this is what I need to tune the next iteration:

```
Symbol / TF:
Date range:
Net Profit:
% Profitable:
Profit Factor:
Max Drawdown:
Avg Trade:
# of Trades:
Largest Losing Trade:
Avg Bars in Winning Trades / Losing Trades:
```

## Ideas for future versions

Already on deck — pick the direction once we see v1/v2/v3 results:

- **v4 Volatility-Regime** — run v2 logic in low-ATR regimes, v3 in high-ATR regimes (auto-switch).
- **v5 Multi-Target** — scale out 50% at 1R, ride the rest with trail.
- **v6 Time-of-Day** — bucket signals by hour, mute the worst-performing buckets.
- **v7 Bar-Pattern-Only** — drop EMA/VWAP/HTF filters to isolate the raw 3-bar edge.

## File layout

```
strategies/thor-3bar-reversal/
  v1.pine    — Baseline (original v3.3, visual upgrades)
  v2.pine    — Selective (stricter signal, better R:R)
  v3.pine    — Trend-Strength (slope-gated, adaptive target, trailing)
  README.md  — this file
```
