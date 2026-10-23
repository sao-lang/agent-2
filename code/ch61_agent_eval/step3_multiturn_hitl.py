"""第 61 章 step3：多轮与 HITL 中断恢复怎么评测（真跑 LangGraph）。

运行：
    python code/ch61_agent_eval/step3_multiturn_hitl.py

step1/step2 评的是"单轮、一次跑完"的轨迹。
但 Agent 真正的难点在：

    ① 多轮对话：第 3 轮的效果依赖第 1 轮记没记住
    ② HITL 中断：中断后再恢复，**状态对不对、副作用重没重**

这两类**单轮评测完全测不到**。这一级用真实的 LangGraph 跑给你看。

所有输出都是真实运行结果。
"""
from __future__ import annotations

import sys
from typing import Annotated, TypedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 76


def line(t: str) -> None:
    print(f"\n{DPRINT}\n{t}\n{DPRINT}")


# ================================================================ ① 多轮记忆
#
# 关键问题：第 N 轮该看到前几轮的什么？
# 这里用一个可测量的方式：让"用户在第 1 轮说过的事实"在第 3 轮被问到。

class ChatState(TypedDict, total=False):
    turns: Annotated[list[str], lambda a, b: a + b]   # 全部对话
    facts: Annotated[list[str], lambda a, b: a + b]   # 抽取的长期事实
    answer: str


def demo_multiturn() -> None:
    print(DPRINT)
    print("① 多轮：第 3 轮还记不记得第 1 轮说的事")
    print(DPRINT)

    # 用户在第 1 轮说了三件事，第 3 轮只问其中一件
    turn1 = "我上周买的耳机有电流声，订单号 A8821，我是企业版客户"
    turn2 = "我想退掉"
    turn3 = "我的退款什么时候到"

    print(f"  第 1 轮: {turn1}")
    print(f"  第 2 轮: {turn2}")
    print(f"  第 3 轮: {turn3}")
    print()

    # 三种"记忆策略"
    strategies = [
        ("全量历史（不裁剪）",
         lambda hist: hist,
         "每轮都把全部历史给模型"),
        ("只留最近 1 轮",
         lambda hist: hist[-1:],
         "省 token，但第 3 轮看不到 A8821"),
        ("结构化抽取（事实槽位）",
         lambda hist: ["订单号: A8821", "等级: 企业版", "问题: 电流声", hist[-1]],
         "第 1 轮抽出事实，后面每轮都带着"),
    ]

    hist = [turn1, turn2, turn3]
    # 第 3 轮回答"什么时候到"，需要订单号才能查
    needs = ["A8821"]

    print(f"  {'策略':<26} {'第3轮上下文':<10} {'能查到订单?':<14} 代价")
    print(f"  {'-' * 26} {'-' * 10} {'-' * 14} {'-' * 26}")
    for name, fn, cost in strategies:
        ctx = fn(hist)
        joined = " ".join(ctx)
        ok = all(n in joined for n in needs)
        # 上下文长度（字）
        chars = len(joined)
        print(f"  {name:<26} {chars:<10} {'✅ 可以' if ok else '❌ 查不到':<14} {cost}")

    print()
    print("  ---- 三行的区别在哪：")
    print("     · 全量：能查到，但上下文随轮数**线性增长**（第 20 轮就是 20 轮的量）")
    print("     · 只留最近 1 轮：第 3 轮完全不知道订单号 → **必然答错或反问**")
    print("     · 结构化抽取：只占 20 来个字（本例 " + str(len(" ".join(strategies[2][1](hist)))) + " 字），")
    print("       且**轮数增加也不涨** —— 因为事实槽位是固定几条")
    print()
    print("  ---- 这就是多轮评测的第一个判据：**跨轮事实保持率**。")
    print("       做法：在第 1 轮埋 3 个事实，第 N 轮抽查其中 1 个，看回答里有没有用上。")
    print("       这个指标单轮评测**永远测不出来**。")


