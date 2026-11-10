"""specpick 命令行入口。零安装：在仓库根目录直接 `python -m specpick ...`。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import decide, load_case, validate_case
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

    args = parser.parse_args(argv)
    return args.func(args)
