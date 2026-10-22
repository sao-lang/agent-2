# 第 6 章 Plan-and-Execute：先想清楚再动手

> **你会遇到的坏事**：让 Agent 调研 5 家竞品，它查完第 3 家突然改用另一种口径回答，前两家白查了。你不知道它为什么中途变卦，也说不清第 4 步为什么会去查一个不相关的字段。
>
> ReAct 的路径是**涌现**出来的——这意味着它无法被审查、无法被复用。
>
> 这一章给你另一种范式：**先声明路径，再执行路径。**

---

## 6.1 ReAct 的三个结构性缺陷（在多步任务上）

第 4 章讲了 ReAct 适合"路径不确定"的任务。但它在**多步任务**上有三个硬伤：

| 缺陷 | 现象 | 后果 |
|---|---|---|
| **无全局视角** | 查到第 3 步才发现口径要变，但不会回头 | 前后不一致，结论不可比 |
| **依赖是隐式的** | 第 4 步用了第 2 步的结果，但只存在于消息历史里 | 无法并行、无法重试、无法审计 |
| **不可预审** | 你要等它跑完才知道它干了什么 | 有副作用的动作无法提前拦住 |

**Plan-and-Execute（P&E）就是针对这三点设计的。**

---

## 6.2 P&E 的两个阶段

```
阶段一：Planning
  输入：目标
  输出：一个有依赖关系的步骤列表（Plan）
  ↓
阶段二：Execution
  按依赖顺序执行，每步结果写回 Plan
  ↓
[可选] 阶段三：Replanning（第 8 章）
  某步失败 → 只替换失效的子计划，不推倒重来
```

**关键差异只有一句话**：

> **ReAct 的路径在执行时产生，P&E 的路径在执行前声明。**

---

## 6.3 计划的数据结构（比你想的重要）

完整代码：[`code/common/planning.py`](code/common/planning.py)

```python
@dataclass
class PlanStep:
    id: str                                  # 唯一标识，重规划时要靠它
    goal: str                                # 面向人：这一步要做什么
    action: str                              # 面向机器：调哪个工具
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)   # ← 关键
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str | None = None
    attempts: int = 0
```

### 四个字段各自的作用

| 字段 | 不写会怎样 |
|---|---|
| `id` | 重规划时无法定位"哪个步骤失效了"（第 8 章） |
| `goal` | 人可以读，但机器不关心——**这是给人审查用的** |
| `depends_on` | 无法并行、无法只重跑失败分支（见 6.5） |
| `status` / `result` / `error` | 崩溃后无法恢复（第 9 章） |

### 依赖是怎么表达的

```python
plan = make_plan(
    goal="对比三家竞品定价并给出建议",
    specs=[
        ("查竞品A定价", "search", {"q": "竞品A"}, []),
        ("查竞品B定价", "search", {"q": "竞品B"}, []),
        ("查竞品C定价", "search", {"q": "竞品C"}, []),
        ("对比A与B", "compare", {"a": "{s1.result}", "b": "{s2.result}"}, ["s1", "s2"]),
        ("给出建议", "answer", {"summary": "{s4.result}"}, ["s4"]),
    ],
)
```

`{s1.result}` 是**占位符**，执行时被替换成 `s1` 的实际结果：

```python
def _resolve(args, plan):
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("{") and v.endswith(".result}"):
            sid = v[1:-8]
            prev = plan.by_id(sid)
            out[k] = prev.result if prev else ""
        else:
            out[k] = v
    return out
```

**这就是 P&E 和 ReAct 最本质的差别**：

- ReAct：数据依赖藏在消息历史里，模型"记得"就用，不记得就用错
- P&E：数据依赖写在 `args` 里，**机器可以校验、可以并行、可以重放**

---

## 6.4 💻 跑一遍执行骨架

```bash
python code/ch06_plan_execute/demo_plan_exec.py
```

**不需要 API key。** 我实际跑出来的输出：

