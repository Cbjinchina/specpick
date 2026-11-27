/* 「AI 定比较项」的清洗层用例。
 *
 * 模型给的是 JSON，但 JSON 里什么都可能冒出来：权重 9、字段名带中文、
 * 「越接近越好」却不给区间、硬条件引用了不存在的字段……这一层负责把它们
 * 变成引擎吃得下的标准形，不合规的直接丢掉。函数本体写在 index.html 里
 * （和页面共用一个作用域），这里按名字取出来跑，改坏了就红。
 *
 * 跑：node web/plan_test.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const Specpick = require('./engine.js');

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log('  [OK]   ' + name); }
  else { fail++; console.log('  [FAIL] ' + name + (detail ? ' → ' + detail : '')); }
}

const src = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

/* 从源码里按名字抠出对象字面量 / 函数体：括号配对，字符串里没有裸括号，够用 */
function grabFrom(startAt) {
  let depth = 0, i = startAt;
  for (; i < src.length; i++) {
    const c = src[i];
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return src.slice(startAt, i + 1); }
  }
  throw new Error('括号没配对');
}
function grabObject(name) {
  const i = src.indexOf('var ' + name + ' = {');
  if (i < 0) throw new Error('index.html 里找不到 ' + name);
  return grabFrom(src.indexOf('{', i));
}
function grabFunc(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('index.html 里找不到函数 ' + name);
  const b = src.indexOf('{', i);
  const body = grabFrom(b);
  return src.slice(i, b + body.length);
}

const code = `
var PLAN_RULE_TEXT = ${grabObject('PLAN_RULE_TEXT')};
var PLAN_RULES = Object.keys(PLAN_RULE_TEXT);
var OP_TEXT = {'<=':'不超过','>=':'至少','<':'小于','>':'大于','==':'等于','!=':'不等于','in':'属于','not_in':'不属于'};
var Specpick = { toNum: toNumLikeEngine };
/* engine.js 的 toNum 依赖闭包里的 NUM_RE / SCALE，toString 拿不到，
   这里放一份等价实现，只用来喂清洗层 */
function toNumLikeEngine(value, ranks){
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  if (typeof value === 'number') return isFinite(value) ? value : null;
  var text = String(value).trim();
  if (!text) return null;
  if (ranks && ranks.length){
    var flat = text.replace(/\\s+/g,'').toLowerCase(), hit = null;
    for (var i = 0; i < ranks.length; i++){
      var k = String(ranks[i]).replace(/\\s+/g,'').toLowerCase();
      if (k && (k === flat || flat.indexOf(k) !== -1)){ hit = i; break; }
    }
    return hit;
  }
  var m = text.match(/[-+]?\\d[\\d,]*(?:\\.\\d+)?/);
  if (!m) return null;
  var num = parseFloat(m[0].replace(/,/g,''));
  if (!isFinite(num)) return null;
  var SCALE = { '万':10000, 'w':10000, 'W':10000, '千':1000, 'k':1000, 'K':1000 };
  var tail = text.charAt(m.index + m[0].length);
  if (SCALE[tail] !== undefined) num *= SCALE[tail];
  return num;
}
function parseRanks(v){
  var arr = Array.isArray(v) ? v : String(v == null ? '' : v).split(/[,，>＞→\\/|]+/);
  return arr.map(function(x){ return String(x).trim(); }).filter(function(x){ return x; });
}
${grabFunc('planKeyOf')}
${grabFunc('hardNum')}
${grabFunc('sanitizeHards')}
${grabFunc('sanitizePlan')}
${grabFunc('sanitizeHardSay')}
${grabFunc('remapItemKeys')}
return { sanitizePlan: sanitizePlan, sanitizeHards: sanitizeHards, planKeyOf: planKeyOf,
  sanitizeHardSay: sanitizeHardSay,
  remapItemKeys: remapItemKeys,
  PLAN_RULES: PLAN_RULES, PLAN_RULE_TEXT: PLAN_RULE_TEXT };
`;

const api = new Function(code)();
const S = api.sanitizePlan;

console.log('\n一、字段清洗');

