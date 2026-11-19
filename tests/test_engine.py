"""标准库 unittest：python -m unittest discover -s tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from specpick.engine import (  # noqa: E402
    decide,
    hard_reasons,
    score_items,
    validate_case,
)
from specpick.report import render_decision, render_review  # noqa: E402

CASE = ROOT / "examples" / "kitchen-rack"


class ExampleCase(unittest.TestCase):
    def setUp(self):
        self.result, self.errors = decide(CASE)

    def test_case_is_valid(self):
        self.assertEqual(self.errors, [])

    def test_winner_and_runner_up(self):
        self.assertEqual(self.result.winner.name, "折叠不锈钢窄款")
        self.assertEqual(self.result.runner_up.name, "折叠硅胶沥水架")

    def test_rejected_items_have_reasons(self):
        by_name = {r.name: r for r in self.result.rejected}
        self.assertIn("不锈钢单层沥水架", by_name)  # 超预算
        self.assertIn("竹木双层沥水架", by_name)
        self.assertTrue(any("预算" in x for x in by_name["不锈钢单层沥水架"].reasons))
        self.assertGreaterEqual(len(by_name["竹木双层沥水架"].reasons), 2)
        for rej in self.result.rejected:
            self.assertTrue(all(rej.reasons))

    def test_scores_are_deterministic(self):
        again, _ = decide(CASE)
        self.assertEqual(
            [(s.item_id, s.total) for s in self.result.accepted],
            [(s.item_id, s.total) for s in again.accepted],
        )

    def test_counterfactual_is_actionable(self):
        self.assertGreaterEqual(len(self.result.moves), 2)
        self.assertEqual(self.result.moves[0].metric, "easy_clean")
        self.assertGreater(self.result.moves[0].target, 4)
        self.assertLess(self.result.moves[0].target, 5)
        self.assertTrue(any(m.metric == "price" for m in self.result.moves))

    def test_sensitivity_shape(self):
        s = self.result.sensitivity
        self.assertEqual(s["trials"], 6)
        self.assertIn(s["verdict"], ("稳健", "基本稳健", "脆弱"))

    def test_report_contains_key_sections(self):
        text = render_decision(self.result)
        for section in ("## 裁决", "## 淘汰清单", "## 反事实", "## 权重敏感性"):
            self.assertIn(section, text)
        self.assertIn("折叠不锈钢窄款", text)


class EngineUnits(unittest.TestCase):
    def test_all_equal_values_do_not_divide_by_zero(self):
        items = [
            {"id": "x", "name": "X", "price": 10, "m": 3},
            {"id": "y", "name": "Y", "price": 10, "m": 3},
        ]
        scored = score_items(items, {"price": 1, "m": 1}, {"price": "lower", "m": "higher"})
        self.assertEqual(scored[0].total, scored[1].total)

    def test_hard_rule_not_in(self):
        needs = {
            "budget": 100,
            "hard": [{"field": "material", "op": "not_in", "value": ["木质"], "label": "不要木质"}],
        }
        self.assertEqual(hard_reasons({"price": 50, "material": "木质"}, needs)[0], "不要木质（实际 木质，要求 not_in ['木质']）")

    def test_validation_catches_missing_fields(self):
        errors = validate_case(
            {"title": "t", "budget": 10, "weights": {"m": 1}, "directions": {}},
            [{"id": "a", "name": "A", "price": 5, "m": 1}],
        )
        self.assertTrue(any("directions" in e for e in errors))
        self.assertTrue(validate_case({"title": "t"}, []))


class ScoringShapes(unittest.TestCase):
    """同一个数字可以按四种比法算分：范围 / 对数 / 名次 / 越接近目标。"""

    ITEMS = [
        {"id": "a", "name": "小", "price": 10, "m": 200},
        {"id": "b", "name": "中", "price": 10, "m": 5000},
        {"id": "c", "name": "大", "price": 10, "m": 120000},
    ]

    def _scores(self, shape_cfg, items=None, direction="higher", metric="m"):
        items = items or self.ITEMS
        scored = score_items(items, {metric: 1}, {metric: direction}, None, {metric: shape_cfg})
        return {s.name: round(s.total, 4) for s in scored}

    def test_span_is_linear(self):
        got = self._scores({"shape": "span"})
        self.assertEqual(got["小"], 0.0)
        self.assertEqual(got["大"], 1.0)
        self.assertAlmostEqual(got["中"], (5000 - 200) / (120000 - 200), places=4)

    def test_log_keeps_small_value_visible(self):
        got = self._scores({"shape": "log"})
        self.assertEqual(got["小"], 0.0)
        self.assertEqual(got["大"], 1.0)
        # 线性下「中」只有 4%，对数下到五成左右，不至于被打成 0
        self.assertGreater(got["中"], 0.45)
        self.assertLess(got["中"], 0.55)

    def test_log_falls_back_when_non_positive(self):
        items = [
            {"id": "a", "name": "零", "price": 10, "m": 0},
            {"id": "b", "name": "半", "price": 10, "m": 50},
            {"id": "c", "name": "满", "price": 10, "m": 100},
        ]
        got = self._scores({"shape": "log"}, items)
        self.assertEqual(got["零"], 0.0)
        self.assertEqual(got["满"], 1.0)
        self.assertAlmostEqual(got["半"], 0.5, places=4)

    def test_ordinal_ignores_magnitude(self):
        items = [
            {"id": "a", "name": "甲", "price": 10, "m": 41},
            {"id": "b", "name": "乙", "price": 10, "m": 38},
            {"id": "c", "name": "丙", "price": 10, "m": 9000},
        ]
        got = self._scores({"shape": "ordinal"}, items)
        self.assertEqual(got["丙"], 1.0)
        self.assertEqual(got["乙"], 0.0)
        self.assertEqual(got["甲"], 0.5)
        # 换成线性，甲乙会被 9000 压成 0.0003 和 0
        span = self._scores({"shape": "span"}, items)
        self.assertLess(span["甲"], 0.01)

    def test_target_point_full_marks_only_at_goal(self):
        items = [
            {"id": "a", "name": "太轻", "price": 10, "m": 1.2},
            {"id": "b", "name": "正好", "price": 10, "m": 1.6},
            {"id": "c", "name": "太重", "price": 10, "m": 2.1},
        ]
        got = self._scores({"shape": "target", "lo": 1.6, "hi": 1.6, "tol": 0.5}, items)
        self.assertEqual(got["正好"], 1.0)
        self.assertAlmostEqual(got["太轻"], 0.2, places=4)
        self.assertEqual(got["太重"], 0.0)  # 偏出 0.5，正好扣到 0

    def test_target_band_gives_full_marks_inside(self):
        items = [
            {"id": "a", "name": "小屏", "price": 10, "m": 5.4},
            {"id": "b", "name": "正好", "price": 10, "m": 6.3},
            {"id": "c", "name": "大屏", "price": 10, "m": 6.8},
        ]
        got = self._scores({"shape": "target", "lo": 6.1, "hi": 6.5, "tol": 1.0}, items)
        self.assertEqual(got["正好"], 1.0)
        self.assertGreater(got["小屏"], 0.0)
        self.assertLess(got["小屏"], 1.0)

    def test_target_needs_no_second_point(self):
        """区间是绝对标准，只有一件候选有数据也应该给分。"""
        items = [
            {"id": "a", "name": "甲", "price": 10, "m": 1.6},
            {"id": "b", "name": "乙", "price": 10, "m": None},
        ]
        got = self._scores({"shape": "target", "lo": 1.6, "hi": 1.6, "tol": 0.5}, items)
        self.assertEqual(got["甲"], 1.0)

    def test_bad_target_config_is_not_scored(self):
        items = [
            {"id": "a", "name": "甲", "price": 10, "m": 1},
            {"id": "b", "name": "乙", "price": 10, "m": 2},
        ]
        for cfg in ({"shape": "target", "lo": 1, "hi": 1, "tol": 0},
                    {"shape": "target", "lo": 1}):
            got = self._scores(cfg, items)
            self.assertEqual(got, {"甲": 0.0, "乙": 0.0})

    def test_validate_rejects_unknown_shape(self):
        errors = validate_case(
            {"title": "t", "budget": 100, "weights": {"m": 1}, "directions": {"m": "higher"},
             "shapes": {"m": {"shape": "magic"}}},
            [{"id": "a", "name": "A", "price": 5, "m": 1}],
        )
        self.assertTrue(any("shape" in e or "比法" in e for e in errors), errors)

    def test_validate_rejects_target_without_tolerance(self):
        errors = validate_case(
            {"title": "t", "budget": 100, "weights": {"m": 1}, "directions": {"m": "higher"},
             "shapes": {"m": {"shape": "target", "lo": 1, "hi": 2, "tol": 0}}},
            [{"id": "a", "name": "A", "price": 5, "m": 1.5}],
        )
        self.assertTrue(errors)
        self.assertTrue(any("容差" in e or "tol" in e for e in errors), errors)


class ReviewReport(unittest.TestCase):
    def test_review_summary(self):
        text = render_review(
            [
                {"case": "a", "picked": "A", "would_rebuy": True, "used_per_week": 5, "lesson": "x"},
                {"case": "b", "picked": "B", "would_rebuy": False, "used_per_week": 0.2, "lesson": "y"},
            ]
        )
        self.assertIn("50%", text)
        self.assertIn("低频提醒", text)
        self.assertIn("经验修正", text)


if __name__ == "__main__":
    unittest.main()
