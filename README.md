# agent-harness v0.3

**框架不提供任何架构，只提供一套完备的最小执行契约与效应系统；架构是运行其上的程序。**

> 设计规格（历史资料）：[`docs/harness/archive/PROPOSAL-通用解释器与效应系统.md`](docs/harness/archive/PROPOSAL-通用解释器与效应系统.md)
> 组件基座：[`docs/harness/SPEC.md`](docs/harness/SPEC.md) · 教程：[`docs/harness/TUTORIAL.md`](docs/harness/TUTORIAL.md)
> 演进记录：[`docs/harness/CHANGELOG.md`](docs/harness/CHANGELOG.md)

框架是**单版本**的：只有一条装配入口、一个解释器、一套事件与审批语义；
没有兼容壳、没有并列实现、没有随包分发的测试替身（离线测试工具在
[`tests/support.py`](tests/support.py)，不进 `src/harness` 包）。

## 唯一契约

```python
Program.transition(state) -> Decision | Halt
```

`Decision` = **一批 `Effect` + 下一个 `program` + `patch` + 可选 `restore`**。
内核只做五件事：问程序 → 批量执行效应（四段链）→ **单一提交点**写状态 →
发事件/检查点 → 换下一个程序，直到 `Halt`。

| 框架守 | 框架不管 |
|---|---|
| 状态单一所有者、能力作用域、预算、四段链、审批、事件、检查点、**全局终止护栏** | 顺序、分支、循环、并行、回溯、图、谁持有控制权 |

`seq / branch / loop / parallel / nest / graph / backtrack` 都不是框架算子，
只是 `Decision.program` 的取值和 `Decision.effects` 的数量。

## 最小用法

```python
import asyncio
from harness import Transition, Halt, FnProgram, Effect, interpret
from harness.fp.frontends import make_state

program = FnProgram(
    lambda state: Transition(
        effects=(Effect("compute", args={"op": "concat", "args": ["裸", "函数"]}, key="last"),),
        program=FnProgram(lambda s: Halt(str(s.data["last_output"])), name="end"),
    ),
    name="bare",
)

print(asyncio.run(interpret(program, make_state("最小示例"))).answer)  # 裸函数
```

一个裸函数就是架构；`Transition` 是转移决策（顶层 `Decision` 是**审批类型**，
两者语义不同，故用别名隔离，原名见 `harness.contracts.decision.Decision`）。

## 装配入口（生产用法）

```python
from harness import HarnessConfig, build_harness, react
from harness.assembly.fpresets import production

harness = build_harness(production(tools=[my_tool]))   # 模型槽位：openai / anthropic / ollama
result = await harness.run(react(max_steps=6), goal)   # program + goal → RunResult
```

- `HarnessConfig(model=None)` 是合法装配：不注入模型的程序（纯计算/工作流）
  照常运行；model 效应在运行期显式报错，不做静默兜底。
- 沙箱默认 `LocalSandbox`，**空白名单 = 全拒绝**（fail-closed）。
- 审批/恢复：`Guard` 判 `ask` → 运行挂起（`RunResult.pending`）→
  `harness.resume(program, session_id, Decision.approve(...))` 续跑；
  崩溃恢复传 `decision=None`，从 CheckpointStore 重放。
- 观测：`run(..., sinks=(my_sink,))`，sink 实现 `emit(RunEvent)`
  （`harness.parts.sinks` 提供 Null/Memory/Jsonl 三实现）。

## 运行

```powershell
$env:PYTHONPATH="$PWD\src"
$env:PYTHONIOENCODING='utf-8'

python tools/verify_harness.py               # 完成线门禁（快照一致 + 341 测试 + 冒烟）
python -m unittest discover -s tests -v      # 341 个测试
python examples/interpret_minimal.py          # 最小解释器
python examples/unknown_architectures.py      # 四种"没想过的架构"
```

## 内置范式（可删的前端库）

`harness.fp.frontends` 提供 10 种主流架构，与用户自写架构**同层同接口**，
内核不认识它们，删掉整个文件框架照样跑任意架构：

