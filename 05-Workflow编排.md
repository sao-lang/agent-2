# 第 5 章 Workflow：什么时候不该用 Agent

> **你会遇到的坏事**：你把一个"评论分类 → 抽理由 → 生成回复"的固定流程做成了 Agent。上线后发现：同样的输入，今天 4 步、明天 7 步，成本翻倍，而且偶尔跳过"抽理由"这一步。
>
> 问题不在模型，在于**你用了错误的架构**。

---

## 5.1 一个必须建立的判断顺序

业界最常见的错误是"先想到 Agent，再找地方用它"。正确的判断顺序反过来：

```
这个任务，我自己能写出确定步骤吗？
├── 能 → 用 Workflow（代码编排）
└── 不能 → 每一步都能验证吗？
          ├── 能 → 用 ReAct
          └── 不能 → 需要规划 + 反思（第 6、7 章）
```

**为什么这个顺序重要**：Agent 的价值是"处理不确定性"。当任务本身没有不确定性时，Agent 只会**引入**不确定性。

---

## 5.2 Workflow 与 Agent 的本质区别

| 维度 | Workflow | Agent |
|---|---|---|
| 谁决定下一步 | **你的代码** | **模型** |
| 路径 | 固定（或用条件边显式分支） | 动态 |
| 成本 | 可预测（步骤数固定） | 不可预测（随模型心情） |
| 调试 | 看代码就知道走到哪 | 要看 trace 才知道 |
| 适合 | 步骤确定、需要稳定输出 | 路径不确定、需要探索 |

**一句话**：Workflow 把"控制流"写进代码，Agent 把"控制流"交给模型。

**用 Agent 做固定流程 = 把 `if` 语句换成了"模型猜的 if"**，成本上升、确定性下降，没有任何收益。

---

## 5.3 💻 实证：同一个任务，两种架构

```bash
python code/ch05_workflow/demo_workflow_vs_agent.py
```

**不需要 API key**：两边用同一个假模型，保证对比的是**架构**而不是模型随机性。

完整代码：[`code/ch05_workflow/demo_workflow_vs_agent.py`](code/ch05_workflow/demo_workflow_vs_agent.py)

### 任务定义

输入：`"收到货发现屏幕有两条划痕，联系客服三次没人回，我要退款，太气人了。"`

输出：`是否退款` / `理由` / `是否升级` / `回复`

**这个任务是确定的**：分类 → 抽理由 → 生成回复，三个步骤不会变。

### Workflow 实现（LangGraph）

```python
g = StateGraph(WFState)
g.add_node("classify", lambda s: wf_classify(s, m))
g.add_node("reason", lambda s: wf_reason(s, m))
g.add_node("reply", lambda s: wf_reply(s, m))

g.add_edge(START, "classify")

# 条件边：只有需要退款才抽理由
g.add_conditional_edges(
    "classify",
    lambda s: "reason" if s["need_refund"] else "reply",
    {"reason": "reason", "reply": "reply"},
)
g.add_edge("reason", "reply")
g.add_edge("reply", END)
```

注意 `add_conditional_edges`：**这是 Workflow 里唯一"像 Agent"的地方**——但它仍然是**你的代码**在做判断（`"退款" in txt`），不是模型在决定。

### 我实际跑出来的对比

```
                    模型调用       token       输出可预测       可调试
----------------------------------------------------------
Workflow               3         417           是         是
Agent                  6         783           否        较难

成本倍数：1.88x（Agent 多花 366 token）
```

**多花 88% 的钱，换来一个更不确定的流程。** 这个交易在任何场景下都不划算。

### 为什么 Agent 版多出 3 步

看它的"思考"：

1. 这个评论需要处理吗？
2. 应该抽理由吗？← 这一步 Workflow 用条件边直接做了
3. 抽理由
4. 是否需要升级？
5. 生成回复
6. **检查我的回复是否完整** ← 模型自己加的"质检"

第 2 步和第 6 步是纯浪费：前者是代码能确定的，后者是模型在猜自己刚做的事对不对。

---

## 5.4 Workflow 的四种控制结构

LangGraph 只是工具，**控制结构**才是你要掌握的东西。

### 结构 1：顺序（Sequential）

```python
g.add_edge("a", "b")
g.add_edge("b", "c")
```

最常用。**能用顺序解决的，就别用条件。**

### 结构 2：条件分支（Conditional）

```python
g.add_conditional_edges("classify", router, {"x": "node_x", "y": "node_y"})
```

**关键：路由函数是纯代码，不是模型。** 这才是 Workflow 的核心优势——分支逻辑可以单元测试。

如果你发现自己写了个 `llm.invoke()` 来决定走哪条边，那你已经在做 Agent 了，只是穿上了 Workflow 的衣服。

### 结构 3：并行（Parallel）

```python
g.add_edge("start", "branch_a")
g.add_edge("start", "branch_b")
g.add_edge("branch_a", "join")
g.add_edge("branch_b", "join")
```

适合"三个来源同时查，然后合并"。第 22 章会用这个结构做延迟优化。

### 结构 4：循环（Loop，有上限）

```python
g.add_conditional_edges("check", lambda s: "retry" if s["failed"] < 2 else "end", ...)
```

**注意 `s["failed"] < 2`**：Workflow 里的循环也必须写上界，否则和第 3 章的失控一样。

