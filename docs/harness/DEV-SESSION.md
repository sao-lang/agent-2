# 副线组件基座：开发会话指导

> **用途**：开一次 `code/harness/` 开发会话前，先读这一份。它记录 2026-10-31 讨论中定下的结构、场景、代码接口与注意事项。
>
> **范围**：卷 12（第 48–53 章）的基座实现与配套正文；不重写主线 0–47、54–59。
>
> **状态**：Phase 0–1 已落地（契约、Agent 循环、ReAct/Workflow/P&E、工具、Guard/Budget/Tracer/Durability/Delivery、审批恢复），RAG/Memory/Resilience/Router/Skills 为最小实现；卷 12 第 48–53 章已写完，四种拓扑已实现。MCP 与真实适配器按第 9 节继续。本文是施工依据，不是最终 API 文档。

---

## 0. 一页结论

1. 这卷不是"组件库导览"，是交付一个**能安装、能测试、能演进的基座**，后续项目直接用它装不同架构的 agent。
2. 四层是**装配语法**，不是包结构：

   ```text
   架构 = 拓扑( Agent[] )
   Agent = 分派层 + 主体层 + 校验层
   横切能力 = 治理 / 供给 / 交付，挂在 Agent 与 loop 的固定插点上
   ```

3. **不要把 15 个组件平铺成同一级。** `Planner` 只属于 `PlanExecute`；`Workflow` 与 `ReAct` 不持有 Planner。
4. 主体层内部再分：`LoopKernel`（必需）、`BodyPolicy`（三选一）、`ExecutionPrimitives`（共享）。
5. 15 个组件里，`Router`、`Guard`、`Delivery`、`Knowledge`、`Skills` 在大纲里缺 Protocol，必须在基座里补齐。
6. `State` 用"信封 + 命名空间"，不要把所有策略的字段并集塞进一个 dataclass。
7. `Topology` 必须实现 `Runnable`/`Agent` 接口，否则不能嵌套。
8. 业务代码只做三件事：**定义能力、填配置、调 `run`**；不 import 内部组件。

---

## 1. 目标与非目标

### 目标

- `pip install -e .` 后，20 行内跑起一个 agent。
- 同一个包能装：单 agent、Workflow、ReAct、P&E、Supervisor、Handoff、Blackboard、Pipeline。
- 换组件（模型、检索、记忆、Guard、Reflector、Tracer）不改 `Agent` 循环。
- 每个组件可离线单测：无模型、无网络。
- 有适配器边界：OpenAI / LangChain / Qdrant / OTel 都不进核心。

### 非目标

- 不做跨进程 A2A（第 34 章）。
- 不做消息队列、限流、鉴权网关（第 32 章）。
- 不做 UI 与平台（第 41 章）。
- 不替代 LangGraph/LangChain，只提供可组合的运行时。

---

## 2. 架构总图

```text
Topology（Supervisor / Handoff / Blackboard / Pipeline）
  └── Agent（Runnable）
        ├── Dispatch     Router + Route + fallback
        ├── Body         LoopKernel + BodyPolicy + ExecutionPrimitives
        └── Verify       Reflector + Judge + Verdict
  cross-cutting:
        Guard / Budget / Tracer / Durability / Delivery
        Knowledge / Memory / Skills
```

### 四层的职责

| 层 | 回答的问题 | 输入 → 输出 | 主要实现 |
|---|---|---|---|
| 分派 | 这条请求走哪条路 | `Goal → Route` | `RuleRouter`、`LLMRouter`、`VectorRouter`、`AlwaysRoute` |
| 主体 | 这一步怎么推进 | `State + Step → ActionResult` | `Workflow`、`React`、`PlanExecute` |
| 校验 | 做对了吗、要不要重来 | `ActionResult + Plan → Verdict` | `RuleReflector`、`LLMJudge`、`NullReflector` |
| 拓扑 | 几个 Agent 怎么连 | `Goal → RunResult` | `Supervisor`、`Handoff`、`Blackboard`、`Pipeline` |

### 横切组件不是第五层

