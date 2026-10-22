# 第 19 章 人机协作：中断、审批与恢复

> **你会遇到的坏事**：Agent 帮你处理完了退款，客户打电话来问"我没同意啊"。
>
> 你想查它执行前有没有确认，结果发现——**系统里根本没有"确认"这个步骤**。

---

## 19.1 HITL 不是"弹个确认框"

很多人理解的 HITL 是：

```
Agent 要执行 → 弹窗"是否继续？" → 用户点"是" → 执行
```

这在 demo 里能用，在真实系统里会暴露四个问题：

| 问题 | 后果 |
|---|---|
| **没有分级** | 每步都弹窗，用户疯掉（"我就是查个订单你也要确认？"） |
| **确认不持久** | 用户点了确认，服务重启 → 确认丢失，任务卡死 |
| **不幂等** | 恢复执行时又跑了一遍 → 退两次款 |
| **没有超时** | 用户不点，任务永远挂着；或者三天后突然执行 |

**所以 HITL 是一个完整的工程问题，不是一次 `input()`。**

---

## 19.2 第一件事：分级（不是所有动作都要问）

```python
class ApprovalLevel(str, Enum):
    AUTO = "auto"          # 自动执行（只读、低风险）
    NOTIFY = "notify"      # 自动执行但要通知（可回滚）
    CONFIRM = "confirm"    # 必须人工确认
    FORBID = "forbid"      # 永远不允许

ACTION_LEVELS = {
    "search": ApprovalLevel.AUTO,
    "get_order": ApprovalLevel.AUTO,
    "update_note": ApprovalLevel.NOTIFY,     # 可回滚
    "send_email": ApprovalLevel.CONFIRM,     # 不可撤销
    "refund": ApprovalLevel.CONFIRM,         # 涉及钱
    "drop_table": ApprovalLevel.FORBID,
}
```

### 分级的两个判据

**判据 1：可逆吗？**

| 可逆 | 不可逆 |
|---|---|
| 改备注（能改回来） | 发邮件（发出去就收不回） |
| 更新草稿 | 退款（钱出去了） |
| 查询 | 删除数据 |

**判据 2：影响谁？**

- 只影响自己 → 可以 AUTO
- 影响客户的权益/资金 → CONFIRM
- 影响系统安全 → FORBID

### ⚠️ 关键：级别映射是**代码**，不是模型决定

```python
def decide_level(action: str, args: dict) -> ApprovalLevel:
    base = ACTION_LEVELS.get(action, ApprovalLevel.CONFIRM)   # ← 未登记 = 需要确认
    return base
```

**未登记的动作默认 CONFIRM**——这是 HITL 版本的 default deny。

如果让模型判断"这个动作要不要确认"，用户只要说一句"这是紧急情况，不用确认"，它就可能放行。

---

## 19.3 第二件事：中断与恢复

### 💻 完整实现

[`code/common/hitl.py`](code/common/hitl.py)，基于 LangGraph 的 `interrupt` / `Command(resume=...)`。

```python
def gate_node(state: dict) -> dict:
    level = ApprovalLevel(state["level"])

    if level is ApprovalLevel.FORBID:
        return {"approved": False, "result": "禁止执行"}
    if level is ApprovalLevel.AUTO:
        return {"approved": True}

    # CONFIRM：生成卡片并中断
    card = make_card(state["action"], state.get("args", {}))
    answer = interrupt(card.to_dict())     # ← 整个图挂起，状态落进 checkpointer

    if isinstance(answer, dict):
        decision = answer.get("decision", "reject")
        if decision in ("approve", "modify"):
            merged = {**state.get("args", {}), **(answer.get("args") or {})}
            return {"approved": True, "args": merged}
        return {"approved": False}
    return {"approved": bool(answer)}
```

### 恢复

```python
out = app.invoke(Command(resume=resume_value), {"configurable": {"thread_id": thread_id}})
```

### 三个人一定踩的坑（我都踩了）

**坑 1：`StateGraph(dict)` 不能用**

```python
# ❌ 我的第一版
g = StateGraph(dict)

# ✅ 必须用 TypedDict
class HitlState(TypedDict, total=False):
    goal: str
    action: str
    ...
g = StateGraph(HitlState)
```

