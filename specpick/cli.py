"""specpick 命令行入口。零安装：在仓库根目录直接 `python -m specpick ...`。"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

from .engine import decide, load_case, validate_case
from .nutrition import FOODS, LABEL, NUTRIENTS, plan as nutrition_plan
from .report import load_reviews, render_decision, render_review

DEFAULT_CASE = "examples/kitchen-rack"


def _write(text: str, out: str | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"已写入 {path}")
    else:
        print(text)


def _cmd_decide(args: argparse.Namespace) -> int:
    case_dir = Path(args.case)
    result, errors = decide(case_dir)
    if errors:
        print(f"needs.toml / items.toml 有 {len(errors)} 处问题：", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    out = args.out if args.out else str(case_dir / "report.md")
    _write(render_decision(result), out)
    if result.winner:
        print(
            f"裁决：{result.winner.name}（{result.winner.total:.2f} 分）｜"
            f"淘汰 {len(result.rejected)} 个｜敏感性 {result.sensitivity.get('verdict', '—')}"
        )
    else:
        print("没有候选通过硬约束。")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    case_dir = Path(args.case)
    needs, items = load_case(case_dir)
    errors = validate_case(needs, items)
    if errors:
        for err in errors:
            print(f"ERROR {case_dir}: {err}", file=sys.stderr)
        return 1
    print(f"OK {case_dir}: {len(items)} 个候选，{len(needs.get('hard', []))} 条硬约束，格式自洽")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    reviews = load_reviews(Path(args.records))
    _write(render_review(reviews), args.out)
    if reviews:
        print(f"共 {len(reviews)} 条决策档案")
    return 0


def _pad(text: str, width: int) -> str:
    """按显示宽度补空格：中文占两格，不然终端里的表会歪。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(text))
    return str(text) + " " * max(0, width - w)


def _cmd_nutrition(args: argparse.Namespace) -> int:
    keys = [k for k in args.need]
    unknown = [k for k in keys if k not in LABEL]
    if unknown:
        print(f"不认识的营养素：{', '.join(unknown)}", file=sys.stderr)
        print("可用：" + "、".join(f"{k}（{LABEL[k]}）" for k, *_ in NUTRIENTS), file=sys.stderr)
        return 1
    cats = {"fruit": ["水果"], "fruitveg": ["水果", "蔬菜"]}.get(args.cats)
    res = nutrition_plan(keys, portion=args.portion, low_sugar=args.low_sugar,
                         limit_k=args.limit_k, cats=cats)
    if res.get("error"):
        print(res["error"], file=sys.stderr)
        return 1

    names = " + ".join(t["label"] for t in res["targets"])
    print(f"要补：{names}｜一次 {res['portion']:.0f}g" +
          ("｜控糖" if args.low_sugar else "") + ("｜限钾" if args.limit_k else ""))
    head = "".join(_pad(t["label"], 12) for t in res["targets"])
    print("\n" + _pad("排行", 6) + _pad("食物", 16) + _pad("类别", 12) + head + "补到")
    for i, row in enumerate(res["rows"], 1):
        cells = "".join(_pad(f"{row['pct'][t['key']]:.0f}%", 12) for t in res["targets"])
        note = f"（按 {row['used']:.0f}g 算）" if row["capped"] else ""
        flags = ("  " + "/".join(row["flags"])) if row["flags"] else ""
        print(_pad(i, 6) + _pad(row["name"], 16) + _pad(row["cat"], 12) +
              cells + _pad(f"{row['score']*100:.0f}%", 6) + note + flags)

    if res["combo"]["items"]:
        parts = " + ".join(f"{it['name']} {it['g']:.0f}g" for it in res["combo"]["items"])
        cover = "、".join(f"{t['label']} {res['combo']['cover'][t['key']]:.0f}%" for t in res["targets"])
        print(f"\n一份搭配：{parts}")
        print(f"合计补到：{cover}")
    if res["gaps"]:
        weak = "、".join(f"{LABEL[k]}（最高 {t['best_pct']:.0f}%）"
                        for k, t in zip(res["gaps"], [x for x in res["targets"] if x["key"] in res["gaps"]]))
        print(f"\n⚠ 这些项这一类里补不上：{weak}，换成肉蛋豆或问医生。")
    print("\n数据为每 100g 可食部的常见参考值，只做相对比较，不构成医学建议。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="specpick",
        description="把「我的需求」写成规格，对少量候选做可解释、可复现的裁决。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_decide = sub.add_parser("decide", help="生成裁决报告")
    p_decide.add_argument("case", nargs="?", default=DEFAULT_CASE, help="案例目录")
    p_decide.add_argument("--out", help="报告输出路径（默认 <case>/report.md）")
    p_decide.set_defaults(func=_cmd_decide)

    p_check = sub.add_parser("check", help="校验规格与候选是否自洽")
    p_check.add_argument("case", nargs="?", default=DEFAULT_CASE, help="案例目录")
    p_check.set_defaults(func=_cmd_check)

    p_review = sub.add_parser("review", help="汇总买后回测")
    p_review.add_argument("--records", default="records", help="回测记录目录")
    p_review.add_argument("--out", help="输出路径（默认打印到终端）")
    p_review.set_defaults(func=_cmd_review)

    p_nut = sub.add_parser("nutrition", help="按营养缺口挑食物（如补维C/纤维吃什么）")
    p_nut.add_argument("--need", required=True, type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
                       help="想补的营养素，逗号分隔：vc,fiber,k,folate,ca,fe,va")
    p_nut.add_argument("--portion", type=float, default=200, help="一次吃多少克（默认 200）")
    p_nut.add_argument("--cats", default="fruit", choices=["fruit", "fruitveg", "all"],
                       help="候选范围：fruit 水果 / fruitveg 水果+蔬菜 / all 全部")
    p_nut.add_argument("--low-sugar", action="store_true", help="控糖：含糖高的降权")
    p_nut.add_argument("--limit-k", action="store_true", help="限钾：钾高的降权")
    p_nut.set_defaults(func=_cmd_nutrition)

    args = parser.parse_args(argv)
    return args.func(args)
