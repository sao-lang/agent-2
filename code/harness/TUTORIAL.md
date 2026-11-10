# Harness 框架封装教程

> 面向对象：想真正理解这个框架怎么"想"的人。读完你应该能回答三个问题：
> 框架守什么、程序管什么、一条 Effect 从产生到落盘走了哪些路。
>
> 配套阅读：`README.md`（一页纸总览）、`../../docs/harness/PROPOSAL-通用解释器与效应系统.md`（设计规格）。

---

## 0. 一句话定位

**框架不提供任何架构，只提供一套完备的最小执行契约与效应系统；架构是运行其上的程序。**

传统 Agent 框架（LangGraph 的图、各种 workflow 引擎）把架构写死在框架里：
换一种编排方式 = 换框架或改框架源码。Harness 反过来 —— 它把**控制流全部还给用户程序**，
自己只守住一组"无论你怎么编排都不许破坏"的不变量。

```text
┌────────────────────────────────────────────────────┐
│  你的架构（seq / ReAct / 图 / 回溯 / 没想过的任何）    │  ← fp/frontends.py 只是示例库
│  Program.transition(state) -> Decision | Halt       │
├────────────────────────────────────────────────────┤
│  内核（全框架唯一的 while 循环）                      │
│  问程序 → 批量执行效应 → 单一提交点 → 事件/检查点       │
├────────────────────────────────────────────────────┤
│  不变量：状态单一所有者 · 能力作用域 · 预算 · 四段链    │
│  审批 · 事件 · 检查点 · 全局终止护栏                  │
└────────────────────────────────────────────────────┘
```

框架守 / 框架不管的分界线，是整个设计的灵魂：

| 框架守（不变量）         | 框架不管（控制流）           |
|-------------------------|---------------------------|
| 状态单一所有者           | 顺序、分支、循环            |
| 能力作用域（RunScope）   | 并行、回溯、图              |
| 预算（Budget/Limits）    | 谁持有控制权                |
| 四段链（Gate→Check→Wrap→Classify） | 自定义终端动作        |
| 审批、事件、检查点       | 自定义状态结构（只要可序列化）|
| 全局终止护栏             | 自定义终止状态码            |

`seq / branch / loop / parallel / nest / graph / backtrack` 都**不是**框架算子，
只是 `Decision.program` 的取值和 `Decision.effects` 的数量（见 §6 映射表）。

---

## 1. 分层架构与依赖方向

```text
src/harness/
├── contracts/    ⑤ 底座：类型、协议、事件、错误（零依赖，人人可用）
├── kernel/       ① 内核：解释器 + 效应系统 + 四段链 + 作用域
├── fp/           ④ 前端库：十种内置范式（可整体删除）
├── assembly/     ③ 装配层：Harness 容器、注册表、兼容壳
├── parts/        ② 组件库：Layer/Middleware/Hook/Guard/Pipe/Budget/工具/护栏…
├── impl/         存储与后端的可替换实现（memory store、fs backend、fakes）
└── adapters/     外部模型适配器（openai）
```

依赖纪律（为什么这样排）：

- **kernel 不 import fp**。内核只认识 `contracts` 里的协议 —— 这保证"删掉
  `fp/frontends.py` 整个文件，框架照样跑任意架构"。
- **前端自注册**：`fp/frontends.py` 末尾的 `_register_frontends()` 主动把自己
  注册进 `assembly.registry.PROGRAMS`，装配层不反向 import fp，分层不破。
- **contracts 零依赖**：任何一层都可以 import 它，它不 import 任何人。
  所有跨层通信的数据形状（State/Effect/Decision/事件）都在这里定死。

一句话记住：**依赖只能向下，注册代替反向引用。**

---

## 2. 唯一契约：`Program.transition(state) -> Decision | Halt`

位置：`contracts/decision.py` + `contracts/protocols/runtime.py`。这是全框架
**唯一**的执行契约，你的架构只需要实现这一个方法。

### 2.1 `Transition`（源码里叫 `Decision`，注意区分！）

`Decision` 是一次"转移决策"，六个字段：

