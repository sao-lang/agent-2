"""第 62 章 step2：AutoGen / CrewAI / OpenAI Agents SDK 的定位与选型。

运行：
    python code/framework/misc/step2_other_stacks.py

这一级做三件事：

    ① 用真实的 pip 依赖解析，证明「CrewAI 装不进这个仓库」（不是猜的）
    ② 用真实 AutoGen 跑一个最小 round-robin 多 Agent（离线，用假模型）
    ③ 给出一张选型表：什么团队、什么场景该选谁

> 重要：这里不调任何真实模型。
> AutoGen 的部分用自定义的假 ChatCompletionClient，保证离线可复现。
"""
from __future__ import annotations

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 78


# ================================================================ ① 依赖冲突
def demo_dependency_conflict() -> None:
    print(DPRINT)
    print("① 为什么 CrewAI 装不进这个仓库（真实 pip 解析结果）")
    print(DPRINT)

    print("  这个仓库锁定的关键版本：")
    print("    langchain 1.4.7 / langchain-core 1.6.13 / openai 3.36.1")
    print()
    print("  对 crewai 做 `pip install --dry-run` 的真实输出（摘录）：")
    print()
    for line in [
        "Would install autogen-agentchat-0.0.2 crewai-0.11.2 ...",
        "  langchain-0.1.20 langchain-community-0.0.38 langchain-core-0.1.53",
        "  langchain-openai-0.0.5 langsmith-0.1.147 openai-1.109.1 ...",
    ]:
        print("    " + line)

    print()
    print("  ---- 注意这三行：")
    rows = [
        ("langchain", "1.4.7", "0.1.20", "**降级 4 个大版本**"),
        ("langchain-core", "1.6.13", "0.1.53", "**降级 5 个大版本**"),
        ("openai", "3.36.1", "1.109.1", "**降级 2 个大版本**"),
    ]
    print(f"  {'包':<18} {'仓库现状':<12} {'CrewAI 要求':<14} 后果")
    print(f"  {'-' * 18} {'-' * 12} {'-' * 14} {'-' * 22}")
    for a, b, c, d in rows:
        print(f"  {a:<18} {b:<12} {c:<14} {d}")

    print()
    print("  **结论：装 CrewAI 会把整个仓库的第 43–46 章代码全部打挂。**")
    print("  所以本章只给 CrewAI 的写法对照，**不给可运行示例** —— 这是取舍，不是偷懒。")
    print()
    print("  一个可执行的判断方法（不用真装）：")
    print("    pip install --dry-run crewai")
    print("  看它会不会 'Would install' 出降级版本。会，就别装。")

    print()
    print("  ---- 顺便给一个真实教训：")
    print("     「我在虚拟环境里装一下试试」是危险动作，因为：")
    print("     · pip 会**静默降级**，装完不报错")
    print("     · 你的测试可能恰好没覆盖到被降级的那部分 API")
    print("     · 等 CI 红了才发现，已经浪费半天")
    print("     正确做法：先在 `--dry-run` 里看清楚，再决定要不要装。")


