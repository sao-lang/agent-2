# agent-harness 框架设计规格书

> **版本** 1.0 · 2026-11-04 · 状态：**定稿，可据此实现**
> **范围** `code/harness/`（副线组件基座）
> **基线** `outline/20-副线封装推导.md`（5.0–5.9）与 `outline/vol12-组件封装.md`（第 48–53 章）。基线的**九个插点、十五个组件、四层架构、R1–R7、十二类型十一接口、五种装配形态、四种拓扑**全部保留，本文只做运行时收敛与接口细化。
> **取代** `docs/harness/ARCHITECTURE.md`（已并入本文并删除）
> **读者** 实施方（人或 AI）：据此做任务拆分（§20）、编码（M1–M16）、验收（§1.4 + §21）

---

## 0. 怎么用这份文档

### 0.1 三条使用规则

1. **本文是唯一权威**。代码与本文冲突时改代码；本文没写的，先补本文再写代码，不许自行发明。
2. **每个模块（M1–M16）自带四件套**：职责、完整接口、设计理由、验收要点。实现一个模块只需读它 + §2.5 的依赖规则。
3. **「必须」是硬约束，「禁止」是红线**，二者都能落成测试（§21）。

### 0.2 术语（全文统一）

| 术语 | 含义 | 不要混成 |
|---|---|---|
| **插点（Point）** | 一次 loop 上的九个位置（§2.2）；运行期收敛为四个可包裹插点 | 段 |
| **段（Stage）** | 一次 step 内的四个阶段：Gate → Check → Wrap → Classify | 插点 |
| **组件** | 基线的十五个部件（§2.3），每个挂在一个插点上 | 拓扑 |
| **层（Layer）** | 组成"包裹型插点"的可组合片，有插点、依赖、构建函数 | 类 |
| **程序（Program）** | 若干层 + 一个 body 组合出的策略单元，纯值 | 运行器 |
| **运行器（Harness）** | 持有模型/存储/后端等能力，执行 Program | 策略 |
| **取景 / 编码** | 选内容（`Framer` → `Frame`）/ 变格式（`Encoder` → `Payload`） | Context |
| **闸（Gate5）** | 护栏的五个位置（M9.1） | 段 Gate |

### 0.3 Program 与 Harness 分离（第一条设计决策）

```python
program = react(max_steps=24) >> budget(200_000) >> checkpoint()   # 纯值：可序列化、可 diff、可测试
harness = Harness.of(model="openai:gpt-4.1", tools=[fetch], backends={"fs": "local:/work"})
result  = await harness.run(program, goal)
```

| 职责 | 谁持有 | 为什么不合并 |
|---|---|---|
| 策略（下一步做什么、包几层） | `Program` | 纯值才可比较、可干跑、可在测试里换能力复用；由内置层/插件层构成时还可序列化（限定见 M1.9） |
| 能力（模型、存储、沙箱、密钥） | `Harness` | 资源有生命周期与连接池，不该跟着策略值到处传 |

这条分离让"换后端不改程序"成为**类型上的事实**，而不是约定。

---

## 1. 目标、基线映射、验收

### 1.1 目标与非目标

**目标**

- `pip install` 后 20 行内跑起一个 agent；带沙箱/文件系统/子 agent/任务板的编码 agent ≤ 40 行。
- 同一套包装出：单 agent、Workflow、ReAct、P&E、Supervisor、Handoff、Blackboard、Pipeline。
- 换任何一个部件（模型/检索/记忆/准入/校验/观测/执行后端）不改内核，新增部件不改已有部件。
- 每个部件离线可测：无模型、无网络、无真实文件系统、无真实沙箱。
- 组合式开发体验优先：**策略用组合表达，能力用注入提供**。

**非目标**

- 不做跨进程 A2A（卷 7）、消息队列产品（第 32 章）、鉴权网关、UI 平台（第 41 章）。
- 不替代 LangGraph/LangChain，不追图运行时与 DSL。
- 不做零配置魔法：一切显式、构造期校验、启动即报错。
- 只做**进程内**拓扑；`Board` 是内存对象，不是消息队列。

### 1.2 卷 12 基线映射（逐章，不许丢）

| 章 | 基线内容 | 落到本文 | 保留方式 |
|---|---|---|---|
| 48 | 为什么封装、封装边界；**插点与组件的对应**；什么不该做成组件 | §2.1–§2.3 | 九插点原样保留；"不是组件"清单原样保留（§2.3.2） |
| 49 | 契约先行：**十二个数据类型 + 十一个接口**；契约冻结；`State` 字段演进 | M1 | 12 类型逐字段保留；11 接口全部保留并给 v2 扩展字段 |
| 50 | **主体层**：LoopKernel、三种策略、执行原语（Actor/Tools/Context/Resilience） | M2 内核 + M3 主体层 | 三策略 + 四原语齐备；`Resilience` 五机制单列 |
| 51 | 校验/治理/供给横切：Guard/Budget/Tracer/Durability/Delivery 深写；Router/Context/Knowledge/Memory/Skills 分组 | M4/M5/M6/M7/M8/M9/M10 | 十个横切部件全部独立成节；`Resilience` 五种共享失败计数 |
| 52 | 装配与验证：`build(cfg)`、五个预设、六个例子、**5.8 装配表** | M15 | 装配表五问五槽保留；六例逐个进 §19 |
| 53 | **组合**：`Agent` 与四种拓扑；回收四层；四种拓扑对照成本与失效 | M14 | 四层回收表原样；PDF 四拓扑对照保留 |
| 5.3 | **五种装配形态** + 替换实验 | M16.4 | 五种形态 + 四条替换实验 + 矩阵取点 |
| 5.4 | **R1–R7 依赖规则** | §2.5 | 七条原样，可执行化 |
| 5.9 | 生命周期四个归属（接入/会话/配置/反馈） | M15.5 | 四归属原样保留 |

### 1.3 三条不可协商的架构决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 内核不可替换，只可拦截 | 换成图运行时就不再是"一个内核"，确定性与可测性同时丢失 |
| 2 | Program 与 Harness 分离 | 让"换后端不改程序"从约定变成类型事实 |
| 3 | 组合式（层）为一等形态，类式仅为装配产物 | 可组合、可替换、可干跑；类式装配保留给配置驱动场景 |

### 1.4 验收判据（每期五条）

| # | 判据 | 检验方式 |
|---|---|---|
| 1 | 可替换 | 把某部件换成内存假件，其余代码零改动 |
| 2 | 可组合 | 任意两层交换顺序不崩（除声明的 `after/before` 与安全不变量） |
| 3 | 可回放 | 同 State + 同模型回复序列，重跑结果一致 |
| 4 | 可判定 | 任何失败都映射到 `RunStatus` 的一个值，不允许"抛出去就算" |
| 5 | 可离线 | 全部测试无网络、无真实沙箱、无真实文件系统 |

**最终验收 = 基线 5.7 的矩阵取点**：五种装配形态 × 四种拓扑，取 3 个点，每点跑一次替换实验。

---

## 2. 结构

### 2.1 四个结构事实（推导起点）

| # | 事实 | 推出什么 |
|---|---|---|
| ① | Agent 的本质是**一个循环**：模型输出 → 可能调工具 → 结果回灌 → 再问 | 最小骨架；没有它就是一次性调用 |
| ② | 每步都在**做决定**（要不要调、调哪个、算不算完） | 「决策」类部件 |
| ③ | 决定需要**素材**（工具清单、检索结果、历史、记忆） | 「供给」类部件 |
| ④ | 每件事都**可能出错且不可逆** | 「治理」类部件 |

组件清单 = **循环骨架 + 三类插件**。判据：每个组件必须挂到一次 loop 的一个具体位置。

### 2.2 九个插点（基线，原样保留）

```text
请求进来 ─▶ ① 入口：这是什么请求？走哪条路？
             ▼
          ② 装配：这一轮让模型看见什么
             ▼
 ┌────────── Loop（反复执行）──────────────┐
 │  ③ 判断：要不要先拆成计划？               │
 │        ▼                                │
 │  ④ 决策：下一步做什么？                   │
 │        ▼                                │
 │  ⑤ 准入：这个动作允许吗？要人点头吗？      │
 │        ▼                                │
 │  ⑥ 执行：真的去调工具 / 真的去问模型       │
 │     （超时→重试→限流→熔断→降级 包住这次调用）│
 │        ▼                                │
 │  ⑦ 校验：这一步做对了吗？整体达标了吗？     │
 │        ▼                                │
 │  ⑧ 记账：花了多少？第几步？存档了吗？       │
 │        ▼                                │
 │  回到 ②（下一轮）或退出                    │
 └──────────────────────────────────────────┘
             ▼
          ⑨ 出口：整理结果、留痕、交回
```

### 2.3 十五个组件（基线）与"不是组件"清单

#### 2.3.1 十五个组件

| 插点 | 组件 | 本文模块 | 为什么必须独立 |
|---|---|---|---|
| ① 入口 | `Router` | M4 | 分流决策与执行分离，才能让简单请求跳过高成本路径 |
| ② 装配 | `Context` | M6 | 窗口预算与召回质量是两件事，混在一起无法归因 |
| ③ 判断 | `Planner` | M3 | 计划是"可审查、可修改的数据"，塞进决策就无法 HITL |
| ④ 决策 | `Actor` | M3 | 唯一必需组件；只做执行，不做评估 |
| ⑤ 准入 | `Guard` | M8 | 必须独立于决策：模型被说服了，Guard 不被说服 |
| ⑥ 执行 | `Tools` | M3 | 能力注册与调用分离；执行后端可替换 |
| ⑥ 执行 | `Resilience` | M3 | 五机制共享同一份失败计数；拆开要跨组件共享状态 |
| ⑦ 校验 | `Reflector` | M5 | 必须能拿到**外部**证据；判定与修复共用一个 `Verdict` |
| ⑧ 记账 | `Budget` | M8 | 被三处读取，任一处持有都会造成反向依赖 |
| ⑧ 记账 | `Tracer` | M10 | 跨全部插点，且必须能离线工作 |
| ⑧ 记账 | `Durability` | M11 | 恢复是"重放结论"不是"重新推理" |
| ⑨ 出口 | `Delivery` | M10 | 终止态/输出过滤/引用编号是**决策**不是渲染 |
| 循环外 | `Memory` | M7 | 跨会话；与单次 loop 的 State 生命周期不同 |
| 循环外 | `Knowledge` | M7 | 召回质量独立于窗口预算 |
| 循环外 | `Skills` | M7 | 给流程不给能力；数量级与加载时机都不同 |

#### 2.3.2 不是组件的东西（禁止做成组件）

| 东西 | 它是什么 | 归属 |
|---|---|---|
| `State` | 随 loop 变化且需持久化的容器 | M1 类型 |
| Prompt | 插点②的产物 | M6 `Frame`/`Payload` |
| Provider / Executor | 部件（后端），不是组件 | M12 |
| Cache | `Budget` 的实现策略 | M8 |
| Session | 持久化与隔离的单位（一个键），横跨多次 loop、挂不到任何插点 | M1 `SessionRef`，由 M11 `Durability` 消费 |
| 拓扑 | 组件的组合方式，不改变单次 loop 内部 | M14 |
| 队列 / 调度 | 交付层（第 32 章） | 不进副线 |

### 2.4 四层架构（基线 5.8，第 53 章回收）

**四种层，三种可替换性。**

| 层 | 副线里是什么 | 契约 | 替换实验 |
|---|---|---|---|
| **分派** | 部件 + 数据（唯一两者都有的层） | `Router` + `Route{name, accepts, fallback}` | `Router → AlwaysRoute` |
| **主体** | loop 的**配置**，不是部件 | `Actor`、`Planner`、`config.body ∈ {workflow, react, pe}` | `Planner → ImplicitPlanner`（P&E 退化成 ReAct） |
| **校验** | 部件 + 预算 | `Reflector` + `Verdict` + 重试计数 | `Reflector → NullReflector` |
| **拓扑** | **组合**，不是部件 | `Agent`、`Brief`、`Board`；R7 | `Supervisor ↔ Handoff ↔ Pipeline` |

一句话：**分派是"换一个部件"，主体与校验是"换一个配置"，拓扑是"换一层组合"。**

### 2.5 依赖规则 R1–R7（可执行化的七条）

| 规则 | 表述 | 违反的样子 | 落地方式 |
|---|---|---|---|
| **R1 按插点分层** | 位置靠后的组件不 import 位置靠前的组件 | `Guard` import `Actor` 判断"它要干什么" | §3.2 依赖白名单 + AST 测试 |
| **R2 只依赖契约** | 组件之间只依赖 Protocol / dataclass | `isinstance(x, LLMJudgeReflector)` | 同上；禁止具体类出现在签名里 |
| **R3 数据只走 State** | 跨组件传数据走 State，不做参数层层透传 | `actor.run(plan, ctx, mem, kb, budget, tracer)` | `RunScope` 只传能力，不传数据 |
| **R4 构造只在装配层** | 所有实例化集中在装配层 | 组件内部 `Planner()` | 只允许 `Harness.of()` / `build()` 里 new |
| **R5 治理不可选** | 装配后任何路径都不能跳过 Guard/Budget/Tracer | "内部调用"绕过 Guard | `Gate` 永远是终端前最后一环（§2.6） |
| **R6 每个组件可离线测** | 无模型、无网络能单测 | 测不了 = 耦合了 | M16.3 一致性测试基类 |
| **R7 拓扑不实现能力** | 拓扑只分派与汇总，不自己调模型做事；黑板触发是声明式规则 | `Supervisor` 长出"实在不行我自己答"的分支 | M14 检查项 |

### 2.6 运行时收敛：九插点 → 四个可包裹插点 + 四段执行链

基线的九个插点是**语义位置**；运行期需要**可包裹的边界**。二者映射如下（这是本文对基线的唯一结构性改动，逐条可核对）：

| 基线插点 | 运行期归属 | 包裹方式 |
|---|---|---|
| ① 入口 | 插点 `run` | 层（Router 在 `run` 之前，见 M4） |
| ② 装配 | 插点 `model_call` | `Context`/`InputGuard` 层 |
| ③ 判断 | body（`PlanExecutePolicy` 内部） | 不可包裹（属策略） |
| ④ 决策 | body（`next_step`） | 不可包裹（属策略） |
| ⑤ 准入 | 段 **Gate** | `Guard` 协议 |
| ⑥ 执行 | 段 **Wrap** → 终端 | `Middleware` + `Resilience` |
| ⑦ 校验 | 插点 `step` | `Validate` 层 |
| ⑧ 记账 | 插点 `run`/`step` | `Budget`/`Trace`/`Checkpoint` 层 |
| ⑨ 出口 | 段 **Classify** + `Delivery` | `Filter` + 出口层 |

四个插点：`run` / `step` / `model_call` / `tool_call`。四段：Gate / Check / Wrap / Classify（§M2.2）。

**为什么允许这次收敛**：九个插点里有三个（③判断/④决策/⑥中的客户端调用）不是"包裹一对请求响应"的形状，硬做成中间件会让失败语义混乱。收敛只影响**挂载机制**，不影响任何组件的职责与替换实验——R1–R7 全部保持。

### 2.7 两条不变量（比归位表更重要）

| 不变量 | 内容 | 违反后果 |
|---|---|---|
| **历史不可变** | 任何状态变更都留下带 `rev` 的记录；旧版本永不修改、永不删除 | 不可回放、不可时间旅行、并发写静默覆盖 |
| **资源单一所有者** | 预算、取消信号、span 各有一个所有者，只沿作用域**单向继承** | 子 agent 偷预算、父取消子不停、span 挂错父 |

### 2.8 归位表（审计工具，不是模型）

| 位置 ＼ 挂载 | 替换（实现协议） | 包裹（层） | 观察（hook） |
|---|---|---|---|
| `run` | `Router` 策略、`Delivery` | Tenancy / Budget / Audit / Trace | `on_run_start/end` |
| `step` | `BodyPolicy` | TaskBoard / Validate / Checkpoint | `on_step_end` |
| `model_call` | `Model`、`Framer`、`Encoder`、`Knowledge` | Context / Cache / InputGuard / OutputGuard | `on_model_call` |
| `tool_call` | `Tool`、`FileSystem`、`Sandbox`、`Index` | Approval / 沙箱路由 / 幂等 / 截断 / SubAgent / Capability | `on_tool_call` |
| 出口 | `Delivery` | OutputGuard | `on_run_end` |
| 构造期 | 全部协议实现 | 插件 | — |

用法：任何改动先在表里指一个格子。指不到 → 协议缺了，补契约，禁止给内核开洞；指到两个 → 职责重叠；指到内核 → 不允许。

**这张表不能当模型**：它只归档不推导、没有时间维度（持久化无位）、没有所有权维度（预算/取消/span 归属无位）、空格子会诱发填充。真正的主模型是 §2.7 的两条不变量。

**判据**：一个特性若既不改变任何不变量、也不落在表里任何格子，它是应用代码，不进框架。

---

## 3. 分层与依赖规则

### 3.1 七层

```text
L6 适配器   adapters/    openai · qdrant · otel · mcp（只被装配层懒加载）
L5 门面     fp/          组合式 API：层、程序、运行器
L4 装配     assembly/    配置校验、Harness 构造、插件、预设
L3 部件     parts/       router · policy · framing · middleware · guardrail · topology · validate
L2 实现     impl/        InMemory* / Local* / Sqlite* / Fakes
L1 契约     contracts/   类型 · 协议 · 事件 · 错误 · 版本
L0 内核     kernel/      循环 · 四段 · 链 · 作用域
```

### 3.2 依赖白名单（唯一铁律）

> **只向内，不向上：任何模块只能依赖自己所在层与更内层的模块；层与层之间不得成环。**

**P1 实施修正**：初稿写的是"除内核外只允许指向 `contracts`"，落地时发现这条不可执行——同一层内的实现必然共享工具（`memory` 用 `knowledge` 的 `_score`、`skills` 用 `body` 的 `WorkflowPolicy`）。**禁止同层依赖只能靠把所有共享工具塞进契约层**，那会污染"零依赖"。所以改成六边形架构的标准表述：**同一层内部允许互依，约束方向与成环**。

| 模块 | 允许依赖 |
|---|---|
| `contracts` | 仅自身（且**零第三方依赖**） |
| `kernel` | `contracts` |
| `parts` | `contracts` `parts`（同层） |
| `impl` | `contracts` `impl`（同层） |
| `assembly` | `contracts` `kernel` `parts` `impl`（同层） |
| `fp` | `contracts` `kernel` `parts` `assembly`（门面要驱动内核循环） |
| `adapters` | 全部（只被 `assembly` 懒加载） |

禁令：禁止向上依赖（`parts` ↛ `kernel`）；禁止层间成环（`kernel → parts` 与 `parts → kernel` 不能同时存在）；`__init__.py` 只做导出不做初始化。

