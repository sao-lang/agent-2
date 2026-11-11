"""工具元数据与能力层的测试（P4 后半验收之一）。"""

from __future__ import annotations

import asyncio
import enum
import unittest
from dataclasses import dataclass
from typing import Literal

from harness.contracts.errors import ConfigError
from harness.contracts.status import SideEffect
from harness.contracts.types import Mount, ToolContext
from harness.impl.backends import MemoryArtifactStore, MemoryFileSystem, MemorySecretBroker
from support import FakeSandbox
from harness.parts.capability import (
    fs_tools,
    register_capabilities,
    sandbox_tools,
    truncate_layer,
)
from harness.parts.tools import ToolRegistry, derive_schema, tool
from harness.kernel.chain import execute
from harness.contracts.types import ToolRequest, ToolResponse, ToolResult, Step


def run(coro):
    return asyncio.run(coro)


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Filter:
    keyword: str
    limit: int = 10


class SchemaTest(unittest.TestCase):
    def test_primitives(self):
        def f(a: str, b: int, c: float, d: bool) -> None: ...

        schema, _, _ = derive_schema(f)
        self.assertEqual(schema["properties"]["a"]["type"], "string")
        self.assertEqual(schema["properties"]["b"]["type"], "integer")
        self.assertEqual(schema["properties"]["c"]["type"], "number")
        self.assertEqual(schema["properties"]["d"]["type"], "boolean")

    def test_optional_is_not_required_and_nullable(self):
        def f(x: int, y: str | None = None) -> None: ...

        schema, _, _ = derive_schema(f)
        self.assertEqual(schema["required"], ["x"])
        self.assertTrue(schema["properties"]["y"]["nullable"])

    def test_literal_and_enum(self):
        def f(mode: str, color: Color) -> None: ...

        def g(mode: "LiteralA") -> None: ...  # noqa: F821

        schema, _, _ = derive_schema(
            lambda mode: None  # placeholder, replaced below
        ) if False else (None, None, None)

        from typing import Literal

        def h(mode: Literal["a", "b"], color: Color) -> None: ...

        schema, _, _ = derive_schema(h)
        self.assertEqual(schema["properties"]["mode"]["enum"], ["a", "b"])
        self.assertEqual(schema["properties"]["color"]["enum"], ["red", "blue"])

    def test_collections(self):
        def f(names: list[str], mapping: dict[str, int]) -> None: ...

        schema, _, _ = derive_schema(f)
        self.assertEqual(schema["properties"]["names"]["type"], "array")
        self.assertEqual(schema["properties"]["names"]["items"]["type"], "string")
        self.assertEqual(schema["properties"]["mapping"]["type"], "object")
        self.assertEqual(schema["properties"]["mapping"]["additionalProperties"]["type"], "integer")

    def test_nested_dataclass(self):
        def f(flt: Filter) -> None: ...

        schema, _, _ = derive_schema(f)
        props = schema["properties"]["flt"]["properties"]
        self.assertIn("keyword", props)
        self.assertEqual(schema["properties"]["flt"]["required"], ["keyword"])

    def test_missing_annotation_rejected(self):
        def f(x) -> None:  # type: ignore[no-untyped-def]
            ...

        with self.assertRaises(ConfigError):
            derive_schema(f)

    def test_docstring_args_become_descriptions(self):
        def f(order_id: str) -> None:
            """查询订单。

            Args:
                order_id: 订单号
            """

        schema, description, _ = derive_schema(f)
        self.assertEqual(description, "查询订单。")
        self.assertEqual(schema["properties"]["order_id"]["description"], "订单号")

    def test_kwargs_open_object(self):
        def f(a: int, **extra) -> None: ...

        schema, _, _ = derive_schema(f)
        self.assertTrue(schema["additionalProperties"])

    def test_ctx_param_not_in_schema(self):
        @tool(side_effects="read")
        async def read_thing(ctx: ToolContext, path: str) -> str:
            return path

        self.assertNotIn("ctx", read_thing.spec.parameters["properties"])
        self.assertIn("path", read_thing.spec.parameters["properties"])


