"""营养缺口推荐的单元测试：python -m unittest discover -s tests -v"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from specpick.nutrition import plan  # noqa: E402


class Basic(unittest.TestCase):
    def test_fruit_vitamin_c(self):
        r = plan(["vc"], portion=200, cats=["水果"])
        self.assertTrue(r["rows"])
        # 冬枣 243mg/100g 最高含量，但只补到 100% 上限；排名靠的是「一份够不够」
        self.assertIn(r["rows"][0]["name"], {"番石榴", "猕猴桃", "冬枣"})
        self.assertLessEqual(r["rows"][0]["score"], 1.0)
        self.assertGreaterEqual(r["rows"][0]["score"], 0.5)

    def test_cap_not_infinite_benefit(self):
        """超过 100% 不再加分：冬枣维C 486%，分数不该因此超过 1。"""
        r = plan(["vc"], portion=300, cats=None, top=40)
        jujube = [x for x in r["rows"] if x["name"] == "冬枣"][0]
        self.assertGreater(jujube["pct"]["vc"], 100)
        self.assertLessEqual(jujube["score"], 1.0)

    def test_liver_capped(self):
        """猪肝维A 极高：单次上限 30g，不能按用户选的 200g 算。"""
        r = plan(["va"], portion=200, cats=None)
        liver = [x for x in r["rows"] if x["name"] == "猪肝"]
        self.assertTrue(liver, "猪肝应该在候选里")
        self.assertEqual(liver[0]["used"], 30.0)
        self.assertTrue(liver[0]["capped"])

    def test_fruit_cannot_fix_iron(self):
        r = plan(["fe", "ca"], portion=200, cats=["水果"])
        self.assertEqual(set(r["gaps"]), {"fe", "ca"})

    def test_all_cats_fix_iron(self):
        r = plan(["fe"], portion=200, cats=None)
        self.assertEqual(r["gaps"], [])
        self.assertIn(r["rows"][0]["name"], {"猪肝", "菠菜", "杂豆（鹰嘴豆）", "燕麦", "北豆腐"})

    def test_empty_targets(self):
        r = plan([], portion=200)
        self.assertEqual(r["rows"], [])
        self.assertIn("至少一个", r["error"])

    def test_low_sugar_penalty(self):
        base = plan(["vc"], portion=200, cats=["水果"], top=40)
        sweet = plan(["vc"], portion=200, cats=["水果"], low_sugar=True, top=40)
        b = {x["name"]: x["score"] for x in base["rows"]}
        s = {x["name"]: x["score"] for x in sweet["rows"]}
        # 糖高的被降权，排名不该上升
        self.assertLessEqual(s["冬枣"], b["冬枣"] + 1e-9)

    def test_combo_does_not_overshoot(self):
        r = plan(["vc", "fiber"], portion=200, cats=["水果"])
        cover = r["combo"]["cover"]
        # 「够用就好」：三样 100g 组合不该把维C 顶到 300% 以上
        self.assertLess(cover["vc"], 300)

    def test_stable(self):
        a = plan(["vc", "fiber", "k"], portion=200, cats=["水果", "蔬菜", "主食豆类"])
        b = plan(["vc", "fiber", "k"], portion=200, cats=["水果", "蔬菜", "主食豆类"])
        self.assertEqual([x["name"] for x in a["rows"]], [x["name"] for x in b["rows"]])


if __name__ == "__main__":
    unittest.main()
