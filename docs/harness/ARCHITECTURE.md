# agent-harness 框架架构设计

> **版本** v2 设计稿 · 2026-11-04
> **范围** `code/harness/`（副线组件基座）
> **基线** 卷 12（第 48–53 章）大纲的全部功能，逐条落到层见 §1.3；v1 的 12 类型 / 11 接口语义不改
> **前置阅读** `docs/harness/DEV-SESSION.md`（施工记录）、第 48–53 章（设计理由）
> **本文性质** 架构决策文档，不是 API 手册。凡写"必须/禁止"的，都可落成可执行检查。

---

## 0. 结论

### 0.1 十一条

1. 现在的包是**库**，不是框架；差别不在接口数量，在**控制反转**。收口方案：内核只保留一条固定骨架，其余全部下沉为可组合部件（中间件 / 后端 / 存储 / 取景编码）。
2. **结构模型 = 两条不变量 + 三个视图**：不变量是「历史不可变」「资源单一所有者」；三个视图是控制流、依赖、数据。「插点 × 挂载」矩阵是**变更归位表**，不是模型（§2.4 给出它的五条局限）。
3. 彻底解耦的抓手不是"多写 Protocol"，是**依赖方向单一**（六边形 / Ports & Adapters）：除契约层外，任何模块只能 import 契约层。这条用可执行测试守住，不靠自觉。
4. 一次 `step` 走**四段执行链**：**Gate（准入，返回判定不抛错）→ Check（校验，抛 `ValidationError`）→ Wrap（包裹，可改请求与结果）→ Classify（异常 → `RunStatus` 的唯一映射）**。四段失败语义不同，不可合并、不可重排（§5.2）。
5. 给模型看的上下文由两段产出：`Framer` 取景（选、排序、裁剪，产出 `Frame`）→ `Encoder` 编码（`Frame` → 载荷）。一份 State 出四种帧：model / human / approval / trace（§6）。
6. 护栏独立于 Guard：**Guard 管"动作能不能做"（决策边界），Guardrail 管"内容能不能进出"（数据边界）**；入站、入上下文、出模型、工具边界、出口共五道闸。
7. 内置中间件 12 个，顺序由**声明式依赖 + 拓扑排序**得出，不由人手排。
8. Store 拆五个（会话 / 检查点 / 消息日志 / 记忆 / 幂等），另有 Artifact 存大对象；记忆的难点在 `MemoryPolicy`，不在 Store 本身。
9. 后端十个（模型 / 文件 / 沙箱 / 工件 / 密钥 / 索引 / 事件 / 队列 / 审批 / 时钟），一律窄接口 + 内存实现 + 一致性测试。
10. 所有资源走**作用域**（run scope → step scope → child scope），`async with` 收口；子 agent 默认独立沙箱、共享预算。
11. 迁移四期，每期可回滚；期 1 的唯一验收标准是**现有 18 个测试全绿**。

### 0.2 三条设计来源的处置

| 来源 | 处置 | 具体 |
|---|---|---|
| 护栏分输入、输出 | **采纳并扩展** | 两道不够，共五道闸（§8.2）；检测与动作分离（§8.3）；流式输出必须增量护栏（§8.4）；护栏自身崩溃的默认语义显式定义（§8.5） |
| 统一结构模型之问 | **不设总模式** | 可变性有三个正交方向（控制流 / 依赖 / 数据），任何单一模式只能描述其中一个。模型定为**两条不变量 + 三个视图**（§2.4），数据视图用取景-编码表达（§6） |
| 洋葱式拦截 | **定为四段执行链** | 洋葱只覆盖"包裹一对"，表达不了准入、校验、错误归类。四段各有独立失败语义，洋葱仅存在于 `Wrap` 段（§5.2）；不提供装饰器、DI 容器、请求作用域模型 |

### 0.3 原始四问的落点

| 原始问题 | 落点 | 一句话结论 |
|---|---|---|
| Store 是否抽象 | §10 | 要，但拆五个 + Artifact；接口只做存取，写入策略独立成 policy |
| 沙箱 / 文件系统后端 | §11 | 要，且不止两个：十类后端，统一"窄接口 + 一致性测试" |
| 是否要 hooks | §9 | 要，但它只是中间件的退化形态（只观察不控制），不许改控制流 |
| 中间件 + 五内置 | §7 | 内核只有洋葱骨架，能力全部下沉；内置 12 个，五个来自你的清单 |

---

## 1. 目标、非目标、判据

### 1.1 目标

- `pip install` 之后，新建一个 agent 项目 = 写模型适配器 + 选后端 + 打开几个中间件 + 写业务工具，**20 行以内**。
- 同一套包能装出单 agent、Workflow、ReAct、P&E、Supervisor、Handoff、Blackboard、Pipeline，以及带沙箱 / 文件系统 / 子 agent / 任务板的编码型 agent。
- 换任何一个部件（模型、存储、沙箱、护栏、上下文策略）**不改内核**，且新增部件不需要改已有部件。
- 每个部件能离线单测：无模型、无网络、无真实文件系统。
- 框架敢承诺"实现这 24 个协议就通过这 24 组测试"——可替换性靠测试证明，不靠文档声明。

### 1.2 非目标

- 不做跨进程 A2A、消息队列产品、鉴权网关、UI 平台（分别属第 34 / 32 / 41 章）。
- 不替代 LangGraph / LangChain；不追图运行时、不追 DSL。
- 不做"零配置魔法"：配置项显式，装配期校验，宁可启动时报错也不运行期猜。
- 不把内核做成可替换。**内核不可替换，只能拦截**——这是与 LangGraph 的根本分歧，也是本框架的唯一护城河。

### 1.3 基线功能 → 层归属

卷 12 大纲的功能全部保留，只是归位。这张表是"不许丢功能"的检查清单。

| # | 基线功能 | 归属层 | v1 状态 | v2 变化 |
|---|---|---|---|---|
| 1 | 模型调用（Model 协议） | 后端 | ✅ | 加 `stream` / `tool_choice` / usage 归一化 |
| 2 | 工具定义与调用 | 契约 + 内核 | ✅ | 工具加元数据（§4.4） |
| 3 | 唯一循环 + 三种终止 | 内核 | ✅ | 抽成洋葱，行为不变 |
| 4 | ReAct | 部件（policy） | ✅ | 不动 |
| 5 | Workflow | 部件（policy） | ✅ | 不动 |
| 6 | Plan-and-Execute + Planner | 部件（policy） | ✅ | Planner 仍只属 P&E |
| 7 | Reflector / Verdict | 部件 | ✅ | 挪进 `validate` 中间件 |
| 8 | Router / Route / fallback | 部件 | ✅ | 不动 |
| 9 | 四种拓扑（Pipeline/Handoff/Supervisor/Blackboard） | 部件（topology） | ✅ | 子 agent 改为运行时可派发（§7.3） |
| 10 | State 信封 + 命名空间 | 契约 | ✅ | 加取景层（State → Frame） |
| 11 | Durability 检查点 | 存储 | ✅ 覆盖写 | 加 rev、时间旅行 |
| 12 | 人工审批 + resume | 内核 + 中间件 | ✅ | 泛化为任意检查点恢复 |
| 13 | Budget | 契约 + 中间件 | ✅ | 支持父子预算切分 |
| 14 | Tracer / 事件 | 后端 | ✅ | 加事件流与 span 传播 |
| 15 | Delivery 出口 | 内核 | ✅ | 拆 Result / Event 双出口 |
| 16 | RAG：Knowledge / Retrieval / Context | 部件 + 后端 | ✅ 最小 | Context 拆成 Framer + Encoder |
| 17 | Memory | 存储 + policy | ✅ 最小 | 拆分存取与写入策略 |
| 18 | Skills | 中间件 + 供给 | ✅ 但未接线 | 渐进披露 + `allowed_tools` 真正生效 |
| 19 | Guard | 内核插点 | ✅ | 位置写死，不可被中间件重排 |
| 20 | Resilience | 中间件 | ✅ | 挪进 `retry` 中间件 |
| 21 | 五个装配预设 | 装配 | ✅ | `build(cfg)` → `Harness(cfg)` |
| 22 | MCP（未做） | 适配器 | ⬜ | 期 4 |
| 23 | 多租户 | 契约（namespace） | ⬜ | 进 Store 强制过滤 |
| 24 | 幂等 | 存储 | ⬜ 有字段无用 | 幂等表 + `tool_call` 中间件 |

### 1.4 验收判据（每期都用这五条打分）

1. **可替换**：把某个部件换成内存假实现，其余代码零改动。
2. **可组合**：任意两个中间件换顺序不崩（除安全不变量，§5.4）。
3. **可回放**：同一 State + 同一模型回复序列，重跑结果一致。
4. **可判定**：任何失败都能映射到 `RunStatus` 的一个值，不允许"抛出去了事"。
5. **可离线**：全部测试无网络、无真实沙箱。

