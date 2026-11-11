> **历史资料，非实现依据。** 本文按框架代际（v1/v2/v3/v3.1）记录当时的设计与施工过程；
> 现行唯一权威是 `docs/harness/AUDIT-断点-重复实现-版本说法统计.md`（§6.5 完成线）与 `audit-report.json` 快照。
> 单一版本口径见根 `CHANGELOG.md`。

# 通用解释器与效应系统：agent-harness v3 方案

> 状态：提案（已带可运行样张） · **实施状态：已落地，见附录 C** · 日期：2026-11-09 · 目标版本：0.3 / contracts_version 3  
> 配套代码：`proposals/`（独立样张，不接入 `src/harness`）  
> 运行验收：`PYTHONPATH="src;." python -m proposals.demo`  
> 实测：10 种内置范式 + 4 种"框架作者没想过的架构"全部通过；带环 DAG 被装配期拦截；治理分级、dry_run、横切观测均通过。

---

## 0. 一页摘要

**框架不提供任何架构，只提供一套完备的最小执行契约与效应系统；架构是运行其上的程序。**

| 项          | 内容                                                   |
| ---------- | ---------------------------------------------------- |
| 唯一契约       | `Program.transition(state) -> Decision \| Halt`      |
| `Decision` | 一批 `Effect` + 下一个 `program` + `patch` + 可选 `restore` |
| 内核职责       | 问程序 → 批量执行效应（四段链）→ 提交状态 → 事件/检查点 → 换下一个程序            |
| 框架守什么      | 状态单一所有者、能力作用域、预算、四段链、审批、事件、检查点、**全局终止护栏**            |
| 框架不管什么     | 顺序、分支、循环、并行、回溯、图、谁持有控制权                              |
| 内置范式       | 10 种主流架构，写成一个可选前端库，与用户自写架构完全同层                       |
| 新架构        | 写一个 program（或一段声明，或一个裸函数），**框架源码 diff = 0**          |
| 准确性        | "任何架构都不需要改内核"，不是"任何架构都不需要写代码"                        |

`seq / branch / loop / parallel / nest / graph / backtrack` 都不是框架算子，只是 `Decision.program` 的取值和 `Decision.effects` 的数量。

---

## 1. 为什么改：现状诊断

### 1.1 两条线并存

|     | v1 线                                        | v2 线                                            |
| --- | ------------------------------------------- | ----------------------------------------------- |
| 入口  | `assembly/build.py` → `Agent`               | `assembly/config.py` → `Harness` → `fp.Program` |
| 循环  | `assembly/agent.py:169` `Agent._loop_inner` | `kernel/loop.py:52` `run_loop`                  |
| 上下文 | `RunContext`（服务定位器）                         | `RunScope`（冻结 dataclass）                        |
| 策略  | `parts/body/*` 三种                           | `parts/policy/*` 三种                             |
| 执行  | `parts/actor.py`                            | `parts/actor_v2.py`                             |
| 拓扑  | `parts/topology.py` 四个硬编码类                  | `fp` 的组合子（只覆盖横切）                                |
| 对外  | **`__init__.py` 公开导出的是这一条**                 | 需单独 import                                      |

`parts/topology.py:12` 的 `_call` 用 `try/except TypeError` 兼容两种 `run()` 签名，是"组合不闭合"的直接证据。

### 1.2 架构假设泄漏进了内核契约

- `kernel/loop.py:52`：`while ... next_step → 四段 → step_index+1`，假设"一次运行 = 一串 Step"。
- `BodyPolicy.next_step() -> Step | Done`（`contracts/protocols/body.py`）：把这个假设写成了内核协议。
- `Runnable.run(goal, *, scope) -> RunResult`（`contracts/protocols/runtime.py`）：假设"一个 Goal 进、一个 Answer 出"。
- `chain.POINTS = ("run","step","model_call","tool_call")`、`Program = body + layers`：同一批假设。

合起来，现有框架是"**一个 ReAct 循环 + 可换皮肤**"，不是任意架构的运行时。上一版方案（组合子 + DAG 声明）把四个硬编码拓扑类换成六个硬编码算子，**没有拆掉这些假设**，遇到没想过的控制语义仍要改框架。

### 1.3 后果

1. 任何架构都要压扁成"单循环里的一步一步"；控制流图没有一等表示。
2. 拓扑类绕过四段链/护栏/预算，`_merge_usage` 在四个类里各写一遍 → 换架构就丢治理。
3. 治理能力要在两个循环里各实现一遍。
4. 公开 API 倒挂：能力更全的 v2 反而不是默认入口。

---

## 2. 设计目标与边界

### 2.1 目标

- 任何架构都**不改内核、不改已有拓扑类**。新组合只写声明；新能力只加适配器；新架构由用户写自己的 `program`。
- **解释器唯一**：`interpret()` 是唯一循环；v1 删实现留兼容壳，v2 删循环留效应系统。
- 治理统一：所有 I/O 必须表达成 `Effect`，经四段链执行 —— 这是全架构共用一套治理的前提。
- 保留现有资产：组件库、Layer / Middleware / Hook / Guard / Pipe / Filter、护栏、后端、存储、工具、技能全部不删。

### 2.2 边界（明确不承诺）

- 不承诺"任何架构都可静态检查"。控制流是不透明代码时，静态校验、可视化、序列化、时间旅行会降级（见 §4.4）。
- 不承诺"零代码"。写新架构本身就是写程序；保证的是 diff 落在用户代码里，不在框架源码里。
- 若新东西要求改变**运行时不变量**（多状态所有者、新的失败语义、跨运行因果一致性），那是**新运行时**，不是新架构。承认边界不是失败。
- 纯 DAG 不承诺表达环。环放在节点内部或显式受控回边（见 §7.10）。

### 2.3 验收判据

> 让框架作者没想过的架构，在框架源码 diff = 0 的前提下跑起来，且控制流完全定义在框架之外。

三个测试用例见 §8：回溯搜索、运行时自改写控制流、控制权交给外部系统。

---

## 3. 总体分层

```
架构前端（框架之外，是输入 / 程序）
   内置组合子标准库  ·  用户自定义架构  ·  未来未知架构          ← 三者同层同接口
                              ↓ 编译 / 直接实现
唯一契约   transition(state) -> Decision | Halt
                              ↓
通用程序   Program = (State, Transition, Effects)               ← 唯一的框架契约
                              ↓
内核解释器  transition → 批量效应 → 提交状态 → 事件/检查点 → 换 program，直到 Halt
                              ↓
效应系统  四段链 · RunScope · Budget · 审批 · 事件 · 检查点 · 沙箱   ← 稳定不变量
```

