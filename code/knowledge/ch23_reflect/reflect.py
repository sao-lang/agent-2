"""自评为什么无效，以及三种裁判与三种修复粒度。

不联网。裁判是脚本化的判定函数，用来把"谁在评"和"评得准不准"分开观察。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 产物

BAD = {"order_id": "A1001", "days": 3, "reason": "签收不想要"}
GOOD = {"order_id": "A1001", "days": 30, "reason": "超过退货窗口"}


# ---------------------------------------------------------------- 裁判

def self_review(artifact: dict) -> tuple[bool, str]:
    """自评：只看产物本身，不看依据。脚本化：总是通过。"""
    return True, "看起来合理，字段齐全。"


def rule_review(artifact: dict) -> tuple[bool, str]:
    """规则裁判：业务代码能表达的判据。"""
    days = artifact.get("days")
    reason = artifact.get("reason", "")
    if not isinstance(days, int):
        return False, "days 不是整数"
    if days <= 7 and "超过" in reason:
        return False, "days<=7 却说超过窗口"
    if "签收不想要" in reason:
        return False, "reason 不是政策口径（应引用窗口天数）"
    return True, "通过"


def test_review(artifact: dict, cases: list[dict]) -> tuple[bool, str]:
    """测试裁判：拿一批已知答案比对。"""
    for case in cases:
        if case["order_id"] != artifact.get("order_id"):
            continue
        if case["expect_days"] != artifact.get("days"):
            return False, f"{case['order_id']} 期望 days={case['expect_days']}"
    return True, "与已知答案一致"


# ---------------------------------------------------------------- 修复粒度

def retry_mark() -> str:
    return "retry：原样重跑一次"


def patch(artifact: dict, field: str, value) -> dict:
    new = dict(artifact)
    new[field] = value
    return new


def replan_all_mark() -> str:
    return "replan_all：丢掉当前的中间结果，回到第 1 步重来"


def main() -> None:
    print("=== 同一产物，三种裁判 ===")
    for name, fn in [("自评", self_review), ("规则裁判", rule_review)]:
        ok, why = fn(BAD)
        print(f"  {name:<8} {'通过' if ok else '驳回'}  {why}")
    ok, why = test_review(BAD, [{"order_id": "A1001", "expect_days": 30}])
    print(f"  {'测试裁判':<8} {'通过' if ok else '驳回'}  {why}")

    print()
    print("=== 三种修复粒度 ===")
    fixed = patch(BAD, "reason", "超过 7 天窗口")
    print("  场景 A：规则裁判说 reason 口径不对 -> patch 后：", fixed)
    print("  场景 B：测试裁判说 days 错 ->", retry_mark())
    print("  场景 C：产物方向错（days=30 但订单只签收 3 天）->", replan_all_mark())
    ok, why = rule_review(GOOD)
    print(f"    重规划后换一份产物自检：{'通过' if ok else '驳回'}  {why}")

    print()
    print("=== 自评为什么会放行 ===")
    print("  产物字段：", list(BAD.keys()))
    print("  自评能看到的：产物本身")
    print("  自评看不到的：政策窗口、订单真实天数、测试期望")
    print("  -> 它没有可用于否证的依据，只能凭'像不像'判断")


if __name__ == "__main__":
    main()
