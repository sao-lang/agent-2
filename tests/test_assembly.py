"""装配层测试（P6 验收）：spec 解析、八条校验、预设、换存储介质。"""

from __future__ import annotations

import asyncio
import unittest

from harness.assembly import (
    BackendSpec,
    HarnessConfig,
    StoreSpec,
    build_harness,
    parse_spec,
    resolve,
    validate,
)
from harness.assembly.fpresets import minimal, production
from harness.contracts.errors import ConfigError
from harness.contracts.types import Budget, Goal, LayerSpec
from harness.impl.stores import MemoryCheckpointStore
from harness.fp import describe, react


def run(coro):
    return asyncio.run(coro)


class ParseSpecTest(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(parse_spec("memory", kind="store"), ("memory", "", {}))

    def test_name_with_arg(self):
        self.assertEqual(parse_spec("sqlite:runs.db", kind="store"), ("sqlite", "runs.db", {}))

    def test_dict_form(self):
        name, arg, extra = parse_spec({"kind": "postgres", "dsn": "pg://x", "pool": 5},
                                      kind="store")
        self.assertEqual(name, "postgres")
        self.assertEqual(arg, "pg://x")
        self.assertEqual(extra, {"pool": 5})

    def test_bad_name_rejected(self):
        with self.assertRaises(ConfigError):
            parse_spec("Memory", kind="store")

    def test_empty_rejected(self):
        with self.assertRaises(ConfigError):
            parse_spec("", kind="store")

    def test_unknown_name_lists_available(self):
        with self.assertRaises(ConfigError) as ctx:
            resolve("store", "nosuch", {"memory": lambda **kw: None})
        self.assertIn("可用", str(ctx.exception))


class ValidationTest(unittest.TestCase):
    def test_ok(self):
        validate(HarnessConfig())

    def test_unknown_guardrail(self):
        with self.assertRaises(ConfigError):
            validate(HarnessConfig(guardrails=("nope",)))

    def test_duplicate_tool_names(self):
        from harness.parts.tools import tool

        @tool(name="dup")
        def a() -> str:
            return "a"

        @tool(name="dup")
        def b() -> str:
            return "b"

        with self.assertRaises(ConfigError):
            validate(HarnessConfig(tools=(a, b)))

    def test_unknown_layer(self):
        with self.assertRaises(ConfigError):
            validate(HarnessConfig(layers=(LayerSpec(name="nope"),)))

    def test_local_fs_requires_path(self):
        with self.assertRaises(ConfigError):
            validate(HarnessConfig(backends=BackendSpec(fs="local")))

    def test_non_positive_budget(self):
        with self.assertRaises(ConfigError):
            validate(HarnessConfig(budget=Budget(tokens=0, calls=1)))

    def test_negative_depth(self):
        with self.assertRaises(ConfigError):
            validate(HarnessConfig(max_depth=-1))

    def test_adapter_missing_gives_install_hint(self):
        with self.assertRaises(ConfigError) as ctx:
            validate(HarnessConfig(stores=StoreSpec(memory="postgres:pg://x")))
        self.assertIn("pip install", str(ctx.exception))


class BuildTest(unittest.TestCase):
    def test_builds_harness_with_guardrails(self):
        config = HarnessConfig(guardrails=("injection", "pii"))
        harness = build_harness(config)
        self.assertEqual(len(harness.guardrails), 2)
        self.assertIsNone(harness.model)   # model=None 合法：不注入模型的程序

    def test_store_slot_resolves_to_instance(self):
        harness = build_harness(HarnessConfig(stores=StoreSpec(durability="memory")))
        self.assertIsInstance(harness.stores["durability"], MemoryCheckpointStore)

    def test_default_backends_present(self):
        harness = build_harness(HarnessConfig())
        for slot in ("fs", "sandbox", "artifacts", "secrets", "index", "queue",
                     "approval", "clock"):
            self.assertIn(slot, harness.backends)

    def test_preset_production_has_three_guardrails(self):
        config = production()
        self.assertEqual(len(config.guardrails), 3)
        build_harness(config)                       # 校验通过


class SwapStoreTest(unittest.TestCase):
    """最初的问题：换存储介质是否容易？——这里给出可执行答案。"""

    def test_swap_memory_store_keeps_program_untouched(self):
        program = react(max_steps=2) >> __import__(
            "harness.parts.middleware", fromlist=["taskboard_layer"]
        ).taskboard_layer()

        before = describe(program)

        config_a = HarnessConfig(stores=StoreSpec(memory="memory"))
        config_b = HarnessConfig(stores=StoreSpec(memory={"kind": "memory", "ttl_days": 30}))

        build_harness(config_a)
        build_harness(config_b)
        self.assertEqual(describe(program), before)   # 程序一个字没改


class PresetTest(unittest.TestCase):
    def test_minimal_preset_builds_small_budget(self):
        config = minimal()
        self.assertLessEqual(config.budget.tokens, 10_000)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
