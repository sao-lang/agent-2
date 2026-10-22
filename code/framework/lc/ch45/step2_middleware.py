"""第 45 章 step2：中间件——Agent 的可插拔行为层（离线）。

运行：
    python code/framework/lc/ch45/step2_middleware.py

上一级的痛点：
    你想给 Agent 加"最多调 5 次模型""每 3 轮摘要一次""危险工具要审批"。
    在 0.x 里只能改 base prompt 或包一层 while 循环 —— 越加越乱。

这一级做什么：
    ① 列出 1.x 内置中间件（本机真实导入的）
    ② 用 3 个内置中间件跑起来，看它们各自改了什么
    ③ 写一个自定义中间件（6 个钩子）
    ④ 一个坑：中间件顺序会影响结果

核心心智模型：
    中间件 = 在固定的几个点上"插一脚"的类。钩子只有 6 个，但足够覆盖
    限流、重试、降级、摘要、审批、PII、待办清单……
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import ai, scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


@tool
def query_order(order_id: str) -> str:
    """查订单状态"""
    return f"{order_id}: 在保修期内"


def main() -> None:
    line("① 1.x 内置中间件（本机真实可导入的）")
    import langchain.agents.middleware as M

    builtin = [
        ("ModelCallLimitMiddleware", "限制模型调用次数（防死循环）"),
        ("ToolCallLimitMiddleware", "限制工具调用次数"),
        ("ModelRetryMiddleware", "模型调用失败重试"),
        ("ToolRetryMiddleware", "工具调用失败重试"),
        ("ModelFallbackMiddleware", "主模型失败换备胎"),
        ("ToolErrorMiddleware", "工具异常转成给模型看的文本"),
        ("SummarizationMiddleware", "上下文太长时自动摘要"),
        ("HumanInTheLoopMiddleware", "危险动作前中断，等人工审批"),
        ("TodoListMiddleware", "给 Agent 一个待办清单"),
        ("PIIMiddleware", "检测/脱敏个人信息"),
        ("LLMToolSelectorMiddleware", "工具太多时先用小模型挑"),
        ("ContextEditingMiddleware", "清理/编辑历史上下文"),
    ]
    for name, desc in builtin:
        mark = "✓" if hasattr(M, name) else "—"
        print(f"  {mark} {name:<30}{desc}")

    line("② 内置中间件实跑：限流 + 工具错误 + 待办清单")
    from langchain.agents import create_agent
    from langchain.agents.middleware import (
        ModelCallLimitMiddleware,
        TodoListMiddleware,
        ToolErrorMiddleware,
    )

    @tool
    def broken_tool(x: str) -> str:
        """故意失败的示例工具"""
        raise ValueError("数据库连不上")

    def on_error(e: Exception, request: Any) -> str:  # noqa: ANN001, ARG001
        """把异常翻译成"人话"，模型读到后可以自救。"""
        return f"工具执行失败（{type(e).__name__}）：{e}。请勿重试，直接告知用户稍后再试。"

    model = scripted(
        ai(tool_calls=[{"name": "broken_tool", "args": {"x": "1"}}]),
        ai("工具失败了，我先告诉用户稍后再试。"),
    )
    agent = create_agent(
        model,
        tools=[broken_tool],
        middleware=[
            ModelCallLimitMiddleware(run_limit=5),
            ToolErrorMiddleware(on_error=on_error),
            TodoListMiddleware(),
        ],
    )
    out = agent.invoke({"messages": [HumanMessage("查一下")]})
    print(f"  消息数 = {len(out['messages'])}")
    for m in out["messages"]:
        kind = type(m).__name__
        body = m.content if isinstance(m.content, str) else str(m.content)
        print(f"    {kind:<14}{body[:70]!r}")
    print("\n  → ToolErrorMiddleware 把 ValueError 变成 ToolMessage 文本，模型能读到并自救")

    line("③ 自定义中间件：6 个钩子各插在哪")
    from langchain.agents.middleware import AgentMiddleware

    events: list[str] = []

    class Audit(AgentMiddleware):
        """记录每个阶段，并统计模型调用次数。"""

        def before_agent(self, state, runtime):  # noqa: ANN001
            events.append("before_agent")
            return None

        def before_model(self, state, runtime):  # noqa: ANN001
            events.append(f"before_model(messages={len(state['messages'])})")
            return None

        def after_model(self, state, runtime):  # noqa: ANN001
            last = state["messages"][-1]
            calls = len(getattr(last, "tool_calls", []) or [])
            events.append(f"after_model(tool_calls={calls})")
            return None

        def after_agent(self, state, runtime):  # noqa: ANN001
            events.append("after_agent")
            return None

    model2 = scripted(
        ai(tool_calls=[{"name": "query_order", "args": {"order_id": "A1"}}]),
        ai("在保修期内，可以免费维修。"),
    )
    agent2 = create_agent(model2, tools=[query_order], middleware=[Audit()])
    agent2.invoke({"messages": [HumanMessage("A1 还行吗")]})
    print("  钩子触发顺序：")
    for e in events:
        print(f"    {e}")

    print("""
  六个钩子的位置：

    before_agent ──┐                       ┌── after_agent
                   ├─► before_model ─► model ─► after_model ─┐
                   │                                          │
                   └────────────── 循环 ◄── tools ◄───────────┘

    wrap_model_call(request, handler)   包住「这一次模型调用」（改消息/换模型/计费）
    wrap_tool_call(request, handler)    包住「这一次工具调用」（审批/改参/重试）
    """)

    line("④ 一个坑：中间件顺序 = 洋葱皮")
    class Tag(AgentMiddleware):
        def __init__(self, tag: str) -> None:
            super().__init__()
            self._tag = tag

        @property
        def name(self) -> str:  # 覆盖只读属性，让两个实例名字不同
            return f"Tag-{self._tag}"

        def before_model(self, state, runtime):  # noqa: ANN001
            print(f"      enter {self._tag}")
            return None

        def after_model(self, state, runtime):  # noqa: ANN001
            print(f"      exit  {self._tag}")
            return None

    m = scripted("好")
    print("  顺序 [A, B]：")
    create_agent(m, tools=[], middleware=[Tag("A"), Tag("B")]).invoke({"messages": [HumanMessage("hi")]})
    print("  → 进入顺序 A→B，退出顺序 B→A（洋葱皮）。想「外层先拦截」就把拦截器放前面")
    print("  → 两个同类中间件必须有不同的 name（默认是类名），否则报 duplicate middleware")

    line("⑤ 一个反直觉：中间件能改状态，但不能改「用户的意图」")
    print("  中间件擅长：限流、重试、降级、摘要、审批、脱敏")
    print("  中间件不擅长：改业务规则（那是工具和提示词的事）")
    print("  → 用中间件兜「系统韧性」，不用它兜「业务正确性」")


if __name__ == "__main__":
    main()