const ok = S({ fields: [
  { key: 'battery_h', label: '续航 小时', rule: 'number|higher|span', weight: 5, why: '一天不找插座' },
  { key: 'panel', label: '屏幕素质', rule: 'rank|higher|span', weight: 2, ranks: ['普通', '高色域', '专业'] }
] });
check('合法两项都留下', ok.fields.length === 2, JSON.stringify(ok.fields));
check('label / 权重 / 比法原样保留',
  ok.fields[0].label === '续航 小时' && ok.fields[0].weight === 5 && ok.fields[0].shape === 'span',
  JSON.stringify(ok.fields[0]));
check('档位词按数组保留', ok.fields[1].ranks.join('/') === '普通/高色域/专业', String(ok.fields[1].ranks));
check('why 带出来给界面显示', ok.fields[0].why === '一天不找插座', ok.fields[0].why);

const clamp = S({ fields: [
  { key: 'a', label: '九分', rule: 'number|higher|span', weight: 9 },
  { key: 'b', label: '零分', rule: 'number|higher|span', weight: 0 },
  { key: 'c', label: '负分', rule: 'number|higher|span', weight: -3 },
  { key: 'd', label: '文字项', rule: 'text|higher|span', weight: 4 }
] });
check('权重 9 夹到 5', clamp.fields[0].weight === 5, String(clamp.fields[0].weight));
check('权重 0 / 负数回到 3', clamp.fields[1].weight === 3 && clamp.fields[2].weight === 3,
  clamp.fields[1].weight + '/' + clamp.fields[2].weight);
check('文字项权重强制 0（只筛选不打分）', clamp.fields[3].weight === 0, String(clamp.fields[3].weight));

check('未知比法退回「数字·越大越好」',
  S({ fields: [{ key: 'x', label: 'X', rule: '想当然' }] }).fields[0].shape === 'span');
check('缺 label 的项直接丢', S({ fields: [{ key: 'x', rule: 'number|higher|span' }] }).fields.length === 0);
const many = S({ fields: Array.from({ length: 9 }, (_, i) => ({ key: 'k' + i, label: 'L' + i, rule: 'number|higher|span' })) });
check('最多留 6 项', many.fields.length === 6, String(many.fields.length));

console.log('\n二、字段名');

const keys = S({ fields: [
  { key: 'Battery-Hours', label: '续航', rule: 'number|higher|span' },
  { key: '材质', label: '材质', rule: 'text|higher|span' },
  { key: 'price', label: '价格自带', rule: 'number|lower|span' },
  { key: 'f1', label: '撞名', rule: 'number|higher|span' }
] });
check('大写连字符转小写下划线', keys.fields[0].key === 'battery_hours', keys.fields[0].key);
check('纯中文 key 换成 f 编号', keys.fields[1].key === 'f1', keys.fields[1].key);
check('price 是保留字，重新分配', keys.fields[2].key !== 'price', keys.fields[2].key);
check('编号撞车自动加后缀', keys.fields[3].key === 'f1_2', keys.fields[3].key);

console.log('\n三、比法：目标区间');

const noRange = S({ fields: [{ key: 'inch', label: '尺寸', rule: 'number|higher|target', weight: 3 }] });
check('说「越接近越好」却没给区间 → 退回普通比法', noRange.fields[0].shape === 'span', noRange.fields[0].shape);

const withRange = S({ fields: [{ key: 'inch', label: '尺寸', rule: 'number|higher|target',
  target: { lo: 16, hi: 14, tol: 0 }, weight: 3 }] });
const tg = withRange.fields[0].target || {};
check('区间上下限会被摆正', tg.lo === 14 && tg.hi === 16, JSON.stringify(tg));
check('容差为 0 时兜底，不让引擎除零', tg.tol > 0, String(tg.tol));

console.log('\n四、硬条件');