### 3.3 用测试守住

```python
# tests/test_architecture.py（已落地，P1）
ALLOWED = {
    "contracts": {"contracts"},
    "kernel": {"contracts", "kernel"},
    "parts": {"contracts", "parts"},
    "impl": {"contracts", "impl"},
    "assembly": {"contracts", "kernel", "parts", "impl", "assembly"},
    "fp": {"contracts", "parts", "assembly", "fp"},
}
# 四条用例：目录存在、依赖方向、契约层零三方依赖、层间无环
```

### 3.4 目标文件树

### 3.4 目标文件树

```text
src/harness/
├── contracts/  version.py status.py types.py errors.py events.py protocols/{model,tools,body,
│               runtime,guards,guardrails,framing,stores,backends}.py
├── kernel/     loop.py stage.py chain.py scope.py
├── parts/      router/ policy/ framing/ middleware/ guardrail/ topology/ validate/ resilience/
├── impl/       stores/ backends/ fakes/
├── assembly/   config.py app.py plugins.py presets.py
├── fp/         layer.py ops.py runtime.py topo.py
└── adapters/   openai.py qdrant.py otel.py mcp.py
```

#### 3.4.1 落地状态（P1 已完成的过渡布局）

目标树中的子包划分属 P3/P4 工作。**P1 先保证分层与依赖方向正确**，目录内部暂为扁平：

| 目标 | P1 实际 | 何时对齐 |
|---|---|---|
| `contracts/{types,status,events,protocols}/` | ✅ `types.py`+`status.py`+`events.py`+`protocols/{model,tools,body,runtime,guards,framing,stores,backends,governance}.py` | P2 已完成 |
| `kernel/{loop,stage,chain,scope}.py` | `kernel/{stage,chain,scope}.py` ✅；`loop.py` 待 P4（Agent 仍用 v1 循环） | P4 |
| `parts/{policy,framing,middleware,...}/` | ✅ `parts/framing/`、`parts/middleware/`；其余仍扁平 + `parts/body/` | P4 后半 |
| `impl/{stores,backends,fakes}/` | ✅ `stores/memory.py`、`backends/{paths,fs,core}.py`、`fakes.py` | P3 已完成 |
| `assembly/{config,harness,registry,fpresets}.py` | ✅ 已就位；v1 的 `agent/build/presets` 保留兼容 | P6 已完成 |
| `fp/*` | 空包 + 文档字符串 | P5 |
| 兼容壳 | `harness/{errors,testing,state,result}.py` 再导出旧路径 | P2 起逐个删除 |

**为什么 `Agent` 放在 `assembly` 而不是 `kernel`**：`Agent` 要 `new` 具体部件（`Actor`/`Guard`/`Tracer`），违反"内核只依赖契约"。它是组合产物，属装配层（R4：构造只在装配层）。

---

## 模块 M1 · 契约层

**职责**：定义全部类型、协议、事件、错误。零依赖（仅标准库），不 import 同包任何模块。

**为什么单独成层**：契约层是"什么可替换"的白名单。它一旦依赖具体实现，"换后端不改程序"就只是口号。零依赖可机械验证，所以它当白名单最可靠。

### M1.1 五条设计纪律

| # | 纪律 | 理由 |
|---|---|---|
| 1 | **窄而深**：一个协议最多 4 个方法 | 宽接口没人写第二个实现，可替换性就死了 |
| 2 | **全 async** | 同步封装只留最外层，内部不允许两条调用路径 |
| 3 | **命名空间强制**：涉及数据归属的方法首参是 `Namespace` | 不给无 namespace 的重载，多租户漏一个 `where` 就是事故 |
| 4 | **数据类型只增不改**：新增字段必须有默认值 | 契约冻结才能让部件独立演进 |
| 5 | **每个协议配一个内存实现 + 一组一致性测试** | 没有这两样，协议只是愿望 |

### M1.2 基线十二个数据类型（逐字段保留）

| 类型 | 基线字段 | v2 增补（有默认值） |
|---|---|---|
| `Goal` | `text: str`、`user_id: str`、`session_id: str` | `metadata: dict = {}` |
| `Step` | `index: int`、`plan_id: str`、`instruction: str`、`tool_name: str \| None`、`args: dict`、`idem_key: str` | `id: str = ""`、`kind: Literal["tool","llm","agent","human"] = "tool"` |
| `ToolCall` | `name: str`、`args: dict` | `id: str = ""` |
| `ActionResult` | `step: Step`、`ok: bool`、`output: str`、`error: str \| None`、`tokens: int` | `citations: list[str] = []`、`artifacts: list[ArtifactRef] = []` |
| `Verdict` | `passed: bool`、`reason: str`、`action: Literal["accept","retry","patch","replan_all"]` | — |
| `Plan` | `id: str`、`steps: list[Step]`、`rev: int` | — |
| `Recalled` | `text: str`、`layer: Literal["semantic","episodic","procedural"]`、`score: float`、`source: str`、`age_days: int` | `dedup_key: str = ""`、`id: str = ""`、`superseded_by: str = ""` |
| `Pack` | `messages: list[dict]`、`usage: dict[str,int]`、`dropped: list[str]` | `frame: Frame \| None = None` |
| `SessionRef` | `session_id: str`、`tenant: str`、`started_at: str` | — |
| `Brief` | `goal: Goal`、`context_refs: list[str]`、`done: list[str]`、`forbidden: list[str]`、`deadline: float \| None` | — |
| `Board` | `state: State`、`rev: int`、`owner: str \| None` | — |
| `Route` | `name: str`、`accepts: list[str]`、`fallback: bool` | — |

**`State` 的字段演进（基线 5.5 约束 4 + v2）**

```python
@dataclass
class State:
    goal: Goal
    session: SessionRef
    step_index: int = 0
    messages: list[dict] = field(default_factory=list)
    plan: Plan | None = None                 # 基线字段
    verdicts: list[Verdict] = field(default_factory=list)   # 基线字段
    budget_used: dict[str, int] = field(default_factory=dict)  # 基线字段
    # v2 增补
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    data: dict[str, Any] = field(default_factory=dict)   # 各层命名空间，必须可 JSON 化
    status: RunStatus = RunStatus.RUNNING
    last_error: str | None = None
    rev: int = 0

    def section(self, name: str) -> dict[str, Any]: ...   # 取/建命名空间
    def to_dict(self) -> dict[str, Any]: ...              # 带 schema_version
    @classmethod
    def from_dict(cls, raw: dict) -> "State": ...          # 走迁移函数
```

| 约束 | 理由 |
|---|---|
| `State` 是唯一可变载体；组件之间不传 State 的字段，只传 State 本身（R3） | 传字段等于隐式耦合 |
| `messages` 追加、不改写 | 与"历史不可变"一致；压缩发生在取景，不发生在存储 |
| `to_dict` 带 `schema_version` | 旧数据能读；不允许"读旧数据直接崩" |
| 禁止放连接、句柄、锁、客户端、session 对象 | 不可 JSON 化 → 不可重放 → 检查点失效 |

### M1.3 基线十一个接口（签名保留，注明 v2 调整）

| 接口 | 基线签名 | v2 落地 | 为什么这样调整 |
|---|---|---|---|
| `Actor` | `step(step, state) -> ActionResult` | 保留；新增 `propose(state) -> Step \| Done` | ReAct 需要"先决策再执行"，基线把两件事塞进 `step` |
| `Tool` | `name: str`、`schema() -> dict`、`invoke(args) -> str` | `spec: ToolSpec`、`invoke(args, ctx: ToolContext) -> ToolResult` | 工具需要元数据（副作用/超时/幂等）与能力注入 |
| `Planner` | `plan(goal, state) -> Plan` | 保留 | — |
| `Reflector` | `review(result, plan) -> Verdict` | `review(result: ActionResult, state) -> Verdict` | 判定要看得见 State（含外部证据），不是只看 plan |
| `Context` | `assemble(state, budget) -> Pack` | 拆为 `Framer.frame()` + `Encoder.encode()` | 选择与格式是两个变化原因（M6） |
| `Memory` | `recall(query, scope, layers, k)`、`write(items)` | 加 `forget`、`expire`，`scope` → `Namespace` | 缺遗忘与过期就不是记忆，只是日志 |
| `Budget` | `remaining() -> int`、`spend(tokens)` | `remaining_tokens/remaining_calls`、`spend(tokens, calls)`、`owner` | 被三处读取（循环/策略/子 agent），口径必须统一 |
| `Durability` | `save(state, key)`、`load(key) -> State` | `put(state, expect_rev) -> int`、`get(rev)`、`history()` | 覆盖写违反"历史不可变" |
| `Tracer` | `span(name, **fields)`、`on_event(name, payload)` | `emit(event: RunEvent)` 单方法 | 一个出口，事件类型由枚举约束 |
| `Agent` | `run(goal, state) -> State`、`run_once(goal, state) -> (State, str\|None)` | `run(goal, *, scope) -> RunResult` | 出口必须有 `RunStatus`，不能只回 State |
| `Topology` | `run(goal) -> State`、`name: str` | `run(goal, *, scope) -> RunResult`、`children` | 与 `Agent` 同签名才可嵌套 |

### M1.4 v2 完整数据类型（30 个，按角色）

| 角色 | 类型 |
|---|---|
| 标识 | `Namespace(tenant, user, session, agent)`、`SessionRef`、`RunId`、`TraceId` |
| 输入 | `Goal`、`Brief`、`TaskSpec` |
| 过程 | `Step`、`ToolCall`、`Plan`、`ModelReply(content, tool_calls, usage, finish_reason)`、`ModelDelta(kind, text, index, usage)` |
| 判定 | `Verdict`、`GuardDecision(action, reason, card, expires_in)`、`GuardrailVerdict(risk, labels, action, spans, replacement)`、`Decision(action, by, reason, args)` |
| 结果 | `ActionResult`、`ToolResult`、`ExecResult(exit, stdout, stderr, artifacts, truncated, timed_out)`、`RunResult`、`Pack`、`Failure(status, reason, retryable)` |
| 视图 | `Frame(kind, sections, dropped, tokens_est, meta)`、`Section(name, priority, source, text, tokens_est, ephemeral)`、`Recalled`、`Card` |
| 状态 | `State`、`Checkpoint(session_id, rev, state, created_at)`、`SessionMeta`、`Page(items, cursor)` |
| 治理 | `Budget`、`Limits(cpu_s, mem_mb, wall_s, output_bytes, network)`、`Mount(target, source, mode)`、`ApprovalRequest`、`Recorded(key, value, at)` |
| 事件 | `RunEvent(id, trace_id, span_id, parent_id, name, kind, ts_ms, fields)`、`HookEvent` |

### M1.5 四种判定为什么不能合并

| 判定 | 谁产生 | 回答什么 | 失败语义 | 能否改变执行 |
|---|---|---|---|---|
| `GuardDecision` | `Guard` | 这个**动作**能不能做 | deny → `REFUSED` | 能（短路） |
| `GuardrailVerdict` | `Guardrail` | 这段**内容**能不能进出 | block → 拒绝/改写 | 能（改写内容） |
| `Verdict` | `Reflector` | 这个**结果**够不够好 | 差 → retry/replan | 能（回到循环） |
| `Decision` | 人 | 批不批 | reject → `REFUSED` | 能（挂起/恢复） |

合并的后果：护栏 block 与 Guard deny 都返回 `REFUSED`，但前者该"改写后继续"、后者该"停下"，合并后只能靠错误字符串猜。

### M1.6 协议总表（33 个）

| 模块 | 协议 | 方法数 | 可空实现 |
|---|---|---|---|
| M3 | `Actor` | 2（`step`/`propose`） | `ScriptedActor` |
| M3 | `Tool` | 1（`invoke`） | `NoopTool` |
| M3 | `BodyPolicy` | 1（`next_step`） | `React` |
| M3 | `Planner` | 1（`plan`） | `ScriptedPlanner` |
| M3 | `Resilience` | 1（`call`） | `NoResilience` |
| M4 | `Router` | 1（`route`） | `AlwaysRoute` |
| M5 | `Reflector` | 1（`review`） | `NullReflector` |
| M5 | `Validator` | 1（`validate`） | `AnswerNonEmpty` |
| M6 | `Framer` | 1 | 四内置 |
| M6 | `Encoder` | 1 | 多格式 |
| M7 | `Memory` | 4 | `InMemory` |
| M7 | `MemoryPolicy` | 4 | `Conservative` |
| M7 | `Knowledge` | 1（`retrieve`） | `InMemory` / `NullKnowledge` |
| M7 | `Skills` | 3（`catalog`/`load`/`resource`） | `SkillRegistry` |
| M8 | `Guard` | 2（`check`/`check_identity`） | `AllowAll` / `DenyAll` |
| M9 | `Guardrail` | 1 | `NullGuardrail` |
| M9 | `GuardrailStream` | 2 | — |
| M10 | `Delivery` | 1（`finish`） | `DefaultDelivery` |
| M10 | `Tracer` | 1（`emit`） | `Null` / `Memory` / `Jsonl` |
| M10 | `EventSink` | 1 | 同上 |
| M11 | `Durability`（`CheckpointStore`） | 3 | `InMemory` / `Sqlite` |
| M11 | `SessionStore` | 4 | `InMemory` |
| M11 | `MessageLog` | 2 | `InMemory` |
| M11 | `Idempotency` | 2 | `InMemory` |
| M12 | `Model` | 2 | `FakeModel` |
| M12 | `FileSystem` | 6 | `LocalFS` / `FakeFS` |
| M12 | `Sandbox` | 2 | `Subprocess` / `FakeSandbox` |
| M12 | `ArtifactStore` | 3 | `Memory` / `Local` |
| M12 | `SecretBroker` | 2 | `Env` / `Memory` |
| M12 | `IndexBackend` | 2 | `InMemory` |
| M12 | `Queue` | 3 | `Memory` |
| M12 | `ApprovalChannel` | 3 | `Callback` |
| M12 | `Clock` | 2 | `System` / `FakeClock` |
| M13 | `Middleware` | 1 | — |
| M13 | `Hook` | 1 | `nullhook` |
| M13 | `Filter` | 1 | `DefaultFilter` |
| M13 | `Pipe` | 1 | `Identity` |
| M14 | `Runnable`（`Agent`） | 1 | — |
| M14 | `Topology` | 1 | 四内置 |

### M1.7 挂载层的请求/响应类型（`Middleware` 的入参与返回值）

层的签名在 M2/M13 反复出现，这里一次定义清楚。四个插点各一对请求/响应，`Request`/`Response` 是它们的联合：

```python
@dataclass(frozen=True)
class RunRequest:    goal: Goal;  ns: Namespace
@dataclass(frozen=True)
class StepRequest:   state: State; step: Step | Done
@dataclass(frozen=True)
class ModelRequest:  state: State; messages: tuple[Message, ...]
                     tools: tuple[dict, ...]; budget: Budget; frame: Frame | None
@dataclass(frozen=True)
class ToolRequest:   state: State; step: Step; spec: ToolSpec

@dataclass(frozen=True)
class RunResponse:   result: RunResult
@dataclass(frozen=True)
class StepResponse:  step: Step
@dataclass(frozen=True)
class ModelResponse: reply: ModelReply; usage: dict[str, int]
@dataclass(frozen=True)
class ToolResponse:  result: ToolResult

Request  = RunRequest | StepRequest | ModelRequest | ToolRequest
Response = RunResponse | StepResponse | ModelResponse | ToolResponse
Handler  = Callable[[Request], Awaitable[Response]]
```

| 约束 | 理由 |
|---|---|
| 请求/响应全部 `frozen` | 层改结果的方式是**构造新的 Response**，不是原地改；否则无法判断谁改了 |
| 一个层只处理自己 `points` 声明的请求类型 | 混用会让 `isinstance` 分支失控 |
| `ToolResponse` 携带完整 `ToolResult`（含 `artifacts`/`meta`） | 截断、脱敏、落 artifact 都在层里完成，结果必须能表达 |
| `RunResponse` 携带 `RunResult` | 出口层（`OutputGuard`）要在最终答案上动手 |

### M1.8 `RunResult`、`Message`、`Span`

```python
@dataclass
class RunResult:
    status: RunStatus                     # 七态之一；禁止 RUNNING
    answer: str = ""
    state: State | None = None
    usage: dict[str, int] = field(default_factory=lambda: {"tokens": 0, "calls": 0})
    citations: list[str] = field(default_factory=list)
    pending: ApprovalRequest | None = None
    error: str | None = None
    trace_id: str = ""
    rev: int = 0                          # 指向最终检查点，供 resume / 时间旅行
    metadata: dict[str, Any] = field(default_factory=dict)
    @property
    def ok(self) -> bool: ...             # COMPLETED | DEGRADED

@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[dict, ...] = ()     # assistant 发起
    tool_call_id: str = ""                # tool 回填
    name: str = ""

@dataclass
class Span:
    trace_id: str; span_id: str; parent_id: str | None
    name: str; start_ms: int; end_ms: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    def end(self, **fields) -> None: ...
```

### M1.9 可序列化形态：`LayerSpec` / `ProgramSpec`（解决"组合值可存库"）

`Layer` 持 `build: Callable`（闭包），**不可序列化**。所以每个层都必须同时提供"声明形态"：

```python
@dataclass(frozen=True)
class LayerSpec:
    name: str                              # "budget" / "checkpoint" / "plugin:x"
    config: dict[str, Any] = field(default_factory=dict)     # 必须是 JSON 可表达

@dataclass(frozen=True)
class ProgramSpec:
    body: str = "react"                    # react | workflow | pe | skill_program
    max_steps: int = 24
    workflow: tuple[dict, ...] = ()
    layers: tuple[LayerSpec, ...] = ()

def compile_layer(spec: LayerSpec) -> Layer: ...      # 注册表：name → 工厂(config) → Layer
def compile_program(spec: ProgramSpec) -> Program: ...
```

| 规则 | 说明 |
|---|---|
| 内置层与已注册插件层**必须**可 `to_spec()` | 保证 `Program` 能存库、能 diff、能由配置文件生成 |
| 用户自写的闭包层 **不可** `to_spec()`，调用即抛 `NotSerializable` | 诚实边界：闭包里的状态无法序列化，不假装可以 |
| `config` 只允许 JSON 类型 | 保证规格能被配置文件、数据库、HTTP 原样传输 |

**因此 §0.3 的"可序列化"准确表述是**：`Program` 在**由内置层/插件层构成时**可序列化；否则退化为"可比较、可干跑、可测试"。这条限定必须写进 `to_spec()` 的文档字符串。

### M1.10 效果即数据（`dry_run` 的类型）

