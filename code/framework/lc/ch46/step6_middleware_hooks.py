"""第 46 章 step6：AgentMiddleware 的完整钩子表与内置中间件清单（离线）。

运行：
    python code/framework/lc/ch46/step6_middleware_hooks.py

第 46 章讲了 create_agent 和"中间件有顺序"，但没给完整的钩子表。
这一级补上：

    ① 中间件顺序的源码级证据（第 46.5 节讲过行为，这里补「为什么」）
    ② 内置中间件的真实签名（从类上读出来的，不是抄文档）
    ③ ToolCallLimitMiddleware 的 exit_behavior 三档差异
    ④ 自定义中间件的三个限制

全程不调模型，所以完全离线、可复现。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 78


# ================================================================ ① 源码级证据
#
# 第 46.5 节已经讲了「6 个钩子 + 洋葱皮顺序」。
# 这里只补**证据**：顺序不是猜的，是从 langchain 源码里读出来的。
# 有一处和直觉不同，值得单独看。


def demo_source_order() -> None:
    print(DPRINT)
    print("① 中间件顺序的源码级证据")
    print(DPRINT)

    print("  第 46.5 节讲了「洋葱皮」。这一节回答一个更细的问题：")
    print("  **after_* 到底是正序还是逆序？**")
    print()
    print("  langchain/agents/factory.py 里的真实代码：")
    print()
    for line in [
        'entry_node      = f"{middleware_w_before_agent[0].name}.before_agent"',
        'loop_entry_node = f"{middleware_w_before_model[0].name}.before_model"',
        'loop_exit_node  = f"{middleware_w_after_model[0].name}.after_model"',
        'exit_node       = f"{middleware_w_after_agent[-1].name}.after_agent"',
    ]:
        print("    " + line)
    print()
    print("  两处 [0]，一处 [-1]：")
    print()
    rows = [
        ("before_agent", "[0]", "正序：列表第一个最先进入"),
        ("before_model", "[0]", "正序"),
        ("after_model", "[0]", "**看着是正序，实际是逆序** —— 见下"),
        ("after_agent", "[-1]", "逆序：列表最后一个最先退出"),
    ]
    print(f"  {'钩子':<16} {'下标':<8} 含义")
    print(f"  {'-' * 16} {'-' * 8} {'-' * 44}")
    for a_, b_, c_ in rows:
        print(f"  {a_:<16} {b_:<8} {c_}")

    print()
    print("  ---- 为什么 after_model 的 [0] 反而是「最后执行」？")
    print()
    print("  **因为整个中间件栈被编译成了一张 LangGraph 图，不是简单的函数链。**")
    print("  before_* 是一条入链，after_* 是一条出链，两条链的节点命名里都带下标。")
    print("  出链从 [0] 这个**入口**接入，但图的实际执行是从最里层往外退的。")
    print()
    print("  一个更可靠的记忆方式：**你拿到的观测结果，永远符合洋葱皮模型。**")
    print("  before 正序进、after 逆序出 —— 不管源码下标怎么写，行为是这样。")
    print()
    print("  而 wrap_* 的源码注释直接写明：")
    print("       Composes handlers so first in list becomes outermost layer.")
    print("  → 列表第一个 = 最外层。想「外层先拦截」就把拦截器放列表最前面。")


# ================================================================ ② 内置中间件
def demo_builtin() -> None:
    print()
    print(DPRINT)
    print("② 内置中间件的真实签名（从类上读出来的）")
    print(DPRINT)

    try:
        import langchain.agents.middleware as M
    except ImportError as e:
        print(f"  需要 langchain >= 1.x：{e}")
        return

    names = [
        "ModelCallLimitMiddleware", "ToolCallLimitMiddleware",
        "ToolRetryMiddleware", "ModelFallbackMiddleware",
        "SummarizationMiddleware", "PIIMiddleware", "HumanInTheLoopMiddleware",
    ]
    for n in names:
        cls = getattr(M, n, None)
        if cls is None:
            print(f"  {n}: 不存在")
            continue
        sig = str(inspect.signature(cls.__init__))
        sig = sig.replace("(self, ", "(").replace("'", "")
        print(f"  {n}")
        print(f"    {sig[:150]}")
        print()

    print("  ---- 重点讲 ToolCallLimitMiddleware 的 exit_behavior 三档（这是最容易配错的）：")
    print()
    rows = [
        ("continue（默认）", "拦截超限的工具，其余继续", "模型会收到一个「被拦截」的 ToolMessage，可以换策略",
         "想让它「自己想办法」，比如搜索超限就改用精确查询"),
        ("error", "直接抛异常", "整个 Agent 崩掉，调用方拿到异常",
         "严格场景：超限即视为 bug"),
        ("end", "立刻结束，为每个超限调用生成 ToolMessage", "返回一个说明为什么停的 AI 消息",
         "成本敏感：超限就收工，别烧钱"),
    ]
    print(f"  {'取值':<16} {'行为':<30} {'模型看到什么':<38} 什么时候用")
    print(f"  {'-' * 16} {'-' * 30} {'-' * 38} {'-' * 26}")
    for a, b, c, d in rows:
        print(f"  {a:<16} {b:<30} {c:<38} {d}")

    print()
    print("  ---- 默认值是 continue，很多人以为超限就自动停了，其实不会。")
    print("       如果你的需求是「超了就停」，必须显式写 exit_behavior=end。")


# ================================================================ ④ 限制
def demo_limits() -> None:
    print()
    print(DPRINT)
    print("③ 自定义中间件的三个限制")
    print(DPRINT)

    rows = [
        ("before_* 的返回值会**合并进 state**，不是替换",
         "返回 {'messages': [x]} 是追加（有 reducer 时），返回整个 messages 想覆盖是做不到的",
         "只返回你要改的字段"),
        ("wrap_* 里不调用 handler 就等于「不发生」",
         "wrap_tool_call 里直接 return 一个假 ToolMessage，工具真的不会被调用",
         "这既是权力也是坑：权限拦截用它，但别不小心跳过真正的调用"),
        ("中间件拿不到「上一次工具的结果」除非从 state 读",
         "中间件本身无状态，每次都是纯函数；跨步骤信息必须落进 state",
         "要跨步记忆，就在 before_model 里从 state 读、算完写回去"),
    ]
    print(f"  {'限制':<44} 说明")
    print(f"  {'-' * 44} {'-' * 40}")
    for a, b, _c in rows:
        print(f"  {a:<44} {b}")

    print()
    print("  ---- 第三条最容易被误解：")
    print("     很多人以为中间件是「有状态的对象」，可以在 self 上存东西。")
    print("     **可以存，但并发时不安全**（同一个中间件实例被多个请求共用）。")
    print("     正确做法：临时状态放进 state 或 runtime.context。")


def demo_checklist() -> None:
    print()
    print(DPRINT)
    print("④ 写中间件的检查清单")
    print(DPRINT)
    items = [
        ("要「观察」还是「阻止」？", "观察用 before/after，阻止必须用 wrap_*"),
        ("要不要跨步记忆？", "要 -> 读写 state；不要 -> 保持纯函数"),
        ("异常时怎么办？", "抛出（调用方处理）还是返回降级值（继续跑）"),
        ("并发安全吗？", "self 上不存可变状态"),
        ("放第几层？", "见 ② 的推荐顺序"),
        ("异步版实现了吗？", "服务端是 async 的话，只写同步版会阻塞事件循环"),
    ]
    print(f"  {'问题':<26} 结论")
    print(f"  {'-' * 26} {'-' * 46}")
    for a, b in items:
        print(f"  {a:<26} {b}")


if __name__ == "__main__":
    demo_source_order()
    demo_builtin()
    demo_limits()
    demo_checklist()
    print()
    print(DPRINT)
    print("step6 完成。四句话带走：")
    print("  1. before/after 是「观察+打补丁」，wrap_* 是「控制流」——想阻止必须用 wrap。")
    print("  2. 包装顺序是洋葱：before 正序、after 逆序、wrap 嵌套。超时放最外层。")
    print("  3. ToolCallLimitMiddleware 默认 exit_behavior='continue'，超限不会自动停。")
    print("  4. 中间件别在 self 上存可变状态，并发会串数据。")
    print(DPRINT)
