"""SUPPLEMENT-PLAN（v3.1）补充项的离线验收。

覆盖：A1 重规划 / A2 检查点与崩溃恢复 / A3 路由 / A4 预算接线 /
A5 结构化输出 / A6 token 计数 / B2 openai 注册表 / B3 向量检索。
每个补充项的验收都含一次替换实验（"换掉它只消失一件事"）。
"""

from __future__ import annotations

import asyncio
import unittest

from harness.assembly.build import AgentConfig, build
from harness.assembly.registry import BACKENDS, MODELS, resolve
from harness.contracts.decision import FnProgram
from harness.contracts.decision import Decision as Transition
from harness.contracts.decision import Halt
from harness.contracts.errors import ConfigError, ContractError
from harness.contracts.status import RunStatus
from harness.contracts.types import (
    ActionResult,
    Budget,
    Document,
    Done,
    Effect,
    Goal,
    Namespace,
    Plan,
    Route,
    Step,
    Verdict,
)
from harness.fp.frontends import make_state
from harness.impl.backends.core import MemoryIndex
from harness.impl.backends.vector import InMemoryVectorIndex
from harness.impl.stores.memory import MemoryCheckpointStore
from harness.kernel.interpret import interpret, resume_from_checkpoint
from harness.parts.body.pe import PlanExecutePolicy
from harness.parts.budget import Budget as AgentBudget
from harness.parts.dispatch import LLMRouter, RuleRouter, VectorRouter
from harness.parts.framing.encoders import ChatEncoder
from harness.parts.framing.framers import ModelFramer, est_tokens
from harness.parts.structured import structured, validate_json
from harness.parts.tokens import CharEstimator, TiktokenCounter
from harness.testing import FakeModel, answer, tool_call

from conformance import IndexBackendConformance, NS_A