Tool Use · ReAct · Plan & Execute · Reflection · Router · Router + Skill ·
Supervisor · Handoff · Blackboard · Graph / DAG

`GraphSpec` / JSON Spec 可 `program_from_spec(...)` 编译；程序工厂注册在
`assembly.registry.PROGRAMS`，新增前端只需 `register_program(...)` 一行。

## 验收结果

| 判据 | 结果 |
|---|---|
| 十种主流架构共用同一个 `interpret()` | ✅ 10/10 completed |
| 四种"框架作者没想过的架构"、框架 diff = 0 | ✅ Backtrack / SelfModifying / ExternalControl / BareFunction |
| 零封装裸函数也能跑 | ✅ |
| 带环 DAG 装配期拦截 | ✅ `ValidationFailed` |
| 审批挂起 → 人工批准 → 续跑；崩溃恢复重放 | ✅ `Harness.resume` |
| dry_run 只记账不执行 | ✅ `[dry-run:model]` |
| Layer / Hook 横切观测 | ✅ |
| 全局终止护栏 | ✅ transitions / calls / tokens / 墙钟 |
| 全部回归 | ✅ 341 个测试 |
| 完成线门禁 | ✅ `GATE OK` + `CHECK OK`（判据 1.4，锚点 44/44） |

## 关键约束

- **解释器唯一**：唯一 `while` 循环在 `kernel/interpret.py`（机械检查测试锁定）。
- **状态单一所有者**：`transition` 只读 `State`；I/O 必须表达成 `Effect`；
  只有 `Runtime._commit` 写状态。
- **回滚粒度**：业务状态（`data/results/rev/...`）可回滚；`journal`（观测进度）
  与 `usage`（计量）是既成事实，**不随回溯回滚**。
- **治理分级**：程序可选实现 `describe/to_spec/static_check`；不透明程序
  `to_spec()` 抛 `NotSerializable`，检查点写 `<opaque>`，不假装支持时间旅行。
- **测试替身不进包**：`FakeModel`/剧本回放 handler/剧本沙箱/可控时钟只在
  `tests/support.py`（examples 用 `examples/demo_model.py`）；框架包内只有
  真实实现与内存/本地实现。
- 核心零第三方依赖；适配器放 `adapters/`；`State` 只存可序列化数据。
- 新增效应类型只注册 handler，内核不加 `if kind == ...` 分支。

## 目录（真实分层）

```text
src/harness/
├── contracts/         类型、协议、事件、错误（零依赖）
│   └── decision.py    ★ Decision / Halt / Program 协议 / FnProgram / 治理分级
├── kernel/
│   ├── interpret.py   ★ 唯一解释器 + Limits + Outcome + 单一提交点 + 检查点
│   ├── effects.py     ★ 四段链 + Effect→Step 适配 + 并发 + 幂等 + dry_run
│   ├── stage.py       四段链（body 路径与效应路径共用）
│   ├── chain.py       插点拓扑排序
│   ├── loop.py        空壳（历史占位，机械检查"解释器唯一"用）
│   └── scope.py       RunScope 能力作用域
├── fp/
│   ├── frontends.py   ★ 十种内置范式 + GraphSpec / JSON Spec 编译
│   └── __init__.py    门面：Program / react / workflow / pe / 组合子
├── assembly/          Harness、HarnessConfig、build_harness、注册表、fpresets
├── parts/             组件库（Actor/策略/层/护栏/工具/技能/拓扑/事件出口）
├── impl/              存储与后端实现（内存态 + 本地态；无测试替身）
└── adapters/          外部模型适配器（openai）
examples/              10 个可运行示例（demo_model.py 为其共用离线模型）
tests/                 341 个测试 + support.py（测试替身与剧本回放的唯一住址）
tools/                 verify_harness.py（门禁） + audit_harness.py（机械审计）
docs/harness/          SPEC / TUTORIAL / CHANGELOG / AUDIT（archive/ 为历史资料）
proposals/             独立可运行样张（不接入 src，作规格对照）
```
