# 第 8 章 重规划：计划失效之后怎么办

> **你会遇到的坏事**：第 6 章的计划跑到了第 2 步，工具报错。你的程序**没有报错，也没有结束——它就这么卡住了**。
>
> 这是 P&E 最阴险的失败形态：**静默卡死**。

---

## 8.1 三种失败，三种修法（不要混用）

新手最常见的问题是"一失败就全部重来"，成本翻三倍还更慢。

正确的做法是**分级**：

| 失败类型 | 例子 | 修法 | 代价 |
|---|---|---|---|
| **瞬时故障** | 超时、503、429 限流 | `RETRY` 原样重试 | 极低 |
| **局部错误** | 工具名写错、参数格式不对 | `PATCH` 只替换失效步骤 | 低（已完成的不重跑） |
| **前提错误** | 假设数据在 MySQL，实际在 Hive | `REPLAN_ALL` 全部重来 | 高（但必要） |

**判断依据是"错误信息"，不是"模型的心情"。**

```python
def decide(self, step, plan, replan_count) -> str:
    if replan_count >= self.replan_budget:
        return "give_up"

    err = (step.error or "").lower()

    # ① 瞬时故障 → 重试
    if any(k in err for k in ("timeout", "502", "503", "429", "connection")):
        if step.attempts < self.max_retries_per_step:
            return "retry"
        return "patch"

    # ② 参数/工具问题 → 局部替换
    if any(k in err for k in ("参数", "invalid", "未知动作", "not found")):
        return "patch"

    # ③ 地基错了 → 全部重来
    if step.id == plan.steps[0].id or not step.depends_on:
        return "replan_all"

    return "patch"
```

⚠️ **`replan_budget` 是必须的**：没有它的重规划会陷入"重规划 → 又失败 → 再重规划"的循环，比不重规划更糟。

---

## 8.2 💻 三种策略的对照实验

```bash
python code/ch08_replan/demo_replan.py
```

**不需要 API key。** 场景是第 6 章的计划，但**故意把 s2 的工具名写成 `search_B`**（不存在）。

### 对照组 1：没有任何重规划

```
✔ [s1] 查竞品A定价 → 竞品A：¥99/月，按席位计费，含基础模型。
✘ [s2] 查竞品B定价 → 未知动作：search_B

完成：False  失败步骤：['s2']
剩余未执行： ['s3', 's4']
```

**注意 `剩余未执行`**：s3、s4 永远是 PENDING。

**这就是静默卡死**：程序没有抛异常，`run()` 也正常返回了，但计划只完成了一半。

> 如果你在生产环境见过"任务状态一直显示'处理中'，但日志里什么都没有"——大概率就是这个。

### 对照组 2：只允许 RETRY

```
⚠️ [s2] 失败：未知动作：search_B
→ 决策：give_up
```

`search_B` **根本不存在**，重试 10 次也是这个错。**RETRY 只能治瞬时故障。**

### 实验组：PATCH

```
⚠️ [s2] 失败：未知动作：search_B
→ 决策：patch
→ 已修复，计划版本 v2，共 2 步
✔ [s2] 查竞品B定价（已修正工具名） → 竞品B：¥129/月，按调用量计费，含高级模型。

完成：True
计划版本：v2
```

**关键：s1 没有被重跑。** 已经花掉的钱和已经拿到的结果，全部保留。

---

## 8.3 PATCH 的两个难点（我都踩过）

### 难点 1：下游步骤的依赖会失效

s3 的 `args` 里写着 `{"b": "{s2.result}"}`。如果 PATCH 给新步骤换了个 id（比如 `s2_new`），s3 的引用就指向了一个不存在的步骤——**结果变成空字符串，静默出错**。

**修法：保持 `id` 不变。**

```python
return [
    PlanStep(
        id=failed.id,          # ← 保持 id，下游引用才不会失效
        goal=failed.goal + "（已修正工具名）",
        action="search",
        args=failed.args,
        depends_on=failed.depends_on,
    )
]
```

### 难点 2：不能把"已完成的下游"一起删掉

我的第一版实现是这样的：

```python
kept = [s for s in new_plan.steps if s.id not in to_replace]   # ← 错的
new_plan.steps = kept + new_steps
```

它把 s2 和它**全部下游**（s3、s4）都删了，只留下 s1 和修正后的 s2。

结果 `is_complete()` 返回 **True**——因为计划里只剩两个已完成的步骤，`s3`、`s4` 不见了！

**这是最典型的"修复引入了更隐蔽的 bug"**：

- 修复前：计划卡住（显性问题）
- 修复后：计划"成功"了，但根本没给出建议（隐性问题）

**正确做法：只删"未完成的"下游，已完成的结果要保留。**

```python
removable = {s.id for s in new_plan.steps if s.id in to_replace and s.status != StepStatus.DONE}
kept = [s for s in new_plan.steps if s.id not in removable]
```

⚠️ **这个坑值得记住**：修 bug 时，"看起来对了"比"明显错了"更危险。**每次修完都要重新检查完成的定义。**

---

## 8.4 让"静默卡死"变成"明确报错"

第 6 章实验 B 的坑：依赖写错（指向不存在的 id），计划会静默卡住。

修法是**在构造计划时就校验**：