```python
@dataclass(frozen=True)
class Effect:
    kind: Literal["model", "tool"]
    step: Step
    spec: ToolSpec | None                 # kind=="tool" 时非空
    est_tokens: int = 0
```

`harness.dry_run(program, goal) -> list[Effect]` 走完整四段链，但把终端替换成"记录不执行"。用途：① 上线前看这一步会做什么；② 一致性测试离线跑；③ 审批卡片展示"批准后会发生什么"。

### M1.11 辅助类型字段（后端实现需要）

| 类型 | 字段 | 备注 |
|---|---|---|
| `Document` | `id: str`、`text: str`、`metadata: dict`、`vector: list[float] \| None = None` | 索引写入单元 |
| `Job` | `id: str`、`kind: str`、`payload: dict`、`not_before: float = 0`、`attempts: int = 0`、`dedup_key: str = ""` | 队列单元 |
| `Match` | `path: str`、`line: int`、`text: str` | `grep` 返回 |
| `Stat` | `path: str`、`size: int`、`mtime: float`、`mode: int`、`is_dir: bool` | `stat` 返回 |
| `ArtifactRef` | `uri: str`、`bytes: int = 0`、`sha256: str = ""`、`content_type: str = ""` | 只放引用，不放内容 |
| `ArtifactMeta` | `ref: ArtifactRef`、`created_at: float`、`expires_at: float \| None = None` | — |
| `SessionMeta` | `id: str`、`tenant: str`、`user_id: str`、`title: str = ""`、`status: str = "active"`、`created_at: float = 0`、`last_active: float = 0`、`quota: dict[str, int] = {}`、`pinned_model: str \| None = None` | `quota` 见 M8.4 |
| `Card` | `title: str`、`body: str`、`fields: dict[str, str] = {}`、`actions: tuple[str, ...] = ()` | 审批/人读视图 |
| `ResponseFormat` | `kind: Literal["text", "json_schema"] = "text"`、`schema: dict \| None = None` | 模型结构化输出 |
| `StreamState` | `buffer: str = ""`、`blocks: int = 0`、`resumed: bool = False` | 流式护栏用 |

**规则**：这些类型只增不改，新增字段必须有默认值（M1.1 纪律 4）。后端实现只依赖这些字段，不得要求调用方传额外参数。

---

## 模块 M2 · 内核

**职责**：唯一循环（`LoopKernel`）、四段执行链、链执行器、作用域。**不含任何策略。**

**为什么必须最小**：内核是唯一不可替换的东西。它每多一个职责，就多一处不能替换的代码。

### M2.1 LoopKernel

```python
async def run_loop(program: Program, goal: Goal, scope: RunScope) -> RunResult:
    state = await scope.durability.load_or_new(goal, scope)
    while state.step_index < program.max_steps:
        if scope.budget.exhausted:
            return await scope.delivery.finish(state, RunStatus.DEGRADED, reason="budget")
        decision = await program.body.next_step(state, scope)      # ④ 决策
        if isinstance(decision, Done):
            return await scope.delivery.finish(state, RunStatus.COMPLETED, answer=decision.answer)
        step = await run_stages(decision, state, scope)            # ⑤⑥⑦
        state.step_index += 1
        await scope.durability.put(state, expect_rev=state.rev)    # ⑧ 记账/存档
    return await scope.delivery.finish(state, RunStatus.DEGRADED, reason="max_steps")
```

| 约束 | 理由 |
|---|---|
| 循环里只有四个动作（取步/四段/记账/存档） | 任何第五个动作都是策略泄漏 |
| 终止只有三种：`Done` / 预算 / 步数上限 | 与第 7 章三终止一致，不允许第四种 |
| 每步结束必落盘 | 实现"历史不可变"；崩溃后可续跑 |
| **禁止**在循环内 `return` 到出口以外 | 出口唯一 |

### M2.2 四段执行链（定死，不可改）

```python
async def run_stages(step: Step, state: State, scope: RunScope) -> Step:
    for stage in scope.stages:            # Gate → Check → Wrap → Classify，固定顺序
        step = await stage(step, state, scope)
    return step
```

| 段 | 协议 | 输入 → 输出 | 失败方式 | 允许 | 禁止 |
|---|---|---|---|---|---|
| **Gate** | `Guard` | `Step` → `GuardDecision` | 返回 `deny`/`ask`，**不抛异常** | 短路：拒绝或转人工 | 改参数、改结果、做 IO |
| **Check** | `Pipe` | `Step` → `Step` | 抛 `ValidationError` | 参数校验、补全、转换 | 短路、做 IO |
| **Wrap** | `Middleware` | `ToolRequest` → `ToolResult` | 异常原样穿透 | 改请求、改结果、重试、记账 | 跳过 Gate、伪造 `ToolResult` |
| **Classify** | `Filter` | `Exception` → `Failure` | 不吞异常，只归类 | 决定出口状态与重试性 | 重试、降级、改数据 |

**为什么四段不能合并**：合并后三个问题没有答案——Gate 拒绝后还要不要走 `Wrap(after)`？Check 抛错算不算运行失败？Classify 在洋葱里是第几层？

**洋葱只存在于 `Wrap` 段**，且只有一种实现：

```python
def wrap(layers: Sequence[Middleware], terminal: Handler) -> Handler:
    return reduce(lambda nxt, m: partial(m, nxt=nxt), reversed(layers), terminal)
```

等价于 `m1 >> m2 >> … >> terminal`：洋葱与组合是同一实现的两种写法。

#### M2.2.1 `Check` 段：`Pipe` 的四个内置实现

| Pipe | 行为 | 失败 |
|---|---|---|
| `SchemaPipe(schema)` | 按 JSON Schema 校验必填/类型/枚举/`additionalProperties` | `ValidationError(field="args.amount", expect="integer")` |
| `CoercePipe()` | `"100"`→`100`、`"true"`→`True`、单值→单元素列表 | 无法无损转换 → `ValidationError`（**不猜**：`"abc"` 不会变成 `0`） |
| `DefaultPipe()` | 按 schema 的 `default` 填缺省 | 无默认值且必填 → 交给 `SchemaPipe` 报错 |
| `CompositePipe(*pipes)` | 顺序执行，短路于第一个失败 | 同左 |

**固定顺序**：`DefaultPipe → SchemaPipe → CoercePipe`（先补默认、再校验、最后转换）。理由：校验必须在转换后复核，否则 `"1.5"→1` 的静默截断无人发现；转换后再跑一次轻量校验（`CoercePipe` 内部自带类型断言）。

| 约束 | 理由 |
|---|---|
| `Pipe` 只能改 `Step.args`，不能改 `tool_name` | 换工具 = 换风险面，必须走审批 |
| 校验失败 → `ValidationError`（不是 `ToolError`） | 前者是 `REFUSED`，后者要回灌模型自愈 |
| 错误信息必须带字段路径 | 否则模型不知道改哪个参数 |

### M2.3 链执行器

```python
def resolve(layers: Sequence[Layer], point: Point) -> list[Middleware]:
    """筛出该插点的层，按 after/before 拓扑排序；有环 → ConfigError。"""

async def execute(layers, req: Request, terminal: Handler) -> Response:
    """洋葱执行；每层名写入 trace span；异常不重新包装。"""
```

| 规则 | 理由 |
|---|---|
| 只对**同一插点**内的层排序 | 跨插点顺序由循环结构决定 |
| 顺序冲突（环）→ `ConfigError` | 启动期报错，不拖到运行期 |
| 每层执行前后各发一个 span | 深层嵌套时栈帧变长，span 是唯一可靠定位手段 |
| 异常不重新包装 | 重复包装会让 `Filter.classify` 拿不到原始类型 |

### M2.4 作用域

```python
@dataclass(frozen=True)
class RunScope:
    namespace: Namespace
    model: Model; tools: ToolRegistry; actor: Actor
    budget: Budget
    durability: Durability; sessions: SessionStore; messages: MessageLog; memory: Memory
    artifacts: ArtifactStore; fs: FileSystem | None; sandbox: Sandbox | None
    secrets: SecretBroker; index: IndexBackend | None
    tracer: Tracer; events: EventSink; delivery: Delivery; clock: Clock
    guard: Guard; guardrails: tuple[Guardrail, ...]
    config: RuntimeConfig
    def child(self, name: str, *, budget_fraction: float = 0.3) -> "RunScope": ...

@dataclass
class StepScope:
    run: RunScope; state: State; step: Step; span: Span
```

| 选择 | 理由 |
|---|---|
| 一个 frozen `RunScope` 装全部能力 | 层拿能力靠参数，不靠全局单例；冻结保证层无法换能力 |
| 子 agent 用 `child()` 派生 | 实现"资源单一所有者"：新 namespace、切分预算、新沙箱、span 挂父 |
| 作用域不带可变状态 | 可变状态只有 `State` |

**禁止**：模块级单例、`contextvars` 隐式传能力。

---

## 模块 M3 · 主体层

**职责（基线第 50 章）**：`LoopKernel` 的决策部分与执行原语。四种形态：固定工作流 / ReAct / P&E / Skill 程序。

> `LoopKernel` 在 M2；本模块负责 `Actor`、`Tools`、`Context`（见 M6）、`Resilience`、三种 `BodyPolicy`、`Planner`。

### M3.1 `Actor`（插点 ④ 决策 + ⑥ 执行）

```python
class Actor(Protocol):
    async def propose(self, state: State, scope: RunScope) -> Step | Done: ...   # ④ 决定下一步
    async def step(self, step: Step, state: State, scope: RunScope) -> ActionResult: ...  # ⑥ 执行
```

| 约束 | 理由 |
|---|---|
| **只做执行，不做评估**（基线 5.2） | 评估在 `Reflector`；混进来就无法替换其一 |
| `propose` 内部完成"取景 → 编码 → 模型 → 解析 tool_call" | 这三步是决策的实现细节，不外泄到策略 |
| 每次模型调用都记账到 `state` 与 `budget` | 预算单一所有者是 run scope |

`Actor` 的默认实现 `LlmActor`：

```text
propose:
  frame ← scope.framing.framer.frame(state, budget)      # ② 装配（M6）
  pack  ← scope.framing.encoder.encode(frame)
  reply ← resilience.call(lambda: model.complete(pack.messages, tools=schemas))
  记账；reply.tool_calls 非空 → Step(tool_name=第一个, args=参数, idem_key=派生)
  否则 → Done(answer=reply.content)
```

### M3.2 `Resilience`（插点 ⑥ 的执行包裹，五机制共享一份失败计数）

```python
@dataclass
class Resilience(Protocol):
    async def call(self, fn: Callable[[], Awaitable[T]], *, key: str) -> T: ...

@dataclass
class Policy:                      # 五机制的统一配置
    timeout_s: float = 30.0
    retries: int = 2
    backoff_s: float = 0.2         # 指数退避基数
    max_qps: float | None = None   # 限流
    breaker: int = 5               # 熔断：连续失败次数
    breaker_cooldown_s: float = 30.0
    degrade: Callable[[], T] | None = None   # 降级兜底
```

| 机制 | 行为 | 为什么必须与其他机制共享计数 |
|---|---|---|
| 超时 | `asyncio.wait_for` 包住一次调用 | 超时算一次失败 |
| 重试 | 有界退避；只对 `TransientError` | 重试耗尽要记入熔断计数 |
| 限流 | 令牌桶，按 `key`（工具名/模型名） | 限流拒绝也应按同一口径计失败 |
| 熔断 | 连续失败达阈值 → 直接失败 + 冷却 | 熔断依赖重试与超时的失败计数 |
| 降级 | 熔断期间返回 `degrade()` 结果 | 降级是熔断的出口，不是独立策略 |

**为什么五机制必须同一组件**（基线 5.2 原文）：拆开要跨组件共享状态。所以 `Resilience` 持有 `dict[key, FailureCounter]`，五机制共读共写。

### M3.3 三种 `BodyPolicy`

```python
class BodyPolicy(Protocol):
    name: str
    async def next_step(self, state: State, scope: RunScope) -> Step | Done: ...
```

| 形态 | 类 | 何时选 | 行为 |
|---|---|---|---|
| 固定工作流 | `WorkflowPolicy(steps, on_tool_error="stop")` | 步骤**能提前写死** | 顺序吐 `Step`；耗尽 → `Done`；首个失败默认整体失败 |
| ReAct | `ReactPolicy(max_tool_calls=1)` | 下一步依赖上一步观察 | 每轮 `Actor.propose`；一轮只取第一个 `tool_call` |
| P&E | `PlanExecutePolicy(planner, max_replan=2)` | 长任务、计划需人审 | 先 `plan` 再逐步执行；`reflector` 可 retry/patch/replan_all |
| Skill 程序 | `SkillProgramPolicy(skill)` | 有现成 SOP | 加载 skill 的 workflow.json 编译成 `WorkflowPolicy` |

| 约束 | 理由 |
|---|---|
| `Planner` **只属 P&E** | ReAct/Workflow 持有 Planner 会产生"隐式规划"，无法归因 |
| 重试/重规划次数上限写死在策略里 | 否则 Reflection 自激 |
| 达到 `max_steps` → `Done(reason="max_steps")` | 与内核上限同义，不允许两套终止 |
| v1 用 `policy.__class__.__name__ == "WorkflowPolicy"` 判断中止（[agent.py:238](../../code/harness/src/harness/agent.py)） | **删除**，改为 `on_tool_error` 显式属性 |

### M3.4 `Planner`

```python
class Planner(Protocol):
    async def plan(self, goal: Goal, state: State) -> Plan: ...
```

实现：`ScriptedPlanner`（固定计划，测试用）、`LlmPlanner(llm, checks=[max_steps(3), tool_whitelist(...)])`（LLM 出计划 + 代码校验）。

**为什么计划是数据不是控制流**（基线 5.2）：计划要可审查、可修改、可 HITL、可 diff；塞进决策里就做不到。

### M3.5 `Tools`（插点 ⑥ 执行原语）

```python
class Tool(Protocol):
    spec: ToolSpec
    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]                  # JSON Schema
    side_effects: Literal["pure","read","write","net","shell"] = "pure"
    scopes: frozenset[str] = frozenset()        # fs:read fs:write sandbox:exec net:* secrets:*
    timeout_s: float | None = None
    idempotent: bool = False
    max_output_bytes: int = 32_000              # 超出转 artifact，只回摘要
    needs_approval: bool = False
    sandbox: bool = False                       # 必须进沙箱执行

@dataclass(frozen=True)
class ToolContext:                              # 能力按 spec.scopes 注入
    fs: FileSystem | None
    sandbox: Sandbox | None
    artifacts: ArtifactStore
    secrets: SecretBroker
    state: State
    signal: asyncio.Event                       # 取消信号（不变量 2）
```

| 字段 | 驱动什么 | 为什么必须有 |
|---|---|---|
| `side_effects` | 审批分级、幂等要求、沙箱路由 | 靠名字猜副作用不可靠（`send`/`update`/`apply` 都可能写库） |
| `scopes` | 能力注入白名单 | 工具只能拿到声明过的能力，防"顺手读个密钥" |
| `timeout_s` | 超时包装 | 无超时会挂住整个 run |
| `idempotent` | 重试许可 | 非幂等重试 = 重复扣款 |
| `max_output_bytes` | 截断转 artifact | 大输出进上下文必炸 |
| `sandbox` | 强制进沙箱 | `shell` 类不许在宿主执行 |

**校验顺序（固定）**：`Gate(审批) → Check(schema) → 幂等查表 → Wrap(超时/沙箱/截断) → invoke → 脱敏 → 落 artifact`。

**幂等键派生（必须按此实现）**：

```python
idem_key = sha256(f"{ns.session}:{step.index}:{spec.name}:{canonical_json(args)}")[:32]
```

`canonical_json`：键排序、无空格、UTF-8。幂等键必须在工具层统一派生；各层自算会让 `retry` 与 `replay` 得到不同的键，幂等失效。

**注册表**：

```python
class ToolRegistry:
    def add(self, *tools: Tool) -> "ToolRegistry": ...          # 重名 → ToolError
    def get(self, name: str) -> Tool: ...
    def schemas(self, *, allow: frozenset[str] | None = None) -> list[dict]: ...  # 按允许集过滤
```

`schemas(allow=...)` 是唯一口子：`allowed_tools`（skill 约束）与 `scopes`（能力约束）最终都收敛到"这轮给模型看哪些工具"。

#### M3.5.1 `@tool` 的签名 → JSON Schema 推导规则（定死，不许猜）

| Python 标注 | JSON Schema | 是否必填 |
|---|---|---|
| `str` / `int` / `float` / `bool` | `string` / `integer` / `number` / `boolean` | 无默认值即必填 |
| `list[X]` / `tuple[X, ...]` / `set[X]` | `array` + `items` | 同上 |
| `dict[str, X]` | `object` + `additionalProperties` | 同上 |
| `Literal["a","b"]` | `enum: ["a","b"]` | 同上 |
| `Enum` 子类 | `enum: [e.value ...]` | 同上 |
| `X \| None`（`Optional[X]`） | `X` 的 schema + `nullable: true` | **恒非必填** |
| 嵌套 dataclass / pydantic `BaseModel` | 展开为 `object` + `properties`（递归） | 同上 |
| `Annotated[int, Field(ge=0, le=100)]` | 追加 `minimum` / `maximum` | 同上 |
| **无标注** | **拒绝**：抛 `ConfigError` | — |

**必须遵守的四条**

1. **无标注一律拒绝，不默认 `string`**。默认 `string` 会把 `amount: int` 变成字符串传给下游，错误发生在最远的地方。
2. **必填 = 无默认值**；有默认值的参数在 schema 里带 `default`，且不进 `required`。
3. **`description` 来源**：docstring 首段为工具描述；`Args:` 段落中 `name: 说明` 逐参数提取。缺 `Args:` 时参数 `description` 留空，不编造。
4. **`*args`/`**kwargs`/`self`/`cls` 跳过**；`**kwargs` 存在时 `additionalProperties: true`，否则 `false`。

```python
@tool(side_effects="write", scopes={"net:api"}, idempotent=True)
async def refund(order_id: str, amount: int, reason: str | None = None) -> dict:
    """发起退款。

    Args:
        order_id: 订单号
        amount: 退款金额（分）
        reason: 可选原因
    """
# → parameters = {
#   "type": "object",
#   "required": ["order_id", "amount"],
#   "additionalProperties": false,
#   "properties": {
#     "order_id": {"type": "string", "description": "订单号"},
#     "amount":   {"type": "integer", "description": "退款金额（分）"},
#     "reason":   {"type": ["string","null"], "nullable": true, "description": "可选原因"}}}
```

---

## 模块 M4 · 分派层

**职责（基线 5.8）**：分派是四层里**唯一同时有部件与数据**的层。它不解决问题，只决定谁来解决。

### M4.1 契约