---

## 2. 第一性原理：骨架与变体

### 2.1 三件不变

先把"什么不能变"钉死，剩下的才好切。整个框架只有三件不变的事：

| 不变的东西 | 内容 | 为什么不能变 |
|---|---|---|
| **骨架** | 取下一步 → 校验 → 执行 → 记账 → 存档，直到终止 | 一变就成图运行时，失去"一个内核" |
| **边界** | 副作用只能经工具发生；工具只能经内核调用 | 边界一松，护栏与审批全部失效 |
| **出口** | 每次运行必须有 `RunStatus` + `RunResult`，不允许只返回 State | 没有出口就没有可判定性，上层无法写代码 |

### 2.2 三种挂载方式

其余一切都是变体。变体只能通过三种方式挂上去：

```text
① 替换（Substitution）：实现同一个协议      → 后端、存储、模型、策略
② 包裹（Wrapping）：在四层拦截点上套洋葱     → 中间件
③ 观察（Observation）：只读事件，不改控制流  → hooks
```

**组合 = ①②③ 的笛卡尔积。** 框架的全部工作，就是把这三种挂载方式做成稳定、可校验、可测试的。凡是无法用这三者表达的需求，说明协议缺了，而不是该给内核开洞。

### 2.3 三个视图 + 一张归位表

框架的可变性有三个正交方向，任何一个单一模式都只能描述其中一个。所以这里**不设"总模式"**：只设三个视图（描述手段）与一张归位表（审计工具），真正的模型是 §2.4 的两条不变量。

| 视图 | 要回答的问题 | 采用的结构 | 明确不采用 |
|---|---|---|---|
| **控制流视图** | 什么时候调用、谁能插手 | 四个插点，每点四段执行链 | 不用图 / DSL 描述流程 |
| **依赖视图** | 谁能依赖谁、什么可替换 | 六边形（Ports & Adapters），依赖只向内 | 不用分层图描述调用关系 |
| **数据视图** | 看见什么、看见多少 | 取景（Framer）→ 编码（Encoder） | 不做响应式、不做双向 |

三个视图之间只允许两条连接线，**禁止互相穿透**：

1. 插点上的拦截器通过**作用域**取到依赖视图的实现对象（不 import 具体类）。
2. 数据视图的产物只能经 `model_call` 的请求 / 响应进出（取景层不许调工具，后端不许读 State 内部结构）。

#### 把三个视图压成一张可检查的表：「插点 × 挂载」归位表

| 位置 ＼ 挂载 | **替换**（实现协议） | **包裹**（中间件） | **观察**（hook） |
|---|---|---|---|
| `run` | — | Tenancy / BudgetGuard / Audit / Trace | `on_run_start` `on_run_end` |
| `step` | `BodyPolicy`（react / workflow / pe） | TaskBoard / Reflector 重试 / Checkpoint | `on_step_end` |
| `model_call` | `Model` 后端、`Framer` + `Encoder` | ContextManager / 缓存 / InputGuard / OutputGuard | `on_model_call` |
| `tool_call` | `Tool`、`FileSystem`、`Sandbox`、`Index` | Approval / 沙箱路由 / 幂等 / SubAgent / Capability | `on_tool_call` |
| 出口 | `Delivery`（Result + Event 双出口） | OutputGuard（最终答案） | `on_run_end` |
| 构造期 | 24 个协议实现（store / backend / model / …） | 插件（entry points） | — |

**用法：任何功能、任何改动，先在表里指一个格子。**

- 指不到 → 协议缺了。补 §4.5 的清单，**不要给内核开洞**。
- 指到两个 → 职责重叠，会出现双重执行或顺序歧义。
- 指到"内核骨架"→ 不允许。内核只有骨架与插点，其余全在表里。

这张矩阵比分层图更有用：分层图只能描述依赖视图，而**框架的多数设计错误恰恰是"把变化放错格子"**。v1 有三个真实案例——

| 错误 | 放错的格子 | 后果 |
|---|---|---|
| 把内容护栏做成 `Guard` | "内容"塞进"动作"的格子 | deny 语义混淆：该改写的被停掉，该停的被放过 |
| 用静态拓扑代替运行时子 agent | "运行时"塞进"构造期"的格子 | 不能在循环中派发，`Supervisor` 只能预排 |
| 把压缩写进 `assemble` | "策略"塞进"编码"的格子 | 压缩不可测、不可回放、不可换 |

三个视图的命名在代码里要可见：`kernel/` 对应控制流，`contracts/` 对应依赖的端口，`parts/framing/` 对应数据（§3.4）。

### 2.4 模型：两条不变量 + 三个视图

**结构模型 = 两条不变量 + 三个视图。** 定义如下，不留解释空间：

| 组成 | 内容 | 作用 |
|---|---|---|
| **不变量 1 · 历史不可变** | 任何状态变更都必须留下带 `rev` 的记录；旧版本永不修改、永不删除 | 可回放、可时间旅行、并发写不覆盖 |
| **不变量 2 · 资源单一所有者** | 预算、取消信号、trace span 各有一个所有者，只沿作用域**单向继承** | 子 agent 不偷预算、父取消子必停、span 不挂错父 |
| 视图 1 · 控制流 | run → step → model_call / tool_call | 决定"在哪插手" |
| 视图 2 · 依赖 | 六边形，只向内 | 决定"什么可替换" |
| 视图 3 · 数据 | State → Frame → 载荷 | 决定"看见什么" |

#### 归位表是工具，不是模型

上一节的「插点 × 挂载」矩阵**不是模型**，是**变更归位表**。它只有两个用途：code review 时核对改动落在哪个格子；测试时断言"配置声明的中间件都落在已知格子上"。

它不能当模型，有五条硬伤——这也是为什么必须另立不变量：

| # | 硬伤 | 后果 |
|---|---|---|
| 1 | 只归档，不推导 | 给不出"这个新需求该放哪"，只用于事后核对 |
| 2 | 没有时间维度 | 六行全是调用点，没有一行描述历史；而持久化正是 agent 与普通服务的分界 |
| 3 | 没有所有权维度 | 预算 / 取消 / span 的归属不出现在任何格子，而框架的真实 bug 都在这里（§7.4、§12.2） |
| 4 | 术语成本 | 视图 / 归位表 / 格子三套词，要先学会描述方式才能定位问题 |
| 5 | 空格子诱发填充 | 24 格大半为空，空格子天然邀请"往这儿塞东西"，与"插点越少越好"冲突 |

**判据**：一个特性若既不改变任何不变量、也不落在归位表任何格子，它是应用代码，不进框架。

#### 历史不可变的实现：多版本快照（已定，不再讨论）

每次状态变更写一条新 `rev`；旧 `rev` 永不修改，可 `get(sid, rev)` 取回。`CheckpointStore` 的 `put` / `get` / `history` 三个方法就是它的全部接口。

**不采用事件日志 + fold。** 两条否决理由：① 重放必须做效果记忆化，否则重放会真的再调一次工具；② 事件 schema 演进比状态快照难。多版本快照两条都不需要，且时间旅行、并发保护、审计留痕的能力等价。

---

## 3. 分层与依赖规则

### 3.1 六层（依赖视图的落地：六边形 / Ports & Adapters）

这一节只负责**依赖视图**：把 §2.3 的"依赖视图"落成目录与依赖规则。端口（`contracts`）归内核所有，适配器（`impl` / `adapters`）在外围实现，依赖一律向内。

```text
L5 适配器    adapters/       openai · qdrant · otel · mcp · sqlite · local-sandbox
                             只 import L0-L4，且只被装配层按需 import（懒加载）
L4 装配      assembly/       Harness(cfg) · 校验 · 插件注册 · 生命周期
                             依赖 L0-L3，不可被任何下层 import
L3 部件      parts/          policy · framing · middleware · topology · guardrail
                             middleware 只能 import L0（+ L3 内的协议定义）
L2 具体实现  impl/           InMemoryStore · SqliteStore · LocalFS · SubprocessSandbox · FakeModel
                             实现 L1 的后端/存储协议，依赖 L0
L1 契约      contracts/      类型 · 协议 · 事件 · 错误 · 版本号
                             零依赖（标准库除外），不 import 任何兄弟模块
L0 内核      kernel/         循环 · 作用域 · 洋葱执行器 · 插点顺序
                             只 import L1
```

### 3.2 依赖规则（唯一铁律）

> **除 L0 之外，任何模块对同包其它模块的依赖，只允许指向 `contracts`。跨层调用必须经过接口对象，不经过具体类。**

配套的三条：

1. **禁止向上依赖**：`impl` 不许 import `assembly`；`parts` 不许 import `impl`（要靠注入拿到实现）。
2. **禁止兄弟依赖**：`middleware/a` 不许 import `middleware/b`；共享逻辑下沉到 `contracts` 或独立工具模块。
3. **`__init__.py` 只做导出，不做初始化**。任何模块级副作用（读文件、建连接、注册）都不允许。

