# agent-harness v0.3

**框架不提供任何架构，只提供一套完备的最小执行契约与效应系统；架构是运行其上的程序。**

> 规格：[`docs/harness/PROPOSAL-通用解释器与效应系统.md`](../../docs/harness/PROPOSAL-通用解释器与效应系统.md)
> 组件基座（v1/v2 资产）：[`SPEC.md`](../../docs/harness/SPEC.md) · 开发记录：[`DEV-SESSION.md`](../../docs/harness/DEV-SESSION.md)

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

一个裸函数就是架构；`Transition` 是转移决策（顶层 `Decision` 是既有**审批类型**，
两者语义不同，故用别名隔离，原名见 `harness.contracts.decision.Decision`）。

## 运行

```powershell
$env:PYTHONPATH="$PWD\code\harness\src"
$env:PYTHONIOENCODING='utf-8'

python -m unittest discover -s code/harness/tests -v      # 304 个测试
python code/harness/examples/interpret_minimal.py          # 最小解释器
python code/harness/examples/unknown_architectures.py      # 四种"没想过的架构"
```

```bash
cd code/harness && PYTHONPATH=. python -m proposals.demo   # 独立可运行样张（14 案例）
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
| 治理分级（Graph 全支持 / 裸函数显式降级） | ✅ |
| dry_run 只记账不执行 | ✅ `[dry-run:model]` |
| Layer / Hook 横切观测 | ✅ |
| 全局终止护栏 | ✅ transitions / calls / tokens / 墙钟 |
| 全部回归（v1 + v2 + v3） | ✅ 304 个测试 |

## 关键约束

- **解释器唯一**：唯一 `while` 循环在 `kernel/interpret.py`。`kernel/loop.py`、
  `assembly/agent.py` 都降为「前端 + 兼容壳」，名字与签名保留。
- **状态单一所有者**：`transition` 只读 `State`；I/O 必须表达成 `Effect`；
  只有 `Runtime._commit` 写状态。
- **回滚粒度**：业务状态（`data/results/rev/...`）可回滚；`journal`（观测进度）
  与 `usage`（计量）是既成事实，**不随回溯回滚**。
- **治理分级**：程序可选实现 `describe/to_spec/static_check`；不透明程序
  `to_spec()` 抛 `NotSerializable`，检查点写 `<opaque>`，不假装支持时间旅行。
- 核心零第三方依赖；适配器放 `adapters/`；`State` 只存可序列化数据。
- 新增效应类型只注册 handler，内核不加 `if kind == ...` 分支。

## 目录（真实分层）

```text
src/harness/
├── contracts/         类型、协议、事件、错误
│   └── decision.py    ★ v3：Decision / Halt / Program 协议 / FnProgram / 治理分级
├── kernel/
│   ├── interpret.py   ★ v3：唯一解释器 + Limits + Outcome + 单一提交点 + 检查点
│   ├── effects.py     ★ v3：四段链 + Effect→Step 适配 + 并发 + 幂等 + dry_run
│   ├── legacy.py      ★ v3：v2 组合子线的前端适配（旧循环已删）
│   ├── loop.py        兼容壳：转发到 kernel.legacy
│   ├── stage.py       四段链（零改动）
│   ├── chain.py       插点拓扑排序（POINTS 扩展到 8 个）
│   └── scope.py       RunScope 能力作用域
├── fp/
│   ├── frontends.py   ★ v3：十种内置范式 + GraphSpec / JSON Spec 编译
│   └── __init__.py    门面：Program 加 transition()，from_spec 走注册表
├── assembly/          配置校验、注册表（PROGRAMS）、Harness、v1/v2 兼容壳
├── parts/             组件库（Layer/Middleware/Hook/Guard/Pipe/Filter/护栏/工具/技能）
└── impl/              存储与后端实现
examples/
├── interpret_minimal.py       最小解释器
└── unknown_architectures.py   四种框架作者没想过的架构（纯用户侧）
tests/
├── test_interpret.py            核心验收
├── test_unknown_architectures.py 框架 diff = 0 验收
└── test_compat.py               兼容与「解释器唯一」机械检查
proposals/             独立可运行样张（不接入 src，作规格对照）
```
