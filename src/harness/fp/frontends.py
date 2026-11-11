"""十种内置架构范式（v3 / PROPOSAL §7）—— **可删的前端库**。

这些类与用户自写架构完全同层、同一个 ``Program`` 协议：内核不认识它们，
删掉整个文件，框架照样能跑任意架构。它们不是框架算子，只是
``Decision.program`` 的取值和 ``Decision.effects`` 的数量：

    seq/branch/loop/parallel/nest/graph/backtrack 都不是框架概念
    seq      = program 换成下一个游标
    branch   = program 换成某个 arm
    loop     = program 返回自己
    parallel = effects 一批多个
    nest     = Effect(kind="child")
    graph    = transition 读图数据算下一批节点
    backtrack= program 换回历史 + restore 恢复状态
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, ClassVar

from harness.contracts.decision import Decision, Halt
from harness.contracts.state import State
from harness.contracts.types import Effect, Goal, SessionRef

__all__ = [
    "Leaf", "ToolUse", "React", "PlanExecute", "Reflection", "Router", "RouterSkill",
    "SupervisorProgram", "HandoffProgram", "BlackboardProgram", "Graph", "GraphSpec",
    "compile_graph", "program_from_spec", "builtin_paradigms", "toolset", "make_state",
]


def make_state(text: str, *, data: dict[str, Any] | None = None,
               session_id: str = "s1") -> State:
    """按现网 State 信封构造初始状态（样张用的是简化 State）。"""
    return State(
        goal=Goal(text, session_id=session_id),
        session=SessionRef(session_id),
        data=dict(data or {}),
    )


def _goal(state: State) -> str:
    goal = state.goal
    return goal if isinstance(goal, str) else str(getattr(goal, "text", goal))


def _batch(state: State) -> dict[str, Any]:
    return state.results.get("__batch__", {})


def _out(batch: dict[str, Any], key: str) -> Any:
    value = batch.get(key)
    return value.get("output") if isinstance(value, dict) else value


# ------------------------------------------------------------------ 公共叶子


@dataclass(frozen=True)
class Leaf:
    """辅助叶子：立即结束的程序（不是第 11 种架构）。"""

    name: ClassVar[str] = "leaf"
    text: str = ""

    def describe(self) -> str:
        return f"leaf({self.text})"

    def to_spec(self) -> dict[str, Any]:
        return {"kind": "leaf", "text": self.text}

    def transition(self, state: State) -> Decision | Halt:
        return Halt(self.text)


# ------------------------------------------------------------------ ① Tool Use


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
        effects = self.calls or (
            Effect("tool", args={"name": "echo", "args": {"text": "hi"}}, key="last"),
        )
        return Decision(effects=effects, program=replace(self, fired=True), note="call tool")


# ------------------------------------------------------------------ ② ReAct


@dataclass(frozen=True)
class React:
    """``program=self`` 就是循环，不需要 loop 算子。"""

    name: ClassVar[str] = "react"
    max_steps: int = 8
    step: int = 0

    def describe(self) -> str:
        return f"react(max_steps={self.max_steps})"

    def transition(self, state: State) -> Decision | Halt:
        if self.step >= self.max_steps:
            return Halt("max_steps", "degraded")
        reply = _out(_batch(state), "model")
        if reply is not None:
            calls = reply.get("tool_calls", []) if isinstance(reply, dict) else []
            if not calls:
                return Halt(str(reply.get("content", "")) if isinstance(reply, dict) else str(reply))
            call = calls[0]
            return Decision(
                effects=(Effect("tool", args={"name": call["name"],
                                              "args": call.get("args", {})}, key="tool"),),
                program=replace(self, step=self.step + 1), note="act",
            )
        return Decision(effects=(Effect("model", key="model"),), program=self, note="think")


# ------------------------------------------------------------------ ③ Plan & Execute


@dataclass(frozen=True)
class PlanExecute:
    name: ClassVar[str] = "plan_execute"
    phase: str = "plan"
    steps: tuple[dict, ...] = ()
    cursor: int = 0

    def describe(self) -> str:
        return f"plan_execute(phase={self.phase}, cursor={self.cursor})"

    def transition(self, state: State) -> Decision | Halt:
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self, note="plan")
            plan = reply.get("plan", []) if isinstance(reply, dict) else []
            return Decision(effects=(), program=replace(self, phase="exec", steps=tuple(plan)),
                            note="plan ready")
        if self.cursor >= len(self.steps):
            return Halt(str(state.data.get("last_output", "")))
        step = self.steps[self.cursor]
        return Decision(
            effects=(Effect("tool", args={"name": step["name"],
                                          "args": step.get("args", {})}, key="tool"),),
            program=replace(self, cursor=self.cursor + 1), note=f"step {self.cursor + 1}",
        )


# ------------------------------------------------------------------ ④ Reflection


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
            return Decision(effects=(), program=replace(self, phase="critic"),
                            patch={"draft": text}, note="draft ready")
        verdict = _out(batch, "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="critic")
        passed = isinstance(verdict, dict) and verdict.get("verdict") == "pass"
        if passed or self.round >= self.max_rounds:
            return Halt(str(state.data.get("draft", "")))
        return Decision(effects=(),
                        program=replace(self, phase="draft", round=self.round + 1), note="revise")


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
    """分流（目录常驻）+ 能力包（按需加载正文）+ 执行体。"""

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
                return Decision(effects=(Effect("model", key="model"),), program=self,
                                note="select skill")
            name = reply.get("route", "general") if isinstance(reply, dict) else "general"
            if name not in self.arms:
                name = "general"
            return Decision(
                effects=(Effect("skill", args={"name": name, "part": "body"}, key="body"),),
                program=replace(self, phase="dispatch", chosen=name), note=f"load {name}",
            )
        body = _out(batch, "body")
        arm = self.arms.get(self.chosen, self.fallback)
        if arm is None:
            return Halt("无匹配技能", "refused")
        return Decision(effects=(), program=arm,
                        patch={"skill": self.chosen, "skill_body": body},
                        note=f"run {self.chosen}")


# ------------------------------------------------------------------ ⑦ Supervisor


@dataclass(frozen=True)
class SupervisorProgram:
    """一批 child = 并行 fan-out，下一轮 join。"""

    name: ClassVar[str] = "supervisor"
    workers: dict[str, Any] = field(default_factory=dict)
    phase: str = "plan"

    def describe(self) -> str:
        return f"supervisor(workers={sorted(self.workers)})"

    def transition(self, state: State) -> Decision | Halt:
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self,
                                note="decompose")
            tasks = reply.get("tasks", []) if isinstance(reply, dict) else []
            effects = tuple(
                Effect("child", args={"goal": goal, "data": {}}, child=self.workers[name],
                       key=name)
                for name, goal in tasks if name in self.workers
            )
            return Decision(effects=effects, program=replace(self, phase="join"), note="fan-out")
        outputs = [str(state.results.get(name, {}).get("output", "")) for name in self.workers]
        return Halt(" | ".join(o for o in outputs if o))


# ------------------------------------------------------------------ ⑧ Handoff


@dataclass(frozen=True)
class HandoffProgram:
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
            return Decision(effects=(Effect("model", key="model"),), program=self,
                            note=f"{self.current} thinks")
        if isinstance(reply, dict) and reply.get("handoff") and self.hops < self.max_hops:
            target = reply["handoff"]
            return Decision(effects=(),
                            program=replace(self, current=target, hops=self.hops + 1),
                            patch={"last_role": self.current}, note=f"handoff -> {target}")
        text = reply.get("content", self.current) if isinstance(reply, dict) else str(reply)
        return Halt(f"{self.current}: {text}")


# ------------------------------------------------------------------ ⑨ Blackboard


@dataclass(frozen=True)
class BlackboardProgram:
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
            board = [str(state.results.get(self._key(i, a), {}).get("output", ""))
                     for i, a in enumerate(self.agents)]
            return Halt(" / ".join(v for v in board if v))
        effects = tuple(
            Effect("child", args={"goal": _goal(state), "data": {}}, child=a,
                   key=self._key(i, a))
            for i, a in enumerate(self.agents)
        )
        return Decision(effects=effects, program=replace(self, round=self.round + 1),
                        patch={"board_rev": self.round}, note="write board")


# ------------------------------------------------------------------ ⑩ Graph / DAG


@dataclass(frozen=True)
class Graph:
    """声明式前端：节点 + 条件边。纯 DAG 表达不了环 —— 环放进节点内部。"""

    name: ClassVar[str] = "graph"
    nodes: dict[str, Effect] = field(default_factory=dict)
    edges: tuple[tuple[str, str, str], ...] = ()
    entry: str = ""
    done: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"graph(entry={self.entry}, nodes={len(self.nodes)}, edges={len(self.edges)})"

    def to_spec(self) -> dict[str, Any]:
        return {"kind": "graph", "nodes": {k: asdict(v) for k, v in self.nodes.items()},
                "edges": [list(e) for e in self.edges], "entry": self.entry}

    def static_check(self) -> list[str]:
        """装配期可查：入口、悬空边、环。环必须放进节点内部或显式受控回边。"""
        problems: list[str] = []
        if self.entry not in self.nodes:
            problems.append(f"入口节点不存在：{self.entry}")
        indeg = {n: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n: [] for n in self.nodes}
        for src, dst, _when in self.edges:
            if src not in self.nodes or dst not in self.nodes:
                problems.append(f"悬空边：{src} -> {dst}")
                continue
            adj[src].append(dst)
            indeg[dst] += 1
        ready, seen = [n for n, d in indeg.items() if d == 0], 0
        while ready:
            node = ready.pop()
            seen += 1
            for nxt in adj[node]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt)
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
            return Decision(effects=(replace(self.nodes[self.entry], key=self.entry),),
                            program=replace(self, done=(self.entry,)), note="entry")
        nxt = [dst for src, dst, when in self.edges
               if src in self.done and dst not in self.done and self._ok(when, state)]
        if not nxt:
            return Halt(str(state.data.get("last_output", "")))
        return Decision(effects=tuple(replace(self.nodes[n], key=n) for n in nxt),
                        program=replace(self, done=self.done + tuple(nxt)),
                        note="-> " + ",".join(nxt))


@dataclass(frozen=True)
class GraphSpec:
    """可序列化的图形态；编译成 ``Graph.transition``，与用户自写架构同层。"""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: tuple[tuple[str, str, str], ...] = ()
    entry: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GraphSpec":
        return cls(
            nodes={k: dict(v) for k, v in raw.get("nodes", {}).items()},
            edges=tuple(tuple(e) for e in raw.get("edges", ())),
            entry=raw.get("entry", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "graph", "nodes": dict(self.nodes),
                "edges": [list(e) for e in self.edges], "entry": self.entry}


def compile_graph(spec: GraphSpec | dict[str, Any]) -> Graph:
    """声明 → 程序。``nodes`` 里每个值是 ``Effect`` 的字段字典。"""
    data = spec if isinstance(spec, dict) else spec.to_dict()
    nodes = {name: Effect(**raw) for name, raw in data.get("nodes", {}).items()}
    return Graph(nodes=nodes, edges=tuple(tuple(e) for e in data.get("edges", ())),
                 entry=data.get("entry", ""))


def program_from_spec(spec: dict[str, Any]) -> Any:
    """JSON Spec → 程序。工厂查 ``assembly.registry.PROGRAMS``，无白名单。"""
    from harness.assembly.registry import PROGRAMS
    from harness.contracts.errors import ConfigError

    data = dict(spec)
    kind = data.pop("kind", "")
    factory = PROGRAMS.get(kind)
    if factory is None:
        raise ConfigError(f"未知程序形态：{kind!r}；可用：{sorted(PROGRAMS)}")
    # 嵌套声明：arms/workers/roles/fallback/agents 里的 {"kind": ...} 递归编译
    for key in ("arms", "workers", "roles"):
        if isinstance(data.get(key), dict):
            data[key] = {k: _compile_ref(v) for k, v in data[key].items()}
    for key in ("fallback", "program", "child"):
        if key in data:
            data[key] = _compile_ref(data[key])
    for key in ("agents", "calls", "steps"):
        if isinstance(data.get(key), (list, tuple)):
            data[key] = tuple(_compile_ref(v) for v in data[key])
    return factory(**data)


def _compile_ref(value: Any) -> Any:
    return program_from_spec(value) if isinstance(value, dict) and "kind" in value else value


# ------------------------------------------------------------------ 验收夹具


async def echo(text: str = "hi") -> str:
    return f"echo:{text}"


async def lookup(order_id: str = "A1") -> dict:
    return {"order_id": order_id, "status": "已签收"}


def toolset() -> dict[str, Any]:
    return {"echo": echo, "lookup": lookup}


def builtin_paradigms() -> list[tuple[str, Any, State]]:
    """返回 (架构名, program, 初始 state)，供验收统一运行。"""
    skills = {
        "refund": {"description": "退款处理流程", "body": "先查订单，再走退款审批",
                   "resources": {"policy.md": "七天无理由"}},
        "general": {"description": "通用问答", "body": "直接回答", "resources": {}},
    }
    leaf_a, leaf_b = Leaf("退款已受理"), Leaf("已答复")
    cases: list[tuple[str, Any, State]] = []

    cases.append(("① Tool Use", ToolUse(), make_state("查订单", data={"tools": toolset()})))

    cases.append(("② ReAct", React(), make_state("查 A1001", data={
        "tools": toolset(),
        "script": [
            {"content": "", "tool_calls": [{"name": "lookup", "args": {"order_id": "A1001"}}]},
            {"content": "A1001 已签收"},
        ],
    })))

    cases.append(("③ Plan & Execute", PlanExecute(), make_state("两步任务", data={
        "tools": toolset(),
        "script": [{"plan": [{"name": "echo", "args": {"text": "step1"}},
                             {"name": "echo", "args": {"text": "step2"}}]}],
    })))

    cases.append(("④ Reflection", Reflection(), make_state("写代码", data={
        "tools": toolset(),
        "script": [
            {"content": "v1"}, {"verdict": "fail"},
            {"content": "v2"}, {"verdict": "pass"},
        ],
    })))

    cases.append(("⑤ Router", Router(arms={"refund": leaf_a}, fallback=leaf_b),
                  make_state("我要退款", data={"tools": toolset(),
                                               "script": [{"route": "refund"}]})))

    cases.append(("⑥ Router + Skill", RouterSkill(arms={"refund": leaf_a, "general": leaf_b}),
                  make_state("我要退款", data={"tools": toolset(), "skills": skills,
                                               "script": [{"route": "refund"}]})))

    cases.append(("⑦ Supervisor", SupervisorProgram(workers={
        "research": Leaf("资料"), "write": Leaf("报告"),
    }), make_state("写报告", data={"tools": toolset(),
                                    "script": [{"tasks": [["research", "查资料"],
                                                            ["write", "写报告"]]}]})))

    cases.append(("⑧ Handoff", HandoffProgram(roles={"triage": leaf_b, "specialist": leaf_a}),
                  make_state("转人工", data={
                      "tools": toolset(),
                      "script": [{"handoff": "specialist"},
                                 {"content": " specialist 已处理"}],
                  })))

    cases.append(("⑨ Blackboard", BlackboardProgram(agents=(Leaf("发现一"), Leaf("发现二"))),
                  make_state("调研", data={"tools": toolset()})))

    cases.append(("⑩ Graph / DAG", Graph(
        nodes={
            "a": Effect("compute", args={"op": "upper", "args": ["abc"]}),
            "b": Effect("compute", args={"op": "concat", "args": ["x", "y"]}),
            "c": Effect("compute", args={"op": "join", "args": ["1", "2"]}),
        },
        edges=(("a", "b", ""), ("b", "c", "route:ok")),
        entry="a",
    ), make_state("走固定流程", data={"tools": toolset(), "route": "ok"})))

    return cases


# ------------------------------------------------------------------ 自注册


def _program_factory(name: str, cls: Any):
    """把声明编译成前端实例；工厂签名兼容 ``registry.resolve``。"""

    def factory(arg: str = "", **kwargs: Any) -> Any:
        return compile_graph(kwargs) if name == "graph" else cls(**kwargs)

    return factory


def _register_frontends() -> None:
    """注册到 ``assembly.registry.PROGRAMS``（PROPOSAL §9.2）。

    前端库**自己**注册，assembly 不反向 import fp —— 分层约束不破，
    且新增一种前端只需在这里加一行。
    """
    from harness.assembly.registry import PROGRAMS, register_program

    for name, cls in {
        "leaf": Leaf,
        "graph": Graph,
        "tool_use": ToolUse,
        "react_loop": React,
        "plan_execute": PlanExecute,
        "reflection": Reflection,
        "router": Router,
        "router_skill": RouterSkill,
        "supervisor": SupervisorProgram,
        "handoff": HandoffProgram,
        "blackboard": BlackboardProgram,
    }.items():
        if name not in PROGRAMS:
            register_program(name, _program_factory(name, cls))


_register_frontends()
