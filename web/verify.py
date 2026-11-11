"""双实现一致性校验：Python 权威引擎 vs web/engine.js。

手机网页版是同一套算法的第二个实现。任何一边改了算法，这个脚本都会
在 CI 里报错，避免「网页说选 A、命令行说选 B」。

用法：python web/verify.py   （需要 node，GitHub Actions runner 自带）
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from specpick.engine import (  # noqa: E402
    counterfactual,
    hard_reasons,
    load_case,
    score_items,
    sensitivity,
    validate_case,
)

REAL_CASES = [
    ("kitchen", ROOT / "examples" / "kitchen-rack"),
    ("laptop", ROOT / "playground" / "examples" / "laptop"),
    ("gpu", ROOT / "playground" / "examples" / "gpu"),
]


def synthetic() -> list[tuple[str, dict, list[dict]]]:
    """覆盖引擎边界的合成案例，用 dict 构造，不需要 TOML 文件。"""
    out = []

    out.append((
        "all_rejected",
        {"title": "预算太小", "budget": 10,
         "weights": {"price": 1}, "directions": {"price": "lower"}},
        [{"id": "A", "name": "甲", "price": 20},
         {"id": "B", "name": "乙", "price": 30},
         {"id": "C", "name": "丙", "price": 40}],
    ))

    out.append((
        "single_candidate",
        {"title": "只有一个候选", "budget": 100,
         "weights": {"price": 1, "quality": 2},
         "directions": {"price": "lower", "quality": "higher"}},
        [{"id": "A", "name": "唯一", "price": 50, "quality": 4}],
    ))

    out.append((
        "exact_tie",
        {"title": "完全打平", "budget": 100,
         "weights": {"price": 2, "quality": 3},
         "directions": {"price": "lower", "quality": "higher"}},
        [{"id": "A", "name": "甲", "price": 50, "quality": 4},
         {"id": "B", "name": "乙", "price": 50, "quality": 4}],
    ))

    out.append((
        "zero_weight_and_equal_bounds",
        {"title": "零权重与取值范围相同", "budget": 100,
         "weights": {"price": 2, "ignored": 0, "same": 3},
         "directions": {"price": "lower", "ignored": "higher", "same": "higher"},
         "hard": [{"field": "same", "op": ">=", "value": 1, "label": "至少 1"}]},
        [{"id": "A", "name": "甲", "price": 30, "ignored": 1, "same": 5},
         {"id": "B", "name": "乙", "price": 60, "ignored": 9, "same": 5}],
    ))

    out.append((
        "text_hard_rules",
        {"title": "文字型硬约束", "budget": 500,
         "weights": {"price": 1, "score": 4},
         "directions": {"price": "lower", "score": "higher"},
         "hard": [
             {"field": "os", "op": "==", "value": "Windows", "label": "必须 Windows"},
             {"field": "material", "op": "not_in",
              "value": ["木质", "竹质"], "label": "不要木质/竹质"},
         ]},
        [{"id": "A", "name": "甲", "price": 100, "score": 5,
          "os": "Windows", "material": "不锈钢"},
         {"id": "B", "name": "乙", "price": 80, "score": 5,
          "os": "Linux", "material": "硅胶"},
         {"id": "C", "name": "丙", "price": 90, "score": 4,
          "os": "Windows", "material": "竹质"}],
    ))

    out.append((
        "invalid_directions",
        {"title": "方向写错", "budget": 100,
         "weights": {"score": 2}, "directions": {"score": "up"}},
        [{"id": "A", "name": "甲", "price": 10, "score": 3}],
    ))

    out.append((
        "missing_metric",
        {"title": "候选缺字段", "budget": 100,
         "weights": {"score": 2}, "directions": {"score": "higher"}},
        [{"id": "A", "name": "甲", "price": 10, "score": 3},
         {"id": "B", "name": "乙", "price": 20}],
    ))

    return out


def decide_data(needs: dict, items: list[dict], case_id: str) -> tuple[dict, list[str]]:
    """与 engine.decide 等价，只是输入从目录换成已解析的 dict。"""
    empty = {
        "case_id": case_id, "accepted": [], "rejected": [],
        "moves": [], "sensitivity": {},
        "winner": None, "runner_up": None,
    }
    errors = validate_case(needs, items)
    if errors:
        return empty, errors

    eligible: list[dict] = []
    rejected: list[tuple[str, str, list[str]]] = []
    for item in items:
        reasons = hard_reasons(item, needs)
        if reasons:
            rejected.append((str(item["id"]), str(item["name"]), reasons))
        else:
            eligible.append(item)

    accepted = score_items(eligible, needs["weights"], needs["directions"]) if eligible else []
    moves: list = []
    sens: dict = {}
    if len(accepted) >= 2:
        moves = counterfactual(eligible, accepted[0], accepted[1],
                               needs["weights"], needs["directions"])
        sens = sensitivity(eligible, needs["weights"], needs["directions"])
    return {
        "case_id": case_id,
        "accepted": accepted,
        "rejected": rejected,
        "moves": moves,
        "sensitivity": sens,
        "winner": accepted[0] if accepted else None,
        "runner_up": accepted[1] if len(accepted) > 1 else None,
    }, []


def summarize(data: dict, errors: list[str]) -> dict:
    return {
        "case_id": data["case_id"],
        "errors": errors,
        "winner": data["winner"].item_id if data["winner"] else None,
        "winner_total": data["winner"].total if data["winner"] else None,
        "runner_up": data["runner_up"].item_id if data["runner_up"] else None,
        "accepted": [
            {"id": s.item_id, "name": s.name, "price": s.price,
             "total": s.total, "parts": s.parts}
            for s in data["accepted"]
        ],
        "rejected": [
            {"id": rid, "name": name, "reasons": reasons}
            for rid, name, reasons in data["rejected"]
        ],
        "moves": [
            {"metric": m.metric, "current": m.current,
             "target": m.target, "relative": m.relative}
            for m in data["moves"]
        ],
        "sensitivity": {
            "baseline": data["sensitivity"].get("baseline"),
            "trials": data["sensitivity"].get("trials", 0),
            "flips": data["sensitivity"].get("flips", []),
            "verdict": data["sensitivity"].get("verdict"),
        },
    }


def canon(obj):
    """统一数值精度、dict 顺序与数字文本格式，消除跨语言差异。

    JS 的 number 不区分 2 与 2.0，Python 的 TOML 会把 2.0 读成 float 并在
    淘汰理由里打印成「2.0」，而 JS 打印成「2」。这只是显示格式差异，不改变
    比较语义，因此校对时统一成「2」。
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return round(float(obj), 6)
    if isinstance(obj, str):
        return re.sub(r"(\d+)\.0(?=\D|$)", r"\1", obj)
    if isinstance(obj, dict):
        return {k: canon(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [canon(x) for x in obj]
    return obj


def main() -> int:
    cases: list[tuple[str, dict, list[dict]]] = []
    for name, path in REAL_CASES:
        needs, items = load_case(path)
        cases.append((name, needs, items))
    cases.extend(synthetic())

    payload = [{"id": cid, "needs": needs, "items": items}
               for cid, needs, items in cases]
    expected = []
    for cid, needs, items in cases:
        data, errors = decide_data(needs, items, cid)
        expected.append(summarize(data, errors))

    proc = subprocess.run(
        ["node", str(HERE / "verify.js")],
        input=json.dumps(payload, ensure_ascii=False),
        text=True, capture_output=True, cwd=str(HERE),
    )
    if proc.returncode != 0:
        print("JS 引擎执行失败：", proc.stderr.strip(), file=sys.stderr)
        return 1
    try:
        got = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print("JS 输出不是合法 JSON：", exc, proc.stdout[:300], file=sys.stderr)
        return 1

    actual = got["results"]
    failed = 0
    for exp, act in zip(expected, actual):
        cid = exp["case_id"]
        a = json.dumps(canon(exp), ensure_ascii=False, sort_keys=True)
        b = json.dumps(canon(act), ensure_ascii=False, sort_keys=True)
        ok = a == b
        detail = ""
        if ok:
            w = exp["winner"]
            detail = (f"胜出 {w or '—'}"
                      + (f" {exp['winner_total']:.2f} 分" if exp["winner_total"] is not None else "")
                      + f" · 通过 {len(exp['accepted'])} / 淘汰 {len(exp['rejected'])}"
                      + (f" · 校验拦截 {len(exp['errors'])} 条" if exp["errors"] else ""))
        else:
            failed += 1
            detail = "结果不一致"
            for key in exp:
                if json.dumps(canon(exp[key]), sort_keys=True) != json.dumps(canon(act.get(key)), sort_keys=True):
                    detail += f"\n    {key}: Python={exp[key]!r}\n          JS={act.get(key)!r}"
        print(f"  [{'OK' if ok else 'FAIL'}] {cid}: {detail}")

    parity = got.get("parity")
    if not isinstance(parity, dict) or any(v is not True for v in parity.values()):
        failed += 1
        print("  [FAIL] 网页内置案例与仓库 TOML 数据不一致：", parity)
    else:
        print("  [OK] 网页内置案例与仓库 TOML 的裁决字段一致：", ", ".join(parity))

    print(f"\n共 {len(cases)} 个案例 · 失败 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
