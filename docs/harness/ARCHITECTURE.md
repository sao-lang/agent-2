# agent-harness 框架架构设计

> **版本** v2 设计稿 · 2026-11-04
> **范围** `code/harness/`（副线组件基座）
> **基线** 卷 12（第 48–53 章）大纲的全部功能，逐条落到层见 §1.3；v1 的 12 类型 / 11 接口语义不改
> **前置阅读** `docs/harness/DEV-SESSION.md`（施工记录）、第 48–53 章（设计理由）
> **本文性质** 架构决策文档，不是 API 手册。凡写"必须/禁止"的，都可落成可执行检查。

---

## 0. 结论

### 0.1 十一条

1. 现在的包是**库**，不是框架；差别不在接口数量，在**控制反转**。收口方案：内核只保留一条固定骨架，其余全部下沉为可组合部件（中间件 / 后端 / 存储 / 投影）。
2. **框架的结构模型是一条主轴 + 两个截面**：主轴 = 控制流（run → step → model_call / tool_call 四个拦截点）；截面 A = 依赖（六边形，只向内）；截面 B = 数据（单向投影）。三者统一表达为**「插点 × 挂载」矩阵**（§2.3）——任何可变性必须落进唯一一个格子。这是本框架对"结构模型是什么"的回答。
3. 彻底解耦的抓手不是"多写 Protocol"，是**依赖方向单一**（六边形 / Ports & Adapters）：除契约层外，任何模块只能 import 契约层。这条用可执行测试守住，不靠自觉。
4. 一次 `step` 按 Nest 的四件套切分：**Guard（准入）→ Pipe（校验）→ Interceptor 洋葱（包裹）→ Filter（错误出口）**。四类失败语义不同，禁止合成一条链。
5. 给模型看的上下文是**表现层**，只是观众不是人：State 经 Projector 投影、经 Renderer 渲染，一份状态多个只读视图。借 MVVM 的**三分**，不借 MVVM 当整体结构（§6.1）。
6. 护栏独立于 Guard：**Guard 管"动作能不能做"（决策边界），Guardrail 管"内容能不能进出"（数据边界）**；入站、入上下文、出模型、工具边界、出口共五道闸。
7. 内置中间件 12 个，顺序由**声明式依赖 + 拓扑排序**得出，不由人手排。
8. Store 拆五个（会话 / 检查点 / 消息日志 / 记忆 / 幂等），另有 Artifact 存大对象；记忆的难点在 `MemoryPolicy`，不在 Store 本身。
9. 后端十个（模型 / 文件 / 沙箱 / 工件 / 密钥 / 索引 / 事件 / 队列 / 审批 / 时钟），一律窄接口 + 内存实现 + 一致性测试。
10. 所有资源走**作用域**（run scope → step scope → child scope），`async with` 收口；子 agent 默认独立沙箱、共享预算。
11. 迁移四期，每期可回滚；期 1 的唯一验收标准是**现有 18 个测试全绿**。

### 0.2 对三条建议的裁决

| 建议 | 裁决 | 具体处置 |
|---|---|---|
| 护栏分输入、输出 | **全采纳，并扩展** | 两道不够，共五道闸（§8.2）；检测与动作分离（§8.3）；流式输出必须增量护栏（§8.5）；护栏自身崩溃的默认语义要显式定义（§8.6） |
| 架构要不要有统一的结构模型（MVVM 只是举例） | **采纳问题，否决"单一模式"** | 单模式装不下：可变性有三个正交方向（控制流 / 依赖 / 数据），MVVM 只覆盖数据方向的一半。统一表达改用**「插点 × 挂载」矩阵**（§2.3）；MVVM 的三分只落在截面 B（§6.1）。响应式仍拒绝：破坏可序列化与可重放 |
| 借 Nest / Express 洋葱圈 | **采纳并修正** | 洋葱只能覆盖"包裹一对"这一种语义（Interceptor）。Guard / Pipe / Filter 硬塞进洋葱会让失败语义混乱（谁抛错、谁短路、谁改结果分不清）。真正值得借的是**四件套的分工**，见 §5.2 |

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
| 10 | State 信封 + 命名空间 | 契约 | ✅ | 拆 Model/投影三层 |
| 11 | Durability 检查点 | 存储 | ✅ 覆盖写 | 加 rev、时间旅行 |
| 12 | 人工审批 + resume | 内核 + 中间件 | ✅ | 泛化为任意检查点恢复 |
| 13 | Budget | 契约 + 中间件 | ✅ | 支持父子预算切分 |
| 14 | Tracer / 事件 | 后端 | ✅ | 加事件流与 span 传播 |
| 15 | Delivery 出口 | 内核 | ✅ | 拆 Result / Event 双出口 |
| 16 | RAG：Knowledge / Retrieval / Context | 部件 + 后端 | ✅ 最小 | Context 拆成 Projector + Renderer |
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