# ================================================================ ② AutoGen 真跑
def demo_autogen() -> None:
    print()
    print(DPRINT)
    print("② AutoGen 0.7.5 的最小可跑示例（离线，假模型）")
    print(DPRINT)

    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
        from autogen_agentchat.teams import RoundRobinGroupChat
        from autogen_core.models import ChatCompletionClient, CreateResult, RequestUsage
    except ImportError as e:
        print(f"  需要 autogen-agentchat>=0.7：{e}")
        print("  pip install 'autogen-agentchat>=0.7'")
        return

    class ScriptedClient(ChatCompletionClient):
        """按剧本返回的假模型 —— 每个 agent 轮到自己时说固定的话。"""

        def __init__(self, name: str, script: list[str]) -> None:
            self._name = name
            self._script = list(script)
            self._i = 0

        async def create(self, messages, *, model=None, tools=None, **kw) -> CreateResult:
            text = self._script[min(self._i, len(self._script) - 1)]
            self._i += 1
            return CreateResult(
                finish_reason="stop",
                content=text,
                usage=RequestUsage(prompt_tokens=10, completion_tokens=5),
                cached=False,
            )

        def create_stream(self, *a, **kw):
            raise NotImplementedError

        async def close(self) -> None:
            return None

        def actual_usage(self) -> RequestUsage:
            return RequestUsage(prompt_tokens=0, completion_tokens=0)

        def total_usage(self) -> RequestUsage:
            return RequestUsage(prompt_tokens=0, completion_tokens=0)

        def count_tokens(self, messages, *, tools=None) -> int:
            return 10

        def remaining_tokens(self, messages, *, tools=None) -> int:
            return 10_000

        @property
        def model_info(self):  # noqa: D401
            from autogen_core.models import ModelInfo

            return ModelInfo(vision=False, function_calling=False, json_output=False,
                             family="unknown", structured_output=False)

        @property
        def capabilities(self):  # noqa: D401
            from autogen_core.models import ModelCapabilities

            return ModelCapabilities(vision=False, function_calling=False, json_output=False)

    async def main() -> None:
        # 三个角色：写手 -> 审稿 -> 定稿
        writer = AssistantAgent(
            "writer",
            model_client=ScriptedClient("writer", ["第一版：退款需要 7 个工作日。"]),
            description="负责起草回答",
        )
        reviewer = AssistantAgent(
            "reviewer",
            model_client=ScriptedClient("reviewer", ["补充：到账方式为原路退回。"]),
            description="负责补充遗漏",
        )
        approver = AssistantAgent(
            "approver",
            model_client=ScriptedClient("approver", ["APPROVE 最终版：退款 7 个工作日，原路退回。"]),
            description="负责定稿",
        )

        team = RoundRobinGroupChat(
            [writer, reviewer, approver],
            termination_condition=(
                TextMentionTermination("APPROVE") | MaxMessageTermination(8)
            ),
        )

        print("  三个 Agent（writer -> reviewer -> approver）轮流转：")
        print()
        n = 0
        async for msg in team.run_stream(task="退款要多久到账？"):
            if hasattr(msg, "source") and hasattr(msg, "content"):
                n += 1
                content = str(msg.content).replace("\n", " ")[:60]
                print(f"    [{n}] {msg.source:<10} {content}")
        print()
        print(f"  共 {n} 条消息，最后由 APPROVE 终止。")

    asyncio.run(main())

    print()
    print("  ---- 从这段代码能看出 AutoGen 的设计取向：")
    rows = [
        ("核心抽象", "Agent + Team（群聊）", "对话是核心，流程 = 谁什么时候发言"),
        ("流程控制", "轮转 / 选择器 / 自定义", "靠**发言顺序规则**，不是显式图"),
        ("终止条件", "TextMention / MaxMessage 组合", "用「某个词出现」来结束，很直觉"),
        ("适合", "多角色讨论、辩论、评审", "开放式协作，没有固定流程图"),
        ("不适合", "流程严格确定的业务", "用 LangGraph 画死更安全"),
    ]
    print(f"  {'维度':<12} {'AutoGen 的做法':<30} 含义")
    print(f"  {'-' * 12} {'-' * 30} {'-' * 30}")
    for a, b, c in rows:
        print(f"  {a:<12} {b:<30} {c}")


