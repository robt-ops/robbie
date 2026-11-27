#!/usr/bin/env node
// =============================================================
// diagnose-volume-gate.mjs
// =============================================================
// Reproduces findings 3, 4, 5 and the baseline short-only scan in
// analysis/candidates/thor-crosssource-integrity-2026-11-27.json
// directly from the committed thor.bars.v1 data files, so the
// reported numbers are independently checkable.
//
// Usage
//   node analysis/qa/diagnose-volume-gate.mjs [dataDir]
//     dataDir defaults to data/extended-2026-11-27
//
// What it prints
//   1. cross-source OHLC divergence (finding 3)
//   2. filter attrition through the v1 short-only chain (finding 4)
//   3. closing-auction contamination of the volume baseline (finding 5)
//   4. short-event rate vs volMult, across three volume baselines
//   5. the baseline v1 short-only backtest with severe friction
//
// IMPORTANT
//   The parameters below are the v1.pine BASELINE set. They are NOT
//   the tuned 3-Bar short-only configuration. Nothing printed here
//   is a verdict on the lead candidate.
// =============================================================

import fs from 'fs';
import path from 'path';

const dataDir = process.argv[2] ?? 'data/extended-2026-11-27';
const STAMP = path.basename(dataDir).replace('extended-', '');
const SYMBOLS = ['AMD', 'MU'];
const SOURCES = ['webull', 'robinhood'];

function load(src, sym) {
  const f = path.join(dataDir, `${sym}-m5-${src}-extended-${STAMP}.json`);
  const d = JSON.parse(fs.readFileSync(f, 'utf8'));
  return d.bars.map(b => ({ t: Date.parse(b.t), iso: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v }));
}
const feeds = {};
for (const src of SOURCES) { feeds[src] = {}; for (const sym of SYMBOLS) feeds[src][sym] = load(src, sym); }

// ---------------- indicators (full-history state) ----------------
const emaOf = (a, n) => { const k = 2 / (n + 1); let p = null; return a.map(v => p = (p === null ? v : v * k + p * (1 - k))); };
const wilder = (a, n) => { let p = null; return a.map(v => p = (p === null ? v : (p * (n - 1) + v) / n)); };
const smaOf = (a, n) => a.map((_, i) => i < n - 1 ? null : a.slice(i - n + 1, i + 1).reduce((x, y) => x + y, 0) / n);
const medOf = (a, n) => a.map((_, i) => { if (i < n - 1) return null; const w = a.slice(i - n + 1, i + 1).slice().sort((x, y) => x - y); return w[Math.floor(n / 2)]; });
function atrOf(bars, n) {
  const tr = bars.map((b, i) => i === 0 ? b.h - b.l : Math.max(b.h - b.l, Math.abs(b.h - bars[i - 1].c), Math.abs(b.l - bars[i - 1].c)));
  return wilder(tr, n);
}
function sessVwap(bars) {
  let day = null, pv = 0, vv = 0;
  return bars.map(b => {
    const d = b.iso.slice(0, 10);
    if (d !== day) { day = d; pv = 0; vv = 0; }
    const h3 = (b.h + b.l + b.c) / 3; pv += h3 * b.v; vv += b.v;
    return vv ? pv / vv : h3;
  });
}
// 15m HTF value from the most recently CLOSED 15m bar (request.security lookahead_off)
function htf15(bars, n) {
  const bk = [], ix = []; let cur = null;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i], mins = new Date(b.t).getUTCMinutes();
    const key = b.iso.slice(0, 13) + ':' + (Math.floor(mins / 15) * 15);
    if (!cur || cur.key !== key) { cur = { key, c: b.c }; bk.push(cur); } else cur.c = b.c;
    ix[i] = bk.length - 1;
  }
  const cl = bk.map(x => x.c), e = emaOf(cl, n);
  return bars.map((_, i) => { const j = ix[i] - 1; return j < 0 ? { c: null, e: null } : { c: cl[j], e: e[j] }; });
}
const hhmm = iso => +iso.slice(11, 13) * 100 + +iso.slice(14, 16);
const IN_SESS = t => t >= 1435 && t < 2055;   // 0835-1455 America/Chicago (CST = UTC-6)
const SESS_END = t => t === 2055;

// v1.pine BASELINE parameters, short-only
const P = {
  emaLen: 50, htfEmaLen: 50, atrLen: 14, volLen: 20, volMult: 1.25, minBodyPct: 0.50,
  riskATR: 1.25, targetATR: 2.00, beTrigger: 1.00, maxBarsHold: 12,
  strictBar3: true, useVWAP: true, useHTF: true, useBE: true,
};
const FRICTION = { commPct: 0.0001, slipTicks: 2, tick: 0.01 };