```python
@dataclass(frozen=True)
class Decision:
    effects: tuple[Effect, ...] = ()   # 一批效应请求：0 个 = 纯决策步，多个 = 并行
    program: Any = None                # 下一个程序；None = 保持当前
    patch: dict[str, Any] = {}         # 显式状态增量，由解释器在唯一提交点写入
    restore: dict[str, Any] | None = None  # 回溯：先恢复历史快照再执行
    note: str = ""                     # 人类可读的备注，进 trace
    meta: dict[str, Any] = {}          # 透传给效应运行时的附加信息，内核不解释
```

设计意义，逐字段看：

- **`program=None` 表示"保持当前程序"** —— 这就是循环。ReAct 的"loop"不过是
  `program=self`，框架里根本没有 loop 算子。
- **`program=新实例`** —— 不可变 dataclass 的 `replace(self, step=...)` 派生
  新程序，这是状态机转移：程序的"步数/阶段"存在程序自身字段里，不偷写 State。
- **`patch` 是程序唯一合法的写状态通道**。程序绝不能 `state.data[...] = x`
  （程序只读 State），想写就放进 patch，由解释器在唯一提交点统一写入。
- **`restore` 是回溯**：把某次检查点里的快照还回去，再继续执行。
- **`effects` 一批多个** = 并行。框架不提供 parallel 算子，批量就是并行
  （内核用 `asyncio.gather` 并发执行，见 §5.2）。

### 2.2 `Halt`

```python
@dataclass(frozen=True)
class Halt:
    answer: str = ""
    status: str = "completed"   # completed / degraded / refused / failed / …自定义
    extra: dict[str, Any] = {}
```

`status` 故意用字符串而不是枚举 —— 前端可以自定义终止状态而不改内核。

### 2.3 命名空间隔离（一个容易踩的坑）

`harness.contracts.decision.Decision` 是"转移决策"；而顶层导出的
`harness.Decision`（来自 `contracts/types.py`）是**人工审批结果**，语义完全不同，
被 `ApprovalChannel` / `Agent.resume` 依赖。所以：

- 顶层 `harness.Decision` = 审批类型（保持兼容）
- 转移决策用 `harness.contracts.decision.Decision`，顶层别名为 **`Transition`**

教程和示例代码里写 `Decision` 时，指的都是转移决策（从 `contracts.decision` 导入）。

### 2.4 `FnProgram`：零封装入口

```python
class FnProgram:
    def __init__(self, fn: Callable[[State], Decision | Halt], name: str = "fn"): ...
    def transition(self, state): return self.fn(state)
```

把一个裸函数包成 Program。它的存在证明了一件事：**一个裸函数就是架构**。
框架没有任何必须继承的基类、必须填的配置 —— 只要对象有 `transition()`。

### 2.5 治理分级：`CAPABILITIES = ("describe", "to_spec", "static_check")`

程序**可选**实现三个静态能力，框架"不假装全能"：

| 能力 | 作用 | 不实现时的降级 |
|---|---|---|
| `describe()` | 人类可读描述，进 trace | 显示 `<opaque:类名>` |
| `to_spec()` | 检查点序列化，支撑时间旅行 | 抛 `NotSerializable`，检查点写 `<opaque>` |
| `static_check()` | 装配期静态检查（如 Graph 查环） | 返回空列表（运行时治理） |

闭包程序永远无法被序列化 —— 框架不骗你，明确降级而不是假装支持。

---

## 3. `State`：状态单一所有者的物质基础

位置：`contracts/state.py`。

### 3.1 字段一览

```python
@dataclass
class State:
    goal: Goal              # 这次要干什么（文本 + 用户/会话元信息）
    session: SessionRef     # 会话引用（session_id、tenant）
    trace_id: str           # 全链路追踪 id
    data: dict              # 业务状态命名空间（你的架构的工作内存）
    messages: list[dict]    # 对话消息
    step_index: int         # 步号
    status: RunStatus       # running / completed / failed / …
    usage: dict             # {"tokens": n, "calls": n} 计量
    last_error: str | None
    rev: int                # 落盘版本号（不变量 1）
    results: dict           # v3：效应结果；__batch__ = 本批新结果
    journal: dict           # v3：观测/消费进度，不随回溯回滚
```