```
=== 计划 ===
  [s1] 查竞品A定价       action=search
  [s2] 查竞品B定价       action=search
  [s3] 查竞品C定价       action=search
  [s4] 对比A与B         action=compare   依赖 ['s1', 's2']
  [s5] 给出建议         action=answer    依赖 ['s4']

=== 执行 ===
  ✔ [s1] 查竞品A定价 → 竞品A：¥99/月，按席位计费，含基础模型。
  ✔ [s2] 查竞品B定价 → 竞品B：¥129/月，按调用量计费，含高级模型。
  ✔ [s3] 查竞品C定价 → 竞品C：¥79/月，免费额度 10 万 token。
  ✔ [s4] 对比A与B → 对比结论：... 价差约 30%
  ✔ [s5] 给出建议 → 最终建议：...

=== 独立步骤：串行 vs 并行 ===
  串行：1.20s   并行：0.41s   提速 2.9x
```

**注意最后那个 2.9x**：s1/s2/s3 之间没有依赖，**它们天然可以并行**。

这是 P&E 的隐藏收益：**显式的依赖关系自动告诉你哪些步骤能并发**。ReAct 做不到这一点，因为它根本不知道自己有几条并行线索。

---

## 6.5 三种执行策略（以及为什么依赖关系决定了它）

| 策略 | 什么时候用 | 收益 |
|---|---|---|
| **串行** | 依赖链很深（s1→s2→s3→s4） | 简单、可控 |
| **并行** | 多个步骤互不依赖 | 延迟从"相加"变成"取最大" |
| **拓扑分批** | 混合情况 | 每批内部并行，批间串行 |

`Plan.ready()` 就是拓扑分批的核心：

```python
def ready(self) -> list[PlanStep]:
    done = {s.id for s in self.steps if s.status == StepStatus.DONE}
    return [
        s for s in self.steps
        if s.status == StepStatus.PENDING and all(d in done for d in s.depends_on)
    ]
```

它返回"当前所有前置都已完成、且自己还没跑"的步骤——**这批就可以并发**。

> 第 22 章会用 `asyncio.gather` 把批内并发真正跑起来，那里你会看到延迟从 1.2s 降到 0.4s。

---

## 6.6 用真实模型生成计划

### 💻 可运行代码（需要 API key）

```bash
python code/ch06_plan_execute/demo_llm_planner.py
```

核心是**结构化输出**：让模型直接给出可执行的 JSON，而不是一段待解析的文字。

```python
class PlannedStep(BaseModel):
    goal: str = Field(description="这一步要达成什么，一句话，面向人")
    action: str = Field(description=f"工具名，只能是：{', '.join(TOOLS)} 或 answer")
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list, description="依赖第几步（从 1 开始）")

class PlannedSteps(BaseModel):
    steps: list[PlannedStep]

structured = llm.with_structured_output(PlannedSteps)
result = structured.invoke(PLANNER_PROMPT.format(goal=goal))
```

### ⚠️ 为什么一定要 Pydantic 约束

| 不约束 | 约束后 |
|---|---|
| 模型写 `action: "搜索竞品定价"` | 枚举里没有，无法执行 |
| 模型写 `args: "q=竞品A"`（字符串） | `dict` 类型强制 |
| 模型写 `depends_on: "第一步"` | `list[int]` 强制 |
| 你要再写一堆 try/except 解析 | 解析失败在 schema 层就报出来 |

**这就是第 4 章的教训升级版**：不要给"解析"留空间，让类型系统在源头拦住。

---

## 6.7 计划审查：P&E 最被低估的价值

生产环境里，P&E 真正的杀手锏不是"效率"，而是**可预审**：

```python
def review(plan: Plan) -> bool:
    for s in plan.steps:
        print(f"[{s.id}] {s.action}({json.dumps(s.args, ensure_ascii=False)[:60]})")
        print(f"     目标：{s.goal}")

    # 一条简单的规则检查示例
    risky = [s for s in plan.steps if s.action == "answer" and not s.depends_on and len(plan.steps) > 1]
    if risky:
        print("⚠️  存在不依赖任何前置步骤的 answer，可能给出了没根据的结论。")
        return False
    return True
```

**为什么这重要**：

> 如果你的 Agent 要执行**有副作用**的动作（改数据库、发邮件、提交代码），
> 你**必须**在动手之前知道它要干什么。

ReAct 做不到——你只有等它跑完才知道。P&E 天然能做——**计划就是一份待审批的清单**。

