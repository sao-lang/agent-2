"""第 50 章 step3：子图、Supervisor / Handoff、CachePolicy（离线）。

运行：
    python code/framework/lg/ch50/step3_subgraph_multiagent.py

上一级的痛点：
    一个图的节点多到 20 个就画不清了；想复用"客服子流程"却只能复制粘贴。

这一级做什么：
    ① 子图：把一个编译好的图当成节点（状态可以共享，也可以只有一部分）
    ② Supervisor：一个"调度员"节点决定下一步交给谁（第 36 章的落地形态）
    ③ Handoff：不是"我来做"，而是"转交给你，并带上状态"
    ④ CachePolicy / RetryPolicy / 超时：三种运行时策略的真实配置
    ⑤ 一个必须知道的判断：什么时候该拆多 Agent（第 36 章的结论）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

sys.path.insert(0, str(Path(__file__).parent))


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


class Parent(TypedDict):
    question: str
    answer: str
    trace: Annotated[list[str], lambda a, b: a + b]


class Sub(TypedDict):
    question: str
    answer: str


def make_sub(name: str) -> object:
    """一个对外只有一个键的"子流程"：输入 question，输出 answer。"""
    def step(state: Sub) -> dict:
        return {"answer": f"[{name}] 处理了：{state['question']}"}

    g = StateGraph(Sub)
    g.add_node("step", step)
    g.add_edge(START, "step")
    g.add_edge("step", END)
    return g.compile()


def main() -> None:
    line("① 子图：编译好的图可以直接 add_node")
    sub = make_sub("退款子流程")

    def wrap(state: Parent) -> dict:
        r = sub.invoke({"question": state["question"], "answer": ""})
        return {"answer": r["answer"], "trace": ["subgraph"]}

    g = StateGraph(Parent)
    g.add_node("refund_sub", wrap)
    g.add_edge(START, "refund_sub")
    g.add_edge("refund_sub", END)
    out = g.compile().invoke({"question": "能退吗", "answer": "", "trace": []})
    print(f"  {out['answer']}")
    print("\n  → 共享键（question/answer）自动传进传出；子图内部字段不需要暴露给父图")
    print("  → 真实项目：子图用来「复用一段流程」，而不是「拆服务」。别为了解耦硬拆。")

    line("② Supervisor：一个调度员决定下一步交给谁")
    class TeamState(TypedDict):
        question: str
        next: str
        result: str
        trace: Annotated[list[str], lambda a, b: a + b]

    def supervisor(state: TeamState) -> dict:
        q = state["question"]
        if state["result"]:              # ★ 已经干完 → 收工，否则会无限循环
            return {"next": "FINISH", "trace": ["supervisor→FINISH"]}
        nxt = "refund_agent" if "退款" in q else "tech_agent" if "坏" in q else "FINISH"
        return {"next": nxt, "trace": [f"supervisor→{nxt}"]}

    def refund_agent(state: TeamState) -> dict:
        return {"result": "退款已受理", "trace": ["refund_agent"]}

    def tech_agent(state: TeamState) -> dict:
        return {"result": "已安排换新", "trace": ["tech_agent"]}

    team = StateGraph(TeamState)
    team.add_node("supervisor", supervisor)
    team.add_node("refund_agent", refund_agent)
    team.add_node("tech_agent", tech_agent)
    team.add_edge(START, "supervisor")
    team.add_conditional_edges(
        "supervisor",
        lambda s: s["next"],
        {"refund_agent": "refund_agent", "tech_agent": "tech_agent", "FINISH": END},
    )
    team.add_edge("refund_agent", "supervisor")     # 干完回到调度员
    team.add_edge("tech_agent", "supervisor")
    team_app = team.compile()

    for q in ["我要退款", "耳机坏了", "你们几点下班"]:
        r = team_app.invoke({"question": q, "next": "", "result": "", "trace": []})
        print(f"  {q:<8} trace={r['trace']}  result={r['result']!r}")

    print("\n  → 代价：每个问题至少多一次模型调用（调度员）。")
    print("    第 36 章实测：简单任务拆多 Agent 更慢、更贵、更差。只在**边界清晰且互不干扰**时拆。")
    print("  ⚠️ 注意上面那个 if state['result']：没有它，supervisor 会一直派活，")
    print("     直到 GraphRecursionError（默认 recursion_limit 很高，能空转上万步）。")
    print("     这就是第 16 章说的「循环失控」，在多 Agent 里同样存在。")

    line("③ Handoff：转交 = Command(goto=..., update=...)，而不是「我来做」")
    print("""  def refund_agent(state):
      if 需要技术支持(state):
          return Command(goto="tech_agent", update={"handoff_reason": "需要工程师"})
      return Command(goto=END, update={"result": "退款已受理"})

  → 和 supervisor 的区别：
      Supervisor：每次都回到调度员（集中式，好调试，多一次 LLM 调用）
      Handoff   ：直接交给下一个（去中心化，省一次调用，但链路难追踪）
  → 两条链路都必须把 handoff 记进 trace，否则线上根本看不出谁接的手。
    """)

    line("④ 三种运行时策略")
    from langgraph.types import RetryPolicy

    calls = {"n": 0}

    def expensive(state: Parent) -> dict:
        calls["n"] += 1
        return {"answer": f"第 {calls['n']} 次计算", "trace": ["expensive"]}

    g2 = StateGraph(Parent)
    g2.add_node(
        "expensive",
        expensive,
        retry_policy=RetryPolicy(max_attempts=2, retry_on=ConnectionError),
    )
    g2.add_edge(START, "expensive")
    g2.add_edge("expensive", END)
    app2 = g2.compile()
    app2.invoke({"question": "same", "answer": "", "trace": []})
    app2.invoke({"question": "same", "answer": "", "trace": []})
    print(f"  两次相同输入 → 节点执行 {calls['n']} 次（没有 CachePolicy，所以每次都真算）")

    print("""
  三个策略各管一件事：
    RetryPolicy   失败重试        max_attempts / initial_interval / retry_on（异常类）
    CachePolicy   相同输入复用    ttl（秒）/ key_func；只在 compile(cache=BaseCache()) 时生效
    Timeout       没有节点级参数  用 asyncio.wait_for 或 HTTP 客户端 timeout（第 35 章）
    """)
    print("  ⚠️ 踩坑直说：只写 cache_policy=CachePolicy(ttl=60) 而 compile() 时没传 cache=，")
    print("     缓存是**静默不生效**的 —— 又一次「装配错误不报错」（见第 54.1 节）。")

    line("⑤ 一个必须知道的判断：该不该拆多 Agent")
    table = [
        ("任务边界清晰（退款 / 技术 / 物流）", "可以拆"),
        ("每个子任务都要看完整上下文", "别拆，只会多付一遍上下文钱"),
        ("子任务能并行", "可以拆（Send）"),
        ("只是「步骤多」", "用一张图 + 多个节点，不要拆 Agent"),
        ("需要不同权限/不同工具集", "可以拆（收窄工具，第 55 章）"),
    ]
    for cond, verdict in table:
        print(f"  {cond:<36}{verdict}")
    print("\n  → 一句话：拆多 Agent 的理由应该是「隔离」，不是「分工」。分工用节点就够了。")


if __name__ == "__main__":
    main()
