"""v3 通用解释器与效应系统验收（PROPOSAL §11）。

判据：十种主流架构 + 零封装程序共用一个 ``interpret()``；带环 DAG 装配期
拦截；治理分级明确降级；dry_run 只记账；Layer/Hook 照常；全局终止护栏
保证任何程序都能停下来；状态只在 commit 写；回滚不撤销观测计量。
"""

from __future__ import annotations

import asyncio
import unittest

from harness.contracts.decision import (
    Decision,
    FnProgram,
    Halt,
    capabilities,
    describe,
    to_spec,
)
from harness.contracts.errors import NotSerializable
from harness.contracts.types import Effect
from harness.fp.frontends import Graph, Leaf, builtin_paradigms, make_state
from harness.kernel.effects import EffectLayer
from harness.kernel.interpret import Runtime, RuntimeLimits, ValidationFailed, interpret


def run(coro):
    return asyncio.run(coro)


EVENTS: list[str] = []


def budget_gate(effect, state) -> str:
    return "deny" if state.usage["calls"] > 50 else "allow"


def audit_observe(effect, result, state) -> None:
    EVENTS.append(f"{effect.kind}:{state.rev}")


def truncate_wrap(effect, nxt):
    async def handler(eff, state):
        out = await nxt(eff, state)
        if isinstance(out, dict) and isinstance(out.get("output"), str) and len(out["output"]) > 80:
            out = {**out, "output": out["output"][:80] + "…[truncated]"}
        return out
    return handler


LAYERS = (
    EffectLayer("budget", gate=budget_gate),
    EffectLayer("audit", observe=audit_observe),
    EffectLayer("truncate", wrap=truncate_wrap),
)


def runtime(**kwargs) -> Runtime:
    params = dict(layers=LAYERS, limits=RuntimeLimits(max_transitions=64, max_calls=80))
    params.update(kwargs)
    return Runtime(**params)


class ParadigmTest(unittest.TestCase):
    def test_ten_builtin_paradigms_share_one_interpreter(self):
        cases = builtin_paradigms()
        self.assertEqual(len(cases), 10)
        for name, program, state in cases:
            with self.subTest(name=name):
                self.assertEqual(runtime().validate(program), [])
                out = run(runtime().interpret(program, state))
                self.assertEqual(out.status, "completed", f"{name}: {out.trace}")
                self.assertTrue(out.trace[0].startswith("run.start:"))
                self.assertEqual(out.trace[-1], "run.end:completed")
                self.assertEqual(out.checkpoints, out.transitions)

    def test_cyclic_dag_is_rejected_at_assembly(self):
        graph = builtin_paradigms()[9][1]
        cyclic = Graph(
            nodes={"a": graph.nodes["a"], "b": graph.nodes["b"]},
            edges=(("a", "b", ""), ("b", "a", "")),
            entry="a",
        )
        self.assertTrue(any("环" in p for p in runtime().validate(cyclic)))
        with self.assertRaises(ValidationFailed):
            run(runtime().interpret(cyclic, make_state("bad", data={"tools": {}})))

    def test_dangling_edge_and_missing_entry_are_reported(self):
        graph = Graph(nodes={"a": Effect("compute")}, edges=(("a", "ghost", ""),), entry="nope")
        problems = runtime().validate(graph)
        self.assertTrue(any("入口" in p for p in problems))
        self.assertTrue(any("悬空" in p for p in problems))

    def test_bad_transition_return_is_rejected(self):
        from harness.contracts.errors import DecisionError

        bad = FnProgram(lambda s: "not a decision", name="bad")
        with self.assertRaises(DecisionError):
            run(interpret(bad, make_state("x")))

    def test_leaf_and_bare_function_are_same_layer(self):
        bare = FnProgram(
            lambda s: Decision(
                effects=(Effect("compute", args={"op": "concat", "args": ["裸", "函数"]},
                                key="last"),),
                program=FnProgram(lambda x: Halt(str(x.data.get("last_output", ""))), name="end"),
            ),
            name="bare",
        )
        for program in (Leaf("叶子"), bare):
            with self.subTest(program=program.name):
                out = run(interpret(program, make_state("x")))
                self.assertEqual(out.status, "completed")