### 3.3 用测试守住（不是用文档）

```python
# tests/test_architecture.py —— 架构约束的可执行版本
import ast, pathlib

ALLOWED = {
    "contracts": set(),                      # 零依赖
    "kernel":    {"contracts"},
    "impl":      {"contracts"},
    "parts":     {"contracts"},
    "assembly":  {"contracts", "kernel", "impl", "parts"},
    "adapters":  {"contracts", "kernel", "impl", "parts", "assembly"},
}

def test_import_direction():
    for mod, allowed in ALLOWED.items():
        for path in pathlib.Path(f"src/harness/{mod}").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.level >= 1:
                    target = (node.module or "").split(".")[0]
                    assert target in allowed | {""}, f"{path} 越界依赖 {target}"
```

这条测试比任何架构图都有效：**违反解耦当秒红**。

### 3.4 目标文件树

```text
src/harness/
├── contracts/             L1
│   ├── types.py           Goal/Step/Result/Verdict/Plan/...（dataclass，全部冻结）
│   ├── status.py          RunStatus / Phase / StopReason
│   ├── errors.py          错误分类
│   ├── events.py          RunEvent 与 12 种事件
│   ├── protocols/
│   │   ├── model.py       Model / ModelReply / ModelDelta
│   │   ├── tools.py       Tool / ToolSpec / ToolResult
│   │   ├── body.py        BodyPolicy / Planner
│   │   ├── guards.py      Guard / Guardrail / GuardrailStream
│   │   ├── stores.py      SessionStore/CheckpointStore/MessageLog/MemoryStore/Idempotency
│   │   ├── backends.py    FileSystem/Sandbox/Artifact/Secret/Index/EventSink/Queue/Approval/Clock
│   │   ├── framing.py      Framer / Encoder / Frame / Pack
│   │   ├── runtime.py     Middleware / Hook / Runnable / Topology
│   │   └── governance.py  Budget / Reflector / Router
│   └── version.py         contracts_version = "2"
├── kernel/                L0
│   ├── loop.py            唯一循环（不含策略）
│   ├── chain.py           洋葱执行器 + 拓扑排序
│   ├── scope.py           RunScope / StepScope / ChildScope
│   ├── pipes.py           参数校验与转换
│   └── filters.py         错误 → RunStatus 映射
├── parts/                 L3
│   ├── policy/            react · workflow · plan_execute · planner
│   ├── framing/           framers · encoders
│   ├── guardrail/         input · output · tool · stream
│   ├── middleware/        12 个内置（§7.3）
│   └── topology/          pipeline · handoff · supervisor · blackboard
├── impl/                  L2
│   ├── stores/            memory_*.py · sqlite_*.py
│   ├── backends/          local_fs.py · subprocess_sandbox.py · memory_artifact.py ...
│   └── fakes/             FakeModel · FakeClock · FakeSandbox（测试专用）
├── assembly/              L4
│   ├── config.py          HarnessConfig（声明式，带校验）
│   ├── app.py             Harness（生命周期 + run/astream/resume）
│   ├── presets.py         五个预设（配置简写，不是另一套实现）
│   └── plugins.py         entry_points 注册表
└── adapters/              L5
    ├── openai.py  qdrant.py  otel.py  mcp.py
```

---

## 4. 契约层

### 4.1 设计纪律

1. **窄而深**：一个协议最多 4 个方法。宽接口没人写第二个实现。
2. **全 async**：同步只留最外层封装（`run_sync`），内部不许出现两条调用路径。
3. **命名空间强制**：凡涉及数据归属的方法，第一个参数是 `Namespace(tenant, user, session, agent)`，不提供无 namespace 的重载。
4. **冻结类型**：进入契约的 dataclass 一律 `frozen=True`；可变性只允许在 `State.data` 里（且必须可 JSON 化）。
5. **每个协议配一个内存实现 + 一组一致性测试**。没有这两样，协议不算契约，只算愿望。

### 4.2 类型分层（26 个类型，按角色分组）

| 角色 | 类型 | 说明 |
|---|---|---|
| 标识 | `Namespace` `SessionRef` `RunId` `TraceId` | 全部是不可变值对象 |
| 输入 | `Goal` `Brief` `TaskSpec` | `Brief` 只用于子 agent（含禁止项与期限） |
| 过程 | `Step` `ToolCall` `ModelReply` `ModelDelta` `Plan` | `Step` 是唯一跨层流动的执行单元 |
| 判定 | `Verdict` `GuardDecision` `GuardrailVerdict` `Decision` | **四种判定不许合并**（§4.3） |
| 结果 | `ActionResult` `ToolResult` `ExecResult` `Pack` `RunResult` | |
| 帧 | `Frame` `Section` `Payload` `Recalled` | 取景产物与编码载荷（§6） |
| 治理 | `Budget` `Limits` `Mount` `ApprovalRequest` `RunEvent` | |
| 状态 | `State` | 唯一可变 + 唯一可序列化的容器 |

### 4.3 四种判定为什么不能合并

这是 v1 最容易做错的地方，v2 明确拆开：

| 判定 | 谁产生 | 回答什么问题 | 失败语义 | 能否改变执行 |
|---|---|---|---|---|
| `GuardDecision` | Guard | **这个动作**能不能做 | deny → REFUSED | 能（短路） |
| `GuardrailVerdict` | Guardrail | **这段内容**能不能进出 | deny → 拒绝/改写 | 能（改写内容） |
| `Verdict` | Reflector | 这个**结果**够不够好 | 差 → retry/replan | 能（回到循环） |
| `Decision` | 人 | 批不批 | reject → REFUSED | 能（挂起/恢复） |

合并的后果：护栏 deny 和 Guard deny 都返回 `REFUSED`，但前者应该"改写后继续"，后者应该"停下"。合并后无法区分，只能靠错误字符串猜。

### 4.4 工具元数据

工具不再只有 name/description/parameters。元数据是中间件做路由、审批分级、超时、幂等的依据。

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    side_effects: Literal["pure", "read", "write", "net", "shell"] = "pure"
    scopes: tuple[str, ...] = ()            # 需要哪些后端能力，如 ("fs:write", "sandbox:exec")
    timeout_s: float | None = None
    idempotent: bool = False
    max_output_bytes: int = 32_000          # 超出转 artifact，只回摘要
    needs_approval: bool = False            # 显式要求人工审批，不靠名字猜
    sandbox: bool = False                   # 是否必须进沙箱执行
```

`side_effects` 直接驱动三件事：① 审批分级（`write`/`shell` 默认 ask）② 幂等要求（非幂等的 `write` 必须带 `idem_key`）③ 沙箱路由（`shell` 必须进沙箱）。

### 4.5 协议清单（24 个）

| 组 | 协议 | 方法数 | 可空实现 |
|---|---|---|---|
| 模型 | `Model` | 2（`complete` / `stream`） | `FakeModel` |
| 工具 | `Tool` | 1（`invoke`） | `noop` |
| 主体 | `BodyPolicy` `Planner` `Topology` | 1 / 1 / 1 | `react` / — / `pipeline` |
| 校验 | `Reflector` `Validator` | 1 / 1 | `NullReflector` |
| 准入 | `Guard` | 1 | `AllowAllGuard` |
| 护栏 | `Guardrail` `GuardrailStream` | 1 / 2 | `NullGuardrail` |
| 取景 | `Framer` `Encoder` | 1 / 1 | `BudgetedFramer` |
| 存储 | `SessionStore` `CheckpointStore` `MessageLog` `MemoryStore` `Idempotency` | 4 / 3 / 2 / 4 / 2 | `InMemory*` |
| 后端 | `FileSystem` `Sandbox` `ArtifactStore` `SecretBroker` `IndexBackend` `EventSink` `Queue` `ApprovalChannel` `Clock` | 6/2/3/2/2/1/3/3/1 | `Local*` / `Memory*` |
| 运行时 | `Middleware` `Hook` `Runnable` | 1 / 1 / 1 | — |

---

## 5. 内核：一次 step 的执行链

### 5.1 为什么内核必须最小

内核只有 4 个职责（v1 的 `_loop_inner` 已经接近了）：**取步、过边界、执行、记账存档**。所有"智能"都在外面：

```text
Agent._loop()
 ├─ while 未终止:
 │    Step  ← BodyPolicy.next_step(state, scope)      // 决策在部件
 │    if Done → 出口
 │    ── 执行链（§5.2）──
 │    ActionResult ← 执行链(Step)
 │    state.step_index += 1; 记账; 存档
 └─ 出口：delivery.finish(state, status)
```

### 5.2 四段执行链（定死，不可改）

一次 `step` 内部固定为四段，**顺序不可调、不可合并、不可省略**。段是位置，协议是实现该段的部件，二者一一对应：

```text
                ┌──────────────────── Classify ─────────────────────┐