| 类别 | 组件 | 挂点 |
|---|---|---|
| 治理 | `Guard`、`Budget`、`Tracer`、`Durability` | 动作前、每步后、运行前后 |
| 供给 | `Knowledge`、`Memory`、`Skills` | 装配前、运行前、按需 |
| 交付 | `Delivery` | 出口 |

---

## 3. 关键修正：不要把 15 个组件平铺

### 3.1 Planner 只在 P&E

| 策略 | 下一步从哪来 | 需要 Planner |
|---|---|---|
| Workflow | 开发者写死的步骤表 | 否 |
| ReAct | 模型每轮根据观察决定 | 否 |
| Plan-and-Execute | 先由 Planner 产出 `Plan`，再逐步执行 | **是** |

配置用判别联合，错误组合在 `build` 时拒绝：

```python
@dataclass
class WorkflowConfig:
    steps: list[Step]

@dataclass
class ReactConfig:
    max_steps: int = 8

@dataclass
class PlanExecuteConfig:
    planner: Planner          # 只有这个分支有

BodyConfig = WorkflowConfig | ReactConfig | PlanExecuteConfig
```

| mode | planner | workflow |
|---|---|---|
| `workflow` | 必须为 `None` | 必须有 |
| `react` | 必须为 `None`（内部 `ImplicitPlanner`） | 必须为 `None` |
| `pe` | 必须有 | 必须为 `None` |

### 3.2 主体层内部

```text
主体层
├── LoopKernel        必需：状态、步进、终止、插点调用
├── BodyPolicy        三选一：Workflow / ReAct / PlanExecute
└── ExecutionPrimitives  共享：Actor、Tools、Context、Resilience
```

`Agent` 只持有 `policy`，不持有 `planner`：

```python
Agent(policy=PlanExecutePolicy(planner=..., actor=...), ...)
```

### 3.3 四层是选型语言，不是 import 路径

代码按运行时分组：`core/`、`kernel/`、`components/`、`topology/`、`adapters/`、`build/`。四层只出现在 `build` 的选型表和书稿的章节结构里。

---

## 4. 包结构

```text
agent-harness/
├── pyproject.toml
├── src/harness/
│   ├── __init__.py          # 只导出稳定 API，__version__
│   ├── contracts.py         # 类型、Protocol、错误
│   ├── state.py             # State 信封
│   ├── result.py            # RunResult、RunStatus
│   ├── agent.py             # Agent 循环
│   ├── kernel/              # LoopKernel、BodyPolicy、Done
│   ├── body/                # workflow.py、react.py、pe.py、planner.py
│   ├── dispatch/            # router.py、route.py、fallback.py
│   ├── verify/              # reflector.py、judge.py、verdict.py
│   ├── components/          # actor、tools、context、budget、guard、tracer、durability、delivery、knowledge、memory、skills、resilience
│   ├── topology/            # supervisor、handoff、blackboard、pipeline
│   ├── build/               # config.py、presets.py
│   ├── adapters/            # openai、langchain、qdrant、sqlite、otel、mcp
│   └── testing/             # FakeModel、FakeTool、FakeJudge
├── examples/                # pdf_analysis、refund、research、rag_qa
└── tests/
```

**核心零第三方依赖**；适配器放 `adapters/`，用 extras 安装。

---

## 5. 公开 API 与契约

### 5.1 对外只承诺一个小 API

```python
from harness import (
    Agent, AgentConfig, build, Goal, RunResult, RunStatus,
    tool, Tool, GuardDecision, Verdict,
    Router, Route, Knowledge, Memory, Skills, Tracer, Durability,
)
```

其余组件是高级扩展点，不承诺稳定。

### 5.2 核心类型