### 3.2 三条关键语义

1. **只存可序列化数据**：`to_dict()` 走 `_jsonable()`，JSON 表达不了的东西
   （对象、句柄、函数）进 State 会直接 TypeError。这是检查点/恢复/跨机迁移的前提。
2. **回滚粒度是有意设计过的**：`snapshot()` 只备份
   `goal/data/results/messages/step_index/status/last_error/rev`；
   `journal`（"已经消费到模型脚本第几条"）和 `usage`（"已经花了多少 token"）
   是**外部世界的既成事实**，不随回溯回滚 —— 否则回溯会把"已经问过模型"
   这件事也撤销，脚本被重复消费。
3. **谁有权写**：程序只读；效应 handler 只返回结果（终端只记账不写业务状态）；
   唯一的写入口是解释器的 `Runtime._commit`（见 §5.1）。

### 3.3 `results` 与 `__batch__`

每轮效应执行完，`_commit` 把结果按 `effect.key` 写进 `state.results[key]`，
并把本批结果整体放进 `state.results["__batch__"]`（每轮覆盖）。
前端范式统一用 `_batch(state)` 读"本批新结果"，这是程序与效应结果之间的标准接口。

---

## 4. `Effect`：I/O 的唯一载体

位置：`contracts/types.py`。

```python
Effect(
    kind="tool",              # 效应类型（str，可扩展）
    args={"name": "echo", "args": {"text": "hi"}},
    key="last",               # 结果写入 state.results 的键
    child=None,               # kind="child" 时携带的子程序
    idem_key="…",             # 幂等键：同键同结果
    est_tokens=0, index=0, step=None, spec=None,
)
```

### 4.1 概念：描述，不是执行

> Effect 是"想对外部世界做的一件事的**描述**"，不是立刻做。

这就是"效应系统"（Effect System）的核心思想，借自函数式编程：
把 I/O 从计算里剥离成**值**。程序产出的是一批"请求"（纯数据），
执行权完全在框架手里 —— 于是框架才有资格在执行前后插桩：
准入（Gate）、校验（Check）、包裹（Wrap）、归类（Classify）、记账（dry_run）、
幂等去重、审批拦截。如果程序自己直接 `open()` / `await model(...)`,
这些治理全部失效。

### 4.2 内置效应类型（`EffectRuntime.handlers` 注册表）

| kind | 语义 | handler 做什么 |
|---|---|---|
| `model` | 调模型 | 有 `state.data["script"]` 时按游标回放脚本（测试）；否则调注入的 `model.complete()` |
| `tool` | 调工具 | 按 `args["name"]` 查工具表（注入的 registry 或 `state.data["tools"]`）执行 |
| `skill` | 技能渐进披露 | `part=catalog/body/resource` 三段：目录常驻，正文与资源按需 |
| `ask` | 人工审批 | 返回审批结果（可接入 ApprovalChannel） |
| `wait` | 交给外部 | 从 `state.data["external_queue"]` 异步取消息，控制权交给外部系统 |
| `compute` | 纯计算 | concat/upper/sum/join 等演示算子 |
| `child` | 子运行 | 用新 State（深拷贝 data）递归跑 `interpret()`，预算由父护栏统一管 |

### 4.3 扩展点：新增 kind 不改内核

`EffectRuntime.__post_init__` 先装内置 handler，再 `update(extra_handlers)`。
**内核里没有 `if kind == ...`** —— 新效应类型 = 注册一个 `async fn(effect, state) -> dict`。

---

## 5. 内核：`kernel/`（教程重点）

### 5.1 `interpret.py` —— 全框架唯一的循环

源码头部的伪代码就是全部真相：

```python
program = 初始程序
while True:
    d = await program.transition(state)      # 架构在这里，框架不问
    if d is Halt: return Outcome
    results = await runner.execute(d.effects, state)   # 批量 → 四段链
    commit(state, d.patch, results)          # 唯一提交点
    emit(state); checkpoint(state, program)  # 事件 + 检查点
    program = d.program or program           # 自=循环 / 历史=回溯 / 新组合=改图
```