```python
class Router(Protocol):
    async def route(self, goal: Goal, state: State | None = None) -> Route: ...

class Branch(Protocol):              # 一条分支：提示词 / 工作流 / Skill 程序
    name: str
    async def handle(self, agent: Agent, goal: Goal, state: State) -> RunResult: ...
```

### M4.2 四个内置路由器

| 实现 | 机制 | 成本 | 何时用 |
|---|---|---|---|
| `AlwaysRoute(name)` | 恒返回一条 | 0 | 兜底、单分支系统 |
| `RuleRouter(rules)` | 关键词/正则/字段匹配 | 极低 | 请求形状固定 |
| `ConfidenceRouter(model, threshold)` | 小模型给分支打分 | 一次小调用 | 分支语义相近 |
| `EmbeddingRouter(index)` | 分支描述向量最近邻 | 一次向量检索 | 分支多、表述自由 |

**路由置信度不是概率**（第 13 章）：它只用于**比较**，阈值是运营参数，不是统计推断。

### M4.3 分派层的四个契约（基线 22.6）

| # | 契约 | 要求 |
|---|---|---|
| 1 | **输入归一化** | 各路由器的输入统一为 `(Goal, State)`，禁止某个路由器要求额外参数 |
| 2 | **输出形状** | 永远是 `Route{name, accepts, fallback}`；`accepts` 是它接受的输入类型声明 |
| 3 | **兜底归属** | 兜底由 `Router` 显式给出（`fallback=True`），**不是**"没有匹配"的隐式结果 |
| 4 | **N 条分支的测试代价** | 分支数 × 每分支一条回归用例；分支内容分三种（提示词/工作流/Skill），只有 Skill 连工具集一起换 |

### M4.4 误分流的代价（为什么必须显式兜底）

| 分支类型 | 换掉的东西 | 误分流后果 |
|---|---|---|
| 提示词分支 | 只要 system | 回答风格错，可重试 |
| 工作流分支 | 步骤序列 | 走了错的流程，可能产生副作用 |
| Skill 程序分支 | 流程 + **工具集** | 拿到了不该有的工具，**权限错配** |

所以 `Route` 必须声明 `accepts`，`Guard` 在 `check_identity` 阶段可据此拒绝跨分支越权。

---

## 模块 M5 · 校验层

**职责（基线 5.8）**：部件 + 预算。判定"这一步做对了吗"与"整体达标了吗"，并驱动修复。

### M5.1 协议

```python
class Reflector(Protocol):
    async def review(self, result: ActionResult, state: State) -> Verdict: ...

class Validator(Protocol):
    async def validate(self, answer: str, state: State) -> Verdict: ...
```

### M5.2 三档校验（基线 22.7，成本曲线）

| 档 | 实现 | 每次调用的额外开销 | 能抓什么 | 抓不到什么 |
|---|---|---|---|---|
| 无裁判 | `NullReflector` | 0 | 只有硬错误（异常、空输出） | 语义错误 |
| 自评 | 主体模型自查 | +1 次调用 | 格式、自相矛盾 | 主体自己没想到的错误 |
| 外部裁判 | 独立模型 / 规则 / 测试 | +1 次调用（独立预算） | 事实性、越权、测试失败 | 裁判本身的盲区 |

**`Judge` 必须独立预算**：与主体共用预算时，主体会烧光预算让裁判无法否决，等于没有校验。

### M5.3 评分器循环（Evaluator-Optimizer）

```text
执行 → Reflector.review → Verdict
  accept     → 采纳
  retry      → 同一 Step 重跑（≤2 次；连续失败 2 次则采纳并记 reason）
  patch      → 改 args 后重跑（≤2 次）
  replan_all → 清 plan，回 Planner（≤2 次）
```

| 约束 | 理由 |
|---|---|
| 修复轮数 × 成本要写进 trace | 否则"反思很贵"是感觉不是数据 |
| 计数落在 `Budget` 上，不落在 `State` | 预算单一所有者（不变量 2） |
| 修复耗尽后必须**采纳并标注** | 不允许无限循环，也不允许静默丢弃 |

### M5.4 归属：一次 step 内的位置

`Validate` 层挂在插点 `step`，在 `Wrap`（执行）之后、`Checkpoint` 之前。`Validator` 挂在插点 `run` 的出口前。

---

## 模块 M6 · 供给层之一：Context（取景与编码）

**职责（插点 ②）**：回答"这一轮让模型看见什么"。基线契约是 `assemble(state, budget) -> Pack`；本文把它拆成两段，**接口面扩大但语义不变**。

### M6.1 为什么拆两段

v1 的 `assemble` 一个方法做了五件事：选哪些、怎么排、放哪个槽、超预算丢谁、渲染成什么格式。后果是换模型家族要改选择逻辑，换裁剪策略要改格式。拆开：

| 段 | 协议 | 输入 → 输出 | 只负责 |
|---|---|---|---|
| 取景 | `Framer` | `State` + `FrameKind` + `Budget` → `Frame` | 选哪些、怎么排、超预算丢谁 |
| 编码 | `Encoder` | `Frame` → `Payload` | 变成哪种格式 |

```python
class FrameKind(StrEnum):
    MODEL = "model"; HUMAN = "human"; APPROVAL = "approval"; TRACE = "trace"

@dataclass(frozen=True)
class Section:
    name: str            # system skills memory retrieved history goal task
    priority: int        # 越大越先留
    source: str          # "memory:recall" / "doc:42" / "skill:refund"
    text: str
    tokens_est: int
    ephemeral: bool = False   # 只本轮可见，不写回 messages

@dataclass(frozen=True)
class Frame:
    kind: FrameKind
    sections: tuple[Section, ...]     # 已按 priority 排序
    dropped: tuple[str, ...]          # 必须可解释
    tokens_est: int
    meta: dict[str, Any] = field(default_factory=dict)

class Framer(Protocol):
    kind: FrameKind
    async def frame(self, state: State, *, budget: Budget) -> Frame: ...

class Encoder(Protocol):
    fmt: str
    async def encode(self, frame: Frame) -> Payload: ...     # Payload = Pack | Card
```

### M6.2 四槽位与四个取景器（基线的"四槽位装配"）

`ModelFramer` 固定按基线四槽位收集：`system`（角色+规则）、`skills`（目录）、`memory`（召回）、`retrieved`（资料），再追加 `history` 与 `goal`。

| 取景器 | 内容 | 裁剪策略 |
|---|---|---|
| `ModelFramer` | 上述六槽 | 按 `priority` 从低到高丢；先丢 history，再丢 retrieved；**永不丢 goal** |
| `HumanFramer` | 全量 + 折叠 + 时间线 | 不裁剪，超限折叠 |
| `ApprovalFramer` | 只含待批 step + 影响面 + 期限 | 定长 |
| `TraceFramer` | 步骤、用量、耗时、错误 | 定长 |

**裁剪算法（必须按此实现，保证可回放）**：

```python
def frame(state, budget) -> Frame:
    sections = collect(state)                                  # 顺序固定
    for s in sorted(sections, key=lambda x: x.priority):        # 低优先级先丢
        if total <= budget.remaining_tokens: break
        if s.name == "goal": continue                          # 永不丢
        drop(s); dropped.append(s.name)
    if dropped: sections.append(omission_section(len(dropped))) # 必须可解释
    return Frame(kind=MODEL, sections=tuple(sections), dropped=tuple(dropped), tokens_est=total)
```

### M6.3 编码器

| 编码器 | `fmt` | 产物 |
|---|---|---|
| `ChatEncoder` | `openai` / `anthropic` / `gemini` | `Pack` |
| `CardEncoder` | `ui` / `slack` | `Card` |
| `JsonlEncoder` | `jsonl` | `str` / `list[RunEvent]` |

### M6.4 设计理由与红线

| 选择 | 理由 |
|---|---|
| 选择与格式分两段 | 两个变化原因；换模型不改选择，换策略不改格式 |
| 裁剪必须写 `dropped` 并附加"已省略 N 条" | 模型不知道瞎了会自信答错；可解释是正确性要求 |
| 一帧可被多个 `Encoder` 消费 | "换模型家族不改内核"的落点 |
| `ephemeral` 标记 | skill 正文、本轮推导只对本轮可见，防污染历史 |
| 明确**不做响应式** | `State` 必须可序列化、可重放；agent 无"用户改表单"事件源 |
| `Memory` 不感知预算，`Context` 不感知评分（基线约束 5） | 否则两者耦合，无法归因 |

**禁止**：`Framer` 拼字符串或决定 JSON 结构；`Encoder` 决定留哪条。

---

## 模块 M7 · 供给层之二：知识、记忆、技能

### M7.1 `Knowledge`（循环外，插点②的输入源）

```python
class Knowledge(Protocol):
    async def retrieve(self, query: str, *, k: int, ns: Namespace,
                       filters: dict[str, Any] | None = None) -> list[Recalled]: ...
```

| 约束 | 理由 |
|---|---|
| 只返回候选，不决定条数 | `k` 由 `Context` 给（基线约束 5） |
| 过滤必须**下推到后端** | 拉回来再过滤 = 租户泄漏风险 |
| `NullKnowledge` 必须存在 | 替换实验要能"只剩纯对话" |

### M7.2 `Memory`（循环外，跨会话）

```python
class Memory(Protocol):
    async def recall(self, ns: Namespace, query: str, *, layers: Sequence[str], k: int) -> list[Recalled]: ...
    async def upsert(self, ns: Namespace, items: Sequence[Recalled]) -> int: ...
    async def forget(self, ns: Namespace, ids: Sequence[str]) -> int: ...   # 软删：置 superseded_by，recall 不再返回
    async def expire(self, ns: Namespace, now: datetime) -> int: ...
```

**存取（`Memory`）与写入策略（`MemoryPolicy`）必须分开**：

```python
class MemoryPolicy(Protocol):
    async def should_write(self, state: State, result: RunResult) -> bool: ...
    async def extract(self, state: State) -> list[Recalled]: ...
    async def merge(self, old: list[Recalled], new: list[Recalled]) -> list[Recalled]: ...
    async def decay(self, items: list[Recalled], now: datetime) -> list[Recalled]: ...
```

默认 `Conservative` 四条：① 只写结论与偏好，不写流水；② 冲突时新覆盖旧但保留旧为超链接；③ 每条必须带 `source`，无来源不写；④ 脱敏在写入前，不在读取后。

### M7.3 `Skills`（给流程，不给能力）

```python
class Skills(Protocol):
    def catalog(self) -> list[SkillMeta]: ...                    # name + description only
    async def load(self, name: str) -> Skill: ...                # 正文
    async def resource(self, name: str, path: str) -> str: ...   # references/*
```

**三段式渐进披露（必须按此实现）**

| 段 | 时机 | 注入量 | 手段 |
|---|---|---|---|
| ① 目录 | 每次 `model_call` | 每 skill 一行（name + description） | `ModelFramer` 的 `skills` 槽 |
| ② 正文 | 模型调 `load_skill(name)` 后 | 一个 SKILL.md 正文 | `Capability` 层改写本轮 sections，`ephemeral=True` |
| ③ 资源 | 模型调 `read_skill_resource` 后 | 单个 reference | 同上，按需 |

外加：`allowed_tools` 在 `tool_call` 链里**真正执行**（过滤 `schemas(allow=...)`）。v1 只解析不使用（[skills.py:93](../../code/harness/src/harness/skills.py)），这是现成的洞。

| 约束 | 理由 |
|---|---|
| 目录只暴露 name + description | 目录是常驻成本，正文是偶发成本，量级差两个数量级 |
| `SkillRegistry.from_dir` **懒加载**正文 | 启动时读全部 SKILL.md 会让首屏变慢 |
| Skill 可编译成 `WorkflowPolicy` | "Skill 程序"是主体第四形态（基线 5.2） |

### M7.4 换存储介质：把记忆换成 PostgreSQL（完整演练）

**结论先行**：`kernel/` 与 `parts/` **零改动**，`Program` **零改动**，只改 1 行配置 + 新增 1 个 `impl` 文件 + 1 组一致性测试。

**第 1 步：改配置（唯一的一行业务改动）**

```python
h = Harness.of(
    model="openai:gpt-4.1",
    stores=StoreSpec(memory="postgres:$MEM_DSN"),      # memory 从 memory 换成 postgres
)
```

**第 2 步：实现 `Memory` 四个方法（约 180 行）**

```python
class PostgresMemory:                       # 实现 M7.2 的 Memory 协议
    def __init__(self, dsn: str, *, embed: Embedder, table="memory_items"):
        self.pool, self.embed, self.table = make_pool(dsn), embed, table

    async def recall(self, ns, query, *, layers, k) -> list[Recalled]:
        vec = await self.embed(query)
        rows = await self.pool.fetch(f"""
            SELECT id, text, layer, source, age_days, dedup_key,
                   1 - (embedding <=> $1) AS score
              FROM {self.table}
             WHERE tenant=$2 AND user_id=$3 AND session_id=$4 AND agent=$5   -- 命名空间下推
               AND layer = ANY($6)                                           -- layer 下推
               AND superseded_by IS NULL                                     -- 只取最新版本
               AND (expires_at IS NULL OR expires_at > now())                -- 过期下推
             ORDER BY embedding <=> $1
             LIMIT $7""",
            vec, ns.tenant, ns.user, ns.session, ns.agent, list(layers), k)
        return [Recalled(**r) for r in rows]

    async def upsert(self, ns, items) -> int:      # 去重靠 DB 唯一约束，不靠应用层先查后写
        async with self.pool.acquire() as c, c.transaction():
            await c.executemany(f"""
                INSERT INTO {self.table}(tenant,user_id,session_id,agent,layer,text,
                                         source,age_days,dedup_key,embedding)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (tenant,user_id,session_id,agent,dedup_key)
                DO UPDATE SET text=EXCLUDED.text, embedding=EXCLUDED.embedding,
                              age_days=EXCLUDED.age_days, source=EXCLUDED.source""",
                [(ns.tenant, ns.user, ns.session, ns.agent, i.layer, i.text,
                  i.source, i.age_days, i.dedup_key, await self.embed(i.text)) for i in items])
        return len(items)

    async def forget(self, ns, ids) -> int: ...     # 软删：置 superseded_by
    async def expire(self, ns, now) -> int: ...      # 物理删或标记，二选一写死
```

**第 3 步：表结构（三处细节决定成败）**

```sql
CREATE TABLE memory_items (
  id            BIGSERIAL PRIMARY KEY,
  tenant        TEXT NOT NULL,          -- 命名空间是四列复合，不是字符串前缀
  user_id       TEXT NOT NULL,
  session_id    TEXT NOT NULL,
  agent         TEXT NOT NULL,
  layer         TEXT NOT NULL,
  text          TEXT NOT NULL,
  source        TEXT NOT NULL DEFAULT '',
  age_days      INT  NOT NULL DEFAULT 0,
  dedup_key     TEXT NOT NULL,
  embedding     VECTOR(1024),
  superseded_by BIGINT REFERENCES memory_items(id),   -- 支撑 MemoryPolicy 的"旧条目保留为超链接"
  expires_at    TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant, user_id, session_id, agent, dedup_key)   -- 并发 upsert 的正确性来源
);
CREATE INDEX ON memory_items (tenant, user_id, agent, layer);
CREATE INDEX ON memory_items USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON memory_items (expires_at) WHERE expires_at IS NOT NULL;
```

**第 4 步：跑一致性测试（`MemoryConformance`，见 M16.3）**

**第 5 步：迁移存量数据**

```text
旧 InMemory/JSONL → SELECT 全部条目 → 计算 dedup_key（无则用 sha256(text)[:16]）→ 批量 upsert → 校验条数
```

**为什么这么容易：四个设计决定在起作用**

| 设计决定 | 这次替换里省掉了什么 |
|---|---|
| `Memory` 只有 4 个方法（M1.1 窄而深） | 不用实现 20 个方法；Postgres 版本半年能维护 |
| `Namespace` 是四列复合值（不是字符串） | 租户隔离写成 4 个 `WHERE` 条件，不用解析前缀 |
| `MemoryPolicy` 与 `Memory` 分离 | 写入策略（该不该写/合并/衰减）在换介质时**完全不动** |
| `Program` 里没有实例（§0.3） | 业务侧只改 1 行配置，不动任何 `react(...) >> ...` 组合 |

**四个必须避开的坑（都来自"换了介质"这件事本身）**

| 坑 | 正确做法 |
|---|---|
| 在 Python 里过滤 layer/ns/过期 | 必须**下推**到 SQL：否则先拉全表再过滤，既慢又泄漏 |
| 先 `SELECT` 再 `INSERT` 做去重 | 必须靠 `UNIQUE` + `ON CONFLICT`，否则并发下会产生两条 |
| 一致性测试断言精确 `score` | 只断言"返回 ≤ k 条、按 score 降序、ns 隔离、dedup 覆盖旧值"——不同后端的打分不可比 |
| `expire` 与 `recall` 各写一套过期判断 | 一处在 SQL、一处在定时任务，语义必须同源（都用 `expires_at > now()`） |

**代价评估**：新实现 ~180 行 + 一致性测试 ~120 行 + 表结构与迁移脚本；**内核与部件零改动**。这就是"可替换"这条验收判据（§1.4 第 1 条）的实际兑现方式。

---

## 模块 M8 · 治理层之一：准入与预算

### M8.1 `Guard`（插点 ⑤ 准入 + 接入阶段）

```python
class Guard(Protocol):
    async def check_identity(self, goal: Goal, ns: Namespace) -> GuardDecision: ...   # 接入：鉴权/租户/配额
    async def check(self, step: Step, state: State) -> GuardDecision: ...             # 准入：这个动作允许吗
```

**为什么两个方法而不是两套组件**（基线 5.9）：接入与准入共享"不通过就拦"的语义，拆开会把同一条拒绝逻辑写两遍。

| 实现 | 用途 |
|---|---|
| `AllowAll` | 显式放行（**不允许用"没有 Guard"表示放行**） |
| `DenyAll` | 默认拒绝；装配时忘记配 Guard 的兜底 |
| `FunctionGuard(fn)` | 函数式规则 |
| `PolicyGuard(rules)` | 声明式规则：白名单/目录/金额/时间窗 |
| `CompositeGuard(*guards)` | 任一 deny 即 deny；任一 ask 即 ask |

`GuardDecision.card` 是给人看的审批卡片内容；`expires_in` 是期限。**Guard 不抛异常**，只返回判定。

### M8.2 `Budget`（插点 ⑧，被三处读取）

