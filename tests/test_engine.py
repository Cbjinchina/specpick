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