**设计意义**：架构的"全部自由度"被压缩到 `transition()` 的返回值里，
内核的"全部职责"被压缩到这五行循环里。这意味着：

- 内核里没有 `if kind == ...`、没有对任何具体范式的偏袒；
- 换架构、加效应类型，内核一行不改（这是验收判据："框架作者没想过的架构，
  框架 diff = 0"）。

#### 四个内核级对象

- **`Limits`**（全局终止护栏）：`max_transitions / max_calls / max_tokens /
  wall_seconds`。设计动机：新程序可以无限返回自己或发空效应空转 —— 控制流
  交给了用户，"必须能停下来"就成了框架唯一的硬责任。护栏在每轮循环开头检查，
  超限返回 `Halt(..., "degraded")`。
- **`Outcome`**：一次运行的产物：`answer / status / transitions / usage /
  checkpoints / trace / state / extra`。
- **`Runtime`**：解释器本体 = 一个循环 + 一个效应运行时（`EffectRunner`）。
  runner 可整体替换：默认走 v3 效应系统；旧路径注入 `CallbackRunner`
  把效应喂给既有 `kernel.stage.run_stages` —— 内核一行不改。
- **`_commit`（唯一提交点）**：框架里**唯一**写 State 的地方。它做的事：
  1. 把每个结果按 `effect.key` 写入 `state.results`，`output` 同步到
     `data["last_output"]`；
  2. 计量入账（`_usage`，缺省 calls=1）；
  3. `_messages` 追加进对话；
  4. 本批结果整体放 `results["__batch__"]`；
  5. 应用 `decision.patch`；
  6. `rev += 1`（版本号推进）。

#### 循环里的两次"明确降级"

- `restore is not None` → 先 `state.restore(快照)`（journal/usage 不回滚）再执行效应；
- 检查点序列化时 `to_spec()` 抛 `NotSerializable` → 检查点里写 `"<opaque>"`，
  不假装支持时间旅行。

#### 观测语义

所有 `emit()` 吞掉观察侧异常 —— **观测失败不得影响运行**（SPEC M10.1）。
事件插点：`run.start / transition / commit / checkpoint / effect / run.end`。

### 5.2 `effects.py` —— 效应系统（四段链的家）

#### 批量并发

```python
async def execute(self, effects, state):
    indexed = [replace(e, index=i) for i, e in enumerate(effects)]
    return list(await asyncio.gather(*(self._stages(e, state) for e in indexed)))
```

一批效应并发执行 —— **并行不需要框架算子，effects 里多放几个就是并行**。
0 个效应 = 纯决策步，不落盘不记账（程序可以只做决策不发效应）。

#### 四段链：`Gate → Check → Wrap → Classify`

每个效应独立走一遍（`_stages`）。**为什么是四段而不是一条洋葱中间件链？**
因为四段的**失败语义不同**（SPEC M2.2），不能合并：

| 段 | 语义 | 失败行为 |
|---|---|---|
| ① Gate | 动作准入（护栏/审批） | **返回判定** `allow/deny/ask`，不抛异常，可短路 |
| ② Check | 参数校验与转换（Pipe） | 抛异常 → 统一走 Classify |
| ③ Wrap | 洋葱包裹执行（Middleware，外层在最外） | 异常原样穿透 → Classify |
| ④ Classify | 异常 → `Failure` 的**唯一映射点** | 未知异常 fail-closed（`FAILED`） |

Gate 返回 `deny` → 结果 `status=refused`；`ask` → `needs_approval`。
Check/Wrap 的异常不会炸掉整批 —— 被 Classify 归类成结构化失败
（`{"ok": False, "status": ..., "reason": ...}`），解释器照常提交。
**失败也是数据**，由程序在下一轮决定怎么处理（重试/回溯/放弃）。

#### 三件定死的事

