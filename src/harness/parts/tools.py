"""工具：签名 → JSON Schema 推导、装饰器、注册表（SPEC M3.5 / M3.5.1）。

工具是唯一有副作用的执行原语；参数校验在 invoke 之前完成。

**推导规则（定死，不许猜）**：无标注一律报 `ConfigError`，不默认 `string`——
否则 `amount: int` 会被当成字符串传给下游，错误发生在最远的地方。
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import json
import types
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Union, get_args, get_origin, get_type_hints

from harness.contracts.errors import ConfigError, ToolError
from harness.contracts.status import SideEffect
from harness.contracts.types import ToolCall, ToolContext, ToolResult, ToolSpec

_PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return True, args[0]
    return False, annotation


def schema_for_type(annotation: Any, *, name: str = "") -> dict[str, Any]:
    """把 Python 标注翻译成 JSON Schema 片段。"""
    if annotation in _PRIMITIVES:
        return {"type": _PRIMITIVES[annotation]}

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        return {"enum": list(args)}

    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {"enum": [member.value for member in annotation]}

    if origin in (list, set, frozenset, tuple):
        item = args[0] if args else None
        if item is None or item is Ellipsis:
            return {"type": "array"}
        return {"type": "array", "items": schema_for_type(item, name=name)}

    if origin is dict:
        value = args[1] if len(args) > 1 else None
        out: dict[str, Any] = {"type": "object"}
        if value is not None:
            out["additionalProperties"] = schema_for_type(value, name=name)
        return out

    if origin in (Union, types.UnionType):        # 多分支联合：只声明类型不猜
        return {"anyOf": [schema_for_type(a, name=name) for a in args]}

    if dataclasses.is_dataclass(annotation):
        # 嵌套 dataclass 的字段类型可能是字符串（`from __future__ import annotations`）
        resolved = get_type_hints(annotation, include_extras=False)
        props: dict[str, Any] = {}
        required: list[str] = []
        for f in dataclasses.fields(annotation):
            ftype = resolved.get(f.name, f.type)
            optional, inner = _is_optional(ftype)
            props[f.name] = schema_for_type(inner, name=f.name)
            if not optional and f.default is dataclasses.MISSING:
                required.append(f.name)
        return {"type": "object", "properties": props, "required": required,
                "additionalProperties": False}

    if annotation is Any:
        raise ConfigError(f"参数 {name} 标注为 Any，无法推导 schema；请给出具体类型")

    raise ConfigError(f"参数 {name} 的类型不受支持：{annotation!r}")


def _docstring_parts(func: Callable[..., Any]) -> tuple[str, dict[str, str]]:
    """拆 docstring：首段是工具描述，`Args:` 段是逐参数说明。"""
    raw = inspect.getdoc(func) or ""
    description_lines: list[str] = []
    args: dict[str, str] = {}
    in_args = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(("args:", "arguments:", "参数:")):
            in_args = True
            continue
        if in_args:
            if not stripped:
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                args[key.strip()] = value.strip()
            continue
        if stripped and not description_lines:
            description_lines.append(stripped)
    return (description_lines[0] if description_lines else ""), args


def derive_schema(func: Callable[..., Any]) -> tuple[dict[str, Any], str, dict[str, str]]:
    """返回 (parameters, description, param_descriptions)。"""
    signature = inspect.signature(func)
    hints = get_type_hints(func, include_extras=False)
    description, arg_docs = _docstring_parts(func)

    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:   # **kwargs → 开放对象
            properties[name] = {"type": "object", "additionalProperties": True}
            continue
        if hints.get(name) is ToolContext:                # 能力注入参数，不进 schema
            continue
        if name not in hints:
            raise ConfigError(f"参数 {name} 缺少类型标注（不默认 string）")
        optional, inner = _is_optional(hints[name])
        piece = schema_for_type(inner, name=name)
        if optional:
            piece = {**piece, "nullable": True}
        if name in arg_docs:
            piece["description"] = arg_docs[name]
        properties[name] = piece
        if not optional and param.default is inspect.Parameter.empty:
            required.append(name)

    has_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
    )
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": has_kwargs,
    }
    return schema, description, arg_docs


@dataclass
class FunctionTool:
    """同时满足既有形状（name/description/parameters/invoke），也带 `spec` 元数据。"""

    spec: ToolSpec
    func: Callable[..., Any]
    is_async: bool = False

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self.spec.parameters

    @property
    def _takes_ctx(self) -> bool:
        """工具的首参若标注为 `ToolContext`，调用时注入能力。"""
        try:
            hints = get_type_hints(self.func, include_extras=False)
        except Exception:  # noqa: BLE001 - 推导失败时按无 ctx 处理
            return False
        return any(h is ToolContext for h in hints.values())

    async def invoke(self, args: dict[str, Any], ctx: ToolContext | None = None) -> str:
        try:
            if self._takes_ctx and ctx is not None:
                value = self.func(**{**args, "ctx": ctx})
            else:
                value = self.func(**args)
            if inspect.isawaitable(value):
                value = await value
        except TypeError as exc:
            raise ToolError(f"{self.name}: 参数不匹配：{exc}") from exc
        except PermissionError:
            # 路径越界 / 权限拒绝：原样抛出，交给 Classify 归为 REFUSED。
            # 包成 ToolError 会被当作"可重试的工具失败"回灌给模型，错误归因就丢了。
            raise
        except Exception as exc:  # noqa: BLE001 - 工具边界统一包装
            raise ToolError(f"{self.name}: {exc}") from exc
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    async def call(self, args: dict[str, Any], ctx: ToolContext | None = None) -> ToolResult:
        """返回结构化结果，供 Wrap 段截断/脱敏。"""
        out = await self.invoke(args, ctx)
        return ToolResult(step_id="", tool=self.name, ok=True, output=out)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.spec.name,
                "description": self.spec.description,
                "parameters": self.spec.parameters,
            },
        }


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    side_effects: str | SideEffect = SideEffect.PURE,
    scopes: tuple[str, ...] | set[str] = (),
    timeout_s: float | None = None,
    idempotent: bool = False,
    max_output_bytes: int = 32_000,
    needs_approval: bool = False,
    sandbox: bool = False,
):
    """把一个函数变成 `FunctionTool`；支持 `@tool` 与 `@tool(...)`。"""

    def wrap(fn: Callable[..., Any]) -> FunctionTool:
        parameters, doc, _ = derive_schema(fn)
        spec = ToolSpec(
            name=name or fn.__name__,
            description=description or doc or (inspect.getdoc(fn) or "").strip(),
            parameters=parameters,
            side_effects=SideEffect(side_effects),
            scopes=frozenset(scopes),
            timeout_s=timeout_s,
            idempotent=idempotent,
            max_output_bytes=max_output_bytes,
            needs_approval=needs_approval,
            sandbox=sandbox,
        )
        return FunctionTool(spec=spec, func=fn, is_async=inspect.iscoroutinefunction(fn))

    if func is None:
        return wrap
    return wrap(func)


@dataclass
class ToolRegistry:
    tools: dict[str, FunctionTool] = field(default_factory=dict)

    def add(self, *tools: Any) -> "ToolRegistry":
        for item in tools:
            item = as_tool(item)
            if item.name in self.tools:
                raise ToolError(f"工具重名：{item.name}")
            self.tools[item.name] = item
        return self

    def get(self, name: str) -> FunctionTool:
        if name not in self.tools:
            raise ToolError(f"未知工具：{name}")
        return self.tools[name]

    def schemas(self, *, allow: frozenset[str] | None = None) -> list[dict[str, Any]]:
        items = self.tools.values()
        if allow is not None:                     # skill 的 allowed_tools 在这里生效
            items = [t for t in items if t.name in allow]
        return [item.schema() for item in items]

    def specs(self, *, allow: frozenset[str] | None = None) -> list[ToolSpec]:
        items = self.tools.values()
        if allow is not None:
            items = [t for t in items if t.name in allow]
        return [item.spec for item in items]

    def names(self) -> list[str]:
        return sorted(self.tools)

    async def invoke(self, call: ToolCall, ctx: ToolContext | None = None) -> str:
        return await self.get(call.name).invoke(call.args, ctx)


def as_tool(value: Any) -> FunctionTool:
    if isinstance(value, FunctionTool):
        return value
    if callable(value):
        return tool(value)
    raise ToolError(f"无法作为工具：{value!r}")


__all__ = [
    "FunctionTool",
    "ToolRegistry",
    "as_tool",
    "tool",
    "derive_schema",
    "schema_for_type",
]
