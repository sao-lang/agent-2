# 第 52 章 · 装配与验证：build 与五个预设六个例子

> **卷 12 · 组件封装（副线）（第 48–53 章）**｜[全书目录](./docs/INDEX.md#vol12)｜[本卷导读](./outline/vol12-组件封装.md)
>
> - **知识点**：无（本章只建立全书的地图，不承载 A–G 中的任何一条）
> - **本章回答**：为什么 `build(cfg)` 是唯一实例化处；五个预设各自装什么；六个例子怎么做到只改配置；非法组合与替换实验怎么验
> - **示例目录**：`code/harness/examples/assembly.py`（基座包在 `code/harness/src/harness/`）
> - **读完应当能回答**：给一个项目，选哪个预设；新增一个例子要改哪些字段；为什么不能在业务代码里 `new Guard`

---

## 目录

[一、build 是唯一实例化处](#一build-是唯一实例化处)\
[二、五个预设](#二五个预设)\
[三、六个例子](#三六个例子)\
[四、配置字段表](#四配置字段表)\
[五、装配顺序](#五装配顺序)\
[六、非法组合](#六非法组合)\
[七、替换实验](#七替换实验)\
[八、测试](#八测试)\
[九、会怎么坏](#九会怎么坏)\
[十、边界](#十边界)\
[这一章建立的 7 件事](#这一章建立的-7-件事)

## 一、build 是唯一实例化处

第 48–51 章把组件讲完了。现在的问题是：这些组件谁来 `new`？

如果让业务代码自己 `new`：

```python
agent = Agent(
    policy=ReactPolicy(max_steps=8),
    actor=Actor(model=OpenAI(...), tools=ToolRegistry().add(...)),
    context=BudgetedContext(...),
    guard=RefundGuard(...),
    budget=Budget(...),
    tracer=JsonlTracer(...),
    durability=SQLiteDurability(...),
    delivery=DefaultDelivery(),
    reflector=CitationReflector(),
)
```

这段代码有四个问题：

1. 业务代码要知道九个组件的构造顺序；
2. 换一个组件要改业务代码；
3. 非法组合只能在运行时发现；
4. 每个项目都复制一遍这段装配，最后各不相同。

基座的解法是 `build(cfg)`：**唯一实例化处**。业务代码只填配置，不碰组件构造。

```python
agent = build(AgentConfig(
    model=model,
    tools=[get_order, check_policy],
    mode="react",
    guard=RefundGuard(),
    budget=Budget(tokens=60_000, calls=20),
))
```

`build` 做四件事：

1. 校验配置组合；
2. 把工具列表变成 `ToolRegistry`；
3. 按 `mode` 构造 `BodyPolicy`；
4. 把组件注入 `Agent`。

这四件事只在一个地方发生。换组件、加默认值、改构造顺序，都只改 `build`，不改业务代码。

### 1.1 为什么不是工厂模式

`build` 看起来像一个工厂，但它不是“工厂模式”。

工厂模式通常有：

- 一个工厂接口；
- 多个具体工厂；
- 产品族。

基座没有“工厂接口”，只有 `build(cfg)`；也没有“产品族”，只有一个 `Agent`。它不做“创建哪一类产品”的决策，只做“按配置装配同一个产品”。

这个区别很重要：工厂模式会鼓励“为每种配置写一个工厂”，最后得到 `MinimalFactory`、`ProductionFactory`、`RagFactory`；基座只需要一个 `build`，加几个预设函数。

`build` 的职责是“把配置翻译成对象图”，不是“决定用哪种架构”。架构选择在第 47 章，配置表达在 `AgentConfig`，构造在 `build`。三者分开，才不会把选型写进代码。

### 1.2 build 与 main 的分工

`build` 不是 `main`。两者的职责要分开。

`main` 做：

- 读环境变量/配置文件；
- 构造具体适配器（模型客户端、数据库连接）；
- 调 `build(cfg)`；
- 启动服务/跑一次任务。

`build` 做：

- 校验配置；
- 按配置装配组件；
- 返回 `Agent`。

`main` 可以有副作用，`build` 不能。`build` 可以在测试里反复调用，`main` 不能。

这个分工让“配置错误”在 `build` 暴露，“环境错误”在 `main` 暴露。两者分开，测试不需要 mock 环境。

**build 是纯函数，main 是入口。** 混在一起，测试就要连真实环境。

### 1.3 build 的签名

`build` 的签名只有两个东西：`AgentConfig` 与返回值。

```python
def build(config: AgentConfig) -> Agent: ...
```

它不接收 `**kwargs`，不接收 `None`，不接收“部分配置”。所有字段在 `AgentConfig` 里，所有默认值在 dataclass 里。

原因：

- 签名稳定：加字段不改 `build`；
- 类型明确：静态检查器能查字段；
- 测试简单：构造一个配置对象即可。

如果 `build` 接受 `**kwargs`，用户会传任意键，类型检查失效，非法字段只能运行时发现。**装配入口越窄，配置越可测。**

## 二、五个预设

预设不是“另一套实现”，只是 `AgentConfig` 的简写。五个预设覆盖五种规模。

### 2.1 minimal

```python
def build_minimal(*, model, tools=None, **kwargs):
    return build(AgentConfig(model=model, tools=list(tools or []), mode="react", **kwargs))
```

最小形态：一个模型、零个或多个工具、默认 Guard/Budget/Tracer/Durability/Delivery。适合 hello world 与单测。

### 2.2 react

```python
def build_react(*, model, tools=None, budget=None, tracer=None, guard=None,
                durability=None, **kwargs):
    return build(AgentConfig(..., mode="react", ...))
```

循环形态：多了预算、轨迹、Guard、恢复。适合开放任务、工具调用。

### 2.3 workflow

```python
def build_workflow(*, model, workflow, tools=None, **kwargs):
    return build(AgentConfig(..., mode="workflow", workflow=list(workflow), ...))
```

工作流形态：步骤写死，模型只出现在 LLM 步骤。适合固定流程、合规审批。

### 2.4 pe

```python
def build_pe(*, model, planner, tools=None, **kwargs):
    return build(AgentConfig(..., mode="pe", planner=planner, ...))
```

计划形态：先产出一份 `Plan`，再逐步执行。适合步骤可计划、需要审查的任务。

### 2.5 production

```python
def build_production(*, model, tools=None, guard, budget, tracer, durability,
                     delivery=None, reflector=None, knowledge=None,
                     retrieval=None, memory=None, memory_policy=None, **kwargs):
    return build(AgentConfig(..., mode="react", ...))
```

生产形态：治理五件、检索、记忆、校验都挂上。适合真实项目。

五个预设的差别只在“装哪些件”，不在“组件实现”。`build_production` 不是另一个 `Agent`，它只是字段更多的 `AgentConfig`。

### 2.6 预设的边界

预设最有用的地方，是给读者一个“从这里开始”的默认路径；最危险的地方，是变成“必须从这里开始”的框架。

三个边界：

**第一，预设不是唯一入口。** 用户可以不用 `build_react`，直接 `build(AgentConfig(...))`；预设只是简写，不是权限。

**第二，预设不隐藏关键决策。** `build_production` 仍然要求用户传 `guard`/`budget`/`tracer`/`durability`；它不替用户选“默认生产配置”。生产配置因业务而异，预设不能假装知道。

**第三，预设不承诺稳定。** 预设是便利函数，可以随版本调整；真正稳定的契约是 `AgentConfig` 与 `build`。如果用户把预设当 API，升级时会痛。

预设的数量也要控制。五个覆盖“最小、循环、工作流、计划、生产”；再加就会变成“每个项目一个预设”，那不是预设，是复制。

**预设的价值是“少想几个字段”，不是“不用想”。** 关键决策仍然要用户填。

### 2.7 预设的组合

五个预设不是互斥的，可以组合。

- `build_react` + `build_production` 的治理字段 = 生产版 ReAct；
- `build_workflow` + `build_production` 的检索 = 带 RAG 的固定流程；
- `build_pe` + `build_production` 的审批 = 带人工审批的计划执行。

组合的方式不是“继承预设”，是“把字段传进去”。预设函数只做“补默认值”，不做“组合逻辑”；组合逻辑在 `AgentConfig`。

如果预设之间开始互相调用（`build_production` 调 `build_react`），会出现“改一个预设影响另一个”的隐藏耦合。正确做法是让所有预设都调用同一个 `build`，只是传入的字段不同。

**预设是配置的简写，不是配置的层级。** 简写可以组合，层级不能。

### 2.8 预设的默认值

五个预设的默认值不一样，这是有意的。

- `build_minimal` 不设预算、不设轨迹；它追求“最少字段能跑”。
- `build_react` 设预算与轨迹，但不设 Guard；它追求“能看住成本”。
- `build_workflow` 不设 Planner；它追求“步骤确定”。
- `build_pe` 必须给 Planner；它追求“计划可审查”。
- `build_production` 必须给 Guard/Budget/Tracer/Durability；它追求“能上线”。

默认值不是“随便选”，是“这个预设的最小生产形态”。`build_production` 不替用户选 Guard，因为 Guard 是业务规则；但它要求用户显式给，不能默认 `AllowAll`。

**预设的默认值，表达的是“这个形态最低限度要什么”。** 读者看到默认值，就知道自己还缺什么。

### 2.9 预设的参数传递

预设函数的 `**kwargs` 是便利，也是风险。

好处：用户可以传任意 `AgentConfig` 字段，不用预设重复列一遍。

风险：类型检查失效，非法字段不会在调用时暴露；用户传了 `planner` 给 `build_react`，要到 `build` 才报错。

折中：预设函数显式列出常用字段，`**kwargs` 只用于高级字段；高级字段在 `build` 里统一校验。

```python
def build_react(*, model, tools=None, budget=None, tracer=None, guard=None,
                durability=None, **kwargs):
    ...
```

这样常用字段有类型提示，高级字段仍可传；非法组合由 `build` 兜底。

**便利与约束不是二选一。** 常用路径显式，罕用路径开放，是配置 API 的常见取舍。

### 2.10 预设的版本

预设是便利函数，不承诺稳定；但“不承诺”不等于“可以随便改”。

三条兼容规则：

- 加字段给默认值，旧调用仍可跑；
- 删除字段先弃用，保留一个版本；
- 改默认值要写迁移说明，并在 trace 里记录版本。

预设的版本可以跟包版本走；`contracts_version` 只管类型与协议，不管预设。两者分开，避免“改一个预设就升契约版本”。

**预设可以演进，契约必须稳定。** 读者可以跟着预设升级，但不应被预设锁死。

### 2.11 预设的文档

每个预设的文档只写三行：

```text
用途：最小可运行
必填：model
默认：mode=react，其余空实现
```

不要写“本预设采用先进的 ReAct 架构”这类话。读者只关心：什么时候用、要给什么、默认装了什么。

预设文档还要给“下一步”：从 `build_minimal` 到 `build_react` 加什么字段，从 `build_react` 到 `build_production` 加什么。读者才知道怎么升级。

**文档的价值是“下一步”，不是“本页有什么”。**

## 三、六个例子

六个例子不是六份代码，是六份配置。前三个完整，后三个只给差异。

### 3.1 例子一：最小问答

```python
agent = build_minimal(model=FakeModel([answer("hello")]))
result = await agent.run(Goal("hi", session_id="min"))
```

输出：

```text
completed hello
```

它验证的是：没有工具、没有检索、没有审批，循环仍然能跑通；默认组件都有合理的空实现。

### 3.2 例子二：ReAct + 工具

```python
agent = build_react(
    model=FakeModel([tool_call("concat", left="a", right="b"), answer("ab")]),
    tools=[concat],
    budget=Budget(tokens=1000, calls=4),
)
```

输出：

```text
completed ab
```

它验证的是：工具调用、结果回灌、预算扣减、终止判断四段都在。

### 3.3 例子三：Workflow

```python
agent = build_workflow(
    model=FakeModel([answer("unused")]),
    tools=[concat],
    workflow=[
        Step(id="a", tool_name="concat", args={"left": "a", "right": "b"}),
        Step(id="b", tool_name="concat", args={"left": "c", "right": "d"}),
    ],
)
```

输出：

```text
completed cd
```

它验证的是：步骤按顺序执行，模型不参与决策；`state.data["workflow_index"]` 递增到 2。

### 3.4 例子四：P&E

```python
plan = Plan(id="p1", steps=[...])
agent = build_pe(model=FakeModel([answer("unused")]),
                 planner=ScriptedPlanner(plan), tools=[concat])
```

输出：

```text
completed cd
```

它验证的是：`Plan` 被执行、`plan_id` 可追溯、`index` 到 2；Planner 只出现在 P&E 配置里。

### 3.5 例子五：production（RAG + 治理）

```python
agent = build_production(
    model=FakeModel([tool_call("get_order", order_id="A1001"), answer("已签收")]),
    tools=[get_order],
    guard=AllowAllGuard(),
    budget=Budget(tokens=2000, calls=4),
    tracer=tracer,
    durability=MemoryDurability(),
    knowledge=kb,
    retrieval=AutoRetrieval(k=1),
)
```

输出：

```text
completed 已签收 events= 4
```

它验证的是：检索、工具、预算、轨迹、恢复同时挂上，输出仍是 `RunResult`，没有多一层“生产专用 API”。

### 3.6 例子六：只改配置

第六个例子是“同一套组件，换业务”。比如把 `get_order` 换成 `search_docs`，把 `RefundGuard` 换成 `PiiGuard`，把 `Budget(2000)` 换成 `Budget(60000)`；`Agent`、`Actor`、`Context`、`Delivery` 一行不改。

```python
# 例子五 -> 例子六：只改 build 的参数
agent = build_production(
    model=model,
    tools=[search_docs],          # 换工具
    guard=PiiGuard(),             # 换 Guard
    budget=Budget(tokens=60_000, calls=30),
    tracer=JsonlTracer("runs.jsonl"),
    durability=SQLiteDurability("runs.db"),
    knowledge=kb,
    retrieval=AutoRetrieval(k=6),
)
```

验收句：**换一个例子，只改 `build` 的参数；如果改了组件代码，就是耦合。**

### 3.7 六个例子的共同点

六个例子看起来不同，它们的结构完全一样：

```text
Goal -> Agent -> BodyPolicy -> Actor -> Tools -> ActionResult -> Delivery
```

差别只有四个：

- **BodyPolicy**：react / workflow / pe；
- **Tools**：concat / get_order / search_docs；
- **治理**：AllowAll / RefundGuard / PiiGuard；
- **供给**：无 / Knowledge / Memory。

四个差别都在 `AgentConfig` 里，没有一个在 `Agent` 的循环里。这就是装配层的验收：**例子之间的差异，应该全部落在配置上。**

如果第六个例子需要改 `Agent`、`Actor` 或 `Delivery`，说明前五个例子的抽象不够，或者第六个例子引入了新契约。新契约可以加，但要先证明它不能由现有字段表达。

六个例子的数量也有讲究。少于三个，证明不了“只改配置”；多于六个，读者记不住。三个完整 + 三个差异，是“可验证”与“可读”的平衡。

### 3.8 例子的代码结构

六个例子的代码结构应该完全一样：

```text
1. 定义工具
2. 定义模型（或 FakeModel）
3. 构造 AgentConfig
4. build(cfg)
5. run(goal)
6. 断言 status/answer
```

差异只在第 3 步。如果某个例子在第 1 步定义了新的 `Tool` 基类，或在第 4 步之后改了 `Agent` 的字段，它就脱离了“只改配置”的验收。

例子不是文档，是可执行测试。每个例子都应该能被测试直接调用，而不是“复制到 main 里跑一下”。

**例子的价值，是让读者看到“同一个骨架，不同配置”；不是让读者看到“六种不同写法”。**

### 3.9 例子的验收

六个例子要通过三条验收。

**第一条：能跑。** 每个例子都能独立运行，输出 `RunStatus` 与答案；不依赖网络、不依赖真实模型。

**第二条：只改配置。** 六个例子共用同一套 `contracts.py` 与组件实现；差异只在 `build(cfg)` 的参数。测试可以断言“组件类没有被重新定义”。

**第三条：能解释。** 每个例子要能回答“为什么用这个 mode、这个 Guard、这个预算”。只跑通不解释，读者抄了也不知道什么时候该换。

三条验收对应三种价值：可运行、可复用、可迁移。缺一条，例子就只是演示。

### 3.10 例子与测试

六个例子应该被测试直接引用，而不是复制到测试里。

```python
from examples.assembly import example_minimal, example_react
```

例子函数返回 `RunResult`，测试断言 `status` 与关键字段。这样例子改了，测试跟着跑；不会出现“文档里的例子早就过期”。

例子函数不要 `print`，也不要 `asyncio.run`；它们只构造、运行、返回。打印与入口放在 `main` 里。

**例子是可执行文档，测试是例子的守卫。** 两者分开写，例子一定会腐烂。

### 3.11 例子的目录

例子目录按“形态”分，不按“业务”分。

```text
examples/
├── minimal.py
├── react.py
├── workflow.py
├── pe.py
├── production.py
└── assembly.py      # 一次跑五个，用于演示
```

按业务分（`refund.py`、`research.py`）会让读者以为“每种业务要一套代码”；按形态分，读者看到“同一个骨架，不同配置”。

业务例子可以放在应用仓库，不必放进基座。基座只保留“形态例子”，证明配置能表达差异。

## 四、配置字段表

`AgentConfig` 的字段不多，但要分清“必填、常用、高级”。

| 字段 | 类别 | 默认值 | 什么时候必须改 |
|---|---|---|---|
| `model` | 必填 | 无 | 永远 |
| `tools` | 常用 | `[]` | 需要外部动作 |
| `mode` | 常用 | `react` | 任务形状变化 |
| `workflow` | 分支 | `None` | `mode=workflow` |
| `planner` | 分支 | `None` | `mode=pe` |
| `max_steps` | 常用 | `12` | 任务步数上限 |
| `system` | 常用 | `""` | 需要系统提示 |
| `guard` | 高级 | `AllowAll` | 生产必须换 |
| `budget` | 高级 | 默认上限 | 生产必须设 |
| `tracer` | 高级 | `Null` | 生产必须换 |
| `durability` | 高级 | `Null` | 长任务必须换 |
| `delivery` | 高级 | 默认 | 需要引用/脱敏 |
| `reflector` | 高级 | `Null` | 需要外部裁判 |
| `knowledge` | 高级 | `None` | 需要检索 |
| `retrieval` | 高级 | `None` | 需要自动检索 |
| `memory` | 高级 | `None` | 需要跨会话 |
| `memory_policy` | 高级 | `None` | 需要记忆策略 |
| `resilience` | 高级 | `None` | 需要超时/重试 |

“必填、常用、高级”不是装饰。它决定读者第一次用基座时要填几个字段。

最小可用只需要 `model`；加工具填 `tools`；加流程填 `mode`/`workflow`/`planner`；其余按需。**如果读者第一次用就要填十八个字段，说明默认值没设计好。**

默认值也有语义：

- `guard=AllowAll` 是“显式允许所有动作”，不是“没有 Guard”；
- `tracer=Null` 是“显式不记录”，不是“没有观测”；
- `durability=Null` 是“显式不恢复”，不是“没有持久化”。

显式空实现比“没有这个字段”好：读者知道自己关掉了什么，也知道怎么打开。

### 4.1 配置的三种读法

同一份 `AgentConfig`，三种读者看的东西不同。

**使用者**看“必填 + 常用”：`model`、`tools`、`mode`、`max_steps`。他只关心怎么跑起来。

**替换者**看“高级”：`guard`、`budget`、`tracer`、`durability`、`delivery`、`reflector`、`knowledge`、`memory`。他关心换哪个组件、影响哪一段。

**维护者**看“分支”：`workflow`、`planner`、`mode` 的组合。他关心非法组合与默认值。

配置文档应该按这三种读法组织，而不是按字母表。按字母表排，使用者要读完十八个字段才知道哪个必填；按读法排，第一次用只看前五个。

**配置的复杂度不在字段数，在读者要不要一次理解全部。** 好的配置让使用者只读五个字段，替换者再读其余。

### 4.2 配置与代码的边界

配置能表达“装哪些件”，不能表达“怎么执行”。这条边界经常被越过。

能放配置的：

- 选哪个 `mode`；
- 用哪个 `guard`/`budget`/`tracer`；
- 工具的列表；
- 最大步数；
- 检索的 `k`。

不能放配置的：

- 业务规则的具体判断（`if amount > 1000`）；
- 工具的实现；
- 提示词模板的拼接逻辑；
- 重试的具体算法。

业务规则放配置，配置会变成一门 DSL；工具实现放配置，配置会变成代码；提示词拼接放配置，配置会变成模板引擎。

**配置是选择，代码是执行。** 选择可以外置，执行不能。

### 4.3 默认值的测试

默认值不是文档，是测试。

三条默认值测试：

- `AgentConfig(model=...)` 不传 `mode`，`agent.policy` 是 `ReactPolicy`；
- 不传 `max_steps`，`agent.max_steps == 12`；
- 不传 `guard`，`agent.guard` 是 `AllowAllGuard`，不是 `None`。

第三条最重要：默认 Guard 必须是显式对象，不能是 `None`。`None` 会让循环在 `guard.check` 时崩溃；显式 `AllowAll` 让“没有配置”和“配置了放行”可区分。

**默认值测试，测的是“没有配置时系统仍然一致”。** 没有这条测试，默认值迟早会变成 `None`。

## 五、装配顺序

`build(cfg)` 内部的顺序是固定的，不能随意调。

```text
1. 校验配置
2. 构造 ToolRegistry
3. 构造 Actor
4. 按 mode 构造 BodyPolicy
5. 构造 Context
6. 构造 Agent，注入治理/供给
```

四个顺序约束：

**约束一：先校验，后构造。** 非法组合要在构造任何对象之前拒绝；否则会留下半成品对象。

**约束二：先工具，后 Actor。** `Actor` 需要 `ToolRegistry`；工具重名要在构造 Actor 之前报错。

**约束三：先策略，后 Agent。** `Agent` 需要 `policy`；策略构造失败要直接抛出，不能构造一个没有策略的 Agent。

**约束四：治理/供给最后注入。** 它们不影响策略构造，但影响 Agent 的字段；放在最后，构造顺序最清晰。

这个顺序不是“实现细节”，是失败语义：配置错在第一步报，工具错在第二步报，策略错在第四步报；每一步的错误都能定位到具体字段。

### 5.1 构造顺序的失败

顺序错了，会出现三种“半成品”。

**第一种：先构造 Agent，后构造策略。** `Agent` 需要一个 `policy`，只能先传 `None`，再补；补的时候如果策略构造失败，`Agent` 已经存在，调用方拿到一个不能用的对象。

**第二种：先构造 Actor，后构造工具。** `Actor` 需要一个 `ToolRegistry`，只能先传空表，再注册；注册失败时，`Actor` 已经持有空表，错误要等到执行才暴露。

**第三种：先构造治理，后校验配置。** 配置非法时，Guard/Tracer 已经构造，可能已经连了外部服务；再抛错，连接泄漏。

三种半成品的共同点是“错误发生得太晚”。构造顺序的目标不是“代码好看”，是“错误尽早、对象要么完整要么不存在”。

**要么完整，要么不存在。** 这是装配层的事务性：`build` 失败时，不返回半成品对象。

### 5.2 构造的依赖图

`build` 的依赖图是单向的：

```text
AgentConfig
  ├── Model
  ├── ToolRegistry <- Tools
  ├── Actor <- Model + ToolRegistry + Resilience
  ├── BodyPolicy <- Mode + (Workflow | Planner)
  ├── Context
  └── Agent <- Actor + BodyPolicy + Context + 治理/供给
```

箭头只能向下，不能向上。`Model` 不知道 `Actor`，`ToolRegistry` 不知道 `Agent`，`BodyPolicy` 不知道 `Delivery`。

依赖图的价值是回答“谁可以先构造”。`Model` 和 `Tools` 最先，`Actor` 次之，`BodyPolicy` 再次，`Agent` 最后。任何反向依赖都说明组件边界破了。

如果 `BodyPolicy` 需要 `Delivery` 来构造，说明策略在决定“怎么交回”，那是出口的事；如果 `Actor` 需要 `Agent`，说明执行器在回调循环，那是循环的事。

**依赖图是装配层的设计图；图画不出来，`build` 一定写不清。**

### 5.3 构造顺序与测试

构造顺序可以用对象图测试固定下来。

```python
agent = build(cfg)
assert isinstance(agent.policy, ReactPolicy)
assert isinstance(agent.actor, Actor)
assert agent.actor.tools is not None
assert agent.budget is not None
```

四条断言对应四个构造阶段。少一条，构造顺序就可能被改坏而没人发现。

对象图测试不需要运行循环，构造完就能断言；它是装配层最快的测试。

## 六、非法组合

`build` 的另一个职责是拒绝非法组合。最典型的是 `mode` 与 `planner`：

```python
if config.mode == "pe":
    if config.planner is None:
        raise ConfigError("mode=pe 需要 planner")
elif config.mode == "react":
    if config.planner is not None:
        raise ConfigError("mode=react 不允许 planner")
elif config.mode == "workflow":
    if config.planner is not None:
        raise ConfigError("mode=workflow 不允许 planner")
```

三条规则看起来只是几个 `if`，它们防止的是三种常见错误：

- 用户以为“传了 Planner 就会计划”，但 `mode=react` 从不调用它，计划没生效；
- 用户以为“Workflow 也能计划”，但步骤表写死，Planner 是死字段；
- 用户以为“P&E 不需要 Planner”，但运行时 `next_step` 直接报 `NoneType`。

三种错误都不应该在运行时才发现。**配置错误在启动时暴露，比在线上请求时暴露便宜一百倍。**

非法组合不止 `planner`。还有：

- `mode=workflow` 没有 `steps`；
- `mode=workflow` 同时传 `planner`；
- `mode=pe` 同时传 `workflow`；
- `tools` 里有重名工具；
- `budget` 的 token/calls 为负。

每一条都要在 `build` 里拒绝，而不是让运行时“试试看”。

### 6.1 校验的三个层次

配置校验分三层，越早越便宜。

**第一层：语法。** 字段类型对不对、必填有没有、枚举值是否合法。这一层不需要业务知识，`build` 开头就能做。

**第二层：组合。** `mode` 与 `workflow`/`planner` 是否匹配、`tools` 是否重名、`budget` 是否非负。这一层需要知道组件之间的关系，仍在 `build` 里做。

**第三层：环境。** 模型 key 有没有、数据库连不连得上、索引版本对不对。这一层需要外部依赖，通常在启动时做，不在 `build` 里做。

三层分开的好处是：语法错立刻报，组合错构造前报，环境错启动时报。三层混在一起，`build` 会变成一个“什么都做”的初始化函数。

**build 只做前两层。** 环境检查放在应用启动或健康检查里；`build` 不应该因为网络抖动而失败。

### 6.2 错误信息的写法

`ConfigError` 的信息要能直接告诉用户“改哪个字段”。

坏信息：

```text
invalid config
```

好信息：

```text
mode=react 不允许 planner；要使用 planner，请把 mode 改成 "pe"
```

三个要素：

- **当前值**：`mode=react`；
- **冲突字段**：`planner`；
- **修法**：把 `mode` 改成 `"pe"`。

错误信息不是日志，是用户界面。用户看到错误信息后，应该能直接改配置，而不是去读源码。

错误信息还要稳定：测试可以断言错误码，不要只断言字符串。字符串会变，错误码不会。

### 6.3 非法组合表

把非法组合列成表，`build` 逐条实现，测试逐条覆盖。

| 组合 | 结果 |
|---|---|
| `mode=workflow` + 无 `workflow` | `ConfigError` |
| `mode=workflow` + `planner` | `ConfigError` |
| `mode=react` + `workflow` | `ConfigError` |
| `mode=react` + `planner` | `ConfigError` |
| `mode=pe` + 无 `planner` | `ConfigError` |
| `mode=pe` + `workflow` | `ConfigError` |
| 重名工具 | `ToolError` |
| 负预算 | `ConfigError` |

这张表是 `build` 的规格说明。表里每一条都要有测试；没有测试的规则，迟早会被绕过。

**校验规则不是越多越好，是“每条都有测试”。** 没有测试的校验，只是注释。

### 6.4 错误分类

`build` 的错误只有两类：配置错与工具错。

- `ConfigError`：字段组合非法、缺必填、负预算；
- `ToolError`：工具重名、工具名为空。

不要把所有错误都包成 `ConfigError`。工具错是“注册失败”，配置错是“参数不对”；调用方要分开处理。

也不要抛裸 `ValueError`/`KeyError`。基座的错误要可捕获、可分类；裸异常让调用方只能 `except Exception`。

**错误类型是 API 的一部分，和返回值一样重要。**

### 6.5 校验的成本

配置校验几乎零成本：几个 `if`、几个 `isinstance`，不需要网络与模型。

这条成本优势意味着：**校验可以放在每次 `build` 时做，不需要缓存。** 一个应用启动时构造一次 Agent，校验一次；测试里构造一百次，也只多几毫秒。

不要为了“性能”跳过校验。校验省下的几毫秒，会在一次线上配置错误里全部还回去。

## 七、替换实验

装配的验收不是“五个预设都能跑”，是“换一个字段，行为只变一处”。

| 替换 | 只应消失 | 其他必须不变 |
|---|---|---|
| `build_minimal` → `build_react` | 无（只是多了工具/预算） | 循环、出口 |
| `build_react` → `build_workflow` | 模型逐步决策 | 工具、Guard、Delivery |
| `build_workflow` → `build_pe` | 写死步骤 | 工具、Guard、Delivery |
| `AllowAllGuard` → `RefundGuard` | 无拦截 | 执行、校验、出口 |
| `NullTracer` → `MemoryTracer` | 无事件 | 结果、预算 |
| `NullDurability` → `MemoryDurability` | 无恢复 | 单次运行 |

替换实验要断言“其他组件的调用次数不变”，不是只断言“结果一样”。结果一样可能是碰巧；调用次数一样才说明链路没变。

装配层的替换实验还有一个额外断言：**`Agent` 的构造参数不变。** 换一个 Guard 只换 `config.guard`，不换 `Agent` 的签名；如果换组件要改 `Agent`，说明装配层没有收口。

### 7.1 装配层的替换矩阵

装配层的替换与组件层不同：它换的是“配置字段”，不是“实现类”。

| 字段 | 换成 | 只应变化 | 其他必须不变 |
|---|---|---|---|
| `guard` | `AllowAll` ↔ `RefundGuard` | 拦截行为 | 循环、工具、出口 |
| `budget` | 小预算 ↔ 大预算 | 降级时机 | 组件、结果格式 |
| `tracer` | `Null` ↔ `MemoryTracer` | 事件有无 | 结果、预算 |
| `durability` | `Null` ↔ `MemoryDurability` | 恢复能力 | 单次运行 |
| `delivery` | 默认 ↔ 引用版 | 输出格式 | 运行状态 |
| `reflector` | `Null` ↔ `CitationReflector` | 校验次数 | 执行、预算 |
| `knowledge` | `None` ↔ `InMemory` | 检索有无 | 循环、工具 |
| `memory` | `None` ↔ `InMemory` | 记忆有无 | 单次运行 |

矩阵的每一行都应该有一个“只改配置”的测试。测试的断言不是“结果一样”，而是“其他字段对应的组件调用次数不变”。

如果换 `tracer` 让 `delivery` 的输出变了，说明 Tracer 与 Delivery 有隐藏耦合；如果换 `durability` 让单次运行的步数变了，说明 Durability 参与了决策。

**装配层的耦合，表现为“换一个字段，另一个字段的行为也变了”。** 矩阵就是用来抓这个的。

### 7.2 替换实验的写法

装配层的替换实验分两步。

第一步：用同一个 `Goal`、同一组工具、同一个 `FakeModel`，构造两份配置，只有目标字段不同。

```python
base = build(AgentConfig(model=model, tools=[...], tracer=NullTracer()))
replaced = build(AgentConfig(model=model, tools=[...], tracer=MemoryTracer()))
```

第二步：断言“目标字段的变化”与“其他字段的不变”。

```python
r1 = await base.run(goal)
r2 = await replaced.run(goal)
assert r1.answer == r2.answer
assert r1.status == r2.status
assert len(replaced.tracer.events) > 0
assert len(base.tracer.events) == 0
```

三个要点：

- 用 `FakeModel` 固定输出，否则“答案一样”可能是巧合；
- 断言 `status` 与 `usage`，不只断言 `answer`；
- 目标字段的差异要可见，其他字段的差异要为零。

替换实验写不出来，通常不是测试难写，而是 `build` 的字段没有真正解耦。**测试写不动，是装配层的设计信号。**

### 7.3 替换实验的例子

以换 `tracer` 为例，完整测试：

```python
async def test_tracer_replacement():
    goal = Goal("hi", session_id="t")
    null_agent = build(AgentConfig(model=FakeModel([answer("ok")]), tracer=NullTracer()))
    mem_tracer = MemoryTracer()
    mem_agent = build(AgentConfig(model=FakeModel([answer("ok")]), tracer=mem_tracer))

    r1 = await null_agent.run(goal)
    r2 = await mem_agent.run(goal)

    assert r1.answer == r2.answer
    assert r1.status == r2.status
    assert len(mem_tracer.events) > 0
```

这个测试只证明“tracer 能换”，不证明“其他组件不变”。要证明后者，还要断言 `guard.calls`、`actor.calls`、`budget.used` 相同。

替换实验不是“换一个类再跑一遍”，是“换一个字段，证明其他字段没动”。

### 7.4 替换实验的成本

替换实验不是免费的，但比线上事故便宜。

- 每个字段一行测试，十个字段十行；
- 用 `FakeModel`，不烧 token；
- 用内存 Durability，不写盘；
- 跑一次几毫秒。

成本最低的替换实验，是“断言对象图”：

```python
assert isinstance(agent.guard, AllowAllGuard)
assert agent.actor.tools.names() == ["concat"]
```

对象图断言不需要跑循环，直接检查 `build` 的产物。它抓的是“装配错”，不是“运行错”。

**对象图测试 + 一次运行测试 = 装配层的最小验收。** 两者都要有。

## 八、测试

装配层的测试分四组。

**第一组：预设冒烟。** 五个预设各跑一次，断言 `status=COMPLETED`，不关心业务结果。

**第二组：字段校验。** 每个非法组合一条测试，断言 `ConfigError` 与错误信息。

**第三组：替换实验。** 换 Guard/Tracer/Durability/Reflector，断言“只消失一件事”。

**第四组：例子一致性。** 六个例子共用同一套 `contracts.py` 与组件实现；换例子只改 `build(cfg)`。测试可以断言“换例子后组件类的数量不变”。

四组测试对应四种读者：使用者、配置者、替换者、维护者。只做第一组，配置错误到线上才发现；只做第二组，替换时不知道有没有隐藏耦合。

装配层的测试不追求覆盖率，追求“配置组合数”。五个预设、六个例子、十条非法组合，覆盖了大部分真实使用方式。

### 8.1 测试目录

装配层的测试单独一个文件，不跟组件测试混。

```text
tests/
├── test_build.py        # 五个预设冒烟、非法组合、默认值
├── test_replacement.py  # 字段替换矩阵
└── test_examples.py     # 六个例子只改配置
```

`test_build.py` 至少包含：

- 五个预设各跑一次；
- 每条非法组合抛 `ConfigError`；
- 默认值符合文档（`mode` 默认 `react`，`max_steps` 默认 12）。

`test_examples.py` 用同一组工具、同一个 `FakeModel`，只改 `AgentConfig`，断言六个例子都完成；如果某个例子需要额外组件类，测试会失败。

**装配层的测试，测的是“配置能不能表达差异”，不是“业务对不对”。** 业务测试在应用层，不在基座层。

### 8.2 装配测试的断言

装配测试的断言要具体到“字段 → 行为”。

| 测试 | 断言 |
|---|---|
| 预设冒烟 | `status=COMPLETED`，`answer` 非空 |
| 非法组合 | `ConfigError`，错误码/字段名 |
| 默认值 | `mode=react`、`max_steps=12` |
| 替换 | 目标组件调用次数变化，其他不变 |
| 例子一致 | 六个例子共用组件类集合 |

不要断言“输出字符串完全一样”。模型输出会变，字符串断言会让测试变脆；断言 `status`、调用次数、字段存在性，才是装配层的契约。

**装配测试测结构，业务测试测内容。** 两者混在一起，改一个提示词就要改装配测试。

### 8.3 装配测试的 fake

装配测试不需要真实模型，但需要能“计数”的 fake。

三个 fake：

- `FakeModel`：按脚本返回，记录调用次数与消息；
- `FakeGuard`：记录每次 `check` 的 `Step`，返回固定决策；
- `FakeDelivery`：记录 `finish` 的 `status` 与 `pending`。

三个 fake 让装配测试可以断言“Guard 被调用了几次、Delivery 收到了什么状态”，而不依赖真实环境。

**装配测试的 fake 不是 mock 框架，是可控的契约实现。** 它们实现同一套 Protocol，所以替换实验与真实组件走同一条路径。

### 8.4 测试失败怎么读

装配测试失败时，先看“对象图”，再看“运行”。

- 如果对象图断言失败，是 `build` 的字段映射错；
- 如果运行断言失败，是组件交互错；
- 如果两者都过但业务错，是配置选错，不是装配错。

三种失败对应三种修法：改 `build`、改组件、改配置。不要一看到失败就改业务代码。

### 8.5 装配测试的覆盖

装配测试不追求行覆盖率，追求“字段覆盖率”。

```text
每个 AgentConfig 字段：至少一个测试
每个预设：至少一个冒烟
每个非法组合：至少一个测试
每个替换：至少一个对象图断言
```

字段覆盖率比行覆盖率有用：`build` 的分支就是字段组合，覆盖字段就覆盖了主要分支。

**装配测试的目标，是“每个字段都能被单独验证”。** 做不到，说明字段之间有隐藏耦合。

### 8.6 装配测试的顺序

测试按“从构造到运行”的顺序写：

1. 对象图：`build` 后字段类型对不对；
2. 预设冒烟：五个预设各跑一次；
3. 非法组合：每条 `ConfigError`；
4. 替换矩阵：每个字段换一次；
5. 例子一致：六个例子只改配置。

顺序不能反。先写运行测试，失败时分不清是构造错还是组件错；先写对象图，失败点更明确。

**装配测试从“对象图”开始，不从“答案”开始。** 对象图对了，答案错才是业务问题。对象图错了，答案对只是巧合，下一次换配置就会坏。把这句话贴在测试文件开头，能省很多次“为什么昨天还好好的”。装配层没有魔法，只有对象图；对象图对了，行为才有讨论的基础。反过来，对象图错了，讨论行为就是浪费时间。所以 `build` 的测试永远先断言“装了什么”，再断言“跑出什么”。前者稳定，后者依赖模型；顺序对了，失败定位快一半。装配层的测试不是“证明系统能跑”，是“证明配置装对了”。跑通是应用层的事，装对是基座层的事。两者都重要，但顺序不能反：先装对，再跑通。装对之后，跑不通至少知道问题在业务；装错之后，跑通也只是碰巧。这就是为什么装配测试要先于业务测试。先证明对象图，再证明行为；顺序反过来，调试成本会翻倍。下一章从单个对象图，走到多个 Agent 的组合图。那一步不再是装配，而是拓扑。装配装一个，拓扑连多个；两者分开，边界才清楚。

## 九、会怎么坏

**第一，业务代码绕过 build。** 直接 `Agent(...)` 或 `new Guard()`；换组件要改业务代码，`build` 形同虚设。

**第二，预设变成第二套实现。** `build_production` 里写了自己的循环或自己的 Guard；预设不再是配置，是分叉。

**第三，配置默认值太激进。** 默认 `guard=DenyAll`，所有请求被拒；默认 `budget=0`，所有请求降级。默认值应该“最小可用”，不是“最安全”。

**第四，非法组合不校验。** `mode=react` 传 Planner，运行时不报错但计划不生效；用户以为计划生效，结果错了才发现。

**第五，例子各写一套。** 六个例子各自定义 `Tool`、`State`、`Guard`；读者抄哪份都能跑，但拼不到一起。

**第六，装配层持有业务逻辑。** `build` 里写“如果金额大于 1000 就用 RefundGuard”；业务规则进入装配，换业务要改 `build`。

### 9.1 装配层的四个信号

四个信号说明装配层已经失控。

**信号一：`build` 超过 100 行。** 它开始做业务判断、环境检查、重试；不再是“校验 + 构造”。

**信号二：预设之间复制代码。** `build_production` 复制了 `build_react` 的构造逻辑，只是多几个字段；改一处要改五处。

**信号三：`AgentConfig` 出现 `**kwargs`。** 用户能传任何字段，类型检查失效；非法组合到运行时才报。

**信号四：业务代码 import 组件。** 应用里出现 `from harness.guard import RefundGuard`，说明 `build` 没有暴露足够的扩展点，或者用户不知道用配置。

四个信号出现任意一个，就应该回头改 `build`，而不是继续加字段。

### 9.2 装配的演进

装配层会随项目演进，但方向是“字段增加、预设减少”。

早期：一个 `build_minimal` 就够，字段少，改得快。

中期：加 `guard`、`budget`、`tracer`、`durability`；字段变多，但仍有默认值。

后期：字段太多，读者记不住；这时应该把字段分组，用预设表达常见组合，而不是继续加字段。

预设的数量不应该随字段增加而增加。字段是能力，预设是“常见组合”；组合太多，说明字段没有分组。

**装配层的成熟标志，不是字段多，是“常用组合有名字，罕用组合仍可表达”。**

### 9.3 装配与拓扑

`build` 只装一个 `Agent`；多 agent 的组合是第 53 章。

这个边界要守住。如果 `build` 开始接受 `workers` 列表，它就从“装配一个 Agent”变成“装配整个系统”，职责膨胀。

正确的分工：

- `build` 装一个 `Agent`；
- `Supervisor`/`Handoff`/`Pipeline` 接收多个 `Agent`；
- 业务代码先用 `build` 装 worker，再把 worker 传给拓扑。

这样拓扑不需要知道 `AgentConfig`，`build` 也不需要知道拓扑。两者通过 `Agent` 接口连接。

**装配是纵向（一个 Agent 装多少件），拓扑是横向（几个 Agent 怎么连）。** 两者不能合成一个函数。

### 9.4 装配与配置中心

配置外置到配置中心后，`build` 仍然是纯构造。

流程是：

```text
配置中心 -> 读取 dict -> 校验成 AgentConfig -> build(cfg) -> Agent
```

`build` 不读配置中心，不解析 YAML/JSON，不处理热更新。这些都在入口做；`build` 只接收已经合法的 `AgentConfig`。

热更新也不改 `build`：配置变了，构造一个新的 `Agent`，旧 `Agent` 处理完在途请求后退役。`build` 不需要知道“版本切换”。

**build 不关心配置从哪来，只关心配置合不合法。** 这是它能保持纯函数的原因。

### 9.5 装配失败的代价

装配失败分两种：启动时失败与运行时失败。

启动时失败：配置错、工具重名、缺 Planner。代价是一次部署失败，改配置重来。

运行时失败：配置合法但语义错，比如 `AllowAllGuard` 上生产、`NullDurability` 跑长任务。代价是线上事故。

`build` 能拦住第一种，拦不住第二种。第二种要靠“生产预设必须显式给治理件”来防：`build_production` 要求 `guard`/`budget`/`tracer`/`durability`，不给就构造失败。

**装配层不能判断“配置是否适合生产”，但可以要求“生产配置必须显式”。** 显式不等于正确，但比默认放行好。

## 十、边界

**第一，build 不做业务判断。** 它只校验配置、构造对象；业务规则在 Guard/Tool/Policy 里。

**第二，预设不是框架。** 五个预设只是简写；用户可以不用预设，直接 `build(AgentConfig(...))`。

**第三，配置不是 DSL。** 不要为了“灵活”把配置写成表达式树；配置只描述“装哪些件”，不描述“怎么执行”。

**第四，装配不替代拓扑。** 多 agent 的组合是第 53 章；`build` 只装单个 Agent。

**第五，例子不是产品。** 六个例子证明“只改配置”，不证明“生产可用”；生产还要评测、监控、审批后台。

### 10.1 build 的输入与输出

`build` 的输入是配置，输出是一个可运行的 `Agent`；它不启动、不连接、不调用模型。

三个“不”：

- **不启动服务**：没有端口、没有后台线程；启动是应用的事。
- **不连接外部**：模型、向量库、数据库的客户端由适配器构造；`build` 只接收接口。
- **不调用模型**：构造不产生 token；第一次 `run` 才调用。

三个“不”让 `build` 可以在测试里反复调用，不会产生副作用。装配层一旦有副作用，单测就要 mock 外部世界，成本急剧上升。

**build 是纯构造，不是初始化。** 初始化（连库、拉配置、预热）在应用启动时做；构造只组装对象。

### 10.2 从例子到产品

六个例子不是产品，但它们是产品的骨架。

从例子到产品，要补五件事：

1. **真实模型适配器**：`FakeModel` 换成供应商实现；
2. **真实存储**：`MemoryDurability` 换成 SQLite/Postgres；
3. **真实检索**：`InMemoryKnowledge` 换成向量库；
4. **真实审批**：`Guard.ask` 接审批后台；
5. **评测与监控**：离线评测集、线上 Tracer、告警。

五件事都在适配器与产品层，不在 `Agent` 循环里。例子证明“骨架可复用”，产品补“外部世界”。

**不要把产品逻辑塞回例子。** 例子越像产品，越难读；产品越像例子，越不可靠。两者的边界是适配器。

### 10.3 build 的测试边界

`build` 只测“对象图对不对”，不测“业务跑得通不通”。

- 对象图测试：`build(cfg)` 后，`agent.policy` 是 `ReactPolicy`，`agent.guard` 是 `RefundGuard`，`agent.actor.tools` 包含两个工具。
- 业务测试：`agent.run(goal)` 的答案对不对；这需要真实/模拟模型，属于应用层。

把业务测试塞进 `build` 测试，会让装配测试依赖模型；把对象图测试省掉，装配错误要到运行时才发现。

**装配测试看结构，业务测试看结果。** 两者分开，测试才稳定。

### 10.4 装配的验收清单

一个装配层是否合格，看五条：

- [ ] 业务代码只 import `build`/`AgentConfig`/`Goal`，不 import 组件；
- [ ] 五个预设都调用同一个 `build`；
- [ ] 六条非法组合都有测试；
- [ ] 换一个字段，其他字段的行为不变；
- [ ] `build` 失败时，不返回半成品对象。

五条都过，才叫“装配层完成”。缺一条，组件再多也只是散件。

### 10.5 装配的边界

装配层只做“把配置变成对象图”，不做“让对象图跑得好”。

跑得好是评测、监控、调优的事；装配层只保证“装对了”。装错了，调优也救不回来；装对了，调优才有意义。

**装配层的成功标准是“换配置不改代码”，不是“跑得快”。** 性能是运行层的事，不是装配层的事。

### 10.6 装配的下一版

这一版 `build` 只支持单 Agent、三种 BodyPolicy、五个预设。下一版会遇到三个新需求：拓扑装配、多租户配置、热更新。

三个需求都不应该直接改 `build`：

- 拓扑装配用 `Topology(agents)`，`build` 仍只装一个 Agent；
- 多租户配置在入口合并，`build` 只接收合并后的 `AgentConfig`；
- 热更新构造新 Agent，旧 Agent 退役。

**build 的边界越稳定，上层越容易演进。** 每次想往 `build` 里加职责，先问“这是构造，还是运行/入口/拓扑”。

## 这一章建立的 7 件事

1. `build(cfg)` 是唯一实例化处：业务代码只填配置，不 `new` 组件。
2. 五个预设是配置的简写，不是第二套实现；它们都调用同一个 `build`。
3. 六个例子共用同一套契约与组件，差异只在 `AgentConfig`；换例子不改组件。
4. 配置分三层：必填、常用、高级；读者第一次只需要读前五个字段。
5. 装配顺序固定：校验 → 工具 → Actor → 策略 → Context → Agent；失败时不返回半成品。
6. 非法组合在 `build` 时拒绝，错误信息要带当前值、冲突字段、修法。
7. 装配测试看对象图，业务测试看结果；两者不能混。

## 下一章

一个 Agent 装好了，最后一个问题是：多个 Agent 怎么连。

第 53 章讲拓扑：Supervisor、Handoff、Blackboard、Pipeline 四种组合，为什么拓扑只依赖 `Agent`/`State`/`Board`/`Brief`，以及“换一种拓扑，只应改变控制权归谁，结论不变”。

---

[← 第 51 章 · 校验、治理与供给：横切部件怎么挂](./51-校验-治理与供给-横切部件怎么挂.md)　｜　[卷 12 目录](./docs/INDEX.md#vol12)　｜　[第 53 章 · 组合：Agent 与四种拓扑 →](./53-组合-Agent与四种拓扑.md)