Step ──▶ Gate ──▶ Check ──▶ ┌── Wrap(before) ──┐                     │
        (准入)  (校验)       │    Terminal      │  ← 工具 / 沙箱       │
                             │  （唯一副作用）   │                     │
                             └── Wrap(after) ───┘                     │
                                              Result ────────────────┘
```

| 段 | 协议 | 输入 → 输出 | 失败方式 | 允许做什么 | 禁止做什么 |
|---|---|---|---|---|---|
| **Gate** | `Guard` | `Step` → `GuardDecision` | 返回 `deny` / `ask`，**不抛异常** | 短路：拒绝或转人工 | 改参数、改结果、做 IO |
| **Check** | `Pipe` | `Step` → `Step` | 抛 `ValidationError` | 参数校验、补全、类型转换 | 短路、做 IO |
| **Wrap** | `Middleware`（tool_call 点） | `ToolRequest` → `ToolResult` | 异常原样穿透给 Classify | 改请求、改结果、重试、记账、超时、幂等 | 跳过 Gate、伪造 `ToolResult` |
| **Classify** | `Filter` | `Exception` → `RunStatus` | 不吞异常，只归类 | 决定出口状态 | 重试、降级、改数据 |

四段必须分开，因为它们的失败语义不同。合并成一条洋葱会立刻产生三个没有答案的问题：Gate 拒绝后还要不要走 `Wrap(after)`？Check 抛错算不算运行失败？Classify 在洋葱里是第几层？

**洋葱只存在于 `Wrap` 段**，且只有一种实现形式：

```python
# kernel/chain.py
async def run_chain(mws: Sequence[Middleware], req: Request, terminal: Handler) -> Response:
    async def go(i: int, r: Request) -> Response:
        if i == len(mws):
            return await terminal(r)
        return await mws[i](r, lambda r2: go(i + 1, r2))
    return await go(0, req)
```

`Wrap` 就是函数嵌套：`run_chain` 等价于 `m1 >> m2 >> … >> terminal`（附录 D 的 `>>` 是同一件事的语法糖）。所以"洋葱"与"组合"不是两个方案，是同一个实现的两种写法。

#### 排除项（本框架不提供）

| 不提供 | 理由 |
|---|---|
| 装饰器 / 元数据 / 反射 | 等于 `inspect` 管道，破坏类型推断，与组合式 API 冲突 |
| 依赖注入容器 | 把"依赖从哪来"变成运行期问题；本框架用作用域（§12），构造期可查可测 |
| 请求作用域 + 单次响应模型 | agent 是长事务：流式产出、审批处挂起、重试重放，都不符合"一次请求一次响应" |
| 用洋葱作为整条执行模型 | 已由本节的四段表否决 |

### 5.3 四个插点

| 插点 | 请求 / 响应 | 典型中间件 |
|---|---|---|
| `run` | `RunRequest{goal, namespace}` / `RunResult` | 租户、审计、限流、总预算、记忆写回 |
| `step` | `StepRequest{state, step\|done}` / `StepResult` | 任务板、反思重试、审批挂起 |
| `model_call` | `ModelRequest{messages, tools, budget}` / `ModelReply` | 上下文压缩、缓存、脱敏、输入护栏、输出护栏 |
| `tool_call` | `ToolRequest{step, spec}` / `ToolResult` | 沙箱路由、路径 jail、幂等、截断、子 agent、skill |

四个插点是**嵌套**关系（run ⊃ step ⊃ {model_call, tool_call}），所以四个点各有一条链，不是一条链走到底。

### 5.4 四条安全不变量（写进代码，不写进文档）

1. **`tool_call` 链的终端永远是 Gate → Terminal**。中间件可以改参数、可以在之后审计，但**不能把 Gate 挪走、不能跳过**。
2. **没有工具调用就没有副作用**。禁止中间件直接做 IO 然后伪造 `ToolResult`——需要 IO 就注册工具。
3. **出口唯一**。所有终止路径都经 `Classify → delivery.finish`，禁止在内核里定向 `return`（v1 的 `WorkflowPolicy` 特判，见 [agent.py:238](../../code/harness/src/harness/agent.py)，就是反例，P1 删除）。
4. **State 只存可序列化数据**。中间件私有状态放实例，不放 `State`。

---

## 6. 数据视图：取景与编码

### 6.1 两段式：取景（Frame）→ 编码（Encode）

数据视图只回答一件事：**这一次调用，参与方看见什么。** 它拆成两段，一段只做选择，一段只做格式：

| 段 | 协议 | 输入 | 输出 | 只负责 |
|---|---|---|---|---|
| 取景 | `Framer` | `State` + `FrameKind` + `Budget` | `Frame` | 选哪些、怎么排、超预算丢谁 |
| 编码 | `Encoder` | `Frame` | `Payload`（messages / 卡片 / 事件） | 变成哪种格式 |

同一份 State 出四种帧，互不影响：

```text
State
 ├─ Framer(model)     → 预算内、按相关性排序、丢弃项有记录  → Encoder(openai) → Pack
 ├─ Framer(human)     → 全量 + 折叠 + 时间线               → Encoder(ui)     → Card
 ├─ Framer(approval)  → 只留待批那一步 + 影响面             → Encoder(card)   → Card
 └─ Framer(trace)     → 步骤 + 用量 + 耗时                 → Encoder(jsonl)  → RunEvent[]
```

**为什么必须分两段**：v1 的 [BudgetedContext.assemble](../../code/harness/src/harness/context.py) 一个方法同时做了五件事——选哪些、怎么排、放哪个槽、超预算丢谁、渲染成什么格式。后果是换模型家族要改选择逻辑，换选择策略要改格式。分开后，换模型只换 `Encoder`，换裁剪策略只换 `Framer`。

**观众决定取舍**：人看 UI 可以滚动、可以追问、可以忍冗余；模型看上下文不行——超了就是超了，漏了它也不知道。所以"选哪些、超预算丢谁、丢了怎么告知"必须是一等公民。

**三条纪律**：

1. `Framer` 不拼字符串、不决定 JSON 结构；`Encoder` 不决定留哪条。
2. 裁剪必须**可解释**：`Frame.dropped` 非空时，`model` 帧必须编码出一句"已省略 N 条较早历史"。
3. 一个 `Frame` 可被多个 `Encoder` 消费；一个 `Encoder` 只认一种格式。

**明确不采用响应式**（Proxy / 依赖收集 / 双向绑定），三条理由：

- `State` 必须能 `to_dict()` 落库、重放；Proxy 会把不可序列化的陷阱对象带进 State。
- 模型看见的内容必须**确定性**：同一 State 重放必须得到同一 `Frame`。响应式让"看见什么"依赖求值时机。
- agent 没有"用户改表单"这个事件源，双向绑定没有用处。

数据视图的方向固定为**单向、只读、可重放**：`State → Frame → Payload`，没有回写路径。

### 6.2 三个类型

```python
class Framer(Protocol):
    kind: FrameKind
    async def frame(self, state: State, *, budget: Budget) -> Frame: ...

class Encoder(Protocol):
    fmt: str
    async def encode(self, frame: Frame) -> Payload: ...

@dataclass(frozen=True)
class Frame:
    kind: FrameKind                     # model | human | approval | trace
    sections: tuple[Section, ...]       # 有序、带优先级、带来源引用
    dropped: tuple[str, ...]            # 被裁掉的，必须可解释
    tokens_est: int
```

### 6.3 与上下文压缩的分工

压缩是**取景策略**，不是独立机制：`summary_framer` 用摘要替换早期 `sections`，产出的仍是 `Frame`。好处是压缩结果可见、可测、可回放（v1 的压缩散在 `assemble` 的循环里，无法单测）。

---

## 7. 中间件

### 7.1 协议与声明式依赖

```python
class Middleware(Protocol):
    name: str
    points: frozenset[Point]        # {RUN, STEP, MODEL_CALL, TOOL_CALL}
    needs: frozenset[str]           # 依赖哪些后端（如 {"fs", "sandbox"}）
    after: frozenset[str]           # 必须排在这些中间件之后
    before: frozenset[str]          # 必须排在这些之前


    async def __call__(self, req: Request, nxt: Handler) -> Response: ...
