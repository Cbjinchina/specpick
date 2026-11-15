"""营养缺口 → 该买什么吃。

和主引擎的关系：主引擎回答「这几个候选里挑哪个」，这里回答反过来的问题——
「我缺什么，该往什么方向买」。

数据口径
--------
* 含量为每 100g 可食部的常见参考值（量级参照《中国食物成分表》第 6 版与 USDA
  公开数据，取常见品种的中位量级），**只用于同表内相对比较**，不用于精算摄入量；
* NRV 是《预包装食品营养标签通则》的每日参考值，用来把「吃一份能补到多少」算成百分比；
* `max_g` 是这个东西「一次别超过多少克」：猪肝的维A 是日需的 60 倍/100g，
  按用户选的 200g 直接算会给出伤人的建议，所以算分前先按上限截断；
* 这张表是内置常量，不联网、不随机，和 web/engine.js 里的表必须逐字一致
  （web/verify.py 会交叉校验）。

⚠️ 这不是医学建议。真的怀疑自己缺什么，看化验单，别靠一张食物表。
"""

from __future__ import annotations

from typing import Any

# (key, 名称, 单位, 每日参考值 NRV)
NUTRIENTS: list[tuple[str, str, str, float]] = [
    ("vc", "维生素C", "mg", 100.0),
    ("fiber", "膳食纤维", "g", 25.0),
    ("k", "钾", "mg", 2000.0),
    ("folate", "叶酸", "µg", 400.0),
    ("ca", "钙", "mg", 800.0),
    ("fe", "铁", "mg", 15.0),
    ("va", "维生素A", "µg", 800.0),
]

_COLS = ("vc", "k", "fiber", "folate", "ca", "fe", "va")

# 列顺序：名称, 类别, vc, k, fiber, folate, ca, fe, va, 糖, 单次上限(g，0=不设)
FOODS_RAW: list[tuple] = [
    ("冬枣", "水果", 243, 195, 1.9, 20, 22, 1.2, 40, 28, 0),
    ("猕猴桃", "水果", 62, 312, 2.6, 25, 27, 1.2, 6, 10, 0),
    ("番石榴", "水果", 68, 235, 5.9, 49, 13, 0.2, 31, 8, 0),
    ("草莓", "水果", 47, 131, 1.1, 24, 18, 1.8, 5, 7, 0),
    ("橙子", "水果", 33, 159, 1.8, 30, 20, 0.4, 13, 11, 0),
    ("木瓜", "水果", 43, 182, 1.7, 44, 12, 0.3, 47, 8, 0),
    ("芒果", "水果", 23, 138, 1.3, 43, 11, 0.2, 150, 14, 0),
    ("圣女果", "水果", 14, 179, 1.8, 15, 10, 0.5, 92, 4, 0),
    ("蓝莓", "水果", 10, 77, 2.4, 6, 6, 0.3, 3, 10, 0),
    ("香蕉", "水果", 8, 256, 1.2, 20, 7, 0.4, 5, 15, 0),
    ("牛油果", "水果", 8, 599, 6.7, 81, 12, 0.6, 3, 1, 0),
    ("梨", "水果", 6, 92, 3.1, 8, 9, 0.5, 6, 10, 0),
    ("苹果", "水果", 4, 119, 1.7, 3, 4, 0.6, 3, 13, 0),
    ("火龙果", "水果", 3, 20, 1.6, 8, 6, 0.3, 5, 13, 0),
    ("彩椒", "蔬菜", 72, 142, 1.4, 46, 10, 0.3, 57, 4, 0),
    ("西兰花", "蔬菜", 51, 316, 2.6, 63, 50, 0.7, 60, 3, 0),
    ("菠菜", "蔬菜", 32, 558, 2.2, 194, 66, 2.9, 487, 1, 0),
    ("红薯", "蔬菜", 26, 130, 2.2, 12, 23, 0.5, 125, 6, 0),
    ("胡萝卜", "蔬菜", 5, 320, 2.8, 12, 32, 0.5, 688, 5, 0),
    ("燕麦", "主食豆类", 0, 214, 10.6, 26, 54, 3.6, 0, 1, 0),
    ("杂豆（鹰嘴豆）", "主食豆类", 1, 291, 7.6, 172, 49, 2.9, 1, 3, 0),
    ("北豆腐", "主食豆类", 0, 106, 0.5, 27, 164, 1.9, 0, 0, 0),
    ("猪肝", "肉蛋奶", 20, 235, 0, 236, 6, 22.6, 4972, 0, 30),
    ("瘦牛肉", "肉蛋奶", 0, 284, 0, 6, 6, 2.8, 0, 0, 0),
    ("鸡蛋", "肉蛋奶", 0, 154, 0, 47, 56, 1.6, 234, 0, 0),
    ("牛奶", "肉蛋奶", 1, 109, 0, 5, 104, 0.3, 24, 5, 300),
    ("杏仁", "坚果", 0, 705, 12.2, 30, 97, 2.1, 0, 4, 30),
]

FOODS: list[dict[str, Any]] = []
for _row in FOODS_RAW:
    _name, _cat = _row[0], _row[1]
    _per = {col: float(_row[2 + i]) for i, col in enumerate(_COLS)}
    FOODS.append({"name": _name, "cat": _cat, "per100": _per,
                  "sugar": float(_row[9]), "max_g": float(_row[10])})

