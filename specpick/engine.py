"""specpick 核心引擎：纯标准库，无网络、无随机数、无第三方依赖。

输入是两份 TOML：needs.toml（我的需求规格）与 items.toml（少量候选）。
输出是确定性的裁决：谁赢、谁被淘汰、为什么、要改什么才能翻盘。
"""

from __future__ import annotations

import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
    shapes: dict[str, dict[str, Any]]
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
    for metric, cfg in (needs.get("shapes") or {}).items():
        if metric not in weights:
            errors.append(f"shapes.{metric} 没有对应的权重项")
            continue
        shape = _shape_of(cfg)
        if (cfg or {}).get("shape") and (cfg or {}).get("shape") not in SHAPES:
            errors.append(f"shapes.{metric}.shape 只能是 {' / '.join(SHAPES)}")
        if shape == "target":
            for key in ("lo", "hi", "tol"):
                v = (cfg or {}).get(key)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    errors.append(f"shapes.{metric} 按「越接近越好」算，必须给数字 {key}")
            tol = (cfg or {}).get("tol")
            if isinstance(tol, (int, float)) and not isinstance(tol, bool) and tol <= 0:
                errors.append(f"shapes.{metric}.tol 必须大于 0")
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


# 「同一个数字怎么比」的四种比法。默认 span：按这批候选里的最高最低拉一条线。
#   span    按范围     最高分 1、最低分 0，中间按比例（现在的默认）
#   log     对数刻度   跨度很大时（销量 200 对 12 万）不把小的全压成 0
#   ordinal 按名次     只看谁比谁强，不看强多少，一个极端值也带不偏
#   target  越接近越好 有个最舒服的区间，两头都扣分（重量、尺寸、距离）
SHAPES = ("span", "log", "ordinal", "target")


def _shape_of(cfg: dict[str, Any] | None) -> str:
    s = str((cfg or {}).get("shape") or "span")
    return s if s in SHAPES else "span"


def _make_scorer(
    values: list[float | None], direction: str, cfg: dict[str, Any] | None
) -> tuple[Callable[[float], float] | None, dict[str, Any]]:
    """造这一项的计分器。返回 (score, meta)。

    score 为 None 表示这项对所有人都不算分（没数据 / 一个点定不出高低）。
    meta 里带上形状和边界，反事实求解要用它把「要提多少分」换算回「要改到多少」。
    """
    cfg = cfg or {}
    shape = _shape_of(cfg)
    known = [v for v in values if v is not None]
    if not known:
        return None, {"shape": shape}

    if shape == "target":
        try:
            lo, hi, tol = float(cfg["lo"]), float(cfg["hi"]), float(cfg["tol"])
        except (KeyError, TypeError, ValueError):
            return None, {"shape": "target", "bad": True}
        if lo > hi:
            lo, hi = hi, lo
        if tol <= 0:
            return None, {"shape": "target", "bad": True}

        def score_target(v: float) -> float:
            if v < lo:
                d = lo - v
            elif v > hi:
                d = v - hi
            else:
                return 1.0
            return max(0.0, 1.0 - d / tol)

        # 区间是绝对值，一件有数据也能比，不需要「至少两个点」
        return score_target, {"shape": "target", "lo": lo, "hi": hi, "tol": tol}

    if len(known) < 2 and len(values) > 1:
        return None, {"shape": shape}

    if shape == "ordinal":
        ranks = sorted(set(known))
        if len(ranks) < 2:
            # 大家一样：定不出名次，但也不能因此把这一项判成「没数据」
            return (lambda v: 1.0), {"shape": "ordinal", "flat": True}
        pos = {v: i / (len(ranks) - 1) for i, v in enumerate(ranks)}

        def score_ordinal(v: float) -> float:
            r = pos[v]
            return r if direction == "higher" else 1.0 - r

        return score_ordinal, {"shape": "ordinal"}

    # 对数是给正数用的。出现 0 / 负数就退回线性，并在 meta 里标明，好让报告解释
    use_log = shape == "log" and all(v > 0 for v in known)
    tf: Callable[[float], float] = (lambda v: math.log10(v)) if use_log else float
    tvals = [tf(v) if v is not None else None for v in values]
    low = min(x for x in tvals if x is not None)
    high = max(x for x in tvals if x is not None)

    def score_span(v: float) -> float:
        if high == low:
            return 1.0
        ratio = (tf(v) - low) / (high - low)
        return ratio if direction == "higher" else 1.0 - ratio

    return score_span, {
        "shape": "log" if use_log else "span",
        "log": use_log,
        "low": low,
        "high": high,
        "log_fallback": shape == "log" and not use_log,
    }



