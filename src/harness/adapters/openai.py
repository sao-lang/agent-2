"""OpenAI 适配器（SPEC M12.2 / M15.7）。

只做三件事：消息映射、工具映射、usage 归一化成 `{input, output, total}`。
没装 `openai` 时给出安装提示，不静默降级。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from harness.contracts.errors import ConfigError
from harness.contracts.types import ModelDelta, ModelReply, ToolCall


def _require_openai() -> Any:
    try:
        import openai  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise ConfigError(
            "openai 适配器需要安装依赖：pip install agent-harness[openai]"
        ) from exc
    return openai


def normalize_usage(raw: Any) -> dict[str, int]:
    """归一化 usage：上层记账与预算只认统一口径。"""
    if raw is None:
        return {"input": 0, "output": 0, "total": 0}
    data = raw if isinstance(raw, dict) else getattr(raw, "model_dump", lambda: {})()
    prompt = int(data.get("prompt_tokens", data.get("input_tokens", 0)) or 0)
    completion = int(data.get("completion_tokens", data.get("output_tokens", 0)) or 0)
    total = int(data.get("total_tokens", prompt + completion) or 0)
    return {"input": prompt, "output": completion, "total": total or prompt + completion}


def to_reply(response: Any) -> ModelReply:
    """把 OpenAI 的 chat.completion 映射成契约类型。"""
    choice = (getattr(response, "choices", None) or [None])[0]
    message = getattr(choice, "message", None)
    content = str(getattr(message, "content", "") or "")
    calls: list[ToolCall] = []
    function = getattr(message, "function_call", None)
    if function is not None:                       # 旧式 function_call
        calls.append(ToolCall(name=function.name, args=_json_loads(function.arguments)))
    for call in getattr(message, "tool_calls", None) or []:
        calls.append(
            ToolCall(
                id=str(getattr(call, "id", "") or ""),
                name=call.function.name,
                args=_json_loads(call.function.arguments),
            )
        )
    return ModelReply(
        content=content,
        tool_calls=calls,
        usage=normalize_usage(getattr(response, "usage", None)),
        finish_reason=str(getattr(choice, "finish_reason", "stop") or "stop"),
    )


def _json_loads(raw: Any) -> dict[str, Any]:
    import json

    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class OpenAIModel:
    """实现 `Model` 协议：`complete` + `stream`。"""

    def __init__(self, name: str = "gpt-4.1", *, client: Any = None,
                 temperature: float = 0.0, **kwargs: Any) -> None:
        if client is None:
            openai = _require_openai()
            client = openai.AsyncOpenAI(**kwargs)
        self.name = name
        self.client = client
        self.temperature = temperature

    async def complete(self, messages, tools=None, *, response_format=None) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.name,
            "messages": list(messages),
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = list(tools)
        if response_format is not None and response_format.kind == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": response_format.schema or {}},
            }
        response = await self.client.chat.completions.create(**payload)
        return to_reply(response)

    async def stream(self, messages, tools=None) -> AsyncIterator[ModelDelta]:
        payload: dict[str, Any] = {
            "model": self.name,
            "messages": list(messages),
            "temperature": self.temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = list(tools)
        async for chunk in await self.client.chat.completions.create(**payload):
            choice = (getattr(chunk, "choices", None) or [None])[0]
            delta = getattr(choice, "delta", None)
            text = str(getattr(delta, "content", "") or "")
            if text:
                yield ModelDelta(kind="text", text=text)
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield ModelDelta(kind="usage", usage=normalize_usage(usage))


__all__ = ["OpenAIModel", "normalize_usage", "to_reply"]


# （SUPPLEMENT B2）：适配器自注册（同 fp.frontends 的手法）。
# adapters → assembly 是合法依赖方向；registry 的 "openai" 槽位默认是
# 占位工厂，import 本模块后即被真工厂覆盖——用户接线只需一行 import。
def _registry_factory(arg: str = "", **kwargs: Any) -> Any:
    return OpenAIModel(arg or "gpt-4.1", **kwargs)


try:
    from harness.assembly import registry as _registry

    _registry.MODELS["openai"] = _registry_factory
except Exception:  # noqa: BLE001 - 独立使用适配器时注册表可选
    pass
