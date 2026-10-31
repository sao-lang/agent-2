"""工具：协议、装饰器、注册表。

工具是唯一有副作用的执行原语；参数校验在 invoke 之前完成。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import ToolCall
from .errors import ToolError

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _schema_for(func: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(func)
    hints = inspect.get_annotations(func, eval_str=True)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if name in ("self", "cls") or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation = hints.get(name, str)
        properties[name] = {
            "type": _TYPE_MAP.get(annotation, "string"),
            "description": "",
        }
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


@dataclass
class FunctionTool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    is_async: bool = False

    async def invoke(self, args: dict[str, Any]) -> str:
        try:
            value = self.func(**args)
            if inspect.isawaitable(value):
                value = await value
        except TypeError as exc:
            raise ToolError(f"{self.name}: 参数不匹配：{exc}") from exc
        except Exception as exc:  # noqa: BLE001 - 工具边界统一包装
            raise ToolError(f"{self.name}: {exc}") from exc
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def tool(func: Callable[..., Any] | None = None, *,
         name: str | None = None,
         description: str | None = None):
    """把一个函数变成 FunctionTool；支持 @tool 与 @tool(name=...)。"""

    def wrap(fn: Callable[..., Any]) -> FunctionTool:
        return FunctionTool(
            name=name or fn.__name__,
            description=description or (inspect.getdoc(fn) or "").strip(),
            parameters=_schema_for(fn),
            func=fn,
            is_async=inspect.iscoroutinefunction(fn),
        )

    if func is None:
        return wrap
    return wrap(func)


@dataclass
class ToolRegistry:
    tools: dict[str, FunctionTool] = field(default_factory=dict)

    def add(self, *tools: FunctionTool) -> "ToolRegistry":
        for item in tools:
            if item.name in self.tools:
                raise ToolError(f"工具重名：{item.name}")
            self.tools[item.name] = item
        return self

    def get(self, name: str) -> FunctionTool:
        if name not in self.tools:
            raise ToolError(f"未知工具：{name}")
        return self.tools[name]

    def schemas(self) -> list[dict[str, Any]]:
        return [item.schema() for item in self.tools.values()]

    def names(self) -> list[str]:
        return sorted(self.tools)

    async def invoke(self, call: ToolCall) -> str:
        return await self.get(call.name).invoke(call.args)


def as_tool(value: FunctionTool | Callable[..., Any]) -> FunctionTool:
    if isinstance(value, FunctionTool):
        return value
    return tool(value)
