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
[六、共用契约](#六共用契约)\
[七、替换实验](#七替换实验)\
[八、嵌套](#八嵌套)\
[九、会怎么坏](#九会怎么坏)\
[十、边界](#十边界)\
[这一章建立的 7 件事](#这一章建立的-7-件事)

## 一、拓扑只组合 Agent

前五章把单个 Agent 装好了：分派、主体、校验、治理、供给、装配。本章只剩一个问题：多个 Agent 怎么连。

答案不是“再写一个更大的 Agent”，而是拓扑：

```text
拓扑( Agent[] )
```

拓扑只做三件事：

- 决定有几个 Agent；
- 决定谁先跑、谁能并行；
- 决定上下文怎么过去。

它不做四件事：

- 不实现能力（工具、检索、模型调用）；
- 不实现治理（Guard、Budget、Tracer）；
- 不实现主体策略（ReAct、Workflow、P&E）；
- 不改变单个 Agent 的循环。

这条边界就是第 33 章讲的“拓扑是系统层，不是 agent 层”。本章用代码把它落下来。

### 1.1 四种拓扑

四种拓扑对应四种控制权：

| 拓扑 | 控制权 | 适合 |
|---|---|---|
| Pipeline | 固定顺序 | 阶段明确、无分支 |
| Handoff | 当前 Agent | 分诊、转交 |
| Supervisor | 中心调度者 | 任务可拆分、需要汇总 |
| Blackboard | 共享看板 | 多角色协作、写冲突 |

四种拓扑的代码都在 `topology.py`，只 import `Goal`、`RunResult`、`SessionRef`，不 import 任何组件。

### 1.2 拓扑与编排的区别

“编排”和“拓扑”常被混用。两者的区别是“谁决定下一步”。

- **编排**（第 22 章）是单个 Agent 内部的三层：分派、主体、校验；
- **拓扑**是多个 Agent 之间的连接方式。

编排决定“这个 Agent 怎么走”；拓扑决定“几个 Agent 谁先走、谁指挥谁”。

一个任务可以只有编排、没有拓扑（单 Agent）；也可以有拓扑、没有复杂编排（每个 worker 都是简单 ReAct）。

两者不能互相替代：

- 单 Agent 编排再好，也解决不了“多个角色协作”；
- 拓扑再复杂，也解决不了“一个 Agent 内部决策混乱”。

**编排是纵向，拓扑是横向。** 先有纵向的 Agent，才有横向的拓扑。

### 1.3 拓扑的输入输出

四种拓扑的输入输出必须一致：

```text
run(Goal, SessionRef | None) -> RunResult
```

一致的输入输出带来三个好处：

- 拓扑可以互相嵌套；
- 测试可以用同一套 `Goal`/`RunResult`；
- 调用方不需要知道内部是哪种拓扑。

如果某个拓扑的 `run` 返回 `dict` 或 `str`，它就不能嵌套，也不能被统一测试。**拓扑的契约比拓扑的实现重要。**

### 1.4 拓扑与框架

LangGraph、AutoGen、CrewAI 都提供拓扑；基座的拓扑与它们不冲突。

三种关系：

- **替代**：基座拓扑够用，不用框架；
- **嵌套**：基座 Agent 作为框架图的一个节点；
- **对照**：同一任务，用框架与基座各搭一遍，比较可维护性。

不要为了“用框架”而用框架。拓扑的核心是控制权，不是 API；API 可以换，控制权不能乱。

**框架提供运行时，基座提供契约。** 两者可以共存，不能互相替代。

## 二、Pipeline

Pipeline 是最简单的拓扑：阶段按顺序执行，上一阶段的答案作为下一阶段的输入。

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

Pipeline 的优点是确定性：阶段顺序写死，每一段都可检查点，失败只重跑一段。

它的缺点是“阶段之间只能传文本”。如果第二段需要第一段的结构化结果，Pipeline 要在 `Goal.metadata` 或 `State` 里传，不能只传 `answer`。

Pipeline 适合：

- 解析 → 分析 → 写报告；
- 检索 → 生成 → 校验；
- 固定 ETL 流程。

Pipeline 不适合：

- 阶段数不固定；
- 下一段跑不跑取决于上一段结果；
- 需要多个 Agent 并行。

**Pipeline 不是“多 agent”，是“一个任务切成固定阶段”。** 阶段可以是 Agent，也可以是普通函数；拓扑不关心。

### 2.1 Pipeline 的接口

Pipeline 的阶段只要实现 `run(goal, session) -> RunResult` 即可。

Agent 实现了这个接口；普通函数可以用一个小适配器包一下：

```python
class FunctionStage:
    name = "function"
    def __init__(self, fn): self.fn = fn
    async def run(self, goal, session=None):
        return RunResult(status=RunStatus.COMPLETED, answer=self.fn(goal.text))
```

这样 Pipeline 不依赖 Agent 类型，只依赖 `Runnable` 契约。阶段可以是 Agent、函数、子拓扑。

Pipeline 的合并逻辑也要显式：

- 成功：返回最后一个阶段的 `RunResult`；
- 失败：立即返回失败阶段的结果，不继续；
- 降级：继续，但记录缺口。

三种处理对应三种 `status`；不处理，Pipeline 会把失败当成功继续跑。

### 2.2 Pipeline 的检查点

Pipeline 的检查点要记“跑到第几阶段”，不是“跑到第几步”。

```text
state.data["pipeline"] = {"index": 2, "results": [...]}
```

恢复时从 `index` 开始，不用重跑前两段。前两段的结果要存，否则第三段拿不到输入。

Pipeline 的检查点与 Agent 的检查点要分开：Agent 存自己的 `step_index`，Pipeline 存阶段索引。两者混在一起，恢复时不知道从哪一层继续。

**Pipeline 的恢复单位是阶段，Agent 的恢复单位是步骤。** 单位不同，检查点不能共用。

### 2.3 Pipeline 的并行

Pipeline 默认顺序，但阶段之间如果没有依赖，可以并行。

并行的条件：

- 两个阶段不共享输入；
- 两个阶段没有先后依赖；
- 合并策略能处理并发结果。

并行带来两个问题：预算竞争与 trace 顺序。预算要提前分，trace 要有 `parent_id`。

不要为了“快”强行并行。阶段之间的依赖通常比看起来多；先顺序跑通，再按测量结果并行。

**Pipeline 的价值是确定，不是快。** 需要快，先看阶段能不能合并，而不是先并行。

### 2.4 Pipeline 的输入

Pipeline 的输入不只是 `Goal.text`，还有阶段之间的数据契约。

三种传法：

- **文本**：上一段的 `answer` 作为下一段的 `Goal.text`；最简单，但丢结构。
- **结构化**：上一段的 `RunResult.metadata` 或 `state` 作为下一段的输入；保留字段，但要求阶段约定 schema。
- **文件/引用**：大结果落盘，下一段拿引用；适合长文档、图片。

三种传法要显式选择。默认文本最省事，但第二段需要“上一段提取的字段”时，文本会丢信息。

**Pipeline 的耦合点不在代码，在阶段之间的数据形状。** 形状不约定，第二段只能重新解析文本。

### 2.5 Pipeline 的测试

Pipeline 的测试要固定每个阶段的输出。

```python
stages = [make("a"), make("b"), make("c")]
team = Pipeline(stages)
result = await team.run(goal)
assert result.answer == "c"
assert [s.calls for s in stages] == [1, 1, 1]
```

三个断言：

- 最终答案来自最后一个阶段；
- 每个阶段只调用一次；
- 中间失败时后续阶段不调用。

第三个断言最重要：Pipeline 失败要停，不能继续跑；继续跑会把失败当成功。

### 2.6 Pipeline 的失败

Pipeline 的失败要停在失败阶段，不继续。

```python
if result.status not in (COMPLETED, DEGRADED):
    return result
```

停在失败阶段，调用方知道“走到哪一段、为什么停”；继续跑，调用方只看到最后一段的错误，前面的工作白费。

失败阶段的 `error` 要带阶段名与输入；只带“执行失败”，排障时不知道是哪一段。

**Pipeline 的失败是“阶段失败”，不是“整体失败”。** 保留阶段信息，才能重跑。

### 2.7 Pipeline 的成本

Pipeline 的成本是阶段成本之和，延迟是阶段延迟之和（顺序时）。

顺序执行简单，但总延迟高；并行能降延迟，但增加预算竞争与合并复杂度。

先测量每个阶段的成本与延迟，再决定是否并行。没有测量，并行只是把问题藏起来。先顺序跑通，再按瓶颈并行；这是 Pipeline 的施工顺序。顺序版本也是并行版本的对照基线，没有基线就不知道并行有没有变快。基线不是保守，是测量的前提。没有基线，所有“优化”都只是感觉。拓扑的优化也一样：先量顺序版，再量并行版，最后决定值不值。值不值，看成本、延迟与失败率三项，不看单次演示。单次演示只能证明“能跑”，不能证明“值得跑”。拓扑的验收，最终要落在测量上。没有测量，拓扑选型只能靠偏好；偏好可以争论，测量不能。下一章进入深水区，先看循环工程。这是卷十二的收口，也是深水区的入口。

## 三、Handoff

Handoff 把控制权交给一个 Agent，原 Agent 不再回来。

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

Handoff 的关键是“交接内容”。只传 `goal`，接手的 Agent 不知道前一个 Agent 做了什么；要传 `Brief` 或 `State`。

Handoff 适合：

- 分诊：先判断类型，再交给专家；
- 转人工：AI 处理不了，交给人工；
- 升级：普通客服转 expert。

Handoff 不适合：

- 需要多个 Agent 协作；
- 需要中心汇总；
- 接手后还要回来。

**Handoff 是“控制权转移”，不是“任务复制”。** 转移后原 Agent 不再参与；需要回来，用 Supervisor 或 Pipeline。

### 3.1 Handoff 的分诊

Handoff 最常用在分诊：先判断类型，再交给专家。

```python
routes = [
    Route("refund", accepts=["退款", "退货"]),
    Route("technical", accepts=["报错", "登录"]),
    Route("general", fallback=True),
]
```

三个工程点：

- **分诊器要轻**：不要用大模型做路由；规则或小模型足够。
- **交接要带 Brief**：接手的 Agent 要知道“为什么转给我、已经做了什么”。
- **兜底要有人接**：`general` 或人工；不能路由失败就抛错。

分诊错误比回答错误更贵：转错部门，用户要重复一遍；转给不存在的 Agent，直接失败。分诊要可测试：每条路由写正例/反例。

### 3.2 Handoff 的返回

Handoff 有两种返回语义：一去不回，和可回传。

- **一去不回**：接手的 Agent 直接返回结果，原 Agent 结束；适合转人工、转专家。
- **可回传**：接手的 Agent 返回结果，原 Agent 继续处理；适合“专家给建议，主 Agent 汇总”。

基座默认“一去不回”；可回传用 Supervisor 或 Pipeline 表达，不要给 Handoff 加回调。回调会让控制权变得模糊：到底谁负责最终结果？

**Handoff 的语义越简单，越多 agent 系统越容易推理。** 一去不回是默认，可回传是另一种拓扑。

### 3.3 Handoff 的权限

Handoff 最容易出的安全问题是“越权转移”。

- 普通客服不能把用户转给财务系统；
- 外部用户不能转给内部 agent；
- 低权限 agent 不能把上下文交给高权限 agent。

权限要在 Handoff 的 `Router` 或 `Guard` 里检查，不能靠“接手的 agent 自己判断”。接手的 agent 拿到请求时，已经晚了。

三个检查点：

- 转出方：有没有权限发起转移；
- 接收方：有没有权限接收这类请求；
- 上下文：有没有不该带过去的数据。

**Handoff 是权限边界，不是简单的函数调用。** 不检查，等于把权限控制交给路由器。

### 3.4 Handoff 的上下文

Handoff 要传多少上下文？三种粒度。

- **只传目标**：接手的 Agent 从零开始；适合独立任务，但用户要重复。
- **传摘要**：传前一个 Agent 的结论；省 token，但可能丢关键细节。
- **传依据**：传 `context_refs` 与已完成步骤；最完整，但上下文可能超预算。

推荐“摘要 + 依据引用”：给接手的 Agent 一份简短摘要，加上可查的原始引用。它需要细节时能查，不需要时不占窗口。

只传摘要，接手的 Agent 无法验证；只传依据，窗口会被撑爆。**摘要给方向，依据给验证。**

### 3.5 Handoff 的失败

Handoff 失败有三种：没路由、路由到不存在的 Agent、接手的 Agent 失败。

三种处理：

- 没路由：走 fallback，或返回 `REFUSED`；
- Agent 不存在：配置错误，启动时校验；
- 接手的 Agent 失败：原 Agent 已退出，只能返回失败或转人工。

第三种最麻烦：控制权已经转移，原 Agent 不能“假装没转”。所以 Handoff 之前要确认接手的 Agent 可用；不可用就不要转。

**Handoff 是单向门。** 转出去之前，先确认门后有人。

## 四、Supervisor

Supervisor 是中心调度：一个调度者决定派给谁，worker 执行，调度者汇总。

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

Supervisor 的关键是“Brief”：派给 worker 的不是原始 `goal`，而是带上下文、约束、完成标准的交接单。只传 `goal.text`，worker 会重复调研、越权、跑偏。

Supervisor 适合：

- 研究报告：调研 → 分析 → 写作；
- 多文档处理：每个 worker 处理一部分；
- 需要中心汇总的任务。

Supervisor 不适合：

- worker 之间需要自由对话；
- 调度逻辑本身很复杂，Plan 写不出来；
- 单任务，不需要拆分。

**Supervisor 是“中心控制”，Handoff 是“控制权转移”。** 两者的差别不是代码，是控制权归谁。

### 4.1 Supervisor 的 Brief

Supervisor 派活时，不能只传 `goal.text`。要传 `Brief`：

```python
Brief(
    goal=goal,
    context_refs=["doc:42", "order:A1001"],
    done=["已确认订单状态"],
    forbidden=["不要改写原文"],
    deadline=time.time() + 300,
)
```

`context_refs` 是原始依据，不是结论；`done` 是已经完成的步骤；`forbidden` 是硬约束；`deadline` 是时间上限。

只传结论，worker 会转述失真；只传目标，worker 会重复调研；不传 forbidden，worker 可能越权。

**Brief 的质量，决定 worker 的输出质量。** Supervisor 的主要工作不是“派活”，是“写清楚派什么活”。

### 4.2 Supervisor 的汇总

Supervisor 的最后一步是汇总，最容易失真。

三种汇总：

- **拼接**：把 worker 的答案按顺序拼起来；简单，但可能重复、矛盾。
- **重写**：让调度者根据 worker 结果重写一份；质量高，但多一次模型调用。
- **结构化合并**：worker 返回结构化字段，调度者按字段合并；最可靠，但要求 worker 输出 schema。

三种都要处理“缺口”：某个 worker 失败，汇总要标注，不能假装完整。

**汇总不是“把答案拼起来”，是“决定以什么结构交回”。** 结构在 `Brief` 里就要约定，不能等最后再猜。

### 4.3 Supervisor 的预算

Supervisor 要决定预算怎么分给 worker。

两种方式：

- **共享预算**：所有 worker 共用一个 `Budget`；一个 worker 花多了，其他 worker 没得花。
- **独立预算**：每个 worker 一份；总预算要提前分，分少了 worker 做不完，分多了浪费。

基座建议“共享总预算 + 每个 worker 上限”。总预算防超支，worker 上限防单个 worker 吃光。

预算分配要在 `plan` 里体现：哪个 worker 分多少、预计几步。分配不合理，Supervisor 会在某个 worker 上卡住，其他 worker 空转。

**Supervisor 的调度，本质是预算调度。** 不分配预算，调度只是派活。

### 4.4 Supervisor 的 plan

`plan` 是 Supervisor 的核心：它决定派给谁、派什么。

三种 plan：

- **静态 plan**：构造时给定步骤列表；确定，但不能根据中间结果调整。
- **动态 plan**：每次根据 `Goal`/`Board` 生成；灵活，但多一次规划调用。
- **混合 plan**：静态骨架 + 动态补充；适合大部分流程固定、少数分支开放。

plan 的输出必须是 `[(worker_name, subtask)]`，不能是自然语言。自然语言计划无法执行，也无法测试。

plan 的失败要显式：worker 不存在、subtask 为空、计划为空，都要返回 `FAILED` 或 `REFUSED`，不能静默跳过。

**Supervisor 的可测试性，取决于 plan 是不是数据。** plan 是数据，就能单测；plan 是模型输出的一段话，就只能集成测。

### 4.5 Supervisor 的失败

Supervisor 的失败分两种：调度失败与 worker 失败。

- 调度失败：plan 为空、worker 不存在、subtask 为空；应该在派活前拒绝。
- worker 失败：某个 worker 返回 `FAILED`/`REFUSED`；按失败策略处理。

两种失败的归属不同：调度失败是拓扑的 bug，worker 失败是任务的正常分支。

**Supervisor 要把“我的错”和“worker 的错”分开报。** 混在一起，排障时不知道改拓扑还是改 worker。

### 4.6 Supervisor 的测试

Supervisor 的测试要固定 plan 与 worker。

```python
team = Supervisor(
    workers={"a": make("A"), "b": make("B")},
    plan=lambda goal: [("a", "任务A"), ("b", "任务B")],
    synth=lambda results: "|".join(r.answer for r in results.values()),
)
assert (await team.run(goal)).answer == "A|B"
```

三个断言：plan 按顺序执行、每个 worker 只调一次、synth 收到全部结果。

再加一个失败测试：某个 worker 返回 `FAILED`，断言 Supervisor 按失败策略返回，不是静默继续。

## 五、Blackboard

Blackboard 是共享看板：多个 Agent 读写同一块板，reducer 合并，trigger 决定什么时候停。

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

Blackboard 的关键是“写冲突”：多个 Agent 同时写一个字段，谁赢？`reducer` 必须显式声明合并方式：追加、取最新、投票、优先级。

Blackboard 适合：

- 多角色评审：每个角色写意见，最后汇总；
- 并行调研：每个 worker 写发现，最后合并；
- 需要保留所有中间结论。

Blackboard 不适合：

- 写冲突无法合并；
- 需要严格顺序；
- 一个 Agent 的输出会覆盖另一个的关键结论。

**Blackboard 是“共享状态”，不是“共享对话”。** 板上的内容是结构化结论，不是聊天记录。

### 5.1 Blackboard 的并发

Blackboard 最容易出问题的是并发写。

两种实现：

- **顺序写**：一个 Agent 写完，下一个再写；简单，但没有并行。
- **并行写**：多个 Agent 同时写；快，但要处理冲突。

并行写至少要三件：

- `rev`：每次写递增；写前检查版本，冲突就重试；
- `owner`：记录谁写的；冲突时知道找谁；
- `reducer`：合并策略；追加、取最新、投票、优先级。

没有这三件，并行写一定丢数据。顺序写虽然慢，但至少不丢；先做顺序写，再按需并行。

**Blackboard 的价值是“保留所有中间结论”，不是“让 Agent 互相聊天”。** 聊天记录不是看板，结论才是。

### 5.2 Blackboard 的触发

Blackboard 什么时候停？三种触发：

- **数量触发**：所有 Agent 都写完了，停；
- **质量触发**：看板满足某个条件（比如有两个独立来源确认），停；
- **预算触发**：花到上限，停。

三种触发可以叠加。只靠“所有 Agent 写完”，可能永远等不到；只靠“质量触发”，可能永远不满足。

触发条件要可判定，不能是“模型觉得够了”。模型说够了，不等于够了；这是第 23 章的老问题。

**Blackboard 的终止条件，必须是数据条件，不是模型自评。**

### 5.3 Blackboard 的合并

`reducer` 是 Blackboard 的核心。三种合并策略：

- **追加**：所有结论都保留，最后拼起来；适合调研、评审。
- **取最新**：后写的覆盖先写的；适合状态更新，但会丢历史。
- **投票**：多个结论投票，取多数；适合判断类任务。

三种策略都要处理“空看板”：没有结论时返回 `FAILED` 或 `REFUSED`，不能返回空字符串当成功。

合并策略要显式配置，不能由 Agent 自己决定。Agent 只负责写，怎么合并是拓扑的事。

**Blackboard 的价值在“所有结论都保留”，合并策略决定“怎么读”。** 两者分开，板才不会变成垃圾桶。

### 5.4 Blackboard 的所有权

Blackboard 上每个字段要有 owner。

- `owner` 为空的字段：谁都能写，一定冲突；
- `owner` 固定的字段：只有 owner 能写，其他只读；
- `owner` 可转移的字段：写之前先拿锁，写完释放。

基座默认每个 worker 写自己的 key，不共享 key；需要共享时，用 `reducer` 或显式 owner。

**共享字段是冲突的根源。** 能让每个 worker 写自己的 key，就不要共享一个 key。

### 5.5 Blackboard 的测试

Blackboard 的测试要覆盖写冲突与终止。

- 两个 worker 写不同 key：都能保留；
- 两个 worker 写同一个 key：reducer 按策略合并；
- trigger 满足：提前停；
- 空看板：返回 `FAILED`，不是空字符串。

四条测试对应四种失败。只测“能汇总”，线上遇到并发写就丢数据。

### 5.6 Blackboard 的失败

Blackboard 失败有三种：空看板、写冲突、trigger 不满足。

- 空看板：返回 `FAILED`，不返回空字符串；
- 写冲突：按 reducer 合并，冲突无法合并时标 `DEGRADED`；
- trigger 不满足：达到预算/最大轮次后停，返回 `DEGRADED`。

三种都要显式处理。没有 trigger 的 Blackboard，会一直跑到预算耗尽；没有冲突处理的，会静默丢数据。

## 六、共用契约

四种拓扑只依赖四个类型：`Goal`、`RunResult`、`State`、`Brief`/`Board`。

- `Goal`：输入；
- `RunResult`：输出；
- `State`：单个 Agent 的状态；
- `Brief`：Supervisor/Handoff 的交接单；
- `Board`：Blackboard 的共享看板。

拓扑不 import `Actor`、`Tools`、`Guard`、`Budget`。它拿到的是已经 `build` 好的 `Agent`，只调用 `run`。

这条约束让拓扑可替换：换一种拓扑，只改组合方式，组件一行不改。

### 6.1 交接单 Brief

`Brief` 至少包含：

- `goal`：原始目标；
- `context_refs`：原始依据，不是结论；
- `done`：已经完成的步骤；
- `forbidden`：不能做的事；
- `deadline`：什么时候必须停。

只传 `goal.text`，worker 不知道前一个 Agent 做了什么；只传结论，worker 会转述失真。**Brief 要带依据，不是带摘要。**

### 6.2 看板 Board

`Board` 至少包含：

- `state`：共享状态；
- `rev`：版本号，用于并发写检测；
- `owner`：当前写者。

`rev` 不是装饰：两个 worker 同时写，`rev` 冲突要能发现；`owner` 让“谁写的”可追溯。

### 6.3 State 怎么传

拓扑之间传 `State` 有三种方式，不能混。

**第一种：不传。** 每个 worker 从 `Goal` 重新开始；简单，但 worker 不知道前文。

**第二种：传副本。** 把外层 `State` 复制一份给 worker；worker 改了不影响外层。适合只读上下文。

**第三种：传引用。** worker 直接改外层 `State`；灵活，但并发与恢复都难。只适合顺序拓扑。

基座默认“不传”，需要上下文时用 `Brief.context_refs`；需要共享结论时用 `Board`。**不要把外层 `State` 直接塞给 worker**，那会让 worker 依赖外层的实现。

### 6.4 拓扑的 trace

拓扑的 trace 要能串起 worker。

三个字段：

- `trace_id`：整个拓扑共享；
- `parent_id`：worker 的 span 指向拓扑的 span；
- `topology`：`pipeline`/`handoff`/`supervisor`/`blackboard`。

没有这三个字段，线上只能看到四个独立的 Agent trace，不知道谁先谁后、谁失败导致整体失败。

拓扑的 trace 不是“多打日志”，是“让控制权可追溯”。**控制权是拓扑唯一的产出，trace 必须记录它。**

### 6.5 拓扑与状态

拓扑不应该拥有自己的业务状态。它只拥有“控制状态”：执行到哪、谁完成了、谁失败了。

业务状态属于 worker；拓扑要读，通过 `Board` 或 `Brief`，不直接改。

如果拓扑开始存业务字段（订单、金额、用户偏好），它就从“组合”变成了“业务层”；换拓扑要迁数据，复用不可能。

**拓扑的状态是控制状态，不是业务状态。** 两者混在一起，拓扑就不可替换。

### 6.6 拓扑与预算

拓扑层的预算与 Agent 层的预算要分开。

- 拓扑层：整个多 agent 任务的预算；决定能不能再派一个 worker。
- Agent 层：单个 worker 的预算；决定这个 worker 能走几步。

拓扑层预算耗尽，返回 `DEGRADED`，不再派新 worker；Agent 层预算耗尽，worker 返回 `DEGRADED`，拓扑决定是否继续。

两层预算都要有，不能只靠一层。只有拓扑层，worker 可能内部超支；只有 Agent 层，整体可能超支。

**预算是拓扑的调度资源。** 不分配预算，Supervisor 的 plan 只是愿望。

### 6.7 拓扑的错误传播

worker 的错误要传到顶层，不能吞掉。

三种传播：

- **原样返回**：顶层拿到 worker 的 `RunResult`，保留 `error`/`status`；
- **包装**：顶层加“哪个 worker 失败”的信息，再返回；
- **降级**：顶层把失败转成 `DEGRADED`，带缺口。

三种都要保留原始错误。只返回“多 agent 任务失败”，排障时不知道是哪个 worker、哪一步。

**错误传播不是“往上抛”，是“带上上下文往上交”。** 上下文丢了，顶层只能猜。

### 6.8 拓扑的配置

拓扑也需要配置，但配置很少：worker 列表、plan、reducer、trigger、失败策略。

这些配置不要塞进 `AgentConfig`；它们是拓扑的构造参数。`AgentConfig` 只描述单个 Agent，拓扑配置描述组合。

```python
Supervisor(
    workers={"research": agent1, "write": agent2},
    plan=...,
    synth=...,
    failure_policy="degraded",
)
```

拓扑配置与 Agent 配置分开，才能独立演进：换拓扑不改 Agent 配置，换 Agent 不改拓扑配置。

## 七、替换实验

拓扑的验收不是“四种都能跑”，是“换一种拓扑，只改变控制权”。

| 替换 | 只应改变 | 其他必须不变 |
|---|---|---|
| Pipeline → Supervisor | 控制权从顺序变为中心 | worker 的实现、工具、Guard |
| Supervisor → Handoff | 控制权从中心变为当前 Agent | worker 的实现、工具 |
| Handoff → Blackboard | 控制权从单个 Agent 变为共享板 | worker 的实现、工具 |
| Blackboard → Pipeline | 控制权从共享板变为顺序 | worker 的实现、工具 |

测试要断言“worker 的 `run` 调用次数与结果不变”，只改变“谁决定下一步”。

如果换拓扑后 worker 的工具调用次数变了，说明拓扑在偷偷实现能力；如果换拓扑后 worker 的 Guard 被绕过，说明拓扑在偷偷做治理。

**拓扑的耦合，表现为“换组合方式，组件行为也变了”。**

### 7.1 替换测试怎么写

拓扑的替换测试要固定 worker，只换拓扑。

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

三个断言：

- worker 的 `run` 调用次数不变；
- worker 的工具调用次数不变；
- worker 的 Guard 决策不变。

如果换拓扑后 worker 被多调了一次，说明拓扑在重试或重复派活；如果 Guard 决策变了，说明拓扑绕过了治理。

**拓扑测试看“控制权”，不看“答案”。** 答案一样不代表拓扑对；控制权一样才说明组合没改能力。

### 7.2 替换的边界

不是所有拓扑都能直接互换。有些替换会改变语义。

- Pipeline → Supervisor：后者需要 plan、summary，语义变了；能换，但要补配置。
- Supervisor → Handoff：后者一去不回，丢掉汇总；不能直接换。
- Handoff → Blackboard：前者单个 Agent，后者多个 Agent 写板；不能直接换。
- Blackboard → Pipeline：后者顺序覆盖，丢掉多角色；不能直接换。

可替换的是“控制权相似”的拓扑；语义不同的拓扑，替换要先改任务契约。

**替换实验不是“所有拓扑都能互换”，是“换一种控制权，只改变控制权”。** 语义都变了，就不是替换，是重写。

### 7.3 替换的判据

判断两个拓扑能不能替换，看三个条件。

- 输入相同：都是 `Goal`；
- 输出相同：都是 `RunResult`；
- 控制权相似：都是顺序/中心/转移/共享之一。

三个条件都满足，才能做替换实验；有一个不满足，就是两种不同的任务结构。

替换实验的目的不是“证明所有拓扑一样”，是“证明控制权可以换，能力不跟着换”。

## 八、嵌套

四种拓扑都实现 `run(goal, session)`，所以可以互相嵌套。

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

嵌套的边界：

- 子拓扑只通过 `Goal`/`RunResult` 与外层交互；
- 子拓扑不共享外层的 `State`；
- 子拓扑的预算要显式分配；
- 子拓扑的 trace 要带 `parent_id`。

嵌套不是默认选择。能平铺就平铺；嵌套一层，trace 深一层，失败归因难一层。

### 8.1 嵌套的代价

嵌套不是免费的。每深一层，多三样成本。

**第一，trace 深一层。** 一次失败要穿过子拓扑、worker、Agent、循环四层；没有 `parent_id`，根本串不起来。

**第二，预算难分。** 子拓扑用外层预算，一个子任务能花光整个 run；子拓扑用独立预算，又要决定分多少。

**第三，上下文难传。** 子拓扑只拿到 `Goal`，不知道外层已经做了什么；要传 `Brief`，但 `Brief` 太大会挤占 worker 的窗口。

三层以上，通常说明架构错了：要么该拆服务，要么该用图（第 55 章），而不是继续套拓扑。

**嵌套是组合，不是分层。** 组合可以，分层要谨慎。

### 8.2 嵌套的例子

一个典型的嵌套：

```python
research = Pipeline([search, read, summarize])
review = Handoff(agents={"reviewer": reviewer, "auditor": auditor}, router=...)
team = Supervisor(
    workers={"research": research, "review": review},
    plan=lambda goal: [("research", "查资料"), ("review", "审稿")],
    synth=merge,
)
```

这个结构里，`research` 是 Pipeline，`review` 是 Handoff，外层是 Supervisor。三种拓扑各司其职。

嵌套的验收：外层只调 `run`，不关心内层是哪种拓扑；内层只通过 `Goal`/`RunResult` 交互，不读外层 `State`。

如果外层需要知道“内层用了几个 agent”，说明嵌套泄漏了实现；如果内层需要读外层预算，说明预算没有显式分配。

### 8.3 嵌套的预算

嵌套时，预算要按层分。

- 外层预算：整个任务的上限；
- 子拓扑预算：外层分给它的份额；
- worker 预算：子拓扑再分给 worker 的份额。

三层预算都要显式，不能共享一个全局计数器。共享计数器会让一个子任务花光全部预算，其他子任务饿死。

分配方式可以是固定比例、按历史消耗、按任务预估；无论哪种，都要在 trace 里记录“分了多少、用了多少”。

**预算分配是嵌套拓扑的核心工作。** 不分配，嵌套只是把复杂度藏起来。

### 8.4 嵌套的 trace

嵌套的 trace 要能看出“哪一层失败”。

每层加一个 `topology` 字段：`pipeline`/`supervisor`/`handoff`/`blackboard`；每个 worker 的 span 带 `parent_id`。

失败时，从顶层往下查：顶层 `status=DEGRADED`，哪个子拓扑 `FAILED`，哪个 worker `FAILED`。三层信息缺一层，排障就要靠猜。

**嵌套的 trace 是树，不是列表。** 列表只能看到“发生了什么”，树才能看到“谁导致谁”。

### 8.5 嵌套的选型

什么时候嵌套？三个信号。

- 子任务本身是一个固定流程：用 Pipeline 嵌套；
- 子任务需要分诊：用 Handoff 嵌套；
- 子任务需要多角色：用 Supervisor/Blackboard 嵌套。

三个信号对应三种子结构。没有信号，就不要嵌套；平铺更简单。

嵌套的层数控制在两层。三层以上，先问“是不是该拆服务或上图”，而不是继续套。

## 九、会怎么坏

**第一，拓扑实现能力。** Supervisor 里直接调模型、查库；换拓扑要重写能力。

**第二，拓扑做治理。** Handoff 里自己判断“能不能转”，绕过 Guard；治理分散在拓扑里。

**第三，Brief 只带结论。** worker 拿到“已确认可退”，不知道依据；出错无法回溯。

**第四，Board 写冲突不处理。** 两个 worker 同时写 `answer`，后写的覆盖先写的；结论丢一半。

**第五，拓扑共享可变 State。** 子 Agent 直接改外层 `State`；换拓扑就坏。

**第六，没有终止条件。** Blackboard 的 trigger 永远不满足，循环跑不完；Supervisor 的 plan 无限长。

### 9.1 拓扑的失败分类

拓扑失败与单 Agent 失败不同：一个 worker 失败，拓扑要决定“整体怎么办”。

三种策略：

- **快速失败**：任何 worker 失败，整体失败；适合强一致流程。
- **部分成功**：失败的 worker 跳过，其余继续；最后标注缺口；适合调研。
- **重试/换人**：失败后换一个 worker 或重试；适合可替代任务。

三种策略要显式配置，不能由拓扑默认。默认“快速失败”最安全，但会丢掉已完成的部分；默认“部分成功”最宽容，但可能把失败当成功。

**拓扑的失败策略，决定多 agent 系统在异常时的行为。** 不配置，就等于让代码里的 `if` 决定。

### 9.2 失败策略的实现

三种失败策略对应三种返回值。

- 快速失败：返回失败 worker 的 `RunResult`，`status=FAILED`。
- 部分成功：继续，最后 `status=DEGRADED`，`error` 记录失败的 worker。
- 重试/换人：重试一次或换 worker；仍失败则按前两种处理。

关键点：**部分成功不能返回 `COMPLETED`。** 返回 `COMPLETED` 会让调用方以为全部完成；返回 `DEGRADED` 才会让调用方检查缺口。

失败的 worker 也要记录：是哪个 worker、失败原因、是否重试。没有这些，汇总时不知道缺口在哪。

**失败策略不是“错误处理”，是“交付语义”。** 它决定调用方看到什么状态，而不只是内部怎么重试。

### 9.3 拓扑的监控

多 agent 系统的监控，比单 agent 多三个指标。

- **worker 利用率**：有多少 worker 在跑、有多少空转；
- **交接次数**：Handoff/Supervisor 派了多少次活，是否重复；
- **汇总缺口**：多少任务以 `DEGRADED` 结束，缺了哪个 worker。

三个指标对应三种浪费：空转、重复、缺口。单看总成功率，看不出这些。

拓扑的监控要按 `trace_id` 聚合：一次任务的所有 worker span 串起来，才能算利用率与交接次数。

**多 agent 的监控，单位是任务，不是 worker。** 只看单个 worker，永远不知道整体卡在哪。

### 9.4 拓扑的降级

拓扑失败时，也有降级交付。

- Supervisor 部分 worker 失败：交已完成的部分，标注缺口；
- Handoff 接手的 Agent 失败：退回分诊，转人工或兜底；
- Pipeline 中间阶段失败：交前几段的产出，标注停在哪；
- Blackboard 部分角色失败：交已有结论，标注缺哪个角色。

四种降级都要返回 `DEGRADED`，带缺口说明；不能返回 `COMPLETED`，也不能只抛异常。

**降级交付是多 agent 系统的基本能力。** 一个 worker 失败就让整个任务失败，等于浪费其他 worker 的工作。

### 9.5 拓扑的重试

拓扑的重试与 Agent 的重试不同：前者重派任务，后者重跑步骤。

拓扑重试要满足三个条件：

- 任务幂等：重派不会产生第二次副作用；
- worker 可替换：换一个 worker 也能做；
- 预算足够：重试要花额外的钱。

三个条件不满足，就不要在拓扑层重试；让失败返回，由调用方决定。

**拓扑重试是“换人再做”，不是“同一个人再做一遍”。** 同一个人失败，通常是任务不适合它。

## 十、边界

**第一，拓扑不跨进程。** A2A 在第 34 章；本章的拓扑都在进程内。

**第二，拓扑不替代队列。** 长任务、异步、重试在第 32 章；拓扑只决定组合。

**第三，拓扑不替代评测。** 多 agent 好不好，要看任务成功率、成本、延迟；拓扑只提供结构。

**第四，拓扑不承诺“越多越好”。** 一个 Agent 能做的，不要拆成三个；拆分的代价是交接、汇总、失败点。

**第五，拓扑可以嵌套，但不要为了嵌套而嵌套。** 两层足够，三层就要问“是不是架构错了”。

### 10.1 拓扑与部署

拓扑在进程内，部署在进程外。两者要分开。

- 单进程：四种拓扑都可以直接跑；
- 多进程：Handoff 可以变成 A2A，Supervisor 可以变成远程调度；
- 队列：Pipeline 的每个阶段可以变成独立 worker；
- 服务化：Blackboard 可以变成共享存储。

四种变化都不改拓扑的 `run` 契约；改的是 `Runnable` 的实现（本地 Agent → 远程客户端）。

**拓扑描述“谁和谁连”，部署描述“连的线怎么走”。** 两者分开，拓扑才能从单机长到多机。

### 10.2 拓扑的选型

四种拓扑怎么选？三个问题。

**问题一：阶段顺序固定吗？** 固定 → Pipeline；不固定 → 下一问。

**问题二：需要一个中心汇总吗？** 需要 → Supervisor；不需要 → 下一问。

**问题三：控制权要转移吗？** 要 → Handoff；不要 → Blackboard。

三个问题覆盖大部分场景。选不出来，通常不是拓扑问题，是任务没拆清楚。

| 场景 | 拓扑 |
|---|---|
| 解析→分析→写报告 | Pipeline |
| 分诊→转专家 | Handoff |
| 调研→分析→汇总 | Supervisor |
| 多角色评审 | Blackboard |

**拓扑选型不是“哪种更先进”，是“控制权归谁最自然”。**

### 10.3 拓扑的演进

拓扑会随任务演进，方向是“从简到繁，再从繁到简”。

早期：Pipeline 够用，阶段固定，问题少。

中期：加 Handoff 处理分诊，加 Supervisor 处理汇总；系统能覆盖更多任务。

后期：拓扑太复杂，trace 串不起来，失败归因难；这时应该“拆服务”或“用图”，而不是再加一层拓扑。

拆服务：把稳定的子拓扑变成独立服务，通过 A2A 调用；图：用显式节点/边表达复杂控制流（第 55 章）。

**拓扑不是越复杂越强。** 复杂度超过任务需要，维护成本会吃掉收益。

### 10.4 拓扑的测试

拓扑的测试分三层。

**第一层：组合冒烟。** 四种拓扑各跑一次，断言 `status` 与 `answer`。

**第二层：控制权。** 换拓扑，断言 worker 调用次数不变、结果不变。

**第三层：失败。** 让一个 worker 失败，断言拓扑按配置快速失败/部分成功/重试。

三层测试对应三个问题：能不能跑、换组合有没有副作用、异常时交付什么。只做第一层，换拓扑才发现副作用；只做第二层，异常时才发现状态错。

拓扑测试不需要真实模型；`FakeModel` 足够。

### 10.5 拓扑的边界

拓扑的边界是“组合”，不是“能力”。

- 不实现工具：工具在 worker 里；
- 不实现检索：检索在 worker 的 Knowledge；
- 不实现审批：审批在 worker 的 Guard；
- 不实现模型：模型在 worker 的 Actor。

拓扑只决定“谁先跑、谁指挥谁、上下文怎么过去”。越过这条线，拓扑就会变成“大 Agent”，组件封装就白做了。

**拓扑越薄，组合越自由。** 薄的拓扑可以嵌套、可以替换、可以测试；厚的拓扑只能重写。

### 10.6 拓扑的下一版

这一版拓扑只有四种、都在进程内。下一版会遇到三个需求：跨进程、动态编排、图。

三个需求都不应该直接改四种拓扑：

- 跨进程：定义 `RemoteAgent` 实现 `run`，拓扑不变；
- 动态编排：把 `plan` 从回调变成可插拔策略，拓扑不变；
- 图：第 55 章单独实现，拓扑与图可以互相嵌套。

**拓扑的稳定，来自“只依赖 run 契约”。** 契约不变，实现可以长；契约一变，所有拓扑重写。

### 10.7 卷十二的收口

卷 12 六章到这里结束。回看六章的分工：

- 48：为什么切，边界在哪；
- 49：切开的组件之间传什么；
- 50：主体层怎么推进；
- 51：横切件怎么挂；
- 52：怎么装成一个 Agent；
- 53：多个 Agent 怎么组合。

六章是一条线：**边界 → 契约 → 实现 → 装配 → 组合**。缺任何一章，后面的章都会悬空。

这条线也是后续项目的施工顺序：先定边界，再定契约，再实现，再装配，最后组合。反过来，先写拓扑再补契约，一定会重写。

卷 12 是副线，可以跳过；但跳过它，第 54–59 章的“深水区”就只能看热闹，看不出它们各自补的是哪一块。

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
