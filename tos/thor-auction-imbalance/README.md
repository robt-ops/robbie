# THOR Auction Imbalance — thinkorswim watchlist pack

Six custom quote columns for monitoring the opening and closing auction windows
across the liquid semiconductor complex and the core index tape.

**Nothing in this directory has been installed or compiled.** It was written
without access to the Mac running thinkorswim. Every script carries a
`STATUS: not compiled` header for that reason. Work through
[Verification](#verification) before trading off any of it.

## Read this first: auction imbalance is not available to thinkScript

The original plan was to build these columns *around* native auction imbalance
fields. That is not possible, and the limitation is structural rather than a
matter of finding the right function name.

| What exists | Where it lives | Reachable from a watchlist column? |
|---|---|---|
| Exchange auction imbalance (Nasdaq NOII: paired/unpaired shares, reference price) | Nasdaq TotalView feed | **No** — not surfaced to thinkScript at all |
| Bookmap "Order Book Imbalance" / volume imbalance bars | Bookmap panel, chart-only | **No** — panel feature, no thinkScript accessor |
| Price, volume, VWAP, session OHLC | thinkScript | Yes — this is what the pack uses |

Two consequences:

1. There is no `GetAuctionImbalance()`. It is not undocumented, it does not
   exist, and any script claiming to read NOII from thinkScript is reading
   something else.
2. These columns are **auction-window confirmation**, not imbalance
   replication. They tell you where price sits against session VWAP, how heavy
   the tape is versus the same time on recent days, and whether those agree.
   They cannot tell you there is a $400M buy imbalance in NVDA at 15:52.

If you need the actual imbalance number, it has to come from outside
thinkorswim — a TotalView-entitled feed, or Nasdaq NOIView. Worth deciding
before you invest more time in the TOS side.

**One thing to check in-platform**, which settles whether any imbalance column
exists natively: right-click any watchlist column header → *Customize* → in the
**Available Items** search box type `imbal`. Published column references do not
list one, but that search is authoritative and takes five seconds. Tell me what
it returns.

## The columns

| # | Column name | Type | Reads |
|--:|---|---|---|
| 1 | `THOR RelVol` | number | Cumulative volume vs. same time of day, prior 5 sessions. 1.00 = normal pace |
| 2 | `THOR VWAP` | number | Percent distance from session VWAP. Positive = above |
| 3 | `THOR Momentum` | number | 30-minute rate of change, percent |
| 4 | `THOR Auction Score` | number | 0–100 conviction, direction-neutral |
| 5 | `THOR Grade` | text | A+ / A / A- / PASS |
| 6 | `THOR Direction` | text | LONG / SHORT / FLAT |

### Why score, grade and direction are three columns

Schwab's Custom Quotes documentation notes that a column formatted as text
sorts alphanumerically. A single `A+ LONG` cell would therefore sort `A-` above
`A`, and `PASS` would land between them — the strongest names end up buried
mid-list exactly when you are scanning fastest.

So the score stays a bare number and is the only column you ever sort by.
Grade and direction are colored text you read across the row once the sort has
put the right names on top. **Do not sort by grade or direction.**

### Score composition

Four 25-point components, all direction-neutral:

- **VOL** — relative volume pace, 1.00x → 2.50x maps 0 → 25
- **VWAP** — absolute distance from session VWAP, 0 → 1.00% maps 0 → 25
- **MOM** — absolute 30-minute rate of change, 0 → 1.50% maps 0 → 25
- **ALIGN** — 25 points only when VWAP side, momentum sign and position in
  session range all point the same way

A name can score 75 on magnitude alone while `Direction` reads `FLAT`. That is
the intended behavior: heavy and volatile, but with nothing agreeing on a side.
Grade answers "how much is happening", direction answers "is there a trade".

## Install

Per column, six times:

1. Right-click any watchlist column header → **Customize**.
2. Scroll the Available Items list to **Custom** → pick a free `Custom N` slot →
   **Add Item(s)**.
3. With it added, click the small **edit (pencil)** icon on that custom item.
4. Paste the contents of the matching `.ts` file into the thinkScript editor.
5. Set **Aggregation period = 5 min**.
6. Set **Extended hours = OFF** — load-bearing, see below.
7. Name the column exactly as the table above (`THOR RelVol`, etc.).
8. **Apply** → **OK**.

Then build the list itself: **Watchlist** gear → *Create watchlist* → name it
`THOR Auction Imbalance` → add the symbols from `universe.txt`.

Create it as a **new** watchlist. Do not retrofit an existing one — the custom
column slots are shared platform-wide, so overwriting an occupied `Custom N`
slot silently changes every other watchlist that uses it. Before you paste into
a slot, confirm it is empty.

### Extended hours must be OFF

`01`, `04`, `05` and `06` offset by `barsPerDay = 78`, which is the number of
5-minute bars in a 09:30–16:00 regular session. With extended hours enabled the
bar count per day changes and those lookbacks silently point at the wrong time
of day. The RelVol figure will still render — it will just be wrong. If you want
a pre-market-inclusive version, `barsPerDay` has to change to match.

## Using it

Sort descending by **THOR Auction Score**, once. Leave it sorted.

**Opening auction, 09:30–10:00.** Columns need bars before they say anything;
`THOR Momentum` is meaningless until roughly 10:00, when its 30-minute lookback
first spans the open. Before then, read `THOR RelVol` and `THOR VWAP` only.
RelVol above ~2.0 in the first fifteen minutes is the opening cross clearing
unusual size. Pair it with `THOR Direction` for a side.

**Closing auction, 15:30–16:00.** Nasdaq begins disseminating closing-cross
imbalance at 15:50, which you cannot see here. What this pack gives you in that
window is whether a name is being carried into the close on real volume and on
the right side of VWAP. A late `THOR RelVol` expansion with `Direction` holding
the same side it held at 15:00 is continuation; expansion with a direction flip
is the imbalance pushing against the day's position.

**Group confirmation.** `SMH` and `SOXX` are in the universe on purpose. A
single semi printing A+ while SMH reads PASS is a single-name move; both lighting
up together is the group, which usually has a different follow-through profile.

## Verification

In order. Steps 1–3 are mechanical; step 4 needs a live session.

1. **Compiles.** Paste each file, hit Apply, confirm no red error text in the
   editor. A custom quote column must have **exactly one** `plot` *or* **one**
   `AddLabel`, never both — `01`–`04` use `plot`, `05`–`06` use `AddLabel`.
   That is the most likely failure, and the error names it.
2. **Renders.** Cells show numbers, not blank or a perpetual `Loading`. Blank
   on every symbol usually means insufficient history for the 5-session
   lookback; let it sit a minute, then re-check.
3. **Sanity-check against a chart.** Open NVDA on a 5-minute chart with VWAP
   plotted. `THOR VWAP` in the watchlist should match the chart's percent
   distance from the VWAP line. If it does not, the accumulator is anchoring on
   the wrong session boundary and `newSession` needs looking at.
4. **Confirm RelVol is believable.** At roughly 10:15 on a normal day, most of
   the universe should read between 0.7 and 1.5, with outliers above 2. If
   *everything* reads 3+, the time-of-day lookback is misaligned — check that
   extended hours is actually off on that column.

Numbers to send back if something is off: the exact error text from step 1, and
for step 4 the RelVol reading on NVDA, SPY and SMH with a timestamp. That is
enough to tell a lookback problem from a threshold-tuning problem.

## Known limitations

- **No auction imbalance.** Covered above. The core limitation.
- **Thresholds are untested priors.** The 1.00%/1.50%/2.50x cutoffs were chosen
  to put a liquid semi's genuinely unusual open in the 75–100 band. They have
  not been fitted to data. Expect to retune after a week of watching.
- **Grade/score duplication.** `04`, `05` and `06` each carry their own copy of
  the scoring block, because custom quote columns cannot import one another.
  Retune a threshold in one, retune it in all three.
- **Momentum is blind for the first 30 minutes**, so the score is effectively
  three-component until ~10:00 and tops out near 75 before then.
- **Cell budget.** Custom Quotes compute up to 1,500 cells. This pack is 22
  symbols x 6 columns = 132. Adding columns across large watchlists is what
  hits that ceiling, not this list.

## Sources

- [Custom Quotes — thinkorswim Learning Center](https://toslc.thinkorswim.com/center/howToTos/thinkManual/MarketWatch/Quotes/customquotes)
- [Watchlist Columns — thinkorswim Learning Center](https://toslc.thinkorswim.com/center/howToTos/thinkManual/MarketWatch/Quotes/Watchlist-Columns)
- [Create and Customize Watchlists on thinkorswim — Schwab](https://www.schwab.com/learn/story/create-and-customize-watchlists-on-thinkorswim)
- [Imbalance Indicators (Bookmap) — thinkorswim Learning Center](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Bookmap/Imbalance-Indicators)
- [Nasdaq NOIView specification (PDF)](https://assets.ctfassets.net/mx0rke14e5yt/35jGr6CD9xcecVEn3gZ8Pg/c29d69dafae253dc8f5ceee009068207/NOIViewSpecification.pdf)
- [Automation and Information Produce Efficient Price Discovery in Nasdaq's Auction Process](https://www.nasdaq.com/articles/automation-and-information-produce-efficient-price-discovery-in-nasdaqs-auction-process)
- [thinkScript AddLabel in watchlist columns — thinkScript101](https://thinkscript101.com/thinkscript-add-label/)
- [How To Create A Custom Watchlist Column — useThinkScript](https://usethinkscript.com/threads/how-to-create-a-custom-watchlist-column-a-tutorial-for-thinkorswim.9709/)