| 类型 | 字段/职责 |
|---|---|
| `Goal` | `text`、`user_id`、`session_id` |
| `Step` | `id`、`instruction`、`tool_name`、`args`、`idem_key` |
| `ActionResult` | `step`、`ok`、`output`、`error`、`tokens` |
| `Verdict` | `passed`、`reason`、`action`（accept/retry/patch/replan_all） |
| `Plan` | `id`、`steps`、`rev`（只有 P&E 用） |
| `Recalled` | `text`、`layer`、`score`、`source`、`age_days` |
| `Pack` | `messages`、`usage`、`dropped` |
| `SessionRef` | `session_id`、`tenant`、`started_at` |
| `Brief` | `goal`、`context_refs`、`done`、`forbidden`、`deadline` |
| `Board` | `state`、`rev`、`owner` |
| `Route` | `name`、`accepts`、`fallback` |
| `RunResult` | `status`、`answer`、`state`、`usage`、`citations`、`pending`、`error` |

### 5.3 State 用信封

```python
@dataclass
class State:
    goal: Goal
    session: SessionRef
    data: dict[str, Any]       # 各策略自己的字段放命名空间
    trace: TraceContext
    status: RunStatus
```

- `data["react"]`、`data["pe"]`、`data["workflow"]` 各写各的；
- `RunResult` 单独返回，不塞进 State；
- `State` 必须可序列化，不能放连接、锁、客户端。

### 5.4 运行结果

```python
class RunStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    REFUSED = "refused"
    FAILED = "failed"
    NEEDS_APPROVAL = "needs_approval"
    CANCELLED = "cancelled"
```

调用方必须能区分这六种，不能都抛 `Exception`。

### 5.5 必须补齐的五个 Protocol

大纲的 11 个接口缺了五个组件：

```python
class Router(Protocol):
    def route(self, goal: Goal) -> Route: ...

class Guard(Protocol):
    def check(self, step: Step, state: State) -> GuardDecision: ...

class Delivery(Protocol):
    def finish(self, state: State) -> RunResult: ...

class Knowledge(Protocol):
    def retrieve(self, query: str, *, k: int, filters: dict) -> list[Recalled]: ...

class Skills(Protocol):
    def catalog(self) -> list[SkillMeta]: ...
    def load(self, name: str) -> SkillBody: ...
```

### 5.6 错误类型

```python
class HarnessError(Exception): ...
class BudgetExceeded(HarnessError): ...
class GuardDenied(HarnessError): ...
class ToolError(HarnessError): ...
class ReflectorReject(HarnessError): ...
class ApprovalExpired(HarnessError): ...
```

---

## 6. 开发一个 agent 的代码路径

### 6.1 最小 agent

```python
from harness import AgentConfig, Goal, build, tool
from harness.adapters.openai import OpenAIModel


@tool
def get_order(order_id: str) -> dict:
    """查询订单状态与签收时间。"""
    return {"order_id": order_id, "status": "已签收", "signed_days_ago": 3}


agent = build(AgentConfig(
    model=OpenAIModel("gpt-4.1-mini"),
    tools=[get_order],
    mode="react",
    budget={"tokens": 60_000, "calls": 20},
))

result = agent.run(Goal(text="订单 A1001 还能退吗？", user_id="u-1", session_id="s-1"))
print(result.status, result.answer)
```

### 6.2 RAG

```python
from harness.adapters.qdrant import QdrantKnowledge
from harness import AutoRetrieval, BudgetedContext, CitedDelivery

kb = QdrantKnowledge(url="http://localhost:6333", collection="docs_v1", embedder=...)
kb.ingest("./docs", chunker=MarkdownChunker(600, 80), metadata={"tenant": "acme"})

agent = build(AgentConfig(
    model=model,
    mode="react",
    knowledge=kb,
    retrieval=AutoRetrieval(k=6, query_from="goal", when="first_step"),
    context=BudgetedContext(slots={"system": 0.1, "task": 0.2, "memory": 0.2, "retrieved": 0.5}),
    delivery=CitedDelivery(),
))
```

或者把检索做成工具：

```python
@tool
def search_docs(query: str) -> list[dict]:
    """检索内部文档；只在需要政策、条款、历史记录时调用。"""
    return [r.as_dict() for r in kb.retrieve(query, k=6, filters={"tenant": "acme"})]
```

### 6.3 人工审批

