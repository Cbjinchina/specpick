/* 从「截图里复制出来的文字」里把候选商品还原成结构化数据。
 *
 * 为什么不做图片识别：手机端装不了任何东西，也不可能要求顾客有 API Key。
 * 所以分工是——手机系统负责「看字」（相册长按 / 微信长按 → 提取文字），
 * 这里负责「把字变成表」：拆出名称、价格，以及能确定归属的数字。
 *
 * 纯函数、不联网、不猜：认不出就留空，宁缺勿错。
 * 浏览器和 Node 都能跑，便于测试与 CI。
 */
(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory();
  else root.PasteParser = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // 店铺、销量、促销等：对比较没有价值，直接丢掉
  var NOISE = /(人付款|已付款|人已购|已售|月销|销量|条评价|评价|好评|问大家|包邮|分期|免息|优惠|领券|券后|满减|直降|秒杀|广告|旗舰店|专营店|专卖店|自营|配送|现货|以旧换新|价保|保障|服务|促销|限时|折|加购|对比|关注|收藏|进店|店铺|补贴|百亿|国家补贴|支持|赠|晒图|视频|图集)/;
  // 页面导航、筛选栏一类的固定文字
  var HEADER = /^(综合|销量|价格|全部|京东|淘宝|天猫|拼多多|搜索|筛选|排序|结果|商品|店铺|首页|我的|购物车|共\s*\d+\s*件?|下一页|上一页|返回|客服|分享|加入购物车|立即购买|店铺关注|自营|新品|配送至)/;

  function clean(s) {
    return String(s)
      .replace(/[\u00a0\u3000]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // 只看「这一行是不是一个价格」，避免把型号 5060 当价格
  function priceOf(line) {
    var s = line.replace(/[￥]/g, '¥');
    // ¥ 开头或带「元 / 起」，可信度最高
    var m = s.match(/^¥\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:元|起)?$/);
    if (m) return { value: num(m[1]), strong: true };
    m = s.match(/¥\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)/);
    if (m) return { value: num(m[1]), strong: true, head: s.slice(0, m.index).trim() };
    m = s.match(/([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*元(?:起)?\s*$/);
    if (m) return { value: num(m[1]), strong: true, head: s.slice(0, m.index).trim() };
    // 纯数字行：3~6 位、两位数以上，才敢当价格
    if (/^[0-9][0-9,]{2,6}(?:\.[0-9]{1,2})?$/.test(s)) {
      var v = num(s);
      if (v >= 20) return { value: v, strong: false };
    }
    return null;
  }

  function num(s) { return Number(String(s).replace(/,/g, '')); }

  function isTitleLike(s) {
    if (s.length < 3) return false;
    if (!/[\u4e00-\u9fa5A-Za-z]/.test(s)) return false;
    if (HEADER.test(s)) return false;
    if (NOISE.test(s) && s.length < 12) return false;
    return true;
  }

  // 名称里常混着规格，顺手把能确定的数字认出来（只在对应比较项存在时才用）
  var GUESS = [
    { key: '显存', re: /(\d{1,2})\s*G(?:B)?/i, min: 4, max: 48 },
    { key: '内存', re: /(\d{1,3})\s*G(?:B)?/i, min: 4, max: 256 },
    { key: '硬盘', re: /(\d{3,4})\s*G(?:B)?/i, min: 64, max: 8192 },
    { key: '存储', re: /(\d{3,4})\s*G(?:B)?/i, min: 64, max: 8192 },
    { key: '重量', re: /(\d(?:\.\d{1,2})?)\s*(?:kg|KG|千克)/, min: 0.4, max: 5 },
    { key: '续航', re: /(\d{1,2}(?:\.\d)?)\s*(?:小时|h|H)/, min: 2, max: 30 },
    { key: '风扇', re: /([1-4])\s*(?:风扇|扇)/, min: 1, max: 4 },
    { key: '屏', re: /(\d{2}(?:\.\d)?)\s*(?:英寸|寸)/, min: 10, max: 32 }
  ];

  function guessFor(label, text) {
    for (var i = 0; i < GUESS.length; i++) {
      var g = GUESS[i];
      if (String(label).indexOf(g.key) < 0) continue;
      var m = String(text).match(g.re);
      if (!m) continue;
      var v = Number(m[1]);
      if (v >= g.min && v <= g.max) return v;
    }
    return null;
  }

  /** 主函数：把一段粘贴文字解析成候选列表。 */
  function parse(text, fields) {
    var lines = String(text == null ? '' : text)
      .replace(/\r\n?/g, '\n')
      .split('\n')
      .map(clean)
      .filter(function (s) { return s; });

    var items = [];
    var pending = null;   // 已认出名称、等价格
    var bucket = [];      // 名称后面那几行，可能含规格
    var loose = [];       // 没配上名称的价格
    var absorb = 0;       // 刚用「价格在先」配好一件，紧跟的标题行算它的规格
    var noise = 0;

    function commit(name, price, extra) {
      var nm = clean(name).replace(/[¥￥]\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?\s*$/, '').trim();
      if (nm.length < 2) return;
      items.push({ name: nm, price: price, extra: extra || '' });
    }

    function guessNumbers(item) {
      var out = {};
      if (!fields || !fields.length) return out;
      var src = item.name + ' ' + item.extra;
      fields.forEach(function (f) {
        if (f.type !== 'number') return;
        var v = guessFor(f.label || f.key, src);
        if (v !== null) out[f.key] = v;
      });
      return out;
    }

    for (var i = 0; i < lines.length; i++) {
      var s = lines[i];
      var p = priceOf(s);

      if (p) {
        var name = p.head && isTitleLike(p.head) ? p.head : null;
        if (name) {                       // 「名称 ¥5999」挤在同一行
          commit(name, p.value, bucket.join(' '));
          pending = null; bucket = []; absorb = 0;
          continue;
        }
        if (pending) {                    // 正常情况：名称在上，价格在下
          commit(pending, p.value, bucket.join(' '));
          pending = null; bucket = []; absorb = 0;
        } else if (items.length && items[items.length - 1].price === 0) {
          items[items.length - 1].price = p.value;   // 名称已收下但没价格
          items[items.length - 1].guessed = guessNumbers(items[items.length - 1]);
        } else {
          loose.push(p.value);
          absorb = 0;                     // 出现新价格，上一件的规格区到此结束
        }
        continue;
      }

      if (HEADER.test(s)) continue;
      if (NOISE.test(s)) { noise++; continue; }

      if (isTitleLike(s)) {
        if (absorb > 0) {                 // 紧跟的规格行，归上一件
          var nxt = lines[i + 1];
          if (nxt && priceOf(nxt)) {      // 下一行就是价格 → 这其实是下一件
            absorb = 0; pending = s; bucket = [];
            continue;
          }
          var last = items[items.length - 1];
          if (last) last.extra = clean(last.extra + ' ' + s);
          absorb--;
          continue;
        }
        if (pending) {                    // 同一张卡的第二行标题 → 当规格
          bucket.push(s);
          continue;
        }
        if (loose.length) {               // 价格写在名称前面
          commit(s, loose.shift(), '');
          absorb = 1;
          continue;
        }
        pending = s;
        bucket = [];
        continue;
      }

      if (pending && bucket.length < 6) bucket.push(s);
    }
    if (pending) commit(pending, 0, bucket.join(' '));

    // 去重：同名保留第一个（通常是最完整的那条）
    var seen = {}, uniq = [];
    items.forEach(function (it) {
      var k = it.name.replace(/\s/g, '');
      if (seen[k]) { if (!seen[k].price && it.price) seen[k].price = it.price; return; }
      seen[k] = it; uniq.push(it);
    });

    // 补上没配到名称的零散价格（按顺序填空缺），仍不确定就丢掉
    uniq.forEach(function (it) {
      if (!it.price && loose.length) it.price = loose.shift();
      if (it.price) it.guessed = guessNumbers(it);
    });

    return {
      items: uniq.filter(function (it) { return it.name && it.price > 0; }),
      unpriced: uniq.filter(function (it) { return !it.price; }).map(function (it) { return it.name; }),
      noiseLines: noise
    };
  }

  return { parse: parse, priceOf: priceOf, guessFor: guessFor, GUESS: GUESS };
});