```

`needs` 里声明的后端在构造期解析：缺任何一个 → `ConfigError`，不降级、不静默跳过。\n\n顺序由**拓扑排序**得出，不由人手排。三个好处：① 换顺序不会崩；② 缺依赖在启动期就报错，不拖到运行期；③ 第三方中间件可以声明"我必须在内置 X 之后"，不用改内置代码。

排序冲突（环）→ `ConfigError`。`after`/`before` 只约束同一点内的链。

### 7.2 顺序铁律

1. **改输入的在外，改输出的在内**（否则你截断完又被压缩）。
2. **便宜的在外的**（租户判定、预算检查不必承担后续开销）。
3. **安全在最内**：Guardrail（内容）在 `Wrap` 内侧、紧贴终端；Gate（动作）永远在终端前最后一环。

### 7.3 内置 12 个

| # | 中间件 | 点 | 依赖 | 职责 | 关闭后 |
|---|---|---|---|---|---|
| 1 | `Tenancy` | run | — | 绑定 namespace、拒绝越权 session | 单租户模式 |
| 2 | `BudgetGuard` | run, model_call | — | 父子预算切分、超限降级 | 无上限（危险） |
| 3 | `Audit` | 全部 | event | 结构化审计（谁、做了什么、结果） | 只剩 trace |
| 4 | `Trace` | 全部 | clock | span 父子关系、跨子 agent 传播 | 无 trace |
| 5 | `Checkpoint` | step | checkpoints | 每步落盘、rev 递增、幂等键写入 | 不支持恢复 |
| 6 | `Approval` | tool_call | approval | `ask` 挂起、`resume` 继续（v1 内核逻辑迁入） | 需审批的动作直接拒 |
| 7 | `InputGuard` | model_call（前） | guardrails | 用户输入、检索资料、记忆的检测与改写 | 不设防（危险） |
| 8 | `OutputGuard` | model_call（后）, run（出口） | guardrails | 模型回复与最终答案的检测、脱敏、拦截 | 不设防（危险） |
| 9 | `ContextManager` | model_call | — | 调 `Framer` 取景 + `Encoder` 编码；预算紧张时换摘要取景器 | 上下文无裁剪 |
| 10 | `TaskBoard` | step, model_call | — | 任务清单注入 + `task_*` 工具；把意图提出 messages 抗压缩 | 无任务管理 |
| 11 | `SubAgent` | tool_call | sandbox, budget | `task` 工具 → 子 agent（独立沙箱、共享预算、深度/并发上限、返回摘要） | 只能静态拓扑 |
| 12 | `Capability` | tool_call | fs, sandbox, secrets | 挂载文件系统工具、沙箱路由与资源限制、skill 渐进披露与 `allowed_tools` 执行、结果截断转 artifact | 只有纯计算工具 |

`Capability` 是一个**复合中间件**（可拆成 `FileSystem` / `Sandbox` / `Skill` / `Truncate` 四个更小的），默认打包成一组，因为它们的组合逻辑（沙箱路由需要 FS 挂载信息）耦合度高。拆开时各自遵守同样的协议。

### 7.4 子 agent：五个必须做全的点

`SubAgent` 是最容易做成玩具的中间件。缺一条就不可用：

1. **独立作用域**：自己的 State、自己的沙箱、自己的 trace span（parent 指向父）。
2. **共享预算**：`child_budget = parent.split(0.3)`；子消耗计入父，否则递归把成本炸掉。
3. **上限**：深度（默认 2）、并发（默认 4）、单子树步数。
4. **返回摘要，不返回全文**：子 agent 的 messages 绝不回灌父上下文，只回 `answer` + 引用 + 用量。
5. **取消传播**：父被取消/超时，子必须一起停（`asyncio.TaskGroup` + `CancelScope`），不能留孤儿任务烧钱。

### 7.5 Skill 渐进披露（三段式）

| 段 | 时机 | 注入量 | 手段 |
|---|---|---|---|
| ① 目录 | 每次 `model_call` | 每 skill 一行（name + description） | `Framer` 的 `skills` section |
| ② 正文 | 模型调 `load_skill(name)` 之后 | 一个 SKILL.md 正文 | `Capability` 中间件改写该轮 messages |
| ③ 资源 | 模型调 `read_skill_resource` 之后 | 单个 reference 文件 | 同上，按需 |

外加：`allowed_tools` 在 `tool_call` 链里**真正执行**（v1 只解析不使用，见 [skills.py:93](../../code/harness/src/harness/skills.py)）。这是现成的洞。

---

## 8. 护栏：输入护栏与输出护栏

### 8.1 Guard 与 Guardrail 的分工

这两类东西在提案里常被混为一谈，混了就没法组合：

| | Guard | Guardrail |
|---|---|---|
| 管什么 | **动作**（这一步做不做） | **内容**（这段文字进不进/出不出） |
| 作用对象 | `Step`（工具名 + 参数） | 文本 / 消息 / 回复 |
| 典型策略 | 白名单、审批、预算、频率 | 注入检测、PII、越权承诺、毒性、密钥泄漏 |
| 失败动作 | `deny`（停）/ `ask`（问） | `redact`（脱敏）/ `rewrite`（改写）/ `block`（拦） |
| 位置 | `tool_call` 终端前 | 五道闸（§8.2） |

### 8.2 五道闸

```text
用户输入 ──▶ ① 入站 ──▶ 取景 ──▶ ② 入上下文 ──▶ 模型 ──▶ ③ 出模型
                                                              │
                       工具结果 ◀── ④ 工具边界 ◀── 工具调用 ◀──┘
                           │
                       ⑤ 出口（最终答案）
```

| 闸 | 检查内容 | 为什么必须有 |
|---|---|---|
| ① 入站 | 用户原始输入 | 最便宜的一道；能在早期拒掉的不要带进循环 |
| ② 入上下文 | 检索资料、记忆、skill 正文 | **间接注入的主战场**——知识库和记忆是攻击面，不是可信数据 |
| ③ 出模型 | 模型回复（含工具调用参数） | 模型要写 `rm -rf` 时，参数就是输出 |
| ④ 工具边界 | 工具返回值 | 工具可能回灌注入载荷（网页、文件、API 响应） |
| ⑤ 出口 | 最终答案、卡片、事件 | 最后一道；也是审计留痕的地方 |

② 和 ④ 是 v1 完全没有的，却恰恰是真实事故的高发点：**别只防用户输入**。

### 8.3 三段式：检测 → 判定 → 动作

```python
class Guardrail(Protocol):
    name: str
    async def check(self, content: Content, ctx: Scope) -> GuardrailVerdict: ...

@dataclass(frozen=True)
class GuardrailVerdict:
    risk: float                        # 0..1
    labels: tuple[str, ...]            # ["prompt_injection", "pii.email"]
    action: Literal["allow", "warn", "redact", "rewrite", "ask", "block"]
    spans: tuple[Span, ...]            # 要脱敏/改写的具体区间
    replacement: str | None = None
```

**检测器与动作必须分离**：检测器只回答"哪一段、什么风险"，动作由策略层决定（同一个 PII 检测器，在开发环境 warn、生产环境 redact）。合并成"检测器自己决定怎么办"之后，就无法按环境/租户调策略，也无法对多个检测器结果做仲裁。

多个护栏的仲裁规则（显式定义，不许隐式）：**取最严动作**；同级取最高 risk；`rewrite` 与 `redact` 冲突时以 `block` 优先，其次 `redact`（改写可能引入新风险）。仲裁结果写进 `RunEvent.guardrail`，可审计。

### 8.4 流式输出护栏

流式下不能"等全文再检查"，否则流式退化成非流式。做法：

```python
class GuardrailStream(Protocol):
    async def feed(self, delta: str) -> GuardrailVerdict: ...   # 增量判定
    async def flush(self) -> GuardrailVerdict: ...              # 收尾判定
