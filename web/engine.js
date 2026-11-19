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
    var shapes = needs.shapes || {};
    Object.keys(shapes).forEach(function (metric) {
      var cfg = shapes[metric] || {};
      if (!(metric in weights)) {
        errors.push('shapes.' + metric + ' 没有对应的权重项');
        return;
      }
      if (cfg.shape && SHAPES.indexOf(cfg.shape) === -1) {
        errors.push('shapes.' + metric + '.shape 只能是 ' + SHAPES.join(' / '));
      }
      if (shapeOf(cfg) === 'target') {
        ['lo', 'hi', 'tol'].forEach(function (key) {
          if (typeof cfg[key] !== 'number' || !isFinite(cfg[key])) {
            errors.push('shapes.' + metric + ' 按「越接近越好」算，必须给数字 ' + key);
          }
        });
        if (typeof cfg.tol === 'number' && isFinite(cfg.tol) && cfg.tol <= 0) {
          errors.push('shapes.' + metric + '.tol 必须大于 0');
        }
      }
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

  /* 四种比法，与 engine.py 的 SHAPES / _make_scorer 一一对应：
   * span 按范围（默认）· log 对数刻度 · ordinal 按名次 · target 越接近越好 */
  var SHAPES = ['span', 'log', 'ordinal', 'target'];

  function shapeOf(cfg) {
    var s = String((cfg && cfg.shape) || 'span');
    return SHAPES.indexOf(s) === -1 ? 'span' : s;
  }

  function makeScorer(values, direction, cfg) {
    cfg = cfg || {};
    var shape = shapeOf(cfg);
    var known = values.filter(function (v) { return v !== null; });
    if (!known.length) return [null, { shape: shape }];

    if (shape === 'target') {
      var lo = cfg.lo, hi = cfg.hi, tol = cfg.tol;
      if (typeof lo !== 'number' || typeof hi !== 'number' || typeof tol !== 'number' ||
          !isFinite(lo) || !isFinite(hi) || !isFinite(tol)) {
        return [null, { shape: 'target', bad: true }];
      }
      if (lo > hi) { var t0 = lo; lo = hi; hi = t0; }
      if (tol <= 0) return [null, { shape: 'target', bad: true }];
      var scoreTarget = function (v) {
        var d;
        if (v < lo) d = lo - v;
        else if (v > hi) d = v - hi;
        else return 1.0;
        return Math.max(0.0, 1.0 - d / tol);
      };
      // 区间是绝对值，一件有数据也能比，不需要「至少两个点」
      return [scoreTarget, { shape: 'target', lo: lo, hi: hi, tol: tol }];
    }

    if (known.length < 2 && values.length > 1) return [null, { shape: shape }];

    if (shape === 'ordinal') {
      var uniq = [];
      known.slice().sort(function (a, b) { return a - b; }).forEach(function (v) {
        if (uniq.indexOf(v) === -1) uniq.push(v);
      });
      if (uniq.length < 2) return [function () { return 1.0; }, { shape: 'ordinal', flat: true }];
      var pos = {};
      uniq.forEach(function (v, i) { pos[v] = i / (uniq.length - 1); });
      var scoreOrdinal = function (v) {
        var r = pos[v];
        return direction === 'higher' ? r : 1.0 - r;
      };
      return [scoreOrdinal, { shape: 'ordinal' }];
    }

    // 对数是给正数用的。出现 0 / 负数就退回线性，并在 meta 里标明
    var useLog = shape === 'log' && known.every(function (v) { return v > 0; });
    var tf = useLog ? Math.log10 : Number;
    var tvals = values.map(function (v) { return v === null ? null : tf(v); });
    var low = Math.min.apply(null, tvals.filter(function (x) { return x !== null; }));
    var high = Math.max.apply(null, tvals.filter(function (x) { return x !== null; }));
    var scoreSpan = function (v) {
      if (high === low) return 1.0;
      var ratio = (tf(v) - low) / (high - low);
      return direction === 'higher' ? ratio : 1.0 - ratio;
    };
    return [scoreSpan, {
      shape: useLog ? 'log' : 'span',
      log: useLog,
      low: low,
      high: high,
      log_fallback: shape === 'log' && !useLog
    }];
  }

  function scoreItems(items, weights, directions, ranks, shapes) {
    ranks = ranks || {};
    shapes = shapes || {};
    var metrics = Object.keys(weights);
    var values = {}, scorers = {};
    metrics.forEach(function (m) {
      values[m] = items.map(function (it) { return toNum(it[m], ranks[m]); });
      scorers[m] = makeScorer(values[m], directions[m] || 'higher', shapes[m]);
    });
    var totalW = 0;
    metrics.forEach(function (m) { if (scorers[m][0] !== null) totalW += Number(weights[m]); });
    var scored = items.map(function (item, idx) {
      var parts = {}, avail = 0, known = 0;
      metrics.forEach(function (m) {
        var fn = scorers[m][0];
        var weight = Number(weights[m]);
        var v = values[m][idx];
        if (fn === null || v === null) { parts[m] = null; return; }
        parts[m] = pyRound(weight * fn(v), 4);
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

  function counterfactual(items, winner, runnerUp, weights, directions, ranks, shapes) {
    ranks = ranks || {};
    shapes = shapes || {};
    var gap = winner.total - runnerUp.total;
    if (gap <= 0) return [];
    var byId = {};
    items.forEach(function (it) { byId[String(it.id)] = it; });
    var challenger = byId[runnerUp.item_id];
    var info = {};
    Object.keys(weights).forEach(function (m) {
      info[m] = makeScorer(
        items.map(function (it) { return toNum(it[m], ranks[m]); }),
        directions[m] || 'higher', shapes[m]);
    });
    var moves = [];
    Object.keys(weights).forEach(function (metric) {
      var weight = Number(weights[metric]);
      var fn = info[metric][0], meta = info[metric][1];
      if (weight <= 0 || fn === null) return;
      // 名次型的「改到多少」取决于别人改不改，说不清就不说
      if (meta.shape === 'ordinal') return;
      var current = toNum(challenger[metric], ranks[metric]);
      if (current === null) return;
      var needed = gap / weight;
      var targetScore = fn(current) + needed;
      if (targetScore > 1.0 + 1e-4) return;

      var target, scale, low, high, t;
      if (meta.shape === 'target') {
        var lo = meta.lo, hi = meta.hi, tol = meta.tol;
        if (current >= lo && current <= hi) return;   // 已经在最舒服的区间里
        var dist = current < lo ? lo - current : current - hi;
        var newDist = Math.max(0.0, dist - needed * tol);
        target = current < lo ? lo - newDist : hi + newDist;
        scale = tol;
      } else {
        low = meta.low; high = meta.high;
        if (high === low) return;
        t = directions[metric] === 'higher'
          ? low + targetScore * (high - low)
          : high - targetScore * (high - low);
        if (meta.log) {
          low = Math.pow(10, low); high = Math.pow(10, high); target = Math.pow(10, t);
        } else {
          target = t;
        }
        target = Math.max(low, Math.min(high, target));  // 不外推到样本取值范围之外
        scale = high - low;
      }

      var delta = Math.abs(target - current);
      moves.push({
        metric: metric,
        current: current,
        target: pyRound(target, 2),
        relative: scale ? pyRound(delta / scale, 4) : 0.0
      });
    });
    moves.sort(function (a, b) { return a.relative - b.relative; });
    return moves;
  }

  function sensitivity(items, weights, directions, ranks, shapes) {
    shapes = shapes || {};
    var baseline = scoreItems(items, weights, directions, ranks, shapes)[0].item_id;
    var trials = 0, flips = [];
    Object.keys(weights).forEach(function (metric) {
      [0.75, 1.25].forEach(function (factor) {
        var perturbed = {};
        Object.keys(weights).forEach(function (m) { perturbed[m] = weights[m]; });
        perturbed[metric] = Number(weights[metric]) * factor;
        trials += 1;
        var top = scoreItems(items, perturbed, directions, ranks, shapes)[0].item_id;
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
      shapes: {},
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
    result.shapes = needs.shapes || {};
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
      result.accepted = scoreItems(eligible, needs.weights, needs.directions,
                                   needs.ranks, needs.shapes || {});
    }
    result.winner = result.accepted[0] || null;
    result.runner_up = result.accepted[1] || null;
    if (result.accepted.length >= 2) {
      result.moves = counterfactual(eligible, result.accepted[0], result.accepted[1],
                                    needs.weights, needs.directions, needs.ranks,
                                    needs.shapes || {});
      result.sensitivity = sensitivity(eligible, needs.weights, needs.directions,
                                       needs.ranks, needs.shapes || {});
    }
    return { result: result, errors: [] };
  }

  /* ---------------- 营养缺口推荐（对应 specpick/nutrition.py） ----------------
   * 表里是每 100g 可食部的常见参考值，只用于同表内相对比较；
   * NRV 用《预包装食品营养标签通则》的每日参考值，把「吃一份能补多少」算成百分比。
   * 这张表必须和 Python 侧逐字一致，web/verify.py 会交叉校验。
   */
  var _NUT_COLS = ['vc', 'k', 'fiber', 'folate', 'ca', 'fe', 'va'];
  var NUTRIENTS = [
    ['vc', '维生素C', 'mg', 100.0],
    ['fiber', '膳食纤维', 'g', 25.0],
    ['k', '钾', 'mg', 2000.0],
    ['folate', '叶酸', 'µg', 400.0],
    ['ca', '钙', 'mg', 800.0],
    ['fe', '铁', 'mg', 15.0],
    ['va', '维生素A', 'µg', 800.0]
  ];
  var FOODS_RAW = [
    ['冬枣', '水果', 243.0, 195.0, 1.9, 20.0, 22.0, 1.2, 40.0, 28.0],
    ['猕猴桃', '水果', 62.0, 312.0, 2.6, 25.0, 27.0, 1.2, 6.0, 10.0],
    ['番石榴', '水果', 68.0, 235.0, 5.9, 49.0, 13.0, 0.2, 31.0, 8.0],
    ['草莓', '水果', 47.0, 131.0, 1.1, 24.0, 18.0, 1.8, 5.0, 7.0],
    ['橙子', '水果', 33.0, 159.0, 1.8, 30.0, 20.0, 0.4, 13.0, 11.0],
    ['木瓜', '水果', 43.0, 182.0, 1.7, 44.0, 12.0, 0.3, 47.0, 8.0],
    ['芒果', '水果', 23.0, 138.0, 1.3, 43.0, 11.0, 0.2, 150.0, 14.0],
    ['圣女果', '水果', 14.0, 179.0, 1.8, 15.0, 10.0, 0.5, 92.0, 4.0],
    ['蓝莓', '水果', 10.0, 77.0, 2.4, 6.0, 6.0, 0.3, 3.0, 10.0],
    ['香蕉', '水果', 8.0, 256.0, 1.2, 20.0, 7.0, 0.4, 5.0, 15.0],
    ['牛油果', '水果', 8.0, 599.0, 6.7, 81.0, 12.0, 0.6, 3.0, 1.0],
    ['梨', '水果', 6.0, 92.0, 3.1, 8.0, 9.0, 0.5, 6.0, 10.0],
    ['苹果', '水果', 4.0, 119.0, 1.7, 3.0, 4.0, 0.6, 3.0, 13.0],
    ['火龙果', '水果', 3.0, 20.0, 1.6, 8.0, 6.0, 0.3, 5.0, 13.0],
    ['彩椒', '蔬菜', 72.0, 142.0, 1.4, 46.0, 10.0, 0.3, 57.0, 4.0],
    ['西兰花', '蔬菜', 51.0, 316.0, 2.6, 63.0, 50.0, 0.7, 60.0, 3.0],
    ['菠菜', '蔬菜', 32.0, 558.0, 2.2, 194.0, 66.0, 2.9, 487.0, 1.0],
    ['红薯', '蔬菜', 26.0, 130.0, 2.2, 12.0, 23.0, 0.5, 125.0, 6.0],
    ['胡萝卜', '蔬菜', 5.0, 320.0, 2.8, 12.0, 32.0, 0.5, 688.0, 5.0],
    ['燕麦', '主食豆类', 0.0, 214.0, 10.6, 26.0, 54.0, 3.6, 0.0, 1.0],
    ['杂豆（鹰嘴豆）', '主食豆类', 1.0, 291.0, 7.6, 172.0, 49.0, 2.9, 1.0, 3.0],
    ['北豆腐', '主食豆类', 0.0, 106.0, 0.5, 27.0, 164.0, 1.9, 0.0, 0.0],
    ['猪肝', '肉蛋奶', 20.0, 235.0, 0.0, 236.0, 6.0, 22.6, 4972.0, 0.0],
    ['瘦牛肉', '肉蛋奶', 0.0, 284.0, 0.0, 6.0, 6.0, 2.8, 0.0, 0.0],
    ['鸡蛋', '肉蛋奶', 0.0, 154.0, 0.0, 47.0, 56.0, 1.6, 234.0, 0.0],
    ['牛奶', '肉蛋奶', 1.0, 109.0, 0.0, 5.0, 104.0, 0.3, 24.0, 5.0],
    ['杏仁', '坚果', 0.0, 705.0, 12.2, 30.0, 97.0, 2.1, 0.0, 4.0]
  ];

  // 「一次别超过多少克」：猪肝的维A 是日需的 60 倍/100g，照用户选的 200g 算会给出伤人的建议
  var MAX_G = {
    '猪肝': 30, '牛奶': 300, '杏仁': 30
  };

  var NRV = {}, NLABEL = {}, NUNIT = {};
  NUTRIENTS.forEach(function (n) { NRV[n[0]] = n[3]; NLABEL[n[0]] = n[1]; NUNIT[n[0]] = n[2]; });
  var FOODS = FOODS_RAW.map(function (row) {
    var per = {};
    _NUT_COLS.forEach(function (col, i) { per[col] = row[2 + i]; });
    return { name: row[0], cat: row[1], per100: per, sugar: row[9],
             max_g: MAX_G[row[0]] || 0 };
  });

  function gramsOf(food, portion) {
    return (food.max_g > 0 && food.max_g < portion) ? food.max_g : portion;
  }

  function nutritionPlan(targets, opts) {
    opts = opts || {};
    var portion = opts.portion == null ? 200 : Number(opts.portion);
    var lowSugar = !!opts.lowSugar;
    var limitK = !!opts.limitK;
    var cats = opts.cats || null;
    var top = opts.top == null ? 8 : opts.top;

    var keys = [];
    (targets || []).forEach(function (t) {
      if (NRV[t] != null && keys.indexOf(t) === -1) keys.push(t);
    });
    if (!keys.length) {
      return { targets: [], portion: portion, rows: [],
               combo: { items: [], cover: {} }, gaps: [],
               error: '先选至少一个想补的营养素' };
    }

    var pool = FOODS.filter(function (f) { return !cats || cats.indexOf(f.cat) !== -1; });
    var rows = pool.map(function (food) {
      var grams = gramsOf(food, portion);
      var per100 = {}, pcts = {};
      keys.forEach(function (k) {
        per100[k] = food.per100[k] / NRV[k] * 100;      // 每 100g 能补到的百分比
        pcts[k] = per100[k] * grams / 100;
      });
      var cover = 0;
      keys.forEach(function (k) { cover += Math.min(1, pcts[k] / 100); });
      cover = cover / keys.length;
      var flags = [];
      if (limitK && food.per100.k >= 300) flags.push('钾偏高');
      if (lowSugar && food.sugar >= 15) flags.push('糖偏高');
      var score = cover;
      if (flags.indexOf('钾偏高') !== -1) score *= 0.6;
      if (flags.indexOf('糖偏高') !== -1) score *= 0.7;
      return { name: food.name, cat: food.cat, sugar: food.sugar,
               used: grams, capped: grams < portion,
               pct: pcts, pct100: per100, score: score, flags: flags };
    });

    rows.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      if (a.sugar !== b.sugar) return a.sugar - b.sugar;
      return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0);
    });

    var bestByTarget = {};
    keys.forEach(function (k) {
      var m = 0;
      rows.forEach(function (r) { if (r.pct[k] > m) m = r.pct[k]; });
      bestByTarget[k] = m;
    });
    var gaps = keys.filter(function (k) { return bestByTarget[k] < 25; });

    return {
      targets: keys.map(function (k) {
        return { key: k, label: NLABEL[k], unit: NUNIT[k], nrv: NRV[k],
                 best_pct: bestByTarget[k] };
      }),
      portion: portion,
      rows: rows.slice(0, top),
      combo: nutritionCombo(rows, keys),
      gaps: gaps
    };
  }

  function nutritionCombo(rows, keys) {
    var picked = [], cover = {}, remaining = rows.slice();
    keys.forEach(function (k) { cover[k] = 0; });
    for (var slot = 0; slot < 3; slot++) {
      var best = null, bestGain = 0, bestG = 0;
      remaining.forEach(function (row) {
        var grams = row.used >= 100 ? 100 : row.used;
        var gain = 0, waste = 0;
        keys.forEach(function (k) {
          var add = row.pct100[k] * grams / 100;
          gain += Math.min(1, (cover[k] + add) / 100) - Math.min(1, cover[k] / 100);
          waste += Math.max(0, cover[k] + add - 100) / 100;
        });
        var value = gain - 0.25 * waste;   // 够用就好：同样能补齐，选浪费少的
        if (value > bestGain + 1e-9) { best = row; bestGain = value; bestG = grams; }
      });
      if (!best) break;
      var pct = {};
      keys.forEach(function (k) { pct[k] = best.pct100[k] * bestG / 100; });
      picked.push({ name: best.name, cat: best.cat, g: bestG, pct: pct });
      keys.forEach(function (k) { cover[k] += pct[k]; });
      remaining = remaining.filter(function (r) { return r !== best; });
    }
    var out = {};
    keys.forEach(function (k) { out[k] = cover[k]; });
    return { items: picked, cover: out };
  }

  return {
    decide: decide,
    nutritionPlan: nutritionPlan,
    nutritionNutrients: NUTRIENTS,
    nutritionFoods: FOODS_RAW,
    validateCase: validateCase,
    hardReasons: hardReasons,
    scoreItems: scoreItems,
    counterfactual: counterfactual,
    sensitivity: sensitivity,
    toNum: toNum,
    pyRound: pyRound
  };
});