1. **幂等**：`effect.idem_key` 命中 `runtime.seen` 直接回放缓存结果，
   `_usage = {calls: 0, tokens: 0}`（不重复计量）。设计意义：重试/回溯后
   重复发同一效应，不会重复扣款、重复发邮件。
2. **dry_run**：`record_only=True` 时四段链**照走**（门禁、校验、归类全部真实），
   只有终端替换成记账：`{"ok": True, "output": "[dry-run:kind]"}`。
   上线前可以完整"彩排"一次将要发生的全部 I/O。
3. **kind 可扩展**：见 §4.3。

#### Hook 落点

每条效应结束后 `_fire_hooks` 触发 `effect.<kind>` 插点的 Hook（只读，
返回值被忽略，hook 报错只发 `hook.error` 事件）。这是 v3 首次给 v2 的
Hook 协议接上真正的执行落点。

#### `EffectRunner` 协议

`Runtime` 只认识 `execute(effects, state) -> list[result]` 这一个接口。
换掉它就能把效应喂给任何执行后端（旧路径的 `CallbackRunner` 就是范例）。

### 5.3 `stage.py` —— 四段链的 v1 遗产（零改动复用）

v2 时代的 `run_stages(step, state, terminal=…)`，四段顺序"不可调、不可合并、
不可省略"。v3 效应系统没有重写它，而是把 `Effect` 薄适配成 `Step`
（`to_step()`：按 `_KIND_TO_STEP` 映射 kind），让旧四段链直接被新路径喂入。
这是"复用治理资产"的典型手法：**适配，而不是重写**。

`DefaultClassify` 是异常 → 失败分类的默认映射表，值得记住：
`CancelledError→CANCELLED`、`ApprovalRequired→NEEDS_APPROVAL`、
`GuardDenied/PolicyError→REFUSED`、`ValidationError→REFUSED`、
`TransientError→DEGRADED(retryable)`、`BudgetExceeded→DEGRADED`、
未知异常→`FAILED`（**fail-closed**）。

### 5.4 `scope.py` —— `RunScope` 能力作用域

```python
@dataclass(frozen=True)
class RunScope:
    namespace: Namespace    # 谁（agent/session）在跑
    budget: Any             # 预算
    model / fs / sandbox / secrets / memory / guardrails / events …  # 能力引用
    depth: int = 0
    max_depth: int = 2      # 子 agent 深度上限

    def child(self, name, *, budget_fraction=0.3) -> "RunScope": ...
```

设计要点：

- **作用域只持有不可变的能力引用**，可变状态只有 `State`。程序能拿到什么能力
  （能不能访问文件系统、密钥、子 agent）由装配期注入的作用域决定 ——
  这是"最小权限"的落点。
- **`child()` 派生子作用域**：新命名空间、预算 `split(0.3)` 切分、深度 +1
  （超限抛 `ConfigError`）。资源"单一所有者、单向继承"：子作用域的能力
  只能是父作用域的子集。
- `child_slots`（并发槽位）挂在 scope 而不是层上：层是值、会被复制，
  挂在层上会导致"每层各造一个信号量"，总量失控（SPEC M13.7 的教训）。

### 5.5 `chain.py` / `loop.py` / `legacy.py`

- `chain.py`：插点拓扑排序，POINTS 扩展到 8 个 —— 决定层/hook 在哪些插点、
  以什么顺序生效。
- `loop.py` / `legacy.py`：v2 组合子线的**兼容壳**，转发到新内核。名字与签名
  保留，真正的循环已经只剩 `interpret.py` 一个 —— 这就是"解释器唯一"的
  机械检查（`tests/test_compat.py` 里有对应断言）。

---

## 6. `fp/frontends.py` —— 十种内置范式（可删的前端库）

**这是最容易误解的部分**：这十种类不是框架，它们与你自写的架构**同层同接口**
（都只是实现了 `transition()` 的对象），内核不认识它们。删掉整个文件，
框架照样能跑任意架构。它们的价值是"参考答案库"—— 每种主流 Agent 架构
如何用 `Decision` 表达，这里各给了一份最小实现。

### 6.1 控制流 → 契约的映射表（本框架最重要的一张表）