const hard = S({
  fields: [
    { key: 'weight_kg', label: '重量 kg', rule: 'number|lower|span', weight: 4 },
    { key: '端口', label: '接口', rule: 'text|higher|span' },
    { key: 'panel', label: '屏幕素质', rule: 'rank|higher|span', ranks: ['普通', '高色域'] }
  ],
  hards: [
    { field: 'weight_kg', op: '<=', value: 2, label: '整机不超过 2kg' },
    { field: '端口', op: 'not_in', value: ['只有 C 口'], label: '不要只有 C 口的' },
    { field: 'price', op: '<=', value: 8000, label: '预算 8000 以内' },
    { field: 'ghost', op: '<=', value: 1, label: '不存在的字段' },
    { field: 'panel', op: '<=', value: '普通', label: '文字项不能比大小' },
    { field: 'weight_kg', op: 'in', value: [1, 2], label: '数字项不用 in' },
    { field: 'weight_kg', op: '>=', value: 1, label: '至少 1kg' }
  ]
});
const labelSet = hard.hards.map(h => h.label);
check('合法的三条都留下', hard.hards.length === 3, labelSet.join(' / '));
check('引用不存在字段的被丢掉', labelSet.indexOf('不存在的字段') < 0, labelSet.join(' / '));
check('文字项用 <= 的被丢掉', labelSet.indexOf('文字项不能比大小') < 0, labelSet.join(' / '));
check('中文 key 的硬条件跟到新字段上', hard.hards.some(h => h.field === 'f1'), labelSet.join(' / '));
check('档位项允许 not_in', hard.hards.filter(h => h.field === 'f1').length === 1, labelSet.join(' / '));

const capped = S({ fields: [{ key: 'a', label: 'A', rule: 'number|higher|span' }],
  hards: [1, 2, 3, 4, 5].map(n => ({ field: 'a', op: '>=', value: n, label: '第' + n + '条' })) });
check('硬条件最多 3 条', capped.hards.length === 3, String(capped.hards.length));

console.log('\n五、文字与兜底');

check('notes 原样带出', S({ fields: [{ key: 'a', label: 'A', rule: 'number|higher|span' }], notes: '先卡续航' }).notes === '先卡续航');
check('traps 最多 3 条', S({ fields: [{ key: 'a', label: 'A', rule: 'number|higher|span' }],
  traps: ['1', '2', '3', '4'] }).traps.length === 3);
check('空对象不炸，字段为空', S({}).fields.length === 0);
check('null 不炸', S(null).fields.length === 0);
check('字段不是数组也不炸', S({ fields: 'abc' }).fields.length === 0);

console.log('\n六、识图自动归纳比较项：键要搬得过去');

const auto = S({ fields: [
  { key: 'Battery-Hours', label: '续航 小时', rule: 'number|higher|span', weight: 4 },
  { key: '屏幕', label: '屏幕素质', rule: 'rank|higher|span', weight: 3, ranks: ['普通', '高色域'] }
] });
check('keyMap 指向清洗后的键', auto.keyMap['Battery-Hours'] === 'battery_hours', String(auto.keyMap['Battery-Hours']));
check('中文键也记进 keyMap', auto.keyMap['屏幕'] === auto.fields[1].key, String(auto.keyMap['屏幕']));

const item = api.remapItemKeys({ id: 'A', name: '某本', price: 4999, 'Battery-Hours': '12 小时', '屏幕': '高色域' }, auto.keyMap);
check('候选里的值跟着搬到新键', item.battery_hours === '12 小时' && item[auto.fields[1].key] === '高色域',
  JSON.stringify(item));
check('id / name / price 原样不动', item.id === 'A' && item.name === '某本' && item.price === 4999);
check('没在 keyMap 里的键原样留着', api.remapItemKeys({ name: 'X', price: 1, extra: 2 }, {}).extra === 2);

console.log('\n七、一句话说死要求：翻成规则');

const HS = api.sanitizeHardSay;
const cur = [
  { key: 'weight_kg', label: '重量 千克', type: 'number', direction: 'lower', shape: 'span', weight: 3 },
  { key: 'battery_h', label: '续航 小时', type: 'number', direction: 'higher', shape: 'span', weight: 4 }
];

