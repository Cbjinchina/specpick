/* specpick 擂台：两两对选，再从「你选了什么」反推权重。
 *
 * 为什么要有这块：拖滑块设权重是件人做不到的事 —— 「噪音 3 分、重量 2 分」
 * 谁说得准？但「这两件你要哪个」人一眼就能答。所以反过来：先让你选，
 * 再用逻辑回归把选择拟合回每个比较项的权重（显示性偏好，revealed preference）。
 *
 * 零依赖、无随机数：同样的输入永远得到同样的权重，方便测试和跨端复现。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Duel = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function zeros(n) {
    var a = [], i;
    for (i = 0; i < n; i++) a.push(0);
    return a;
  }

  /* 全部两两配对：n 件共 n(n-1)/2 场，顺序固定（可复现、可测试）。 */
  function pairs(n) {
    var out = [], i, j;
    for (i = 0; i < n; i++) {
      for (j = i + 1; j < n; j++) out.push([i, j]);
    }
    return out;
  }

  /* 分轮排表（圆桌轮转法）：每轮每人只出场一次，一轮结束名次就大致公平。
   * 轮内先打完再去下一轮，中途退出也不会只让某几件多打。 */
  function schedule(n) {
    var list = [], i;
    for (i = 0; i < n; i++) list.push(i);
    if (list.length % 2) list.push(-1);        // 奇数人补一个「轮空」
    var m = list.length, rounds = [], r, k;
    for (r = 0; r < m - 1; r++) {
      var round = [];
      for (k = 0; k < m / 2; k++) {
        var a = list[k], b = list[m - 1 - k];
        if (a >= 0 && b >= 0) round.push(a < b ? [a, b] : [b, a]);
      }
      rounds.push(round);
      list.splice(1, 0, list.pop());            // 第一个不动，其余顺时针转一格
    }
    return rounds;
  }

  /* 名次：先看净胜场（Copeland：胜 − 负）；净胜相同，看「你赢过的对手有多强」。 */
  function standings(n, duels) {
    var win = zeros(n), loss = zeros(n), opp = zeros(n), i;
    duels.forEach(function (d) { win[d.winner] += 1; loss[d.loser] += 1; });
    duels.forEach(function (d) {
      opp[d.winner] += win[d.loser];   // 强者赛程：赢的对手本身赢得多
      opp[d.loser] += win[d.winner];
    });
    var rows = [];
    for (i = 0; i < n; i++) {
      rows.push({ i: i, win: win[i], loss: loss[i], net: win[i] - loss[i], opp: opp[i] });
    }
    rows.sort(function (a, b) {
      if (b.net !== a.net) return b.net - a.net;
      if (b.opp !== a.opp) return b.opp - a.opp;
      if (b.win !== a.win) return b.win - a.win;
      return a.i - b.i;
    });
    return rows;
  }

  /* 逻辑回归（系数非负 + L2）。
   * 每场样本 = 「你选的那件」减「落选那件」在各比较项上的归一化差值，
   * 标签恒为 1。收敛后系数越大，说明你越是在意那一项。
   * 非负约束很重要：反向指标已经在调用方翻过方向，系数为负没有意义，
   * 只会把噪声拟合成「你讨厌好参数」这种假结论。
   */
  function fit(rows, opts) {
    opts = opts || {};
    var m = rows.length ? rows[0].length : 0;
    if (!m || !rows.length) return { weights: [], accuracy: 0, fitted: 0 };

    var w = zeros(m);
    var lr = opts.lr || 0.6;
    var l2 = opts.l2 == null ? 0.02 : opts.l2;
    var iters = opts.iters || 700;
    var n = rows.length;
    var t, k, j;

    for (t = 0; t < iters; t++) {
      var g = zeros(m);
      for (k = 0; k < n; k++) {
        var z = 0;
        for (j = 0; j < m; j++) z += w[j] * rows[k][j];
        // 标签恒为 1，所以梯度就是 (1 - p) * x
        var e = 1 - 1 / (1 + Math.exp(-z));
        for (j = 0; j < m; j++) g[j] += e * rows[k][j];
      }
      for (j = 0; j < m; j++) {
        var step = g[j] / n - l2 * w[j];
        var next = w[j] + lr * step;
        w[j] = next > 0 ? next : 0;
      }
    }

    // 训练集上能解释多少场：dot > 0 就算猜对（等于「这套权重也选它」）
    var ok = 0, tot = 0;
    for (k = 0; k < n; k++) {
      var norm = 0;
      for (j = 0; j < m; j++) norm += rows[k][j] * rows[k][j];
      if (norm < 1e-12) continue;      // 两件在这些项上完全一样，无从判断
      tot += 1;
      var dot = 0;
      for (j = 0; j < m; j++) dot += w[j] * rows[k][j];
      if (dot > 0) ok += 1;
    }
    return { weights: w, accuracy: tot ? ok / tot : 0, fitted: tot };
  }

  /* 把拟合出来的系数压到 0–5 的滑块刻度上（保留相对大小，不保留绝对量）。 */
  function toScale(weights, maxScale) {
    var mx = 0, i;
    for (i = 0; i < weights.length; i++) if (weights[i] > mx) mx = weights[i];
    if (!(mx > 0)) return weights.map(function () { return 0; });
    return weights.map(function (x) {
      var v = Math.round(x / mx * maxScale);
      return v < 0 ? 0 : v;
    });
  }

  /* 每项上「你选的那件确实更好」占多少场 —— 不依赖拟合，肉眼可核对的那一半。 */
  function leading(rows) {
    var m = rows.length ? rows[0].length : 0;
    var out = [], j, k;
    for (j = 0; j < m; j++) {
      var better = 0, cmp = 0;
      for (k = 0; k < rows.length; k++) {
        var d = rows[k][j];
        if (d > 1e-9) { better += 1; cmp += 1; }
        else if (d < -1e-9) { cmp += 1; }
      }
      out.push({ better: better, compared: cmp });
    }
    return out;
  }

  /* 两个名次表有多一致：Kendall tau，1 = 完全一样，-1 = 完全相反。 */
  function kendall(a, b) {
    var n = a.length, con = 0, dis = 0, i, j;
    if (n < 2) return 1;
    for (i = 0; i < n; i++) {
      for (j = i + 1; j < n; j++) {
        var s = (a[i] - a[j]) * (b[i] - b[j]);
        if (s > 0) con += 1;
        else if (s < 0) dis += 1;
      }
    }
    var p = con + dis;
    return p ? (con - dis) / p : 1;
  }

  return {
    pairs: pairs,
    schedule: schedule,
    standings: standings,
    fit: fit,
    toScale: toScale,
    leading: leading,
    kendall: kendall
  };
});
