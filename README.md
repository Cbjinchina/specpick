# specpick

**不猜你喜欢什么，只回答：按我写下的标准，谁该赢、另一个为什么输了、要改哪个条件它才会赢。以及三个月后，我当初判断对不对。**

把「我的需求」写成一份可 `git diff` 的 TOML 规格，对**你已经在看的 3–20 个候选**做可解释裁决，输出一份 Markdown 报告。全部逻辑是纯函数：100% Python 标准库，零 API Key、零爬虫、零数据库、零随机数，同样的输入永远得到同样的输出。

---

## 为什么不叫「推荐系统」

这个题目一点都不新。2026 年 GitHub 上从导购工具、Agent、AI skill 到评测基准已经四层覆盖了；本项目的差别**不在题目，在做法**：

| 已有做法 | 典型依赖 | 本项目 |
| --- | --- | --- |
| AI 导购 Agent（Anthropic Commerce Agents、各类 commerce MCP） | 商品目录、服务端、模型调用 | 不做，候选自己录入 |
| 参数对比 + 加权打分 + LLM 解释（如 WorthIt?） | Groq / Streamlit / SQLite，结论可能每次不同 | 打分保留，解释改为确定性规则，**不用 LLM** |
| 爬虫比价 / 避雷（SpotTruth、Shop Smart、拾价等） | 反爬、账号风险、实时价格 | 不联网，不碰平台数据 |
| 决策日志（Regret Ledger、Ownly、logbook、decision-record CLI） | SQLite / MCP / Node / Rust，面向通用决策 | 只做一件事，纯文本 + 标准库 |
| 买家侧评测基准（DeepPlanning / ShoppingBench、τ-Rec、timo-decision-benchmark） | 大厂数据集、论文级工程量 | 不做基准，只做个人可用的小工具 |

最接近的是 WorthIt?：它同样用确定性规则打分、同样谈 trade-off。差别是它绑了 Streamlit + SQLite + 托管模型、只覆盖耳机/笔记本/手机这类参数标准化的 3C 品类，而且没有买后回测。**specpick 是同一个想法被剥到只剩可复现内核的样子**——所以它五年后还能跑。

---

## 三条命令

需要 Python ≥ 3.11（用到标准库 `tomllib`），无需 `pip install`。

```bash
git clone https://github.com/Cbjinchina/specpick.git
cd specpick

python -m specpick check examples/kitchen-rack     # 校验规格与候选是否自洽
python -m specpick decide examples/kitchen-rack    # 生成 examples/kitchen-rack/report.md
python -m specpick review --records records --out REVIEW.md   # 汇总买后回测

python -m unittest discover -s tests -v            # 跑测试
```

`decide` 会在终端打印一行结论，例如：

```
裁决：折叠不锈钢窄款（5.00 分）｜淘汰 2 个｜敏感性 稳健
```

CI 里会**重新生成报告并和仓库中提交的 `report.md` 做 diff**——如果有人改了引擎却没同步报告，构建直接失败。可复现性不是口号，是被 CI 卡住的。

---

## 输入长什么样

`needs.toml` 把需求分成三层：预算、硬约束、软偏好。

```toml
title = "小厨房的沥水架"
budget = 120

[weights]          # 软偏好：归一化后加权
footprint = 3
easy_clean = 2
price = 1

[directions]       # 方向必须显式写，避免「分数越高越好」的隐含假设
footprint = "lower"
easy_clean = "higher"
price = "lower"

[[hard]]           # 硬约束：不满足直接淘汰，并写出理由
field = "width_cm"
op = "<="
value = 30
label = "宽度不超过 30cm"
```

`items.toml` 是候选清单，字段自己定，支持 `<= < >= > == != in not_in`。完整可运行样例见 [`examples/kitchen-rack/`](examples/kitchen-rack/)，生成的报告见 [`examples/kitchen-rack/report.md`](examples/kitchen-rack/report.md)。

---

## 三个设计选择

**1. 淘汰理由是一等公民。** 推荐系统习惯把不合意的候选悄悄丢掉，这里每个被淘汰的候选都要留下逐条理由（超预算多少、哪个字段违反了哪条约束）。报告里「为什么不是它」和「为什么是它」同样详细。

**2. 反事实是解析解，不是模型编的。** 线性加权下可以直接算出：第二名只改一个字段，最少要改到多少才能反超。样例里会给出「易清洗从 4 提到 4.43 即可反超」这种结论，而不是「也许可以考虑另一款」。同时对每个权重做 ±25% 扰动，告诉你这个第一名是「稳健」还是「脆弱」。

**3. 买后回测写回仓库。** `records/*.toml` 记录几个月后的真实情况：`would_rebuy`、`used_per_week`、`lesson`。`review` 会汇总「重来还会买」的比例，并点出买回来基本没用的东西——下次同类购买，那些权重该下调了。这是把一次性的工具变成个人判断档案的那一步。

---

## 边界（刻意不做）

- 不抓商品、不接电商 API、不接 LLM、不做协同过滤 / 向量召回、不做实时价格
- 不覆盖百万商品库；候选是**你手动录入的少量选项**
- 线性加权模型，不做黑盒；反事实只算单变量，多变量组合留给后续版本
- 不提供 Web UI——报告就是 Markdown，天然适合 git、PR 和 GitHub Pages

这些不是功能缺失，是让项目保持小、可复现、可审计的前提。

---

## 怎么贡献

最容易上手的三件事：

1. 在 `examples/` 加一个新案例。**最欢迎非 3C 品类**（家居、厨具、文具、母婴、宠物），因为这类东西参数不统一、靠主观权衡，恰恰是标准参数对比工具最无能为力的地方。
2. 在 `records/` 加一条真实复盘，尤其是判断错了的那次。
3. 给 `hard` 规则加更友好的中文理由模板，或补一个边界测试。

所有贡献跑 `python -m specpick check <案例目录>` 和测试即可，不需要配任何环境。

## 路线图

- v0.1（当前）：TOML 规格、硬约束淘汰、加权打分、反事实、权重敏感性、买后回测
- v0.2：多变量组合反事实、把历史 `lesson` 汇总成可复用的「我的权重模板」
- v0.3：可选的 HTML 报告 / GitHub Pages 展示（仍不联网）

## 许可

MIT