### 2.3 结构模型：一条主轴 + 两个截面

Vue 的结构模型是 MVVM。本框架的结构模型是什么？——**没有单一的"某某 V"可用，因为可变性有三个正交方向**。硬凑一个"agent 的 MVVM"，只会得到一张只解释三分之一的图，剩下三分之二靠口口相传，这正是 v1 的病灶。

| 轴 | 要回答的问题 | 采用的结构 | 明确不采用 |
|---|---|---|---|
| **主轴**（控制流） | 什么时候调用、谁能插手 | 四个拦截点，每点一条洋葱 | 不用图 / DSL 描述流程 |
| **截面 A**（依赖） | 谁能依赖谁、什么可替换 | 六边形（Ports & Adapters），依赖只向内 | 不用分层图描述调用关系 |
| **截面 B**（数据） | 看见什么、看见多少 | 单向投影（State → ViewModel → View） | 不做响应式、不做双向 |

三轴之间只允许两条连接线，**禁止互相穿透**：

1. 主轴上的拦截点通过**作用域**取到截面 A 的实现对象（不 import 具体类）。
2. 截面 B 的产物只能经 `model_call` 的请求 / 响应进出（投影层不许调工具，后端不许读 State 内部结构）。

#### 把三轴压成一个可检查的东西：「插点 × 挂载」矩阵

| 位置 ＼ 挂载 | **替换**（实现协议） | **包裹**（中间件） | **观察**（hook） |
|---|---|---|---|
| `run` | — | Tenancy / BudgetGuard / Audit / Trace | `on_run_start` `on_run_end` |
| `step` | `BodyPolicy`（react / workflow / pe） | TaskBoard / Reflector 重试 / Checkpoint | `on_step_end` |
| `model_call` | `Model` 后端、`Projector` + `Renderer` | ContextManager / 缓存 / InputGuard / OutputGuard | `on_model_call` |
| `tool_call` | `Tool`、`FileSystem`、`Sandbox`、`Index` | Approval / 沙箱路由 / 幂等 / SubAgent / Capability | `on_tool_call` |
| 出口 | `Delivery`（Result + Event 双出口） | OutputGuard（最终答案） | `on_run_end` |
| 构造期 | 24 个协议实现（store / backend / model / …） | 插件（entry points） | — |

**用法：任何功能、任何改动，先在表里指一个格子。**

- 指不到 → 协议缺了。补 §4.5 的清单，**不要给内核开洞**。
- 指到两个 → 职责重叠，迟早出现双重执行或顺序歧义。
- 指到"内核骨架"→ 不允许。内核只有骨架与插点，其余全在表里。

这张矩阵比分层图更有用：分层图只能描述截面 A，而**框架的多数设计错误恰恰是"把变化放错格子"**。v1 有三个真实案例——

| 错误 | 放错的格子 | 后果 |
|---|---|---|
| 把内容护栏做成 `Guard` | "内容"塞进"动作"的格子 | deny 语义混淆：该改写的被停掉，该停的被放过 |
| 用静态拓扑代替运行时子 agent | "运行时"塞进"构造期"的格子 | 不能在循环中派发，`Supervisor` 只能预排 |
| 把压缩写进 `assemble` | "策略"塞进"渲染"的格子 | 压缩不可测、不可回放、不可换 |

三条轴的命名在代码里也要可见：`kernel/` 对应主轴，`contracts/` 对应截面 A 的端口，`parts/projection/` 对应截面 B（§3.4）。

---

## 3. 分层与依赖规则

### 3.1 六层（截面 A 的落地：六边形 / Ports & Adapters）

这一节只负责**空间轴**：把 §2.3 的"截面 A"落成目录与依赖规则。端口（`contracts`）归内核所有，适配器（`impl` / `adapters`）在外围实现，依赖一律向内。

