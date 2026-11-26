/* 登录态解析的回归用例。
 *
 * SDK 不同版本返回的形状不一样：有时 data 本身就是 session，有时裹一层 .session，
 * 有时只有 accessToken。解析错一次，就会出现「验证码明明通过了、顶部还是未登录」。
 * 这里把 index.html 里的三个纯函数抠出来跑，改坏就红。
 *
 * 跑：node web/login_test.js
 */
'use strict';

const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log('  [OK]   ' + name); }
  else { fail++; console.log('  [FAIL] ' + name + (detail ? ' → ' + detail : '')); }
}

const src = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function grabFrom(startAt) {
  let depth = 0, i = startAt;
  for (; i < src.length; i++) {
    const c = src[i];
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return src.slice(startAt, i + 1); }
  }
  throw new Error('括号没配对');
}
function grabFunc(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('index.html 里找不到函数 ' + name);
  const b = src.indexOf('{', i);
  return src.slice(i, b + grabFrom(b).length);
}

const code = `
var authSession = null;
${grabFunc('pickSession')}
${grabFunc('signedIn')}
${grabFunc('maskPhone')}
return {
  pickSession: pickSession, signedIn: signedIn, maskPhone: maskPhone,
  set: function(v){ authSession = v; }
};
`;
const api = new Function(code)();

console.log('\n一、会话形状：三种都要认出来');

const inner = { user: { id: 'u1', phone: '+8613800138000' }, accessToken: 'tok' };
check('data 本身就是 session（SDK 实际返回这种）', api.pickSession({ data: inner }) === inner);
check('data.session 裹一层', api.pickSession({ data: { session: inner } }) === inner);
check('data 里有 user', api.pickSession({ data: { user: { id: 'u2' } } }).user.id === 'u2');
check('只有 access_token 也认', api.pickSession({ data: { access_token: 'abc' } }).access_token === 'abc');
check('空 data 返回 null', api.pickSession({ data: {} }) === null);
check('没有 data 返回 null', api.pickSession(null) === null && api.pickSession({}) === null);

console.log('\n二、signedIn：只看能不能放行 AI');

api.set({ user: { id: 'u1' } });
check('有 user → 已登录', api.signedIn() === true);
api.set({ accessToken: 'tok' });
check('只有 token → 也算已登录', api.signedIn() === true);
api.set({});
check('空对象 → 未登录', api.signedIn() === false);
api.set(null);
check('null → 未登录', api.signedIn() === false);

console.log('\n三、手机号打码');

check('+86 开头不显示 +86', api.maskPhone('+8613800138000') === '138****8000', api.maskPhone('+8613800138000'));
check('纯 11 位正常打码', api.maskPhone('13800138000') === '138****8000', api.maskPhone('13800138000'));
check('带空格 / 连字符也能打码', api.maskPhone('+86 138-0013-8000') === '138****8000', api.maskPhone('+86 138-0013-8000'));
check('邮箱原样显示', api.maskPhone('a@b.com') === 'a@b.com');
check('空值不炸', api.maskPhone('') === '' && api.maskPhone(null) === '');

console.log('\n共 ' + (pass + fail) + ' 项 · 通过 ' + pass + ' · 失败 ' + fail);
process.exit(fail ? 1 : 0);