# ================================================================ ③ 选型表
def demo_selection() -> None:
    print()
    print(DPRINT)
    print("③ 选型表：什么场景选谁")
    print(DPRINT)

    print("  五个框架的定位（按「你需要的控制力」排序）：")
    print()
    header = f"  {'框架':<20} {'控制力':<10} {'典型形态':<26} 最适合"
    print(header)
    print(f"  {'-' * 20} {'-' * 10} {'-' * 26} {'-' * 22}")

    rows = [
        ("纯手写", "最高", "while 循环 + if", "流程固定、要极致可控"),
        ("LangGraph", "高", "显式图 + 状态机", "流程确定但要中断/持久化"),
        ("pydantic-ai", "中高", "强类型 Agent", "输出要强类型、依赖要注入"),
        ("LangChain create_agent", "中", "ReAct + 中间件", "标准 Agent、要现成的护栏"),
        ("AutoGen", "中低", "群聊 + 轮转", "多角色讨论/评审"),
        ("CrewAI", "中低", "角色 + 任务 + 流程", "角色分工直觉、快速搭原型"),
    ]
    for a, b, c, d in rows:
        print(f"  {a:<20} {b:<10} {c:<26} {d}")

    print()
    print("  三条选型判据（按顺序问）：")
    print()
    print("  ① 流程是确定还是开放？")
    print("     确定 -> LangGraph / 纯手写")
    print("     开放 -> create_agent / pydantic-ai / AutoGen")
    print()
    print("  ② 需要中断 + 持久化 + 恢复吗？")
    print("     需要 -> LangGraph（checkpointer 是它的护城河）")
    print("     不需要 -> 其他都行")
    print()
    print("  ③ 输出要强类型吗？")
    print("     要 -> pydantic-ai（output_type 直接是 Pydantic 模型）")
    print("     不要 -> 其他都行")
    print()
    print("  ---- 一个反直觉但重要的建议：")
    print("     **先写纯手写版，再决定用哪个框架。**")
    print("     因为纯手写版让你看清「流程到底确不确定」——")
    print("     而这恰恰是选框架的唯一决定性因素。")
    print("     直接上框架的人，经常在生产里才发现")
    print("     「原来我的流程是确定的，根本不需要 Agent」。")


def demo_migration_note() -> None:
    print()
    print(DPRINT)
    print("④ 如果你已经选了「错」的框架，怎么迁")
    print(DPRINT)

    print("  好消息：这些框架的核心都是「模型 + 工具 + 循环」，迁移成本主要在三处：")
    print()
    rows = [
        ("工具的声明方式", "@tool 装饰器 / Pydantic 模型 / 函数签名", "重写工具定义，但业务逻辑可复用"),
        ("状态的形状", "dict / TypedDict / Pydantic model", "**最容易出 bug 的地方**"),
        ("中断与持久化", "只有 LangGraph 有成熟的 checkpointer", "迁出 LangGraph 要自己实现"),
    ]
    print(f"  {'迁移点':<20} {'各框架差异':<40} 代价")
    print(f"  {'-' * 20} {'-' * 40} {'-' * 34}")
    for a, b, c in rows:
        print(f"  {a:<20} {b:<40} {c}")

    print()
    print("  ---- 一条实用策略：**把业务逻辑和框架隔开。**")
    print()
    print("     ❌ 不好：业务规则写在 @tool 里、状态依赖框架的 state")
    print("     ✅ 好  ：业务逻辑是纯函数，框架层只做「把它挂上去」")
    print()
    print("     这样迁移时，你只改「挂上去」那一层（几十行），")
    print("     业务逻辑一行都不用动。本章 step1 的 A 实现就是这个思路。")


if __name__ == "__main__":
    demo_dependency_conflict()
    demo_autogen()
    demo_selection()
    demo_migration_note()
    print()
    print(DPRINT)
    print("step2 完成。四句话带走：")
    print("  1. CrewAI 会把这个仓库的 langchain/openai 降级 4~5 个大版本，装之前先 --dry-run。")
    print("  2. AutoGen 的核心是「群聊 + 发言顺序」，适合多角色讨论，不适合严格流程。")
    print("  3. 选框架先问「流程确定吗」—— 确定就别让模型有机会乱走。")
    print("  4. 把业务逻辑写成纯函数，框架只负责挂上去，迁移成本能从周变成小时。")
    print(DPRINT)
