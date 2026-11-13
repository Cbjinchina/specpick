/* specpick 浏览器引擎：与 specpick/engine.py 一一对应的纯函数实现。
 *
 * 这是「同一套算法」的第二个实现，存在的唯一理由是让手机浏览器无需 Python
 * 也能离线裁决。web/verify.py 会用 Python 权威实现逐案例交叉校验本文件，
 * 任何算法改动必须两边同步，否则 CI 会失败。
 *
 * 零依赖：浏览器用 <script src>，Node 用 require()。不使用随机数、时间、网络。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Specpick = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Python 的 round(x, n) 是四舍六入五成双，JS 的 Math.round 不是，需自行复刻。
  function pyRound(x, digits) {
    var f = Math.pow(10, digits);
    var scaled = x * f;
    var fl = Math.floor(scaled);
    var frac = scaled - fl;
    var n;
    if (frac > 0.5 + 1e-12) n = fl + 1;
    else if (frac < 0.5 - 1e-12) n = fl;
    else n = (fl % 2 === 0) ? fl : fl + 1;
    return n / f;
  }

  function pyVal(v) {
    if (Array.isArray(v)) {
      return '[' + v.map(function (x) {
        return typeof x === 'string' ? "'" + x + "'" : String(x);
      }).join(', ') + ']';
    }
    return String(v);
  }

  // 与 engine.py 的 to_num 一一对应：抽得出数字就给数字，抽不出给 null（这项没数据）。
  var NUM_RE = /[-+]?\d[\d,]*(?:\.\d+)?/;
  var SCALE = { '万': 10000, 'w': 10000, 'W': 10000, '千': 1000, 'k': 1000, 'K': 1000 };

  function flatKey(s) { return String(s).replace(/\s+/g, '').toLowerCase(); }

  function toNum(value, ranks) {
    if (value === null || value === undefined || typeof value === 'boolean') return null;
    if (typeof value === 'number') return isFinite(value) ? value : null;
    var text = String(value).trim();
    if (!text) return null;
    if (ranks && ranks.length) {
      var flat = flatKey(text);
      for (var i = 0; i < ranks.length; i++) {
        var key = flatKey(ranks[i]);
        if (key && (key === flat || flat.indexOf(key) !== -1)) return i;
      }
      return null; // 定义了档位就只认档位词，不能把「4」当第 5 档
    }
    var m = NUM_RE.exec(text);
    if (!m) return null;
    var num = parseFloat(m[0].replace(/,/g, ''));
    if (!isFinite(num)) return null;
    var tail = text.charAt(m.index + m[0].length);
    if (SCALE[tail] !== undefined) num *= SCALE[tail];
    return num;
  }

  var OPS = {
    '<=': function (a, b) { return a <= b; },
    '<': function (a, b) { return a < b; },
    '>=': function (a, b) { return a >= b; },
    '>': function (a, b) { return a > b; },
    '==': function (a, b) { return a === b; },
    '!=': function (a, b) { return a !== b; },
    'in': function (a, b) {
      return Array.isArray(b) ? b.indexOf(a) !== -1 : String(b).indexOf(String(a)) !== -1;
    },
    'not_in': function (a, b) {
      return Array.isArray(b) ? b.indexOf(a) === -1 : String(b).indexOf(String(a)) === -1;
    }
  };

  function validateCase(needs, items) {
    var errors = [];
    ['title', 'budget', 'weights', 'directions'].forEach(function (key) {
      if (!(key in needs)) errors.push('needs.toml 缺少 ' + key);
    });
    if (!items.length) errors.push('items.toml 没有任何 [[item]]');
    var weights = needs.weights || {};
    var directions = needs.directions || {};
    Object.keys(weights).forEach(function (metric) {
      var weight = weights[metric];
      if (!(metric in directions)) errors.push('权重 ' + metric + ' 缺少 directions 方向定义');
      if (directions[metric] !== 'higher' && directions[metric] !== 'lower') {
        errors.push('directions.' + metric + ' 必须是 higher 或 lower');
      }
      if (typeof weight !== 'number' || !isFinite(weight) || weight < 0) {
        errors.push('weights.' + metric + ' 必须是非负数');
      }
    });
    (needs.hard || []).forEach(function (rule) {
      ['field', 'op', 'value', 'label'].forEach(function (key) {
        if (!(key in rule)) errors.push('hard 规则缺少 ' + key);
      });
      if (!OPS[rule.op]) errors.push('不支持的操作符：' + rule.op);
    });
    items.forEach(function (item, i) {
      ['id', 'name', 'price'].forEach(function (key) {
        if (!(key in item)) errors.push('第 ' + (i + 1) + ' 个候选缺少 ' + key);
      });
      Object.keys(weights).forEach(function (metric) {
        if (!(metric in item)) errors.push('候选 ' + (item.name || i) + ' 缺少指标 ' + metric);
      });
      (needs.hard || []).forEach(function (rule) {
        if (!(rule.field in item)) {
          errors.push('候选 ' + (item.name || i) + ' 缺少硬约束字段 ' + rule.field);
        }
      });
    });
    return errors;
  }

  function compare(actual, op, expected, ranks) {
    // 返回 true/false；null 表示「值里读不出可比的数字」
    if (op === 'in' || op === 'not_in') return OPS[op](actual, expected);
    var a = toNum(actual, ranks), b = toNum(expected);
    if (op === '==' || op === '!=') {
      if (a !== null && b !== null) return OPS[op](a, b);
      return OPS[op](String(actual).trim(), String(expected).trim());
    }
    if (a === null || b === null) return null;
    return OPS[op](a, b);
  }

  function hardReasons(item, needs) {
    var reasons = [];
    var ranks = needs.ranks || {};
    var price = toNum(item.price);
    if (price !== null && needs.budget !== null && needs.budget !== undefined && price > Number(needs.budget)) {
      reasons.push('价格 ¥' + pyVal(item.price) + ' 超出预算 ¥' + pyVal(needs.budget));
    }
    (needs.hard || []).forEach(function (rule) {
      var actual = item[rule.field];
      if (actual === undefined || actual === null) {
        reasons.push('缺少 ' + rule.field + ' 数据，无法验证「' + rule.label + '」');
        return;
      }
      var ok = compare(actual, rule.op, rule.value, ranks[rule.field]);
      if (ok === null) {
        reasons.push('「' + rule.label + '」这一项填的是「' + actual + '」，读不出数字，无法验证');
      } else if (!ok) {
        reasons.push(rule.label + '（实际 ' + pyVal(actual) + '，要求 ' +
                     rule.op + ' ' + pyVal(rule.value) + '）');
      }
    });
    return reasons;
  }

  function boundsOf(values, itemCount) {
    var nums = values.filter(function (v) { return v !== null; });
    if (!nums.length) return null;
    // 只有一件候选有数据：定不出高低，给了它满分等于白送，整项按「比不了」处理
    if (nums.length < 2 && itemCount > 1) return null;
    return [Math.min.apply(null, nums), Math.max.apply(null, nums)];
  }

  function norm(value, low, high, direction) {
    if (high === low) return 1.0;
    var ratio = (Number(value) - low) / (high - low);
    return direction === 'higher' ? ratio : 1.0 - ratio;
  }

  function scoreItems(items, weights, directions, ranks) {
    ranks = ranks || {};
    var metrics = Object.keys(weights);
    var values = {}, bounds = {};
    metrics.forEach(function (m) {
      values[m] = items.map(function (it) { return toNum(it[m], ranks[m]); });
      bounds[m] = boundsOf(values[m], items.length);
    });
    var totalW = 0;
    metrics.forEach(function (m) { if (bounds[m] !== null) totalW += Number(weights[m]); });
    var scored = items.map(function (item, idx) {
      var parts = {}, avail = 0, known = 0;
      metrics.forEach(function (m) {
        var weight = Number(weights[m]);
        var b = bounds[m], v = values[m][idx];
        if (b === null || v === null) { parts[m] = null; return; }
        parts[m] = pyRound(weight * norm(v, b[0], b[1], directions[m]), 4);
        known += parts[m];
        avail += weight;
      });
      var total;
      if (avail <= 0) total = 0.0;
      else if (avail < totalW) total = pyRound(known * totalW / avail, 4);
      else total = pyRound(known, 4);
      return {
        item_id: String(item.id),
        name: String(item.name),
        price: item.price,
        total: total,
        parts: parts
      };
    });
    scored.sort(function (a, b) {
      if (a.total !== b.total) return b.total - a.total;
      if (a.price !== b.price) return a.price - b.price;
      return a.item_id < b.item_id ? -1 : (a.item_id > b.item_id ? 1 : 0);
    });
    return scored;
  }

  function counterfactual(items, winner, runnerUp, weights, directions, ranks) {
    ranks = ranks || {};
    var gap = winner.total - runnerUp.total;
    if (gap <= 0) return [];
    var byId = {};
    items.forEach(function (it) { byId[String(it.id)] = it; });
    var challenger = byId[runnerUp.item_id];
    var bd = {};
    Object.keys(weights).forEach(function (m) {
      bd[m] = boundsOf(items.map(function (it) { return toNum(it[m], ranks[m]); }), items.length);
    });
    var moves = [];
    Object.keys(weights).forEach(function (metric) {
      var weight = Number(weights[metric]);
      if (weight <= 0) return;
      var b = bd[metric];
      if (b === null) return;
      var low = b[0], high = b[1];
      if (high === low) return;
      var current = toNum(challenger[metric], ranks[metric]);
      if (current === null) return;
      var needed = gap / weight;
      var currentNorm = norm(current, low, high, directions[metric]);
      var targetNorm = currentNorm + needed;
      if (targetNorm > 1.0 + 1e-4) return;
      var target = directions[metric] === 'higher'
        ? low + targetNorm * (high - low)
        : high - targetNorm * (high - low);
      target = Math.max(low, Math.min(high, target));
      var delta = Math.abs(target - current);
      moves.push({
        metric: metric,
        current: current,
        target: pyRound(target, 2),
        relative: pyRound(delta / (high - low), 4)
      });
    });
    moves.sort(function (a, b) { return a.relative - b.relative; });
    return moves;
  }

  function sensitivity(items, weights, directions, ranks) {
    var baseline = scoreItems(items, weights, directions, ranks)[0].item_id;
    var trials = 0, flips = [];
    Object.keys(weights).forEach(function (metric) {
      [0.75, 1.25].forEach(function (factor) {
        var perturbed = {};
        Object.keys(weights).forEach(function (m) { perturbed[m] = weights[m]; });
        perturbed[metric] = Number(weights[metric]) * factor;
        trials += 1;
        var top = scoreItems(items, perturbed, directions, ranks)[0].item_id;
        if (top !== baseline) flips.push(metric + ' ×' + factor);
      });
    });
    var verdict = flips.length === 0 ? '稳健' : (flips.length <= 1 ? '基本稳健' : '脆弱');
    return { baseline: baseline, trials: trials, flips: flips, verdict: verdict };
  }

  function decide(needs, items, caseId) {
    var errors = validateCase(needs, items);
    var result = {
      case_id: caseId || 'case',
      title: needs.title || '',
      scene: needs.scene || '',
      budget: needs.budget || 0,
      weights: {},
      directions: {},
      hard_rules: [],
      accepted: [],
      rejected: [],
      moves: [],
      sensitivity: {},
      winner: null,
      runner_up: null
    };
    if (errors.length) return { result: result, errors: errors };

    result.weights = needs.weights;
    result.directions = needs.directions;
    result.hard_rules = needs.hard || [];

    var eligible = [];
    items.forEach(function (item) {
      var reasons = hardReasons(item, needs);
      if (reasons.length) {
        result.rejected.push({
          item_id: String(item.id), name: String(item.name), reasons: reasons
        });
      } else {
        eligible.push(item);
      }
    });

    if (eligible.length) {
      result.accepted = scoreItems(eligible, needs.weights, needs.directions, needs.ranks);
    }
    result.winner = result.accepted[0] || null;
    result.runner_up = result.accepted[1] || null;
    if (result.accepted.length >= 2) {
      result.moves = counterfactual(eligible, result.accepted[0], result.accepted[1],
                                    needs.weights, needs.directions, needs.ranks);
      result.sensitivity = sensitivity(eligible, needs.weights, needs.directions, needs.ranks);
    }
    return { result: result, errors: [] };
  }

  return {
    decide: decide,
    validateCase: validateCase,
    hardReasons: hardReasons,
    scoreItems: scoreItems,
    counterfactual: counterfactual,
    sensitivity: sensitivity,
    toNum: toNum,
    pyRound: pyRound
  };
});
