"""P8 验收：适配器映射与 CLI 脚手架。"""

from __future__ import annotations

import asyncio
import shutil
import unittest
from pathlib import Path

from harness.adapters.openai import OpenAIModel, normalize_usage, to_reply
from harness.cli import main, new_project
from harness.contracts.errors import ConfigError


def run(coro):
    return asyncio.run(coro)


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls
        self.function_call = None


class FakeChoice:
    def __init__(self, message, finish="stop"):
        self.message = message
        self.finish_reason = finish


class FakeResponse:
    def __init__(self, message, usage=None):
        self.choices = [FakeChoice(message)]
        self.usage = usage


class UsageTest(unittest.TestCase):
    def test_normalizes_prompt_completion(self):
        self.assertEqual(normalize_usage({"prompt_tokens": 10, "completion_tokens": 5}),
                         {"input": 10, "output": 5, "total": 15})

    def test_normalizes_none(self):
        self.assertEqual(normalize_usage(None), {"input": 0, "output": 0, "total": 0})

    def test_total_falls_back_to_sum(self):
        self.assertEqual(normalize_usage({"prompt_tokens": 3, "completion_tokens": 4,
                                          "total_tokens": 0})["total"], 7)


class ReplyMappingTest(unittest.TestCase):
    def test_text_reply(self):
        reply = to_reply(FakeResponse(FakeMessage("hi"), {"prompt_tokens": 1,
                                                          "completion_tokens": 2}))
        self.assertEqual(reply.content, "hi")
        self.assertEqual(reply.usage["total"], 3)
        self.assertEqual(reply.tool_calls, [])

    def test_tool_call_mapping(self):
        message = FakeMessage("", [FakeToolCall("c1", "refund", '{"amount": 100}')])
        reply = to_reply(FakeResponse(message))
        self.assertEqual(len(reply.tool_calls), 1)
        call = reply.tool_calls[0]
        self.assertEqual((call.id, call.name, call.args), ("c1", "refund", {"amount": 100}))

    def test_bad_json_args_become_empty(self):
        message = FakeMessage("", [FakeToolCall("c1", "x", "not json")])
        self.assertEqual(to_reply(FakeResponse(message)).tool_calls[0].args, {})


class ClientTest(unittest.TestCase):
    def test_missing_sdk_gives_install_hint(self):
        try:
            import openai  # noqa: F401
        except ImportError:
            with self.assertRaises(ConfigError) as ctx:
                OpenAIModel("gpt-4.1")
            self.assertIn("pip install", str(ctx.exception))
        else:  # pragma: no cover - 装了 SDK 的环境
            self.skipTest("环境已安装 openai SDK")

    def test_injected_client_launches_call(self):
        captured = {}

        class Completions:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return FakeResponse(FakeMessage("ok"), {"prompt_tokens": 1,
                                                        "completion_tokens": 1})

        class Chat:
            completions = Completions()

        class Client:
            chat = Chat()

        model = OpenAIModel("gpt-4.1", client=Client())
        reply = run(model.complete([{"role": "user", "content": "hi"}]))
        self.assertEqual(reply.content, "ok")
        self.assertEqual(captured["model"], "gpt-4.1")
        self.assertEqual(captured["messages"][0]["content"], "hi")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / "_tmp_cli"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_new_creates_skeleton(self):
        target = self.root / "demo"
        code = main(["new", str(target)])
        self.assertEqual(code, 0)
        self.assertTrue((target / "main.py").exists())
        self.assertTrue((target / "README.md").exists())
        self.assertTrue((target / "skills").is_dir())
        body = (target / "main.py").read_text(encoding="utf-8")
        self.assertIn("HarnessConfig", body)
        self.assertIn("react(max_steps", body)

    def test_help_without_args(self):
        self.assertEqual(main([]), 0)

    def test_unknown_command(self):
        self.assertEqual(main(["nope"]), 2)

    def test_check_reports_usable_spec(self):
        self.assertEqual(main(["check", "memory"]), 0)
        self.assertEqual(main(["check", {"kind": "memory"}]), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
