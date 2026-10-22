# 第 25 章 多 Agent：什么时候该拆，什么时候不该

> **你会遇到的坏事**：你把一个还算能用的 Agent 拆成了 4 个。上线后：成本 ×3，延迟 ×2，质量还降了。
>
> 因为每个 Agent 都必须重新理解全部上下文——而它们看到的都不是同一个版本。

---

## 25.1 先接受一个事实：多 Agent 是成本放大器

| | 单 Agent | 多 Agent（4 个） |
|---|---|---|
| 调用次数 | 4 | 10 |
| 成本 | ¥0.020 | ¥0.056（**2.8×**） |
| 延迟（串行） | 1.2s | 2.4s |
| 延迟（并行） | 1.2s | 0.6s |

**这是本章示例跑出来的真实数字。**

所以问题的正确问法不是"能不能拆"，而是：

> **拆了之后，多出来的 2.8 倍成本，换来了什么？**

如果答案是"什么都没换来"，那你只是在给自己增加复杂度。

---

## 25.2 三个判据（缺一不可）

```python
@dataclass
class SplitCriteria:
    can_parallel: bool          # 子任务能并行吗？
    need_cross_read: bool       # 子任务需要互相看结果吗？
    context_too_large: bool     # 单个上下文装不下吗？
```

### 💻 六个任务的实际判断

```bash
python code/ch25_multi_agent/demo_multi_agent.py
```

```
任务                               可并行     需互看     装不下   结论
------------------------------------------------------------------------
写三份不同产品的文案                      True   False   False   ✅ 可拆
写文案 + 审文案（要互看）                 False    True   False   ❌ 不拆：用单 Agent + Reflection
读 500 页手册后总结                    True   False    True   ✅ 可拆
查一个订单状态                        False   False   False   ❌ 不拆：只会更贵更慢
对比 5 家竞品定价                      True   False   False   ✅ 可拆
审合同时交叉核对条款                     False    True    True   ✅ 可拆
```

### 三条判断的实际含义

**判据 1：能并行吗？**

- 能 → 拆了能省延迟（唯一无可替代的价值）
- 不能 → 拆了只是把串行变得更贵

**判据 2：需要互相看结果吗？**

需要交叉验证，但**上下文装得下** → **不要拆！**

> "写文案 + 审文案"看起来是两个角色，但只要一份文档装得下，
> **单 Agent + Reflection（第 7 章）更便宜、更准**。
>
> 因为单个 Agent 审自己时，**上下文完全一致**；两个 Agent 审的时候，
> critic 只能看到 writer 的输出，看不到 writer 的推理过程。

**判据 3：上下文装不下吗？**

这是拆分的**最强理由**。如果一份材料 20 万 token，单个模型读不完，那必须拆。

**但要注意**：拆了之后，**汇总者又要读全部结果**——它可能又装不下。

---

## 25.3 形态 A：Supervisor（串行分派）

```python
def supervisor_node(state: SupState) -> dict:
    findings = state.get("findings", [])
    rounds = state.get("rounds", 0)
    if rounds >= 3:
        return {"done": True, "final": " | ".join(findings)}
    order = ["researcher", "analyst", "critic"]
    return {"next_agent": order[min(rounds, 2)], "rounds": rounds + 1}
```

### 💻 实测

```
轮次：3
产出：['[researcher] 产出第 1 项结果', '[analyst] 产出第 2 项结果', '[critic] 产出第 3 项结果']
耗时：460ms
```

### ⚠️ Supervisor 的两个致命陷阱

**陷阱 1：协调者成了上下文瓶颈**

如果协调者要把 A 的完整输出转述给 B，那**所有信息都要过它一遍**——它的上下文会爆炸。

**正确做法：协调者只做分派和汇总，不搬数据。**

```python
# ✅ 子 Agent 直接写共享状态（黑板），协调者只读摘要
return {"next_agent": "analyst", "findings": findings}
```

**陷阱 2：没有终止条件**

第 3 章的无限循环在这里会变成"协调者永远觉得还不够"。

**必须显式写终止条件**：

```python
if rounds >= 3 or coverage(findings) >= 0.9 or budget_exhausted:
    return {"done": True}
```

---

## 25.4 形态 B：并行 fan-out（唯一真正有价值的形态）

```python
def fan_out(state: FanState) -> list:
    from langgraph.types import Send

    subtasks = state.get("subtasks", [])
    return [Send("worker", {"task": state.get("task", ""), "sub": s}) for s in subtasks]
```

### 💻 实测

```
结果：汇总 3 个子任务结果
子结果数：3
耗时：306ms
```

**串行需要 900ms（3 × 300ms），并行只需要 306ms（取 max）。**

### ⚠️ 两个必须知道的细节

**细节 1：`Send` 的第二个参数是分支的输入 state**

```python
# ❌ 我的第一版
return [Send("worker", sub) for sub in subtasks]     # 传了字符串

# ✅ 正确
return [Send("worker", {"task": ..., "sub": s}) for s in subtasks]
```

传错的话 worker 读不到 `sub`，产出全是空。

**细节 2：结果列表必须用 reducer 累加**

```python
results: Annotated[list[str], _merge]     # ← 不加 reducer 会被互相覆盖
```

3 个分支同时写 `results`，没有 reducer 的话**只剩最后一个**——而且不报错。

---

## 25.5 共享黑板：需要互看时的正确做法