```

三条规则：
1. **窗口缓冲**：保留最近 N 字符（默认 64）不立即下发，等下一段到达再放行——否则跨块的敏感串会漏。
2. **已下发不可撤回**：一旦 token 发给用户，后续检测到问题只能"中断 + 说明"，不能假装没发过。这个语义要写进 `RunResult`（`status=DEGRADED, reason=guardrail_blocked_midstream`）。
3. **块级降级**：检测器不支持增量时，退化为"每 K 字符整块检测"，并标记 `degraded_stream_guard`。

### 8.5 护栏自身的失败模式

护栏是安全件，它崩溃时的默认语义必须显式：

| 情形 | 默认 | 可配置 |
|---|---|---|
| 检测器超时 | `block`（fail-closed） | → `warn` 仅当 `fail_open=True` 且只在非生产 namespace |
| 检测器异常 | `block` + 记 `RunEvent.guardrail_error` | 同上 |
| 检测器未注册但被引用 | 启动期 `ConfigError` | 不允许运行期跳过 |

**fail-open 只允许是显式配置，且必须在 `RunResult.metadata` 里留痕**，否则审计追不出来。

---

## 9. Hooks

### 9.1 与中间件的分工

| | Middleware | Hook |
|---|---|---|
| 能力 | 改输入、改输出、短路、重试 | 只读观察 |
| 返回值 | 有（可替换 Response） | 无（`None`） |
| 异常处理 | 穿透到 Filter | **吞掉并记事件**，绝不影响运行 |
| 顺序 | 拓扑排序 | 注册顺序 |
| 用途 | 任务板、子 agent、护栏、沙箱 | 指标、日志、告警、外部审计、调试打印 |

**判据一句话：需要改结果或改控制流的，都是中间件，不是 hook。** 所以二者不做两套扩展点——hook 就是"不调 `nxt`、只读 req、返回 None"的中间件，由 `as_hook()` 适配器转换。这样扩展点只有一个，语义不会分叉。

### 9.2 六个 hook 点

| 点 | 载荷 | 典型用途 |
|---|---|---|
| `on_run_start` / `on_run_end` | `RunResult` | 指标、计费 |
| `on_step_end` | `Step` + `ActionResult` | 进度上报 |
| `on_model_call` | `ModelReply` + usage | 成本采样、prompt 调试 |
| `on_tool_call` | `ToolSpec` + `ToolResult` | 审计、慢调用告警 |
| `on_checkpoint` | rev | 外部备份 |
| `on_error` | `Exception` + phase | 告警 |

---

## 10. Store（五个 + 工件）

### 10.1 为什么要拆五个

v1 的 `Durability.save(state)` 每步覆盖一行（[durability.py:49](../../code/harness/src/harness/durability.py)），带来三个问题：历史只能在 `state.messages` 里越滚越大、无法时间旅行、并发写无保护。按访问模式拆开就各自可控：

| Store | 粒度 | 访问模式 | 关键约束 |
|---|---|---|---|
| `SessionStore` | 会话元数据 | 小、可列表/搜/分页 | 标题、状态、归属、最后活跃时间 |
| `CheckpointStore` | 每步 State 快照 | 按 rev 追加读 | **乐观并发** `expect_rev`；支持 `history()` 时间旅行 |
| `MessageLog` | 消息 | append-only | 按 token 预算取尾部；不可改历史（改 = 新记录） |
| `MemoryStore` | 记忆条目 | 语义检索 | namespace + layer + 去重键 + TTL |
| `Idempotency` | 幂等键 | 点查 | `begin(key)` 命中即返回旧结果 |
| `ArtifactStore` | 大对象 | 流式写读 | 只存引用；内容不进 State |

### 10.2 五个协议

```python
class CheckpointStore(Protocol):
    async def put(self, ns: Namespace, sid: str, state: State, *, expect_rev: int | None) -> int: ...
    async def get(self, ns: Namespace, sid: str, rev: int | None = None) -> Checkpoint | None: ...
    async def history(self, ns: Namespace, sid: str, limit: int = 20) -> list[int]: ...

class MessageLog(Protocol):
    async def append(self, ns: Namespace, sid: str, msgs: Sequence[Message]) -> None: ...
    async def tail(self, ns: Namespace, sid: str, *, max_tokens: int) -> list[Message]: ...

class MemoryStore(Protocol):
    async def recall(self, ns: Namespace, q: str, *, layers: Sequence[Layer], k: int) -> list[Recalled]: ...
    async def upsert(self, ns: Namespace, items: Sequence[Recalled]) -> int: ...   # 带 dedup_key
    async def forget(self, ns: Namespace, ids: Sequence[str]) -> int: ...
    async def expire(self, ns: Namespace, now: datetime) -> int: ...

class Idempotency(Protocol):
    async def begin(self, ns: Namespace, key: str) -> Recorded | None: ...
    async def commit(self, ns: Namespace, key: str, value: Recorded) -> None: ...
```

### 10.3 记忆：存取与策略分开

`MemoryStore` 只做存取。真正难的是**写入策略**，独立成 `MemoryPolicy`：

```python
class MemoryPolicy(Protocol):
    async def should_write(self, state: State, result: RunResult) -> bool: ...
    async def extract(self, state: State) -> list[Recalled]: ...      # 抽取候选
    async def merge(self, old: list[Recalled], new: list[Recalled]) -> list[Recalled]: ...  # 冲突消解
    async def decay(self, items: list[Recalled]) -> list[Recalled]: ...                     # 衰减/过期
```

四条判断写进默认策略：① 只写"结论与偏好"，不写对话流水；② 冲突时**新覆盖旧但留旧为超链接**（可追溯）；③ 带来源（哪次 run、哪条消息），无来源不写；④ 脱敏在写入前，不在读取后。

### 10.4 三条硬约束

1. **全 async、全带 namespace、全幂等**。这是给 adapter 作者的验收标准，写进一致性测试。
2. **namespace 在 Store 层强制过滤**，不给无 namespace 的重载——多租户漏一个 `where` 就是事故。
3. **State 只存引用，不存内容**（大输出 → `ArtifactStore`，State 里放 `artifact://...`）。

---

## 11. 后端（十个）

### 11.1 清单

| 后端 | 关键方法 | 内存/本地实现 | 失败模式要点 |
|---|---|---|---|
| `Model` | `complete` / `stream` | `FakeModel` | 超时、限流、上下文溢出要可分类 |
| `FileSystem` | `read/write/edit/glob/grep/stat` | `LocalFS` | **虚拟路径 + 挂载表**；越界即拒 |
| `Sandbox` | `exec` / `kill` | `SubprocessSandbox` | 资源限制、超时、输出截断、孤儿进程回收 |
| `ArtifactStore` | `put` / `get` / `stat` | `MemoryArtifact` | 大对象不进 State |
| `SecretBroker` | `get` / `list` | `EnvSecrets` | 只按名字取、只给声明了 scope 的工具、永不明文进 prompt |
| `IndexBackend` | `search` / `upsert` | `InMemoryIndex` | 过滤必须下推到后端（租户隔离） |
| `EventSink` | `emit` | `MemorySink` / `JsonlSink` | 慢消费者不能阻塞运行（背压策略见 §13） |
| `Queue` | `enqueue` / `dequeue` / `ack` | `MemoryQueue` | 至少一次投递 + 幂等键 |
| `ApprovalChannel` | `request` / `wait` / `respond` | `CallbackApproval` | 超时、过期、并发审批 |
| `Clock` | `now` / `monotonic` | `FakeClock` | 测试与回放必须可控 |

### 11.2 沙箱与文件系统：两个易错点

1. **虚拟路径 + 挂载表，而不是直传 `os.path`**：

```python
@dataclass(frozen=True)
class Mount:
    target: str          # 虚拟路径，如 "/work"
    source: str | None   # 宿主路径；None = 纯内存
    mode: Literal["ro", "rw"]
```

`FileSystem.resolve(path) -> RealPath | Denied` 是**唯一**做 jail 的地方。所有 FS 实现共用这一层，路径穿越（`../`、符号链接、Windows 短名、UNC）在一处收口，不在每个实现里各写一遍。

2. **沙箱是执行边界，不是决策边界**：Guard 放行了，沙箱仍必须挡住越界。两者不合并，因为它们的失败语义不同（拒绝 vs 崩溃）。

### 11.3 三条设计纪律

- **窄而深**：`Sandbox.exec` 一个方法（+ kill），不要 exec/read/write/install 各开一个。
- **每个后端配一个内存实现 + 一组一致性测试**（§16）。
- **后端经作用域注入，不做全局单例**：子 agent 必须能拿到自己的沙箱实例（安全要求，不是偏好）。

---

## 12. 生命周期、作用域与结构化并发

### 12.1 三个作用域

```text
Harness（app，跨 run 存活：连接池、插件、配置）
  └─ RunScope（一次 run：namespace、预算、trace、事件通道）
       └─ StepScope（一次 step：当前 span、当前中间件链状态）
            └─ ChildScope（子 agent：继承预算与 trace，新 State、新沙箱）
```

**作用域只持有不可变服务引用；可变数据只有 `State`。** 这样"谁能看见什么"在类型上是明确的，不需要读代码猜。

### 12.2 生命周期

```python
async with Harness(config) as app:          # startup：建连接、校验配置、装插件
    result = await app.run(goal)
    async for ev in app.astream(goal): ...  # 流式
    await app.resume(session_id, decision)  # 恢复
# shutdown：回收沙箱、flush 事件、关连接
```

三条要求：
1. **启动期校验一切**：协议实现了没有、依赖中间件的后端在不在、中间件图有没有环、配置组合合法不合法（`mode=react` 传 `planner` 直接 `ConfigError`，保留 v1 这条）。
2. **取消必须收敛**：`run` 被取消 → 子任务全部取消 → 沙箱进程 kill → 检查点已写 → 抛 `CancelledError`（不吞）。
3. **异常必须归类**：`Filter` 是唯一把异常映射成 `RunStatus` 的地方（§14）。

### 12.3 并发模型（需要显式决策的地方）

| 场景 | 默认 | 为什么 |
|---|---|---|
| 同一 session 两个并发 `run` | **串行**（lease + `expect_rev` 冲突则拒绝） | 否则检查点互相覆盖，状态错乱 |
| 不同 session | 并行 | 无共享可变状态 |
| 一个 run 内多个工具 | **串行**（固定） | 部分失败没有唯一语义（重试哪几个、结果怎么合），串行才有确定性 |
| 子 agent | 受并发上限约束的并行 | 有独立 State，安全 |

