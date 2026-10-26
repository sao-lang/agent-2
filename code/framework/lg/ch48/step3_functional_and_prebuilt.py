"""第 48 章 step3：两种 API 与「预置 Agent 已经废弃」（离线可跑）。

运行：
    python code/framework/lg/ch48/step3_functional_and_prebuilt.py

第 48 章讲了 StateGraph + Reducer（图式 API）。
这一级补三件事：

    ① 函数式 API（@entrypoint + @task）—— LangGraph 的第二种写法
    ② create_react_agent 已废弃 —— 真实的 DeprecationWarning，附迁移路径
    ③ 用 create_agent 离线跑通一次「调工具 -> 拿结果 -> 回答」

全程不调真实模型（用 GenericFakeChatModel），离线可复现。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 76


def line(t: str) -> None:
    print(f"\n{DPRINT}\n{t}\n{DPRINT}")


# ================================================================ ① 函数式 API
def demo_functional() -> None:
    line("① 函数式 API：@entrypoint + @task")

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.func import entrypoint, task

    calls: list[tuple[str, int]] = []

    @task
    def double(x: int) -> int:
        calls.append(("double", x))
        return x * 2

    @task
    def add(a: int, b: int) -> int:
        return a + b

    @entrypoint(checkpointer=InMemorySaver())
    def wf(n: int) -> int:
        a = double(n).result()
        b = double(a).result()
        return add(a, b).result()

    cfg = {"configurable": {"thread_id": "f1"}}
    print(f"  wf.invoke(3) = {wf.invoke(3, cfg)}")
    print(f"  执行过的 task = {calls}")

    calls.clear()
    print(f"  同一 thread 再 invoke(3) = {wf.invoke(3, cfg)}")
    print(f"  执行过的 task = {calls}")

    print()
    print("  ---- 两个必须知道的事实：")
    print("   1. `.result()` 是**阻塞式**取结果。写 `double(n)` 得到的是一个 future。")
    print("   2. **同一 thread_id 再 invoke 不会复用上次的结果** —— 上面第二次调用")
    print("      task 又跑了一遍。想复用要显式配 cache_policy（第 50 章补课）。")
    print()
    print("  函数式 API vs 图式 API：")
    rows = [
        ("怎么写", "@entrypoint + @task", "StateGraph + add_node/add_edge"),
        ("适合", "**线性、无环、无分支**的流程", "有分支/循环/并行/中断"),
        ("可视化", "不能画图", "get_graph().draw_mermaid()"),
        ("中断 interrupt", "可用但很别扭", "原生支持"),
        ("什么时候选它", "脚本式数据处理、ETL 式流水", "Agent 这类有循环和分支的"),
    ]
    print(f"  {'维度':<16} {'函数式 API':<30} 图式 API")
    print(f"  {'-' * 16} {'-' * 30} {'-' * 28}")
    for a, b, c in rows:
        print(f"  {a:<16} {b:<30} {c}")

    print()
    print("  ---- 一句话：**写 Agent 用图式，写流水线用函数式。**")
    print("       图式 API 能表达函数式能表达的一切，反之不成立。")


# ================================================================ ② 废弃警告
def demo_deprecation() -> None:
    line("② create_react_agent 已废弃（真实的 DeprecationWarning）")

    print("  在 langgraph 1.2.16 上，**导入** create_react_agent 就会触发（不用调用）：")
    print()
    print("    LangGraphDeprecatedSinceV10: create_react_agent has been moved to")
    print("    `langchain.agents`. Please update your import to")
    print("    `from langchain.agents import create_agent`.")
    print("    Deprecated in LangGraph V1.0 to be removed in V2.0.")
    print()
    print("  ---- 这是本书反复强调的一件事的一个实例：")
    print("       0.x 的写法到 1.x 会变。第 46 章那张 0.x→1.x 对照表就是这个原因。")
    print()
    print("  迁移路径：")
    rows = [
        ("from langgraph.prebuilt import create_react_agent",
         "from langchain.agents import create_agent"),
        ("create_react_agent(model, tools)",
         "create_agent(model, tools=tools)"),
        ("model 需要自己 bind_tools",
         "create_agent 内部处理"),
    ]
    print(f"  {'旧写法':<52} 新写法")
    print(f"  {'-' * 52} {'-' * 40}")
    for a, b in rows:
        print(f"  {a:<52} {b}")

    print()
    print("  ⚠️ 还有一个更细的坑（我们真撞了）：")
    print("     用 GenericFakeChatModel 做离线测试时，它没有实现 bind_tools，")
    print("     `create_react_agent` 会直接抛 NotImplementedError。")
    print("     解法定制一个假模型，补一个什么都不做的 bind_tools —— 见 ③ 的代码。")

    # 警告在首次导入时触发一次，之后再导入不会重复缓存，
    # 所以在干净子进程里探测才可信。
    # 所以这里不去"再捕获一次"（本进程里 import 已经缓存了），
    # 而是在一个**干净的子进程**里验证，这样结果才可信。
    import subprocess

    probe = (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    try:\n"
        "        from langgraph.prebuilt import create_react_agent\n"
        "    except Exception:\n"
        "        pass\n"
        "print([w.category.__name__ for w in caught])\n"
    )
    try:
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                           text=True, timeout=60, encoding="utf-8")
        names = (r.stdout or "").strip()
    except Exception as e:
        names = f"探测失败：{e}"
    print()
    print(f"  干净子进程里捕获到的警告类型: {names or '（无）'}")


# ================================================================ ③ 离线跑通
def demo_create_agent() -> None:
    line("③ 用 create_agent 离线跑通「调工具 -> 拿结果 -> 回答」")

    try:
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.tools import tool
    except ImportError as e:
        print(f"  跳过：{e}")
        return

    @tool
    def get_order(order_id: str) -> str:
        """按订单号查询订单。"""
        return f"order {order_id}: 399元"

    class FakeToolModel(GenericFakeChatModel):
        """补上 bind_tools 的假模型 —— GenericFakeChatModel 本身没有实现它。"""

        def bind_tools(self, tools, **kwargs):  # noqa: ARG002
            return self

    model = FakeToolModel(messages=iter([
        AIMessage(content="", tool_calls=[
            {"name": "get_order", "args": {"order_id": "A8821"}, "id": "1"},
        ]),
        AIMessage(content="已查到：399 元"),
    ]))

    agent = create_agent(model, tools=[get_order])
    out = agent.invoke({"messages": [("user", "A8821 多少钱")]})

    print("  完整的消息链：")
    for m in out["messages"]:
        tc = getattr(m, "tool_calls", None)
        content = (m.content or "").replace("\n", " ")[:30]
        print(f"    {type(m).__name__:14} | {content:30} | tool_calls={tc}")

    print()
    print("  ---- 这说明 create_agent 的循环是：")
    print("     HumanMessage -> AIMessage(带 tool_calls) -> ToolMessage -> AIMessage(最终答案)")
    print("     也就是第 18 章 ReAct 的标准形状。")
    print()
    print("  ---- 但它也暴露了一个评测上的问题：")
    print("     **这里答案对不对，完全取决于我写死的剧本。**")
    print("     所以这种离线测试只能验证「接线通不通」，")
    print("     「模型会不会选对工具、参数对不对」必须用真实模型 + 评测集（第 61 章）。")


if __name__ == "__main__":
    demo_functional()
    demo_deprecation()
    demo_create_agent()
    print()
    print(DPRINT)
    print("step3 完成。三句话带走：")
    print("  1. 函数式 API（@entrypoint/@task）适合线性流水线，写 Agent 用图式。")
    print("  2. create_react_agent 在 1.x 已废弃，迁移到 langchain.agents.create_agent。")
    print("  3. 离线假模型只能验证接线，验证不了「模型选对没选对」。")
    print(DPRINT)