| 传统算子 | 在 Harness 里等于 | 源码例证 |
|---|---|---|
| `seq`（顺序） | `program` 换成下一个游标 | PlanExecute：`replace(self, cursor+1)` |
| `branch`（分支） | `program` 换成某个 arm | Router：`program=arm` |
| `loop`（循环） | `program` 返回自己 | React：`program=self` |
| `parallel`（并行） | `effects` 一批多个 | minimal 例子的 fan-out 2 |
| `nest`（嵌套） | `Effect(kind="child")` | Supervisor：fan-out child |
| `graph`（图） | `transition` 读图数据算下一批节点 | Graph：边表 + `done` 集合 |
| `backtrack`（回溯） | `program` 换回历史 + `restore` 快照 | unknown_architectures 例 |

### 6.2 十种范式速览

| # | 范式 | 一句话核心 | 关键机制 |
|---|---|---|---|
| ① | ToolUse | 发一批工具效应然后收结果 | `program=replace(self, fired=True)` |
| ② | ReAct | 想→动→想→…直到模型不给 tool_calls | `program=self` 循环 |
| ③ | PlanExecute | 先规划拿 steps，再逐个执行 | `phase` 状态机 + 游标 |
| ④ | Reflection | 起草→批评→不过关就重写 | phase 轮换 + max_rounds |
| ⑤ | Router | 模型分类，选一个 arm | `program=arms[name]` |
| ⑥ | RouterSkill | 分流 + 技能按需加载正文 | `Effect("skill", part="body")` |
| ⑦ | Supervisor | 拆任务 → 一批 child 并行 → join | 多个 `Effect("child")` |
| ⑧ | Handoff | 角色间移交控制权 | `program=roles[target]` + hops 上限 |
| ⑨ | Blackboard | 多 agent 轮流写同一块黑板 | 一批 child × 多轮 |
| ⑩ | Graph/DAG | 节点+条件边的声明式执行 | `static_check()` 装配期查悬空边/环 |

注意几个精妙处：

- **Graph 的环**：纯 DAG 表达不了环 —— 框架的态度是"环放进节点内部"
  （节点自己的 transition 可以循环），装配期 `static_check` 直接拒绝带环 DAG。
- **程序是不可变值**：所有范式都是 `frozen dataclass`，"状态推进"靠
  `replace(self, …)` 派生新实例。好处：程序本身可以进检查点、可以回溯
  （回溯 = 换回历史程序实例）。
- **`make_state()`**：按现网 State 信封构造初始状态的便捷函数。

### 6.3 声明式编译：`GraphSpec` / `program_from_spec`

`JSON Spec → 程序`：工厂查 `assembly.registry.PROGRAMS`（无白名单，
注册即用），嵌套的 `arms/workers/roles/fallback` 递归编译。
新增一种前端 = 写一个类 + `register_program("my_kind", factory)` 一行。

---

## 7. `assembly/` —— 装配层

### 7.1 `Harness`：能力容器

```python
Harness(model=…, tools=ToolRegistry, budget=Budget, guard=…,
        pipes=…, guardrails=…, system="system prompt", max_depth=2, …)
```

**"模型、工具、存储、后端。不持有任何策略。"** —— 能力（可以做什么）
归 Harness，策略（什么时候做、按什么规则）归程序与层。

核心方法（v3 入口）：

- `new_runtime(state, …)`：装配期注入能力 → 造 `Runtime`（唯一解释器）。
  预算从 `Budget` 映射进 `Limits`，护栏、检查管道、分类器、事件出口在这里接上。
- `harness.interpret(program, goal=…)`：**任意架构**的唯一解释器入口。
  与旧 `Harness.run` 的区别：不假设 ReAct 循环，程序自己决定一切。
- `dry_run_program(...)`：`record_only=True` 的完整彩排，返回
  `(结果, 效应清单)`。
- `astream(program, goal)`：流式出口 —— **共用同一条内核**，只是多挂一个
  队列 sink（`_QueueSink`，溢出丢最旧并计数）。流式不是另一条执行路径，
  是同一事件的另一个消费者。