NRV = {k: nrv for k, _, _, nrv in NUTRIENTS}
LABEL = {k: label for k, label, _, _ in NUTRIENTS}
UNIT = {k: unit for k, _, unit, _ in NUTRIENTS}

# 用户说「我缺什么」时，常见信号 → 该关注的营养素。
# 症状不等于缺乏，只是给个起点，确诊靠化验。
SIGNS = [
    ("牙龈出血、伤口好得慢、总像要感冒", ["vc"]),
    ("蹲下起来发晕、月经量大、吃素为主", ["fe"]),
    ("腿爱抽筋、口重、蔬菜吃得少", ["k"]),
    ("几天才上一次厕所、总靠外卖", ["fiber"]),
    ("在备孕 / 已经怀孕", ["folate"]),
    ("不喝奶、很少晒太阳、腰背酸", ["ca"]),
    ("晚上看不清、眼睛干、皮肤干", ["va"]),
]

NUT_CATS = ["水果", "蔬菜", "主食豆类", "肉蛋奶", "坚果"]


def _grams(food: dict[str, Any], portion: float) -> float:
    """这一顿实际按多少克算：用户选的份量，超过这个东西的单次上限就截断。"""
    cap = food["max_g"]
    return portion if cap <= 0 else min(portion, cap)


def plan(
    targets: list[str],
    portion: float = 200,
    low_sugar: bool = False,
    limit_k: bool = False,
    cats: list[str] | None = None,
    top: int = 8,
) -> dict[str, Any]:
    """按目标营养素给食物排序，并给一份「几样搭着吃」的组合。

    排序口径不是简单的「含量最高」，而是「按你一次吃的份量，能补掉多少缺口」：
    含 243mg/100g 的冬枣吃 200g 就超了，含 33mg 的橙子吃 200g 只有 66%，
    超出的部分不算额外价值（缺口不会因为你吃撑了就补两次）。
    """
    keys: list[str] = []
    for t in targets or []:
        if t in NRV and t not in keys:
            keys.append(t)
    if not keys:
        return {"targets": [], "portion": portion, "rows": [],
                "combo": {"items": [], "cover": {}}, "gaps": [],
                "error": "先选至少一个想补的营养素"}

    pool = [f for f in FOODS if not cats or f["cat"] in cats]

    rows: list[dict[str, Any]] = []
    for food in pool:
        per100 = {k: food["per100"][k] / NRV[k] * 100.0 for k in keys}  # 每 100g 能补到的百分比
        grams = _grams(food, portion)
        pcts = {k: per100[k] * grams / 100.0 for k in keys}
        cover = sum(min(1.0, pcts[k] / 100.0) for k in keys) / len(keys)
        flags: list[str] = []
        if limit_k and food["per100"]["k"] >= 300:
            flags.append("钾偏高")
        if low_sugar and food["sugar"] >= 15:
            flags.append("糖偏高")
        score = cover
        if "钾偏高" in flags:
            score *= 0.6
        if "糖偏高" in flags:
            score *= 0.7
        rows.append({
            "name": food["name"], "cat": food["cat"], "sugar": food["sugar"],
            "used": grams, "capped": grams < portion,
            "pct": pcts, "pct100": per100,
            "score": score, "flags": flags,
        })

    rows.sort(key=lambda r: (-r["score"], r["sugar"], r["name"]))
    best_by_target = {k: max([r["pct"][k] for r in rows], default=0.0) for k in keys}
    # 一样都补不到 25%（约四分之一日需），说明这类食物本身就不是好来源
    gaps = [k for k in keys if best_by_target[k] < 25.0]

    return {
        "targets": [
            {"key": k, "label": LABEL[k], "unit": UNIT[k], "nrv": NRV[k],
             "best_pct": best_by_target[k]}
            for k in keys
        ],
        "portion": portion,
        "rows": rows[:top],
        "combo": _combo(rows, keys),
        "gaps": gaps,
    }


def _combo(rows: list[dict[str, Any]], keys: list[str]) -> dict[str, Any]:
    """贪心凑一份组合：每次挑「最快填掉剩下缺口」的那样，每样 100g（受该食物上限约束）。"""
    picked: list[dict[str, Any]] = []
    cover = {k: 0.0 for k in keys}
    remaining = list(rows)
    for _ in range(3):
        best, best_gain, best_g = None, 0.0, 0.0
        for row in remaining:
            grams = 100.0 if row["used"] >= 100.0 else row["used"]
            gain = 0.0   # 有效补上的部分（超过 100% 不加分）
            waste = 0.0  # 白吃进去的部分
            for k in keys:
                add = row["pct100"][k] * grams / 100.0
                now = min(1.0, cover[k] / 100.0)
                nxt = min(1.0, (cover[k] + add) / 100.0)
                gain += nxt - now
                waste += max(0.0, cover[k] + add - 100.0) / 100.0
            value = gain - 0.25 * waste   # 够用就好：同样能补齐，选浪费少的
            if value > best_gain + 1e-9:
                best, best_gain, best_g = row, value, grams
        if best is None:
            break
        add = {k: best["pct100"][k] * best_g / 100.0 for k in keys}
        picked.append({"name": best["name"], "cat": best["cat"], "g": best_g, "pct": add})
        for k in keys:
            cover[k] += add[k]
        remaining = [r for r in remaining if r is not best]
    return {"items": picked, "cover": {k: cover[k] for k in keys}}
