#!/usr/bin/env node
// =============================================================
// flag-underfilled-bars.mjs
// =============================================================
// Purpose
//   Detect bars that LOOK valid (non-zero volume, not flagged
//   `interpolated`) but are in fact severely under-filled, by
//   comparing a candidate feed against a reference feed on the
//   same 5m grid.
//
// Why this exists
//   The existing pipeline guard rejects zero-volume / interpolated
//   placeholder bars. That guard is NOT sufficient. Over 2026-11-10
//   .. 2026-11-25, Robinhood 5m "regular" bars included 24 bars
//   (11 AMD, 13 MU) whose volume was 5x to 26,302x below Webull's
//   bar for the same minute, with the price range collapsed to
//   2-49% of Webull's. None of those bars carried interpolated=true
//   and none had volume 0, so the existing guard passes them
//   straight into traded-bar backtests.
//
//   Worst observed:
//     MU  2026-11-20T20:55:00Z  RH vol        286  vs WB 7,522,325  (26,302x)
//     AMD 2026-11-12T18:05:00Z  RH vol         87  vs WB   271,374  ( 3,119x)
//
// Range-awareness (important)
//   A plain volume-ratio test produces false positives on the
//   20:55 closing-auction bar, where Robinhood legitimately reports
//   less auction volume than Webull but the SAME high/low. Genuine
//   broken bars lose price range as well as volume, so this gate
//   requires BOTH a volume gap and a range collapse.
//
// Usage
//   node flag-underfilled-bars.mjs <candidate.json> <reference.json> [--ratio 5] [--range 0.5] [--json]
//
//   Each input is a thor.bars.v1 file: { bars: [ {t,o,h,l,c,v}, ... ] }
//   with `t` an ISO-8601 UTC timestamp.
//
// Exit codes
//   0  no suspect bars
//   1  suspect bars found (and listed)
//   2  bad invocation / unreadable input
// =============================================================

import fs from 'fs';

export const DEFAULTS = { minVolRatio: 5, maxRangeFrac: 0.5 };

/**
 * @param {Array<{t:string,h:number,l:number,c:number,v:number}>} candidate
 * @param {Array<{t:string,h:number,l:number,c:number,v:number}>} reference
 * @param {{minVolRatio?:number,maxRangeFrac?:number}} opts
 * @returns {{matched:number, flagged:Array<object>}}
 */
export function flagUnderfilled(candidate, reference, opts = {}) {
  const { minVolRatio = DEFAULTS.minVolRatio, maxRangeFrac = DEFAULTS.maxRangeFrac } = opts;
  const ref = new Map(reference.map(b => [Date.parse(b.t), b]));
  const flagged = [];
  let matched = 0;

  for (const c of candidate) {
    const r = ref.get(Date.parse(c.t));
    if (!r) continue;
    matched++;

    // volume gap: reference / candidate
    const volRatio = (c.v > 0 && r.v > 0) ? r.v / c.v : (c.v === 0 ? Infinity : 1);
    const cRange = c.h - c.l;
    const rRange = r.h - r.l;
    const rangeFrac = rRange > 0 ? cRange / rRange : 1;

    if (volRatio > minVolRatio && rangeFrac < maxRangeFrac) {
      flagged.push({
        t: c.t,
        candidate_volume: c.v,
        reference_volume: r.v,
        volume_ratio: Number(volRatio.toFixed(1)),
        candidate_range: Number(cRange.toFixed(4)),
        reference_range: Number(rRange.toFixed(4)),
        range_fraction: Number(rangeFrac.toFixed(3)),
        candidate_close: c.c,
        reference_close: r.c,
        close_divergence_bp: Number((Math.abs(c.c - r.c) / r.c * 1e4).toFixed(1)),
      });
    }
  }
  return { matched, flagged };
}

/** Convenience: timestamps to drop from a traded-bar backtest. */
export function underfilledTimestamps(candidate, reference, opts = {}) {
  return new Set(flagUnderfilled(candidate, reference, opts).flagged.map(f => f.t));
}

// ---------------- CLI ----------------
function isMain() {
  return process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href;
}

if (isMain()) {
  const args = process.argv.slice(2);
  const files = args.filter(a => !a.startsWith('--'));
  const asJson = args.includes('--json');
  const flagVal = (name, dflt) => {
    const i = args.indexOf('--' + name);
    return i >= 0 && args[i + 1] ? Number(args[i + 1]) : dflt;
  };

  if (files.length !== 2) {
    console.error('usage: node flag-underfilled-bars.mjs <candidate.json> <reference.json> [--ratio 5] [--range 0.5] [--json]');
    process.exit(2);
  }

  let cand, ref;
  try {
    cand = JSON.parse(fs.readFileSync(files[0], 'utf8'));
    ref = JSON.parse(fs.readFileSync(files[1], 'utf8'));
  } catch (e) {
    console.error('cannot read input: ' + e.message);
    process.exit(2);
  }

  const candBars = cand.bars ?? cand;
  const refBars = ref.bars ?? ref;
  const { matched, flagged } = flagUnderfilled(candBars, refBars, {
    minVolRatio: flagVal('ratio', DEFAULTS.minVolRatio),
    maxRangeFrac: flagVal('range', DEFAULTS.maxRangeFrac),
  });

  if (asJson) {
    console.log(JSON.stringify({
      candidate: files[0], reference: files[1],
      candidate_bars: candBars.length, reference_bars: refBars.length,
      matched, flagged_count: flagged.length, flagged,
    }, null, 1));
  } else {
    console.log(`candidate ${cand.symbol ?? files[0]} (${cand.source ?? '?'})  ${candBars.length} bars`);
    console.log(`reference ${ref.symbol ?? files[1]} (${ref.source ?? '?'})  ${refBars.length} bars`);
    console.log(`matched on grid: ${matched}`);
    console.log(`suspect under-filled bars: ${flagged.length}`);
    for (const f of flagged) {
      console.log(`  ${f.t}  vol ${f.candidate_volume} vs ${f.reference_volume}` +
        ` (${f.volume_ratio}x)  range ${(f.range_fraction * 100).toFixed(0)}% of reference` +
        `  dClose ${f.close_divergence_bp}bp`);
    }
  }
  process.exit(flagged.length > 0 ? 1 : 0);
}