一次循环的语义：

```
program = 初始程序
while True:
    d = program.transition(state)          # 架构在这里，框架不问
    if d is Halt: return RunResult
    results = execute_effects(d.effects)   # 批量 → 每个走 Gate/Check/Wrap/Classify
    commit(state, d.patch, results)        # 唯一提交点
    emit(state); checkpoint(state, program)
    program = d.program or program         # 自己=循环 / 历史=回溯 / 新组合=动态改图
```

| 上一版的"算子"       | 在这个模型里其实是什么                     |
| -------------- | ------------------------------- |
| `seq`          | `program` 换成下一个游标               |
| `branch`       | `program` 换成某个 arm              |
| `loop`         | `program` 返回自己                  |
| `parallel`     | `effects` 一批多个                  |
| `nest`         | `Effect(kind="child")`          |
| `graph`        | `transition` 读图数据算下一批节点         |
| `backtrack`（新） | `program` 换回历史 + `restore` 恢复状态 |

---

## 4. 核心契约（完整代码）

> 完整可运行版本：`proposals/contracts.py`。下面代码与该文件一致，仅省略模块 docstring 与 `__all__`。

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

@dataclass
class State:
    """唯一可变状态。单一所有者：只有解释器的 commit 能写它。"""
    goal: str
    data: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    rev: int = 0
    journal: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """只备份可回滚的业务状态。

        journal（观测/消费进度）与 usage（计量）是既成事实，不随回溯回滚 ——
        否则回溯会把"已经问过模型"这件事也撤销，评估脚本会被重复消费。
        """
        import copy
        return copy.deepcopy(
            {"goal": self.goal, "data": self.data, "results": self.results, "rev": self.rev}
        )

    def restore(self, snap: dict[str, Any]) -> None:
        import copy
        self.goal = snap["goal"]
        self.data = copy.deepcopy(snap["data"])
        self.results = copy.deepcopy(snap["results"])
        self.rev = snap["rev"]


@dataclass(frozen=True)
class Effect:
    """一个效应请求：想对外部世界做的一件事，不是立刻做。kind 可扩展。"""
    kind: str
    spec: dict[str, Any] = field(default_factory=dict)
    key: str = ""


@dataclass(frozen=True)
class Decision:
    effects: tuple[Effect, ...] = ()       # 一批：0 个 = 纯决策步，多个 = 并行
    program: Any = None                    # 下一个程序；None = 保持当前
    patch: dict[str, Any] = field(default_factory=dict)
    restore: dict[str, Any] | None = None # 回溯：先恢复历史状态再执行
    note: str = ""


@dataclass(frozen=True)
class Halt:
    answer: str = ""
    status: str = "completed"


@runtime_checkable
class Program(Protocol):
    name: str
    def transition(self, state: State) -> Decision | Halt: ...


class FnProgram:
    """零封装入口：把一个裸函数变成 Program。"""
    def __init__(self, fn: Callable[[State], Decision | Halt], name: str = "fn") -> None:
        self.fn = fn
        self.name = name

    def transition(self, state: State) -> Decision | Halt:
        return self.fn(state)


def capabilities(program: Any) -> dict[str, bool]:
    """治理分级：程序声明自己支持哪些静态能力，缺省即降级。"""
    return {name: callable(getattr(program, name, None))
            for name in ("describe", "to_spec", "static_check")}


def describe(program: Any) -> str:
    fn = getattr(program, "describe", None)
    return fn() if callable(fn) else f"<opaque:{getattr(program, 'name', type(program).__name__)}>"


def to_spec(program: Any) -> dict[str, Any]:
    fn = getattr(program, "to_spec", None)
    if not callable(fn):
        raise TypeError("NotSerializable: 闭包程序不提供 to_spec()")
    return fn()


# ---- 横切：Layer / Hook 全部保留，插点可扩展 ----
def _allow(effect, state) -> str: return "allow"
def _noop_check(effect, state) -> None: return None
def _identity_wrap(effect, nxt): return nxt
def _noop_observe(effect, result, state) -> None: return None

@dataclass
class Layer:
    """gate=Gate, check=Check, wrap=Wrap, observe=Hook。

    与现有 harness 的 Layer/Middleware/Hook 协议一一对应。
    """
    name: str
    gate: Callable[[Effect, State], str] = _allow
    check: Callable[[Effect, State], None] = _noop_check
    wrap: Callable[[Effect, Callable], Callable] = _identity_wrap
    observe: Callable[[Effect, Any, State], None] = _noop_observe
```

### 4.1 关键设计点

- **`transition` 是纯同步函数**：只读 `State`，所有 I/O 表达成 `Effect`。这是治理能统一、程序可回放的前提。需要外部信息时发 `Effect(kind="model"/"wait"/"ask")`，结果写回 state，下一轮再读。
- **`effects` 是一批**：并行不需要算子。
- **`program` 是返回值**：循环/分支/回溯/动态改图不需要算子。
- **`patch` 是显式增量**：状态单一所有者、可检查点、可回放。
- **回滚粒度**：`State` 分两区 —— 可回滚的业务状态（`data/results/rev`）与不可回滚的观测计量（`journal/usage`）。样张第一次运行时正是踩了这个坑：回溯把模型脚本的消费进度一起撤销，导致第二分支重复读到同一 verdict。修正后 14 个案例全绿。

### 4.2 治理分级

程序可选实现 `describe() / to_spec() / static_check()`。数据化前端（`Graph` / JSON Spec）全支持；闭包/含对象引用的程序只保证能跑，`to_spec()` 抛 `NotSerializable`。框架**保证任何程序都能跑，不保证任何程序都可检查**，装配期 `validate()` 能查的都查、查不了的明确降级。

---


## 5. 唯一解释器（完整代码）

> 完整可运行版本：`proposals/interpreter.py`。下面为核心实现（保留全部逻辑）。

```python
import asyncio, copy, inspect
from dataclasses import dataclass, field
from typing import Any, Callable
from proposals.contracts import Decision, Effect, Halt, Layer, State, describe, to_spec

class ValidationFailed(Exception): pass

@dataclass
class Limits:
    """框架新增的唯一不变量：任何程序都必须能停下来。"""
    max_transitions: int = 64
    max_calls: int = 100
    max_tokens: int = 200_000

@dataclass
class Outcome:
    answer: str
    status: str
    transitions: int
    usage: dict[str, int]
    checkpoints: int
    trace: list[str] = field(default_factory=list)

