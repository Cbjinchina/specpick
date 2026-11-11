"""把裁决渲染成可提交进 git 的 Markdown 报告。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .engine import Result

METRIC_LABELS = {
    "price": "价格",
    "footprint": "占地",
    "easy_clean": "易清洗",
    "durability": "耐用",
    "noise": "噪音",
    "weight": "重量",
    "weight_kg": "重量(kg)",
    "battery_h": "续航(h)",
    "ram_gb": "内存(GB)",
    "vram_gb": "显存(GB)",
    "fan_count": "风扇数",
    "tier": "型号档位",
}


def _label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric)


def render_decision(r: Result) -> str:
    lines: list[str] = [
        f"# {r.title}",
        "",
        f"> 案例 `{r.case_id}` · 预算 ¥{r.budget} · 由 specpick 本地生成，可复现",
        "",
    ]
    if r.scene:
        lines += [f"**场景**：{r.scene}", ""]

    lines += ["## 我的需求规格", "", "| 指标 | 方向 | 权重 |", "| --- | --- | --- |"]
    for metric, weight in r.weights.items():
        direction = "越大越好" if r.directions.get(metric) == "higher" else "越小越好"
        lines.append(f"| {_label(metric)} (`{metric}`) | {direction} | {weight} |")
    lines.append("")
    if r.hard_rules:
        lines += ["**硬性约束**（不满足即淘汰，不参与打分）：", ""]
        for rule in r.hard_rules:
            lines.append(f"- {rule['label']}：`{rule['field']}` {rule['op']} `{rule['value']}`")
        lines.append("")

    lines += ["## 裁决", ""]
    if not r.accepted:
        lines += ["**没有候选通过硬约束。** 这不是打分问题，是要求或候选需要调整。", ""]
    else:
        metrics = list(r.weights)
        header = "| 排名 | 候选 | 售价 | 总分 | " + " | ".join(_label(m) for m in metrics) + " |"
        sep = "| --- | --- | --- | --- | " + " | ".join("---" for _ in metrics) + " |"
        lines += [header, sep]
        for i, s in enumerate(r.accepted, 1):
            cells = " | ".join(f"{s.parts[m]:.2f}" for m in metrics)
            lines.append(f"| {i} | {s.name} | ¥{s.price} | **{s.total:.2f}** | {cells} |")
        lines += ["", f"**结论**：{r.winner.name} 胜出。", ""]

    if r.rejected:
        lines += ["## 淘汰清单（含逐条理由）", ""]
        for rej in r.rejected:
            lines.append(f"- **{rej.name}**")
            for reason in rej.reasons:
                lines.append(f"  - {reason}")
        lines.append("")

    if r.moves and r.runner_up:
        lines += [
            "## 反事实：第二名要怎样才会赢", "",
            f"当前差距 {r.winner.total - r.runner_up.total:.2f} 分。只改一个字段、且改动幅度最小的路径：",
            "",
        ]
        for m in r.moves[:3]:
            direction = "降到" if r.directions.get(m.metric) == "lower" else "提到"
            lines.append(
                f"- **{_label(m.metric)}** 从 `{m.current:g}` {direction} `{m.target:g}` "
                f"（跨越该指标取值范围的 {m.relative * 100:.0f}%）即可追平或反超"
            )
        lines.append("")
        lines += ["> 这是线性模型的解析解，不是猜测；改多个字段的组合不在 v0 范围内。", ""]
    elif len(r.accepted) >= 2:
        lines += ["## 反事实", "", "单改任一字段都追不上第一名，需要同时调整多个条件。", ""]

    if r.sensitivity:
        s = r.sensitivity
        lines += [
            "## 权重敏感性", "",
            f"对每个权重做 ±25% 扰动，共 {s['trials']} 次重算，"
            f"第一名变化 {len(s['flips'])} 次 → **{s['verdict']}**。",
            "",
        ]
        if s["flips"]:
            lines += ["易翻转的权重：" + "、".join(s["flips"]), ""]

    lines += [
        "---",
        "",
        "本报告由 `python -m specpick decide` 生成：纯标准库、零 API Key、零爬虫、"
        "同样的输入永远得到同样的输出。",
        "",
    ]
    return "\n".join(lines)


def load_reviews(records_dir: Path) -> list[dict]:
    if not records_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(records_dir.glob("*.toml")):
        with path.open("rb") as fh:
            out.append(tomllib.load(fh))
    return out


def render_review(reviews: list[dict]) -> str:
    lines = ["# 买后回测", "", "> 决策当时写得再清楚，也要过几个月才知道判断准不准。", ""]
    if not reviews:
        lines += ["还没有回测记录。在 `records/` 下加一个 TOML 即可。", ""]
        return "\n".join(lines)

    reviewed = [r for r in reviews if r.get("would_rebuy") is not None]
    rebuy = sum(1 for r in reviewed if r["would_rebuy"])
    rate = rebuy / len(reviewed) if reviewed else 0
    uses = [r.get("used_per_week") for r in reviewed if isinstance(r.get("used_per_week"), (int, float))]
    avg_use = sum(uses) / len(uses) if uses else 0

    lines += [
        "| 指标 | 值 |", "| --- | --- |",
        f"| 已回测决策 | {len(reviewed)} / {len(reviews)} |",
        f"| 「重来还会买」比例 | {rate * 100:.0f}% |",
        f"| 平均每周使用次数 | {avg_use:.1f} |",
        "",
        "## 逐条复盘", "",
    ]
    for r in reviews:
        flag = "会再买" if r.get("would_rebuy") else ("不会" if r.get("would_rebuy") is False else "待回测")
        lines += [
            f"### {r.get('case', '未命名')} · {r.get('decided_on', '')}",
            "",
            f"- 当时选了：{r.get('picked', '—')}（{flag}）",
            f"- 回看日期：{r.get('reviewed_on', '—')}",
        ]
        if r.get("lesson"):
            lines.append(f"- 经验修正：{r['lesson']}")
        lines.append("")

    idle = [r for r in reviewed if isinstance(r.get("used_per_week"), (int, float)) and r["used_per_week"] < 1]
    if idle:
        lines += ["## 低频提醒", "", "以下东西买回来基本没用，下次同类购买的权重应该下调：", ""]
        for r in idle:
            lines.append(f"- {r.get('picked', r.get('case'))}（每周 {r['used_per_week']} 次）")
        lines.append("")
    return "\n".join(lines)