第 19 章会把这一步做成完整的人机协作（HITL）流程。
项目 A（Coding Agent）的 `plan → 人工确认 → 执行` 就是这个模式。

---

## 6.8 P&E 的代价（必须诚实说）

| 代价 | 说明 | 缓解 |
|---|---|---|
| **规划可能过度** | 模型拆出 20 步，其中 8 步是废话 | prompt 里限制"步骤尽量少"；上限硬约束 |
| **计划可能错** | 第 3 步基于错误假设 | 第 8 章的重规划 |
| **多一次调用** | planning 本身要花钱 | 用便宜模型做规划（第 21 章） |
| **不适合探索型任务** | "先看看有什么再决定" | 这种还是用 ReAct |

**判断标准**：

> 如果你能提前说出"大概要做哪几件事"，用 P&E。
> 如果你连"要做几件事"都不知道，用 ReAct。

---

## 6.9 💥 失败实验

### 实验 A：让计划包含一个必然失败的步骤

把 `("查竞品D定价", "search", {"q": "竞品D"}, [])` 加进 `demo_plan()`。

**观察**：执行器怎么处理？后续依赖它的步骤会怎样？（`ready()` 会永远等不到它 → 死锁）

**这个实验直接引出第 8 章**：没有重规划，一个失败步就能让整个计划卡死。

### 实验 B：故意写错依赖

把 `s4` 的 `depends_on` 改成 `["s9"]`（不存在的步骤）。

**观察**：`ready()` 返回什么？计划能跑完吗？程序会报错还是静默卡住？

**答案：静默卡住。** 这是 P&E 最阴险的 bug——它不报错，只是什么都不做。

**修法**：在 `make_plan` 时校验所有 `depends_on` 都存在，且没有环。

### 实验 C：去掉 `goal` 字段

把 `goal` 全设成空字符串，然后跑 `review()`。

**观察**：你还能审查这个计划吗？

**结论**：`goal` 是纯"给人看"的字段，机器完全不需要它。但它决定了**人能不能审**。**可读性不是装饰，是可审批性的前提。**

---

## 6.10 ✏️ 小练习

### 练习 1（必做）：给计划加依赖校验

在 `make_plan` 里加：

1. 所有 `depends_on` 的 id 必须存在
2. 不能有环（拓扑排序检测）

**验收**：实验 B 的用例能被**明确报错**，而不是静默卡住。

### 练习 2：把"三路并行搜索"真的并行化

把 `Executor.run` 改造成异步，用 `asyncio.gather` 跑 `ready()` 返回的整批。

**验收**：延迟从 1.2s 降到约 0.4s（和我上面模拟的数字一致）。

### 练习 3（进阶）：加"计划质量"打分

写一个函数，给计划打分：

- 步骤数是否合理（超过 10 步扣分）
- 是否有"孤立步骤"（没有依赖也没人依赖它）
- 最后一步是否一定是 `answer`

**验收**：能识别出"拆得过碎"和"有冗余步骤"的计划。

---

## 6.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| Plan / PlanStep 数据结构 | `code/common/planning.py` | 第 8 章重规划、第 19 章 HITL |
| 依赖解析 `_resolve` | 同上 | 第 25 章多 Agent 数据传递 |
| 拓扑执行 `Executor` | 同上 | 第 22 章并行化 |
| 结构化规划器 | `code/ch06_plan_execute/demo_llm_planner.py` | 项目 A/B |

---

## 6.12 ✅ 验收

1. ReAct 和 P&E 的路径分别在什么时候确定？
2. `depends_on` 为什么不能省？它带来哪三个能力？
3. `{s1.result}` 这种占位符解决了什么问题？ReAct 里对应的是什么？
4. 为什么说"计划审查"是 P&E 最大的工程价值？
5. 什么任务不该用 P&E？

**数字验收**：把三个独立步骤并行后，延迟从多少降到多少？

---

## 6.13 延伸阅读

- Plan-and-Execute 论文（2023）：先规划后执行的最早系统化描述
- 第 8 章：计划失效之后怎么修，而不是重来
- 第 19 章：把"计划审查"做成完整的人机协作流程

---

下一页：[第 7 章 Reflection 与 Reflexion：让 Agent 学会改自己](07-Reflection与Reflexion.md)