```python
class RefundApproval:
    def check(self, step, state):
        if step.tool_name == "refund" and step.args["amount"] > 1000:
            return GuardDecision.ask(
                reason="单笔退款超过 1000 元",
                card={"order_id": step.args["order_id"], "amount": step.args["amount"],
                      "impact": "将调用退款接口，资金不可逆"},
                expires_in=86400,
            )
        return GuardDecision.allow()


agent = build(AgentConfig(..., guard=RefundApproval(), durability=SQLiteDurability("runs.db")))
result = agent.run(goal)

if result.status is RunStatus.NEEDS_APPROVAL:
    result = agent.resume(result.pending.id, Decision.approve(by="alice"))
    # Decision.reject(...) / Decision.modify({"amount": 800}, by="alice")
```

### 6.4 记忆与恢复

```python
from harness.adapters.sqlite import SQLiteMemory
from harness import MemoryPolicy, SessionRef

agent = build(AgentConfig(
    memory=SQLiteMemory("memory.db", tenant="acme"),
    memory_policy=MemoryPolicy(
        recall_layers=["semantic", "episodic"],
        recall_k=6,
        write_on="run_end",
        write_sources=["user_preference", "feedback", "confirmed_fact"],
    ),
    durability=SQLiteDurability("runs.db"),
    context=BudgetedContext(slots={"memory": 0.2, ...}),
))

session = SessionRef(session_id="s-1", tenant="acme")
result = agent.run(goal, session=session)
result = agent.resume("s-1")     # 进程重启后
```

### 6.5 Skills

```python
from harness.skills import SkillRegistry, SkillPolicy

skills = SkillRegistry.from_dir("./skills")

# 目录常驻，模型按需 load_skill
agent = build(AgentConfig(
    model=model, tools=[...], skills=skills,
    skill_policy=SkillPolicy(mode="catalog", max_loaded=2, allow_tools=True),
))

# 或把 Skill 编译成固定工作流
agent = build(AgentConfig(
    mode="workflow",
    workflow=skills.as_workflow("refund-review"),
    model=model, tools=[...],
))
```

### 6.6 MCP

```python
from harness.adapters.mcp import MCPToolProvider

async with MCPToolProvider(command=["npx", "-y", "..."], namespace="fs", timeout=30) as mcp:
    tools = await mcp.tools()
    agent = build(AgentConfig(
        model=model, tools=tools,
        guard=MCPGuard(allowed=["fs.read_file", "fs.list_directory"]),
    ))
    result = await agent.run_async(goal)
```

### 6.7 多 agent

```python
from harness.topology import Supervisor, Handoff, Blackboard, Pipeline

team = Supervisor(
    workers={"research": build(cfg1), "analyze": build(cfg2), "write": build(cfg3)},
    planner=LLMPlanner(model),
    brief=lambda goal, step: Brief(goal=goal, context_refs=["doc:42"], done=[], forbidden=["改写原文"]),
    synth=merge_reports,
)

team = Handoff(agents=[triage, refund, human], router=LLMRouter(model))
team = Blackboard(agents=[...], reducer=append_findings, trigger=all_done)
team = Pipeline([parse, analyze, write])
```

嵌套：

```python
team = Supervisor(workers={
    "research": Pipeline([search, read, summarize]),
    "review": Handoff([reviewer, auditor]),
})
```

### 6.8 自定义 BodyPolicy / Topology

```python
class MyPolicy:
    def next_step(self, state):
        if state.data["custom"]["done"]:
            return Done()
        return Step(instruction="...", tool_name="my_tool")

agent = Agent(policy=MyPolicy(), model=model, tools=[...])

class Debate:
    def run(self, goal) -> RunResult: ...
```

### 6.9 测试

```python
from harness.testing import FakeModel, FakeTool

agent = build(AgentConfig(
    model=FakeModel(["调用 get_order", "最终答复"]),
    tools=[FakeTool("get_order", {"status": "已签收"})],
    mode="react",
))
assert agent.run(goal).status is RunStatus.COMPLETED
```

---

## 7. 场景清单