```python
@dataclass
class Budget:
    tokens: int = 200_000
    calls: int = 60
    used_tokens: int = 0
    used_calls: int = 0
    owner: str = "run"                      # run | session | child:<name>
    retries: int = 0                        # 校验层的修复计数
    replans: int = 0

    @property
    def remaining_tokens(self) -> int: ...
    @property
    def remaining_calls(self) -> int: ...
    @property
    def exhausted(self) -> bool: ...
    def spend(self, tokens: int = 0, calls: int = 1) -> None: ...
    def split(self, fraction: float) -> "Budget": ...          # 给子 agent
    def view(self, owner: str) -> "Budget": ...                # 只读视图，写入回落到根
```

| 设计 | 理由 |
|---|---|
| 被循环、策略、子 agent 三处读取 | 任一处持有都会造成反向依赖（基线 5.2） |
| `split()` 而非新建 | 实现不变量 2：子消耗必须计入父 |
| `retries`/`replans` 放预算上 | 校验层的修复计数属预算，不属 State |
| 支持 `scope="session"` | 会话级累计配额（基线 5.9） |

### M8.3 审批（插点 ⑤ 的 `ask` 分支）

```text
Guard 返回 ask
  → Approval 层构造 ApprovalRequest(step, reason, card, expires_at)
  → {待批 step} 写入检查点（pending 字段）
  → 返回 RunResult(status=NEEDS_APPROVAL, pending=...)
  → 外部 decide() 后调用 harness.resume(session_id, decision)
  → 校验 expires_at；批准则跳过 Gate 直接执行；驳回 → REFUSED
```

| 约束 | 理由 |
|---|---|
| 挂起时必须落盘 | 进程可能在这期间重启 |
| 恢复必须校验 `expires_at` | 过期审批不应生效 |
| 批准的 step 不再过 Gate | 已经批过，重复审批是骚扰 |
| `Decision.modify` 只改 `args` | 允许人改参数，不允许人改工具名（换工具=换风险面） |

### M8.4 配额与限流的归属（定死）

| 项 | 归属 | 规则 |
|---|---|---|
| 配额存储 | `SessionStore` 的 `SessionMeta.quota = {"tokens": n, "calls": m}` | 配额是**会话属性**，不是进程属性；跨实例部署必须共享 |
| 配额判定 | `Guard.check_identity` | **只读判定**，不改状态：读 `SessionMeta` → 与 `Budget(session)` 已用量比较 → `allow/deny` |
| 配额累加 | `Budget(scope="session")` | 由 `BudgetGuard` 在出口统一写回 `SessionStore`，每 run 一次 |
| 限流 | `Resilience.max_qps`（按 `key`） | 进程级令牌桶即可；跨实例限流属交付层（第 32 章），不进副线 |

**为什么判定与累加必须分开**：`Guard` 是纯函数式的准入（同一输入同一结论），写入状态会让它产生副作用，进而无法在 `dry_run` 与测试里复用。**单一所有者**（不变量 2）：只有 `BudgetGuard` 写回。

| 失败语义 | 结果 |
|---|---|
| 配额耗尽 | `GuardDecision.deny("quota_exceeded")` → `REFUSED`（不是 `DEGRADED`：这是拒绝服务，不是降级） |
| 限流触发 | `TransientError` → 有界重试，耗尽后 `DEGRADED` |
| `SessionStore` 不可用 | `ConfigError`（启动期已探活），不在运行期降级 |

---

## 模块 M9 · 治理层之二：护栏

**职责**：判定"内容能不能进出"。与 `Guard`（判定"动作能不能做"）是两个东西。

### M9.1 五道闸

```text
用户输入 ─▶ ① 入站 ─▶ 取景 ─▶ ② 入上下文 ─▶ 模型 ─▶ ③ 出模型
                                                       │
                    工具结果 ◀─ ④ 工具边界 ◀─ 工具调用 ◀┘
                        │
                    ⑤ 出口（最终答案 / 卡片 / 事件）
```

| 闸 | 检查对象 | 为什么必须有 |
|---|---|---|
| ① 入站 | 用户原始输入 | 最便宜的一道；早期能拒的不带进循环 |
| ② 入上下文 | 检索资料、记忆、skill 正文 | **间接注入主战场**：知识库与记忆是攻击面，不是可信数据 |
| ③ 出模型 | 模型回复（含工具调用参数） | 模型要写 `rm -rf` 时，参数就是输出 |
| ④ 工具边界 | 工具返回值 | 网页/文件/API 响应会回灌注入载荷 |
| ⑤ 出口 | 最终答案、卡片、事件 | 最后一道，也是审计留痕处 |

### M9.2 协议与三段式

```python
class Gate5(StrEnum):
    INBOUND = "inbound"; CONTEXT = "context"; MODEL_OUT = "model_out"
    TOOL_OUT = "tool_out"; OUTBOUND = "outbound"

@dataclass(frozen=True)
class Content:
    text: str; kind: str; ref: str = ""      # kind: user|retrieved|memory|skill|model|tool|answer

class Guardrail(Protocol):
    name: str
    gates: frozenset[Gate5]
    async def check(self, content: Content, scope: RunScope) -> GuardrailVerdict: ...

class GuardrailStream(Guardrail, Protocol):
    async def feed(self, delta: str, st: StreamState) -> GuardrailVerdict: ...
    async def flush(self, st: StreamState) -> GuardrailVerdict: ...
```

**检测与动作必须分离**：检测器只回答"哪一段、什么风险"（`risk/labels/spans`），动作（`allow/warn/redact/rewrite/ask/block`）由策略按环境与租户决定。合并后无法按环境调策略，也无法对多个检测器仲裁。

### M9.3 仲裁规则（定死）

1. 取最严动作：`block > ask > rewrite > redact > warn > allow`。
2. 同动作取最高 `risk`。
3. `rewrite` 与 `redact` 冲突 → 取 `redact`（改写可能引入新风险）。
4. 仲裁结果发 `guardrail` 事件（`fields={labels, action, spans}`）。

### M9.4 流式护栏三条规则

1. **窗口缓冲**：保留最近 64 字符不立即下发（防跨块敏感串）。
2. **已下发不可撤回**：命中只能"中断 + 说明"，`status=DEGRADED`，`metadata.reason="guardrail_blocked_midstream"`。
3. **块级降级**：检测器不支持增量时，每 256 字符整块检测，标 `degraded_stream_guard=true`。

### M9.5 护栏自身失败（默认 fail-closed）

| 情形 | 默认 | 可配置 |
|---|---|---|
| 检测器超时 | `block` | `fail_open=True` 且仅非生产 namespace → `warn` |
| 检测器异常 | `block` + `guardrail_error` 事件 | 同上 |
| 引用未注册检测器 | 构造期 `ConfigError` | 不允许运行期跳过 |

`fail_open` 启用后必须在 `RunResult.metadata.guardrail_fail_open=true` 留痕。

---

## 模块 M10 · 治理层之三：观测与出口

### M10.1 `Tracer` 与事件（插点 ⑧⑨ + 全部插点）

```python
class EventSink(Protocol):
    async def emit(self, event: RunEvent) -> None: ...

class Tracer(Protocol):                 # Tracer = 带 span 语义的 EventSink
    def span(self, name: str, *, parent: str | None = None) -> Span: ...
    async def emit(self, event: RunEvent) -> None: ...
```

基线固定事件名：`run.start` / `step.end` / `run.end` / `run.error`。v2 扩展 13 种：

| 事件 | 载荷 | 消费者 |
|---|---|---|
| `run.start` / `run.end` | goal / status + usage + rev | 指标、计费 |
| `step.start` / `step.end` | step / result + index | 进度 |
| `model.start` / `model.delta` / `model.end` | 增量文本 / usage | 逐字显示、成本 |
| `tool.start` / `tool.end` | spec / result + 耗时 | 审计、慢调用 |
| `guardrail` | labels + 仲裁动作 + spans | 安全审计 |
| `approval.required` / `approval.resolved` | 卡片 / 决策 | HITL UI |
| `checkpoint` | rev | 外部备份 |
| `error` / `hook.error` / `guardrail_error` | 分类 + phase | 告警 |

| 规则 | 理由 |
|---|---|
| `span` 必须真实填写 `parent_id` | v1 留了字段从未填写，跨 agent 就断了 |
| 事件处理异常只记日志，不影响请求 | 可观测性不得影响可用性 |
| `Tracer` 必须能离线工作（`Jsonl`/`Memory`） | 离线测试是 R6 的前提 |

### M10.2 双形态出口

```python
async def run(self, program: Program, goal: Goal) -> RunResult                 # 同步语义
def astream(self, program: Program, goal: Goal) -> AsyncIterator[RunEvent]     # 流式语义
```

**必须共用同一条内核**：`astream` 不是另一套实现。实现方式：内核持有 `EventSink` 列表，`astream` 额外挂一个 `asyncio.Queue` 适配器。禁止复制循环。

**背压**：队列 256；溢出默认 `drop_oldest` 并计数到 `metadata.event_dropped`；只有 `EventSink.blocking=True` 显式配置才阻塞。

### M10.3 `Delivery`（插点 ⑨）

```python
class Delivery(Protocol):
    async def finish(self, state: State, status: RunStatus, *,
                     answer: str = "", reason: str = "",
                     pending: ApprovalRequest | None = None) -> RunResult: ...
```

**终止态的三种与四种附加态**（基线 5.2 ⑨）：答完（`COMPLETED`）、降级（`DEGRADED`）、拒答（`REFUSED`）；附加 `FAILED`/`NEEDS_APPROVAL`/`CANCELLED`/`RUNNING`（后者禁止出现在结果里）。

| 职责 | 为什么在 `Delivery` 而不在各 agent |
|---|---|
| 终止态判定 | 分散实现会导致"同一失败在不同路径表现不同" |
| 输出过滤（最后一道护栏） | 护栏的最后一公里 |
| 引用编号与格式 | 引用必须全局连续编号，各 agent 各自编号必然冲突 |
| 元数据（用量、rev、trace_id） | 出口唯一才能保证每个结果都带齐 |

### M10.4 取消语义（定死）

```python
async def cancel(self, session_id: str) -> None      # 幂等；重复调用无操作
```

| 环节 | 规则 |
|---|---|
| 传播 | `harness.cancel()` 只设一个 `asyncio.Event`；循环在每个 step 边界检查一次（不中断正在进行的工具调用） |
| 捕获点 | `CancelledError` **只在 `Classify` 段被捕获**，映射为 `Failure(status=CANCELLED, retryable=False)` |
| 收尾顺序 | ① 写检查点（`status=CANCELLED`，`rev+1`）→ ② `sandbox.kill()` 回收 → ③ 取消子任务（`TaskGroup`）→ ④ `Delivery.finish` |
| 流式中断 | 已下发的 `model.delta` 不可撤回；检查点**必须落盘** `CANCELLED`，否则恢复时状态不明 |
| 恢复 | `CANCELLED` 的会话可 `resume` 从最后 `rev` 继续（`status` 回 `RUNNING`），也可直接重建 |
| 禁止 | 不允许在四段链内部捕获 `CancelledError`（会吞掉上层取消，留下半执行状态） |

**为什么取消点只在 step 边界**：工具调用中途取消会留下"副作用已发生但结果没记账"的窗口，幂等表与检查点都无法描述它。宁可让这一步跑完（有 `timeout_s` 兜底），也不制造半状态。

---

## 模块 M11 · 存储（Durability / Session / MessageLog / Idempotency）

**职责**：实现"历史不可变"与"会话隔离"。基线只有 `Durability.save/load` 两方法；本文拆成四个协议，语义是**扩展**不是替换。

### M11.1 四个协议

```python
class Durability(Protocol):                  # 基线契约的 v2 形态
    async def put(self, ns: Namespace, sid: str, state: State, *, expect_rev: int | None) -> int: ...
    async def get(self, ns: Namespace, sid: str, rev: int | None = None) -> Checkpoint | None: ...
    async def history(self, ns: Namespace, sid: str, *, limit: int = 50) -> list[int]: ...

class SessionStore(Protocol):
    async def create(self, ns: Namespace, meta: SessionMeta) -> SessionMeta: ...
    async def get(self, ns: Namespace, sid: str) -> SessionMeta | None: ...
    async def list(self, ns: Namespace, *, cursor: str | None = None, limit: int = 50) -> Page[SessionMeta]: ...
    async def update(self, ns: Namespace, sid: str, patch: dict[str, Any]) -> SessionMeta: ...

class MessageLog(Protocol):
    async def append(self, ns: Namespace, sid: str, msgs: Sequence[dict]) -> int: ...
    async def tail(self, ns: Namespace, sid: str, *, max_tokens: int) -> list[dict]: ...

class Idempotency(Protocol):
    async def begin(self, ns: Namespace, key: str) -> Recorded | None: ...
    async def commit(self, ns: Namespace, key: str, value: Recorded) -> None: ...
```

### M11.2 七条语义约束（一致性测试必须覆盖）

| # | 约束 | 违反后果 |
|---|---|---|
| C1 | **历史不可变**：`put` 只追加新 rev；旧 rev 的 `get` 返回当时内容 | 时间旅行失效 |
| C2 | **乐观并发**：`expect_rev` 不匹配 → `ConcurrencyError` | 并发写静默覆盖 |
| C3 | **命名空间强制**：跨 ns 读取视为不存在 | 多租户泄漏 |
| C4 | **幂等写**：同 `dedup_key` 的 upsert 不产生第二条 | 记忆重复膨胀 |
| C5 | **append-only**：`MessageLog.append` 不修改既有记录 | 历史可篡改 |
| C6 | **尾读有预算**：`tail(max_tokens)` 从尾部往回取 | 长会话 OOM |
| C7 | **点查命中**：`Idempotency.begin` 命中返回 `Recorded`，否则 `None` | 重复执行副作用 |

### M11.3 会话生命周期（基线 5.9）

`SessionStore` 承担开始/过期/清理；会话级累计配额由 `Budget(scope="session")` 承担。**`SessionRef` 是持久化单位**（一个键），横跨多次 loop，挂不到任何插点。

### M11.4 多租户隔离级别（定死）

**默认：逻辑隔离** —— 单库单表，`Namespace` 四列作为联合索引前缀，所有读写强制带 `WHERE tenant=? AND user_id=? AND session_id=? AND agent=?`。

| 级别 | 配置 | 适用 | 代价 |
|---|---|---|---|
| **逻辑隔离（默认）** | `StoreSpec(memory="postgres:$DSN")` | 绝大多数场景 | 一次表迁移覆盖所有租户 |
| 模式隔离 | `StoreSpec(memory={"kind":"postgres","dsn":"...","schema_per_tenant":true})` | 单租户数据量大、需按租户备份/导出 | 建表与迁移要按 schema 遍历 |
| 库隔离 | 每租户一个 DSN，由上层按 `ns.tenant` 选择 | 强合规、跨区域 | 连接池与迁移成本最高 |

**三条硬约束**

1. **隔离条件必须由 store 实现的唯一助手生成**（`where_ns(ns)`），**禁止**各方法手写 `WHERE`。手写就一定会漏一个。
2. **唯一键必须包含全部四列**（见 M7.4 的 `UNIQUE (tenant,user_id,session_id,agent,dedup_key)`），否则跨租户会撞键。
3. **禁止"先全表查再在 Python 过滤"**：`recall`/`search`/`list` 的 namespace 条件必须下推到 SQL/索引。

**为什么默认逻辑隔离**：物理隔离是**运维选择**，不是框架能力；把它做成默认会让"跑一个 demo"变成"建三个库"。框架负责的是"换级别时业务代码零改动"——由 `StoreSpec` 承载，业务侧只改配置。

---

## 模块 M12 · 后端（十个）

**职责**：所有"外部世界"的可替换边界。统一纪律：窄接口、内存实现、一致性测试。

### M12.1 接口全集

```python
class Model(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict] | None = None,
                       *, response_format: ResponseFormat | None = None) -> ModelReply: ...
    def stream(self, messages: list[dict], tools: list[dict] | None = None,
               *, response_format: ResponseFormat | None = None) -> AsyncIterator[ModelDelta]: ...

class FileSystem(Protocol):
    mounts: tuple[Mount, ...]
    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> None: ...
    async def edit(self, path: str, old: str, new: str, *, count: int = 1) -> int: ...
    async def glob(self, pattern: str) -> list[str]: ...
    async def grep(self, pattern: str, *, glob: str = "**/*", max_hits: int = 200) -> list[Match]: ...
    async def stat(self, path: str) -> Stat: ...

class Sandbox(Protocol):
    async def exec(self, argv: Sequence[str], *, cwd: str = "/work",
                   env: Mapping[str, str] | None = None, stdin: bytes | None = None,
                   limits: Limits | None = None, timeout_s: float | None = None) -> ExecResult: ...
    async def kill(self, exec_id: str) -> None: ...

class ArtifactStore(Protocol):
    async def put(self, name: str, data: bytes | AsyncIterator[bytes]) -> ArtifactRef: ...
    async def get(self, ref: ArtifactRef) -> bytes: ...
    async def stat(self, ref: ArtifactRef) -> ArtifactMeta: ...

class SecretBroker(Protocol):
    async def get(self, name: str) -> str: ...
    async def list(self) -> list[str]: ...

class IndexBackend(Protocol):
    async def search(self, ns: Namespace, query: str | list[float], *, k: int,
                     filters: dict[str, Any] | None = None) -> list[Recalled]: ...
    async def upsert(self, ns: Namespace, docs: Sequence[Document]) -> int: ...

class Queue(Protocol):
    async def enqueue(self, job: Job, *, delay_s: float = 0) -> str: ...
    async def dequeue(self, *, timeout_s: float) -> Job | None: ...
    async def ack(self, job_id: str) -> None: ...

class ApprovalChannel(Protocol):
    async def request(self, req: ApprovalRequest) -> str: ...
    async def wait(self, approval_id: str, *, timeout_s: float) -> Decision | None: ...
    async def respond(self, approval_id: str, decision: Decision) -> None: ...

class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
```

### M12.2 失效模式与硬要求

| 后端 | 关键要求 | 为什么 |
|---|---|---|
| `Model` | usage 归一化成 `{input, output, total}`；超时/限流可分类 | 上层记账与预算只认统一口径 |
| `FileSystem` | **虚拟路径 + 挂载表**，`resolve()` 单点做 jail | `os.path` 直通会让路径穿越在每个实现里各写一遍 |
| `Sandbox` | 限额、超时、输出截断、孤儿进程回收 | 缺一条就是资源泄漏或挂死 |
| `ArtifactStore` | 只存引用，内容不进 State | State 必须小且可序列化 |
| `SecretBroker` | 只按名取；只给声明了 `scopes` 的工具；**永不明文进 prompt** | 密钥泄漏是最贵的事故 |
| `IndexBackend` | 过滤**下推到后端** | 拉回再过滤 = 租户泄漏风险 |
| `Queue` | 至少一次投递 + 幂等键 | 重复投递必须有幂等兜底 |
| `ApprovalChannel` | 超时、过期、并发审批 | 审批挂死会永久占用 session |
| `Clock` | 可注入（`FakeClock`） | 测试与回放必须控制时间 |