class Runtime:
    """效应运行时。handlers 可扩展：新增 kind 只需注册一个函数。"""
    def __init__(self, *, layers=(), limits=None, record_only=False, extra_handlers=None):
        self.layers, self.record_only = tuple(layers), record_only
        self.limits = limits or Limits()
        self.checkpoints: list[dict] = []
        self.handlers = {
            "model": self._model, "tool": self._tool, "skill": self._skill,
            "ask": self._ask, "wait": self._wait, "compute": self._compute,
            "child": self._child,
        }
        self.handlers.update(extra_handlers or {})

    @staticmethod
    def validate(program) -> list[str]:
        problems = []
        if not hasattr(program, "transition"):
            problems.append("程序缺少 transition()")
        check = getattr(program, "static_check", None)
        if callable(check):
            problems.extend(check())
        return problems

    async def interpret(self, program, state: State) -> Outcome:
        problems = self.validate(program)
        if problems:
            raise ValidationFailed("; ".join(problems))
        trace = [f"run.start:{describe(program)}"]
        n = 0
        while True:
            if n >= self.limits.max_transitions:
                return self._finish(state, Halt("max_transitions", "degraded"), n, trace)
            if state.usage["calls"] >= self.limits.max_calls:
                return self._finish(state, Halt("max_calls", "degraded"), n, trace)

            decision = program.transition(state)
            if isinstance(decision, Halt):
                return self._finish(state, decision, n, trace)
            if not isinstance(decision, Decision):
                raise TypeError(f"transition 必须返回 Decision | Halt，收到 {type(decision)!r}")

            if decision.restore is not None:
                state.restore(decision.restore)
            results = await asyncio.gather(
                *(self._stages(effect, state) for effect in decision.effects)
            )
            self._commit(state, decision, results)
            spec = "<opaque>"
            try:
                spec = to_spec(program)
            except TypeError:
                pass
            self.checkpoints.append({"rev": state.rev, "program": spec})
            trace.append(
                f"{n}:{program.name}:[{','.join(e.kind for e in decision.effects) or 'pure'}]"
                + (f":{decision.note}" if decision.note else "")
            )
            program = decision.program if decision.program is not None else program
            n += 1

    def _finish(self, state, halt, n, trace) -> Outcome:
        trace.append(f"run.end:{halt.status}")
        return Outcome(halt.answer, halt.status, n, dict(state.usage),
                       len(self.checkpoints), trace)

    # ---- 四段链：Gate / Check / Wrap / Classify，语义与 kernel/stage.py 一致 ----
    async def _stages(self, effect: Effect, state: State) -> Any:
        terminal = self._terminal
        for layer in self.layers:                       # ① Gate，不抛异常可短路
            verdict = layer.gate(effect, state)
            if verdict == "deny":
                return {"ok": False, "error": f"gate:{layer.name}"}
            if verdict == "ask":
                return {"ok": False, "error": f"approval:{layer.name}"}
        try:                                            # ② Check
            for layer in self.layers:
                layer.check(effect, state)
        except Exception as exc:
            return {"ok": False, "error": f"invalid:{exc}"}
        handler = terminal                              # ③ Wrap
        for layer in reversed(self.layers):
            handler = layer.wrap(effect, handler)
        try:                                            # ④ Classify
            result = await handler(effect, state)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
        for layer in self.layers:                       # Hook：只读观察，异常吞掉
            try:
                layer.observe(effect, result, state)
            except Exception:
                pass
        return result

    async def _terminal(self, effect, state):
        state.usage["calls"] += 1
        if effect.kind == "model":
            state.usage["tokens"] += 10
        if self.record_only:                            # dry_run：只记账不执行
            return {"ok": True, "output": f"[dry-run:{effect.kind}]"}
        handler = self.handlers.get(effect.kind)
        if handler is None:
            raise KeyError(f"未注册的效应类型：{effect.kind}")
        out = handler(effect, state)
        return await out if inspect.isawaitable(out) else out

    @staticmethod
    def _commit(state, decision, results) -> None:
        batch = {}
        for effect, result in zip(decision.effects, results):
            key = effect.key or "last"
            state.results[key] = result
            batch[key] = result
            if isinstance(result, dict) and "output" in result:
                state.data["last_output"] = result["output"]
            elif isinstance(result, str):
                state.data["last_output"] = result
        state.results["__batch__"] = batch             # 每轮覆盖，程序只读"本批新结果"
        state.data.update(decision.patch)
        state.rev += 1

    # ---- 内置效应处理器（可扩展）----
    async def _model(self, effect, state):
        script = state.data.get("script", [])
        cursor = int(state.journal.get("cursor", 0))
        reply = script[cursor] if cursor < len(script) else {"content": "done"}
        state.journal["cursor"] = cursor + 1
        return {"ok": True, "output": reply}

    async def _tool(self, effect, state):
        fn = state.data["tools"][effect.spec["name"]]
        out = fn(**effect.spec.get("args", {}))
        out = await out if inspect.isawaitable(out) else out
        return {"ok": True, "output": out}

    async def _skill(self, effect, state):
        """渐进披露三段：catalog 常驻 / body 按需 / resource 按需。"""
        catalog, name = state.data.get("skills", {}), effect.spec["name"]
        part = effect.spec.get("part", "body")
        if part == "catalog":
            out = {k: v.get("description", "") for k, v in catalog.items()}
        elif part == "resource":
            out = catalog[name]["resources"].get(effect.spec["path"], "")
        else:
            out = catalog[name].get("body", "")
        return {"ok": True, "output": out}

    async def _ask(self, effect, state):
        return {"ok": True, "output": {"approved": True}}

    async def _wait(self, effect, state):
        queue = state.data["external_queue"]           # 控制权交给外部系统
        return {"ok": True, "output": await queue.get()}

    async def _compute(self, effect, state):
        op, args = effect.spec.get("op"), effect.spec.get("args", [])
        out = {"concat": lambda: "".join(map(str, args)),
               "upper": lambda: str(args[0]).upper(),
               "sum": lambda: sum(args),
               "join": lambda: " | ".join(map(str, args))}[op]()
        return {"ok": True, "output": out}

    async def _child(self, effect, state):
        child_state = State(goal=effect.spec.get("goal", state.goal),
                            data=copy.deepcopy(effect.spec.get("data", {})))
        out = await self.interpret(effect.spec["program"], child_state)
        return {"ok": out.status in ("completed", "degraded"), "output": out.answer}