| # | 场景 | 配置落点 | 不做的后果 | 验证 |
|---|---|---|---|---|
| 1 | 普通工具调用 | `tools` + `mode=react` | 模型只说不做 | 一次工具往返 |
| 2 | RAG（自动检索） | `knowledge` + `AutoRetrieval` + `Context.retrieved` | 答政策问题无依据 | 引用可回溯 |
| 3 | RAG（工具检索） | `@tool search_docs` | 模型可能忘记检索 | 工具被调用 |
| 4 | 分派到 RAG/普通 | `Router` + `Route` | 简单问题也走贵路径 | 路由命中率 |
| 5 | 人工审批 | `Guard.ask` + `Durability` + `resume` | 重启丢审批、重复副作用 | 恢复不重复 |
| 6 | 转人工 | `Handoff(to_human)` | 把审批当转人工，责任不清 | 交接单完整 |
| 7 | 跨会话记忆 | `Memory` + `MemoryPolicy` | 每次从零开始 | 偏好能被召回 |
| 8 | 断点续跑 | `Durability` + `idem_key` | 崩一次重来 | 重启后继续 |
| 9 | Skills 目录 | `SkillRegistry` + `SkillPolicy` | 提示词越写越长 | 按需加载 |
| 10 | Skills 工作流 | `skills.as_workflow()` | 固定流程被模型改序 | 步骤顺序固定 |
| 11 | MCP 工具 | `MCPToolProvider` + `Guard` | 工具重名、越权、断线 | 命名空间与 allowlist |
| 12 | 多 agent | `Topology` | 上下文转述失真、写冲突 | 替换实验 |
| 13 | 流式输出 | `agent.stream()` / `Delivery` | 首段可见性差、断线丢结果 | 断线重连 |
| 14 | 取消/超时 | `CancellationToken` | 用户点停止后仍在花钱 | 取消后无副作用 |
| 15 | 重试/幂等 | `Resilience` + `idem_key` | 重复发邮件/退款 | 重放测试 |
| 16 | 安全边界 | `Guard` + 沙箱 + 数据区 | 提示词注入、路径穿越 | 攻击用例 |
| 17 | 多租户 | 凭据推导 + `tenant` 过滤 | 读到别人数据 | 跨租户测试 |
| 18 | 成本/降级 | `Budget` + `Delivery.degraded` | 预算耗尽当失败 | 降级交付 |
| 19 | 可观测 | `Tracer` 的 `trace_id`/`parent_id` | 跨 agent 串不起来 | trace 树 |
| 20 | 评测/门禁 | 离线 eval | 改动无法证明变好 | 区间与回归 |
| 21 | 版本/迁移 | `contracts_version` + checkpoint 版本 | 旧 run 读不出 | 旧数据回放 |
| 22 | 拓扑嵌套 | Topology 实现 Runnable | 不能套娃 | 嵌套运行 |
| 23 | Skill/MCP 冲突 | 优先级 + 命名空间 + allowlist | 工具被覆盖 | 冲突用例 |
| 24 | 失败分类 | `RunStatus` 六态 | 调用方只能盲重试 | 状态断言 |

---

## 8. 注意事项（按场景）

### RAG

- 检索结果放**数据区**，不放进 system 指令区；防间接注入。
- 引用编号由 `Delivery` 生成，`Reflector` 校验；没有引用的 RAG 回答不可复盘。
- `Knowledge` 只按分数返回候选，`Context` 决定放几条；不要把 `k` 写死在检索层。
- 换嵌入/切块参数时建新 collection，不原地改旧索引。

### 人工审批

- 必须配 `Durability`；审批可能等几天，不能挂线程。
- 审批卡片要写**影响面**：订单号、金额、调用哪个接口、是否可逆。
- `expires_in` 到期自动拒绝；`resume` 要能返回 `ApprovalExpired`。
- 恢复会重放，执行步骤必须带 `idem_key`；审批通过不等于副作用只发生一次。

### 记忆与持久化

- `Memory` 是跨会话的长期数据；`Durability` 是一次运行的检查点；`State` 是当前字段。三者不能混。
- 不要写原始对话；写抽取后的偏好、事实、经验，并带 `source`/`age_days`。
- 记忆要能按用户/租户删除；软删除 + 定期清理。
- `State` 必须可序列化；连接、锁、客户端不能进 State。

