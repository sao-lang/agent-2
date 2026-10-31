"""预算耗尽 → 降级交付：终止原因是 budget，不是 failed。

不联网。任务是写 6 节报告，预算是 token 上限；跑到一半预算用尽时，
出口 on_exit 把已完成的 3 节整理成可交付的部分产物，并在末尾标注缺哪几节。

运行：python code/forms/loop_engineering/budget_degrade.py
"""

from __future__ import annotations

from loop_core import Action, Hooks, Limits, Loop

SECTIONS = [
    "一、现状：三条线索引擎的召回率分别落在 0.61 / 0.58 / 0.66，差距在切块粒度上。",
    "二、成因：切块按固定字数，表格与列表被切断，检索命中后拼不回原结构。",
    "三、验证：把三份索引换成按标题切块，同一批查询的命中位置前移了一位。",
    "四、代价：切块数增加约四成，索引体积与检索延迟同步上升。",
    "五、结论：标题切块在结构化文档上优于固定字数，非结构化文档相反。",
    "六、后续：把切块策略做成按文档类型路由，先用规则，规则不覆盖时再上模型。",
]
TASK = "写一份 6 节的切块策略评估报告"
BUDGET = 150


def make_policy():
    def policy(lp: Loop, obs: str) -> Action | None:
        done = lp.state.setdefault("done", 0)
        if done >= len(SECTIONS):
            return None
        return Action("write", f"第{done + 1}节")
    return policy


def make_act():
    def act(lp: Loop, action: Action) -> str:
        idx = lp.state.get("done", 0)
        body = SECTIONS[idx]
        lp.state.setdefault("sections", []).append(body)
        lp.state["done"] = idx + 1
        return f"已写入{body[:18]}…（累计 {len(lp.state['sections'])} 节，{sum(len(s) for s in lp.state['sections'])} 字）"
    return act


def budget_hook(lp: Loop, obs: str, action: Action | None) -> str | None:
    if lp.tokens > lp.limits.max_tokens:
        return "budget"
    return None


def degrade(lp: Loop, reason: str) -> str:
    """出口：把已有产物整理成可交付，缺的部分写清楚。"""
    parts = lp.state.get("sections", [])
    if not parts:
        return ""
    if reason == "completed":
        return "\n".join(parts)
    missing = [f"第{i + 1}节" for i in range(len(parts), len(SECTIONS))]
    return ("\n".join(parts)
            + f"\n\n[降级交付] 终止原因={reason}；缺 {len(missing)} 节：{'、'.join(missing)}；"
              f"以上 {len(parts)} 节未经整体审阅。")


def run(degrade_on_exit: bool) -> Loop:
    hooks = Hooks(before_step=budget_hook, on_exit=degrade if degrade_on_exit else None)
    lp = Loop(f"budget-{int(degrade_on_exit)}", make_policy(), make_act(),
              Limits(max_steps=10, max_tokens=BUDGET), hooks)
    lp.result = lp.run(TASK)
    return lp


def main() -> None:
    print("=== 1. 预算耗尽后的轨迹（终止原因 = budget） ===")
    lp = run(degrade_on_exit=True)
    print(f"    {lp.result.reason}  步数={lp.result.steps}  tokens={lp.result.tokens}  "
          f"降级={lp.result.degraded}  交付={len(lp.result.delivered)} 字")
    for row in lp.records:
        print(f"    step={row['step']} {row['action']:<10} tokens={row['tokens']:>4} "
              f"obs={row['observation_hash']} state={row['state_digest']}")

    print()
    print("=== 2. 降级交付的全文 ===")
    for line in lp.result.delivered.splitlines():
        print(f"    {line}")

    print()
    print("=== 3. 同一个循环，把预算耗尽当失败（出口不整理产物） ===")
    lp2 = run(degrade_on_exit=False)
    print(f"    {lp2.result.reason}  降级={lp2.result.degraded}  交付={len(lp2.result.delivered)} 字")
    print("    同样的 3 节内容已经写出来了，只是没有出口把它们交出去")

    print()
    print("=== 4. 两种记账 ===")
    print(f"    当降级：可用产出 {len(lp.result.delivered)} 字，标了缺哪几节")
    print(f"    当失败：可用产出 {len(lp2.result.delivered)} 字，调用成本一分没少花")


if __name__ == "__main__":
    main()