# ================================================================ ② HITL 恢复
def demo_hitl() -> None:
    print(DPRINT)
    print("② HITL 中断恢复：真跑 LangGraph，看三件事")
    print(DPRINT)

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt

    # 用外部列表记录"副作用发生过几次"（模拟真实数据库）
    side_effects: list[str] = []

    class S(TypedDict, total=False):
        amount: int
        audited: bool
        approved: bool
        log: list[str]

    def audit(s: S) -> dict:
        """有副作用的节点：写审计日志。"""
        side_effects.append(f"audit:{s.get('amount')}")
        return {"audited": True, "log": (s.get("log") or []) + ["audit"]}

    def approve(s: S) -> Command:
        decision = interrupt({"question": f"批准退款 {s.get('amount')} 元？"})
        if decision == "yes":
            return Command(goto="refund", update={"approved": True})
        return Command(goto=END, update={"approved": False})

    def refund(s: S) -> dict:
        side_effects.append(f"refund:{s.get('amount')}")
        return {"log": (s.get("log") or []) + ["refund"]}

    g = StateGraph(S)
    g.add_node("audit", audit)
    g.add_node("approve", approve)
    g.add_node("refund", refund)
    g.add_edge(START, "audit")
    g.add_edge("audit", "approve")
    g.add_edge("refund", END)
    app = g.compile(checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "hitl-1"}}
    print("  场景：audit（有副作用） -> approve（等审批） -> refund（有副作用）")
    print()

    r1 = app.invoke({"amount": 500, "log": []}, cfg)
    print(f"  第一次 invoke 返回: __interrupt__ = {r1.get('__interrupt__') is not None}")
    st1 = app.get_state(cfg)
    print(f"  中断点 next = {st1.next}")
    print(f"  此时副作用记录 = {side_effects}")
    print()
    print("  ---- 中断时，audit 已经跑过了。这是正常的（它在 interrupt 之前）。")
    print()

    r2 = app.invoke(Command(resume="yes"), cfg)
    print(f"  恢复后返回: {r2}")
    print(f"  最终副作用记录 = {side_effects}")
    print()

    # ===== 关键判据 =====
    print("  三条必须检查的判据：")
    print()

    # 判据 1：副作用有没有重复
    audit_count = sum(1 for x in side_effects if x.startswith("audit:"))
    refund_count = sum(1 for x in side_effects if x.startswith("refund:"))
    print(f"  ① 副作用次数：audit {audit_count} 次，refund {refund_count} 次")
    ok1 = audit_count == 1 and refund_count == 1
    print(f"     {'✅ 通过' if ok1 else '❌ 失败：有重复执行'}")
    print()

    # 判据 2：恢复后状态是否完整
    final = app.get_state(cfg).values
    print(f"  ② 最终状态：{dict(final)}")
    print("     注意 log 字段 —— 这里能看到一个真实坑：")
    print(f"     log = {final.get('log')}")
    print()
    ok2 = bool(final.get("audited")) and bool(final.get("approved"))
    print(f"     audited={final.get('audited')} approved={final.get('approved')}"
          f" -> {'✅ 关键状态在' if ok2 else '❌ 丢状态'}")
    print()

    # 判据 3：能不能改主意
    print("  ③ 能不能「改主意」—— 审批人点错了，要撤回")
    print()
    print("     ⚠️ 这里有个真实坑，我们撞了两次才搞对：")
    print("     · 以为「从旧 checkpoint 重放」就能改主意 —— **不行**，")
    print("       重放时 interrupt 仍返回当前状态里存的那个决定。")
    print("     · 以为 update_state 会「回到 interrupt 点」—— **也不会**，")
    print("       带 as_node 的 update_state 直接按该节点的出边推进，")
    print("       本例里 approve 的 goto 是 END，所以图**直接结束**。")
    print()
    print("     正确的做法（也是唯一能保证不重复副作用的做法）：")
    print("       在中断快照上 `update_state({\"approved\": False}, as_node=\"approve\")`。")
    print()
    cfg3 = {"configurable": {"thread_id": "hitl-3"}}
    app.invoke({"amount": 999, "log": []}, cfg3)
    base = len(side_effects)
    app.update_state(cfg3, {"approved": False}, as_node="approve")
    st3 = app.get_state(cfg3)
    print(f"     update_state 后 next = {st3.next}  values = {st3.values}")
    added = side_effects[base:]
    print(f"     新增副作用 = {added or '（无）'}")
    ok3 = not added and st3.values.get("approved") is False
    print(f"     {'✅ 通过：改主意成功，且没有多退一次款' if ok3 else '❌ 失败'}")
    print()
    print("     ---- 这条判据是 HITL 评测里最容易被漏的：")
    print("          不是「能不能恢复」，而是「**点错了能不能撤回，且不多花钱**」。")
    print("          请把它写成一条自动化用例：")
    print("          中断 -> update_state(拒绝) -> 断言 refund 副作用次数不变。")

    print()
    print("  ④ 还有一个必须测的：**拒绝分支**")
    cfg2 = {"configurable": {"thread_id": "hitl-2"}}
    app.invoke({"amount": 800, "log": []}, cfg2)
    before = list(side_effects)
    r3 = app.invoke(Command(resume="no"), cfg2)
    after = list(side_effects)
    print(f"     拒绝后返回: {r3}")
    print(f"     拒绝分支新增副作用: {after[len(before):] or '（无）'}")
    print(f"     {'✅ 正确：拒绝时不应执行 refund' if after == before else '❌ 错误：拒绝却也退了款'}")


