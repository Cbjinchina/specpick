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

  function hardReasons(item, needs) {
    var reasons = [];
    if (item.price > needs.budget) {
      reasons.push('价格 ¥' + pyVal(item.price) + ' 超出预算 ¥' + pyVal(needs.budget));
    }
    (needs.hard || []).forEach(function (rule) {
      var actual = item[rule.field];
      if (actual === undefined || actual === null) {
        reasons.push('缺少 ' + rule.field + ' 数据，无法验证「' + rule.label + '」');
      } else if (!OPS[rule.op](actual, rule.value)) {
        reasons.push(rule.label + '（实际 ' + pyVal(actual) + '，要求 ' +
                     rule.op + ' ' + pyVal(rule.value) + '）');
      }
    });
    return reasons;
  }

  function bounds(items, metric) {
    var values = items.map(function (it) { return Number(it[metric]); });
    return [Math.min.apply(null, values), Math.max.apply(null, values)];
  }

  function norm(value, low, high, direction) {
    if (high === low) return 1.0;
    var ratio = (Number(value) - low) / (high - low);
    return direction === 'higher' ? ratio : 1.0 - ratio;
  }

  function scoreItems(items, weights, directions) {
    var metrics = Object.keys(weights);
    var bd = {};
    metrics.forEach(function (m) { bd[m] = bounds(items, m); });
    var scored = items.map(function (item) {
      var parts = {};
      metrics.forEach(function (m) {
        var b = bd[m];
        parts[m] = pyRound(Number(weights[m]) * norm(item[m], b[0], b[1], directions[m]), 4);
      });
      var total = 0;
      metrics.forEach(function (m) { total += parts[m]; });
      return {
        item_id: String(item.id),
        name: String(item.name),
        price: item.price,
        total: pyRound(total, 4),
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

  function counterfactual(items, winner, runnerUp, weights, directions) {
    var gap = winner.total - runnerUp.total;
    if (gap <= 0) return [];
    var byId = {};
    items.forEach(function (it) { byId[String(it.id)] = it; });
    var challenger = byId[runnerUp.item_id];
    var bd = {};
    Object.keys(weights).forEach(function (m) { bd[m] = bounds(items, m); });
    var moves = [];
    Object.keys(weights).forEach(function (metric) {
      var weight = Number(weights[metric]);
      if (weight <= 0) return;
      var low = bd[metric][0], high = bd[metric][1];
      if (high === low) return;
      var needed = gap / weight;
      var currentNorm = norm(challenger[metric], low, high, directions[metric]);
      var targetNorm = currentNorm + needed;
      if (targetNorm > 1.0 + 1e-4) return;
      var target = directions[metric] === 'higher'
        ? low + targetNorm * (high - low)
        : high - targetNorm * (high - low);
      target = Math.max(low, Math.min(high, target));
      var delta = Math.abs(target - Number(challenger[metric]));
      moves.push({
        metric: metric,
        current: Number(challenger[metric]),
        target: pyRound(target, 2),
        relative: pyRound(delta / (high - low), 4)
      });
    });
    moves.sort(function (a, b) { return a.relative - b.relative; });
    return moves;
  }

  function sensitivity(items, weights, directions) {
    var baseline = scoreItems(items, weights, directions)[0].item_id;
    var trials = 0, flips = [];
    Object.keys(weights).forEach(function (metric) {
      [0.75, 1.25].forEach(function (factor) {
        var perturbed = {};
        Object.keys(weights).forEach(function (m) { perturbed[m] = weights[m]; });
        perturbed[metric] = Number(weights[metric]) * factor;
        trials += 1;
        var top = scoreItems(items, perturbed, directions)[0].item_id;
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
      result.accepted = scoreItems(eligible, needs.weights, needs.directions);
    }
    result.winner = result.accepted[0] || null;
    result.runner_up = result.accepted[1] || null;
    if (result.accepted.length >= 2) {
      result.moves = counterfactual(eligible, result.accepted[0], result.accepted[1],
                                    needs.weights, needs.directions);
      result.sensitivity = sensitivity(eligible, needs.weights, needs.directions);
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
    pyRound: pyRound
  };
});