```

### 5.1 全局终止护栏（框架新增的唯一不变量）

现在 `max_steps` 分散在 `program.max_steps`、`Agent.max_steps`、`body/react.py`。新程序可以无限返回自己或 `effects=()` 空转，因此 `interpret` 必须有 `max_transitions + Budget + 墙钟` 上限，配置放 `HarnessConfig`。这是框架"不管控制流，但仍要保证能停下"的边界。

### 5.2 检查点与 dry_run

- 检查点保存 `(state.snapshot(), program_spec)`；闭包程序写为 `<opaque>`，不支持时间旅行，与现有 `NotSerializable` 边界一致。
- `dry_run` 就是 `record_only=True` 的 `execute_effects`：四段链照走，终端只记账。

---

## 6. 运行时不变量（框架守什么）

| 不变量     | 现有对应物                                 | 变化                                       |
| ------- | ------------------------------------- | ---------------------------------------- |
| 状态单一所有者 | `State` + `rev`                       | 新增唯一 `commit` 提交点；`journal/usage` 不随回溯回滚 |
| 能力作用域   | `RunScope` + `child()`                | 原样，用于批量效应                                |
| 预算与终止   | `Budget` + `max_steps`                | 分散的上限收拢为 `Limits` 全局护栏                   |
| 动作准入    | `stage.py` 四段链                        | **一行不改**，用 `Effect→Step` 薄适配器喂入          |
| 内容护栏    | `parts/guardrail/*`                   | 原样                                       |
| 观测      | `RunEvent` + `EventSink`              | 原样，新增 `transition/effect/commit/node` 事件 |
| 审批与恢复   | `ApprovalChannel` / `CheckpointStore` | 原样                                       |
| 失败归类    | `Filter.classify`                     | 原样                                       |

|                       |     |       |                              |       |       |                                                                            |
| --------------------- | --- | ----- | ---------------------------- | ----- | ----- | -------------------------------------------------------------------------- |
| `Step.kind` 已是 \`tool | llm | agent | human`，与 `Effect.kind = tool | model | child | ask` 几乎一一对应，所以四段链泛化用薄适配器即可，**`stage.py`/`guards.py`/`runtime.py\` 零改动\*\*。 |

---

## 7. 十种内置架构范式（完整封装代码）

> 目标位置：`src/harness/fp/frontends.py`。样张：`proposals/paradigms.py`。  
> 这十个类与用户自写架构**完全同层、同一个 `Program` 协议**；内核不认识它们，删掉整个文件框架照样跑任意架构。

### 7.0 公共辅助与叶子

```python
from dataclasses import asdict, dataclass, field, replace
from typing import Any, ClassVar
from proposals.contracts import Decision, Effect, Halt, State

def _batch(state): return state.results.get("__batch__", {})
def _out(batch, key):
    value = batch.get(key)
    return value.get("output") if isinstance(value, dict) else value

@dataclass(frozen=True)
class Leaf:
    """辅助叶子：立即结束的程序（不是第 11 种架构）。"""
    name: ClassVar[str] = "leaf"
    text: str = ""
    def describe(self): return f"leaf({self.text})"
    def to_spec(self): return {"kind": "leaf", "text": self.text}
    def transition(self, state): return Halt(self.text)
```

### 7.1 单 Agent + 工具（Tool Use）

```python
@dataclass(frozen=True)
class ToolUse:
    name: ClassVar[str] = "tool_use"
    calls: tuple[Effect, ...] = ()
    fired: bool = False
    def describe(self): return f"tool_use({len(self.calls) or 1} calls)"
    def transition(self, state):
        if self.fired:
            return Halt(str(state.data.get("last_output", "")))
        effects = self.calls or (Effect("tool", {"name": "echo", "args": {"text": "hi"}}, key="last"),)
        return Decision(effects=effects, program=replace(self, fired=True), note="call tool")
```

### 7.2 ReAct（`program=self` 就是循环）

```python
@dataclass(frozen=True)
class React:
    name: ClassVar[str] = "react"
    max_steps: int = 8
    step: int = 0
    def describe(self): return f"react(max_steps={self.max_steps})"
    def transition(self, state):
        if self.step >= self.max_steps:
            return Halt("max_steps", "degraded")
        reply = _out(_batch(state), "model")
        if reply is not None:
            calls = reply.get("tool_calls", []) if isinstance(reply, dict) else []
            if not calls:
                return Halt(str(reply.get("content", "")) if isinstance(reply, dict) else str(reply))
            call = calls[0]
            return Decision(
                effects=(Effect("tool", {"name": call["name"], "args": call.get("args", {})}, key="tool"),),
                program=replace(self, step=self.step + 1), note="act")
        return Decision(effects=(Effect("model", key="model"),), program=self, note="think")
```

### 7.3 Plan & Execute（计划 → 游标执行）

```python
@dataclass(frozen=True)
class PlanExecute:
    name: ClassVar[str] = "plan_execute"
    phase: str = "plan"
    steps: tuple[dict, ...] = ()
    cursor: int = 0
    def describe(self): return f"plan_execute(phase={self.phase}, cursor={self.cursor})"
    def transition(self, state):
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
            effects=(Effect("tool", {"name": step["name"], "args": step.get("args", {})}, key="tool"),),
            program=replace(self, cursor=self.cursor + 1), note=f"step {self.cursor + 1}")
```

### 7.4 Reflection / Evaluator-Optimizer（生成者 + 评估者）

```python
@dataclass(frozen=True)
class Reflection:
    name: ClassVar[str] = "reflection"
    phase: str = "draft"
    round: int = 0
    max_rounds: int = 3
    def describe(self): return f"reflection(round={self.round})"
    def transition(self, state):
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
```

### 7.5 Router（一次分类，交由一个专家）

```python
@dataclass(frozen=True)
class Router:
    name: ClassVar[str] = "router"
    arms: dict[str, Any] = field(default_factory=dict)
    fallback: Any = None
    phase: str = "route"
    def describe(self): return f"router(arms={sorted(self.arms)})"
    def transition(self, state):
        reply = _out(_batch(state), "model")
        if reply is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="classify")
        name = reply.get("route", "general") if isinstance(reply, dict) else "general"
        arm = self.arms.get(name, self.fallback)
        if arm is None:
            return Halt(f"无匹配 arm：{name}", "refused")
        return Decision(effects=(), program=arm, patch={"route": name}, note=f"-> {name}")
```

### 7.6 Router + Skill（路由选中能力包 + 渐进披露）

```python
@dataclass(frozen=True)
class RouterSkill:
    """分流（目录常驻）+ 能力包（按需加载正文）+ 执行体。"""
    name: ClassVar[str] = "router_skill"
    arms: dict[str, Any] = field(default_factory=dict)
    fallback: Any = None
    phase: str = "route"
    chosen: str = ""
    def describe(self): return f"router_skill(arms={sorted(self.arms)})"
    def transition(self, state):
        batch = _batch(state)
        if self.phase == "route":
            reply = _out(batch, "model")
            if reply is None:
                # 目录（第 ① 段）常驻 state.data["skills"]，由取景器注入；这里只做选路
                return Decision(effects=(Effect("model", key="model"),), program=self,
                                note="select skill")
            name = reply.get("route", "general") if isinstance(reply, dict) else "general"
            if name not in self.arms:
                name = "general"
            return Decision(
                effects=(Effect("skill", {"name": name, "part": "body"}, key="body"),),
                program=replace(self, phase="dispatch", chosen=name), note=f"load {name}")
        body = _out(batch, "body")
        arm = self.arms.get(self.chosen, self.fallback)
        if arm is None:
            return Halt("无匹配技能", "refused")
        return Decision(effects=(), program=arm,
                        patch={"skill": self.chosen, "skill_body": body},
                        note=f"run {self.chosen}")
```

### 7.7 Supervisor / Orchestrator-Worker（一批 child = 并行）

```python
@dataclass(frozen=True)
class Supervisor:
    name: ClassVar[str] = "supervisor"
    workers: dict[str, Any] = field(default_factory=dict)
    phase: str = "plan"
    def describe(self): return f"supervisor(workers={sorted(self.workers)})"
    def transition(self, state):
        if self.phase == "plan":
            reply = _out(_batch(state), "model")
            if reply is None:
                return Decision(effects=(Effect("model", key="model"),), program=self,
                                note="decompose")
            tasks = reply.get("tasks", []) if isinstance(reply, dict) else []
            # 生产实现里 child 携带具名 program_ref；样张直接带 Program 对象以便运行
            effects = tuple(
                Effect("child", {"program": self.workers[name], "goal": goal, "data": {}}, key=name)
                for name, goal in tasks if name in self.workers)
            return Decision(effects=effects, program=replace(self, phase="join"), note="fan-out")
        outputs = [str(state.results.get(name, {}).get("output", "")) for name in self.workers]
        return Halt(" | ".join(o for o in outputs if o))
```

### 7.8 Handoff / Swarm（控制权在角色间交接）

```python
@dataclass(frozen=True)
class Handoff:
    name: ClassVar[str] = "handoff"
    roles: dict[str, Any] = field(default_factory=dict)
    current: str = "triage"
    hops: int = 0
    max_hops: int = 6
    def describe(self): return f"handoff(current={self.current})"
    def transition(self, state):
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
```

### 7.9 Blackboard（共享证据 + 循环汇聚）

```python
@dataclass(frozen=True)
class Blackboard:
    name: ClassVar[str] = "blackboard"
    agents: tuple[Any, ...] = ()
    max_rounds: int = 2
    round: int = 0
    def describe(self):
        return f"blackboard(agents={len(self.agents)}, rounds={self.max_rounds})"
    @staticmethod
    def _key(index, agent): return f"{agent.name}-{index}"
    def transition(self, state):
        if self.round >= self.max_rounds:
            board = [str(state.results.get(self._key(i, a), {}).get("output", ""))
                     for i, a in enumerate(self.agents)]
            return Halt(" / ".join(v for v in board if v))
        effects = tuple(
            Effect("child", {"program": a, "goal": state.goal, "data": {}}, key=self._key(i, a))
            for i, a in enumerate(self.agents))
        return Decision(effects=effects, program=replace(self, round=self.round + 1),
                        patch={"board_rev": self.round}, note="write board")
```

### 7.10 Graph / Workflow（DAG 前端，可静态校验可序列化）

```python
@dataclass(frozen=True)
class Graph:
    """声明式前端：节点 + 条件边。纯 DAG 表达不了环 —— 环放进节点内部。"""
    name: ClassVar[str] = "graph"
    nodes: dict[str, Effect] = field(default_factory=dict)
    edges: tuple[tuple[str, str, str], ...] = ()
    entry: str = ""
    done: tuple[str, ...] = ()
    def describe(self):
        return f"graph(entry={self.entry}, nodes={len(self.nodes)}, edges={len(self.edges)})"
    def to_spec(self):
        return {"kind": "graph", "nodes": {k: asdict(v) for k, v in self.nodes.items()},
                "edges": [list(e) for e in self.edges], "entry": self.entry}
    def static_check(self):
        problems = []
        if self.entry not in self.nodes:
            problems.append(f"入口节点不存在：{self.entry}")
        indeg = {n: 0 for n in self.nodes}
        adj = {n: [] for n in self.nodes}
        for src, dst, _when in self.edges:
            if src not in self.nodes or dst not in self.nodes:
                problems.append(f"悬空边：{src} -> {dst}")
                continue
            adj[src].append(dst)
            indeg[dst] += 1
        ready, seen = [n for n, d in indeg.items() if d == 0], 0
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
    def _ok(when, state):
        if not when: return True
        if when.startswith("route:"):
            return state.data.get("route") == when.split(":", 1)[1]
        return True
    def transition(self, state):
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
```

### 7.11 十种范式对照

| 架构               | 关键 `Decision`                     | 是否入 DAG          |
| ---------------- | --------------------------------- | ---------------- |
| Tool Use         | 一批 tool → Halt                    | 单节点              |
| ReAct            | `program=self` 循环，model/tool 交替   | 环在 loop 节点内      |
| Plan & Execute   | 切 phase + 游标                      | 环在节点内            |
| Reflection       | 切 phase + max_rounds              | 受控回边             |
| Router           | `program=arm`                     | 条件边              |
| Router + Skill   | `program=arm` + `Effect("skill")` | 条件边 + 能力节点       |
| Supervisor       | 一批 `child` + join                 | fan-out / fan-in |
| Handoff          | `program=目标角色`                    | 条件边              |
| Blackboard       | 循环一批 child + reducer              | 汇聚节点             |
| Graph / Workflow | `GraphSpec` 编译成 transition        | 原生               |

---

## 8. 使用其他架构的范式（完整代码示例）

> 完整可运行版本：`proposals/custom.py`。  
> 这四个架构都是**框架作者没想过的**，全部只写在用户侧，`contracts.py` / `interpreter.py` 一行不改。

### 8.1 Backtrack：回溯搜索（ToT / LATS）

```python
@dataclass(frozen=True)
class Backtrack:
    """试一个分支 → 评估 → 不合格就恢复快照、换下一分支。"""
    name: ClassVar[str] = "backtrack"
    branches: tuple[str, ...] = ("alpha", "beta", "gamma")
    snapshots: tuple[dict, ...] = ()
    index: int = 0
    phase: str = "try"
    def describe(self): return f"backtrack(branch={self.index}, phase={self.phase})"
    def transition(self, state):
        if self.phase == "try":
            if self.index >= len(self.branches):
                return Halt("所有分支均失败", "failed")
            snap = state.snapshot()
            branch = self.branches[self.index]
            return Decision(
                effects=(Effect("compute", {"op": "upper", "args": [branch]}, key="candidate"),),
                program=replace(self, phase="evaluate", snapshots=self.snapshots + (snap,)),
                note=f"try {branch}")
        verdict = _out(_batch(state), "model")
        if verdict is None:
            return Decision(effects=(Effect("model", key="model"),), program=self, note="evaluate")
        candidate = state.results.get("candidate", {}).get("output", "")
        if isinstance(verdict, dict) and verdict.get("verdict") == "pass":
            return Halt(str(candidate))
        return Decision(effects=(),
                        program=replace(self, index=self.index + 1, phase="try"),
                        restore=self.snapshots[-1], note="backtrack")
```

### 8.2 SelfModifying：运行时自改写控制流

```python
@dataclass(frozen=True)
class SelfModifying:
    name: ClassVar[str] = "self_modifying"
    remaining: tuple[str, ...] = ("n1", "n2", "n3")
    generation: int = 0
    def describe(self):
        return f"self_modifying(gen={self.generation}, remaining={len(self.remaining)})"
    def transition(self, state):
        if not self.remaining:
            return Halt(f"动态图执行完毕（共 {self.generation} 代）")
        head, *tail = list(self.remaining)
        if state.data.get("promote") == head:
            tail = list(reversed(tail))          # 运行时重排剩余控制流
        nxt = replace(self, remaining=tuple(tail), generation=self.generation + 1)
        return Decision(effects=(Effect("compute", {"op": "upper", "args": [head]}, key="last"),),
                        program=nxt, patch={"last_node": head},
                        note=f"gen{self.generation}:{head}")
```

### 8.3 ExternalControl：控制权交给外部系统

```python
@dataclass(frozen=True)
class ExternalControl:
    """程序只发 wait 效应，外部队列给什么指令就做什么。"""
    name: ClassVar[str] = "external_control"
    hops: int = 0
    def describe(self): return f"external_control(hops={self.hops})"
    def transition(self, state):
        command = _out(_batch(state), "cmd")
        if command is None:
            return Decision(effects=(Effect("wait", key="cmd"),), program=self,
                            note="await external")
        if command == "stop":
            return Halt(f"外部系统叫停（执行了 {self.hops} 条指令）")
        return Decision(
            effects=(Effect("compute", {"op": "upper", "args": [str(command)]}, key="last"),),
            program=replace(self, hops=self.hops + 1), note=f"follow {command}")
```

### 8.4 BareFunction：零封装，一个函数就是架构

```python
def bare_transition(state):
    return Decision(
        effects=(Effect("compute", {"op": "concat", "args": ["裸", "函数"]}, key="last"),),
        program=FnProgram(lambda s: Halt(str(s.data.get("last_output", ""))), name="bare_end"),
        note="零封装")

program = FnProgram(bare_transition, name="bare")
await Runtime().interpret(program, State("裸函数"))
```

### 8.5 用户侧的三种情形

1. **只写声明**：用现成前端（组合子 / JSON Spec / GraphSpec）拼出新架构，零框架代码。
2. **写一个 `transition`**：框架源码一行不动，用户写的是架构本身，不是给框架打补丁。
3. **不封装**：闭包/裸函数直接当 program，框架照跑，只是失去静态校验与序列化（治理分级里明确降级）。

---

## 9. 新增 / 修改 / 删除清单

### 9.1 新增文件

| 文件                                                                         | 内容                                                          | 约   |
| -------------------------------------------------------------------------- | ----------------------------------------------------------- | --- |
| `contracts/decision.py`                                                    | `Decision` / `Halt` / `Program` 协议                          | 80  |
| `kernel/interpret.py`                                                      | `interpret()` 循环、`Limits` 全局护栏、提交与检查点                       | 150 |
| `kernel/effects.py`                                                        | `execute_effects()`：Effect→Step 适配、并发、幂等键、`record_only`     | 120 |
| `fp/frontends.py`                                                          | §7 的十种范式 + JSON Spec / GraphSpec 编译成 `transition`           | 400 |
| `examples/interpret_minimal.py`、`unknown_architectures.py`                 | §8 示例                                                       | 150 |
| `tests/test_interpret.py`、`test_unknown_architectures.py`、`test_compat.py` | 验收                                                          | 200 |
| `proposals/`（本次已产出）                                                        | 独立可运行样张：contracts / interpreter / paradigms / custom / demo | 700 |

### 9.2 修改文件（8 个，合计约 150 行）

| 文件                                                      | 改动                                                                          | 兼容策略                                          |
| ------------------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------- |
| `contracts/types.py:531`                                | `Effect` 加 `key` / `args` / `child`，`kind` 放宽到 4 种，全部带默认值                   | 适用文件头"只增不改"纪律；`dry_run` 与 `test_fp.py:169` 不破 |
| `contracts/protocols/__init__.py`、`contracts/errors.py` | 导出 `Program` 协议；加 `DecisionError/EffectError`                               | 纯新增                                           |
| `kernel/chain.py:12`                                    | `POINTS` 改可扩展集合，加 `effect/commit/transition/node`                           | 旧四点保留                                         |
| `assembly/config.py:200`                                | `validate_layers` 遍历新插点；`HarnessConfig` 加 `max_transitions`                 | 默认值，旧配置不破                                     |
| `assembly/harness.py:69`                                | `run()` 改调 `interpret()`；`dry_run()` 复用 `record_only`                       | 签名不变，`astream` 不变                             |
| `assembly/registry.py`                                  | 新增 `PROGRAMS` 表（具名注册前端程序）                                                   | 纯新增                                           |
| `fp/__init__.py`                                        | 给 dataclass `Program` 加 `transition()`；`from_spec` 白名单改走 `registry.resolve` | 鸭子类型让旧类直接满足新协议，**不重命名**                       |
| `__init__.py`                                           | 顶层新增导出 `Decision/Halt/interpret`，保留全部旧导出                                    | 纯新增；不导出 `Program` 协议以免与 `fp.Program` 混淆       |

### 9.3 删除内容

**（a）删除运行时与重复实现（收敛双轨）**

- `assembly/agent.py` 的 `_loop_inner / _prepare / resume` 循环体（`Agent` 名字留作兼容壳）；
- `kernel/loop.py` 的 `run_loop` 循环体（降为 React 前端）；
- `BodyPolicy.next_step` 作为内核契约的地位；`topology._call` 的 `try/except TypeError` 双签名兜底；
- `fp.from_spec` 的白名单、`POINTS` 写死四元组（旧四点仍保留）；
- 双份重复类型：`RunContext` / `TraceEvent` / 第二份 `Budget`；
- v1 组件约 18 文件 862 行清空或改写，能力 100% 有对应物（见 §9.4）。

**（b）删除副线教程文章（卷 12，48–53）**

| 文件                           | 大小       |
| ---------------------------- | -------- |
| `48-为什么要封装-以及封装的边界在哪.md`     | 39,910 B |
| `49-契约先行-十二个数据类型与十一个接口.md`   | 44,740 B |
| `50-主体层-循环-三种策略与执行原语.md`     | 36,816 B |
| `51-校验-治理与供给-横切部件怎么挂.md`     | 47,577 B |
| `52-装配与验证-build与五个预设六个例子.md` | 36,723 B |
| `53-组合-Agent与四种拓扑.md`        | 34,217 B |

原因：内容已落后（以 v1 双轨与"固定循环 + 部件"为前提），与 v3 方案直接冲突；本文件取代其设计说明地位。六篇均被 git 跟踪，删除后可用 `git restore` 恢复。

**保留但同属卷 12**（不是教程文章，未删）：`outline/20-副线封装推导.md`（大纲推导）、`docs/harness/SPEC.md` 与 `DEV-SESSION.md`（组件基座规格与开发记录）。`README.md` 中指向卷 12 的条目在迁移阶段一并更新。

### 9.4 明确保留（组件与 hooks 一个不删）

| 类别       | 具体                                                                                                                                                                                         |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| hooks 全族 | `Hook` 协议、`HookEvent`、`EVENT_NAMES`（含 `hook.error`）、`Middleware` / `Pipe` / `Filter`、`Layer` / `layer()`、`kernel/chain.py` 洋葱与拓扑排序                                                         |
| 内置层      | `parts/middleware/builtin.py`(355) 的 budget/taskboard/checkpoint/context 层、`parts/layers.py`(172) 五个薄层、`parts/guardrail/*`(510)、`parts/subagent.py`(102)                                   |
| 效应系统     | `kernel/stage.py` 四段链(160)、`kernel/scope.py`(70)、`impl/stores/*`、`impl/backends/*`、`parts/tools.py`、`parts/framing/*`、`parts/skills.py`、`parts/capability.py`、`parts/dispatch.py`、33 个契约协议 |

横切/效应部件共 11 文件 1466 行，**一行不删且插点增多**。核对时还发现：`Hook` 协议与 `HookEvent` 目前只有定义、没有实际的注册执行路径（`EVENT_NAMES` 里躺着 `hook.error`，全库无挂载实现）；本方案是第一次给 hooks 接上真正落点。

**公开 API 的名字一个不删**：`build` / `build_react` / `build_production` / `Agent` / `AgentConfig` / `Budget` / `MemoryTracer` / `SkillRegistry` / `RuleRouter` / `Pipeline` / `Handoff` / `Layer` / `layer` / `Hook` / `tool` 全部保留，用户代码不用改；变的只是这些名字背后指向哪份实现。唯一位置变化：**Layer 不再挂在 `program.layers`，改由装配期注入 `execute_effects` 链**（`with_auto_layers` 逻辑迁移），层本身的名字、签名、`points` 不变。

---

## 10. 兼容与迁移

1. 先建 `interpret()` + v1 兼容壳：`build()` / `Agent` / `presets` / 四个拓扑类全部改成"构造 program → `Harness.run` → `interpret`"；同时把 `__init__.py` 公开入口从 v1 切到新内核（修倒挂）。
2. 跑全量回归，用 `test_compat.py` 逐项对比新旧路径的 `status / answer / usage / events / 检查点`。
3. 此时 v1 实现已无调用者，删除才是零风险动作（删死代码）。
4. 清理测试与示例：约 10–12 个测试文件改写或删用例，4–5 个 `examples/` 更新。
5. `__version__` / `contracts_version` 递增，属 breaking change；自用/教程仓库可直接切，外部有使用者需一轮 deprecation（保留符号壳一个版本再删实现）。

---

## 11. 验收标准与实测结果

| 判据                        | 结果                                                                |
| ------------------------- | ----------------------------------------------------------------- |
| 十种主流架构共用同一个 `interpret()` | 通过（§7，10/10 completed）                                            |
| 三个"没想过的架构"框架 diff = 0     | 通过（§8，Backtrack / SelfModifying / ExternalControl 全 completed）    |
| 零封装程序也能跑                  | 通过（`FnProgram` completed）                                         |
| 带环 DAG 装配期拦截              | 通过（`ValidationFailed: 图中存在环`）                                     |
| 治理分级生效                    | 通过（Graph 三类能力全 True；BareFn 全 False，`to_spec` 抛 `NotSerializable`） |
| dry_run 只记账不执行            | 通过（`[dry-run:model]`）                                             |
| Layer / Hook 照常工作         | 通过（40 条观测事件）                                                      |
| 现有 25 个测试不破               | 阶段 1 待验证（样张独立于 `src/`，尚未接线）                                       |

---

## 12. 风险与边界

- **commit 原子性**：一批效应部分成功怎么办 —— 需要幂等键 + 事务式提交（第 25 章的内容）。这是本方案最难写对的地方。
- **闭包 program 不可检查点**：显式降级，不假装支持时间旅行。
- **回滚粒度**：§4.1 的 `journal/usage` 不回滚是必须的；样张第一次运行就因回滚掉模型消费进度而失败，修正后才全绿。真实实现要把这条写进契约。
- **性能**：纯决策步 `effects=()` 不该落盘；靠批量执行与零成本原语。
- **静态治理有梯度**：数据化前端全支持，不透明程序只运行时治理。
- **不变量变了 = 新运行时**，不是新架构，应通过扩展点吸收或明确写进边界；一旦出现 `if kind == "xxx"` 的内核分支，说明控制流放错了层。
- 通用解释器比专用循环难写对，调试完全依赖事件与检查点（第 37、42 章）。

---

## 13. 实施阶段

| 阶段             | 内容                                                                                          | 验收                               |
| -------------- | ------------------------------------------------------------------------------------------- | -------------------------------- |
| 0 纯新增          | `decision.py` / `interpret.py` / `effects.py` + `Effect` 扩字段 + `Limits`；`proposals/` 样张已先落地 | 现有 25 个测试全绿（新代码尚未被调用）            |
| 1 接线           | `Harness.run` 统一走 `interpret`、`fp.Program.transition()`、`PROGRAMS` 注册、去白名单、公开入口切换           | `test_compat.py` 行为等价对比通过        |
| 2 **收敛（不可跳过）** | 删 v1 实现、降 v2 循环、删副线教程、清理测试与示例                                                               | 解释器唯一；git 工作区干净；无并列循环            |
| 3 前端与验收        | `fp/frontends.py` 十种范式、三个未知架构、三个未知架构 diff=0                                                 | `kernel/` 与 `contracts/` 既有语义零改动 |

双轨只能是阶段 0–1 的过渡态，必须标注删除时间点；把"v1 全链路不动"当成最终状态是错的。

---

## 附录 A：文件与运行

```
docs/harness/PROPOSAL-通用解释器与效应系统.md    本文件
proposals/
    contracts.py       State / Effect / Decision / Halt / Program / Layer
    interpreter.py     Runtime（四段链 + interpret + 效应处理器）
    paradigms.py       十种内置架构范式 + builtin_paradigms()
    custom.py          四种其他架构范式 + custom_cases()
    demo.py            端到端验收
    __init__.py
```

```bash
cd code/harness
PYTHONPATH=. python -m proposals.demo
```

## 附录 B：术语

| 术语          | 含义                                                   |
| ----------- | ---------------------------------------------------- |
| 效应（Effect）  | 想对外部世界做的一件事的描述，不立刻做；由解释器统一执行                         |
| 程序（Program） | 实现 `transition(state) -> Decision \| Halt` 的对象，架构本身  |
| 解释器         | 框架内核，只做"问程序 → 执行效应 → 提交 → 换程序"                       |
| 前端          | 把声明/组合子/图编译成 `transition` 的用户侧库，可任意新增                |
| 内置范式        | 十种主流架构的参考实现，与用户自写架构同层，可删                             |
| 治理分级        | 程序声明 `describe/to_spec/static_check`，框架据此提供不同强度的静态能力 |
| 回滚粒度        | 业务状态可回滚，观测与计量（`journal/usage`）不回滚                    |

---

## 附录 C：实施记录（v3 落地）

> 落地版本 `__version__ = 0.3.0` / `contracts_version = 3`。
> 全量回归 **304 个测试全绿**（既有 263 + 新增 41），`proposals.demo` 14 案例仍全绿。

### C.1 文件清单

| 类别 | 文件 |
|---|---|
| 新增契约 | `contracts/decision.py`（Decision / Halt / Program 协议 / FnProgram / 治理分级） |
| 新增内核 | `kernel/interpret.py`（唯一循环 + Limits + Outcome + 单一提交点 + 检查点）、`kernel/effects.py`（四段链 + Effect→Step 适配 + 并发 + 幂等 + dry_run + Hook 落点）、`kernel/legacy.py`（v2 前端适配） |
| 新增前端 | `fp/frontends.py`（十种范式 + GraphSpec / JSON Spec 编译） |
| 新增示例 | `examples/interpret_minimal.py`、`examples/unknown_architectures.py` |
| 新增验收 | `tests/test_interpret.py`、`test_unknown_architectures.py`、`test_compat.py` |
| 只增不改 | `contracts/types.py`（`Effect` 加 `key/args/child/idem_key/index`，`kind` 放宽为 `str`）、`contracts/state.py`（`results/journal` + `snapshot/restore`）、`contracts/errors.py`、`contracts/protocols/runtime.py`（`Program` 协议）、`kernel/chain.py`（POINTS 扩到 8 个） |
| 接线 | `assembly/config.py`（`max_transitions` + 全插点校验）、`assembly/registry.py`（`PROGRAMS` + `register_program`）、`assembly/harness.py`（`interpret()` / `new_runtime()` / `dry_run_program()`）、`fp/__init__.py`（`Program.transition()` + `name` + `from_spec` 走注册表）、`assembly/agent.py`、`kernel/loop.py`、`parts/topology.py`、`__init__.py` |
| 收敛 | `kernel/loop.py` 与 `assembly/agent.py` 的循环体**已删除**，降为 `interpret()` 的前端薄壳；AST 检查确认全库只有一个运行循环 |
| 文档 | `README.md` 重写；根 `README.md` 卷 12 条目更新（48–53 六篇此前已删） |

### C.2 与提案的三处偏差（均有意，且已在测试中钉死）

1. **顶层 `Decision` 不能覆盖。** 现网 `harness.Decision` 是「人工审批结果」，被
   `ApprovalChannel` 协议、`Agent.resume` 与 `tests/test_core.py` 依赖；直接换成
   「转移决策」会破坏审批链。故新契约在 `harness.contracts.decision.Decision`，
   顶层以 **`Transition`** 别名导出，旧名保留。`test_compat.py` 对此有断言。
2. **`Effect` / `State` 复用现网类型，不另起一套。** 按 §9.2 的「只增不改」纪律
   扩字段，使效应系统能直接接到既有 `RunResult` / `CheckpointStore` / `RunScope` 上；
   样张里的简化 `State`/`Effect` 只留在 `proposals/` 作规格对照。
3. **`PROGRAMS` 采用前端自注册。** `assembly` 层不允许反向 import `fp`
   （`tests/test_architecture.py` 的层间无环约束）。故 `registry.py` 只放 v2 body
   工厂与 `register_program()`，十种前端在 `fp/frontends.py` 加载时自行注册；
   依赖方向仍是 `fp → assembly`。

### C.3 阶段 2 的收敛范围

删除了两个并列循环（v1 `_loop_inner`、v2 `run_loop` 循环体）与
`topology._call` 的 `try/except TypeError` 双签名兜底（改为按签名显式分流，
不再吞子节点内部的 TypeError）。**未物理删除** v1 组件、v2 `parts/`、
`RunContext` 与第二份 `Budget`：它们仍是 263 个既有测试的实际调用者，
按 §10 步骤 3「无调用者后删除才是零风险动作」，保留为兼容壳更稳妥。
`Harness.dry_run()` 兼容期保留旧语义（模型照调、只干跑工具效应），
新增 `Harness.dry_run_program()` 使用 `record_only=True` 的全效应记账。

### C.4 仍待处理（不阻塞验收）

- `commit` 原子性：批量效应部分成功时的事务式提交与跨运行幂等（第 25 章内容），
  当前实现提供 per-run 幂等键，未接 `IdempotencyStore`。
- 跨运行检查点恢复 / 时间旅行：不透明程序仍显式降级为 `<opaque>`。
- v1 组件与双份 `Budget`/`RunContext` 的物理删除，待外部使用者完成一轮 deprecation。