### Skills

- 工具收窄靠 `allowed-tools` 交集，不靠提示词。
- 只有 `SKILL.md` 的 Skill 不能 `as_workflow()`；不能把散文假装编译成步骤。
- 多个 Skill 命中要有优先级规则；Skill 版本变更要能回滚。
- `catalog` 模式正文按需加载，`workflow` 模式只加载当前步骤需要的资源。

### MCP

- 工具名加 `server.` 前缀，防重名。
- MCP server 是不可信输入：schema 校验、allowlist、超时、断线重连。
- 不要手写 MCP 工具 schema；用 `tools()` 发现。
- 连接生命周期用 `async with`；不要让连接漏进 Actor。

### 多 agent

- `Brief` 必须带原始依据（`context_refs`），不能只带结论。
- `Board` 写回增量，不是整份快照；否则并发丢数据。
- 预算共享还是分开要显式：`scope="run"` 防超支，`scope="agent"` 防单 agent 饿死。
- `Topology` 只依赖 `Agent`/`State`/`Board`/`Brief`，不 import 组件。
- 拓扑嵌套时，`trace_id`、预算、失败隔离要能继承/隔离。

### 流式、取消、长任务

- 流式只改变交付，不改变总耗时；断线不等于取消。
- 取消要传 `CancellationToken`；取消后检查副作用是否已发生。
- 长任务用队列 + `Durability`；worker 不持有等待中的审批。

### 安全与多租户

- 租户从凭据推导，不从请求体声明；`Knowledge`/`Memory`/`Tracer` 都要带 tenant 过滤。
- 路径安全：`resolve()` 后判前缀，不能只做字符串前缀。
- 工具/检索/MCP 的返回值都按不可信数据处理。

### 成本、观测、评测

- `Budget` 是共享资源；按 `Pack` 扣，不按原始召回扣。
- `Tracer` 要有 `trace_id`/`parent_id`；跨 agent 才能串。
- 评测在离线做；`Reflector` 只做在线校验，不能替代评测集。
- 事故要变成回归用例；门禁看区间，不只看单点通过率。

### 版本与失败分类

- `contracts_version`、checkpoint schema 版本、prompt/model/tool/skill 版本都要进 trace。
- `RunStatus` 六态要区分：完成、降级、拒绝、失败、待审批、已取消。
- 旧 run 必须能读；不能读时要显式拒绝，不能猜。

---

## 9. 开发顺序与完成标准

| 阶段 | 交付 | 完成标准 |
|---|---|---|
| 0 | `contracts.py`、`state.py`、`result.py`、`errors.py`、`testing/` | 类型可导入；FakeModel 能跑；无第三方依赖 |
| 1 | `agent.py` + `ReactPolicy` + 最小 example | 20 行跑通一次工具调用；离线测试通过 |
| 2 | `Guard`、`Budget`、`Tracer`、`Durability`、`Reflector`、`Delivery` | 四类失控各拦一次；预算耗尽降级；重启恢复 |
| 3 | `Router`、`Context`、`Knowledge`、`Memory`、`Skills` | RAG 引用可回溯；记忆可召回；Skill 按需加载 |
| 4 | `WorkflowPolicy`、`PlanExecutePolicy`、`Planner` | Workflow 固定顺序；P&E 计划可审查；配置非法组合被拒 |
| 5 | `Topology` 四种 + 嵌套 | 换拓扑不改组件；替换实验只消失一件事 |
| 6 | `build/`、`examples/`、`adapters/`、文档 | 六例只改配置；`pip install -e .`；API 文档齐全 |

每阶段的 DoD 都是四件：**示例能跑 + 离线单测 + 一次替换实验 + 一页 API 文档**。

---

## 10. 与书稿 48–53 的映射