如果子 Agent 确实需要共享信息（判据 2 为真），用**版本化的黑板**，不要用"协调者转述"。

```python
class Fact(BaseModel):
    text: str
    source: str
    confidence: float
    author: str
    version: int

def append_fact(board: list[Fact], fact: Fact) -> list[Fact]:
    # 追加，不覆盖
    return board + [fact]
```

### 三条规则

| 规则 | 原因 |
|---|---|
| **追加不覆盖** | 两个 Agent 得出矛盾结论时，两个都要保留 |
| **带 author** | 出错时知道是谁写的 |
| **带 version** | 后续 Agent 能判断"我看到的是最新版吗" |

### 矛盾怎么处理

```python
if not any_conflict(new_fact, board):
    board.append(new_fact)
else:
    board.append({**new_fact, "flag": "conflict", "conflicts_with": existing.id})
    # 触发额外的验证 Agent，或转人工
```

**这是第 24 章 wiki 矛盾检测的多 Agent 版本。**

---

## 25.6 预算分摊：防止一个子 Agent 拖垮全局

```python
total_budget = 0.05
workers = 3
per_worker = total_budget / workers * 0.8    # 留 20% 给协调者
```

**关键：每个子 Agent 用独立预算，且加起来不能超过总预算。**

```python
class WorkerBudget:
    def __init__(self, share: float):
        self.limit = share
        self.used = 0.0

    def allow(self, cost: float) -> bool:
        return self.used + cost <= self.limit
```

⚠️ **如果共享一个预算池**，一个子 Agent 跑飞会耗尽全局，其他子 Agent 直接失败——**故障会横向传播**。

---

## 25.7 拆分后的必做对比

拆完必须做**三方对比**（这是第 26 章评测的延伸）：

| 指标 | 单 Agent | 多 Agent | 结论 |
|---|---|---|---|
| 任务完成率 | ? | ? | 质量有没有真的提升 |
| 平均成本 | ? | ? | 贵了多少 |
| P95 延迟 | ? | ? | 快了还是慢了 |
| 失败时可定位性 | 高 | 低 | trace 复杂度 |

**如果"完成率"提升不到 10%，而成本翻了 3 倍——那就退回去。**

### 常见的"看起来多 Agent 更好"的错觉

| 错觉 | 真实原因 |
|---|---|
| "多 Agent 准确率更高" | 其实是**多次采样**的效果（相当于 self-consistency） |
| "多 Agent 更懂分工" | 其实是你把 prompt 拆得更细了（单 Agent 也能做到） |
| "多 Agent 更稳" | 其实是**子任务更简单**，不是架构更好 |

**识别方法：让单 Agent 也跑 3 次取多数，看是不是也能达到同样效果。**

---

## 25.8 💥 失败实验

### 实验 A：把 `results` 的 reducer 去掉

```python
results: list[str]     # 不加 Annotated
```

**观察**：3 个并行分支的结果还剩几个？

**预期**：只剩 1 个，而且**不报错**。这是多 Agent 最隐蔽的 bug。

### 实验 B：让 Supervisor 转述数据

让协调者在 `next_agent` 里带上"上一个 Agent 的完整输出"。

**观察**：协调者的 input token 增长曲线。

**这就是"上下文瓶颈"的实感。**

### 实验 C：所有子 Agent 共享一个预算

让 worker1 故意跑飞（循环 20 次），观察 worker2/3 是否还能执行。

**预期**：全部失败——故障横向传播。

---

## 25.9 ✏️ 小练习

### 练习 1（必做）：给你手上的任务做判据评估

用 `SplitCriteria` 评估 3 个你真实遇到的任务。

**验收**：能说出"为什么这个不拆"，并用第 7 章的反思方案替代。

### 练习 2：实现共享黑板 + 冲突标记

按 25.5 节实现 `append_fact`，并写一个检测矛盾的函数。

**验收**：两个 Agent 给出矛盾事实时，黑板上有两条记录 + 冲突标记。

### 练习 3（进阶）：做一次真实的三方对比

用同一个任务，分别用单 Agent 和 fan-out 多 Agent 跑 20 次，对比完成率/成本/P95 延迟。

**验收**：能给出表格，并回答"值不值得拆"。

---

## 25.10 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 三判据 | `code/common/multi_agent.py::SplitCriteria` | 架构决策 |
| Supervisor 骨架 | `build_supervisor` | 项目 C |
| 并行 fan-out | `build_fan` | 深度研搜类任务 |
| 成本模型 | `CostModel` | 架构对比 |

---

## 25.11 ✅ 验收

1. 为什么说"多 Agent 是成本放大器"？给出一个倍数。
2. 三个判据分别对应什么风险？哪个是拆分的"最强理由"？
3. 为什么"写文案 + 审文案"不该拆成两个 Agent？
4. `Send` 的第二个参数应该传什么？
5. 共享黑板的三个必要字段是什么？

**数字验收**：你的多 Agent 相比单 Agent，成本倍数和延迟变化分别是多少？

---

## 25.12 延伸阅读

- 深度研搜项目（基础教程）：A2A 与真实的多 Agent 协作
- 第 7 章：为什么单 Agent + Reflection 常常更好
- 第 26 章：三方对比的评测方法

---

下一页：[第 26 章 评测体系：结果评估与轨迹评估](26-评测体系.md)