### M12.3 路径隔离（唯一正确实现方式）

```python
@dataclass(frozen=True)
class Mount:
    target: str           # 虚拟路径，如 "/work"
    source: str | None    # 宿主路径；None = 纯内存
    mode: Literal["ro", "rw"]

def resolve(mounts: Sequence[Mount], path: str) -> RealPath:
    """唯一 jail 点：规范化 → 最长匹配挂载 → 校验 mode → 拒绝 ../ 与符号链接逃逸。"""
```

所有 FS 实现（Local / S3 / Fake）**共用这一个函数**，禁止各自拼路径。

### M12.4 沙箱纪律

1. 沙箱是**执行边界**，不是决策边界：`Gate` 放行了，沙箱仍必须挡住越界。
2. `exec` 只收 `argv` 列表，不收字符串命令（不给 shell 解析留口子）。
3. `limits` 缺省取 `RuntimeConfig.default_limits`，**不允许"无限制"**。
4. 退出必须回收子进程；`kill` 幂等。

---

## 模块 M13 · 挂载机制：层与 Hooks

**职责**：定义"组件怎么挂到插点上"的唯一机制。组件是语义单位（§2.3），层是运行期包裹单位；二者是多对一关系。

### M13.1 协议与元数据

```python
class Point(StrEnum):
    RUN = "run"; STEP = "step"; MODEL_CALL = "model_call"; TOOL_CALL = "tool_call"

class Layer:                                     # 值对象，不是 Protocol：层必须可序列化为规格
    name: str
    points: frozenset[Point]
    needs: frozenset[str]                        # model stores sandbox fs secrets events approval ...
    after: frozenset[str]
    before: frozenset[str]
    build: Callable[[Handler], Handler]          # 纯函数：Handler -> Handler

class Middleware(Protocol):
    name: str
    async def __call__(self, req: Request, nxt: Handler) -> Response: ...
```

| 字段 | 作用 | 为什么必须有 |
|---|---|---|
| `points` | 决定进哪几条链 | 一个层可能同时关心 model_call 与 tool_call（如审计） |
| `needs` | 构造期解析能力，缺 → `ConfigError` | 缺依赖必须启动期报错，不允许运行期降级 |
| `after`/`before` | 声明相对顺序，框架拓扑排序 | 第三方层能插到内置层之间，不用改内置代码 |
| `build` | 纯函数，`Handler -> Handler` | 层可组合、可测试、无实例状态（状态放闭包或 Scope） |

### M13.2 组件 → 挂载方式的映射（十五个组件怎么落地）

| 组件 | 挂载方式 | 插点 | 备注 |
|---|---|---|---|
| `Router` | 直接在 `Harness.run` 前调用 | — | 分派是"换一个部件"，不是层 |
| `Context` | `Context` 层（调 `Framer`+`Encoder`） | model_call | 供 `Actor.propose` 使用 |
| `Planner` | body 内部成员 | — | 只属 P&E |
| `Actor` | body 的执行器 | — | 由 `BodyPolicy` 调用 |
| `Guard` | 段 Gate | — | 永远是终端前最后一环 |
| `Tools` | 终端 | tool_call | 唯一的副作用原语 |
| `Resilience` | `Actor`/工具调用的包裹 | — | 五机制共享失败计数 |
| `Reflector` | `Validate` 层 | step | retry/patch/replan |
| `Budget` | `BudgetGuard` 层 | run, model_call | 被三处读取 |
| `Tracer` | `Trace` 层 | 全部 | span 传播 |
| `Durability` | `Checkpoint` 层 | step | 每步落盘 |
| `Delivery` | 内核直接调用 | — | 出口唯一 |
| `Memory` | `MemoryRecall`/`MemoryWrite` 层 | model_call, run | 两处：读在取景前，写在出口后 |
| `Knowledge` | `Retrieval` 层 | model_call | 只给候选 |
| `Skills` | `Capability` 层的子能力 | tool_call, model_call | 三段式披露 |

> 表内是基线十五个组件。v2 另有两个不属于基线的层：`TaskBoard`（任务管理）与 `MemoryWrite` 之外的 `Tenancy`/`Audit`/`IdempotencyLayer`/护栏三层等横切件——它们不改决策也不改执行，只增观察与约束，所以用层表达（完整清单见 M13.4）。

### M13.3 排序规则

1. 只对**同一插点**内的层排序。
2. `after`/`before` 构成有向图，环 → `ConfigError`。
3. 无约束层按注册顺序稳定排序（可复现）。
4. 三条默认铁律：改输入的在外、改输出的在内；便宜的在外的；安全在最内（`Guardrail` 紧贴终端，`Gate` 最后）。

### M13.4 内置层清单（17 个）

| # | 层 | points | needs | after / before | 行为 |
|---|---|---|---|---|---|
| 1 | `Tenancy` | run | — | before: 全部 | 校验 `session_id` 归属；写 `state.session` |
| 2 | `BudgetGuard` | run, model_call | — | after: Tenancy | 记账、超限抛 `BudgetError`、派生子预算 |
| 3 | `Trace` | 全部 | tracer, clock | — | 开/闭 span，填 `parent_id` |
| 4 | `Audit` | 全部 | events | after: Trace | 发 `audit.*` 事件 |
| 5 | `Checkpoint` | step | durability | after: Validate | 每步 `put(expect_rev)`；冲突抛 `ConcurrencyError` |
| 6 | `Validate` | step | — | after: Wrap | 调 `Reflector.review`，按 `Verdict` 重跑或采纳 |
| 7 | `Approval` | tool_call | durability, approval | after: Idempotency | `ask` 挂起；`resume` 继续 |
| 8 | `IdempotencyLayer` | tool_call | idempotency | after: Approval | 查表命中直接回旧结果 |
| 9 | `Retrieval` | model_call | index | before: Context | 调 `Knowledge.retrieve` 写 `state.data["retrieved"]` |
| 10 | `MemoryRecall` | model_call | memory | before: Context | 调 `Memory.recall` |
| 11 | `MemoryWrite` | run | memory | after: 全部 | 出口后按 `MemoryPolicy` 写入 |
| 12 | `Context` | model_call | — | before: InputGuard | `Framer` → `Encoder` |
| 13 | `InputGuard` | model_call | guardrails | — | 闸 ①②；按仲裁改写或拒绝 |
| 14 | `OutputGuard` | model_call, run | guardrails | after: Context | 闸 ③⑤；流式走 `GuardrailStream` |
| 15 | `Capability` | tool_call | fs, sandbox, secrets, artifacts | after: Approval | 挂三组工具集（文件五件套 / 沙箱两件 / skill 三件）、沙箱路由、结果截断转 artifact |
| 16 | `SubAgent` | tool_call | durability, sandbox, budget | after: Approval | `task` 工具 → 子运行 |
| 17 | `TaskBoard` | step, model_call | — | after: Context | 任务清单注入 + `task_*` 三工具（见 M13.4.2） |

**共 17 个内置层**（`Capability` 与 `SubAgent` 是复合项，可各自拆成子层，但对外按一层开关）。

### M13.4.1 `TaskBoard`（任务管理，v2 扩展，非基线组件）

```python
# 状态：state.section("tasks") = {"items": [{"id","text","status","owner"}], "updated_at": ...}
```

| 项 | 规格 |
|---|---|
| 位置 | `step`（推进状态）+ `model_call`（注入清单）两处 |
| 注入 | 每次取景时把"当前任务 + 未完成项"写成一个 `Section(name="task", priority=90, ephemeral=True)` |
| 工具 | `task_create(text) -> id`、`task_update(id, status)`、`task_list() -> list` |
| 状态机 | `todo → doing → done / blocked`；`blocked` 必须带 `reason` |
| 上限 | 单会话 50 条；超出拒绝 `task_create`（防模型无限建任务） |

**为什么它是层而不是组件**：它不改决策、不改执行，只在取景时多塞一段、在执行后更新一行。基线的十五个组件里没有它，因为它服务的不是"怎么想/怎么做"，而是"怎么不忘记"——这是 v2 新增的能力，用层表达最省。

**为什么必须内建而不是让用户自己拼**：长任务真正的瓶颈是上下文压缩把意图压没了。任务清单把意图从 `messages` 里提出来放到 `Section`，是一次性的、抗压缩的；用户自己拼会各写一版。

### M13.4.2 `Capability` 提供的三组工具（完整签名）

**① 文件五件套**（全部走 `FileSystem` 后端，路径先过 `resolve()`）

| 工具 | 参数 | 返回 | `side_effects` |
|---|---|---|---|
| `read_file` | `path, offset=0, limit=2000` | 文本（超限标 `truncated`） | `read` |
| `write_file` | `path, content` | `{ok, bytes}` | `write` |
| `edit_file` | `path, old, new, count=1` | `{ok, replaced}` | `write` |
| `glob` | `pattern` | `list[str]` | `read` |
| `grep` | `pattern, glob="**/*", max_hits=200` | `list[Match{path, line, text}]` | `read` |

**② 沙箱两件**（`exec` 必须 `argv` 列表）

| 工具 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `exec` | `argv: list[str], cwd="/work", timeout_s=30, env_keys: list[str] = []` | `ExecResult` | `env_keys` 只接受 `SecretBroker` 里的名字，值不回流 |
| `kill` | `exec_id` | `{ok}` | 幂等 |

**③ Skill 三件**（三段式披露的落地）

| 工具 | 参数 | 说明 |
|---|---|---|
| `load_skill` | `name` | 注入正文到本轮 sections（`ephemeral=True`） |
| `read_skill_resource` | `name, path` | 注入单个 reference |
| `list_skills` | — | 必要时的显式列举（目录已常驻，通常不需要） |

**共同约束**

| 约束 | 理由 |
|---|---|
| 三组工具按 `spec.scopes` 注入 `ToolContext` | 没声明 `fs:write` 的工具拿不到 `fs` |
| `exec` 的 `env_keys` 只能取密钥名 | 防止模型把 key 写进 stdout |
| 所有工具输出先过 `OutputGuard` 闸 ④ 与截断 | 工具结果是注入载体，也是上下文炸弹 |
| 工具不存在时不必报错：`schemas(allow=)` 直接不展示 | 模型不该看见它无权使用的工具 |

### M13.5 子 agent（最容易做成玩具，五个必须做全）

| # | 要求 | 不做会怎样 |
|---|---|---|
| 1 | 独立作用域：新 `State`、新沙箱、span 挂父 | 污染父状态 |
| 2 | 共享预算：`child = parent.split(0.3)`，消耗计入父 | 递归炸成本 |
| 3 | 上限：深度默认 2、并发默认 4、子树步数上限 | 无限递归 |
| 4 | 返回摘要：只回 `answer`+引用+用量，**不回灌 messages** | 父上下文必炸 |
| 5 | 取消传播：父取消 → 子全停（`TaskGroup`） | 孤儿任务继续烧钱 |

结构化返回支持 `expected_schema`；校验失败 → `Verdict(passed=False, action="retry")`。

### M13.6 Hook（层的退化形态）

```python
@dataclass(frozen=True)
class HookEvent:
    point: str            # run_start run_end step_end model_call tool_call checkpoint error
    state_id: str
    fields: dict[str, Any]

class Hook(Protocol):
    point: str
    async def __call__(self, event: HookEvent) -> None: ...    # 返回值忽略
```

| 规则 | 理由 |
|---|---|
| 只读：拿不到 `nxt`，不能改 `Response` | 观察者改结果 = 不可预测 |
| 异常被吞，只发 `hook.error` | 可观测性不得影响可用性 |
| 按注册顺序，不参与拓扑排序 | 观察者之间无依赖 |
| `as_hook(fn)` 生成"不调 `nxt`"的层 | 只有一个扩展点，语义不分叉 |

### M13.7 并发上限的执行位置（定死）

```python
@dataclass(frozen=True)
class RunScope:
    ...
    child_slots: asyncio.Semaphore     # 容量 = config.subagent_concurrency（默认 4）
    depth: int = 0                     # 当前深度
    max_depth: int = 2
```

| 规则 | 理由 |
|---|---|
| 信号量挂在 `RunScope`，不挂在 `SubAgent` 层 | 层是值、可被复制；挂层上会导致"每层各造一个信号量"，总量失控 |
| 子 scope 通过 `child()` **继承同一个信号量对象** | 全局并发上限必须是一份 |
| `depth` 单调递增，`depth > max_depth` → 直接 `ConfigError`（不是运行期拒绝） | 深度上限是静态结构问题，越早报越好 |
| 并发占位在**子运行开始前**获取、结束后释放（`async with`） | 避免"已创建子 Task 但还在排队"的假并发 |

**为什么用信号量而不是队列**：agent 的子任务是有依赖的树状调用，排队会让父等子、子等槽位，产生死锁；信号量只限制同时活跃数，不改变控制流。

---

## 模块 M14 · 拓扑层

**职责（基线 5.7）**：组件的**组合方式**，不是组件。拓扑不改变一次 loop 的内部，只决定有几个 loop、谁拥有控制权。

### M14.1 契约

```python
class Runnable(Protocol):
    name: str
    async def run(self, goal: Goal, *, scope: RunScope) -> RunResult: ...

class Topology(Runnable, Protocol):
    children: tuple[Runnable, ...]
```

### M14.2 四种拓扑（决定权 / 上下文怎么过去 / 坏了的样子）

| 拓扑 | 决定权 | 上下文怎么过去 | 坏了的样子 |
|---|---|---|---|
| `Supervisor` | 一个中心 | 复制（交给 worker 的 `Brief`） | 上下文二次丢失，转述失真 |
| `Handoff` | 当前持有者 | 转移（连同 State 一起交接） | 责任漂移，两个 agent 互相推回 |
| `Blackboard` | 板上的状态（声明式触发） | 共享（读写同一块 `Board`） | 无主垃圾场，并发写冲突 |
| `Pipeline` | 代码（阶段顺序） | 阶段产物契约 | 阶段间契约漂移 |

一句话：**`Supervisor` 是"调用"，`Handoff` 是"转移"，`Blackboard` 是"读写"，`Pipeline` 是"流水"**。

### M14.3 签名与语义

```python
Supervisor(planner, workers: dict[str, Runnable], brief: Callable[..., Brief],
           synth: Callable[[dict[str, RunResult]], str])
Handoff(router: Router, agents: dict[str, Runnable], fallback: Runnable | None = None)
Blackboard(agents: Sequence[Runnable], reducer: Callable[[Board], str],
           trigger: Callable[[Board], bool])          # 声明式规则，不读 agent 意愿
Pipeline(*stages: Runnable)
```

| 约束 | 理由 |
|---|---|
| **R7**：拓扑只分派与汇总，不自己调模型做事 | 否则 `Supervisor` 会长出"实在不行我自己答"的分支 |
| `Blackboard.trigger` 必须是声明式规则 | 由 agent 自荐会让收敛条件变成主观判断 |
| 拓扑只依赖 `Agent`/`State`/`Board`/`Brief` | 换拓扑时组件一行不改 |
| `Brief` 必须带 `context_refs`（原始依据） | 只带结论会在转述里丢页码/来源 |

### M14.4 替换实验（验收方式）

| 替换 | 应当只有一件事消失 |
|---|---|
| `Supervisor → Handoff` | "中心拥有控制权"消失，结论应一致 |
| `Blackboard → Pipeline` | "动态触发"消失，产物应一致 |
| `Supervisor → 单 Agent` | 只有"上下文隔离"消失 |

**任何一次替换导致别的组件报错，就是耦合。**

### M14.5 与子 agent 的分工

| 维度 | 拓扑 | 子 agent（M13.5） |
|---|---|---|
| 何时决定 | 构造期 | 运行期（模型调 `task` 时） |
| 谁决定 | 代码 | 模型 |
| 预算 | 各自独立 | 强制共享父 |
| 适用 | 已知流程 | 模型自己拆任务 |

二者不互斥：`Supervisor` 的 worker 可以自带 `SubAgent` 层。

---

## 模块 M15 · 装配层

**职责（基线第 52 章）**：所有实例化集中于此（R4）。`build(cfg)` 是唯一构造入口。

### M15.1 `build(cfg)` 是判别联合

```python
@dataclass(frozen=True)
class AgentConfig:
    llm: Model
    tools: tuple[Tool, ...] = ()
    body: BodySpec = BodySpec(kind="react", max_steps=24)      # workflow | react | pe
    workflow: tuple[Step, ...] = ()                             # 仅 workflow
    planner: Planner | None = None                              # 仅 pe
    router: Router | None = None
    context: ContextConfig = ContextConfig()
    guard: Guard | None = None
    budget: Budget | None = None
    tracer: Tracer | None = None
    durability: Durability | None = None
    delivery: Delivery | None = None
    reflector: Reflector | None = None
    validator: Validator | None = None
    resilience: ResiliencePolicy | None = None
    knowledge: Knowledge | None = None
    memory: Memory | None = None
    skills: Skills | None = None
    layers: tuple[Layer, ...] = ()
    name: str = "agent"

def build(cfg: AgentConfig) -> Agent: ...
```

**判别联合的校验（基线第 52 章，构造期报错）**

| 组合 | 结果 |
|---|---|
| `body.kind="workflow"` 且 `planner` 非空 | `ConfigError` |
| `body.kind="workflow"` 且 `workflow` 为空 | `ConfigError` |
| `body.kind="react"` 且 `workflow` 非空 | `ConfigError` |
| `body.kind="pe"` 且 `planner` 为空 | `ConfigError` |
| `body.kind="pe"` 且 `workflow` 非空 | `ConfigError` |

### M15.2 装配表：五个问题的答案决定填哪些槽位（基线 5.8）

| 问题 | 落到槽位 | 不填会怎样 |
|---|---|---|
| 这条请求归谁？ | `router` + `Route` | 所有请求走同一条最贵的路 |
| 步骤能提前写死吗？ | `body.kind`、`planner`、`workflow` | 写死不可预知的步骤 → 静默走错；能写死却不写 → 白花钱 |
| 错了代价多大？ | `reflector`、`guard` | 错误直接流到用户或外部系统 |
| 活多久、会不会死？ | `durability`、`idem_key`、拓扑 | 崩一次重来；恢复重复副作用；一个上下文装不下就互相打架 |
| 怎么交回？ | `delivery` | 终止态不清、输出不脱敏、引用编号对不上 |

### M15.3 `Harness`（能力容器 + 生命周期）

