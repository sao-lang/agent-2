"""三种裁判在同一批产物上的判定，以及一致性。

不联网。裁判分别是：自评（模型看自己的输出）、规则（业务代码）、测试（已知答案）。
"""

from __future__ import annotations

from reflect import rule_review, self_review, test_review

CASES = [
    {"order_id": "A1001", "days": 3, "reason": "签收不想要", "expect_days": 3},
    {"order_id": "A1002", "days": 30, "reason": "超过 7 天窗口", "expect_days": 30},
    {"order_id": "A1003", "days": 5, "reason": "超过 7 天窗口", "expect_days": 5},
    {"order_id": "A1004", "days": "3", "reason": "三天前签收", "expect_days": 3},
]


def main() -> None:
    rows = []
    for c in CASES:
        artifact = {k: c[k] for k in ("order_id", "days", "reason")}
        self_ok, _ = self_review(artifact)
        rule_ok, rule_why = rule_review(artifact)
        test_ok, test_why = test_review(artifact, [c])
        rows.append((c["order_id"], self_ok, rule_ok, test_ok, rule_why, test_why))

    print(f"{'订单':<8}{'自评':<8}{'规则':<8}{'测试':<8}")
    for oid, a, b, c_, rwhy, twhy in rows:
        mark = lambda ok: "通过" if ok else "驳回"
        print(f"{oid:<8}{mark(a):<8}{mark(b):<8}{mark(c_):<8}")

    print()
    print("驳回理由：")
    for oid, a, b, c_, rwhy, twhy in rows:
        if not b or not c_:
            print(f"  {oid}  规则={rwhy}  测试={twhy}")

    print()
    self_pass = sum(1 for r in rows if r[1])
    rule_pass = sum(1 for r in rows if r[2])
    test_pass = sum(1 for r in rows if r[3])
    print(f"通过数：自评 {self_pass}/4   规则 {rule_pass}/4   测试 {test_pass}/4")
    print("自评与规则的判定不一致处：", 
          [r[0] for r in rows if r[1] != r[2]])


if __name__ == "__main__":
    main()
