"""结构化输出闭环（SUPPLEMENT A5 / PROPOSAL §9）。

`structured(model, schema)` 把任意 Model 包装成带校验-回灌-重试回路的
Model：输出经 JSON Schema 子集校验，失败把校验错误作为新的 user 消息
回灌重试（次数可配），通过后 `reply.parsed` 携带强类型对象。

**零第三方依赖**：内置校验器只覆盖 JSON Schema 的常用子集
（type/required/properties/enum/nullable/items/additionalProperties）。
需要 pydantic 级别强类型时，传入自定义 ``validator(text) -> (value, errors)``
即可（R2：只依赖契约，不引入依赖进内核）。

替换实验：换底层模型只改一行（包装器只依赖 Model 协议）。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from harness.contracts.errors import ContractError
from harness.contracts.types import Message, ModelReply, ResponseFormat

#: 自定义校验器签名：原始文本 → (解析后的对象, 错误列表)；错误为空即通过。
Validator = Callable[[str], tuple[Any, list[str]]]

_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def validate_json(text: str, schema: dict[str, Any]) -> tuple[Any, list[str]]:
    """内置校验器：解析 JSON 并按 schema 子集校验。返回 (值, 错误列表)。"""
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        return None, [f"invalid_json: {exc}"]
    errors: list[str] = []
    _check(value, schema, "$", errors)
    return value, errors


def _check(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        return
    expected = schema.get("type")
    nullable = bool(schema.get("nullable"))
    if expected is not None and expected in _TYPE_CHECKS:
        types = _TYPE_CHECKS[expected]
        # bool 是 int 的子类：integer 槽位要排除掉 bool
        if expected == "integer" and isinstance(value, bool):
            errors.append(f"{path}: expected integer, got boolean")
            return
        if value is not None and not isinstance(value, types):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return
        if value is None and not nullable and "null" not in (expected or ""):
            errors.append(f"{path}: null 不允许（schema 未声明 nullable）")
            return
    if "enum" in schema and value is not None and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} 不在枚举 {schema['enum']} 中")
        return
    if isinstance(value, dict):
        for key in schema.get("required", []) or []:
            if key not in value:
                errors.append(f"{path}: 缺少必填字段 {key!r}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                _check(value[key], sub, f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False and schema.get("properties"):
            extra = set(value) - set(schema["properties"])
            for key in sorted(extra):
                errors.append(f"{path}: 多余字段 {key!r}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors)


class StructuredModel:
    """实现 Model 协议的包装器：complete() 带校验-回灌-重试回路。

    stream() 直接透传——结构化校验只约束完整响应，流式增量无法校验。
    """

    def __init__(self, model: Any, schema: dict[str, Any], *,
                 validator: Validator | None = None,
                 max_retries: int = 2,
                 retry_instruction: str = "上一次输出未通过校验，请修正后重新输出完整 JSON。") -> None:
        self.model = model
        self.schema = schema
        # 内置校验器绑定 schema；自定义 validator 收 text 返回 (value, errors)
        self.validator = validator or (lambda text: validate_json(text, schema))
        self.max_retries = max_retries
        self.retry_instruction = retry_instruction

    async def complete(self, messages: list[dict[str, Any]] | None,
                       tools: list[dict[str, Any]] | None = None, *,
                       response_format: ResponseFormat | None = None) -> ModelReply:
        working = list(messages or ())
        last_errors: list[str] = []
        # 按签名显式分流（同 topology._call 的教训：不用 try/except TypeError 兜底，
        # 那会把模型内部抛出的 TypeError 伪装成签名不匹配）。
        import inspect

        accepts_rf = "response_format" in inspect.signature(
            self.model.complete).parameters
        for attempt in range(self.max_retries + 1):
            if accepts_rf:
                reply = await self.model.complete(
                    working, tools,
                    response_format=ResponseFormat(kind="json_schema", schema=self.schema))
            else:
                reply = await self.model.complete(working, tools)
            text = str(getattr(reply, "content", "") or "")
            value, errors = self.validator(text)
            if not errors:
                # 冻结 dataclass：用 object.__setattr__ 注入 parsed，不改契约形状
                object.__setattr__(reply, "parsed", value)
                return reply
            last_errors = errors
            working = list(working or []) + [
                {"role": "user",
                 "content": self.retry_instruction + "\n校验错误：\n- " + "\n- ".join(errors)},
            ]
        raise ContractError(
            f"结构化输出在 {self.max_retries + 1} 次尝试后仍未通过校验：{last_errors}")

    def stream(self, messages, tools=None):  # noqa: ANN201 - 与 Model 协议对齐
        return self.model.stream(messages, tools)


def structured(model: Any, schema: dict[str, Any], **kwargs: Any) -> StructuredModel:
    """便捷入口：structured(model, {"type":"object", …}) -> 带校验的 Model。"""
    return StructuredModel(model, schema, **kwargs)


__all__ = ["StructuredModel", "structured", "validate_json"]