- `run()` / `scope_for()` / `with_auto_layers()`：v2 兼容入口，底层已转发到
  `interpret`。

### 7.2 `registry.py`：`PROGRAMS` 注册表

`register_program(name, factory)` / `resolve`。前端库自注册进去，
`program_from_spec` 按名字查工厂。**注册代替白名单**：新形态零改动接入。

其他文件：`config.py`（HarnessConfig，护栏配置来源）、`build.py` /
`presets.py` / `fpresets.py`（预设装配）、`agent.py`（v2 Agent 兼容壳）。

---

## 8. `parts/` —— 组件库（v1/v2 资产，v3 复用）

按"四段链角色"归类理解，不要平铺记忆：

| 角色 | 在四段链的位置 | 代表部件 |
|---|---|---|
| Gate | ①准入 | `guard.py`（GuardDecision：allow/deny/ask）、`policy/`、`guardrail/`（ detectors/layer/streaming） |
| Check | ②校验转换 | `middleware/`、`capability.py`（能力校验） |
| Wrap | ③洋葱包裹 | `layers.py`、`middleware/base.py`（重试/超时等 builtin） |
| Classify | ④归类 | `resilience.py`、Filter |
| 横切观测 | Hook/事件 | `tracer.py`、`durability.py`（检查点） |
| 能力供给 | 注入 Scope | `tools.py`（ToolRegistry）、`memory.py`、`retrieval.py`、`knowledge.py`、`skills.py` |
| 执行终端 | handler | `actor.py`/`actor_v2.py`（LlmActor）、`framing/`（ModelFramer/ChatEncoder）、`body/`（react/planner/workflow 等旧前端） |
| 子代理 | child 效应 | `subagent.py`、`dispatch.py`、`topology.py` |
| 其他 | — | `budget.py`（Budget.split）、`context.py`、`delivery.py`、`reflector.py` |

初学建议：先只记住四个链上角色 + ToolRegistry + Budget，其余按需查。

---

## 9. `impl/` 与 `adapters/`

- **`impl/`**：contracts 协议的可替换实现。`stores/memory.py`（内存态存储）、
  `backends/`（fs 文件后端）、`fakes.py`（测试假件）。协议在 contracts、
  实现在 impl —— 存储换 Redis/Postgres 时不碰内核。
- **`adapters/openai.py`**：外部模型适配。核心零第三方依赖是硬纪律，
  所有 SDK 依赖被隔离在这里。

---

## 10. 一条 Effect 的完整旅程（串起所有部件）

以 ReAct 一轮里的 `Effect("tool", args={"name": "lookup", ...}, key="tool")` 为例：

```text
React.transition(state)
  │  读 state.results["__batch__"]（上一批结果）
  │  决定：调工具 lookup
  ▼
Decision(effects=(Effect("tool",…),), program=replace(self, step+1))
  │  程序只读 State，产出的是"请求"，不是执行
  ▼
Runtime.interpret 循环体
  │  ① 护栏检查（transitions/calls/tokens/墙钟）
  │  ② （若有 restore）state.restore(快照) —— journal/usage 不回滚
  ▼
EffectRuntime.execute(effects, state)        [asyncio.gather 并发]
  │  每个效应走四段链：
  │  Gate   → layer.gate / guard.check → deny 拒绝 / ask 转审批
  │  Check  → layer.check / pipes.transform（参数修正）
  │  Wrap   → layers 洋葱包裹（重试/超时/日志…）
  │  Terminal → handlers["tool"] → tool_registry 执行 → 返回 dict
  │  （idem_key 命中 → 直接回放，不重复执行不重复计量）
  │  Classify → 任何异常归类成结构化 Failure，不炸批
  │  Hook   → effect.tool 插点；emit("effect", …)
  ▼
Runtime._commit（唯一提交点）
  │  results["tool"]=结果 → last_output 更新 → 计量入账
  │  results["__batch__"]=本批 → data.update(patch) → rev+=1
  ▼
emit("commit") → checkpoint(rev, program.to_spec() 或 "<opaque>", state.snapshot)
  ▼
program = decision.program   # replace 后的新 React（step+1）
  ▼
下一轮 transition：读到 __batch__ 里 lookup 的结果 → 生成回答 → Halt
  ▼
Outcome(answer, status, transitions, usage, trace, checkpoints)
```