---

## 13. 事件与流式

### 13.1 事件是唯一的对外观察面

v1 只有 `tracer.emit` 写文件，`delivery` 只回最终结果。v2 把**事件**提升为一等对外契约：UI 逐字显示、SSE、审批卡片、计费都消费它。

| 事件 | 载荷 | 消费者 |
|---|---|---|
| `run.start` / `run.end` | goal / status + usage | 指标 |
| `step.start` / `step.end` | step / result | 进度 |
| `model.start` / `model.delta` / `model.end` | 增量文本 / usage | 逐字显示、成本 |
| `tool.start` / `tool.end` | spec / result | 审计、慢调用 |
| `guardrail` | verdict + 仲裁结果 | 安全审计 |
| `approval.required` / `approval.resolved` | 卡片 / 决策 | HITL UI |
| `checkpoint` | rev | 外部备份 |
| `error` | 分类 + phase | 告警 |

### 13.2 双形态

```python
async def run(self, goal) -> RunResult               # 同步语义，事件仍发（给 sink）
def astream(self, goal) -> AsyncIterator[RunEvent]   # 流式语义，返回事件
```

两者共用同一条内核，`astream` 不是另一套实现（避免 v1 想加流式时必须复制循环）。

### 13.3 背压

慢消费者不能拖死运行：`EventSink` 有 `bounded queue` + 溢出策略（`drop_oldest` / `block` / `error`），默认 `drop_oldest` 并计数，写进 `RunResult.metadata.event_dropped`。**默认不阻塞**——可观测性不能成为可用性的瓶颈。

---

## 14. 错误、降级、出口

### 14.1 错误分类（决定重试与出口，不决定日志文案）

| 类别 | 例子 | 重试 | 出口状态 |
|---|---|---|---|
| `ConfigError` | 组合非法、依赖缺失 | 否 | 启动期抛出，不进循环 |
| `ContractError` | 部件返回类型错 | 否 | `FAILED` |
| `TransientError` | 超时、限流、5xx | **是**（有界退避） | 重试耗尽 → `DEGRADED` |
| `PolicyError` | Guard/Guardrail 拒绝 | 否 | `REFUSED` |
| `BudgetError` | 预算耗尽 | 否 | `DEGRADED` |
| `ApprovalError` | 过期、驳回 | 否 | `REFUSED` |
| `ToolError` | 工具失败（回灌模型） | 看 `idempotent` | 循环内自愈，步数耗尽 → `DEGRADED` |

### 14.2 出口唯一

`Filter → delivery.finish` 是唯一出口。`RunStatus` 七个值各有确定语义（`RUNNING` 不允许出现在 `RunResult` 里——出现即 `ContractError`）。

v1 反例（v2 删除）：[agent.py:238](../../code/harness/src/harness/agent.py) 用 `self.policy.__class__.__name__ == "WorkflowPolicy"` 判断要不要中止。这是典型的"按类型猜语义"，换成 `policy.stop_on_tool_error` 属性声明。

---

## 15. 装配与插件

### 15.1 配置即契约

```python
@dataclass(frozen=True)
class HarnessConfig:
    model: ModelSpec
    body: BodySpec = BodySpec(kind="react", max_steps=24)
    tools: tuple[ToolSpec, ...] = ()
    middlewares: tuple[MiddlewareSpec, ...] = ()      # 名字 + 参数，不是实例
    backends: BackendSpec = BackendSpec()
    stores: StoreSpec = StoreSpec()
    guard: GuardSpec = GuardSpec(kind="allow_all")
    guardrails: tuple[GuardrailSpec, ...] = ()
    framing: FramingSpec = FramingSpec()
    hooks: tuple[HookSpec, ...] = ()
    namespace: NamespaceSpec = NamespaceSpec()
```

**配置只描述"要什么"，不构造实例**；`Harness` 负责解析、校验、构造、注入。好处：配置可序列化（能存库、能审阅、能 diff）、依赖图能在构造前算出来（缺依赖/有环在启动期报错）。

### 15.2 插件

```toml
[project.entry-points."harness.middlewares"]
taskboard = "my_pkg.mw:TaskBoard"
[project.entry-points."harness.backends"]
"fs.s3" = "my_pkg.s3:S3FS"
```

三条规则：① 插件只通过协议扩展，**不得 import 内核内部**；② 名字冲突 → `ConfigError`（不覆盖，静默覆盖是灾难）；③ 插件加载失败不影响核心启动，只让引用它的配置项报错。

### 15.3 预设只是配置简写

`minimal / react / workflow / pe / production` 五个预设 = 五组 `HarnessConfig` 默认值，不是五套实现。v1 这条做得对，保留。

---

## 16. 可测试性

### 16.1 三层测试

| 层 | 内容 | 数量级 | 依赖 |
|---|---|---|---|
| 契约一致性 | 每个协议一组通用用例，所有实现（内存 + 真实）共用 | 24 组 | 无 |
| 部件单测 | 中间件、取景、护栏、存储各自 | 数百 | 假实现 |
| 端到端 | 预设装配出的完整 agent 跑业务剧本 | 十余 | FakeModel |

### 16.2 一致性测试是"可替换"的证明

```python
class CheckpointStoreConformance:
    """子类只提供 factory()。"""
    async def test_put_get_roundtrip(self): ...
    async def test_optimistic_conflict_raises(self): ...
    async def test_history_returns_increasing_rev(self): ...
    async def test_namespace_isolation(self): ...
    async def test_idempotent_write(self): ...
```

**新写一个 Postgres 实现，跑通这组用例就能换上去**——这是框架对使用者的承诺，也是它唯一可信的卖点。

### 16.3 假件全家桶

`FakeModel`（脚本化回复）· `FakeClock`（可控时间）· `FakeSandbox`（记录命令、返回剧本）· `FakeFS`（内存挂载）· `FakeEventSink`（捕获事件）。全部在 `impl/fakes/`，**不进生产包**。

---

## 17. 版本与兼容

1. `contracts_version` 是唯一兼容边界，v2 起主版本 = 破坏性变更（协议方法签名、必填字段）。
2. **协议只加不删**：新方法必须给默认实现（`Protocol` 里用 mixin 提供），否则就是 v3。
3. 弃用流程：标记 → 一个主版本内双轨 → 删除，且必须在 `CHANGELOG` 写迁移片段。
4. 数据兼容：`State` 的 `to_dict` 带 `schema_version`，读取时走迁移函数；不允许"读旧数据直接崩"。

---

## 18. 迁移路线（四期）

| 期 | 内容 | 验收 | 可回滚点 |
|---|---|---|---|
| **P1 骨架** | 目录重排（六层）+ 依赖规则测试 + `RunScope`/`StepScope` + 洋葱执行器 + `Filter` 出口 + **行为不变** | **现有 18 个测试全绿**；新增架构测试 | 整期可 revert，不改对外 API |
| **P2 契约扩充** | 五 Store、十后端、四判定拆分、`ToolSpec`、`Frame`、事件流、`astream` | 24 组一致性测试；RAG/Memory/Skills 例子改造后跑通 | 旧接口保留 `deprecated` 别名 |
| **P3 内置件** | 12 个中间件 + 输入/输出护栏 + 子 agent + 任务板 + 沙箱/FS | 编码 agent 剧本端到端；护栏五道闸各有测试 | 每个中间件可单独关 |
| **P4 生产化** | OpenAI/Qdrant/OTel/MCP 适配器、SQLite/Postgres 存储、CLI 脚手架 | 真实模型跑通；一个示例项目 ≤ 20 行 | 适配器独立发布 |

**P1 是唯一的硬门槛**：只重构骨架、不改行为，用 18 个测试当回归网。测试一红，说明骨架抽错了，立刻回头，不要往下推进。

---

## 19. 反模式（明确不做）

| 反模式 | 为什么不做 |
|---|---|
| 内核可替换（`BodyPolicy` 再往下抽象成图） | 会变成 LangGraph；失去"一个内核"这个唯一优势 |
| 两套扩展点（hook 一套 + middleware 一套） | 必然语义分叉，用户永远猜错挂在哪 |
| 合并 Guard 与 Guardrail | 失败语义不同（停 vs 改写），合并后只能靠字符串猜 |
| 把 Guard 塞进中间件链 | 安全不变量会被顺序调整破坏 |
| State 里放连接/句柄/锁 | 不可序列化 → 不可重放 → 检查点失效 |
| 响应式 State（Proxy/依赖收集） | 破坏确定性与可序列化，见 §6.1 |
| 同步/异步双套接口 | 两套实现必然不一致，同步只留最外层 |
| 全局单例后端 | 子 agent 拿不到独立沙箱 |
| 用类名判断语义（`policy.__class__.__name__`） | 隐式耦合，v1 已踩过（§14.2） |
| "零配置魔法" | 隐式行为是框架最难排查的故障源 |

