/* 双实现一致性校验的 Node 端：只读 stdin，输出可比对的结构化结果。
 * 由 web/verify.py 调用，不要在浏览器里加载。
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const Specpick = require('./engine.js');

const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

function summarize(out) {
  const r = out.result;
  return {
    case_id: r.case_id,
    errors: out.errors,
    winner: r.winner ? r.winner.item_id : null,
    winner_total: r.winner ? r.winner.total : null,
    runner_up: r.runner_up ? r.runner_up.item_id : null,
    accepted: r.accepted.map(function (s) {
      return { id: s.item_id, name: s.name, price: s.price, total: s.total, parts: s.parts };
    }),
    rejected: r.rejected.map(function (x) {
      return { id: x.item_id, name: x.name, reasons: x.reasons };
    }),
    moves: r.moves.map(function (m) {
      return { metric: m.metric, current: m.current, target: m.target, relative: m.relative };
    }),
    sensitivity: {
      baseline: r.sensitivity.baseline || null,
      trials: r.sensitivity.trials || 0,
      flips: r.sensitivity.flips || [],
      verdict: r.sensitivity.verdict || null
    }
  };
}

const results = payload.map(function (c) {
  return summarize(Specpick.decide(c.needs, c.items, c.id));
});

/* 顺带核对：网页内置案例数据与仓库 TOML 案例的裁决相关字段是否一致。
 * 只比参与计算的字段，忽略标题/场景说明/来源备注等描述性文字与字段顺序。
 */
function buildFromState(s) {
  const needs = { title: s.title, scene: s.scene, budget: s.budget,
                  weights: {}, directions: {}, hard: [], ranks: {} };
  if (s.priceWeight > 0) {
    needs.weights.price = s.priceWeight;
    needs.directions.price = 'lower';
  }
  s.fields.forEach(function (f) {
    if (f.type === 'rank' && f.ranks && f.ranks.length) needs.ranks[f.key] = f.ranks;
    if (f.weight > 0 && (f.type === 'number' || f.type === 'rank')) {
      needs.weights[f.key] = f.weight;
      needs.directions[f.key] = f.type === 'rank' ? 'higher' : f.direction;
    }
  });
  if (!Object.keys(needs.ranks).length) delete needs.ranks;
  s.hard.forEach(function (h) {
    needs.hard.push({ field: h.field, op: h.op, value: h.value, label: h.label });
  });
  const items = s.items.map(function (it) {
    const o = { id: it.id, name: it.name, price: it.price };
    s.fields.forEach(function (f) { o[f.key] = it[f.key]; });
    return o;
  });
  return { needs: needs, items: items };
}

function core(needs, items) {
  const hardFields = (needs.hard || []).map(function (h) { return h.field; });
  const used = {};
  Object.keys(needs.weights || {}).forEach(function (k) { used[k] = 1; });
  hardFields.forEach(function (k) { used[k] = 1; });
  const cleanItems = items.map(function (it) {
    const o = { id: String(it.id), name: String(it.name), price: Number(it.price) };
    Object.keys(used).forEach(function (k) { o[k] = it[k]; });
    return o;
  });
  cleanItems.sort(function (a, b) { return a.id < b.id ? -1 : (a.id > b.id ? 1 : 0); });
  return {
    budget: Number(needs.budget),
    weights: needs.weights || {},
    directions: needs.directions || {},
    hard: (needs.hard || []).map(function (h) {
      return { field: h.field, op: h.op, value: h.value };
    }).sort(function (a, b) { return (a.field + a.op) < (b.field + b.op) ? -1 : 1; }),
    items: cleanItems
  };
}

function canon(o) {
  if (typeof o === 'number') return Math.round(o * 1e6) / 1e6;
  if (Array.isArray(o)) return o.map(canon);
  if (o && typeof o === 'object') {
    const out = {};
    Object.keys(o).sort().forEach(function (k) { out[k] = canon(o[k]); });
    return out;
  }
  return o;
}

function firstDiff(a, b, p) {
  if (a === b) return null;
  if (a === null || b === null || typeof a !== typeof b) return p;
  if (typeof a !== 'object') return p + ' → ' + JSON.stringify(a) + ' / ' + JSON.stringify(b);
  const keys = Array.from(new Set(Object.keys(a).concat(Object.keys(b)))).sort();
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    const d = firstDiff(a[k], b[k], p + '.' + k);
    if (d) return d;
  }
  if (Array.isArray(a) && Array.isArray(b) && a.length !== b.length) return p + '.length';
  return null;
}

let parity = null;
try {
  const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  const start = html.indexOf('var CASES = ');
  const end = html.indexOf('\nfunction blank()', start);
  if (start < 0 || end < 0) throw new Error('index.html 里找不到 CASES 字面量');
  const lit = html.slice(start + 'var CASES = '.length, end).trim().replace(/;\s*$/, '');
  const CASES = vm.runInNewContext('(' + lit + ')');
  parity = {};
  ['kitchen', 'laptop', 'gpu'].forEach(function (k) {
    const src = payload.filter(function (c) { return c.id === k; })[0];
    if (!src) { parity[k] = '缺少对应的仓库案例'; return; }
    const built = buildFromState(CASES[k].data);
    const a = canon(core(built.needs, built.items));
    const b = canon(core(src.needs, src.items));
    const d = firstDiff(a, b, k);
    parity[k] = d === null ? true : ('数据不一致：' + d);
  });
} catch (e) {
  parity = { error: e.message };
}

process.stdout.write(JSON.stringify({ results: results, parity: parity }));