```text
L5 适配器    adapters/       openai · qdrant · otel · mcp · sqlite · local-sandbox
                             只 import L0-L4，且只被装配层按需 import（懒加载）
L4 装配      assembly/       Harness(cfg) · 校验 · 插件注册 · 生命周期
                             依赖 L0-L3，不可被任何下层 import
L3 部件      parts/          policy · projector · renderer · middleware · topology · guardrail
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
│   │   ├── projections.py Projector / Renderer / ViewModel / Pack
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
│   ├── projection/        budgeted_projector · renderer · views
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
| 视图 | `ViewModel` `ViewCard` `Recalled` | 投影层产物（§6） |
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

### 4.4 工具元数据（v2 新增）

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
| 投影 | `Projector` `Renderer` | 1 / 1 | `BudgetedProjector` |
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

### 5.2 四件套（借用 Nest，但各管一件事）

```text
                 ┌──────────────── Filter（错误出口）────────────────┐
Step ──▶ Guard ──▶ Pipe ──▶ ┌── Interceptor beforeEach ──┐            │
  (判定)  (准入)  (校验)      │                            │           │
                             │   Sandbox / Tool.invoke    │           │
                             │                            │           │
                             └── Interceptor afterEach ───┘           │
                                                       Result ────────┘
```

| 件 | 位置 | 职责 | 失败语义 | 能否改结果 |
|---|---|---|---|---|
| **Guard** | 最前 | 准不准做（策略：审批、白名单、预算） | 返回 `deny/ask`，**不抛错** | 能短路 |
| **Pipe** | Guard 后 | 参数校验/补全/类型转换 | 抛 `ValidationError`，映射成 `REFUSED` | 能改参数 |
| **Interceptor** | 包住执行 | 包裹、记账、超时、幂等、路由、截断 | 异常穿透给 Filter | 能改结果 |
| **Filter** | 最外 | 异常 → `RunStatus` 的**唯一**映射点 | 不吞错，只归类 | 决定出口状态 |

**关键修正（对"洋葱圈"建议的处理）**：Guard / Pipe / Filter **不是洋葱层**。把它们塞进洋葱会立刻出现三种歧义——Guard deny 后要不要继续走 afterEach？Pipe 抛错算不算运行失败？Filter 在洋葱里是第几层？把四件分开后，每个问题只有一个答案。

真正是洋葱的只有 Interceptor：

```python
# kernel/chain.py —— 洋葱执行器
async def run_chain(mws: Sequence[Middleware], req: Request, terminal: Handler) -> Response:
    async def step(i: int, r: Request) -> Response:
        if i >= len(mws):
            return await terminal(r)
        return await mws[i](r, lambda r2: step(i + 1, r2))
    return await step(0, req)
