"""第 32 章 step3：工具护栏 —— 未登记的工具必须拒绝（离线）。

运行：
    python code/ch32_guardrails/step3_tool_default_deny.py

上一级的痛点：输入侧能拦了，但模型一旦开始调工具，风险从"说错话"变成"做错事"。
这一级做什么：用两级策略（只读 / 写 / 禁止）把工具分成三档，并证明——
             **default allow 会让一个拼错的工具名绕过全部策略。**

右耳边（真正危险的部分）：未登记 = 拒绝。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.guardrails import Decision, ToolPolicy, Verdict  # noqa: E402

# 一个真实的工具清单（客服 Agent 常见）
TOOLS = [
    ("search", {"q": "订单 A12345"}, "只读：查知识库"),
    ("get_order", {"id": "A12345"}, "只读：查订单"),
    ("web_fetch", {"url": "https://example.com/policy"}, "只读：拉网页"),
    ("refund", {"order": "A12345", "amount": 99}, "写：退款"),
    ("update_order", {"id": "A12345", "address": "杭州"}, "写：改订单"),
    ("send_email", {"to": "user@example.com"}, "写：发邮件"),
    ("drop_table", {"name": "orders"}, "禁止：删表"),
    ("shell_exec", {"cmd": "rm -rf /"}, "禁止：执行 shell"),
    # 两个"看起来像被允许"的：
    ("search_orders", {"q": "A12345"}, "拼错的工具名"),
    ("refund_all", {"tenant": "shop-1"}, "没登记过的批量退款"),
]


class DefaultAllowPolicy(ToolPolicy):
    """对照版：未登记就放行。这是很多人的第一版写法。"""

    def check(self, tool, args):  # type: ignore[override]
        if tool in self.forbidden or tool in self.write_tools or tool in self.read_only:
            return super().check(tool, args)
        return Decision(Verdict.ALLOW, "未登记，放行（错误示范）", rule="unknown_allowed")


def main() -> None:
    deny = ToolPolicy()   # 本章版本：default deny
    allow = DefaultAllowPolicy()

    print("=" * 88)
    print("同一批工具调用，两种策略")
    print("=" * 88)
    print(f"{'工具':<16}{'说明':<20}{'default deny':<16}{'default allow'}")
    print("-" * 88)
    leaked = []
    for name, args, note in TOOLS:
        d1 = deny.check(name, args)
        d2 = allow.check(name, args)
        print(f"{name:<16}{note:<20}{d1.verdict.value:<16}{d2.verdict.value}")
        if d1.verdict.value == "deny" and d2.verdict.value != "deny":
            leaked.append(name)

    print("\n" + "=" * 88)
    print("★ 差在哪：两个『看起来无害』的工具名")
    print("=" * 88)
    for name in ("search_orders", "refund_all"):
        args = next(a for n, a, _ in TOOLS if n == name)
        d1, d2 = deny.check(name, args), allow.check(name, args)
        print(f"  {name}")
        print(f"    default deny  → {d1.verdict.value:<12}{d1.reason}")
        print(f"    default allow → {d2.verdict.value:<12}{d2.reason}")
    print()
    print("  search_orders 是 get_order 的拼写错误，本身只读，看似无害。")
    print("  但 refund_all 是一个**没登记过的批量退款**工具——")
    print("  在 default allow 下它直接通过了，没有人写过这条策略。")
    print()
    print(f"  → 在 default allow 下，{len(leaked)} 个工具绕过了策略：{leaked}")

    print("\n" + "=" * 88)
    print("三档分类的判断依据")
    print("=" * 88)
    print(f"  {'档位':<8}{'判据':<38}{'判定'}")
    print("  " + "-" * 70)
    print(f"  {'只读':<8}{'不改任何外部状态，可重复执行':<38}{'ALLOW'}")
    print(f"  {'写':<8}{'会改数据/发消息，且难回滚':<38}{'NEED_HUMAN'}")
    print(f"  {'禁止':<8}{'改的是整个系统/权限/其它租户':<38}{'DENY'}")
    print(f"  {'未登记':<8}{'没人评估过它的风险':<38}{'DENY'}")
    print()
    print("  最难分的是「写」和「禁止」的边界。一条实用判据：")
    print("    · 影响范围是**一条记录** → 写（可以人工确认后执行）")
    print("    · 影响范围是**一批数据 / 一个库 / 一个租户** → 禁止")

    print("\n" + "=" * 88)
    print("三个必然遇到的坑")
    print("=" * 88)
    print("  坑 1：工具名对不上")
    print("    模型可能生成 `search_orders`（它觉得更自然），而你的策略表里是 `get_order`。")
    print("    → default deny 下这不会造成损害，只是这次调用失败。这恰恰是好事。")
    print()
    print("  坑 2：参数可以绕过语义")
    print("    `refund(order='A12345', amount=999999)` —— 工具名合法，参数不合理。")
    print("    → 工具策略必须能看参数，不能只看名字（本章的 check(tool, args) 就留了这个口子）。")
    print()
    print("  坑 3：策略表和实际工具表不同步")
    print("    新增了一个工具但忘了登记 → default deny 下它直接不可用，")
    print("    上线第一天就会暴露；default allow 下它会静默获得全部权限。")
    print("    → 这正是 default deny 的另一个价值：**把『忘登记』变成显式失败**。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  default deny 是安全设计里最古老、也最有效的原则：")
    print("    · 未登记 → 拒绝（显式失败，容易发现）")
    print("    · 默认放行 → 静默获得权限（最难发现的一种漏洞）")


if __name__ == "__main__":
    main()