---

## 11. 设计不变量清单（code review 时的对照表）

1. **状态单一所有者**：程序只读 State；效应只返回结果；写只发生在
   `Runtime._commit`。
2. **解释器唯一**：全框架唯一的 `while` 循环在 `kernel/interpret.py`
   （有机械检查测试）。
3. **I/O 必须表达成 Effect**：绕过效应系统直接 I/O = 绕过全部治理。
4. **四段链顺序不可调、不可合并、不可省略**（失败语义不同）。
5. **观测失败不得影响运行**：emit/hook/layer.observe 全部吞异常。
6. **全局终止护栏**：控制流可以任意，但任何程序都必须能停下来。
7. **回滚粒度**：业务状态可回滚；journal/usage 是既成事实不回滚。
8. **治理分级**：程序可选实现 describe/to_spec/static_check，
   不透明程序明确降级，不假装支持时间旅行。
9. **fail-closed**：未知异常归类为 FAILED。
10. **契约只增不改**：新增字段必须带默认值，旧调用方零破坏。
11. **注册代替分支**：新增效应类型/前端形态，注册 handler/工厂，内核零改动。
12. **核心零第三方依赖**：SDK 依赖只允许出现在 adapters/。

---

## 12. 上手路径（建议的练习顺序）

```bash
# 环境准备（PowerShell）
$env:PYTHONPATH="$PWD\code\harness\src"
$env:PYTHONIOENCODING='utf-8'

python code/harness/examples/interpret_minimal.py       # 1. 最小解释器
python -m unittest discover -s code/harness/tests -v    # 2. 304 个测试全绿
cd code/harness && PYTHONPATH=. python -m proposals.demo  # 3. 独立样张 14 案例
```

1. **读 `examples/interpret_minimal.py`**（60 行）：裸函数 + 一批并行效应 +
   FnProgram 收尾。亲手把 `effects` 改成 0 个（纯决策步）、把 `program` 改成
   `None`（死循环，观察护栏兜底成 degraded）。
2. **读 `fp/frontends.py` 的 React**（30 行）：理解"循环 = program=self"。
3. **写第 11 种架构**：实现 `transition()` 即可。建议从"双 agent 辩论"开始：
   两个 child 效应交替，一方认同对方即 Halt。
4. **注册自定义效应**：`extra_handlers={"http": my_fetch}`，体会内核零改动。
5. **写一个 EffectLayer**：gate 拦截带敏感词的效应（deny）、
   observe 打印每条效应结果，装配进 `Runtime(layers=…)`。
6. **回溯实验**：程序里保存 `state.snapshot()` 到 `state.data`，某轮决策带
   `restore=` 回去重走，观察 rev 与 journal 的变化。
7. **读验收测试**：`tests/test_interpret.py`（核心验收）、
   `tests/test_unknown_architectures.py`（四种没想过的架构，框架 diff=0）、
   `examples/unknown_architectures.py`。

---

## 附：常见问题

**Q：`Decision` 和 `Transition` 到底用哪个？**
同一样东西。`contracts.decision.Decision` = `Transition` 别名；顶层的
`harness.Decision` 是审批类型，别搞混。

**Q：我的架构需要"循环上限"怎么办？**
两层：程序自己的业务上限（如 React.max_steps）+ 框架的 `Limits` 兜底
（防失控）。前者是架构语义，后者是安全网，职责不同。

**Q：怎么接入真模型？**
两条路：给 `Harness(model=…)` / `Runtime(model=…)` 注入实现 `complete()`
的适配器（见 `adapters/openai.py`）；或测试时用 `state.data["script"]`
脚本回放（内置 handler 原生支持，304 个测试就是这么跑的，零网络）。

**Q：并行失败一个会不会全批失败？**
不会。每个效应独立走四段链，异常被 Classify 归类成 `{"ok": False, …}`，
整批照常提交，由程序决定下一步。