```python
def fix_deadlock(plan: Plan) -> Plan:
    ids = {s.id for s in plan.steps}

    # ① 移除不存在的依赖
    for s in plan.steps:
        s.depends_on = [d for d in s.depends_on if d in ids]

    # ② Kahn 拓扑排序检测环
    indeg = {s.id: len(s.depends_on) for s in plan.steps}
    ready = [sid for sid, d in indeg.items() if d == 0]
    seen = 0
    while ready:
        cur = ready.pop()
        seen += 1
        for s in plan.steps:
            if cur in s.depends_on:
                indeg[s.id] -= 1
                if indeg[s.id] == 0:
                    ready.append(s.id)

    if seen != len(plan.steps):
        raise ValueError("计划中存在循环依赖")
    return plan
```

运行结果：

```
✅ 正确报错：计划中存在循环依赖
```

**工程原则：宁可启动时报错，不要运行到一半静默卡住。**

---

## 8.5 用模型做重规划

教学版用一个规则函数 `repair()` 代替模型。真实系统里，这一步是：

```
输入：原计划 + 失败的那一步 + 错误信息 + 可用工具清单 + 已完成步骤的结果
输出：替换用的新步骤（结构化的 PlanStep 列表）
```

**prompt 的关键**（否则模型会给你重写整个计划）：

```
你的任务是**只修复失败的那一步**，不要重写整个计划。
失败步骤：{step.id}，目标：{step.goal}
错误信息：{error}
可用工具：{tools}
已完成步骤及其结果（不要重做这些）：{done_steps}
```

⚠️ **必须把"已完成的结果"一起喂进去**，否则模型不知道 s3 需要 `s2.result` 是什么格式，修出来的 s2 可能和 s3 对不上。

**约束输出结构（第 6 章的做法）**：

```python
class Patch(BaseModel):
    keep_id: str = Field(description="必须等于失败步骤的 id")
    steps: list[PlannedStep]
```

---

## 8.6 什么时候该 REPLAN_ALL

只在下面这三种情况用：

| 情况 | 例子 |
|---|---|
| **第一步就错了** | 目标理解错了 |
| **前提假设被推翻** | "数据在 MySQL" → 实际在 Hive |
| **已完成的结果全部无效** | 发现用了错误的数据源 |

**判据：如果保留任何一个已完成的步骤会让最终答案错误，就该 replan_all。**

否则一律用 PATCH——**已完成的工作是沉没成本，但也是最有价值的部分。**

---

## 8.7 💥 失败实验

### 实验 A：去掉 `replan_budget`

把 `replan_budget` 设成 `10**9`，然后构造一个"每次修复都会产生新错误"的 `repair_fn`。

**观察**：会跑多少次？成本是多少？

**这是重规划版的无限循环**——第 3 章的刹车在这里依然必要。

### 实验 B：让 PATCH 换掉 id

把 `repair()` 里的 `id=failed.id` 改成 `id=failed.id + "_new"`。

**观察**：`s3` 的 `{s2.result}` 会解析成什么？

**预期**：空字符串。s3 会拿着空数据去对比，然后给出一个看似正常、实际无意义的结论。

**这个实验说明**：**静默错误的危害远大于显式报错。**

### 实验 C：把"已完成的下游"也删掉（我的第一版 bug）

把 `removable` 那一行改回 `to_replace`。

**观察**：`is_complete()` 返回什么？最终结果是什么？

**预期**：返回 `True`，最终结果是"竞品B定价"，而不是"建议"。

---

## 8.8 ✏️ 小练习

### 练习 1（必做）：把 `decide()` 改成可配置

把"错误关键词 → 策略"的映射抽成配置：

```python
STRATEGY_MAP = {
    "timeout": "retry",
    "503": "retry",
    "未知动作": "patch",
    "参数": "patch",
    "schema_mismatch": "replan_all",
}
```

**验收**：新增一种错误类型不用改代码。

### 练习 2：记录重规划史

`ReplanningExecutor.history` 已经记录了每次决策。把它导出成 JSON，并统计：

- 每种策略用了多少次
- 重规划带来的额外成本

**验收**：能回答"我的系统里 patch 占多少、replan_all 占多少"。

### 练习 3（进阶）：把 PATCH 做成"最小改动"

现在的 `repair` 是无条件替换。改成：先尝试**只改参数**（保留 action），失败才换 action。

**验收**：在"参数错误"的场景下，新步骤的 `goal` 和 `args` 与原步骤的差异最小。

---

## 8.9 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 分级重规划信号 | `code/common/replanning.py::ReplanSignal` | 第 25 章多 Agent |
| PATCH / REPLAN_ALL | 同文件 | 项目 A、B |
| 依赖校验 `fix_deadlock` | 同文件 | 所有 P&E 场景 |

---

## 8.10 ✅ 验收

1. 三种失败类型分别对应哪种修法？判断依据是什么？
2. 为什么 PATCH 必须保持 `id` 不变？
3. 为什么不能把"已完成的下游"一起删掉？会有什么后果？
4. `replan_budget` 为什么是必须的？
5. 什么时候应该 REPLAN_ALL 而不是 PATCH？

**数字验收**：在一次"第 2 步失败"的运行里，PATCH 相比 REPLAN_ALL 省了多少次调用？

---

## 8.11 延伸阅读

- 第 9 章：重规划做的每一次改动，都要能被持久化，否则崩溃就白干了
- 第 25 章：多个 Agent 各自重规划时，怎么避免互相踩踏

---

下一页：[第 9 章 长任务与状态持久化](09-长任务与状态持久化.md)
