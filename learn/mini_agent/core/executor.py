"""第 5 / 6 章：一次 tool_calls 响应的执行管道。

原来这一整段塞在 run() 的一个分支里，五层嵌套的 if / try 互相咬着；
现在摊成 _run_one() 里一串顺序的小步骤，每一步只处理一个失败面：

    ① 请求指纹  ② 工具名  ③ 参数校验  ④ 执行  ⑤ 裁剪 + 结果指纹 + 回灌

每个失败面都"回灌一句人话"再 return，绝不静默丢弃——否则模型下一轮还会原样重发。
"""

from __future__ import annotations

# ── 第 6 章 B1：工具调用执行管道（第 5 章参数校验在第 ③ 步）──────────────────

from pydantic import ValidationError

from .contracts import ToolRegistry, ToolCall, json_dumps, to_feedback, tool_msg
from .guards import GuardSet
from .state import Reporter, RunState


class ToolExecutor:
    """把工具声明与实现配对的注册表，交给调用方执行（第 0 章：模型没有副作用能力）。"""

    def __init__(
        self,
        registry: ToolRegistry,
        guards: GuardSet,
        state: RunState,
        reporter: Reporter,
    ) -> None:
        self.registry = registry
        self.guards = guards
        self.state = state
        self.reporter = reporter

    def execute(self, calls: tuple[ToolCall, ...]) -> None:
        """一次响应可能带多个调用，必须逐个处理、按 id 配对（按位置配会静默错）。"""
        for call in calls:
            self.state.stats.tool_calls += 1
            self._run_one(call)

    def _run_one(self, call: ToolCall) -> None:
        name = call.function.name
        arguments = call.function.arguments

        # ① 请求指纹：同一个请求第二次出现就不执行，但要回灌一句让它知道
        if self.guards.is_duplicate_call(name, arguments):
            self._feedback(call, "重复调用：这次请求与之前完全相同，结果上面已经有了。")
            self.reporter.duplicate(self.state.step, name)
            return

        # ② 工具名校验：模型可能给出未声明的名字，直接下标会 KeyError 崩掉
        spec = self.registry.get(name)
        if spec is None:
            self._feedback(call, json_dumps({"error": f"未声明的工具：{name}，请只用已声明的工具"}))
            self.reporter.unknown_tool(self.state.step, name)
            return

        # ③ 参数校验：语法（是不是 JSON）+ 结构（字段/类型/取值）在这里一次性做
        try:
            args = spec.parse(arguments)
        except ValidationError as exc:
            self.state.stats.arg_errors += 1
            self._feedback(call, f"参数不合法，请按 schema 重发：{to_feedback(exc)}")
            self.reporter.arg_error(self.state.step, name)
            return

        # ④ 真正执行：唯一有副作用的时刻（impl(**args.model_dump()) 在 ToolSpec 里）
        try:
            result = spec.invoke(args)
        except KeyError as exc:
            # 业务错误转成 error 回灌，让模型自己决定换参数还是换策略，而不是让程序崩
            self._feedback(call, json_dumps({"error": str(exc)}))
            self.reporter.tool_error(self.state.step, name, exc)
            return

        # ⑤ 回灌前裁剪 → 结果指纹 → 追加 tool 消息
        payload = json_dumps(result)                       # 回灌内容必须是字符串
        trimmed, _ = self.guards.trim_content(payload)     # 裁的是"这一条"的 content
        if self.guards.is_repeated_result(trimmed, name):
            self.reporter.same_result(self.state.step, name)
        self._feedback(call, trimmed)
        self.reporter.tool_ok(self.state.step, name, payload)   # 打印用未裁剪的原文

    def _feedback(self, call: ToolCall, content: str) -> None:
        """回灌三条格式集中在 tool_msg() 一处，配对靠 call.id。"""
        self.state.messages.append(tool_msg(call.id, content))