/** Volume baseline, optionally excluding the 20:55Z closing-auction bar. */
function volBaseline(bars, useMedian, excludeAuction) {
  const series = bars.map(b => (excludeAuction && hhmm(b.iso) === 2055) ? null : b.v);
  const clean = []; let last = null;
  for (const v of series) { if (v === null) clean.push(last === null ? 0 : last); else { clean.push(v); last = v; } }
  return useMedian ? medOf(clean, 20) : smaOf(clean, 20);
}

function shortSignalAt(bars, i, E, V, B, H, p) {
  const b = bars[i], t = hhmm(b.iso), rng = b.h - b.l;
  const body = rng > 1e-8 ? Math.abs(b.c - b.o) / rng : 0;
  return bars[i - 2].c > bars[i - 2].o
    && bars[i - 1].h > bars[i - 2].h
    && b.c < b.o && (!p.strictBar3 || b.c < bars[i - 1].l)
    && body >= p.minBodyPct
    && b.c < E[i]
    && b.v > B[i] * p.volMult
    && IN_SESS(t)
    && (!p.useHTF || H[i].c < H[i].e)
    && (!p.useVWAP || b.c < V[i]);
}

function run(bars, p = P, useMedian = false, excludeAuction = false) {
  const E = emaOf(bars.map(b => b.c), p.emaLen), A = atrOf(bars, p.atrLen),
    V = sessVwap(bars), B = volBaseline(bars, useMedian, excludeAuction), H = htf15(bars, p.htfEmaLen);
  const signals = [], trades = [];
  let pos = null;
  for (let i = 2; i < bars.length; i++) {
    const b = bars[i], t = hhmm(b.iso);
    if (pos) {
      const held = i - pos.i;
      if (!pos.be && i > pos.i && b.l <= pos.entry - pos.atr * p.beTrigger) pos.be = true;
      const stop = (p.useBE && pos.be) ? pos.entry : pos.entry + pos.atr * p.riskATR;
      const tgt = pos.entry - pos.atr * p.targetATR;
      let exit = null, why = null;
      if (b.h >= stop) { exit = stop; why = 'stop'; }             // conservative ordering
      else if (b.l <= tgt) { exit = tgt; why = 'target'; }
      else if (held >= p.maxBarsHold) { exit = b.c; why = 'time'; }
      else if (SESS_END(t)) { exit = b.c; why = 'sessionClose'; }
      if (exit !== null) {
        const slip = FRICTION.slipTicks * FRICTION.tick;
        const eIn = pos.entry - slip, eOut = exit + slip;         // adverse on both legs
        trades.push({ entryIso: pos.iso, exitIso: b.iso, why, held, pnl: (eIn - eOut) - (eIn + eOut) * FRICTION.commPct });
        pos = null;
      }
    }
    if (!pos && B[i] != null && H[i].e != null && i >= p.emaLen && shortSignalAt(bars, i, E, V, B, H, p)) {
      signals.push({ iso: b.iso, px: b.c, atr: A[i] });
      pos = { i, iso: b.iso, entry: b.c, atr: A[i], be: false };
    }
  }
  return { signals, trades };
}
function stats(tr) {
  const w = tr.filter(t => t.pnl > 0), l = tr.filter(t => t.pnl <= 0);
  const gp = w.reduce((s, t) => s + t.pnl, 0), gl = Math.abs(l.reduce((s, t) => s + t.pnl, 0));
  return { n: tr.length, pf: gl > 0 ? gp / gl : (gp > 0 ? Infinity : 0), net: gp - gl, winRate: tr.length ? w.length / tr.length : 0 };
}
const pfs = v => v === Infinity ? 'inf' : v.toFixed(3);

// ---------------- 1. divergence ----------------
console.log('===== (1) CROSS-SOURCE OHLC DIVERGENCE (webull vs robinhood) =====');
for (const sym of SYMBOLS) {
  const idx = new Map(feeds.robinhood[sym].map(b => [b.t, b]));
  let n = 0, maxC = 0, sumC = 0, worst = null, over50 = 0;
  const vr = [];
  for (const b of feeds.webull[sym]) {
    const r = idx.get(b.t); if (!r) continue; n++;
    const dc = Math.abs(b.c - r.c); sumC += dc / r.c;
    if (dc > maxC) { maxC = dc; worst = b.iso; }
    if (dc / r.c * 1e4 > 50) over50++;
    if (r.v > 0) vr.push(b.v / r.v);
  }
  vr.sort((a, b) => a - b);
  console.log(`  ${sym}: ${n} matched | mean |dClose| ${(sumC / n * 1e4).toFixed(2)}bp | max $${maxC.toFixed(4)} (${worst}) | >50bp: ${over50} | median vol ratio WB/RH ${vr[Math.floor(vr.length / 2)].toFixed(3)}`);
}