class GovernanceTierTest(unittest.TestCase):
    def test_graph_supports_all_static_capabilities(self):
        graph = builtin_paradigms()[9][1]
        self.assertEqual(capabilities(graph),
                         {"describe": True, "to_spec": True, "static_check": True})
        self.assertIn("graph", describe(graph))
        self.assertEqual(sorted(to_spec(graph)), ["edges", "entry", "kind", "nodes"])

    def test_opaque_program_degrades_explicitly(self):
        bare = FnProgram(lambda s: Halt("x"), name="bare")
        self.assertEqual(capabilities(bare),
                         {"describe": False, "to_spec": False, "static_check": False})
        self.assertEqual(describe(bare), "<opaque:bare>")
        with self.assertRaises((TypeError, NotSerializable)):
            to_spec(bare)

    def test_checkpoints_record_opaque_program_spec(self):
        bare = FnProgram(lambda s: Halt("x"), name="bare")
        # 走一轮纯决策，产生检查点后再终止
        prog = FnProgram(
            lambda s: Decision(effects=(), program=FnProgram(lambda x: Halt("done"), name="end")),
            name="bare",
        )
        rt = runtime()
        run(rt.interpret(prog, make_state("x")))
        self.assertTrue(rt.checkpoints)
        self.assertEqual(rt.checkpoints[0]["program"], "<opaque>")
        self.assertIn("data", rt.checkpoints[0]["state"])


class FourStagesTest(unittest.TestCase):
    def test_dry_run_only_records_calls(self):
        executed: list[str] = []

        async def charge(amount: int = 0) -> str:
            executed.append("charge")
            return "ok"

        out = run(Runtime(record_only=True, layers=LAYERS).interpret(
            builtin_paradigms()[1][1],
            make_state("干跑", data={"script": [{"content": "done"}],
                                    "tools": {"charge": charge}}),
        ))
        self.assertEqual(out.status, "completed")
        self.assertEqual(out.answer, "[dry-run:model]")
        self.assertEqual(executed, [])

    def test_gate_deny_short_circuits(self):
        deny = EffectLayer("deny", gate=lambda e, s: "deny")

        def prog(state):
            return Decision(effects=(Effect("compute", args={"op": "sum", "args": [1, 2]},
                                           key="k"),),
                            program=FnProgram(lambda s: Halt("ok"), name="end"))

        rt = Runtime(layers=(deny,))
        out = run(rt.interpret(FnProgram(prog, name="p"), make_state("x")))
        self.assertEqual(out.state.results["k"]["error"], "gate:deny")
        self.assertEqual(out.trace[-1], "run.end:completed")  # 门禁不抛异常

    def test_hook_observe_fires_without_affecting_run(self):
        seen: list[tuple] = []

        def boom(effect, result, state):
            raise RuntimeError("hook must not break the run")

        layers = (EffectLayer("observe", observe=lambda e, r, s: seen.append((e.kind, s.rev))),
                  EffectLayer("broken", observe=boom))
        out = run(Runtime(layers=layers).interpret(
            FnProgram(lambda s: Decision(
                effects=(Effect("compute", args={"op": "upper", "args": ["ok"]}, key="k"),),
                program=FnProgram(lambda x: Halt("done"), name="end")), name="p"),
            make_state("x")))
        self.assertEqual(out.status, "completed")
        self.assertEqual(len(seen), 1)

    def test_layer_observation_records_events(self):
        EVENTS.clear()
        name, program, state = builtin_paradigms()[1]
        run(runtime().interpret(program, state))
        self.assertTrue(EVENTS, "EffectLayer.observe / Hook 没有接上落点")
        self.assertTrue(all(":" in e for e in EVENTS))

    def test_extra_handler_extends_kind_without_kernel_change(self):
        async def ping(effect, state):
            return {"ok": True, "output": "pong"}

        out = run(interpret(
            FnProgram(lambda s: Decision(
                effects=(Effect("ping", key="k"),),
                program=FnProgram(lambda x: Halt(str(x.data["last_output"])), name="end")),
                name="p"),
            make_state("x"), extra_handlers={"ping": ping},
        ))
        self.assertEqual(out.answer, "pong")

    def test_idempotency_key_replays_result(self):
        calls: list[int] = []

        async def once(effect, state):
            calls.append(1)
            return {"ok": True, "output": str(len(calls))}

        prog = FnProgram(lambda s: Decision(
            effects=(Effect("once", idem_key="same", key="k"),),
            program=FnProgram(lambda x: Decision(
                effects=(Effect("once", idem_key="same", key="k2"),),
                program=FnProgram(lambda y: Halt("done"), name="end")), name="mid"),
        ), name="p")
        rt = Runtime(extra_handlers={"once": once})
        run(rt.interpret(prog, make_state("x")))
        self.assertEqual(len(calls), 1)


