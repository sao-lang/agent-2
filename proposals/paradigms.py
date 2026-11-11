"""通用解释器方案 · 10 种内置架构范式（提案样张）。

对应方案第 7 节。目标位置是 fp/frontends.py；这里先做成可运行的独立样张。

重要：这 10 个类与用户自己写的架构**完全同层、同一个 Program 协议**，
框架内核不认识它们，删掉整个文件框架照样跑任意架构。

所有 transition 都是纯同步函数：只读 State，所有 I/O 表达成 Effect。
循环 = program 返回自己；顺序 = 换成下一个游标；分支 = 换成某个 arm；
并行 = 一批 Effect；回溯 = 换回历史 program + restore。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, ClassVar

from proposals.contracts import Decision, Effect, Halt, State


def _batch(state: State) -> dict[str, Any]:
    """本批新结果。解释器每轮覆盖，历史结果仍留在 state.results。"""

    return state.results.get("__batch__", {})


def _out(batch: dict[str, Any], key: str) -> Any:
    value = batch.get(key)
    return value.get("output") if isinstance(value, dict) else value


@dataclass(frozen=True)
class Leaf:
    """辅助叶子：一个立即结束的程序（不是第 11 种架构）。"""

    name: ClassVar[str] = "leaf"
    text: str = ""

    def describe(self) -> str:
        return f"leaf({self.text})"

    def to_spec(self) -> dict[str, Any]:
        return {"kind": "leaf", "text": self.text}

    def transition(self, state: State) -> Decision | Halt:
        return Halt(self.text)


# ------------------------------------------------------------------ ① 单 Agent + 工具
@dataclass(frozen=True)
class ToolUse:
    name: ClassVar[str] = "tool_use"
    calls: tuple[Effect, ...] = ()
    fired: bool = False

    def describe(self) -> str:
        return f"tool_use({len(self.calls) or 1} calls)"

    def transition(self, state: State) -> Decision | Halt:
        if self.fired:
            return Halt(str(state.data.get("last_output", "")))
        effects = self.calls or (Effect("tool", {"name": "echo", "args": {"text": "hi"}}, key="last"),)
        return Decision(effects=effects, program=replace(self, fired=True), note="call tool")


# ------------------------------------------------------------------ ② ReAct
@dataclass(frozen=True)
class React:
    name: ClassVar[str] = "react"
    max_steps: int = 8
    step: int = 0

    def describe(self) -> str:
        return f"react(max_steps={self.max_steps})"

    def transition(self, state: State) -> Decision | Halt:
        if self.step >= self.max_steps:
            return Halt("max_steps", "degraded")
        batch = _batch(state)
        reply = _out(batch, "model")
        if reply is not None:
            calls = reply.get("tool_calls", []) if isinstance(reply, dict) else []
            if not calls:
                return Halt(str(reply.get("content", "")) if isinstance(reply, dict) else str(reply))
            call = calls[0]
            return Decision(
                effects=(Effect("tool", {"name": call["name"], "args": call.get("args", {})}, key="tool"),),
                program=replace(self, step=self.step + 1), note="act",
            )
        return Decision(effects=(Effect("model", key="model"),), program=self, note="think")


# ------------------------------------------------------------------ ③ Plan & Execute
@dataclass(frozen=True)
class PlanExecute:
    name: ClassVar[str] = "plan_execute"
    phase: str = "plan"
    steps: tuple[dict[str, Any], ...] = ()
    cursor: int = 0

    def describe(self) -> str:
        return f"plan_execute(phase={self.phase}, cursor={self.cursor})"

    def transition(self, state: State) -> Decision | Halt:
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self, note="plan")
            plan = reply.get("plan", []) if isinstance(reply, dict) else []
            return Decision(effects=(), program=replace(self, phase="exec", steps=tuple(plan)), note="plan ready")
        if self.cursor >= len(self.steps):
            return Halt(str(state.data.get("last_output", "")))
        step = self.steps[self.cursor]
        return Decision(
            effects=(Effect("tool", {"name": step["name"], "args": step.get("args", {})}, key="tool"),),
            program=replace(self, cursor=self.cursor + 1), note=f"step {self.cursor + 1}",
        )


# ------------------------------------------------------------------ ④ Reflection / Evaluator-Optimizer
@dataclass(frozen=True)
class Reflection:
    name: ClassVar[str] = "reflection"
    phase: str = "draft"
    round: int = 0
    max_rounds: int = 3

    def describe(self) -> str:
        return f"reflection(round={self.round})"

    def transition(self, state: State) -> Decision | Halt:
        batch = _batch(state)
        if self.phase == "draft":
            draft = _out(batch, "draft")
            if draft is None:
                return Decision(effects=(Effect("model", key="draft"),), program=self, note="draft")
            text = draft.get("content", "") if isinstance(draft, dict) else str(draft)
            return Decision(
                effects=(), program=replace(self, phase="critic"),
                patch={"draft": text}, note="draft ready",
            )
        verdict = _out(batch, "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="critic")
        passed = isinstance(verdict, dict) and verdict.get("verdict") == "pass"
        if passed or self.round >= self.max_rounds:
            return Halt(str(state.data.get("draft", "")))
        return Decision(
            effects=(), program=replace(self, phase="draft", round=self.round + 1),
            note="revise",
        )


# ------------------------------------------------------------------ ⑤ Router
@dataclass(frozen=True)
class Router:
    name: ClassVar[str] = "router"
    arms: dict[str, Any] = field(default_factory=dict)
    fallback: Any = None
    phase: str = "route"

    def describe(self) -> str:
        return f"router(arms={sorted(self.arms)})"

    def transition(self, state: State) -> Decision | Halt:
        reply = _out(_batch(state), "model")
        if reply is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="classify")
        name = reply.get("route", "general") if isinstance(reply, dict) else "general"
        arm = self.arms.get(name, self.fallback)
        if arm is None:
            return Halt(f"无匹配 arm：{name}", "refused")
        return Decision(effects=(), program=arm, patch={"route": name}, note=f"-> {name}")


# ------------------------------------------------------------------ ⑥ Router + Skill
@dataclass(frozen=True)
class RouterSkill:
    """分流 + 能力包：路由选中技能，按需加载正文（渐进披露第 ② 段）后交给执行体。"""

    name: ClassVar[str] = "router_skill"
    arms: dict[str, Any] = field(default_factory=dict)
    fallback: Any = None
    phase: str = "route"
    chosen: str = ""

    def describe(self) -> str:
        return f"router_skill(arms={sorted(self.arms)})"

    def transition(self, state: State) -> Decision | Halt:
        batch = _batch(state)
        if self.phase == "route":
            reply = _out(batch, "model")
            if reply is None:
                # 目录（第 ① 段）常驻在 state.data["skills"]，由取景器注入；这里只做选路
                return Decision(effects=(Effect("model", key="model"),), program=self, note="select skill")
            name = reply.get("route", "general") if isinstance(reply, dict) else "general"
            if name not in self.arms:
                name = "general"
            return Decision(
                effects=(Effect("skill", {"name": name, "part": "body"}, key="body"),),
                program=replace(self, phase="dispatch", chosen=name), note=f"load {name}",
            )
        body = _out(batch, "body")
        arm = self.arms.get(self.chosen, self.fallback)
        if arm is None:
            return Halt("无匹配技能", "refused")
        return Decision(
            effects=(), program=arm,
            patch={"skill": self.chosen, "skill_body": body}, note=f"run {self.chosen}",
        )


# ------------------------------------------------------------------ ⑦ Supervisor / Orchestrator-Worker
@dataclass(frozen=True)
class Supervisor:
    name: ClassVar[str] = "supervisor"
    workers: dict[str, Any] = field(default_factory=dict)
    phase: str = "plan"

    def describe(self) -> str:
        return f"supervisor(workers={sorted(self.workers)})"

    def transition(self, state: State) -> Decision | Halt:
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self, note="decompose")
            tasks = reply.get("tasks", []) if isinstance(reply, dict) else []
            # 生产实现里 child 携带具名 program_ref；样张直接带 Program 对象以便运行
            effects = tuple(
                Effect("child", {"program": self.workers[name], "goal": goal, "data": {}}, key=name)
                for name, goal in tasks if name in self.workers
            )
            return Decision(effects=effects, program=replace(self, phase="join"), note="fan-out")
        outputs = [
            str(state.results.get(name, {}).get("output", ""))
            for name in self.workers
        ]
        return Halt(" | ".join(o for o in outputs if o))


# ------------------------------------------------------------------ ⑧ Handoff / Swarm
@dataclass(frozen=True)
class Handoff:
    name: ClassVar[str] = "handoff"
    roles: dict[str, Any] = field(default_factory=dict)
    current: str = "triage"
    hops: int = 0
    max_hops: int = 6

    def describe(self) -> str:
        return f"handoff(current={self.current})"

    def transition(self, state: State) -> Decision | Halt:
        reply = _out(_batch(state), "model")
        if reply is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note=f"{self.current} thinks")
        if isinstance(reply, dict) and reply.get("handoff") and self.hops < self.max_hops:
            target = reply["handoff"]
            return Decision(
                effects=(), program=replace(self, current=target, hops=self.hops + 1),
                patch={"last_role": self.current}, note=f"handoff -> {target}",
            )
        text = reply.get("content", self.current) if isinstance(reply, dict) else str(reply)
        return Halt(f"{self.current}: {text}")


# ------------------------------------------------------------------ ⑨ Blackboard
@dataclass(frozen=True)
class Blackboard:
    name: ClassVar[str] = "blackboard"
    agents: tuple[Any, ...] = ()
    max_rounds: int = 2
    round: int = 0

    def describe(self) -> str:
        return f"blackboard(agents={len(self.agents)}, rounds={self.max_rounds})"

    @staticmethod
    def _key(index: int, agent: Any) -> str:
        return f"{agent.name}-{index}"

    def transition(self, state: State) -> Decision | Halt:
        if self.round >= self.max_rounds:
            board = [
                str(state.results.get(self._key(i, agent), {}).get("output", ""))
                for i, agent in enumerate(self.agents)
            ]
            return Halt(" / ".join(v for v in board if v))
        effects = tuple(
            Effect("child", {"program": agent, "goal": state.goal, "data": {}},
                   key=self._key(i, agent))
            for i, agent in enumerate(self.agents)
        )
        return Decision(
            effects=effects, program=replace(self, round=self.round + 1),
            patch={"board_rev": self.round}, note="write board",
        )


# ------------------------------------------------------------------ ⑩ Graph / Workflow（DAG 前端）
@dataclass(frozen=True)
class Graph:
    """声明式前端：节点 + 条件边。可静态校验、可打印、可序列化。

    纯 DAG 表达不了环 —— 环放在节点内部（节点可以是任意 Program）。
    """

    name: ClassVar[str] = "graph"
    nodes: dict[str, Effect] = field(default_factory=dict)
    edges: tuple[tuple[str, str, str], ...] = ()
    entry: str = ""
    done: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"graph(entry={self.entry}, nodes={len(self.nodes)}, edges={len(self.edges)})"

    def to_spec(self) -> dict[str, Any]:
        return {
            "kind": "graph",
            "nodes": {k: asdict(v) for k, v in self.nodes.items()},
            "edges": [list(e) for e in self.edges],
            "entry": self.entry,
        }

    def static_check(self) -> list[str]:
        problems: list[str] = []
        if self.entry not in self.nodes:
            problems.append(f"入口节点不存在：{self.entry}")
        for src, dst, _when in self.edges:
            if src not in self.nodes or dst not in self.nodes:
                problems.append(f"悬空边：{src} -> {dst}")
        indeg = {n: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n: [] for n in self.nodes}
        for src, dst, _when in self.edges:
            if src in adj and dst in indeg:
                adj[src].append(dst)
                indeg[dst] += 1
        ready = [n for n, d in indeg.items() if d == 0]
        seen = 0
        while ready:
            n = ready.pop()
            seen += 1
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if seen != len(self.nodes):
            problems.append("图中存在环：DAG 前端不允许回边（环请放进节点内部）")
        return problems

    @staticmethod
    def _ok(when: str, state: State) -> bool:
        if not when:
            return True
        if when.startswith("route:"):
            return state.data.get("route") == when.split(":", 1)[1]
        return True

    def transition(self, state: State) -> Decision | Halt:
        if not self.done:
            return Decision(
                effects=(replace(self.nodes[self.entry], key=self.entry),),
                program=replace(self, done=(self.entry,)), note="entry",
            )
        nxt = [
            dst for src, dst, when in self.edges
            if src in self.done and dst not in self.done and self._ok(when, state)
        ]
        if not nxt:
            return Halt(str(state.data.get("last_output", "")))
        effects = tuple(replace(self.nodes[n], key=n) for n in nxt)
        return Decision(
            effects=effects, program=replace(self, done=self.done + tuple(nxt)),
            note="-> " + ",".join(nxt),
        )


# ------------------------------------------------------------------ demo 装配
async def echo(text: str = "hi") -> str:
    return f"echo:{text}"


async def lookup(order_id: str = "A1") -> dict:
    return {"order_id": order_id, "status": "已签收"}


def toolset() -> dict[str, Any]:
    return {"echo": echo, "lookup": lookup}


def builtin_paradigms() -> list[tuple[str, Any, State]]:
    """返回 (架构名, program, 初始 state)，供 demo 统一运行。"""

    skills = {
        "refund": {"description": "退款处理流程", "body": "先查订单，再走退款审批",
                   "resources": {"policy.md": "七天无理由"}},
        "general": {"description": "通用问答", "body": "直接回答", "resources": {}},
    }
    leaf_a, leaf_b = Leaf("退款已受理"), Leaf("已答复")

    cases: list[tuple[str, Any, State]] = []

    cases.append(("① Tool Use", ToolUse(), State("查订单", data={"tools": toolset()})))

    cases.append(("② ReAct", React(), State("查 A1001", data={
        "tools": toolset(),
        "script": [
            {"content": "", "tool_calls": [{"name": "lookup", "args": {"order_id": "A1001"}}]},
            {"content": "A1001 已签收"},
        ],
    })))

    cases.append(("③ Plan & Execute", PlanExecute(), State("两步任务", data={
        "tools": toolset(),
        "script": [{"plan": [{"name": "echo", "args": {"text": "step1"}},
                             {"name": "echo", "args": {"text": "step2"}}]}],
    })))

    cases.append(("④ Reflection", Reflection(), State("写代码", data={
        "tools": toolset(),
        "script": [
            {"content": "v1"}, {"verdict": "fail"},
            {"content": "v2"}, {"verdict": "pass"},
        ],
    })))

    cases.append(("⑤ Router", Router(arms={"refund": leaf_a}, fallback=leaf_b), State("我要退款", data={
        "tools": toolset(), "script": [{"route": "refund"}],
    })))

    cases.append(("⑥ Router + Skill", RouterSkill(arms={"refund": leaf_a, "general": leaf_b}), State("我要退款", data={
        "tools": toolset(), "skills": skills, "script": [{"route": "refund"}],
    })))

    cases.append(("⑦ Supervisor", Supervisor(workers={
        "research": Leaf("资料"), "write": Leaf("报告"),
    }), State("写报告", data={
        "tools": toolset(),
        "script": [{"tasks": [["research", "查资料"], ["write", "写报告"]]}],
    })))

    cases.append(("⑧ Handoff", Handoff(roles={"triage": leaf_b, "specialist": leaf_a}), State("转人工", data={
        "tools": toolset(), "script": [{"handoff": "specialist"}, {"content": " specialist 已处理"}],
    })))

    cases.append(("⑨ Blackboard", Blackboard(agents=(Leaf("发现一"), Leaf("发现二"))), State("调研", data={
        "tools": toolset(),
    })))

    cases.append(("⑩ Graph / DAG", Graph(
        nodes={
            "a": Effect("compute", {"op": "upper", "args": ["abc"]}),
            "b": Effect("compute", {"op": "concat", "args": ["x", "y"]}),
            "c": Effect("compute", {"op": "join", "args": ["1", "2"]}),
        },
        edges=(("a", "b", ""), ("b", "c", "route:ok")),
        entry="a",
    ), State("走固定流程", data={"tools": toolset(), "route": "ok"})))

    return cases


__all__ = [
    "Leaf", "ToolUse", "React", "PlanExecute", "Reflection", "Router", "RouterSkill",
    "Supervisor", "Handoff", "Blackboard", "Graph", "builtin_paradigms", "toolset",
]