```

### 5.3 四个拦截点

| 拦截点 | 请求 / 响应 | 典型中间件 |
|---|---|---|
| `run` | `RunRequest{goal, namespace}` / `RunResult` | 租户、审计、限流、总预算、记忆写回 |
| `step` | `StepRequest{state, step\|done}` / `StepResult` | 任务板、反思重试、审批挂起 |
| `model_call` | `ModelRequest{messages, tools, budget}` / `ModelReply` | 上下文压缩、缓存、脱敏、输入护栏、输出护栏 |
| `tool_call` | `ToolRequest{step, spec}` / `ToolResult` | 沙箱路由、路径 jail、幂等、截断、子 agent、skill |

四级是**嵌套**关系（run ⊃ step ⊃ {model_call, tool_call}），所以四个点各有一条链，不是一条链走到底。

### 5.4 四条安全不变量（写进代码，不写进文档）

1. **`tool_call` 链的终端永远是 Guard → invoke**。中间件可以改参数、可以在之后审计，但**不能把 Guard 挪走、不能跳过**。
2. **没有工具调用就没有副作用**。禁止中间件直接做 IO 然后伪造 `ToolResult`——需要 IO 就注册工具。
3. **出口唯一**。所有终止路径都经 `Filter → delivery.finish`，禁止在内核里定向 `return`（v1 的 `WorkflowPolicy` 特判，见 [agent.py:238](../../code/harness/src/harness/agent.py)，就是反例，v2 删除）。
4. **State 只存可序列化数据**。中间件私有状态放实例，不放 `State`。

---

## 6. 截面 B：投影（模型看见什么）

### 6.1 借 MVVM 的三分，不借 MVVM 本身

先划清边界：**MVVM 是 Vue 的整体结构模型，这里借不了。** 框架的可变性有三个方向（§2.3），MVVM 只覆盖"表现层"这一个，而且只覆盖它的一半。

但它覆盖的那一半，恰恰是 agent 独有、而 v1 完全没建模的：**agent 也有表现层，只不过观众不是人，是模型——上下文窗口就是视图。**

| MVVM | 本框架 | 内容 |
|---|---|---|
| Model | **State** | 领域事实，唯一可变、唯一可序列化 |
| ViewModel | **Projector** | 把 State 投影成"给某个消费者看的视图"，负责选、排序、裁剪 |
| View | **Renderer** | 把 ViewModel 渲染成具体格式（messages / 审批卡片 / UI JSON） |

"观众是模型"这一点决定了很多设计：人看 UI 可以滚动、可以追问、可以忍冗余；模型看上下文不行——超了就是超了，漏了它也不知道。所以"选哪些、怎么排、超预算丢谁、丢了怎么告知"必须是**一等公民**，而不是某个 `assemble` 方法里的几行 `while`。

现在 [BudgetedContext.assemble](../../code/harness/src/harness/context.py) 一个方法同时做了"选哪些""怎么排""放哪个槽""超预算丢谁""渲染成什么格式"五件事。结果是换个 UI 要改内核，换个模型上下文策略要改渲染。三分之后：

```text
同一份 State
  ├─ Projector(model_view)    → 只留预算内的、按相关性排序    → Renderer(openai)  → Pack
  ├─ Projector(human_view)    → 全量 + 折叠 + 时间线          → Renderer(ui)      → ViewModel
  ├─ Projector(approval_view) → 只留待批那一步 + 影响面        → Renderer(card)    → ViewCard
  └─ Projector(trace_view)    → 步骤 + 用量 + 耗时            → Renderer(jsonl)   → RunEvent[]
```

**两条拒绝**：

1. **拒绝把 MVVM 当整体结构模型**。框架其余三分之二的可变性（依赖方向、控制流）不在表现层。用 MVVM 去描述它们，会漏掉 §2.3 矩阵里一半的格子，还会凭空造出一个不存在的 UI 组件树。
2. **拒绝响应式**（Proxy / 依赖收集 / 双向绑定）。在这里是负资产：
   - State 必须能 `to_dict()` 后落库、重放；Proxy 会把不可序列化的陷阱对象带进 State。
   - 模型看见的内容必须**确定性**：同一 State 重放必须得到同一 Pack。响应式让"看见什么"依赖求值时机。
   - Agent 没有"用户改表单"这个事件源，双向绑定无用武之地。

结论：投影是**截面 B 的局部模型**，不是框架的结构模型；结构模型见 §2.3。

### 6.2 三个协议

```python
class Projector(Protocol):
    name: str
    async def project(self, state: State, view: ViewKind, *, budget: Budget) -> ViewModel: ...

class Renderer(Protocol):
    fmt: str
    async def render(self, vm: ViewModel) -> Pack | ViewCard | list[RunEvent]: ...

@dataclass(frozen=True)
class ViewModel:
    kind: ViewKind                      # model | human | approval | trace
    sections: tuple[Section, ...]       # 有序、带优先级、带来源引用
    dropped: tuple[str, ...]            # 被裁掉的，必须可解释
    tokens_est: int
```

三条纪律：

- **Projector 不渲染**（不拼字符串、不决定 JSON 结构）；**Renderer 不选择**（不决定留哪条）。
- **裁剪必须可解释**：`dropped` 不为空时，`model_view` 会把它渲染成一句"已省略 N 条较早历史"，否则模型不知道自己瞎了。
- **同一个 ViewModel 可被多个 Renderer 消费**（OpenAI / Anthropic / 本地 UI），这是"换模型不改内核"的落点。

### 6.3 与上下文压缩的分工

压缩是**投影策略**，不是独立机制：`summary_projector` 用摘要替换早期 `sections`，产出同样是 `ViewModel`。好处是压缩的结果可见、可测、可回放（v1 里压缩逻辑散在 `assemble` 的循环里，无法单测）。

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
    optional: bool                  # 后端缺失时是否可自动降级

    async def __call__(self, req: Request, nxt: Handler) -> Response: ...
```