// ---------------- 2. attrition ----------------
const STAGES = ['eligible bars', '+ bar1 bull', '+ bar2 higher high', '+ bar3 bear', '+ bar3 strict', '+ body >=50%', '+ close<EMA50', '+ vol>1.25x SMA20', '+ in session', '+ HTF 15m bear', '+ close<VWAP'];
console.log('\n===== (2) FILTER ATTRITION, v1 short-only chain =====');
for (const src of SOURCES) for (const sym of SYMBOLS) {
  const bars = feeds[src][sym];
  const E = emaOf(bars.map(b => b.c), 50), V = sessVwap(bars), B = smaOf(bars.map(b => b.v), 20), H = htf15(bars, 50);
  const cnt = new Array(STAGES.length).fill(0);
  for (let i = 2; i < bars.length; i++) {
    if (B[i] == null || H[i].e == null || i < 50) continue;
    const b = bars[i], rng = b.h - b.l, body = rng > 1e-8 ? Math.abs(b.c - b.o) / rng : 0;
    const tests = [true, bars[i - 2].c > bars[i - 2].o, bars[i - 1].h > bars[i - 2].h, b.c < b.o,
      b.c < bars[i - 1].l, body >= 0.50, b.c < E[i], b.v > B[i] * 1.25, IN_SESS(hhmm(b.iso)),
      H[i].c < H[i].e, b.c < V[i]];
    for (let k = 0; k < tests.length; k++) { if (!tests[k]) break; cnt[k]++; }
  }
  console.log(`  ${src} ${sym}: ` + cnt.map((c, k) => `${STAGES[k]}=${c}`).join('  '));
}

// ---------------- 3. auction contamination ----------------
console.log('\n===== (3) CLOSING-AUCTION BAR vs TYPICAL BAR =====');
const med = a => { const s = a.slice().sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
for (const src of SOURCES) for (const sym of SYMBOLS) {
  const bars = feeds[src][sym];
  const auc = med(bars.filter(b => hhmm(b.iso) === 2055).map(b => b.v));
  const oth = med(bars.filter(b => hhmm(b.iso) !== 2055).map(b => b.v));
  console.log(`  ${src} ${sym}: auction ${auc.toLocaleString()} vs other ${oth.toLocaleString()} => ${(auc / oth).toFixed(1)}x`);
}

// ---------------- 4. volMult sensitivity ----------------
console.log('\n===== (4) SHORT-EVENT RATE vs volMult =====');
const sessions = new Set(feeds.webull.AMD.map(b => b.iso.slice(0, 10))).size;
console.log(`  sessions in window: ${sessions}`);
for (const cfg of [{ m: false, x: false, lbl: 'SMA20 raw   ' }, { m: false, x: true, lbl: 'SMA20 no-auc' }, { m: true, x: true, lbl: 'MED20 no-auc' }]) {
  for (const vm of [1.50, 1.25, 1.00, 0.75, 0.50]) {
    const p = { ...P, volMult: vm };
    const wb = SYMBOLS.reduce((s, sym) => s + run(feeds.webull[sym], p, cfg.m, cfg.x).signals.length, 0);
    const rh = SYMBOLS.reduce((s, sym) => s + run(feeds.robinhood[sym], p, cfg.m, cfg.x).signals.length, 0);
    const rate = (wb + rh) / 2 / sessions;
    const need = rate > 0 ? Math.ceil(12 / rate) : Infinity;
    console.log(`  volMult ${vm.toFixed(2)} | ${cfg.lbl} | WB ${String(wb).padStart(3)} RH ${String(rh).padStart(3)} | ${rate.toFixed(2)}/session | +12 events in ${need === Infinity ? 'never' : need} sessions`);
  }
}

// ---------------- 5. baseline backtest ----------------
console.log('\n===== (5) BASELINE v1 SHORT-ONLY BACKTEST (severe friction) =====');
console.log('  NOT the tuned configuration - documented only to show baseline sparsity');
const FWD = '2026-11-24T16:45:00.000Z';
for (const src of SOURCES) for (const sym of SYMBOLS) {
  const { signals, trades } = run(feeds[src][sym]);
  const a = stats(trades), f = stats(trades.filter(t => t.entryIso > FWD));
  console.log(`  ${src} ${sym}: full ${a.n} trades PF ${pfs(a.pf)} net $${a.net.toFixed(2)} win ${(a.winRate * 100).toFixed(0)}% | forward ${f.n} trades | fwd signals ${signals.filter(s => s.iso > FWD).length}`);
}
