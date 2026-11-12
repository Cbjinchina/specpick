/* 粘贴文本解析器的用例。跑：node web/paste_test.js */
'use strict';

const P = require('./paste.js');

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log('  [OK]   ' + name); }
  else { fail++; console.log('  [FAIL] ' + name + (detail ? ' → ' + detail : '')); }
}

/* 1. 京东搜索页：名称在上、价格在下，中间夹着店铺与销量噪音 */
const jd = `
京东
综合  销量  价格
七彩虹 Colorfire 旗舰店
七彩虹 5060Ti 16G Ultra W DUO OC
RTX5060Ti 16G 电竞游戏显卡
¥7299
10万+人付款
七彩虹 Colorful 旗舰店
七彩虹 5060 Ultra W OC 8G
¥4799
5万+人付款
万丽电竞旗舰店
万丽 GeForce RTX 5060 OC 8GB GDDR7 雪狐
3999
1万+人付款
`;
const r1 = P.parse(jd, [{ key: 'vram_gb', label: '显存 GB', type: 'number' }]);
check('京东：认出 3 件', r1.items.length === 3, JSON.stringify(r1.items.map(i => i.name)));
check('京东：名称正确', /5060Ti 16G Ultra/.test(r1.items[0].name), r1.items[0].name);
check('京东：¥ 价格正确', r1.items[0].price === 7299, String(r1.items[0].price));
check('京东：纯数字价格正确', r1.items[2].price === 3999, String(r1.items[2].price));
check('京东：显存自动认出 16', r1.items[0].guessed.vram_gb === 16, JSON.stringify(r1.items[0].guessed));
check('京东：型号 5060 没被当价格', r1.items.every(i => i.price < 20000));

/* 2. 名称与价格挤在同一行 */
const oneLine = `小米 Redmi Book 14 ¥4299
联想 小新 Pro 16 5999 元`;
const r2 = P.parse(oneLine, []);
check('同行：认出 2 件', r2.items.length === 2, JSON.stringify(r2.items));
check('同行：¥ 价格', r2.items[0].price === 4299, String(r2.items[0].price));
check('同行：元 价格', r2.items[1].price === 5999, String(r2.items[1].price));

/* 3. 只有名称、没有价格 → 不瞎猜，进「待核对」 */
const r3 = P.parse(`戴尔 XPS 13\n惠普 星 14\n¥5499`, []);
check('缺价：不硬凑', r3.items.length >= 1 && r3.items[0].price === 5499, JSON.stringify(r3));

/* 4. 价格在前、名称在后 */
const r4 = P.parse(`¥3899\n机械革命 无界 14\n¥4599\n华硕 无畏 15`, []);
check('价格在前：两件都配上', r4.items.length === 2 && r4.items[0].price === 3899 && r4.items[1].price === 4599,
  JSON.stringify(r4.items));

/* 5. 噪音行不该变候选 */
const r5 = P.parse(`领券立减 200\n¥1999\n包邮\n品牌旗舰店`, []);
check('噪音：不生成候选', r5.items.length === 0, JSON.stringify(r5.items));

/* 6. 重量/续航/风扇按比较项名称认 */
const lap = `某牌 轻薄本 1.24kg 续航 12 小时\n¥5499`;
const r6 = P.parse(lap, [
  { key: 'weight_kg', label: '重量 kg', type: 'number' },
  { key: 'battery_h', label: '续航 h', type: 'number' }
]);
check('重量自动认出', r6.items[0].guessed.weight_kg === 1.24, JSON.stringify(r6.items[0].guessed));
check('续航自动认出', r6.items[0].guessed.battery_h === 12, JSON.stringify(r6.items[0].guessed));

/* 7. 同名去重 */
const r7 = P.parse(`七彩虹 5060 Ultra W OC 8G\n¥4799\n七彩虹 5060 Ultra W OC 8G\n¥4799`, []);
check('去重：只剩 1 件', r7.items.length === 1, JSON.stringify(r7.items));

console.log('\n共 ' + (pass + fail) + ' 项 · 通过 ' + pass + ' · 失败 ' + fail);
process.exit(fail ? 1 : 0);