def score_items(
    items: list[dict[str, Any]],
    weights: dict[str, Number],
    directions: dict[str, str],
    ranks: dict[str, list[str]] | None = None,
    shapes: dict[str, dict[str, Any]] | None = None,
) -> list[Scored]:
    """按权重打分。

    缺数据的候选不会被打成 0 分：它在剩余项上按权重等比折算总分，
    也就是「这项不知道，就只按我知道的评」。
    """
    ranks = ranks or {}
    shapes = shapes or {}
    metrics = list(weights)
    values = {m: [to_num(it.get(m), ranks.get(m)) for it in items] for m in metrics}
    scorers = {
        m: _make_scorer(values[m], directions.get(m, "higher"), shapes.get(m))
        for m in metrics
    }
    # 比不了的项（没数据 / 只有一个人有）对整个评分体系都不算权重，否则会把别的项放大
    total_w = sum(float(weights[m]) for m in metrics if scorers[m][0] is not None)
    scored: list[Scored] = []
    for idx, item in enumerate(items):
        parts: dict[str, float | None] = {}
        avail = 0.0
        for metric in metrics:
            fn = scorers[metric][0]
            weight = float(weights[metric])
            v = values[metric][idx]
            if fn is None or v is None:
                parts[metric] = None
                continue
            parts[metric] = round(weight * fn(v), 4)
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
    shapes: dict[str, dict[str, Any]] | None = None,
) -> list[Move]:
    """解析求解：只改一个字段，最少要改到多少才能反超。"""
    ranks = ranks or {}
    shapes = shapes or {}
    gap = winner.total - runner_up.total
    if gap <= 0:
        return []
    by_id = {str(it["id"]): it for it in items}
    challenger = by_id[runner_up.item_id]
    info = {
        m: _make_scorer(
            [to_num(it.get(m), ranks.get(m)) for it in items],
            directions.get(m, "higher"),
            shapes.get(m),
        )
        for m in weights
    }
    moves: list[Move] = []
    for metric, weight in weights.items():
        w = float(weight)
        fn, meta = info[metric]
        if w <= 0 or fn is None:
            continue
        if meta.get("shape") == "ordinal":
            # 名次型的「改到多少」取决于别人改不改，说不清就不说
            continue
        current = to_num(challenger.get(metric), ranks.get(metric))
        if current is None:
            continue  # 这件候选本来就没填，谈不上「改到多少」
        needed = gap / w  # 归一化分数需要提高的量
        target_score = fn(current) + needed
        if target_score > 1.0 + 1e-4:
            continue  # 单改这个字段也追不上

        if meta.get("shape") == "target":
            lo, hi, tol = meta["lo"], meta["hi"], meta["tol"]
            if lo <= current <= hi:
                continue  # 已经在最舒服的区间里，再改也加不了分
            dist = (lo - current) if current < lo else (current - hi)
            new_dist = max(0.0, dist - needed * tol)
            target = (lo - new_dist) if current < lo else (hi + new_dist)
            scale = tol
        else:
            low, high = meta["low"], meta["high"]
            if high == low:
                continue
            if directions.get(metric) == "higher":
                t = low + target_score * (high - low)
            else:
                t = high - target_score * (high - low)
            if meta.get("log"):
                low, high = 10 ** low, 10 ** high
                target = 10 ** t
            else:
                target = t
            target = max(low, min(high, target))  # 不外推到样本取值范围之外
            scale = high - low

        delta = abs(target - current)
        moves.append(
            Move(
                metric=metric,
                current=current,
                target=round(target, 2),
                relative=round(delta / scale, 4) if scale else 0.0,
            )
        )
    moves.sort(key=lambda m: m.relative)
    return moves


def sensitivity(
    items: list[dict[str, Any]],
    weights: dict[str, Number],
    directions: dict[str, str],
    ranks: dict[str, list[str]] | None = None,
    shapes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """每个权重 ±25%，看第一名会不会换人。"""
    shapes = shapes or {}
    baseline = score_items(items, weights, directions, ranks, shapes)[0].item_id
    trials = 0
    flips: list[str] = []
    for metric, original in weights.items():
        for factor in (0.75, 1.25):
            perturbed = dict(weights)
            perturbed[metric] = float(original) * factor
            trials += 1
            top = score_items(items, perturbed, directions, ranks, shapes)[0].item_id
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
            shapes={},
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

    shapes = needs.get("shapes") or {}
    accepted = (
        score_items(eligible, needs["weights"], needs["directions"], needs.get("ranks"), shapes)
        if eligible else []
    )
    moves: list[Move] = []
    sens: dict[str, Any] = {}
    if len(accepted) >= 2:
        moves = counterfactual(
            eligible, accepted[0], accepted[1],
            needs["weights"], needs["directions"], needs.get("ranks"), shapes,
        )
        sens = sensitivity(
            eligible, needs["weights"], needs["directions"], needs.get("ranks"), shapes,
        )

    return (
        Result(
            case_id=case_dir.name,
            title=needs["title"],
            scene=needs.get("scene", ""),
            budget=needs["budget"],
            weights=needs["weights"],
            directions=needs["directions"],
            shapes=shapes,
            hard_rules=needs.get("hard", []),
            accepted=accepted,
            rejected=rejected,
            moves=moves,
            sensitivity=sens,
        ),
        [],
    )