```python
@dataclass(frozen=True)
class StoreSpec:                     # 五个存储各一个槽，互不牵连
    durability:   str = "memory"     # "sqlite:runs.db" / "postgres:$DSN"
    session:      str = "memory"
    messages:     str = "memory"
    memory:       str = "memory"     # ← 换记忆介质就改这一行
    idempotency:  str = "memory"

@dataclass(frozen=True)
class BackendSpec:                   # 八个执行/供应后端各一个槽
    fs: str = "local:/work"
    sandbox: str = "local"
    artifacts: str = "memory"
    secrets: str = "env"
    index: str = "memory"
    queue: str = "memory"
    approval: str = "callback"
    clock: str = "system"

@dataclass(frozen=True)
class HarnessConfig:
    model: ModelSpec                                  # "openai:gpt-4.1" 或实例
    tools: tuple[str | Tool, ...] = ()
    stores: StoreSpec = StoreSpec()
    backends: BackendSpec = BackendSpec()
    guardrails: tuple[GuardrailSpec, ...] = ()
    hooks: tuple[HookSpec, ...] = ()
    namespace: NamespaceSpec = NamespaceSpec()
    budget: Budget = Budget()
    limits: Limits = Limits(wall_s=30, output_bytes=1_000_000)
    plugins: tuple[str, ...] = ()

class Harness:
    @classmethod
    def of(cls, config: HarnessConfig | None = None, **kwargs) -> "Harness": ...
    async def __aenter__(self) -> "Harness": ...       # startup：建连接、校验、解析拓扑
    async def __aexit__(self, *exc) -> None: ...       # shutdown：回收沙箱、flush 事件、关连接
    async def run(self, program: Program, goal: Goal) -> RunResult: ...
    def astream(self, program: Program, goal: Goal) -> AsyncIterator[RunEvent]: ...
    async def resume(self, session_id: str, decision: Decision) -> RunResult: ...
    async def dry_run(self, program: Program, goal: Goal) -> list["Effect"]: ...
```

### M15.4 构造期校验清单（缺一条都不许启动）

| # | 校验 | 失败 |
|---|---|---|
| 1 | 层的 `needs` 都有对应能力 | `ConfigError` |
| 2 | 层名唯一（含内置与插件） | `ConfigError` |
| 3 | `after`/`before` 无环 | `ConfigError` |
| 4 | `body.kind` 与 `planner`/`workflow` 的组合合法（M15.1） | `ConfigError` |
| 5 | 工具名唯一；`parameters` 是合法 JSON Schema | `ConfigError` |
| 6 | 引用的护栏/钩子已注册 | `ConfigError` |
| 7 | `mounts.target` 唯一且绝对路径 | `ConfigError` |
| 8 | 层声明的插点在枚举内 | `ConfigError` |

### M15.5 生命周期四个归属（基线 5.9，不新增组件）

| 阶段 | 归属 | 实现 | 为什么不新增组件 |
|---|---|---|---|
| 接入（鉴权/租户/配额） | `Guard.check_identity` | 与准入共享"不通过就拦" | 单独拆会把拒绝逻辑写两遍 |
| 会话（开始/过期/并发/清理） | `Durability` + `Budget(scope="session")` | `open/close/expire` | `SessionRef` 已是数据类型 |
| 配置与版本（prompt/模型/工具/Skill） | 装配层输入 | `build(registry.snapshot(version))`，版本号进 trace | 不改变决策，只改变装哪个实现 |
| 反馈（点踩/纠正） | `Memory.write` 的一条来源 + `Tracer` 事件 | 写 `source="feedback"` 的记忆 | 它是记忆的写入路径，不是新决策点 |

口诀：**"一次请求一次的事"归壳（`Guard`/`Delivery`），"跨请求的事"归存储（`Durability`/`Budget`/`Memory`），两者都不是组件。**

### M15.6 插件与预设

```toml
[project.entry-points."harness.layers"]
taskboard = "my_pkg.layers:TaskBoard"
[project.entry-points."harness.backends"]
"fs.s3" = "my_pkg.s3:S3FS"
```

| 规则 | 理由 |
|---|---|
| 插件只经协议扩展，不得 import 内核内部 | 否则内核一改就全断 |
| 名字冲突 → `ConfigError` | 静默覆盖是灾难 |
| 单个插件加载失败不影响核心启动 | 只让引用它的配置项报错 |

| 预设 | body | 层 | 适用 |
|---|---|---|---|
| `minimal` | react(8) | 无 | 冒烟 |
| `react` | react(24) | budget, trace | 普通工具 agent |
| `workflow` | workflow(steps) | trace, checkpoint | 确定性流程 |
| `pe` | pe(planner) | budget, validate | 长任务 |
| `production` | react(24) | 全部 17 | 生产默认 |

### M15.7 spec 字符串解析（装配层的入口，定死语法）

**两种形态，语法固定**：

```python
# 简写：name 或 name:arg（arg 语义由 name 决定）
model="openai:gpt-4.1"           # name=openai, arg=模型名
stores=StoreSpec(memory="postgres:postgresql://h:5432/mem")
backends=BackendSpec(fs="local:/work")
# 完整形态：dict（用于简写表达不了的参数）
stores=StoreSpec(memory={"kind": "postgres", "dsn": "...", "pool": 10, "schema_per_tenant": True})
```

| 规则 | 内容 |
|---|---|
| 语法 | `name[:arg]`；`name` 匹配 `[a-z][a-z0-9_]*`；`arg` 为 `:` 之后全部字符（允许 `/` `//` `?` `=`，不支持转义） |
| 解析 | `name` → 注册表条目 → `factory(arg=..., **config)` → 实例 |
| 注册表 | 内置表（见下）+ 插件 entry points（`harness.models` / `harness.stores` / `harness.backends` / `harness.layers` / `harness.guardrails`） |
| 未知 name | `ConfigError`，并**列出该分类下的可用名字**（排查成本从这里省） |
| 歧义 | 同一平级分类内重名 → `ConfigError`（插件不覆盖内置） |
| 懒加载 | 适配器模块只在解析到时 import，`harness.contracts` 不因配置而引入第三方依赖 |

**内置注册表（初始集）**

| 分类 | 名字 |
|---|---|
| `models` | `openai` `anthropic` `gemini` `ollama` `fake` |
| `stores` | `memory` `sqlite` `postgres` `redis` |
| `backends.fs` | `local` `memory` `s3` |
| `backends.sandbox` | `local` `subprocess` `docker` `fake` |
| `backends.artifacts` | `memory` `local` `s3` |
| `backends.secrets` | `env` `memory` `vault` |
| `backends.index` | `memory` `qdrant` `pgvector` |
| `backends.queue` | `memory` `redis` |
| `backends.approval` | `callback` `http` `memory` |
| `backends.clock` | `system` `fake` |
| `layers` | M13.4 的 17 个 |
| `guardrails` | `injection` `pii` `secret_leak` `toxicity` |

**为什么配置只描述意图**：`Program`/`HarnessConfig` 可序列化、可 diff、可存库（M1.9）；`Harness.of()` 负责把声明变成实例（R4 唯一构造点）。**解析失败一律启动期报错**，不允许运行期才发现后端不存在。

---

## 模块 M16 · 错误、测试与验收

### M16.1 错误分类（决定重试与出口）

| 类 | 例子 | 重试 | 出口状态 |
|---|---|---|---|
| `ConfigError` | 组合非法、依赖缺失、环 | 否 | 启动期抛出，不进循环 |
| `ContractError` | 部件返回类型错 | 否 | `FAILED` |
| `ConcurrencyError` | `expect_rev` 不匹配 | 否 | `REFUSED`（提示刷新） |
| `ValidationError` | 参数不合法 | 否 | `REFUSED` |
| `TransientError` | 超时、限流、5xx | **是**（退避 3 次） | 耗尽 → `DEGRADED` |
| `PolicyError` | Gate 拒绝、护栏 block | 否 | `REFUSED` |
| `BudgetError` | 预算耗尽 | 否 | `DEGRADED` |
| `ApprovalError` | 过期、驳回 | 否 | `REFUSED` |
| `ToolError` | 工具失败（回灌模型） | 看 `idempotent` | 步数耗尽 → `DEGRADED` |
| `CancelledError` | 外部取消 | 否 | `CANCELLED` |

#### M16.1.1 异常 → `Failure` 的默认映射（`DefaultFilter` 的实现，定死）

```python
@dataclass(frozen=True)
class Failure:
    status: RunStatus
    reason: str
    retryable: bool = False
```

| 异常 | `Failure` | 说明 |
|---|---|---|
| `ConfigError` | 不映射（启动期已抛） | 运行期出现即 `ContractError` |
| `ContractError` | `(FAILED, "contract", False)` | 部件违约，不可重试 |
| `ConcurrencyError` | `(REFUSED, "concurrency_conflict", False)` | 提示调用方刷新后重试 |
| `ValidationError` | `(REFUSED, "invalid_args:<field>", False)` | 参数错，重试也不会对 |
| `TransientError` | `(DEGRADED, "transient_exhausted", True)` | 重试次数耗尽后的终态 |
| `PolicyError` | `(REFUSED, "policy:<rule>", False)` | Gate 拒绝 / 护栏 block |
| `BudgetError` | `(DEGRADED, "budget", False)` | 预算耗尽 |
| `ApprovalError` | `(REFUSED, "approval:<原因>", False)` | 过期/驳回 |
| `ToolError` | `(DEGRADED, "tool", True)` | 仅在步数耗尽时走到这里；否则回灌模型 |
| `asyncio.CancelledError` | `(CANCELLED, "cancelled", False)` | **必须原样识别，不吞** |
| `asyncio.TimeoutError` | `(DEGRADED, "timeout", True)` | 被 `Resilience` 包装后不应到达 |
| **其他未知异常** | `(FAILED, type(exc).__name__, False)` | **fail-closed**：不猜可重试 |

三条规则：① `retryable` 只对 `TransientError` / `TimeoutError` / `ToolError` 为真；② `reason` 必须带可定位信息（字段名/规则名/异常类名），不允许空字符串；③ `Filter` 只归类，**不改 `State`、不发事件**（事件由 `Audit`/`Trace` 层负责）。

### M16.2 `RunStatus` 七态与合法转换

| 状态 | 含义 | 终结 | 从哪来 |
|---|---|---|---|
| `RUNNING` | 运行中 | 否 | 内存态；**禁止出现在 `RunResult`** |
| `COMPLETED` | 答完 | 是 | `Done` |
| `DEGRADED` | 降级（预算/步数/降级兜底/流式中断） | 是 | 循环出口 |
| `REFUSED` | 拒答（准入/护栏/并发冲突/参数非法） | 是 | `Guard`/`Guardrail`/`Check` |
| `FAILED` | 失败（契约错、工作流首错） | 是 | `Classify` |
| `NEEDS_APPROVAL` | 挂起待批 | 是（可恢复） | `Approval` |
| `CANCELLED` | 被取消 | 是 | 取消传播 |

### M16.3 一致性测试基类（每个协议一个）

```python
class DurabilityConformance:
    async def test_put_get_roundtrip(self): ...
    async def test_history_increasing_rev(self): ...
    async def test_old_rev_immutable(self): ...          # C1
    async def test_optimistic_conflict_raises(self): ...  # C2
    async def test_namespace_isolation(self): ...         # C3

class MemoryConformance:
    async def test_upsert_then_recall(self): ...
    async def test_recall_limits_k_and_orders_by_score(self): ...   # 只断言 ≤k 与降序，不断言精确分数
    async def test_recall_filters_layers(self): ...                  # layer 必须下推
    async def test_namespace_isolation(self): ...                    # 跨 ns 必须读不到
    async def test_dedup_key_overwrites_not_appends(self): ...        # C4
    async def test_concurrent_upsert_same_key_yields_one_row(self): ...  # 靠 DB 唯一约束
    async def test_forget_is_soft_and_hides_from_recall(self): ...
    async def test_expire_removes_from_recall_only(self): ...

class KeyValueLogConformance:      # SessionStore / MessageLog / Idempotency 共用骨架
    async def test_append_only(self): ...
    async def test_tail_respects_token_budget(self): ...
    async def test_namespace_isolation(self): ...
```

`MemoryConformance` 是"换记忆介质"的验收标准：**通过即可替换，不需要读源码**。它不断言打分绝对值，因为不同后端的相似度不可比——这是唯一被允许的"宽松断言"。

```python
class FramerConformance:
    async def test_never_drops_goal(self): ...
    async def test_over_budget_marks_dropped_and_adds_omission(self): ...
    async def test_dropped_disjoint_from_sections(self): ...
    async def test_deterministic_for_same_state(self): ...      # 可回放
    async def test_priority_order_respected(self): ...

class EncoderConformance:
    async def test_output_consumable_by_target_model(self): ...  # 结构合法（一次 fake 调用即可）
    async def test_does_not_mutate_frame(self): ...              # frame 是 frozen，无法改
    async def test_idempotent(self): ...

class GuardrailConformance:
    async def test_declared_gates_match_behavior(self): ...      # 只在声明的闸上触发
    async def test_stricter_action_wins_under_arbitration(self): ...
    async def test_detector_failure_blocks_by_default(self): ... # fail-closed
    async def test_spans_within_text_bounds(self): ...
```

**每个协议一个基类、每类实现继承它**——这是"可替换"唯一的验收凭证（§1.4 第 1 条）。新写一个 Qdrant 索引、一个 Docker 沙箱、一个 OpenAI 编码器，跑通对应用例即可上线，不必等 review 看懂实现。

**新写一个 Postgres / S3 / 沙箱实现，跑通这组用例就能换上去。** 这是框架对使用者的唯一可信承诺。

子类只提供 `factory()`；不允许跳过用例（`pytest.mark.skip` 需在 PR 中说明）。

### M16.4 替换实验矩阵（基线 5.3 + 5.7，最终验收）

| 替换实验 | 应当只有一件事消失 |
|---|---|
| `Reflector → NullReflector` | 自我纠错消失 |
| `Router → AlwaysRoute` | 分流消失 |
| `Knowledge → NullKnowledge` | 查资料消失，退化成纯对话 |
| `Planner → ImplicitPlanner` | P&E 退化成 ReAct |
| `Durability → NullDurability` | 崩溃不可恢复，其余不变 |
| `Supervisor → Handoff` | "中心拥有控制权"消失，结论一致 |
| `Blackboard → Pipeline` | "动态触发"消失，产物一致 |
| `Supervisor → 单 Agent` | 只有"上下文隔离"消失 |

取 3 个点（分别属五种装配形态 × 四种拓扑），每点跑一次替换实验，即为副线验收通过。

### M16.5 假件清单（`impl/fakes/`，不进生产包）

`FakeModel`（脚本化回复 + 记录 seen）· `FakeClock` · `FakeSandbox`（记录命令、返回剧本）· `FakeFS`（内存挂载）· `FakeKnowledge` · `FakeMemory` · `FakeDurability` · `MemoryTracer`。

---

## 17. 公开 API 总表

### 17.1 门面 API（`harness.fp`，使用者 95% 只用这一层）

| 名字 | 签名 | 说明 |
|---|---|---|
| `react` | `react(*, max_steps=24, tools=None) -> Program` | ReAct 主体 |
| `workflow` | `workflow(*steps, on_tool_error="stop") -> Program` | 固定工作流 |
| `pe` | `pe(planner, *, max_replan=2) -> Program` | Plan-and-Execute |
| `skill_program` | `skill_program(skills, name) -> Program` | Skill 编译成工作流 |
| `compose` | `compose(*layers) -> Layer` | 由声明约束拓扑排序 |
| `>>` | `Program >> Layer -> Program`；`Layer >> Layer -> Layer` | 顺序组合（左为外层） |
| `\|` | `Layer \| Layer -> Layer` | 回退：前者抛错则整体改用后者 |
| `tenancy` `budget` `trace` `audit` `checkpoint` `validate` `approval` `idempotent` `retrieval` `memory_recall` `memory_write` `context` `input_guard` `output_guard` `capability` `subagent` `taskboard` | 均为 `(...) -> Layer` | 14 个内置层 + 2 个复合层 |
| `as_hook` | `as_hook(fn, point) -> Layer` | 观察者 |
| `pipeline` `supervisor` `handoff` `blackboard` | `(...) -> Runnable` | 四种拓扑 |
| `Harness.of` | `Harness.of(config=None, **kwargs) -> Harness` | 能力容器 |
| `run` / `astream` / `dry_run` | `harness.run(program, goal)` 等 | 执行 |
| `describe` | `describe(program) -> str` | 打印解析后的层顺序 |

### 17.2 契约 API（`harness`，写部件时才用）

`Goal` `Step` `ToolCall` `ActionResult` `Verdict` `Plan` `Recalled` `Pack` `SessionRef` `Brief` `Board` `Route` `State` `RunResult` `Frame` `Section` `Namespace` `Limits` `Mount` `ExecResult`，以及 M1.6 的 33 个协议。

### 17.3 工具 API

| 名字 | 说明 |
|---|---|
| `@tool` | 从函数签名生成 `ToolSpec`，可带 `side_effects`/`scopes`/`idempotent` 等 |
| `ToolRegistry` | `add`/`get`/`schemas(allow=...)` |

---

## 18. FP 组合 API（开发体验主线）

### 18.1 三个类型

```python
@dataclass(frozen=True)
class Layer:      # 单一扩展单元
    name: str; points: frozenset[Point]; needs: frozenset[str]
    after: frozenset[str]; before: frozenset[str]
    build: Callable[[Handler], Handler]

@dataclass(frozen=True)
class Program:    # 策略单元 = body + 若干层
    body: BodyPolicy
    max_steps: int
    layers: tuple[Layer, ...]
    def __rshift__(self, layer: Layer) -> "Program": ...   # 追加层

@dataclass
class Harness:    # 能力容器
    ...
```

### 18.2 语义定死

| 表达式 | 结果 | 顺序语义 |
|---|---|---|
| `compose(a, b, c)` | `Layer` | **由 `after/before` 拓扑排序**，写法顺序不决定顺序；有环 → `ConfigError` |
| `a >> b` | `Layer` | `compose(a, b)` **并追加 pin `a.before ∋ b.name`**，即左为外层 |
| `a \| b` | `Layer` | 回退：`a` 抛错则整体改用 `b`（共享同一个内层） |
| `program >> layer` | `Program` | 追加层，不改变 body |
| `r1 >> r2`（两个 `Runnable`） | `Pipeline` | 上一阶段 `answer` 作为下一阶段 `goal` |
| `describe(x)` | `str` | 打印**解析后**的顺序与约束来源 |

**为什么 `>>` 要 pin 而 `compose` 不 pin**：`compose` 让框架排，`>>` 让人排。两者都要有——前者防手误，后者表达真实依赖（如"护栏必须在取景之后"）。

### 18.3 为什么以组合为主

