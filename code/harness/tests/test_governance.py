"""治理、分派与 Skills 的离线测试。"""

from __future__ import annotations

import asyncio
import json
import shutil
import unittest
from pathlib import Path

from harness import (
    AgentConfig,
    AlwaysRoute,
    Goal,
    Resilience,
    Route,
    RuleRouter,
    RunStatus,
    SkillRegistry,
    Step,
    build,
    tool,
)
from harness.errors import ToolError
from harness.testing import FakeModel, answer


@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right


class TestGovernance(unittest.TestCase):
    def test_resilience_retries(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ToolError("transient")
            return "ok"

        result = asyncio.run(Resilience(retries=1).call(flaky))
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 2)

    def test_rule_router(self):
        router = RuleRouter(routes=[
            Route("refund", accepts=["退款", "退货"]),
            Route("general", fallback=True),
        ])
        self.assertEqual(asyncio.run(router.route(Goal("我要退款"))).name, "refund")
        self.assertEqual(asyncio.run(router.route(Goal("你好"))).name, "general")
        self.assertEqual(asyncio.run(AlwaysRoute().route(Goal("x"))).name, "default")

    def test_skill_as_workflow(self):
        tmp = Path("code/harness/tests/_tmp_skill")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        try:
            folder = tmp / "refund-review"
            folder.mkdir()
            (folder / "SKILL.md").write_text(
                "---\nname: refund-review\ndescription: 退款审核\n"
                "allowed-tools: [concat]\n---\n先查订单，再拼接。\n",
                encoding="utf-8",
            )
            (folder / "workflow.json").write_text(json.dumps({
                "steps": [
                    {"id": "a", "tool_name": "concat", "args": {"left": "a", "right": "b"}},
                    {"id": "b", "tool_name": "concat", "args": {"left": "c", "right": "d"}},
                ]
            }), encoding="utf-8")

            registry = SkillRegistry.from_dir(tmp)
            self.assertEqual([item.name for item in registry.catalog()], ["refund-review"])
            self.assertEqual(registry.load("refund-review").meta.allowed_tools, ["concat"])

            agent = build(AgentConfig(
                model=FakeModel([answer("unused")]),
                tools=[concat],
                mode="workflow",
                workflow=registry.as_workflow("refund-review").steps,
            ))
            result = asyncio.run(agent.run(Goal("退款审核")))
            self.assertEqual(result.status, RunStatus.COMPLETED)
            self.assertEqual(result.answer, "cd")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