---

## 5.5 混合模式：Workflow 骨架 + Agent 单元

真实系统很少是纯 Workflow 或纯 Agent。最常见的是**外层 Workflow，内层 Agent**：

```
[固定] 接收工单
   ↓
[固定] 分类（小模型，便宜）
   ↓
[固定] 决定子流程：物流问题 / 质量问题 / 其他
   ↓
[Agent] 质量问题 → 交给一个 ReAct Agent 去查政策、查订单、算补偿
   ↓
[固定] 回复模板套用 + 发送
```

**为什么这样设计**：

- 外层固定 → 成本可控、路径可预测
- 内层 Agent → 处理"每次都不一样的细节"
- 分类用小模型 → 便宜的事不要用好模型

**这个模式叫 "Workflow with agentic steps"，是当前企业落地最常见形态。** 项目 A（Coding Agent）和项目 B（Computer Use）都是这个结构。

---

## 5.6 什么时候"看起来像 Workflow"其实该用 Agent

反向判断也要会。下面这些信号说明**该用 Agent**：

| 信号 | 例子 |
|---|---|
| 步骤数量本身就是不确定的 | "查资料直到够了为止" |
| 每一步用哪个工具要视情况定 | "根据报错类型选择不同排查工具" |
| 需要根据观察结果改变计划 | "查到第 3 家发现要换维度" |

**判据：如果你写 Workflow 时发现自己在写"很多个 if-else 来模拟决策"，那就承认它是个 Agent 吧。** 硬写成 Workflow 只会得到一堆难以维护的分支。

---

## 5.7 💥 失败实验

### 实验 A：把条件边换成模型决策

把 `add_conditional_edges` 的路由函数改成：

```python
lambda s: "reason" if llm.invoke(f"需要抽理由吗？{s['comment']}") == "yes" else "reply"
```

**观察**：多花多少 token？结果稳定吗？跑 10 次，有多少次走了不同路径？

### 实验 B：去掉条件边，全部执行

把 `classify` 直接连到 `reason`，`reason` 直接连到 `reply`（无条件）。

**观察**：成本增加多少？输出质量有变化吗？

**你会得到的结论**：**条件边不是"优化"，是"业务正确性"**——不需要退款时抽理由，本身就是错的。

### 实验 C：给 Workflow 加一个"自我检查"步骤

在 `reply` 后加一个节点，让模型检查回复是否完整。

**观察**：它花了多少 token？发现了几个真实问题？（多数情况下，它只是说"看起来不错"）

**这就是第 7 章"反思必须有外部信号"的反面案例。**

---

## 5.8 ✏️ 小练习

### 练习 1（必做）：给你自己的任务画架构判断图

拿一个你手上的真实需求，走一遍 5.1 节的判断树：

- 能写出确定步骤吗？
- 每一步能验证吗？
- 哪些步骤该交给 Agent，哪些该固定在 Workflow 里？

**验收**：能对着图说出"这一步为什么是代码，那一步为什么是模型"。

### 练习 2：把示例拆成混合模式

把 Workflow 版的 `reason` 节点换成一个 ReAct Agent（可以查政策、查订单历史）。

**验收**：外层步骤数不变，内层步数动态变化，成本仍可预测（有上界）。

### 练习 3（进阶）：条件边的可测试性

给 `wf_classify` 写 3 条 pytest 用例，覆盖"退款/不退款/边界"三种情况。

**验收**：`pytest` 全绿。这是 Workflow 相对 Agent 的核心优势——**你的分支逻辑可以被单元测试**。

---

## 5.9 ⚠️ 常见坑

| 坑 | 现象 | 修法 |
|---|---|---|
| 用 LLM 做路由 | 路径不稳定、成本上升 | 能用规则就用规则 |
| 没有终点 | 图跑不完 | 每个分支都要能到 `END` |
| 循环没上界 | 死循环 | 计数器 + 条件边 |
| 状态字段无限增长 | 上下文爆炸 | 用 `reducer` 或只在需要时累积 |
| 忘记 `add_edge(START, ...)` | 图没有入口 | 编译时会报错，但信息不直观 |

---

## 5.10 📦 本章沉淀

| 产出 | 说明 |
|---|---|
| 架构判断树 | 5.1 节，后续所有项目的第一道工序 |
| Workflow 四种控制结构 | 5.4 节 |
| 混合模式骨架 | 5.5 节，项目 A/B 的架构基础 |

---

## 5.11 ✅ 验收

1. Workflow 和 Agent 的本质区别是什么？用一句话说。
2. 什么信号说明"这个任务该用 Workflow"？
3. 什么信号说明"你其实在写 Agent，只是包装成了 Workflow"？
4. 混合模式为什么是企业落地的主流？它解决了哪两个矛盾？
5. 为什么条件边的路由函数不该让模型来做？

**数字验收**：在你的场景里，Agent 版比 Workflow 版贵多少倍？贵出来的部分换到了什么？

---

## 5.12 延伸阅读

- Anthropic《Building Effective Agents》：workflows vs agents 的经典论述
- 第 6 章：当步骤"不能预先确定但需要全局视角"时，用 Plan-and-Execute

---

下一页：[第 6 章 Plan-and-Execute：先想清楚再动手](06-Plan-and-Execute.md)