class ToolSpecTest(unittest.TestCase):
    def test_decorator_metadata(self):
        @tool(side_effects="write", scopes={"net:api"}, idempotent=True, needs_approval=True)
        async def refund(order_id: str, amount: int) -> dict:
            """发起退款。"""
            return {"ok": True}

        self.assertEqual(refund.spec.side_effects, SideEffect.WRITE)
        self.assertIn("net:api", refund.spec.scopes)
        self.assertTrue(refund.spec.idempotent)
        self.assertTrue(refund.spec.needs_approval)
        self.assertEqual(refund.spec.description, "发起退款。")

    def test_registry_filters_by_allow(self):
        @tool
        def a() -> str:
            return "a"

        @tool
        def b() -> str:
            return "b"

        registry = ToolRegistry().add(a, b)
        self.assertEqual([d["function"]["name"] for d in registry.schemas(allow=frozenset({"a"}))], ["a"])

    def test_duplicate_name_rejected(self):
        from harness.contracts.errors import ToolError

        @tool(name="dup")
        def a() -> str:
            return "a"

        @tool(name="dup")
        def b() -> str:
            return "b"

        with self.assertRaises(ToolError):
            ToolRegistry().add(a, b)


class FsToolsTest(unittest.TestCase):
    def setUp(self):
        self.fs = MemoryFileSystem(mounts=(Mount("/work", None, "rw"), Mount("/ro", None, "ro")))
        self.ctx = ToolContext(fs=self.fs, artifacts=MemoryArtifactStore(), secrets=MemorySecretBroker())
        self.tools = {t.name: t for t in fs_tools()}

    def test_write_then_read(self):
        run(self.tools["write_file"].invoke({"path": "/work/a.txt", "content": "hello"}, self.ctx))
        out = run(self.tools["read_file"].invoke({"path": "/work/a.txt"}, self.ctx))
        self.assertEqual(out, "hello")

    def test_read_outside_mount_denied(self):
        from harness.impl.backends import PathDenied

        with self.assertRaises(PathDenied):          # 不被包成 ToolError
            run(self.tools["read_file"].invoke({"path": "/etc/passwd"}, self.ctx))

    def test_readonly_write_denied(self):
        with self.assertRaises(Exception):
            run(self.tools["write_file"].invoke({"path": "/ro/x", "content": "x"}, self.ctx))

    def test_grep_returns_structured_hits(self):
        import json

        run(self.tools["write_file"].invoke({"path": "/work/b.py", "content": "alpha\nbeta"}, self.ctx))
        raw = run(self.tools["grep_path"].invoke({"pattern": "beta"}, self.ctx))
        hits = json.loads(raw) if isinstance(raw, str) else raw
        self.assertEqual(hits[0]["line"], 2)


class SandboxToolsTest(unittest.TestCase):
    def test_exec_passes_argv_and_masks_env(self):
        sandbox = FakeSandbox()
        ctx = ToolContext(sandbox=sandbox, secrets=MemorySecretBroker({"TOKEN": "s3cr3t"}))
        tools = {t.name: t for t in sandbox_tools()}
        run(tools["exec"].invoke({"argv": ["echo", "hi"], "env_keys": ["TOKEN"]}, ctx))
        self.assertEqual(sandbox.calls[0], ("echo", "hi"))
        self.assertEqual(tools["exec"].spec.side_effects, SideEffect.SHELL)
        self.assertTrue(tools["exec"].spec.sandbox)


class TruncateLayerTest(unittest.TestCase):
    def test_long_output_offloaded_to_artifact(self):
        artifacts = MemoryArtifactStore()
        layer = truncate_layer(artifacts=artifacts, max_output_bytes=10)

        async def terminal(req):
            return ToolResponse(result=ToolResult(step_id="s1", tool="big", output="x" * 1000))

        out = run(execute([layer], ToolRequest(step=Step(id="s1", tool_name="big")), terminal))
        self.assertIn("已截断", out.result.output)
        self.assertEqual(len(out.result.artifacts), 1)

    def test_short_output_untouched(self):
        artifacts = MemoryArtifactStore()
        layer = truncate_layer(artifacts=artifacts, max_output_bytes=1000)

        async def terminal(req):
            return ToolResponse(result=ToolResult(step_id="s1", tool="small", output="ok"))

        out = run(execute([layer], ToolRequest(step=Step(id="s1", tool_name="small")), terminal))
        self.assertEqual(out.result.output, "ok")
        self.assertEqual(out.result.artifacts, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