def run_(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- B1/B3 conformance


class MemoryIndexConformance(IndexBackendConformance, unittest.TestCase):
    def factory(self):
        return MemoryIndex()


class VectorIndexConformance(IndexBackendConformance, unittest.TestCase):
    def factory(self):
        return InMemoryVectorIndex()


# ---------------------------------------------------------------- A1 重规划


class ReplanAllReflector:
    """永远要求重规划的 Reflector（替换实验的反例件）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def review(self, result, state) -> Verdict:
        self.calls += 1
        return Verdict(passed=False, reason="计划整体不可救", action="replan_all")


class CountingPlanner:
    """数调用次数：初始规划 + 每次重规划各一次。"""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = steps
        self.calls = 0

    async def plan(self, goal, state) -> Plan:
        self.calls += 1
        return Plan(id="p1", steps=list(self.steps))


def _step(name: str) -> Step:
    return Step(id=name, instruction=name, tool_name="noop", args={})


class TestA1Replan(unittest.TestCase):
    def test_replan_all_triggers_new_plan_and_counts(self):
        planner = CountingPlanner([_step("t1"), _step("t2")])
        reflector = ReplanAllReflector()
        budget = Budget()               # contracts 版：带 replans 镜像计数
        policy = PlanExecutePolicy(planner, reflector=reflector,
                                   max_replans=2, budget=budget)
        state = make_state("干点活")

        first = run_(policy.next_step(state, None))
        self.assertEqual(first.id, "t1")            # 初始计划第一步
        self.assertEqual(planner.calls, 1)
        self.assertEqual(state.section("pe")["replans"], 0)

        state.data["last_result"] = ActionResult(step_id="t1", ok=False, error="boom")
        second = run_(policy.next_step(state, None))
        self.assertEqual(second.id, "t1")           # 重规划后回到新计划第一步
        self.assertEqual(state.section("pe")["replans"], 1)
        self.assertEqual(budget.replans, 1)         # 镜像计数
        self.assertEqual(state.section("pe")["replan_context"]["reason"],
                         "计划整体不可救")
        self.assertEqual(state.section("pe")["replan_context"]["completed"],
                         [{"id": "t1", "instruction": "t1", "tool_name": "noop",
                           "args": {}, "idem_key": None, "kind": "tool",
                           "index": 0, "plan_id": ""}])

        state.data["last_result"] = ActionResult(step_id="t1", ok=False, error="boom")
        run_(policy.next_step(state, None))
        self.assertEqual(state.section("pe")["replans"], 2)
        self.assertEqual(planner.calls, 3)          # 初始 + 两次重规划

        state.data["last_result"] = ActionResult(step_id="t1", ok=False, error="boom")
        done = run_(policy.next_step(state, None))
        self.assertIsInstance(done, Done)
        self.assertIn("replan_limit", done.reason)  # 超上限降级，不再重规划

    def test_no_reflector_no_replan_path(self):
        """DoD：NullReflector（reflector=None）时该路径不存在。"""
        planner = CountingPlanner([_step("t1"), _step("t2")])
        policy = PlanExecutePolicy(planner, reflector=None)
        state = make_state("干点活")
        run_(policy.next_step(state, None))
        state.data["last_result"] = ActionResult(step_id="t1", ok=False, error="boom")
        second = run_(policy.next_step(state, None))
        self.assertEqual(second.id, "t2")           # 继续原计划，不重规划
        self.assertEqual(planner.calls, 1)


# ---------------------------------------------------------------- A2 检查点与崩溃恢复


class TestA2CheckpointRecovery(unittest.TestCase):
    def _program(self):
        """两个程序：先算一批效应，再读结果终止。"""
        def step_one(state) -> Transition:
            return Transition(
                effects=(Effect("compute", args={"op": "concat",
                                                 "args": ["恢复", "测试"]}, key="a"),),
                program=FnProgram(lambda s: Halt(str(s.results["a"]["output"])),
                                  name="end"),
                note="fan-out 1",
            )

        return FnProgram(step_one, name="crashy")

    def test_runtime_persists_checkpoints(self):
        store = MemoryCheckpointStore()
        out = run_(interpret(self._program(), make_state("检查点"),
                             checkpoint_store=store))
        self.assertEqual(out.status, "completed")
        got = run_(store.get(Namespace(session="s1"), "s1"))
        self.assertIsNotNone(got)
        # 单转移运行只落一次盘：store 版本从 0 计（rev 由 store 管理）
        self.assertEqual(got.rev, 0)
        self.assertEqual(got.state.results["a"]["output"], "恢复测试")

    def test_resume_from_latest_checkpoint(self):
        """kill 掉跑到一半的运行：从最近检查点重放续跑（重放结论不是重新推理）。"""
        store = MemoryCheckpointStore()
        program = self._program()
        state = make_state("检查点", session_id="crash-1")
        run_(interpret(program, state, checkpoint_store=store))

        recovered = run_(resume_from_checkpoint(
            store, program, "crash-1", ns=Namespace(session="crash-1")))
        self.assertEqual(recovered.status, "completed")
        self.assertEqual(recovered.answer, "恢复测试")

    def test_agent_resume_without_decision_is_crash_recovery(self):
        from harness.parts.tools import tool

        @tool
        async def concat(left: str, right: str) -> str:
            """拼接。"""
            return left + right

        model = FakeModel([
            tool_call("concat", left="崩", right="溃恢复"),
            answer("收尾答复"),
        ])
        agent = build(AgentConfig(
            model=model, tools=[concat], mode="react", max_steps=8,
            checkpoints=MemoryCheckpointStore(),
            budget=AgentBudget(tokens=10**9, calls=10**9),
        ))
        goal = Goal("跑一次", user_id="anonymous", session_id="resume-1")
        first = run_(agent.run(goal))
        self.assertEqual(first.status, RunStatus.COMPLETED)
        # 单 commit 的 ReAct 运行只落一次盘（store 版本从 0 计）；
        # 检查点是否真实存在由下一步 resume 成功与否证明。

        resumed = run_(agent.resume("resume-1", decision=None,
                                    ns=Namespace(session="resume-1")))
        self.assertEqual(resumed.status, RunStatus.COMPLETED)   # 从检查点重放续跑
        self.assertIn("崩", resumed.state.data.get("last_output", ""))

    def test_resume_without_store_raises(self):
        agent = build(AgentConfig(model=FakeModel([answer("x")]), mode="react"))
        with self.assertRaises(Exception):
            run_(agent.resume("nope", decision=None))


# ---------------------------------------------------------------- A4 预算接线


class TestA4BudgetWiring(unittest.TestCase):
    def test_budget_exhausted_triggers_interpreter_guardrail(self):
        """DoD：预算耗尽由解释器护栏触发（degraded），非程序自查。"""
        from harness.parts.tools import tool

        @tool
        async def noop() -> str:
            """空操作。"""
            return "ok"

        model = FakeModel([
            tool_call("noop"),
            tool_call("noop"),
            answer("不该走到这里"),
        ])
        agent = build(AgentConfig(
            model=model, tools=[noop], mode="react", max_steps=8,
            budget=AgentBudget(tokens=10**9, calls=1),   # 只允许 1 次调用
        ))
        result = run_(agent.run(Goal("跑", session_id="a4")))
        self.assertEqual(result.status, RunStatus.DEGRADED)
        self.assertEqual(result.answer, "max_calls")    # 护栏触发，不是 "budget exhausted"
        self.assertNotIn("budget", (result.error or ""))

    def test_explicit_limits_override_budget_derivation(self):
        from harness.kernel.interpret import RuntimeLimits
        from harness.parts.tools import tool

        @tool
        async def noop() -> str:
            """空操作。"""
            return "ok"

        model = FakeModel([tool_call("noop"), answer("完成")])
        agent = build(AgentConfig(
            model=model, tools=[noop], mode="react", max_steps=8,
            budget=AgentBudget(tokens=10**9, calls=10**9),
            limits=RuntimeLimits(max_transitions=2, max_calls=10**9,
                          max_tokens=10**9, wall_seconds=30.0),
        ))
        result = run_(agent.run(Goal("跑", session_id="a4b")))
        self.assertEqual(result.status, RunStatus.COMPLETED)   # 显式 limits 放行


# ---------------------------------------------------------------- A5 结构化输出


SCHEMA = {"type": "object", "required": ["total"],
          "properties": {"total": {"type": "integer"}}}


class TestA5StructuredOutput(unittest.TestCase):
    def test_validation_error_retried_then_parsed(self):
        model = FakeModel(['{"total": "3"}', '{"total": 3}'])   # 第一次类型错
        sm = structured(model, SCHEMA, max_retries=2)
        reply = run_(sm.complete([{"role": "user", "content": "几件？"}]))
        self.assertEqual(reply.parsed, {"total": 3})            # 强类型结果
        self.assertEqual(model.calls, 2)                        # 校验失败自动重试
        # 校验错误回灌：第二次请求比第一次多一条 user 消息
        self.assertEqual(len(model.seen[1]), len(model.seen[0]) + 1)
        self.assertIn("校验错误", model.seen[1][-1]["content"])

    def test_invalid_after_retries_fails_explicitly(self):
        model = FakeModel(['{"total": "x"}', '{"total": "y"}', '{"total": "z"}'])
        sm = structured(model, SCHEMA, max_retries=2)
        with self.assertRaises(ContractError):
            run_(sm.complete([{"role": "user", "content": "几件？"}]))

    def test_builtin_validator_catches_missing_and_type(self):
        value, errors = validate_json('{"total": "3"}', SCHEMA)
        self.assertEqual(value, {"total": "3"})
        self.assertTrue(any("expected integer" in e for e in errors))
        value, errors = validate_json('{"other": 1}', SCHEMA)
        self.assertTrue(any("缺少必填字段" in e for e in errors))
        value, errors = validate_json("not-json", SCHEMA)
        self.assertTrue(any("invalid_json" in e for e in errors))

    def test_replace_model_only_changes_one_thing(self):
        """替换实验：换底层模型只改一行。"""
        class AltModel:
            async def complete(self, messages, tools=None):
                return answer('{"total": 7}')

        reply = run_(structured(AltModel(), SCHEMA).complete([]))
        self.assertEqual(reply.parsed, {"total": 7})


# ---------------------------------------------------------------- A6 token 计数


class DoubleCounter:
    """测试用计数器：字符数 ×2（与 CharEstimator 同构但口径不同）。"""

    name = "double"

    def count(self, text: str) -> int:
        return len(text or "") * 2

    def count_messages(self, messages) -> int:
        return sum(len(str(m.get("content", ""))) * 2 for m in messages or ())


class TestA6TokenCounter(unittest.TestCase):
    def _frame_texts(self, framer, state):
        frame = run_(framer.frame(state, budget=Budget(tokens=100_000)))
        return {s.name: s.tokens_est for s in frame.sections}

    def test_default_counter_matches_char_estimate(self):
        framer = ModelFramer(system="abcd")
        counts = self._frame_texts(framer, make_state("目标"))
        self.assertEqual(counts["system"], est_tokens("abcd"))

    def test_injected_counter_changes_precision_not_decisions(self):
        """替换实验：换计数器只变精度，取景决策（槽位集合）不变。"""
        state = make_state("目标")
        default = self._frame_texts(ModelFramer(system="abcd"), state)
        injected = self._frame_texts(ModelFramer(system="abcd", counter=DoubleCounter()),
                                     state)
        self.assertEqual(set(default), set(injected))   # 槽位集合一致
        self.assertEqual(injected["system"], len("abcd") * 2)

    def test_chat_encoder_uses_counter(self):
        frame = run_(ModelFramer(system="abcd").frame(
            make_state("目标"), budget=Budget(tokens=100_000)))
        pack = run_(ChatEncoder(counter=DoubleCounter()).encode(frame))
        self.assertGreater(pack.usage["estimated_tokens"], 0)
        self.assertEqual(pack.usage["estimated_tokens"] % 2, 0)   # Double 口径

    def test_char_estimator_offline_and_tiktoken_requires_extra(self):
        counter = CharEstimator()
        self.assertEqual(counter.count("abcd"), 1)      # 4 字符 ≈ 1 token
        try:
            TiktokenCounter()
        except ConfigError:
            pass                                        # 未装 tiktoken：明确报错不静默
        except ImportError:
            self.fail("应报 ConfigError 而不是裸 ImportError")


# ---------------------------------------------------------------- A3 路由


class TestA3Routers(unittest.TestCase):
    def _routes(self):
        return [Route("refund", accepts=["退款"]),
                Route("general", fallback=True)]

    def test_llm_router_routes_by_scripted_reply(self):
        model = FakeModel([answer('{"route": "refund"}')])
        router = LLMRouter(routes=self._routes(), model=model, default="general")
        route = run_(router.route(Goal("我要退款", session_id="r")))
        self.assertEqual(route.name, "refund")

    def test_llm_router_falls_back_and_counts(self):
        model = FakeModel([answer("这不是 JSON")])
        router = LLMRouter(routes=self._routes(), model=model, default="general")
        route = run_(router.route(Goal("随便说", session_id="r")))
        self.assertEqual(route.name, "general")
        self.assertEqual(router.fallback_count, 1)
        self.assertEqual(router.fallback_rate, 1.0)

    def test_vector_router_routes_by_nearest_doc(self):
        index = InMemoryVectorIndex()
        run_(index.upsert(NS_A, [
            Document(id="d1", text="退款政策：七天无理由退款",
                     metadata={"source": "route=refund"}),
            Document(id="d2", text="物流查询：查看订单物流",
                     metadata={"source": "route=general"}),
        ]))
        router = VectorRouter(index=index, namespace=NS_A, min_score=0.01,
                              default="general")
        route = run_(router.route(Goal("我的退款到哪一步了", session_id="r")))
        self.assertEqual(route.name, "refund")

    def test_vector_router_falls_back_on_empty_index(self):
        router = VectorRouter(index=InMemoryVectorIndex(), default="general")
        route = run_(router.route(Goal("退款", session_id="r")))
        self.assertEqual(route.name, "general")
        self.assertEqual(router.fallback_count, 1)

    def test_router_replacement_experiment(self):
        """替换实验：RuleRouter ↔ VectorRouter 互换，返回形状一致。"""
        rule = RuleRouter(routes=[Route("refund", accepts=["退款"])],
                          default="general")
        index = InMemoryVectorIndex()
        run_(index.upsert(NS_A, [Document(
            id="d1", text="退款规则说明", metadata={"source": "route=refund"})]))
        vector = VectorRouter(index=index, namespace=NS_A, min_score=0.0,
                              default="general")
        by_rule = run_(rule.route(Goal("退款", session_id="r")))
        by_vector = run_(vector.route(Goal("退款", session_id="r")))
        self.assertEqual(by_rule.name, by_vector.name)   # 下游行为一致
        self.assertIsInstance(by_vector, Route)


# ---------------------------------------------------------------- B2 注册表


class TestB2RegistryWiring(unittest.TestCase):
    def test_openai_slot_no_longer_placeholder(self):
        """openai 槽位接真实现：未装依赖时报带安装命令的 ConfigError，
        装了依赖则返回真 Model——不再是无差别抛错占位。"""
        try:
            model = resolve("model", "openai", MODELS)
            self.assertTrue(hasattr(model, "complete"))
        except ConfigError as exc:
            self.assertIn("pip install", str(exc))

    def test_fake_slot_still_works(self):
        model = resolve("model", "fake", MODELS)
        reply = run_(model.complete([{"role": "user", "content": "hi"}]))
        self.assertEqual(str(getattr(reply, "content", "")), "fake")

    def test_vector_slot_registered(self):
        factory = BACKENDS["index"]["vector"]
        self.assertIsNotNone(factory())


if __name__ == "__main__":
    unittest.main()
