/* duel.js 的自检：不依赖浏览器，node web/duel_test.js 直接跑。 */
'use strict';

var Duel = require('./duel.js');

var failed = 0, total = 0;
function ok(name, cond, extra) {
  total += 1;
  if (!cond) {
    failed += 1;
    console.log('  FAIL ' + name + (extra === undefined ? '' : '  → ' + extra));
  }
}

/* 1) 配对：4 件正好 6 场，且不重复、不自比 */
var p = Duel.pairs(4);
ok('pairs 场次', p.length === 6, p.length);
ok('pairs 不自比', p.every(function (x) { return x[0] < x[1]; }));
var seen = {};
p.forEach(function (x) { seen[x[0] + '-' + x[1]] = 1; });
ok('pairs 不重复', Object.keys(seen).length === 6);

/* 2) 名次：A 全胜、B 一胜、C 全败 */
var duels = [
  { winner: 0, loser: 1 },
  { winner: 0, loser: 2 },
  { winner: 1, loser: 2 }
];
var st = Duel.standings(3, duels);
ok('名次顺序', st[0].i === 0 && st[1].i === 1 && st[2].i === 2,
   st.map(function (r) { return r.i + ':' + r.net; }).join(','));
ok('净胜场', st[0].net === 2 && st[1].net === 0 && st[2].net === -2);

/* 3) 拟合：你其实只看第一项（第二项乱选） → 系数应该压在第一位 */
var rows = [
  [0.6, 0.1], [0.5, -0.3], [0.7, 0.2], [0.4, -0.2], [0.8, 0.05], [0.55, 0.3]
];
var f = Duel.fit(rows);
ok('拟合第一项最大', f.weights[0] > f.weights[1] * 3,
   JSON.stringify(f.weights.map(function (x) { return Math.round(x * 100) / 100; })));
ok('拟合能解释全部场次', f.accuracy === 1, f.accuracy);
var sc = Duel.toScale(f.weights, 5);
ok('刻度上限 5', Math.max.apply(null, sc) === 5, sc.join(','));
ok('刻度非负整数', sc.every(function (v) { return v >= 0 && v === Math.round(v); }), sc.join(','));

/* 4) 完全没有信号（你选的那件每项都更差）→ 不该编出权重 */
var noise = [[-0.5, -0.4], [-0.3, -0.6], [-0.7, -0.2]];
var nf = Duel.fit(noise);
ok('无信号不给权重', nf.weights.every(function (x) { return x === 0; }), nf.weights.join(','));
ok('无信号准确率为 0', nf.accuracy === 0, nf.accuracy);

/* 5) 两件完全一样 → 不进准确率分母 */
var same = [[0, 0], [0.5, 0], [0, 0]];
var sf = Duel.fit(same);
ok('全零样本被跳过', sf.fitted === 1, sf.fitted);

/* 6) 一致性：完全一致 = 1，完全相反 = -1 */
ok('kendall 一致', Duel.kendall([0, 1, 2], [0, 1, 2]) === 1);
ok('kendall 相反', Duel.kendall([0, 1, 2], [2, 1, 0]) === -1);
// 只有一对反了：3 对里 2 对一致 → (2-1)/3
ok('kendall 一对相反', Math.abs(Duel.kendall([0, 1, 2], [1, 0, 2]) - 1 / 3) < 1e-12,
   Duel.kendall([0, 1, 2], [1, 0, 2]));

/* 7) 单项领先统计 */
var lead = Duel.leading([[0.2, -0.1], [0.3, 0], [0.1, 0]]);
ok('第一项三场都更好', lead[0].better === 3 && lead[0].compared === 3, JSON.stringify(lead[0]));
ok('第二项只有一场有差', lead[1].compared === 1, JSON.stringify(lead[1]));

/* 8) 排表：n 人 3..7 都应该每人每轮一次、且全组合不重不漏 */
[3, 4, 5, 6, 7].forEach(function (n) {
  var rounds = Duel.schedule(n), flat = [], seenPairs = {};
  rounds.forEach(function (round) {
    var used = {};
    round.forEach(function (g) {
      used[g[0]] = 1; used[g[1]] = 1;
      var key = g[0] + '-' + g[1];
      seenPairs[key] = (seenPairs[key] || 0) + 1;
      flat.push(key);
    });
    // 每人每轮最多出场一次（奇数人时可以有一个人轮空）
    var cnt = Object.keys(used).length;
    ok('schedule ' + n + ' 人每轮不重复', cnt === round.length * 2, n + ':' + cnt);
  });
  var want = n * (n - 1) / 2;
  ok('schedule ' + n + ' 场次齐全', flat.length === want, flat.length + '/' + want);
  ok('schedule ' + n + ' 无重复对局',
     Object.keys(seenPairs).every(function (k) { return seenPairs[k] === 1; }));
});

/* 9) 确定性：同样的输入跑两次结果完全一样 */
var a1 = Duel.fit(rows), a2 = Duel.fit(rows);
ok('结果可复现', JSON.stringify(a1.weights) === JSON.stringify(a2.weights));

console.log((failed ? 'FAIL ' : 'OK ') + (total - failed) + '/' + total + ' 项通过');
process.exit(failed ? 1 : 0);
