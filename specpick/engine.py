"""specpick 核心引擎：纯标准库，无网络、无随机数、无第三方依赖。

输入是两份 TOML：needs.toml（我的需求规格）与 items.toml（少量候选）。
输出是确定性的裁决：谁赢、谁被淘汰、为什么、要改什么才能翻盘。
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Number = int | float

# 候选这一项可以是纯数字，也可以是从商品页抄下来的一整句原文。
# 只认第一个数字，后面紧跟 万 / 千 / k / w 时换算成绝对量。
_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_SCALE = {"万": 10000, "w": 10000, "W": 10000, "千": 1000, "k": 1000, "K": 1000}


def to_num(value: Any, ranks: list[str] | None = None) -> float | None:
    """把候选填的值变成一个能比大小的数字；变不出来就返回 None（= 这项没数据）。

    - 纯数字：原样返回
    - 带单位的原文：抽第一个数字，「8GB」→ 8，「约 28,000 分」→ 28000，「1.2万」→ 12000
    - 档位：返回该词在顺序表里的位次（0 起），「高」在 低/中/高 里 = 2
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if ranks:
        flat = re.sub(r"\s+", "", text).lower()
        for i, rk in enumerate(ranks):
            key = re.sub(r"\s+", "", str(rk)).lower()
            if key and (key == flat or key in flat):
                return float(i)
        return None  # 定义了档位就只认档位词，不能把「4」当第 5 档
    m = _NUM_RE.search(text)
    if not m:
        return None
    try:
        num = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    tail = text[m.end():m.end() + 1]
    if tail in _SCALE:
        num *= _SCALE[tail]
    return num


@dataclass
class Rejection:
    item_id: str
    name: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class Scored:
    item_id: str
    name: str
    price: Number
    total: float
    parts: dict[str, float] = field(default_factory=dict)


@dataclass
class Move:
    """单变量反事实：改动一个字段刚好反超所需的值。"""

    metric: str
    current: float
    target: float
    relative: float  # 变化量占该指标取值范围的比例


