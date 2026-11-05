"""第 1 / 5 / 6 章：部件之间只传这几样数据。

这一层不认识订单、政策、运费，也不 import openai。换一套工具、换一个厂商、
换一种输出结构，本文件一行都不用改——这就是"换掉一个部件只消失一件事"的前提。

依赖方向：contracts 是最底层，不 import core 里的任何其它模块。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ValidationError

# 四个角色名，拼错任何一个都会让请求被服务端拒绝
ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL = "system", "user", "assistant", "tool"


# ── 第 1 章 A1：回灌三条格式 ─────────────────────────────────────────────────
def tool_msg(call_id: str, content: str) -> dict:
    """role=tool、tool_call_id 配对、content 是字符串，三条少一条服务端就 400。"""
    return {"role": ROLE_TOOL, "tool_call_id": call_id, "content": content}


# ── 第 5 章 A10：校验失败 → 回灌文案 ─────────────────────────────────────────
def to_feedback(exc: ValidationError) -> str:
    """把 pydantic 的错误结构转成模型能读懂的修复指令。

    回灌要带 loc / msg / input 三样；只说"格式错了"等于让模型重猜。
    文案里假设输出是 JSON 对象，这是第 5 章的通用约定，不是某个例子的字段。
    """
    lines = ["你上一次的输出不合法，请只输出 JSON 对象，字段如下："]
    for err in exc.errors():
        field_name = ".".join(str(p) for p in err["loc"])
        lines.append(f"- {field_name}: {err['msg']}（你给的是 {err['input']!r}）")
    return "\n".join(lines)


# ── 第 1 章 A2：一次响应在核心里的形状 ───────────────────────────────────────
@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: str          # JSON 字符串，不是对象；这是第 6 章最容易看错的一处


@dataclass(frozen=True)
class ToolCall:
    id: str                 # 只在一轮响应内唯一，不能当幂等键
    function: FunctionCall


@dataclass(frozen=True)
class Turn:
    """一次模型响应规整后的结果。核心只认 Turn，不认任何 SDK 对象。"""

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @classmethod
    def from_response(cls, resp: Any) -> Turn:
        """唯一一处认识 SDK 响应形状的地方：换框架只改这个函数（第 9 章对照台）。

        用 duck typing 读属性，所以这里不需要 import openai。
        """
        choice = resp.choices[0]
        usage = resp.usage
        calls = tuple(
            ToolCall(c.id, FunctionCall(c.function.name, c.function.arguments))
            for c in (choice.message.tool_calls or [])
        )
        return cls(
            content=choice.message.content,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            prompt_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
            completion_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        )

    def as_message(self) -> dict:
        """把 assistant 消息原样放回历史：产生 tool_calls 的那条必须在（第 6 章）。"""
        msg: dict[str, Any] = {"role": ROLE_ASSISTANT, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in self.tool_calls
            ]
        return msg


# ── 第 6 章 B1：工具的契约 ───────────────────────────────────────────────────
@dataclass(frozen=True)
class ToolSpec:
    """一个工具的声明要素 + 实现 + 参数模型，三样绑成一份。

    声明（给模型看）与实现（给调用方执行）仍是两件事，这里只是把它们配对。
    """

    name: str
    description: str
    args_model: type[BaseModel]
    impl: Callable[..., dict]

    def parse(self, arguments: str) -> BaseModel:
        """第 5 章 A10：字符串 → 模型实例，所有 Field 约束在这一行生效。"""
        return self.args_model.model_validate_json(arguments)

    def invoke(self, args: BaseModel) -> dict:
        """第 0 章：真正执行工具的就是下面这一行，模型从来没有执行过任何东西。"""
        return self.impl(**args.model_dump())          # ← 手册第 0 章要找的那一行


class ToolRegistry(Protocol):
    """工具从哪来，核心不关心（第 26 章换成本地 / MCP / Skill 只要实现这两个方法）。"""

    def declarations(self) -> list[dict[str, Any]]: ...

    def get(self, name: str) -> ToolSpec | None: ...


class ChatClient(Protocol):
    """第 1 章 A1：四个输入进去，一个 Turn 出来。"""

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float,
    ) -> Turn: ...


# ── 第 7 章 B2：装配契约（v0.14 的 build(cfg) 雏形）─────────────────────────
@dataclass(frozen=True)
class RunConfig:
    """一次运行的全部"由调用方决定"的东西，由装配层一次性填好。

    核心只读它，不在这里查文件顶部的常量，也不自己 new 依赖（第 52 章）。
    """

    model: str
    temperature: float
    max_steps: int
    max_prompt_tokens: int
    system_prompt: str
    question: str
    tools: list[dict[str, Any]]
    output_model: type[BaseModel]
    registry: ToolRegistry
    continuation_hint: str
    describe_answer: Callable[[Any], str]
    trim_limit: int = 200
    max_dup_in_row: int = 2


def json_dumps(obj: Any) -> str:
    """回灌内容必须是字符串；统一一处序列化，避免散落的 ensure_ascii 不一致。"""
    return json.dumps(obj, ensure_ascii=False)