# ================================================================ ③ 评测清单
def demo_checklist() -> None:
    print()
    print(DPRINT)
    print("③ 多轮 + HITL 的评测清单（可直接抄进你的项目）")
    print(DPRINT)

    rows = [
        ("跨轮事实保持", "第 1 轮埋 3 个事实，第 N 轮抽查", "回答里用上了该事实"),
        ("跨轮指代消解", "第 1 轮说订单号，第 3 轮说「那个订单」", "正确解析到 A8821"),
        ("上下文不爆", "20 轮对话", "每轮输入 token 不超过阈值"),
        ("中断可恢复", "在 approve 中断，然后 resume", "next 正确，状态不丢"),
        ("副作用不重复", "在 interrupt 前有写操作的节点", "副作用只发生 1 次"),
        ("拒绝分支正确", "resume='no'", "不执行后续写操作"),
        ("可改主意", "在旧快照上重新 resume", "能改，且不重复副作用"),
        ("进程重启可恢复", "中断后换新进程", "用持久化 checkpointer 能恢复"),
    ]
    print(f"  {'评测项':<16} {'怎么造数据':<32} {'通过标准':<28}")
    print(f"  {'-' * 16} {'-' * 32} {'-' * 28}")
    for a, b, c in rows:
        print(f"  {a:<16} {b:<32} {c:<28}")

    print()
    print("  ---- 最后两项（可改主意 / 进程重启）是最常被漏的：")
    print("     · 「可改主意」漏了 → 审批人点错按钮就只能重启整个任务")
    print("     · 「进程重启」漏了 → 开发时用 InMemorySaver 一切正常，")
    print("       上线换成真实进程后，重启即丢失全部中断状态。")
    print()
    print("  一个必须知道的成本：")
    print("   · 单轮评测：1 次调用 / 用例")
    print("   · 多轮评测：N 轮 × 每轮可能多步 = 5~20 倍")
    print("   · 所以多轮评测集通常只有 20~50 条，靠**每个用例覆盖多个断言**补回来。")


if __name__ == "__main__":
    demo_multiturn()
    demo_hitl()
    demo_checklist()
    print()
    print(DPRINT)
    print("step3 完成。三句话带走：")
    print("  1. 多轮要测「跨轮事实保持」：第 1 轮埋事实，第 N 轮抽查用没用上。")
    print("  2. HITL 要测四件事：能恢复 / 副作用不重复 / 拒绝分支正确 / 能改主意。")
    print("  3. 开发用 InMemorySaver 会掩盖「进程重启丢状态」这个线上问题。")
    print(DPRINT)