顺序由**拓扑排序**得出，不由人手排。三个好处：① 换顺序不会崩；② 缺依赖在启动期就报错，不拖到运行期；③ 第三方中间件可以声明"我必须在内置 X 之后"，不用改内置代码。

排序冲突（环）→ `ConfigError`。`after`/`before` 只约束同一点内的链。

### 7.2 顺序铁律

1. **改输入的在外，改输出的在内**（否则你截断完又被压缩）。
2. **便宜的在外的**（租户判定、预算检查不必承担后续开销）。
3. **安全在最内**：Guardrail（内容）在 Interceptor 内侧、紧贴终端；Guard（动作）永远在终端前最后一环。

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
| 9 | `ContextManager` | model_call | — | 调用 Projector 装配；预算紧张时触发摘要压缩 | 上下文无裁剪 |
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
| ① 目录 | 每次 `model_call` | 每 skill 一行（name + description） | Projector 的 `skills` section |
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
用户输入 ──▶ ① 入站 ──▶ 投影 ──▶ ② 入上下文 ──▶ 模型 ──▶ ③ 出模型
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
| 一个 run 内多个工具 | **串行**（v1 行为保留） | 并行工具要处理"部分失败"语义，v2 不引入 |
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
    projections: ProjectionSpec = ProjectionSpec()
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
| 部件单测 | 中间件、投影、护栏、存储各自 | 数百 | 假实现 |
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
| **P2 契约扩充** | 五 Store、十后端、四判定拆分、`ToolSpec`、`ViewModel`、事件流、`astream` | 24 组一致性测试；RAG/Memory/Skills 例子改造后跑通 | 旧接口保留 `deprecated` 别名 |
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
| 2 | 四件套（Guard/Pipe/Interceptor/Filter）分离 | 统一洋葱 | 失败语义不同，合并产生歧义 |
| 3 | 投影只用于截面 B，不做响应式 | 把 MVVM 当整体结构模型 | 框架可变性只有三分之一在表现层；响应式破坏可序列化与可重放 |
| 4 | 护栏五道闸、检测与动作分离 | 只做输入/输出两道 | 间接注入在检索与工具结果 |
| 5 | Store 拆五个 | 单一 Store | 访问模式不同，混用导致覆盖写 |
| 6 | 中间件顺序拓扑排序 | 手工顺序 | 组合爆炸，第三方无法插入 |
| 7 | hook = 退化中间件 | 独立 hook 系统 | 单扩展点原则 |
| 8 | 配置只描述意图 | 配置即对象 | 可序列化、可校验、可 diff |
| 9 | 事件一等公民、双形态 | 只有结果 | UI/SSE/计费都靠它 |
| 10 | 同 session 串行 | 并发 + 合并 | 检查点一致性优先 |
| 11 | 剪裁必须可解释（`dropped`） | 静默丢弃 | 否则模型不知道自己瞎了 |
| 12 | 一致性测试定义可替换性 | 文档声明 | 唯一可信的兼容承诺 |
| 13 | 结构模型 = 「插点 × 挂载」矩阵 | 用单一模式（如 MVVM）统一描述 | 可变性三向正交，单模式只能解释三分之一；矩阵可检查、可问责 |

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
| 结构模型 | 一条主轴 + 两个截面；落地为「插点 × 挂载」矩阵（§2.3） |
| 截面 | 截面 A = 依赖（六边形）；截面 B = 数据（单向投影） |
| 闸 | 护栏的位置（五道） |
| 件 | 一次 step 内的四类拦截器 |
| 作用域 | 资源归属边界（run/step/child） |
| 投影 | State → ViewModel 的单向变换 |
| 一致性测试 | 证明"实现可替换"的通用用例组 |

## 附录 C：未决问题（需要产品决策）

1. 是否支持"同一 run 内并行工具调用"——语义复杂度高（部分失败怎么办），倾向不支持。
2. 检查点保留策略：全留（可时间旅行，存储贵）还是滚动窗口（便宜，不能回溯）——倾向按 namespace 配置。
3. 护栏是否允许仓库级自定义规则 DSL——倾向只允许代码（Python），不做 DSL。
4. 子 agent 的 `answer` 是否允许结构化（返回 JSON 而非文本）——倾向允许 `expected_schema`。
5. 是否提供 CLI 脚手架 `harness new`——P4 再定，先把 20 行体验打磨好。