@dataclass
class Result:
    case_id: str
    title: str
    scene: str
    budget: Number
    weights: dict[str, Number]
    directions: dict[str, str]
    hard_rules: list[dict[str, Any]]
    accepted: list[Scored] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)
    sensitivity: dict[str, Any] = field(default_factory=dict)

    @property
    def winner(self) -> Scored | None:
        return self.accepted[0] if self.accepted else None

    @property
    def runner_up(self) -> Scored | None:
        return self.accepted[1] if len(self.accepted) > 1 else None


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_case(case_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    needs = load_toml(case_dir / "needs.toml")
    items = load_toml(case_dir / "items.toml").get("item", [])
    return needs, list(items)


def validate_case(needs: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
    """返回格式错误列表；空列表表示可以安全计算。"""
    errors: list[str] = []
    for key in ("title", "budget", "weights", "directions"):
        if key not in needs:
            errors.append(f"needs.toml 缺少 {key}")
    if not items:
        errors.append("items.toml 没有任何 [[item]]")
    weights = needs.get("weights", {})
    directions = needs.get("directions", {})
    for metric, weight in weights.items():
        if metric not in directions:
            errors.append(f"权重 {metric} 缺少 directions 方向定义")
        if directions.get(metric) not in ("higher", "lower"):
            errors.append(f"directions.{metric} 必须是 higher 或 lower")
        if not isinstance(weight, (int, float)) or weight < 0:
            errors.append(f"weights.{metric} 必须是非负数")
    for rule in needs.get("hard", []):
        for key in ("field", "op", "value", "label"):
            if key not in rule:
                errors.append(f"hard 规则缺少 {key}")
        if rule.get("op") not in OPS:
            errors.append(f"不支持的操作符：{rule.get('op')}")
    for i, item in enumerate(items):
        for key in ("id", "name", "price"):
            if key not in item:
                errors.append(f"第 {i + 1} 个候选缺少 {key}")
        for metric in weights:
            if metric not in item:
                errors.append(f"候选 {item.get('name', i)} 缺少指标 {metric}")
        for rule in needs.get("hard", []):
            if rule.get("field") not in item:
                errors.append(f"候选 {item.get('name', i)} 缺少硬约束字段 {rule['field']}")
    return errors


def _compare(actual: Any, op: str, expected: Any, ranks: list[str] | None = None) -> bool | None:
    """返回 True/False；返回 None 表示这一项的值里读不出可比的数字。"""
    if op in ("in", "not_in"):
        return OPS[op](actual, expected)
    a = to_num(actual, ranks)
    b = to_num(expected)
    if op in ("==", "!="):
        if a is not None and b is not None:
            return OPS[op](a, b)
        return OPS[op](str(actual).strip(), str(expected).strip())
    if a is None or b is None:
        return None
    return OPS[op](a, b)


def _op_le(a, b):
    return a <= b


def _op_lt(a, b):
    return a < b


def _op_ge(a, b):
    return a >= b


def _op_gt(a, b):
    return a > b


def _op_eq(a, b):
    return a == b


def _op_ne(a, b):
    return a != b


def _op_in(a, b):
    return a in b


def _op_not_in(a, b):
    return a not in b


OPS = {
    "<=": _op_le,
    "<": _op_lt,
    ">=": _op_ge,
    ">": _op_gt,
    "==": _op_eq,
    "!=": _op_ne,
    "in": _op_in,
    "not_in": _op_not_in,
}


def hard_reasons(item: dict[str, Any], needs: dict[str, Any]) -> list[str]:
    """逐条记录淘汰理由，不静默丢弃任何一个候选。

    值可以是「8GB」这种原文，比较时先抽数字；抽不出数字也不当作失败，
    而是明说「这项没法验证」——不能因为格式问题把候选冤杀掉。
    """
    reasons: list[str] = []
    ranks = needs.get("ranks", {})
    budget = needs["budget"]
    price = to_num(item["price"])
    if price is not None and budget is not None and price > float(budget):
        reasons.append(f"价格 ¥{item['price']} 超出预算 ¥{budget}")
    for rule in needs.get("hard", []):
        f, op, expected, label = rule["field"], rule["op"], rule["value"], rule["label"]
        actual = item.get(f)
        if actual is None:
            reasons.append(f"缺少 {f} 数据，无法验证「{label}」")
            continue
        ok = _compare(actual, op, expected, ranks.get(f))
        if ok is None:
            reasons.append(f"「{label}」这一项填的是「{actual}」，读不出数字，无法验证")
        elif not ok:
            reasons.append(f"{label}（实际 {actual}，要求 {op} {expected}）")
    return reasons


def _bounds(
    item_values: list[float | None],
) -> tuple[float, float] | None:
    """只用真正有数据的候选定取值范围。

    返回 None 表示这一项比不了，对所有人都不计分：
    - 一件都没数据；
    - 多件候选里只有一件有数据 —— 只有一个点，定不出「高低」，给了它满分等于白送。
    """
    known = [v for v in item_values if v is not None]
    if not known:
        return None
    if len(known) < 2 and len(item_values) > 1:
        return None
    return min(known), max(known)


def _norm(value: Number, low: float, high: float, direction: str) -> float:
    if high == low:
        return 1.0
    ratio = (float(value) - low) / (high - low)
    return ratio if direction == "higher" else 1.0 - ratio


def score_items(
    items: list[dict[str, Any]],
    weights: dict[str, Number],
    directions: dict[str, str],
    ranks: dict[str, list[str]] | None = None,
) -> list[Scored]:
    """按权重打分。

    缺数据的候选不会被打成 0 分：它在剩余项上按权重等比折算总分，
    也就是「这项不知道，就只按我知道的评」。
    """
    ranks = ranks or {}
    metrics = list(weights)
    values = {m: [to_num(it.get(m), ranks.get(m)) for it in items] for m in metrics}
    bounds = {m: _bounds(values[m]) for m in metrics}
    # 比不了的项（没数据 / 只有一个人有）对整个评分体系都不算权重，否则会把别的项放大
    total_w = sum(float(weights[m]) for m in metrics if bounds[m] is not None)
    scored: list[Scored] = []
    for idx, item in enumerate(items):
        parts: dict[str, float | None] = {}
        avail = 0.0
        for metric in metrics:
            weight = float(weights[metric])
            b = bounds[metric]
            v = values[metric][idx]
            if b is None or v is None:
                parts[metric] = None
                continue
            parts[metric] = round(weight * _norm(v, b[0], b[1], directions[metric]), 4)
            avail += weight
        known = sum(p for p in parts.values() if p is not None)
        if avail <= 0:
            total = 0.0
        elif avail < total_w:
            total = round(known * total_w / avail, 4)
        else:
            total = round(known, 4)
        scored.append(
            Scored(
                item_id=str(item["id"]),
                name=str(item["name"]),
                price=item["price"],
                total=total,
                parts=parts,
            )
        )
    scored.sort(key=lambda s: (-s.total, s.price, s.item_id))
    return scored


def counterfactual(
    items: list[dict[str, Any]],
    winner: Scored,
    runner_up: Scored,
    weights: dict[str, Number],
    directions: dict[str, str],
    ranks: dict[str, list[str]] | None = None,
) -> list[Move]:
    """解析求解：只改一个字段，最少要改到多少才能反超。"""
    ranks = ranks or {}
    gap = winner.total - runner_up.total
    if gap <= 0:
        return []
    by_id = {str(it["id"]): it for it in items}
    challenger = by_id[runner_up.item_id]
    bounds = {m: _bounds([to_num(it.get(m), ranks.get(m)) for it in items]) for m in weights}
    moves: list[Move] = []
    for metric, weight in weights.items():
        w = float(weight)
        if w <= 0:
            continue
        b = bounds[metric]
        if b is None:
            continue
        low, high = b
        if high == low:
            continue
        current = to_num(challenger.get(metric), ranks.get(metric))
        if current is None:
            continue  # 这件候选本来就没填，谈不上「改到多少」
        needed = gap / w  # 归一化分数需要提高的量
        current_norm = _norm(current, low, high, directions[metric])
        target_norm = current_norm + needed
        if target_norm > 1.0 + 1e-4:
            continue  # 单改这个字段也追不上
        if directions[metric] == "higher":
            target = low + target_norm * (high - low)
        else:
            target = high - target_norm * (high - low)
        target = max(low, min(high, target))  # 不外推到样本取值范围之外
        delta = abs(target - current)
        moves.append(
            Move(
                metric=metric,
                current=current,
                target=round(target, 2),
                relative=round(delta / (high - low), 4),
            )
        )
    moves.sort(key=lambda m: m.relative)
    return moves


def sensitivity(
    items: list[dict[str, Any]],
    weights: dict[str, Number],
    directions: dict[str, str],
    ranks: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """每个权重 ±25%，看第一名会不会换人。"""
    baseline = score_items(items, weights, directions, ranks)[0].item_id
    trials = 0
    flips: list[str] = []
    for metric, original in weights.items():
        for factor in (0.75, 1.25):
            perturbed = dict(weights)
            perturbed[metric] = float(original) * factor
            trials += 1
            top = score_items(items, perturbed, directions, ranks)[0].item_id
            if top != baseline:
                flips.append(f"{metric} ×{factor}")
    if not flips:
        verdict = "稳健"
    elif len(flips) <= 1:
        verdict = "基本稳健"
    else:
        verdict = "脆弱"
    return {"baseline": baseline, "trials": trials, "flips": flips, "verdict": verdict}


def decide(case_dir: Path) -> tuple[Result, list[str]]:
    needs, items = load_case(case_dir)
    errors = validate_case(needs, items)
    if errors:
        return Result(
            case_id=case_dir.name,
            title=needs.get("title", ""),
            scene=needs.get("scene", ""),
            budget=needs.get("budget", 0),
            weights={},
            directions={},
            hard_rules=[],
        ), errors

    eligible: list[dict[str, Any]] = []
    rejected: list[Rejection] = []
    for item in items:
        reasons = hard_reasons(item, needs)
        if reasons:
            rejected.append(Rejection(str(item["id"]), str(item["name"]), reasons))
        else:
            eligible.append(item)

    accepted = (
        score_items(eligible, needs["weights"], needs["directions"], needs.get("ranks"))
        if eligible else []
    )
    moves: list[Move] = []
    sens: dict[str, Any] = {}
    if len(accepted) >= 2:
        moves = counterfactual(
            eligible, accepted[0], accepted[1],
            needs["weights"], needs["directions"], needs.get("ranks"),
        )
        sens = sensitivity(
            eligible, needs["weights"], needs["directions"], needs.get("ranks"),
        )

    return (
        Result(
            case_id=case_dir.name,
            title=needs["title"],
            scene=needs.get("scene", ""),
            budget=needs["budget"],
            weights=needs["weights"],
            directions=needs["directions"],
            hard_rules=needs.get("hard", []),
            accepted=accepted,
            rejected=rejected,
            moves=moves,
            sensitivity=sens,
        ),
        [],
    )