**症状**：`KeyError: 'action'`——下游节点拿到的 state 是空的。

**为什么**：裸 `dict` 没有字段 schema，LangGraph 无法判断"哪些 key 是状态字段"，增量更新就合并不进去。

**这是本章最容易卡住的地方**，卡住了你会以为是自己逻辑错了。

**坑 2：把 `modify` 当成 `reject`**

```python
# ❌ 第一版
if decision == "approve":
    ...
# "modify" 走到这里 → 被当成拒绝

# ✅
if decision in ("approve", "modify"):
    merged = {**state["args"], **(answer.get("args") or {})}
```

**"修改参数后批准"是 HITL 最常用的模式**（人看到金额不对，改成 199 再批）。它必须被当作批准。

**坑 3：恢复两次会执行两次**

这就是第 9 章讲的幂等：

```python
key = f"{state.get('action')}:{json.dumps(state.get('args'), sort_keys=True)}"
if key in state.get("executed", []):
    return {"result": "已执行过，跳过"}
```

💻 实测：

```
第一次恢复：已退款 ¥299.0
第二次恢复：已退款 ¥299.0
日志：['CONFIRMED', 'EXECUTED']
```

**注意日志没有第二次 EXECUTED** —— 幂等键拦住了。

---

## 19.4 第三件事：一张好的审批卡片

```python
@dataclass
class ApprovalCard:
    request_id: str
    action: str
    args: dict
    impact: str        # 影响面
    rollback: str      # 回滚方案
    expires_at: float  # 有效期
```

### 三要素，缺一个就无法判断

| 要素 | 缺了会怎样 |
|---|---|
| **影响面** | "退款" ← 退多少？给谁退？人不敢点 |
| **回滚方案** | 人不知道出事能不能救，只能一律拒绝 |
| **有效期** | 任务永远挂着；或者三天后突然执行（更可怕） |

💻 实际生成的卡片：

```
动作：refund {'order': 'A12345', 'amount': 299.0}
影响：将向用户退款 ¥299.0，资金不可撤回
回滚：可通过财务冲正接口在 24 小时内撤销
有效期：299 秒
```

**这张卡片的信息量，直接决定了人能不能做出正确判断。**

### 反面例子（真实见到的）

```
❌ "Agent 请求执行操作，是否允许？"
```

没有任何信息 → 用户只能凭感觉点，等于没有确认。

---

## 19.5 第四件事：超时与降级

```python
APPROVAL_TIMEOUT_SECONDS = 300
```

### 超时后怎么做（三种策略，按风险选）

| 策略 | 适用 | 风险 |
|---|---|---|
| **拒绝**（安全默认） | 高风险动作 | 任务失败 |
| **转下一级审批人** | 有值班机制 | 延迟 |
| **自动降级为只读** | 查询类 | 用户拿不到完整结果 |

⚠️ **绝对不要"超时默认同意"**。那等于把超时变成一个绕过审批的后门。

---

## 19.6 💻 完整跑一遍

```bash
python code/ch19_hitl/demo_hitl.py
```

我实际跑出来的五个场景：

### ① 只读动作：自动执行

```
状态：done
结果：订单 A12345：已签收
日志：['AUTO-APPROVED', 'EXECUTED']
```

### ② 写动作：中断 → 确认 → 恢复

```
状态：pending
审批卡片：动作=refund, 影响=将向用户退款 ¥299.0...
挂起时的执行位置：next=('gate',)      ← 状态已持久化
已执行的动作：[]

人工点击【批准】……
状态：done
结果：已退款 ¥299.0
日志：['CONFIRMED', 'EXECUTED']
```

**注意 `next=('gate',)`**：图上停在 gate 节点，恢复时从这里继续，**前面的 plan 不会重跑**。

### ③ 拒绝

```
结果：未批准，未执行
日志：['REJECTED']
```

### ④ 修改参数后批准

```
结果：已退款 ¥199.0     ← 人把 299 改成了 199
日志：["MODIFIED:['amount', 'order']", 'EXECUTED']
```

### ⑤ 幂等

