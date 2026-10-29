"""check.py 的离线单测：不联网、不调模型。

运行：python tests/test_check.py
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from check import check  # noqa: E402


class CheckTest(unittest.TestCase):
    def test_pass(self) -> None:
        self.assertEqual(check({"order_id": "A1001", "signed_days_ago": 3,
                                "window_days": 7, "conclusion": "可退",
                                "clause": "第四条"}), [])

    def test_boundary_equal(self) -> None:
        # 第 7 天当天仍可退
        self.assertEqual(check({"order_id": "A1002", "signed_days_ago": 7,
                                "window_days": 7, "conclusion": "可退",
                                "clause": "第五条"}), [])

    def test_contradiction(self) -> None:
        problems = check({"order_id": "A1003", "signed_days_ago": 9,
                          "window_days": 7, "conclusion": "可退", "clause": "第四条"})
        self.assertEqual(len(problems), 1)
        self.assertIn("矛盾", problems[0])

    def test_missing_field(self) -> None:
        self.assertIn("缺字段", check({"order_id": "A1004"})[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