class RuntimeInvariantTest(unittest.TestCase):
    def test_global_termination_guardrails(self):
        spin = FnProgram(lambda s: Decision(program=None, note="spin"), name="spin")
        calling = FnProgram(
            lambda s: Decision(effects=(Effect("compute", args={"op": "sum", "args": [1]}),),
                               program=None, note="call"), name="calling")
        for program, limits, expected in (
            (spin, RuntimeLimits(max_transitions=5, wall_seconds=60), "max_transitions"),
            (calling, RuntimeLimits(max_transitions=100, max_calls=1, wall_seconds=60), "max_calls"),
            (spin, RuntimeLimits(max_transitions=100, wall_seconds=0), "wall_clock"),
        ):
            with self.subTest(expected=expected):
                out = run(interpret(program, make_state("x"), limits=limits))
                self.assertEqual(out.status, "degraded")
                self.assertEqual(out.answer, expected)

    def test_parallel_batch_and_single_commit_point(self):
        reads: list[int] = []

        def first(state):
            reads.append(state.rev)
            return Decision(
                effects=(
                    Effect("compute", args={"op": "upper", "args": ["a"]}, key="a"),
                    Effect("compute", args={"op": "upper", "args": ["b"]}, key="b"),
                ),
                program=FnProgram(lambda s: Halt(
                    f"{s.results['a']['output']}{s.results['b']['output']}:rev{s.rev}"), name="end"),
            )

        out = run(interpret(FnProgram(first, name="p"), make_state("x")))
        self.assertEqual(out.answer, "AB:rev1")
        self.assertEqual(reads, [0])           # 程序只读 state，未提交前 rev 不变

    def test_journal_and_usage_do_not_roll_back(self):
        """回溯撤销业务状态，但不撤销已经消费过的模型脚本与计量。"""
        state = make_state("搜索", data={"script": [{"verdict": "fail"}, {"verdict": "pass"}]})
        snap = state.snapshot()
        state.journal["cursor"] = 2
        state.usage["calls"] = 7
        state.data["draft"] = "changed"
        state.restore(snap)
        self.assertEqual(state.journal["cursor"], 2)
        self.assertEqual(state.usage["calls"], 7)
        self.assertNotIn("draft", state.data)

    def test_restore_decision_reverts_business_state(self):
        snapshots: list[dict] = []

        def probe(s):
            snapshots.append(s.snapshot())
            end = FnProgram(lambda y: Halt(str(y.data.get("phase", "clean"))), name="end")
            back = FnProgram(
                lambda x: Decision(effects=(), restore=snapshots[0], program=end,
                                   note="backtrack"), name="back")
            return Decision(effects=(), patch={"phase": "trial"}, program=back)

        out = run(interpret(FnProgram(probe, name="p"), make_state("x")))
        self.assertEqual(out.answer, "clean")
        self.assertTrue(any("backtrack" in t for t in out.trace))

    def test_child_effect_runs_nested_program(self):
        from harness.fp.frontends import SupervisorProgram

        sup = SupervisorProgram(workers={"w": Leaf("子结果")})
        out = run(interpret(sup, make_state("x", data={
            "script": [{"tasks": [["w", "任务"]]}],
        })))
        self.assertEqual(out.status, "completed")
        self.assertEqual(out.answer, "子结果")

    def test_state_snapshot_is_deep_copy(self):
        state = make_state("x", data={"nested": {"v": 1}})
        snap = state.snapshot()
        state.data["nested"]["v"] = 99
        self.assertEqual(snap["data"]["nested"]["v"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