const hit = HS({ hards: [{ field: 'weight_kg', op: '<=', value: 2, label: '整机不超过 2kg' }] }, cur);
check('对上已有比较项就留下', hit.hards.length === 1 && hit.hards[0].field === 'weight_kg',
  JSON.stringify(hit.hards));
check('没有新字段时 fields 为空', hit.fields.length === 0);

const grow = HS({
  hards: [{ field: 'width_cm', op: '<=', value: 30, label: '宽不超过 30cm' }],
  newFields: [{ key: 'width_cm', label: '宽 厘米', rule: 'number|lower|span', weight: 2 }]
}, cur);
check('缺的字段会顺带建出来', grow.fields.length === 1 && grow.fields[0].key === 'width_cm',
  JSON.stringify(grow.fields));
check('引用新字段的规则没被丢掉', grow.hards.length === 1 && grow.hards[0].field === 'width_cm',
  JSON.stringify(grow.hards));
check('新字段的比法照收', grow.fields[0].direction === 'lower' && grow.fields[0].weight === 2,
  JSON.stringify(grow.fields[0]));

const cn = HS({
  hards: [{ field: '宽度', op: '<=', value: 30, label: '宽不超过 30cm' }],
  newFields: [{ key: '宽度', label: '宽 厘米', rule: 'number|lower|span', weight: 2 }]
}, cur);
check('中文 key 被规范化成英文', cn.fields.length === 1 && /^[a-z0-9_]+$/.test(cn.fields[0].key),
  String(cn.fields[0] && cn.fields[0].key));
check('规则跟着搬到新 key 上', cn.hards.length === 1 && cn.hards[0].field === cn.fields[0].key,
  JSON.stringify(cn.hards));

const ghost = HS({ hards: [{ field: 'no_such', op: '<=', value: 1, label: '幽灵条件' }] }, cur);
check('引用不存在字段的规则直接丢', ghost.hards.length === 0, JSON.stringify(ghost.hards));

const dupKey = HS({
  hards: [{ field: 'weight_kg', op: '>=', value: 1, label: '至少 1kg' }],
  newFields: [{ key: 'weight_kg', label: '重量 千克', rule: 'number|lower|span', weight: 2 }]
}, cur);
check('和现有字段撞名时改成新 key', dupKey.fields.length === 1 && dupKey.fields[0].key !== 'weight_kg',
  JSON.stringify(dupKey.fields));
check('撞名后规则指向改名后的字段', dupKey.hards.length === 1 && dupKey.hards[0].field === dupKey.fields[0].key,
  JSON.stringify(dupKey.hards));

const manyH = HS({ hards: [1, 2, 3, 4, 5].map(n => ({ field: 'weight_kg', op: '<=', value: n, label: '第' + n + '条' })) }, cur);
check('规则最多 3 条', manyH.hards.length === 3, String(manyH.hards.length));

const badOp = HS({ hards: [{ field: 'weight_kg', op: 'gt', value: 2, label: '怪运算符' }] }, cur);
check('不认识的运算符丢掉', badOp.hards.length === 0, JSON.stringify(badOp.hards));

const txtNum = HS({ hards: [{ field: 'weight_kg', op: '<=', value: '2kg', label: '不超过 2kg' }] }, cur);
check('带单位的数字也能抽出数', txtNum.hards.length === 1 && txtNum.hards[0].value === 2,
  JSON.stringify(txtNum.hards));

const unsure = HS({ hards: [], unsure: ['「别太吵」没给分贝，卡不了', '', 'a', 'b', 'c'] }, cur);
check('unsure 最多 3 条且过滤空值', unsure.unsure.length === 3, JSON.stringify(unsure.unsure));
check('翻不成规则时不硬造', unsure.hards.length === 0 && unsure.fields.length === 0);

check('null 不炸', HS(null, cur).hards.length === 0);
check('不传现有字段也不炸', HS({ hards: [{ field: 'x', op: '<=', value: 1, label: 'x' }] }).hards.length === 0);

console.log('\n共 ' + (pass + fail) + ' 项 · 通过 ' + pass + ' · 失败 ' + fail);
process.exit(fail ? 1 : 0);