| 章 | 代码 | 正文要证明的事 |
|---|---|---|
| 48 | 包骨架 + 耦合反例 | 没有基座时，换模型/加 Guard 要改多少文件 |
| 49 | `contracts.py` | 四层之间只传契约；类型与 Protocol 冻结 |
| 50 | `body/`、`dispatch/`、`actor/tools/context/resilience` | 三种 BodyPolicy + 执行原语；Planner 只在 PE |
| 51 | `verify/`、`governance/`、`supply/`、`delivery/` | 治理/供给/交付是横切，不新增层 |
| 52 | `build/`、`examples/` | 六例只改 `build(cfg)`，组件不改 |
| 53 | `topology/` | 换拓扑只改组合，组件不改；四拓扑可嵌套 |

**注意**：书稿章节仍按大纲 48–53；代码按本文的运行时分组，不按四层建目录。

---

## 11. 未决问题（下次会话先定）

1. **sync 还是 async 为核心？** 建议 async 核心 + sync 包装；这决定所有 Protocol 签名。
2. **库还是模板仓库？** 库用 `pip install -e .`；模板是复制走再改。两者目录与升级方式不同。
3. **公开 API 只暴露 6 个，还是 15 个都公开？** 建议只承诺 `build`/`Agent`/`Goal`/`Tool`/`Guard`/`Reflector`/`Tracer`/`Topology`。
4. **默认持久化后端？** 建议 SQLite（零依赖）；Postgres/Redis 作为 extras。
5. **MCP/Skills 是核心还是 extras？** 建议接口在核心，实现放 extras。
6. **包名/版本？** 建议 `agent-harness`，从 `0.1.0` 开始，`contracts_version` 独立。

---

## 12. 开工前检查清单

- [ ] 读 `outline/20-副线封装推导.md` 的 5.0–5.9。
- [ ] 读 `outline/vol12-组件封装.md` 与 `docs/PLAN-ARCH.md` 的 52/53 部分。
- [ ] 确认第 11 节六个未决问题。
- [ ] 建 `code/harness/` 与 `pyproject.toml`。
- [ ] 先写 `contracts.py` + `FakeModel` + 一个失败测试，再写 `Agent`。
- [ ] 每个组件先写 Protocol，再写实现，再写替换实验。
- [ ] 本章正文只引用包里的代码，不另写一份示例。

---

## 13. 写作纪律（卷 12 第 48–53 章）

代码不是“写完再补文章”，每阶段结束就写对应章节：

| 阶段 | 对应章 | 写作前提 |
|---|---|---|
| Phase 0–1 | 48、49 | 契约与最小 Agent 已跑通；49 章引用 `contracts.py` 真实代码 |
| Phase 2 | 50 | ReAct/Workflow + Guard/Budget/Tracer/Durability 跑通 |
| Phase 3 | 51 | RAG/Memory/Skills 至少各有一个可运行实现 |
| Phase 4 | 52 | `build(cfg)` 的判别联合与三个完整装配例 |
| Phase 5–6 | 53 | 四种拓扑可嵌套；替换实验通过 |

三条硬规则：

1. **章节代码块只来自 `code/harness/src/`**，不另写一份“书里的示例”。
2. **没有离线测试的组件不写进正文**；正文里的输出必须逐字来自脚本运行。
3. **每章“这一章建立的 N 件事”必须有一句主线没有的判断**：
   - 48：没有基座时，耦合的代价可以数出来；
   - 49：契约不是类型表，是“换掉一个组件只消失一件事”的前提；
   - 50：Planner 只属于 P&E，三种 BodyPolicy 不能共用同一个构造；
   - 51：治理/供给/交付不是第五层，它们挂在插点上；
   - 52：六个例子只改 `build(cfg)`，组件一行不改；
   - 53：拓扑只组合 `Agent`，不实现能力。

**先写 48/49**：这两章只依赖已完成的契约与最小循环，不必等 P&E 和拓扑。50 章等 Phase 2，51 章等 Phase 3，52/53 最后写。

---

## 14. 一句话交接

**先定契约与运行时，再写组件；先让一个 PDF 例子跑通，再证明换配置、换组件、换拓扑都只改一处。** 基座的目标不是“组件很多”，是“下一个项目只写工具和配置”。