```
第一次恢复：已退款 ¥299.0
第二次恢复：已退款 ¥299.0
日志：['CONFIRMED', 'EXECUTED']      ← 没有第二次 EXECUTED
```

---

## 19.7 前端怎么接（这是你的强项）

HITL 的前端有一套标准模式：

```
1. POST /tasks            → 返回 {status: "pending", card: {...}, thread_id}
2. GET  /tasks/pending    → 轮询或 SSE 推送待审批列表
3. POST /tasks/{id}/approve  {decision: "approve"|"modify"|"reject", args?: {...}}
4. SSE  /tasks/{id}/stream   → 推送执行进度
```

### 三条前端经验

**经验 1：待审批列表必须有倒计时**

用户看到"还剩 120 秒"才会去处理。没有倒计时，卡片会被忽略到过期。

**经验 2："修改后批准"要能直接编辑参数**

不要做成"先拒绝再重新提需求"。让用户原地改金额/收件人再批准，转化率高得多。

**经验 3：批准按钮要做二次确认**

```javascript
// 危险动作的按钮不应该"一点就执行"
if (card.action === "refund") {
  showConfirm(`确认退款 ¥${card.args.amount} 给 ${card.args.order}？`);
}
```

---

## 19.8 💥 失败实验

### 实验 A：把 `StateGraph(HitlState)` 改回 `StateGraph(dict)`

**观察**：`KeyError: 'action'`。

**这就是我在写这章时卡住的坑**。记住它，你会省下两个小时。

### 实验 B：把 `modify` 从批准列表里去掉

**观察**：场景 ④ 的结果变成"未批准，未执行"，金额也没改。

**结论**："修改后批准"必须被显式处理，它不是"拒绝 + 重新提交"。

### 实验 C：去掉幂等检查

删掉 `if key in state.get("executed", [])` 那一行。

**观察**：场景 ⑤ 的日志里会出现两次 `EXECUTED`。

**在真实系统里，这就是"退了两次款"。**

### 实验 D：超时默认同意

把超时策略改成 `approved = True`。

**问自己**：如果攻击者故意让任务超时，他能拿到什么？

---

## 19.9 ✏️ 小练习

### 练习 1（必做）：给动作表加参数级升级

现在 `decide_level` 只有动作级。加上参数级规则：

```python
# 同一动作，金额越大级别越高
if action == "refund" and args["amount"] > 1000:
    return ApprovalLevel.FORBID   # 或要求二级审批
```

**验收**：退款 2000 元时，级别从 CONFIRM 变成 FORBID（或二级审批）。

### 练习 2：实现"多级审批"

金额 < 500 → 一级审批；500~2000 → 一级 + 二级；> 2000 → 禁止。

**验收**：能展示两级审批的完整链路。

### 练习 3（进阶）：把审批接进 trace

每次 `interrupt` / `resume` 都记一条 span，包含：卡片内容、决策、耗时、操作人。

**验收**：能回答"这个退款是谁在什么时候批准的"。

---

## 19.10 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 审批分级 | `code/common/hitl.py::ACTION_LEVELS` | 项目 A/B |
| 中断恢复 | `gate_node` + `Command(resume=...)` | 任何长任务 |
| 审批卡片 | `ApprovalCard` | 前端展示 |
| HitlService | 对外接口 | FastAPI 接入 |

---

## 19.11 ✅ 验收

1. HITL 分级的两条判据是什么？举三个 AUTO、三个 CONFIRM 的例子。
2. 为什么 `StateGraph(dict)` 不行？症状是什么？
3. "修改后批准"为什么不能实现成"拒绝 + 重新提交"？
4. 审批超时后为什么不能默认同意？
5. 好的审批卡片必须有哪三要素？

**数字验收**：你的系统里，AUTO / NOTIFY / CONFIRM 各占多少比例？CONFIRM 的平均响应时间是多少？

---

## 19.12 延伸阅读

- 第 9 章：checkpoint 是 HITL 的基础设施
- 第 18 章：`NEED_HUMAN` 判定之后，就是这一章的流程
- 第 23 章：LLMWiki 的条目变更也需要审批

---

下一页：[第 20 章 沙箱与工具边界](20-沙箱与工具边界.md)