---

## 20. 决策记录（ADR 摘要）

| # | 决策 | 备选 | 理由 |
|---|---|---|---|
| 1 | 内核不可替换，只可拦截 | 可替换内核（图运行时） | 保住"一个内核"的确定性与可测性 |
| 2 | 四段执行链（Gate/Check/Wrap/Classify）分离 | 单一洋葱 | 四段失败语义不同，合并后 deny 与校验失败无法区分 |
| 3 | 取景-编码分两段，不做响应式 | 单段装配 + 响应式派生 | 响应式破坏可序列化与可重放；单段装配把选择与格式耦合 |
| 4 | 护栏五道闸、检测与动作分离 | 只做输入/输出两道 | 间接注入在检索与工具结果 |
| 5 | Store 拆五个 | 单一 Store | 访问模式不同，混用导致覆盖写 |
| 6 | 中间件顺序拓扑排序 | 手工顺序 | 组合爆炸，第三方无法插入 |
| 7 | hook = 退化中间件 | 独立 hook 系统 | 单扩展点原则 |
| 8 | 配置只描述意图 | 配置即对象 | 可序列化、可校验、可 diff |
| 9 | 事件一等公民、双形态 | 只有结果 | UI/SSE/计费都靠它 |
| 10 | 同 session 串行 | 并发 + 合并 | 检查点一致性优先 |
| 11 | 剪裁必须可解释（`dropped`） | 静默丢弃 | 否则模型不知道自己瞎了 |
| 12 | 一致性测试定义可替换性 | 文档声明 | 唯一可信的兼容承诺 |
| 13 | 结构模型 = 两条不变量 + 三个视图 | 单一总模式；或把归位表当模型 | 可变性三向正交，单模式只解释三分之一；归位表只归档不推导、缺时间与所有权维度（§2.4） |
| 14 | 执行链固定四段，不提供装饰器 / DI 容器 / 请求作用域 | 洋葱 + 装饰器 + DI 容器 | agent 是长事务（流式、挂起、重放），与单次请求模型不匹配；装饰器与组合式 API 冲突（§5.2） |
| 15 | 历史不可变用多版本快照实现 | 事件日志 + fold | 事件日志需效果记忆化与 schema 演进；多版本快照能力等价且无这两项成本（§2.4） |
| 16 | 组合以函数复合为一等形态 | 类式装配（构造参数 / 子类） | 可组合、可替换、可干跑；语法糖 `>>`，代价是需 `describe` 补可见性（附录 D） |
| 17 | 不支持同一 run 内并行工具调用 | 并行 + 部分失败合并 | 部分失败的语义（重试哪几个、结果怎么合）没有唯一答案，串行才有确定性 |
| 18 | 检查点默认全留，按 namespace 配保留窗口 | 全局滚动窗口 / 全留且不可配 | 时间旅行是能力而非成本项；窗口必须可选，否则长任务撑爆存储 |
| 19 | 护栏规则只允许 Python 代码，不提供 DSL | 仓库级规则 DSL | DSL 要自带解析、版本、测试三件事，收益远低于成本 |
| 20 | 子 agent 支持 `expected_schema` 结构化返回 | 只返回文本 | 调用方要程序化用结果，解析文本是隐性 bug 来源 |
| 21 | 提供 `harness new` 脚手架，在 P4 交付 | 只给文档示例 | 20 行体验需要脚手架固化，否则每个项目重新拼装 |

---

## 附录 A：目标体验（20 行）

```python
import asyncio
from harness import Harness, HarnessConfig, Goal, tool

@tool(side_effects="read")
async def get_order(order_id: str) -> dict:
    """查询订单。"""
    return {"order_id": order_id, "status": "已签收"}

async def main():
    cfg = HarnessConfig(
        model="openai:gpt-4.1",
        tools=(get_order,),
        middlewares=("tenancy", "budget", "audit", "checkpoint",
                     "input_guard", "output_guard", "context",
                     "taskboard", "subagent", "capability"),
        backends={"fs": "local:/work", "sandbox": "subprocess"},
        guardrails=("injection", "pii", "secret_leak"),
    )
    async with Harness(cfg) as app:
        async for ev in app.astream(Goal("查 A1001 并写报告")):
            print(ev)

asyncio.run(main())
```

## 附录 B：术语

| 术语 | 含义 |
|---|---|
| 骨架 | 内核里不可变的执行顺序 |
| 挂载方式 | 替换 / 包裹 / 观察 |
| 结构模型 | 两条不变量 + 三个视图；「插点 × 挂载」矩阵只是归位表（§2.4） |
| 视图 | 控制流（插点）/ 依赖（六边形）/ 数据（取景-编码） |
| 闸 | 护栏的位置（五道） |
| 段 | 一次 step 内的四个阶段：Gate / Check / Wrap / Classify |
| 插点 | 中间件可包裹的位置：run / step / model_call / tool_call |
| 作用域 | 资源归属边界（run/step/child） |
| 取景 | State → Frame 的选择与裁剪，不涉及格式 |
| 一致性测试 | 证明"实现可替换"的通用用例组 |

## 附录 C：已定的产品决策

原本留待决策的五个问题，现已定死（理由见 §20 的 ADR 17–21）：

| 项 | 决定 |
|---|---|
| 同一 run 内并行工具调用 | **不支持**，工具调用一律串行 |
| 检查点保留 | **默认全留**；按 namespace 可配保留窗口，窗口外才删 |
| 护栏规则 DSL | **不提供**，只允许 Python 代码 |
| 子 agent 返回 | **支持 `expected_schema`** 结构化返回 |
| CLI 脚手架 | **提供 `harness new`**，P4 交付 |

## 附录 D：FP 组合样张（可运行）

代码：[`code/harness/examples/fp_composition.py`](../../code/harness/examples/fp_composition.py)。不是框架实现，是用来验证"组合体验"的形态样张，`python` 直接跑，无依赖。

**核心只有三条**：① 程序 = `Aspect`，一个 `Handler -> Handler` 的纯函数；② 组合 = 函数复合（`>>` 左为外层、`|` 回退），无类、无装饰器、无容器；③ 后端 = `env` 里的能力记录，换后端不改程序一个字。

```python
# 工具点：准入 → 执行
tool_chain = compose(approval(lambda t: t != "refund"), audit())
# 运行 / 步点：预算 → 循环 → 每步落盘
program = compose(budget(2_000), react(max_steps=6), checkpoint())

result = await run(program, tool_chain,
                   env={"model": model, "tools": TOOLS, "store": store, "sink": sink},
                   goal="查 A1001 并退款")
```

真实输出（本机跑通，2026-11-04）：

```text
① 程序文本（组合的代价是看不见顺序，所以必须能打印）
    运行链 = budget(2000) > react(6) > checkpoint(store)
    工具链 = approval > audit(sink)

② 跑一次（内存后端）：refund 被准入拒绝，且没有真的执行
    状态=refused  答案=拒绝执行 refund
    已执行工具=['fetch_order']  检查点=1 个  审计=1 条

③ 同一程序，换后端（jsonl）+ 干跑（效果只入账，不执行）
    状态=completed  检查点=1 个
    已执行=[]  消息=[]
    收集到的效果=[{'tool': 'fetch_order', 'args': {'order_id': 'A9'}}]

④ 回退：故意让预算断言炸掉，用 `|` 换整条链
    程序=explode > react(2) > | > react(2)
    状态=completed  答案=兜底成功  trace=['fallback:explode > react(2)']

⑤ 顺序无关性：交换 audit / checkpoint，结果必须一致
    react(6) > checkpoint(store) > audit(sink) -> ('completed', 'ok', ['fetch_order'])
    react(6) > audit(sink) > checkpoint(store) -> ('completed', 'ok', ['fetch_order'])
    等价：True
```

这份样张暴露了三件对设计有约束力的事：

| 观察 | 对设计的约束 |
|---|---|
| ② 第一版把 `approval` 挂在 step 外层，结果"状态 refused 但 refund 已执行" | **插点必须分层**：准入属 `tool_call` 点，不属于 `step` 点。一条洋葱盖不住两层 |
| ③ `mode=collect` 时 `已执行=[]` 但 `效果=[...]` | **效果可以是数据**。这是"先干跑再执行"、以及一致性测试能离线跑的前提 |
| ⑤ 交换 audit / checkpoint 结果相同 | **顺序无关性是必须被测试的性质**，不是口头承诺——这是中间件用拓扑排序而非手工排序的直接理由 |

代价也要写下来：`>>` 链条看不见最终顺序（故必须提供 `describe`）、类型提示弱于显式参数、深度嵌套时栈帧变长（故 §5.4 要求不重复包装异常，且每个环节发 span）。**组合不是免费的，它用"可读性成本"换"可组合性收益"**。判据是定死的：需要组合的部件 ≤ 6 个时用显式构造参数，> 6 个时用组合。
