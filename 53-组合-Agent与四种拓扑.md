# 第 53 章 · 组合：Agent 与四种拓扑

> **卷 12 · 组件封装（副线）（第 48–53 章）**｜[全书目录](./docs/INDEX.md#vol12)｜[本卷导读](./outline/vol12-组件封装.md)
>
> - **知识点**：无（本章只建立全书的地图，不承载 A–G 中的任何一条）
> - **本章回答**：为什么拓扑只依赖 `Agent`/`State`/`Board`/`Brief`；四种拓扑各自怎么组合；换拓扑为什么只应改变“控制权归谁”；拓扑怎么嵌套
> - **示例目录**：`code/harness/examples/topology.py`（基座包在 `code/harness/src/harness/`）
> - **读完应当能回答**：给一个多 agent 任务，选哪种拓扑；说出 Supervisor 与 Handoff 的控制权差别；判断一个拓扑是否偷偷实现了能力

---

## 目录

[一、拓扑只组合 Agent](#一拓扑只组合-agent)\
[二、Pipeline](#二pipeline)\
[三、Handoff](#三handoff)\
[四、Supervisor](#四supervisor)\
[五、Blackboard](#五blackboard)\
[六、共用的契约](#六共用的契约)\
[七、替换、嵌套与失效](#七替换嵌套与失效)\
[这一章建立的 7 件事](#这一章建立的-7-件事)

## 一、拓扑只组合 Agent

前五章把单个 Agent 装好了：分派、主体、校验、治理、供给、装配。剩下的问题是多个 Agent 怎么连，答案不是再写一个更大的 Agent，而是拓扑，四种拓扑的代码都在 `code/harness/examples/topology.py`。

拓扑做的事只有三件：决定有几个 Agent，决定谁先跑、谁能并行，决定上下文怎么过去：

```text
拓扑( Agent[] )
```

它不做四件事：不实现能力，工具、检索、模型调用都在组件里；不实现治理，Guard、Budget、Tracer 不进拓扑；不实现主体策略，ReAct、Workflow、P&E 归 worker；不改变单个 Agent 的循环。这条边界就是第 33 章讲的“拓扑是系统层，不是 agent 层”，本章用代码把它落下来。
四种拓扑对应四种控制权：

| 拓扑 | 控制权 | 适合 |
|---|---|---|
| Pipeline | 固定顺序 | 阶段明确、无分支 |
| Handoff | 当前 Agent | 分诊、转交 |
| Supervisor | 中心调度者 | 任务可拆分、需要汇总 |
| Blackboard | 共享看板 | 多角色协作、写冲突 |

四种拓扑的实现都在 `topology.py`，只 import `Goal`、`RunResult`、`SessionRef`，不 import 任何组件。

### 1.1 拓扑与编排的分界

“编排”和“拓扑”常被混用，区别在谁决定下一步。编排是单个 Agent 内部的三层：分派、主体、校验，见第 22 章；拓扑是多个 Agent 之间的连接方式。编排决定这个 Agent 怎么走，拓扑决定几个 Agent 谁先走、谁指挥谁。

两者不能互相替代：单 Agent 编排再好也解决不了多角色协作，拓扑再复杂也解决不了一个 Agent 内部的决策混乱。编排是纵向，拓扑是横向，先有纵向的 Agent，才有横向的拓扑。

### 1.2 一致的输入输出

四种拓扑的输入输出必须一致，只依赖 `Goal` 与 `RunResult`，接口写在 `topology.py` 里：

```text
run(Goal, SessionRef | None) -> RunResult
```

一致的输入输出带来三个好处：拓扑可以互相嵌套；测试可以用同一套 `Goal` 与 `RunResult`；调用方不需要知道内部是哪种拓扑。如果某个拓扑的 `run` 返回 `dict` 或 `str`，它就不能嵌套，也不能被统一测试，所以拓扑的契约比实现重要。

### 1.3 拓扑与框架

LangGraph、AutoGen、CrewAI 都提供拓扑，基座的拓扑与它们不冲突，三种关系是替代、嵌套与对照：基座拓扑够用就不用框架；也可以把基座 Agent 作为框架图里的一个节点；还可以用同一个任务各搭一遍，比较可维护性。拓扑的核心是控制权，API 可以换，控制权不能乱。

## 二、Pipeline

Pipeline 是最简单的拓扑：阶段按顺序执行，上一阶段的答案作为下一阶段的输入，代码在 `topology.py` 里：

```python
class Pipeline:
    def __init__(self, stages: list[Any]) -> None:
        self.stages = list(stages)

    async def run(self, goal, session=None) -> RunResult:
        current = goal
        results = []
        for stage in self.stages:
            result = await stage.run(current, session)
            results.append(result)
            if result.status not in (RunStatus.COMPLETED, RunStatus.DEGRADED):
                return result
            current = Goal(text=result.answer, ...)
        return merge(results)
```

Pipeline 的优点是确定性：阶段顺序写死，每一段都可检查点，失败只重跑一段。缺点是阶段之间只能传文本，第二段需要第一段的结构化结果时，要把结果放进 `Goal.metadata` 或 `State`。它适合解析、分析、写报告这类阶段固定的任务。

### 2.1 Pipeline 的接口

Pipeline 的阶段只要实现 `run(goal, session) -> RunResult`，普通函数用小适配器包一层就能接上，`topology.py` 里的 `Runnable` 就是它：

```python
class FunctionStage:
    name = "function"
    def __init__(self, fn): self.fn = fn
    async def run(self, goal, session=None):
        return RunResult(status=RunStatus.COMPLETED, answer=self.fn(goal.text))
```

这样 Pipeline 不依赖 Agent 类型，只依赖 `Runnable` 契约，阶段可以是 Agent、函数或子拓扑。合并逻辑也要显式：成功返回最后一个阶段的 `RunResult`；失败立即返回失败阶段的结果；降级继续但记录缺口。三种处理对应三种 `status`，不处理，Pipeline 会把失败当成功继续跑。
Pipeline 的检查点记跑到第几阶段，不是跑到第几步，存的就是阶段索引：

```text
state.data["pipeline"] = {"index": 2, "results": [...]}
```

恢复时从 `index` 开始，不用重跑前两段，但前两段的结果要存，否则第三段拿不到输入。Pipeline 的检查点与 Agent 的检查点要分开：Agent 存 `step_index`，它是步骤序号，Pipeline 存阶段索引，混在一起，恢复时不知道从哪一层继续。

Pipeline 默认顺序，但阶段之间没有依赖时可以并行，条件是两段不共享输入、没有先后依赖、合并策略能处理并发结果。并行带来两个问题：预算竞争与 trace 顺序，预算要提前分，trace 要有 `parent_id`，它是父 span 的标识。不要为了快强行并行，先顺序跑通，再按测量结果并行。

### 2.2 Pipeline 的输入与失败

Pipeline 的输入不只是 `Goal.text`，还有阶段之间的数据契约，三种传法：文本，把上一段的 `answer` 当作下一段的 `Goal.text`；结构化，把 `RunResult.metadata` 或 `state` 传给下一段，保留字段但要求约定 schema；文件引用，大结果落盘，下一段拿引用。默认文本最省事，但第二段需要上一段提取的字段时会丢信息。
Pipeline 的测试要固定每个阶段的输出，`topology.py` 用的是三个脚本化的假 Agent：

```python
stages = [make("a"), make("b"), make("c")]
team = Pipeline(stages)
result = await team.run(goal)
assert result.answer == "c"
assert [s.calls for s in stages] == [1, 1, 1]
```

第三个断言最重要，Pipeline 失败要停，继续跑会把失败当成功。停在失败阶段，调用方知道走到哪一段、为什么停；继续跑，调用方只看到最后一段的错误，前面的工作白费。失败阶段的 `error` 要带阶段名与输入，只带“执行失败”，排障时不知道是哪一段。

Pipeline 的失败要停在失败阶段，不继续，代码里只有一条判断：

```python
if result.status not in (COMPLETED, DEGRADED):
    return result
```

Pipeline 的成本是阶段成本之和，顺序执行时延迟也是阶段延迟之和。并行能降延迟，但增加预算竞争与合并复杂度，所以先测量每段的成本与延迟，再决定是否并行。顺序版本也是并行版本的对照基线。

顺序跑通、再按瓶颈并行，是 Pipeline 的施工顺序。拓扑的优化同理：先量顺序版，再量并行版，最后看成本、延迟与失败率三项值不值。单次演示只能证明能跑，不能证明值得跑，拓扑的验收最终要落在测量上。

## 三、Handoff

Handoff 把控制权交给一个 Agent，原 Agent 不再回来，代码在 `topology.py` 里：

```python
class Handoff:
    def __init__(self, agents: dict[str, Any], router) -> None:
        self.agents = dict(agents)
        self.router = router

    async def run(self, goal, session=None) -> RunResult:
        route = await self.router.route(goal)
        agent = self.agents.get(route.name)
        ...
        return await agent.run(goal, session)
```

Handoff 的关键是交接内容。只传 `goal`，接手的 Agent 不知道前一个 Agent 做了什么，要传 `Brief` 或 `State`。它适合分诊、转人工与升级，不适合多个 Agent 协作、需要中心汇总、接手后还要回来。Handoff 是控制权转移，不是任务复制。

Handoff 最常用在分诊：先判断类型，再交给专家，分诊器要轻，规则或小模型足够：

```python
routes = [
    Route("refund", accepts=["退款", "退货"]),
    Route("technical", accepts=["报错", "登录"]),
    Route("general", fallback=True),
]
```

三个工程点：分诊器要轻，不要用大模型做路由；交接要带 `Brief`，接手的 Agent 要知道为什么转给我、已经做了什么；兜底要有人接，路由失败不能抛错。分诊错误比回答错误更贵：转错部门，用户要重说一遍；转给不存在的 Agent，直接失败。分诊还要可测试，每条路由写正例与反例。
Handoff 有两种返回语义：一去不回，接手的 Agent 直接返回结果，原 Agent 结束；可回传，接手的 Agent 返回结果后原 Agent 继续处理。基座默认一去不回，可回传用 Supervisor 或 Pipeline 表达，不要给 Handoff 加回调，回调会让控制权变得模糊。

### 3.1 Handoff 的权限与上下文

Handoff 最容易出的安全问题是越权转移：普通客服不能把用户转给财务系统，外部用户不能转给内部 agent，低权限 agent 不能把上下文交给高权限 agent。权限要在 `Router` 里检查，它是分诊器，也要在 `Guard` 里检查，`Guard` 是拦截动作的那一层；不能靠接手的 agent 自己判断，它拿到请求时已经晚了。三个检查点是转出方有没有权限发起、接收方有没有权限接收、上下文里有没有不该带过去的数据。

Handoff 要传多少上下文，三种粒度：只传目标，接手的 Agent 从零开始，适合独立任务；传摘要，只带前一个 Agent 的结论，省 token 但可能丢细节；传依据，带 `context_refs` 与已完成步骤，最完整但可能超预算。推荐摘要加依据引用：摘要给方向，依据给验证。

Handoff 失败有三种：没路由、路由到不存在的 Agent、接手的 Agent 失败。没路由走 fallback 或返回 `REFUSED`；Agent 不存在是配置错误，启动时校验；接手的 Agent 失败最麻烦，控制权已经转移，原 Agent 不能假装没转，所以转移之前要确认对方可用。

## 四、Supervisor

Supervisor 是中心调度：一个调度者决定派给谁，worker 执行，调度者汇总，代码在 `topology.py` 里：

```python
class Supervisor:
    def __init__(self, workers, plan, synth=None) -> None:
        self.workers = dict(workers)
        self.plan = plan
        self.synth = synth

    async def run(self, goal, session=None) -> RunResult:
        results = {}
        for name, subtask in self.plan(goal):
            results[name] = await self.workers[name].run(Goal(text=subtask), session)
        answer = self.synth(results) if self.synth else ...
        return RunResult(status=COMPLETED, answer=answer, ...)
```

Supervisor 的关键是 `Brief`：派给 worker 的不是原始 `goal`，而是带上下文、约束、完成标准的交接单。只传 `goal.text`，worker 会重复调研、越权、跑偏。它适合研究报告、多文档处理这类需要中心汇总的任务，不适合 worker 要自由对话、或者根本没必要的单任务。

### 4.1 Supervisor 的交接与汇总

Supervisor 派活时不能只传 `goal.text`，要传 `Brief`，`topology.py` 里的构造只有几行：

```python
Brief(
    goal=goal,
    context_refs=["doc:42", "order:A1001"],
    done=["已确认订单状态"],
    forbidden=["不要改写原文"],
    deadline=time.time() + 300,
)
```

`context_refs` 是原始依据，不是结论；`done` 是已经完成的步骤；`forbidden` 是硬约束；`deadline` 是时间上限。只传结论，worker 会转述失真；只传目标，worker 会重复调研；不传 `forbidden`，worker 可能越权。Brief 的质量决定 worker 的输出质量，Supervisor 的主要工作是写清楚派什么活。
Supervisor 的最后一步是汇总，最容易失真。三种汇总：拼接，按顺序拼起来，简单但可能重复；重写，让调度者根据 worker 结果重写一份，质量高但多一次模型调用；结构化合并，worker 返回结构化字段，按字段合并，最可靠但要求约定 schema。三种都要处理缺口。

Supervisor 要决定预算怎么分。共享预算，所有 worker 共用一个 `Budget`，一个花多了其他没得花；独立预算，每人一份，总预算要提前分。基座建议共享总预算加每个 worker 上限：总预算防超支，worker 上限防单个吃光。分配要在 `plan` 里体现，分配不合理，Supervisor 会卡在一个 worker 上，其他空转。

`plan` 是 Supervisor 的核心，它决定派给谁、派什么。静态 plan 在构造时给定步骤列表，确定但不能按中间结果调整；动态 plan 每次根据 `Goal` 与 `Board` 生成，灵活但多一次规划调用；混合 plan 是静态骨架加动态补充。plan 的输出必须是 `[(worker_name, subtask)]`，不能是自然语言，自然语言的计划无法执行也无法测试。

Supervisor 的失败分两种：调度失败与 worker 失败。plan 为空、worker 不存在、subtask 为空属于调度失败，应该在派活前拒绝；worker 返回 `FAILED` 或 `REFUSED` 是正常分支，按失败策略处理。调度失败是拓扑的 bug，worker 失败是任务的正常分支。

Supervisor 的测试要固定 plan 与 worker，`topology.py` 里的测试只有一个脚本化的 plan：

```python
team = Supervisor(
    workers={"a": make("A"), "b": make("B")},
    plan=lambda goal: [("a", "任务A"), ("b", "任务B")],
    synth=lambda results: "|".join(r.answer for r in results.values()),
)
assert (await team.run(goal)).answer == "A|B"
```

三个断言：plan 按顺序执行、每个 worker 只调一次、synth 收到全部结果。再加一个失败测试：某个 worker 返回 `FAILED`，断言 Supervisor 按失败策略返回，不是静默继续。

## 五、Blackboard

Blackboard 是共享看板：多个 Agent 读写的同一块板，`reducer` 合并，`trigger` 决定什么时候停，代码在 `topology.py` 里：

```python
class Blackboard:
    def __init__(self, agents, reducer, trigger=None) -> None:
        self.agents = list(agents)
        self.reducer = reducer
        self.trigger = trigger

    async def run(self, goal, session=None) -> RunResult:
        board = {}
        for agent in self.agents:
            result = await agent.run(goal, session)
            board[agent.name] = result.answer
            if self.trigger and self.trigger(board):
                break
        return RunResult(status=COMPLETED, answer=self.reducer(board), ...)
```

Blackboard 的关键是写冲突：多个 Agent 同时写一个字段，谁赢。`reducer` 必须显式声明合并方式：追加、取最新、投票、优先级。它适合多角色评审与并行调研，不适合写冲突无法合并的场景。Blackboard 是共享状态，不是共享对话，板上是结构化结论。

### 5.1 Blackboard 的并发与合并

Blackboard 最容易出问题的是并发写。顺序写是一个 Agent 写完下一个再写，简单但没有并行；并行写要快，但要处理冲突。并行写至少要有三件：`rev` 每次写递增，写前检查版本，冲突就重试；`owner` 记录谁写的；`reducer` 是合并策略。没有这三件，并行写一定丢数据，先做顺序写，再按需并行。
Blackboard 什么时候停，三种触发：数量触发，所有 Agent 都写完了就停；质量触发，看板满足某个条件就停，比如有两个独立来源确认；预算触发，花到上限就停。三种可以叠加，只靠写完可能永远等不到，只靠质量触发可能永远不满足。触发条件要可判定，不能是模型觉得够了，这是第 23 章的老问题。
`reducer` 是 Blackboard 的核心，三种合并策略：追加，所有结论都保留；取最新，后写的覆盖先写的，适合状态更新但会丢历史；投票，多个结论取多数，适合判断类任务。三种都要处理空看板，没有结论时返回 `FAILED` 或 `REFUSED`，不能返回空字符串当成功。合并策略要显式配置，怎么合并是拓扑的事。

Blackboard 上每个字段要有 `owner`：`owner` 为空的字段谁都能写，一定冲突；`owner` 固定的字段只有 owner 能写，其他只读；`owner` 可转移的字段写之前先拿锁，写完释放。基座默认每个 worker 写自己的 key，需要共享时用 `reducer` 或显式 owner。共享字段是冲突的根源，能让每个 worker 写自己的 key，就不要共享。

Blackboard 的测试要覆盖写冲突与终止：两个 worker 写不同 key 都能保留；写同一个 key 时 `reducer` 按策略合并；trigger 满足时提前停；空看板返回 `FAILED` 而不是空字符串。四条测试对应四种失败，只测能汇总，线上遇到并发写就丢数据。

Blackboard 失败有三种：空看板返回 `FAILED`；写冲突按 `reducer` 合并，冲突无法合并时标 `DEGRADED`；trigger 不满足时达到预算或最大轮次后停，返回 `DEGRADED`。三种都要显式处理，没有 trigger 的 Blackboard 会一直跑到预算耗尽，没有冲突处理的会静默丢数据。

## 六、共用的契约

四种拓扑只依赖五个类型：`Goal` 是输入，`RunResult` 是输出，`State` 是单个 Agent 的状态，`Brief` 是 Supervisor 与 Handoff 的交接单，`Board` 是 Blackboard 的共享看板。拓扑不 import 执行器、工具、治理与预算的任何类型，它拿到的是已经 `build` 好的 `Agent`，只调用 `run`。

### 6.1 交接单 Brief

`Brief` 至少包含 `goal`、`context_refs`、`done`、`forbidden`、`deadline` 五项：原始目标、原始依据而不是结论、已经完成的步骤、不能做的事、什么时候必须停。只传 `goal.text`，worker 不知道前一个 Agent 做了什么；只传结论，worker 会转述失真，`Brief` 要带依据。

### 6.2 看板 Board

`Board` 至少包含 `state`、`rev`、`owner`：共享状态、版本号、当前写者。`rev` 不是装饰，两个 worker 同时写，`rev` 冲突要能发现；`owner` 让谁写的可追溯。

拓扑之间传 `State` 有三种方式，不能混。不传，每个 worker 从 `Goal` 重新开始，简单但不知道前文；传副本，复制一份给 worker，改了不影响外层，适合只读上下文；传引用，worker 直接改外层 `State`，并发与恢复都难，只适合顺序拓扑。基座默认不传，要上下文用 `Brief.context_refs`，要共享结论用 `Board`。

拓扑的 trace 要能串起 worker，三个字段：`trace_id` 是公共标识，整个拓扑共享；`parent_id` 让 worker 的 span 指向拓扑的 span；`topology` 记录是 `pipeline`、`handoff`、`supervisor` 还是 `blackboard`。没有这三个字段，线上只能看到四个独立的 trace，不知道谁先谁后、谁失败导致整体失败。

拓扑不应该拥有自己的业务状态，它只拥有控制状态：执行到哪、谁完成了、谁失败了。业务状态属于 worker，拓扑要读就通过 `Board` 或 `Brief`，不直接改。如果拓扑开始存订单、金额、用户偏好，它就从组合变成了业务层，换拓扑要迁数据，复用不可能。

拓扑层的预算与 Agent 层的预算要分开：拓扑层是整个多 agent 任务的预算，决定能不能再派一个 worker；Agent 层是单个 worker 的预算，决定它还能走几步。拓扑层耗尽返回 `DEGRADED` 并停止派新 worker；Agent 层耗尽时 worker 返回 `DEGRADED`，由拓扑决定是否继续。两层都要有，只靠一层，另一侧就会超支。

worker 的错误要传到顶层，三种传播：原样返回，顶层拿到 worker 的 `RunResult`，保留 `error` 与 `status`；包装，顶层加上哪个 worker 失败的信息；降级，把失败转成 `DEGRADED` 并带缺口。三种都要保留原始错误，只返回多 agent 任务失败，排障时不知道是哪个 worker、哪一步。

拓扑也需要配置，但配置很少：worker 列表、plan、reducer、trigger、失败策略。它们不要塞进 `AgentConfig`，而是拓扑的构造参数，写在 `topology.py` 的构造函数签名里：

```python
Supervisor(
    workers={"research": agent1, "write": agent2},
    plan=...,
    synth=...,
    failure_policy="degraded",
)
```

拓扑配置与 Agent 配置分开，才能独立演进：换拓扑不改 Agent 配置，换 Agent 不改拓扑配置。

## 七、替换、嵌套与失效

拓扑的验收不是四种都能跑，是换一种拓扑只改变控制权，契约在 `topology.py` 的四个类上：

| 替换 | 只应改变 | 其他必须不变 |
|---|---|---|
| Pipeline → Supervisor | 控制权从顺序变为中心 | worker 的实现、工具、Guard |
| Supervisor → Handoff | 控制权从中心变为当前 Agent | worker 的实现、工具 |
| Handoff → Blackboard | 控制权从单个 Agent 变为共享板 | worker 的实现、工具 |
| Blackboard → Pipeline | 控制权从共享板变为顺序 | worker 的实现、工具 |

测试要断言 worker 的 `run` 调用次数与结果不变，只改变谁决定下一步。如果换拓扑后 worker 的工具调用次数变了，说明拓扑在偷偷实现能力；如果 worker 的 Guard 被绕过，说明拓扑在偷偷做治理。拓扑的耦合，表现为换组合方式组件行为也变了。

拓扑的替换测试要固定 worker，只换拓扑，两份配置只差一个类：

```python
research = make("资料")
write = make("报告")

pipe = Pipeline([research, write])
supervisor = Supervisor(
    workers={"research": research, "write": write},
    plan=lambda goal: [("research", "查资料"), ("write", "写报告")],
)

r1 = await pipe.run(goal)
r2 = await supervisor.run(goal)
assert r1.status == r2.status
assert research.calls == 1  # worker 调用次数不变
```

三个断言：worker 的 `run` 调用次数不变、工具调用次数不变、Guard 决策不变。换拓扑后 worker 被多调一次，说明拓扑在重试或重复派活；Guard 决策变了，说明拓扑绕过了治理。拓扑测试看控制权，不看答案。

不是所有拓扑都能直接互换，有些替换会改变语义。Pipeline 换 Supervisor 要补 plan 与 summary，能换但要补配置；Supervisor 换 Handoff 一去不回，丢掉汇总；Handoff 换 Blackboard，一个是单个 Agent，一个是多个 Agent 写板；Blackboard 换 Pipeline 是顺序覆盖，丢掉多角色。可替换的是控制权相似的拓扑。

### 7.1 替换的判据

判断两个拓扑能不能替换，看三个条件：输入相同，都是 `Goal`；输出相同，都是 `RunResult`；控制权相似，都是顺序、中心、转移、共享之一。三个都满足才能做替换实验，有一个不满足就是两种不同的任务结构。替换实验的目的不是证明所有拓扑一样，是证明控制权可以换、能力不跟着换。

四种拓扑都实现 `run(goal, session)`，所以可以互相嵌套，嵌套只通过 `Goal` 与 `RunResult` 交互，`topology.py` 里有例子：

```python
team = Supervisor(
    workers={
        "research": Pipeline([search, read, summarize]),
        "review": Handoff([reviewer, auditor]),
    },
    plan=...,
    synth=...,
)
```

嵌套的边界：子拓扑只通过 `Goal` 与 `RunResult` 与外层交互；子拓扑不共享外层的 `State`；子拓扑的预算要显式分配；子拓扑的 trace 要带 `parent_id`。嵌套不是默认选择，能平铺就平铺，嵌套一层，trace 深一层，失败归因难一层。

### 7.2 嵌套的代价

嵌套不是免费的，每深一层多三样成本。trace 深一层：一次失败要穿过子拓扑、worker、Agent、循环四层，没有 `parent_id` 根本串不起来。预算难分：子拓扑用外层预算，一个子任务能花光整个 run；用独立预算，又要决定分多少。上下文难传：子拓扑只拿到 `Goal`，不知道外层已经做了什么。三层以上通常说明架构错了，该拆服务或该用图，见第 55 章。
一个典型的嵌套是 Supervisor 包住 Pipeline 与 Handoff：`research` 是 Pipeline，`review` 是 Handoff，外层是 Supervisor，三种拓扑各司其职，代码在 `topology.py` 里：

```python
research = Pipeline([search, read, summarize])
review = Handoff(agents={"reviewer": reviewer, "auditor": auditor}, router=...)
team = Supervisor(
    workers={"research": research, "review": review},
    plan=lambda goal: [("research", "查资料"), ("review", "审稿")],
    synth=merge,
)
```

这个结构里，外层只调 `run`，不关心内层是哪种拓扑；内层只通过 `Goal` 与 `RunResult` 交互，不读外层 `State`。外层要知道内层用了几个 agent，说明嵌套泄漏了实现。

嵌套时预算要按层分：外层是整个任务的上限，子拓扑是外层分给它的份额，worker 是子拓扑再分的份额。三层都要显式，不能共享一个全局计数器，共享会让一个子任务花光全部预算，其他饿死。分配方式可以按固定比例或任务预估，但都要在 trace 里记分了多少、用了多少。

嵌套的 trace 要能看出哪一层失败。每层加一个 `topology` 字段，每个 worker 的 span 带 `parent_id`，失败时从顶层往下查：顶层 `status=DEGRADED`，哪个子拓扑 `FAILED`，哪个 worker `FAILED`。三层信息缺一层，排障就要靠猜，trace 是树而不是列表。

什么时候嵌套，三个信号：子任务本身是一个固定流程，用 Pipeline 嵌套；子任务需要分诊，用 Handoff 嵌套；子任务需要多角色，用 Supervisor 或 Blackboard 嵌套。没有信号就不要嵌套，平铺更简单。层数控制在两层，三层以上先问是不是该拆服务或上图。

六种坏法。拓扑实现能力，Supervisor 里直接调模型、查库，换拓扑要重写能力；拓扑做治理，Handoff 里自己判断能不能转，绕过护栏；`Brief` 只带结论，worker 不知道依据；`Board` 写冲突不处理，两个 worker 同时写 `answer`，后写的覆盖先写的；拓扑共享可变的 `State`；没有终止条件，Blackboard 的 trigger 永远不满足。
拓扑失败与单 Agent 失败不同：一个 worker 失败，拓扑要决定整体怎么办。三种策略：快速失败，任何 worker 失败整体失败，适合强一致流程；部分成功，失败的 worker 跳过，其余继续，最后标注缺口，适合调研；重试或换人，失败后换一个 worker 再试，适合可替代任务。三种要显式配置，不能由拓扑默认。

### 7.3 失败策略

三种失败策略对应三种返回值。快速失败返回失败 worker 的 `RunResult`，`status` 是 `FAILED`；部分成功继续，最后 `status` 是 `DEGRADED`，`error` 记录失败的 worker；重试或换人重试一次，仍失败按前两种处理。关键是部分成功不能返回 `COMPLETED`，那会让调用方以为全部完成。失败策略不是错误处理，是交付语义。
多 agent 系统的监控比单 agent 多三个指标：worker 利用率，有多少在跑、多少空转；交接次数，Handoff 与 Supervisor 派了多少次活、是否重复；汇总缺口，多少任务以 `DEGRADED` 结束、缺了哪个 worker。三个指标对应三种浪费：空转、重复、缺口。单看总成功率看不出这些。

拓扑失败时也有降级交付：Supervisor 部分 worker 失败，交已完成的部分并标注缺口；Handoff 接手的 Agent 失败，退回分诊或转人工；Pipeline 中间阶段失败，交前几段的产出并标注停在哪；Blackboard 部分角色失败，交已有结论并标注缺哪个角色。四种降级都要返回 `DEGRADED`，带缺口说明。

拓扑的重试与 Agent 的重试不同：前者重派任务，后者重跑步骤。拓扑重试要满足三个条件：任务幂等，重派不会产生第二次副作用；worker 可替换，换一个也能做；预算足够，重试要花额外的钱。三个条件不满足就不要在拓扑层重试，让失败返回，由调用方决定。

五条边界。拓扑不跨进程，A2A 在第 34 章，本章的拓扑都在进程内；拓扑不替代队列，长任务、异步、重试在第 32 章；拓扑不替代评测，多 agent 好不好要看成功率、成本、延迟；拓扑不承诺越多越好，一个 Agent 能做的不要拆成三个；拓扑可以嵌套，但不要为了嵌套而嵌套。
拓扑在进程内，部署在进程外。单进程里四种拓扑都能直接跑；多进程时 Handoff 可以变成 A2A，Supervisor 可以变成远程调度；队列里 Pipeline 的每个阶段可以变成独立 worker；服务化后 Blackboard 可以变成共享存储。变化都不改 `run` 契约，改的是 `Runnable` 的实现。

四种拓扑怎么选，三个问题：阶段顺序固定吗，固定就 Pipeline；需要一个中心汇总吗，需要就 Supervisor；控制权要转移吗，要就 Handoff，不要就 Blackboard。三个问题覆盖大部分场景，选不出来通常是任务没拆清楚，对照在 `topology.py` 的注释里：

| 场景 | 拓扑 |
|---|---|
| 解析→分析→写报告 | Pipeline |
| 分诊→转专家 | Handoff |
| 调研→分析→汇总 | Supervisor |
| 多角色评审 | Blackboard |

拓扑选型不是哪种更先进，是控制权归谁最自然。

拓扑会随任务演进，方向是从简到繁再从繁到简。早期 Pipeline 够用，阶段固定问题少；中期加 Handoff 处理分诊、加 Supervisor 处理汇总；后期拓扑太复杂，trace 串不起来，失败归因难，这时该拆服务或用图，见第 55 章，而不是再加一层拓扑。复杂度超过任务需要，维护成本会吃掉收益。

拓扑的测试分三层：组合冒烟，四种拓扑各跑一次，断言 `status` 与 `answer`；控制权，换拓扑断言 worker 调用次数与结果不变；失败，让一个 worker 失败，断言拓扑按配置快速失败或部分成功。三层对应能不能跑、换组合有没有副作用、异常时交付什么。测试不需要真实模型，`FakeModel` 是脚本化的假模型。

拓扑的边界是组合，不是能力：不实现工具，工具在 worker 里；不实现检索，检索在 worker 的 Knowledge；不实现审批，审批在 worker 的 Guard；不实现模型，模型在 worker 的 Actor。越过这条线，拓扑就会变成一个大 Agent，组件封装就白做了。拓扑越薄，组合越自由。

这一版拓扑只有四种、都在进程内，下一版会遇到跨进程、动态编排与图。三个都不应该直接改四种拓扑：跨进程定义 `RemoteAgent`，它是一个实现 `run` 的远程客户端，拓扑不变；动态编排把 `plan` 变成可插拔策略，拓扑不变；图在第 55 章单独实现，两者可以互相嵌套。

卷 12 六章到这里结束：48 章讲为什么切、边界在哪，49 章讲组件之间传什么，50 章讲主体层怎么推进，51 章讲横切件怎么挂，52 章讲怎么装成一个 Agent，53 章讲多个 Agent 怎么组合，是一条线：边界、契约、实现、装配、组合。卷 12 是副线，可以跳过；但跳过它，第 54–59 章的深水区就只能看热闹。

---

## 这一章建立的 7 件事

1. 拓扑只组合 `Agent`，不实现能力、治理、主体策略。
2. Pipeline 是固定顺序；Handoff 是控制权转移；Supervisor 是中心调度；Blackboard 是共享看板。
3. 四种拓扑的差别是“控制权归谁”，不是“组件不同”。
4. `Brief` 要带原始依据，`Board` 要带 `rev`/`owner`；只传结论会转述失真。
5. 换拓扑只应改变控制权；worker 的实现、工具、Guard 必须不变。
6. 拓扑可以嵌套，但子拓扑只通过 `Goal`/`RunResult` 交互，不共享外层 `State`。
7. 拓扑不跨进程、不替代队列、不替代评测；一个 Agent 能做的，不要拆成三个。

## 下一章

卷 12 到此结束。六章从“为什么切”讲到“怎么装”，再到“怎么组合”。

下一卷进入深水区：第 54 章循环工程、第 55 章图工程、第 56 章编码 agent、第 57 章计算机操作 agent、第 58 章 GraphRAG、第 59 章 LLM Wiki。它们不再讲“怎么装一个通用 Agent”，而是讲“某一种形态/知识路线做到极致时，工程上还要补什么”。

---

[← 第 52 章 · 装配与验证：build 与五个预设六个例子](./52-装配与验证-build与五个预设六个例子.md)　｜　[卷 12 目录](./docs/INDEX.md#vol12)　｜　[第 54 章 · 循环工程：一个 agent 的控制结构 →](./54-循环工程-一个agent的控制结构.md)