| 维度 | 组合式 | 类式装配 |
|---|---|---|
| 加一个关注点 | `>> checkpoint()` 一次追加 | 改构造签名 / 加参数 |
| 换一个实现 | 换 `Harness` 的 backend | 改 `build()` 分支 |
| 干跑（不执行） | `harness.dry_run(program, goal)` | 需要 mock |
| 可 diff / 可存库 | 是（`Program` 是值） | 否（含实例） |
| 可见性 | 需 `describe` 补 | 构造参数自解释 |

**判据（定死）**：需要组合的关注点 ≤ 6 个时用显式构造参数；> 6 个时用组合。

---

## 19. 使用示例（基线六例 + 编码 agent）

> 全部示例只改配置与组合，不改任何组件代码——这是 R2/R4/R6 的验收方式。

### 19.1 最小（最小装配形态）

```python
import asyncio
from harness import Goal, tool
from harness.fp import Harness, react

@tool
async def concat(left: str, right: str) -> str:
    """拼接两段文本。"""
    return left + right

async def main():
    h = Harness.of(model="fake", tools=[concat])
    result = await h.run(react(max_steps=4), Goal("把 a 和 b 拼起来"))
    print(result.status, result.answer)

asyncio.run(main())
```

**验收**：一次工具调用跑通（基线"最小"形态）。

### 19.2 RAG 问答（三级路由 + 四槽位装配）

```python
program = (
    react(max_steps=6)
    >> budget(tokens=40_000)
    >> retrieval(k=6)              # 调 Knowledge.retrieve → 写 retrieved 槽
    >> context(ratios={"system": .1, "memory": .15, "retrieved": .5, "history": .25})
    >> input_guard(injection=True)
    >> output_guard(pii=True, citations=True)
)
h = Harness.of(model="openai:gpt-4.1", index="qdrant:faq",
               guardrails=("injection", "pii"))
```

**验收**：坏回答能归因到具体组件（检索 or 装配 or 护栏）。

### 19.3 退款执行（P&E + 审批 + 幂等）

```python
program = (
    pe(planner=llm_planner(checks=[max_steps(3)]))
    >> budget(tokens=20_000)
    >> approval(when="write")       # 只看 side_effects，不猜工具名
    >> idempotent()
    >> checkpoint()
)
h = Harness.of(model="openai:gpt-4.1", tools=[query_order, refund],
               stores={"durability": "sqlite:runs.db"},
               guard=policy_guard(rules=[max_amount(500), same_tenant()]))

result = await h.run(program, Goal("给 A1001 退 100"))
if result.status is RunStatus.NEEDS_APPROVAL:
    result = await h.resume(result.state.session.session_id, Decision.approve("alice"))
```

**验收**：一次越权被拦 + 一次中断恢复 + 重试不重复扣款。

### 19.4 编码 agent（沙箱 + 文件系统 + 子 agent + 任务板）

```python
program = (
    react(max_steps=40)
    >> budget(tokens=400_000)
    >> taskboard()                  # 任务清单抗压缩
    >> capability(fs="/work", sandbox="docker", secrets={"gh": "GH_TOKEN"})
    >> subagent(depth=2, concurrency=4)
    >> validate(reflector=tests_reflector("pytest -q"))
    >> checkpoint()
    >> approval(when="shell")
)
h = Harness.of(model="anthropic:claude-sonnet",
               tools=[read_file, write_file, edit_file, glob, grep, run_tests],
               backends={"fs": "local:/work", "sandbox": "local"},
               limits=Limits(wall_s=60, output_bytes=2_000_000))
```

**验收**：有天然裁判（测试）才敢让它改代码；沙箱越界被拒；子 agent 共享预算。

### 19.5 研究报告（Supervisor，基线第 53 章主例）

```python
workers = {n: harness_agent(cfg[n]) for n in ("extract", "analyze", "write")}
pdf = supervisor(
    planner=llm_planner(checks=[max_steps(3), tool_whitelist(WORKER_TOOLS)]),
    workers=workers,
    brief=lambda goal, step: Brief(goal=goal,
                                   context_refs=[goal.text],     # 带原始依据
                                   done=[], forbidden=["改写原文"]),
    synth=merge_reports,                                          # 只汇总（R7）
)
```

**验收**：换成 `handoff` 结论一致，只少了"中心拥有控制权"。

### 19.6 四种拓扑同任务对照（基线第 53 章）

| 拓扑 | 怎么分 | 成本记号 | 失效 |
|---|---|---|---|
| 流水线 | 解析 → 切块 → 逐节摘要 → 汇总 | 阶段数 × 一次调用（最便宜） | 阶段契约漂移 |
| supervisor | 1 中心 + 3 worker | agent 数 × 各自上下文 + 汇总一次 | 转述失真（丢页码） |
| handoff | 通用 agent 遇专业问题 → 交接 | 每次交接复制一次 State | 责任漂移 |
| blackboard | N 个分节 agent 并行写共享板 | 写入次数 + 冲突重试 | 无主垃圾场 |

### 19.7 组合可见性（`describe`）

```python
print(describe(program))
# react(24) > tenancy > budget(400000) > trace > taskboard > capability > subagent > approval > checkpoint
```

组合的代价是"看不见最终顺序"，`describe` 是必须提供的补偿。

---

## 20. 任务拆分（给实施方）

> 每期只做一期的事；**P1 的验收是现有 18 个测试全绿**，测试一红说明骨架抽错，立即回头。

| 期 | 目标 | 交付物 | 验收 |
|---|---|---|---|
| **P1 骨架** ✅ | 目录重排（六层）、依赖 AST 测试、`RunScope`、四段链、`Classify` 出口 | `kernel/{scope,stage,chain}.py`、`tests/test_architecture.py`、`tests/test_kernel.py` | **已完成（2026-11-04）**：18 个原测试 + 4 条架构用例 + 16 条内核用例 = **38 全绿**，行为零变化 |
| **P2 契约** ✅ | 12 类型补齐 v2 字段、33 协议、错误分类、`RunStatus` 七态 | `contracts/{types,status,events,protocols/*}.py`、`tests/test_contracts.py` | **已完成（2026-11-04）**：30+ 类型冻结检查、七态与 TERMINAL 集合、协议运行期可判定、`__all__` 完整、`State` 带 `schema_version` 往返；54 测试全绿（18 原 + 4 架构 + 16 内核 + 16 契约） |
| **P3 存储与后端** ✅ | 5 存储 + 工件 + 8 后端的内存实现 + 一致性测试基类 | `impl/stores/memory.py`、`impl/backends/{paths,fs,core}.py`、`tests/{conformance,test_stores,test_backends}.py` | **已完成（2026-11-05）**：5 存储跑通 21 条 conformance；9 个后端（FS×2/沙箱×2/工件/密钥×2/索引/队列/审批×2/时钟×2）；路径 jail 12 条用例含 traversal/只读/符号链接逃逸；**101 测试全绿（1 跳过：平台不允许建符号链接）** |
| **P4 部件**（17/17 层 ✅） | 15 组件 + 17 层 + 四拓扑 | 17 层全部落地（含 input_guard/output_guard 与五道闸仲裁）；`parts/tools.py` schema 推导 ✅、`parts/capability.py` ✅、`parts/subagent.py` ✅；剩三策略迁 v2 签名 + 四拓扑 `scope` 参数 | 取景 12 + 层 14 + 治理 15 + 工具/能力 19 + 子 agent/薄层 11 + 护栏 19 条；**193 测试全绿** |
| **P5 门面** | `fp`：`Layer`/`Program`/`Harness`/`compose`/`>>`/`describe`/`dry_run` | `fp/*` | §19 前 5 个示例可跑 |
| **P6 装配** ✅ | spec 解析与注册表、八条构造期校验、Harness 归位、五预设 | `assembly/{registry,config,harness,fpresets}.py` | **已完成（2026-11-05）**：`name[:arg]`/dict 两形态解析；未知名报错并列出可用名；缺适配器给安装提示；8 条校验（护栏/工具重名/层名/预算/深度/租户/挂载/存储可解析）；换存储介质只改配置；**226 测试全绿** |
| **P7 护栏与流式** | 五道闸、三段式、流式护栏、`astream` | `parts/guardrail`、`fp/runtime` | 五闸各有测试；流式中断语义正确 |
| **P8 验收** | 替换实验矩阵（取 3 点）、`adapters/openai`、CLI 脚手架 | `adapters/*`、`cli` | 替换实验全过；真实模型跑通 |

**拆分原则**：每个任务都以"一个协议 + 一个内存实现 + 一组一致性测试"为最小交付单位；不允许交付"只有实现没有测试"的部件。

---

## 21. 验收清单（DoD）

### 21.1 每个部件的 DoD

- [ ] 实现对应协议，无额外公开方法
- [ ] 有内存/假件实现，且与真实实现共用一致性测试
- [ ] 有至少一条"失败路径"测试（超时/越界/拒绝）
- [ ] 不 import 白名单外的模块（§3.3 测试覆盖）
- [ ] 在 `describe` 里可见（若为层）
- [ ] 在归位表里能指到唯一格子

### 21.2 整个框架的 DoD

- [ ] 五个预设各跑一次（§19 前五个示例）
- [ ] 四种拓扑各跑一次（§19.6）
- [ ] 替换实验矩阵取 3 点全过（M16.4）
- [ ] 全部测试离线：无网络、无真实沙箱、无真实 FS
- [ ] `config` 非法组合在启动期报 `ConfigError`（8 条校验）
- [ ] `RunResult.status` 永不为 `RUNNING`
- [ ] 同一 State 重放两次结果一致
- [ ] `describe` 能打印任何 `Program` 的解析顺序
- [ ] 内置层构成的 `Program` 可 `to_spec()` 再 `from_spec()`，往返相等
- [ ] `dry_run` 返回的 `Effect` 序列与真实执行的实际调用序列一致

---

## 22. 版本与兼容

| 项 | 规则 |
|---|---|
| `contracts_version` | 主版本号 = 破坏性变更（协议方法签名、必填字段、状态机） |
| 协议演进 | **只加不删**：新增方法必须给默认实现（mixin），否则算主版本变更 |
| 数据演进 | `State.to_dict()` 带 `schema_version`；读取走迁移函数链，**不允许"读旧数据直接崩"** |
| 弃用流程 | 标记 `@deprecated` → 一个主版本内双轨 → 删除；`CHANGELOG` 必须写迁移片段 |
| 配置兼容 | 不认识的 spec 名 → `ConfigError`（不静默降级）；spec 名一经发布不改语义 |
| 存档兼容 | 旧 `rev` 的 `State` 必须能被新版 `from_dict` 读出（可丢 v2 字段，不可抛错） |

**为什么这条必须写死在文档里**：`Durability` 的旧检查点、`Memory` 里的旧条目、用户存的 `ProgramSpec` 都是**跨版本数据**。没有这条，P3 一改协议就没人敢升级。

## 23. 缺口台账

诚实地记录边界，避免实施方以为读完了就够了。**下表是本文的自我体检结果**，随着补写逐行关闭。

### 23.1 已关闭（本轮补齐）

| # | 缺口 | 关闭于 | 关键决定 |
|---|---|---|---|
| 1 | spec 字符串解析与注册表 | **M15.7** | `name[:arg]` + dict 完整形态；未知名报 `ConfigError` 并列出可用名 |
| 2 | `@tool` 签名 → JSON Schema | **M3.5.1** | 九行类型映射表；**无标注一律拒绝**，不默认 `string` |
| 3 | `Pipe` 内置实现 | **M2.2.1** | Default→Schema→Coerce 固定顺序；转换失败不猜 |
| 4 | 异常 → `Failure` 映射 | **M16.1.1** | 十一种异常逐条映射；未知异常 fail-closed |
| 5 | 取消语义 | **M10.4** | 只在 step 边界生效；`CancelledError` 只在 `Classify` 捕获 |
| 6 | 子 agent 并发上限位置 | **M13.7** | 信号量挂 `RunScope` 并被子 scope 共享 |
| 7 | `Framer`/`Encoder`/`Guardrail` 一致性测试 | **M16.3** | 三个新基类，共 12 条用例 |
| 8 | 辅助类型字段 | **M1.11** | `Document`/`Job`/`Match`/`Stat`/`ArtifactRef`/`SessionMeta` 等十类 |
| 10 | 多租户隔离级别 | **M11.4** | 默认逻辑隔离；级别由 `StoreSpec` 承载，业务零改动 |
| 11 | 配额与限流归属 | **M8.4** | 判定在 `Guard`（纯函数）、累加在 `BudgetGuard`（唯一写者） |
| 12 | 流式中途被护栏 block | **M9.4 + M10.4** | 已发 token 不可撤回；检查点落 `DEGRADED`，原因码固定 |

### 23.2 仍开放（已知未设计）

| # | 缺口 | 影响 | 触发时机 |
|---|---|---|---|
| 9 | **CLI 设计**（`harness new` 模板、`harness check` 输出格式） | P8 无法开工 | P7 末 |
| 13 | **`Board.commit` 的并发语义**（多 agent 同时写黑板时的 reducer 幂等性） | Blackboard 在并发下可能丢结论 | P4 做拓扑时 |
| 14 | **`Judge` 的裁判协议**（判定粒度、跨模型校准、与 `Validator` 的边界） | 外部裁判只能自研 | P4 做校验层时 |
| 15 | **`ProgramSpec` 的版本兼容**（旧 spec 在新层表下如何降级） | 配置漂移 | P6 做装配时 |
| 16 | **工件回收策略**（`ArtifactStore` 的 TTL 与 GC 触发点） | 磁盘无限增长 | P3 做工件时 |
| 17 | **多模态内容**（图像/文件作为 `Message` 的一部分） | 无法接视觉模型 | P8 之后 |

### 23.3 处理规则

- 开放项**不得**被实现方自行决定：先在本文补一节，再写代码。
- 每关闭一项，把它从 23.2 移到 23.1，并写清"关键决定"。
- 关闭时若改变了任何协议签名 → 按 §22 走主版本号。

---

## 附录 A · 决策记录（ADR）

| # | 决策 | 备选 | 理由 |
|---|---|---|---|
| 1 | 内核不可替换，只可拦截 | 可替换内核（图运行时） | 保住"一个内核"的确定性与可测性 |
| 2 | Program 与 Harness 分离 | 一个 Agent 对象全包 | 换后端不改程序，从约定变类型事实 |
| 3 | 四段执行链分离 | 单一洋葱 | 四段失败语义不同，合并后 deny 与校验失败无法区分 |
| 4 | 九插点收敛为四个可包裹插点 | 九插点全部做成中间件 | ③④⑥ 不是"包裹一对请求响应"的形状 |
| 5 | 取景-编码分两段 | 单段 `assemble` | 选择与格式是两个变化原因 |
| 6 | 五道闸、检测与动作分离 | 只做输入/输出两道 | 间接注入主战场在检索与工具结果 |
| 7 | 四存储 + 工件 | 单一 `Durability` | 访问模式不同，覆盖写违反历史不可变 |
| 8 | 层顺序拓扑排序 | 手工顺序 | 组合爆炸，第三方无法插入 |
| 9 | hook = 退化中间件 | 独立 hook 系统 | 单扩展点，语义不分叉 |
| 10 | 组合以函数复合为一等形态 | 类式装配为主 | 可组合、可替换、可干跑 |
| 11 | 同 session 串行 | 并发 + 合并 | 检查点一致性优先 |
| 12 | 不支持同一 run 内并行工具调用 | 并行 + 部分失败合并 | 部分失败没有唯一语义 |
| 13 | 历史不可变用多版本快照 | 事件日志 + fold | 事件日志需效果记忆化与 schema 演进 |
| 14 | 预算五机制同一组件（`Resilience`） | 超时/重试/限流/熔断/降级各拆一个 | 五者共享一份失败计数 |
| 15 | 检查点默认全留、按 namespace 配窗口 | 全局滚动窗口 | 时间旅行是能力不是成本项 |
| 16 | 一致性测试定义可替换性 | 文档声明 | 唯一可信的兼容承诺 |
| 17 | 护栏规则只允许 Python，不做 DSL | 仓库级规则 DSL | DSL 要自带解析/版本/测试 |
| 18 | 子 agent 支持 `expected_schema` | 只回文本 | 调用方要程序化用结果 |
| 19 | 提供 CLI 脚手架（P8） | 只给文档示例 | 20 行体验需固化 |
| 20 | 多租户默认逻辑隔离，级别由 `StoreSpec` 承载 | 默认物理隔离 | 物理隔离是运维选择；跑 demo 不该建三个库（M11.4） |
| 21 | 配额判定在 `Guard`、累加在 `BudgetGuard` | 一处读写 | 判定必须是纯函数才能在 dry_run 与测试里复用（M8.4） |
| 22 | 取消只在 step 边界生效 | 随时可中断 | 工具中途取消会留下"副作用已发生但未记账"的半状态（M10.4） |
| 23 | 子 agent 并发信号量挂在 `RunScope` | 挂在 `SubAgent` 层 | 层是值、可复制；挂层会导致每层各造一个，总量失控（M13.7） |

## 附录 B · 术语

| 术语 | 含义 |
|---|---|
| 插点 | loop 上的九个语义位置；运行期四个可包裹点 |
| 段 | step 内四阶段：Gate/Check/Wrap/Classify |
| 组件 | 十五个语义部件（基线） |
| 层 | 挂到插点上的可组合包裹单元 |
| 程序 / 运行器 | 策略值 / 能力容器 |
| 取景 / 编码 | 选内容 / 变格式 |
| 闸 | 护栏五个位置 |
| 视图 | 描述手段：控制流 / 依赖 / 数据 |
| 替换实验 | 换掉一个部件，只应消失一件事 |

## 附录 C · 与 v1 代码的差异清单（迁移时逐条核对）

| v1 现状 | 本文要求 | 动作 |
|---|---|---|
| `Durability.save(state)` 覆盖写 | `put(expect_rev)` 多版本 | 改签名 + 迁移数据 |
| `Context.assemble` 五合一 | `Framer` + `Encoder` | 拆类 |
| `Memory` 只有 recall/write | 加 forget/expire + `MemoryPolicy` | 扩协议 |
| `Tool` 四字段 | `ToolSpec` 十字段 + `ToolContext` | 扩协议 |
| `Resilience` 只有超时+重试 | 五机制共享失败计数 | 重写 |
| `policy.__class__.__name__ == "WorkflowPolicy"` | `on_tool_error` 属性 | 删除该判断 |
| `allowed_tools` 解析但不执行 | 在 `Capability` 层过滤 `schemas(allow=)` | 接线 |
| `TraceEvent.parent_id` 从不填写 | 必须真实填写 | 补实现 |
| 无 Router 单独层 | `Router` + `Route` 四契约 | 新增 |
| 无护栏（只有 Guard） | 五道闸 + 三段式 | 新增 |
| `RunResult` 无 `rev` | 加 `rev` 指向最终检查点 | 扩字段 |

---

