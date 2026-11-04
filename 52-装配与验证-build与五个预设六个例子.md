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
[四、配置字段与装配顺序](#四配置字段与装配顺序)\
[五、非法组合与替换实验](#五非法组合与替换实验)\
[六、测试、失效与边界](#六测试失效与边界)\
[这一章建立的 7 件事](#这一章建立的-7-件事)

## 一、build 是唯一实例化处

第 48–51 章把九个组件的职责讲完了，剩下一件没有交代：这些组件由谁来 `new`。`code/harness/examples/assembly.py` 里留了一种写法，让业务代码自己构造全部组件。

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

基座的解法是 `build(cfg)`，唯一实例化处：业务代码只填配置，不碰组件构造。

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

这四件事只在一个地方发生，换组件、加默认值、改构造顺序都只改 `build`，业务代码一行不动。
`build` 看起来像一个工厂，但它不是工厂模式：工厂模式有一个工厂接口、多个具体工厂和一个产品族，基座只有一个 `build(cfg)` 和一个 `Agent`。它不决定创建哪一类产品，只按配置装配同一个产品，所以扩展方式是加预设函数，而不是为每种配置写一个工厂。

选架构在第 47 章，配置在 `AgentConfig`，构造在 `build`，三者分开才不会把选型写进代码。
`build` 不是 `main`：`main` 读环境变量与配置文件、构造模型客户端与数据库连接、调 `build(cfg)`、启动服务；`build` 只校验配置、装配组件、返回 `Agent`。`main` 可以有副作用，`build` 不能，所以 `build` 能在测试里反复调用。

这个分工让配置错误在 `build` 暴露、环境错误在 `main` 暴露，测试不必 mock 环境。
`build` 的签名只有两个东西：一个 `AgentConfig`，一个返值 `Agent`，见 `build.py` 的第一行：

```python
def build(config: AgentConfig) -> Agent: ...
```

所有字段在 `AgentConfig` 里，所有默认值在 dataclass 里，所以签名稳定、类型可查、测试只要构造一个配置对象。如果接受 `kwargs`，用户会传任意键，类型检查失效，非法字段只能运行时发现：装配入口越窄，配置越可测；入口越宽，非法字段越会散落到运行期才暴露。

## 二、五个预设

五个预设不是另一套实现，只是 `AgentConfig` 的简写，定义在 `code/harness/src/harness/presets.py`，覆盖五种规模：

```python
def build_minimal(*, model, tools=None, **kwargs):
    return build(AgentConfig(model=model, tools=list(tools or []), mode="react", **kwargs))
```

最小形态是一个模型、零个或多个工具，治理与供给全用默认实现，适合 hello world 与单测。循环形态在它之上加预算、轨迹、Guard 与恢复：

```python
def build_react(*, model, tools=None, budget=None, tracer=None, guard=None,
                durability=None, **kwargs):
    return build(AgentConfig(..., mode="react", ...))
```

循环形态的增量是预算与轨迹，把成本与可观测一起装进来。工作流形态把步骤写死，模型只出现在 LLM 步骤：

```python
def build_workflow(*, model, workflow, tools=None, **kwargs):
    return build(AgentConfig(..., mode="workflow", workflow=list(workflow), ...))
```

工作流形态的步骤表里没有模型决策的位置，顺序与参数都在 `Step` 上。计划形态先产出一份 `Plan` 再执行，适合步骤可计划、需要审查的任务：

```python
def build_pe(*, model, planner, tools=None, **kwargs):
    return build(AgentConfig(..., mode="pe", planner=planner, ...))
```

计划形态把 `Planner` 的产出固定成 `Plan`，可以审查后再执行。生产形态把治理五件、检索、记忆、校验都挂上：

```python
def build_production(*, model, tools=None, guard, budget, tracer, durability,
                     delivery=None, reflector=None, knowledge=None,
                     retrieval=None, memory=None, memory_policy=None, **kwargs):
    return build(AgentConfig(..., mode="react", ...))
```

生产形态是字段最多的一种，`guard`、`budget`、`tracer`、`durability` 必须显式给，检索与记忆可选。五个预设的差别只在装哪些件，`build_production` 不是另一个 `Agent`，只是字段更多的 `AgentConfig`。

### 2.1 预设的边界

预设最有用的地方是给读者一条默认路径，最危险的地方是变成必须走的路径。三个边界：预设不是唯一入口，可以直接 `build(AgentConfig(...))`；预设不隐藏关键决策，`build_production` 仍要求传治理件；预设不承诺稳定，稳定的契约是 `AgentConfig` 与 `build`。数量也要控制，五个覆盖最小、循环、工作流、计划、生产就够。

五个预设不是互斥的，可以组合：`build_react` 加治理字段是生产版 ReAct，`build_workflow` 加检索是带 RAG 的固定流程，`build_pe` 加审批是带人工审批的计划执行。组合的方式不是继承预设，是把字段传进去，组合逻辑在 `AgentConfig` 里，预设之间互相调用会出现隐藏耦合。

### 2.2 预设的默认值

五个预设的默认值不一样，这是有意的：`build_minimal` 不设预算与轨迹，追求最少字段能跑；`build_react` 设预算与轨迹不设 Guard，追求看住成本；`build_pe` 必须给 Planner，追求计划可审查。默认值表达的是这个形态最低限度要什么：`build_production` 不替调用方选 Guard，因为 Guard 是业务规则，但要求显式给，读者看到默认值就知道自己还缺什么。
预设函数的 `kwargs` 是便利，也是风险：用户可以传任意 `AgentConfig` 字段，但类型检查失效，传了 `planner` 给 `build_react` 要到 `build` 才报错。

折中的写法是显式列出常用字段，`kwargs` 只留给高级字段，由 `build` 统一校验，写法在 `presets.py` 里：

```python
def build_react(*, model, tools=None, budget=None, tracer=None, guard=None,
                durability=None, **kwargs):
    ...
```

这样常用字段有类型提示，高级字段仍可传，非法组合由 `build` 兜，写法见 `presets.py` 里的 `build_react`。

### 2.3 预设的版本与文档

预设是便利函数，不承诺稳定，但“不承诺”不等于可以随便改，`presets.py` 的注释里写了三条兼容规则：加字段给默认值，删除字段先弃用，改默认值要写迁移说明并在 trace 里记录版本。预设版本跟包版本走，`contracts_version` 只管类型与协议。
每个预设的文档只写三行：

```text
用途：最小可运行
必填：model
默认：mode=react，其余空实现
```

不要写“本预设采用先进的 ReAct 架构”这类话，读者只关心什么时候用、要给什么、默认装了什么。文档还要给下一步：从 `build_minimal` 到 `build_react` 加什么字段，从 `build_react` 到 `build_production` 加什么。

## 三、六个例子

六个例子不是六份代码，是六份配置，都写在 `assembly.py` 里，前三个完整、后三个只给差异，验收标准是差异全部落在配置上。先看最小问答：

```python
agent = build_minimal(model=FakeModel([answer("hello")]))
result = await agent.run(Goal("hi", session_id="min"))
```

```text
completed hello
```

例子一验证的是没有工具、没有检索、没有审批时循环仍能跑通，默认组件都有合理的空实现。例子二加一个工具，考察工具调用、结果回灌、预算扣减与终止判断四段：

```python
agent = build_react(
    model=FakeModel([tool_call("concat", left="a", right="b"), answer("ab")]),
    tools=[concat],
    budget=Budget(tokens=1000, calls=4),
)
```

```text
completed ab
```

例子二的四段都走到了，答案是工具返回的 `ab`。例子三换成工作流，步骤写死，模型不参与决策：

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

```text
completed cd
```

例子三的输出是最后一步的结果，`state.data["workflow_index"]` 停在 2。例子四加上 `Planner`，先出 `Plan` 再执行：

```python
plan = Plan(id="p1", steps=[...])
agent = build_pe(model=FakeModel([answer("unused")]),
                 planner=ScriptedPlanner(plan), tools=[concat])
```

```text
completed cd
```

例子四的 `plan_id` 是计划标识，可追溯，`index` 到 2，Planner 只出现在 P&E 配置里。例子五把检索、工具、预算、轨迹、恢复一起挂上：

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

```text
completed 已签收 events= 4
```

例子五的输出仍是同一个对象，`RunResult` 是 `run` 的统一返回，没有多一层生产专用 API，`events=4` 说明四类事件都记了。
第六个例子是同一套组件换业务：把 `get_order` 换成 `search_docs`、`RefundGuard` 换成 `PiiGuard`、预算换成六万，`Agent`、`Actor`、`Context`、`Delivery` 一行不改：

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

验收句：换一个例子只改 `build` 的参数；如果改了组件代码，就是耦合。

### 3.1 例子的共同点

六个例子看起来不同，但 `assembly.py` 里它们的结构完全一样：

```text
Goal -> Agent -> BodyPolicy -> Actor -> Tools -> ActionResult -> Delivery
```

差别只有四个：

- `BodyPolicy`：react / workflow / pe；
- `Tools`：concat / get_order / search_docs；
- 治理：AllowAll / RefundGuard / PiiGuard；
- 供给：无 / Knowledge / Memory。

四个差别都在 `AgentConfig` 里，没有一个在 `Agent` 的循环里。这就是装配层的验收：例子之间的差异应该全部落在配置上。数量也有讲究，少于三个证明不了只改配置，多于六个读者记不住。
六个例子的代码结构也应该一样，差异只在构造配置那一步：

```text
1. 定义工具
2. 定义模型（或 FakeModel）
3. 构造 AgentConfig
4. build(cfg)
5. run(goal)
6. 断言 status/answer
```

如果某个例子在第 1 步定义了新的 `Tool` 基类，或在第 4 步之后改了 `Agent` 的字段，它就脱离了只改配置的验收。例子不是文档，是可执行测试。两者分开写，例子一定会腐烂。

### 3.2 例子的验收

六个例子要通过三条验收，验收本身也是测试，落在 `code/harness/tests/test_scenarios.py` 里。

第一条是能跑：每个例子独立运行，输出 `RunStatus`，它是运行状态的枚举，取值只有完成与失败，不依赖网络与真实模型。第二条是只改配置：共用同一套 `contracts.py` 与组件实现，差异只在 `build(cfg)` 的参数。第三条是能解释：能回答为什么用这个 mode、这个 Guard、这个预算。
例子应该被测试直接引用，而不是复制到测试里，测试文件开头只做一件事：

```python
from examples.assembly import example_minimal, example_react
```

例子函数返回 `RunResult`，测试断言 `status` 与关键字段，例子改了测试跟着跑，不会出现文档里的例子早就过期。例子函数不 `print` 也不 `asyncio.run`，只构造、运行、返回。
例子目录按形态分，不按业务分：

```text
examples/
├── minimal.py
├── react.py
├── workflow.py
├── pe.py
├── production.py
└── assembly.py      # 一次跑五个，用于演示
```

按业务分会让读者以为每种业务要一套代码；按形态分，读者看到的是同一个骨架不同配置。业务例子放在应用仓库，基座只保留形态例子，基座不承载业务，例子才能长期可跑。

## 四、配置字段与装配顺序

`AgentConfig` 的字段不多，但要分清必填、常用、高级，字段声明在 `contracts.py` 里：

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

这个分类不是装饰，它决定读者第一次用基座时要填几个字段：最小可用只需要 `model`，加工具填 `tools`，加流程填 `mode` 或 `workflow`。默认值本身也有语义，`guard=AllowAll` 是显式允许所有动作，不是没有 Guard；`tracer=Null` 是显式不记录，不是没有观测。显式空实现比没有这个字段好，读者知道自己关掉了什么，也知道怎么打开。

### 4.1 配置的三种读法

同一份 `AgentConfig`，三种读者看的东西不同。使用者看必填与常用：`model`、`tools`、`mode`、`max_steps`。替换者看高级：`guard`、`budget`、`tracer`、`durability`。维护者看分支：`workflow`、`planner`、`mode` 的组合。配置文档应该按这三种读法组织，而不是按字母表。

### 4.2 配置与代码的边界

配置能表达装哪些件，不能表达怎么执行。能放配置的是选择：选哪个 `mode`、用哪个组件、工具的列表、最大步数；不能放的是执行：业务规则的具体判断、工具的实现、提示词模板的拼接逻辑。业务规则放配置，配置会变成一门 DSL；工具实现放配置，配置会变成代码。选择可以外置，执行不能。
默认值不是文档，是测试。三条断言：不传 `mode` 时 `agent.policy` 是 `ReactPolicy`；不传 `max_steps` 时 `agent.max_steps == 12`；不传 `guard` 时 `agent.guard` 是 `AllowAllGuard`。第三条最重要，`None` 会让循环在 `guard.check` 时崩溃，显式 `AllowAll` 让没有配置和配置了放行可区分。没有这条测试，默认值迟早会变成 `None`。

`build` 内部的顺序是固定的，`build.py` 里只有这一条路径：

```text
1. 校验配置
2. 构造 ToolRegistry
3. 构造 Actor
4. 按 mode 构造 BodyPolicy
5. 构造 Context
6. 构造 Agent，注入治理/供给
```

四个顺序约束。先校验后构造，非法组合要在构造任何对象之前拒绝，否则会留下半成品对象。先工具后 Actor，工具重名要在构造 Actor 之前报错。先策略后 Agent，`Agent` 需要 `policy`，策略失败要直接抛出，不能构造一个没有策略的 Agent。治理与供给最后注入。这个顺序不是实现细节，是失败语义：每一步的错误都能定位到具体字段。

### 4.3 构造顺序的失败

顺序错了会出现三种半成品。先构造 Agent 后构造策略，`Agent` 只能先传 `None` 再补，补的时候失败，调用方已经拿到一个不能用的对象。先构造 Actor 后构造工具，`Actor` 只能先持有空表，注册失败要等到执行才暴露。先构造治理后校验配置，配置非法时 Guard 与 Tracer 已经连了外部服务，抛错就泄漏连接。三种半成品的共同点是错误发生得太晚，构造的目标是对象要么完整要么不存在。

### 4.4 构造的依赖图

`build` 的依赖图是单向的，`build.py` 里的构造顺序就是按它排的：

```text
AgentConfig
  ├── Model
  ├── ToolRegistry <- Tools
  ├── Actor <- Model + ToolRegistry + Resilience
  ├── BodyPolicy <- Mode + (Workflow | Planner)
  ├── Context
  └── Agent <- Actor + BodyPolicy + Context + 治理/供给
```

箭头只能向下：`Model` 不知道 `Actor`，`ToolRegistry` 不知道 `Agent`，`BodyPolicy` 不知道 `Delivery`。依赖图回答谁可以先构造，`Model` 与 `Tools` 最先，`Agent` 最后。任何反向依赖都说明组件边界破了。
构造顺序可以用对象图测试固定下来：

```python
agent = build(cfg)
assert isinstance(agent.policy, ReactPolicy)
assert isinstance(agent.actor, Actor)
assert agent.actor.tools is not None
assert agent.budget is not None
```

四条断言对应四个构造阶段，少一条，构造顺序被改坏就没人发现。对象图测试不需要运行循环，构造完就能断言。

## 五、非法组合与替换实验

`build` 的另一个职责是拒绝非法组合，最典型的是 `mode` 与 `planner`，校验写在 `build.py` 开头：

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

三条规则看起来只是几个 `if`，防的是三种常见错误：以为传了 Planner 就会计划，但 `mode=react` 从不调用它；以为 Workflow 也能计划，但步骤表写死，Planner 是死字段；以为 P&E 不需要 Planner，但运行时读第一步就抛 `TypeError`。缺 `steps`、重名工具、负预算也要在 `build` 里拒绝。这些错误都不该在运行时才发现，配置错误在启动时暴露，比在线上请求时暴露便宜得多。

### 5.1 校验的三个层次

配置校验分三层，越早越便宜。第一层语法：字段类型、必填、枚举值，`build` 开头就能做。第二层组合：`mode` 与 `workflow`、`planner` 是否匹配，`tools` 是否重名，`budget` 是否非负。第三层环境：模型 key 有没有、数据库连不连得上，这层放在启动或健康检查里。`build` 只做前两层，它不应该因为网络抖动而失败，环境检查放到启动或健康检查里才合适。

### 5.2 错误信息的写法

`ConfigError` 的信息要能直接告诉用户改哪个字段，文案在 `errors.py` 里统一。下面是坏信息的写法：

```text
invalid config
```

改成带修法的写法：

```text
mode=react 不允许 planner；要使用 planner，请把 mode 改成 "pe"
```

三个要素：当前值 `mode=react`，冲突字段 `planner`，修法是把 `mode` 改成 `"pe"`。错误信息不是日志，是用户界面，用户看到之后应该能直接改配置。它还要稳定：测试断言错误码，不要只断言字符串。
把非法组合列成表，`build` 逐条实现，测试逐条覆盖：

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

这张表是 `build` 的规格说明，表里每一条都要有测试。没有测试的校验只是注释，迟早会被绕过。
`build` 的错误只有两类：`ConfigError` 处理字段组合非法、缺必填、负预算，`ToolError` 处理工具重名与工具名为空。工具错是注册失败，配置错是参数不对，调用方要分开处理，也不要抛裸 `ValueError`。错误类型是 API 的一部分，和返回值一样重要。

配置校验几乎零成本：几个 `if`、几个 `isinstance`，不需要网络与模型。所以校验放在每次 `build` 时做，不需要缓存。一条校验规则没有对应测试，等于注释。不要为了性能跳过校验，省下的几毫秒会在一次线上配置错误里全部还回去。

装配的验收不是五个预设都能跑，是换一个字段行为只变一处：

| 替换 | 只应消失 | 其他必须不变 |
|---|---|---|
| `build_minimal` → `build_react` | 无（只是多了工具/预算） | 循环、出口 |
| `build_react` → `build_workflow` | 模型逐步决策 | 工具、Guard、Delivery |
| `build_workflow` → `build_pe` | 写死步骤 | 工具、Guard、Delivery |
| `AllowAllGuard` → `RefundGuard` | 无拦截 | 执行、校验、出口 |
| `NullTracer` → `MemoryTracer` | 无事件 | 结果、预算 |
| `NullDurability` → `MemoryDurability` | 无恢复 | 单次运行 |

替换实验要断言其他组件的调用次数不变，不是只断言结果一样：结果一样可能是碰巧，调用次数一样才说明链路没变。装配层的替换还有一个额外断言，`Agent` 的构造参数不变，换 Guard 只换 `config.guard`。换组件要改 `Agent`，说明装配层没有收口。

### 5.3 替换矩阵

装配层换的是配置字段，不是实现类，`contracts.py` 里每个字段都对应一行替换测试：

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

矩阵的每一行都应该有一个只改配置的测试，断言其他字段对应的组件调用次数不变。如果换 `tracer` 让 `delivery` 的输出变了，说明两者有隐藏耦合；如果换 `durability` 让单次运行的步数变了，说明它参与了决策。
替换实验分两步。第一步，用同一个 `Goal`、同一组工具、同一个 `FakeModel`，构造两份配置，只有目标字段不同：

```python
base = build(AgentConfig(model=model, tools=[...], tracer=NullTracer()))
replaced = build(AgentConfig(model=model, tools=[...], tracer=MemoryTracer()))
```

第二步，断言目标字段变了、其他字段没变：

```python
r1 = await base.run(goal)
r2 = await replaced.run(goal)
assert r1.answer == r2.answer
assert r1.status == r2.status
assert len(replaced.tracer.events) > 0
assert len(base.tracer.events) == 0
```

三个要点：用 `FakeModel` 固定输出，否则答案一样可能是巧合；断言 `status` 与 `usage`，不只断言 `answer`；目标字段的差异要可见，其他字段的差异要为零。替换实验写不出来，通常不是测试难写，而是字段没有真正解耦，测试写不动是装配层的设计信号。

换成 `tracer` 的完整测试是这样：

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

这个测试只证明 `tracer` 能换，不证明其他组件不变。要证明后者，还要断言 `guard.calls`、`actor.calls`、`budget.used` 相同。换一个字段并证明其他字段没动，才是替换实验。

替换实验不免费，但比线上事故便宜：每个字段一行测试，用 `FakeModel` 不烧 token，用内存 Durability 不写盘，跑一次几毫秒。成本最低的一种是断言对象图：

```python
assert isinstance(agent.guard, AllowAllGuard)
assert agent.actor.tools.names() == ["concat"]
```

对象图断言不跑循环，直接检查 `build` 的产物，抓的是装配错而不是运行错。对象图测试加一次运行测试，是装配层的最小验收，两者都要有。

## 六、测试、失效与边界

装配层的测试分四组，都落在 `tests/` 下的两个文件里，`test_build.py` 管装配，`test_scenarios.py` 是跑六个例子的那份。预设冒烟：五个预设各跑一次。字段校验：每个非法组合一条，断言 `ConfigError`。替换实验：换 Guard、Tracer、Durability，断言只消失一件事。例子一致性：换例子只改 `build(cfg)`，组件类数量不变。
三个测试文件各管一段，不跟组件测试混：

```text
tests/
├── test_build.py        # 五个预设冒烟、非法组合、默认值
├── test_replacement.py  # 字段替换矩阵
└── test_examples.py     # 六个例子只改配置
```

`test_build.py` 至少包含三类用例：五个预设各跑一次、每条非法组合抛 `ConfigError`、默认值符合文档，也就是 `mode` 默认 `react`、`max_steps` 默认 12。`test_examples.py` 只改 `AgentConfig`，断言六个例子都完成，某个例子需要额外组件类时它会失败。

### 6.1 装配测试的断言

装配测试的断言要具体到字段与行为的对应，`test_core.py` 里的几组断言是这样：

| 测试 | 断言 |
|---|---|
| 预设冒烟 | `status=COMPLETED`，`answer` 非空 |
| 非法组合 | `ConfigError`，错误码/字段名 |
| 默认值 | `mode=react`、`max_steps=12` |
| 替换 | 目标组件调用次数变化，其他不变 |
| 例子一致 | 六个例子共用组件类集合 |

不要断言输出字符串完全一样，模型输出会变，字符串断言会让测试变脆；断言 `status`、调用次数、字段存在性，才是装配层的契约。装配测试测结构，业务测试测内容。
装配测试需要能计数的 fake：`FakeModel` 按脚本返回并记录调用次数，`FakeGuard` 是一个记录每次 `check` 的 `Step` 的假实现。它们不是 mock 框架，是可控的契约实现，实现同一套 Protocol，所以替换实验与真实组件走同一条路径。

装配测试失败时，先看对象图，再看运行。对象图断言失败是 `build` 的字段映射错；运行断言失败是组件交互错；两者都过而业务错，是配置选错。三种失败对应三种修法：改 `build`、改组件、改配置，不要一看到失败就改业务代码。
装配测试不追求行覆盖率，追求字段覆盖率：

```text
每个 AgentConfig 字段：至少一个测试
每个预设：至少一个冒烟
每个非法组合：至少一个测试
每个替换：至少一个对象图断言
```

字段覆盖率比行覆盖率有用，`build` 的分支就是字段组合，覆盖字段就覆盖了主要分支。测试的目标是每个字段都能被单独验证。

测试按从构造到运行的顺序写：

1. 对象图：`build` 后字段类型对不对；
2. 预设冒烟：五个预设各跑一次；
3. 非法组合：每条 `ConfigError`；
4. 替换矩阵：每个字段换一次；
5. 例子一致：六个例子只改配置。

顺序不能反。先写运行测试，失败时分不清是构造错还是组件错；先写对象图，失败点更明确。对象图对了，答案错才是业务问题；对象图错了，答案对只是巧合，换一次配置就会坏。

装配层有六种坏法。业务代码绕过 `build`，直接 `Agent(...)`，换组件就要改业务代码。预设变成第二套实现，`build_production` 里写了自己的循环或 Guard。默认值太激进，默认 Guard 是全部拒绝，所有请求被拒。非法组合不校验，`mode=react` 传 Planner 运行时不报错但计划不生效。例子各写一套，六个例子各自定义工具、状态与 Guard，抄哪份都能跑但拼不到一起。装配层持有业务逻辑，`build` 里写如果金额大于一千就用 `RefundGuard`，换业务就要改 `build`。

### 6.2 装配层的信号与演进

四个信号说明装配层已经失控。`build` 超过 100 行，开始做业务判断、环境检查、重试。预设之间复制代码，改一处要改五处。`AgentConfig` 出现 `kwargs`，类型检查失效。业务代码 import 组件，应用里出现 `from harness.guard import RefundGuard`，说明 `build` 没暴露扩展点。四个信号出现任意一个，就该回头改 `build`，而不是继续加字段。

装配层会随项目演进，方向是字段增加、预设减少。早期一个 `build_minimal` 就够；中期加 `guard`、`budget`、`tracer`，字段变多但都有默认值；后期字段太多读者记不住，这时把字段分组、用预设表达常见组合。成熟的标志不是字段多，是常用组合有名字、罕用组合仍可表达。预设数量不应该随字段增加而增加。

`build` 只装一个 `Agent`，多 agent 的组合是第 53 章，`topology.py` 里那四种拓扑接收的都是装好的 `Agent`。如果 `build` 开始接受 `workers` 列表，它就从装配一个 Agent 变成装配整个系统，两者通过 `Agent` 接口连接才对。

配置外置到配置中心后，`build` 仍然是纯构造，入口的做法是：

```text
配置中心 -> 读取 dict -> 校验成 AgentConfig -> build(cfg) -> Agent
```

`build` 不读配置中心，不解析 YAML 或 JSON，不处理热更新，这些都在入口做。热更新也不改 `build`：配置变了就构造一个新 `Agent`，旧的处理完在途请求后退役。`build` 只关心配置合不合法。

装配失败分两种。启动时失败是配置错、工具重名、缺 Planner，代价是一次部署失败。运行时失败是配置合法但语义错，`AllowAllGuard` 上生产、`NullDurability` 跑长任务，代价是线上事故。第二种靠生产预设必须显式给治理件来防。装配层不能判断配置是否适合生产，但可以要求生产配置必须显式，比默认放行好。

五条边界。`build` 不做业务判断，业务规则在 Guard、Tool、Policy 里。预设不是框架，可以直接 `build(AgentConfig(...))`。配置不是 DSL，只描述装哪些件，不描述怎么执行，写成表达式树之后既没法做类型校验，也没法与 preset 的默认值合并。装配不替代拓扑，多 agent 的组合是第 53 章。例子不是产品，只证明只改配置。

`build` 的输入是配置，输出是一个可运行的 `Agent`，它不启动、不连接、不调用模型：没有端口也没有后台线程，客户端由适配器构造，构造不产生 token。三个不让 `build` 能在测试里反复调用，装配层一旦有副作用，单测就要连真实环境。

### 6.3 从例子到产品

六个例子不是产品，但它们是产品的骨架。从例子到产品要补五件事：`FakeModel` 换成真实适配器，`MemoryDurability` 换成 SQLite，内存版知识库换成向量库，`Guard.ask` 接审批后台，再补离线评测集与线上 Tracer。五件事都在适配器层，不在 `Agent` 循环里；产品逻辑塞回例子，例子就越难读。

`build` 只测对象图对不对，不测业务跑得通不通。对象图测试是 `build(cfg)` 之后 `agent.policy` 是 `ReactPolicy`、`agent.guard` 是 `RefundGuard`；业务测试是 `agent.run(goal)` 的答案对不对，需要模型，属于应用层。装配测试看结构，业务测试看结果。

一个装配层是否合格，看五条：业务代码只 import `build`、`AgentConfig`、`Goal`；五个预设都调用同一个 `build`；六条非法组合都有测试；换一个字段其他字段的行为不变；`build` 失败时不返回半成品对象。

装配层只做把配置变成对象图，不做让对象图跑得好。跑得好是评测、监控、调优的事，装配层只保证装对了。它的成功标准是换配置不改代码，不是跑得快，性能是运行层的事。

这一版 `build` 只支持单 Agent、三种 `BodyPolicy`、五个预设。下一版会遇到拓扑装配、多租户配置、热更新，三个都不应该直接改 `build`：拓扑装配用 `Topology(agents)`，多租户在入口合并配置，热更新构造新 Agent 让旧的退役。每次想往 `build` 里加职责，先问这是构造，还是运行、入口、拓扑。

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
