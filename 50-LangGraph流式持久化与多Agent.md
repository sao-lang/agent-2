# 第 50 章 LangGraph（三）：流式、持久化、HITL、时间回溯、子图与多 Agent

> **这一章你会遇到什么坏事**
> 你的 Agent 一次要跑 8 秒，用户盯着白屏 8 秒。你加了个 loading 动画——**但用户还是不知道它在干什么**。
> 更要命的是：跑到第 3 步要人工审批，你把服务重启了一下，**整个任务从头开始了**；
> 用户说"刚才那版答案不对"，你想回到两步前重跑，**发现历史没有存**。
>
> 更糟的是——**这些能力不是"锦上添花"**。没有它们，你的 Agent 只能是个 demo：
> 不能部署（重启就丢）、不能给业务用（不敢让 AI 直接删数据）、不能排障（不知道它走错了哪一步）。

> **学完你能做到**
> 1. 用 `stream_mode` 把"正在进行什么"流给前端，并选对模式（49.3）
> 2. 用 checkpointer + `thread_id` 让 Agent 重启后能续上（49.4）
> 3. 用 `interrupt` + `Command(resume=)` 做一次人工审批，且知道副作用会重跑（49.5）
> 4. 用 `get_state_history` 回到两步前重跑（49.6）
> 5. 用子图复用流程，并说清"什么时候该拆多 Agent"（49.7）

---

## 50.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **`stream_mode`** | 决定"流出来的是什么"：完整状态 / 改了什么 / token / 调试信息 | 49.3 |
| **`values` / `updates`** | 前者给"最新快照"，后者给"这一步谁改了什么" | 49.3 |
| **`messages`** | 模型 token 流（2 元组：chunk + 元数据） | 49.3 |
| **checkpointer** | 存状态的组件（内存 / SQLite / PG） | 49.4 |
| **`thread_id`** | 会话的标签，checkpointer 按它分区 | 49.4 |
| **`interrupt()`** | 图里的"暂停键"，把 payload 交给外部，等人给答复 | 49.5 |
| **`Command(resume=...)`** | "人的答复"送回图里，继续跑 | 49.5 |
| **子图（Subgraph）** | 一个编译好的图，可以当节点塞进另一张图 | 49.7 |

> 还有四个后面才出现：
> - **`get_state_history`**：列出所有 checkpoint，用于时间回溯（49.6）
> - **`durability`**：什么时候写盘（`exit` / `async` / `sync`）
> - **Supervisor / Handoff**：两种多 Agent 协作形态（49.7）
> - **`CachePolicy`**：节点结果缓存（49.8）

---

## 50.1 先看一个具体的坏事：三个"看起来能跑"的坑

真实场景：退款 Agent，跑一遍要先查订单、再提交退款。

先跑一次，看 `stream_mode` 各吐出什么：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lg\ch49\step1_streaming.py
```

真实输出（段 ① 节选）：

```
  ── stream_mode='values' ──
    1. messages=1 条
    2. messages=2 条
    3. messages=3 条
    4. messages=4 条

  ── stream_mode='updates' ──
    1. ['model']
    2. ['tools']
    3. ['model']

  ── stream_mode='messages' ──
    1. [model] ''
    2. [model] ''
    3. [tools] 'A1: 在保修期内'
    4. [model] '在保修'
```

**看出来了吗？** 同一张图，三种模式吐出三种完全不同的**形状**：

| 模式 | 你拿到什么 | 前端能做什么 |
|---|---|---|
| `values` | 每一轮的**完整 state** | 渲染整页 / 同步数据库 |
| `updates` | 每一轮**哪个节点改了什么** | 进度条、"正在调用工具…" |
| `messages` | 模型 **token** + 元数据 | 打字机效果 |

**选错了会怎样？**

| 错误选择 | 后果 |
|---|---|
| 用 `values` 做打字机 | 每轮才更新一次，用户看到的是一段一段蹦（不是流） |
| 用 `messages` 做进度条 | 你会拿到 `ToolMessage`，只能靠猜"这是工具结果还是模型的话" |
| 用 `updates` 做打字机 | 拿不到 token，只能等整段生成完 |

**结论：`stream_mode` 不是"开关"，是"选一个视图"。**

---

## 50.2 为什么"把完整结果返回给前端"不够

你可能会想：我 `invoke()` 拿到完整结果，一次性返回给前端，不就行了？

对"3 秒能算完"的任务可以。对 Agent 不行，因为：

| 问题 | 具体数字（第 35 章口径） |
|---|---|
| **首字延迟** | 不流式时，用户要等**整轮**（可能 5–10 秒）才有第一个字 |
| **不知道在干什么** | 8 秒白屏 → 用户以为卡死了 → 刷新 → 重复提交 |
| **步骤不可见** | 调了 3 个工具，用户只看到最终答案，无法判断"它查得对不对" |

**所以我们需要"边跑边说"。** 但"说"分两种，对应两种人：

- **对用户说**：token（打字机）+ "正在查询订单…"（进度）
- **对开发者说**：每一步的输入输出（排查）

`stream_mode` 就是在这两者之间选。

> 💥 **失败实验 1：用 `values` 冒充打字机**
> 把 `step1` ② 里的 `stream_mode=["updates", "messages"]` 改成 `"values"`。
> 观察输出：每条都是一个完整 state，**没有 token 级别的流**。
> 结论：`values` 只在**每一轮结束**时吐一次。如果一轮要 5 秒，用户就等 5 秒。

---

## 50.3 流式到底是什么（10 行代码看懂）

### 一句话

> **流式 = 图每走一小步，就吐一个 chunk 给你；你决定哪些给用户看、哪些只给日志看。**

### 最小例子

```python
for mode, chunk in app.stream(inputs, stream_mode=["updates", "messages"]):
    if mode == "messages":
        msg, meta = chunk                       # ①
        print("token:", meta["langgraph_node"], text_of(msg))
    else:
        print("event:", list(chunk))            # ②
```

| 行 | 在做什么 | 备注 |
|---|---|---|
| ① | `messages` 模式下 chunk 是 **2 元组** | 元数据里有 `langgraph_node`（哪个节点吐的） |
| ② | `updates` 模式下 chunk 是 **dict**（节点名 → 更新） | 一般只有一个键 |

真实输出（段 ②）：

```
    [token] model: ''
    [token] model: ''
    [event] ['model']
    [token] tools: 'A1: 在保修期内'
    [event] ['tools']
    [token] model: '在保修'
    [token] model: '期内，'
    [token] model: '可以免'
    [token] model: '费修。'
    [token] model: ''
    [event] ['model']
```

### 六种模式速查

真实输出（段 ④）：

```
  values     每一轮结束的**完整 state**（最新快照），适合「渲染整页」
  updates    每一轮**哪个节点改了什么**，适合「进度条 / 事件流」
  custom     节点里用 get_stream_writer() 自己推任意事件（进度百分比等）
  debug      每个 task 的开始/结束/结果，适合本地排查
  messages   模型 token 流 + 元数据（2 元组 (message_chunk, metadata)）
```

| 模式 | 你该用它做什么 | 千万别用它做什么 |
|---|---|---|
| `values` | 落库、渲染完整页面 | 做打字机 |
| `updates` | 进度提示 | 拿文本 |
| `messages` | 打字机 | 区分"工具结果"和"模型的话"（要靠类型判断） |
| `custom` | 自定义进度（"正在解析第 3/10 个文件"） | —— |
| `debug` | 本地排查 | 生产（信息太多） |
| 组合列表 | 生产标配（`["updates","messages"]`） | —— |

### ✏️ 停下来想一想

`messages` 模式下，你收到了 `[token] tools: 'A1: 在保修期内'`。

**这是模型的 token 吗？**

（不是。这是 `ToolMessage`。如果你把收到的所有 chunk 都拼进气泡，用户会在回答里看到"工具说了什么"。49.4 会讲怎么区分。）

---

## 50.4 从"能流"到"能存"（阶梯代码 step1 / step2）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_streaming.py` | `stream_mode` 六种 + 组合 | — |
| step2 | `step2_persist_hitl.py` | checkpointer / `interrupt` / 时间回溯 | step1 的图跑完就没了 |
| step3 | `step3_subgraph_multiagent.py` | 子图 / Supervisor / Handoff / 策略 | step2 只有一个"单体图" |

### step2：持久化与 HITL

痛点一句话：**跑到第 3 步要审批，进程一重启全丢了。**

真实输出（段 ①）：

```
① 先看不带 checkpointer 会怎样
  不带 checkpointer 时 invoke 返回：__interrupt__ 存在 = True
  → 看起来「停住了」，但状态没地方存
  想继续时 → RuntimeError: Cannot use Command(resume=...) without checkpointer
```

**这个坑很阴**：不带 checkpointer 时，`invoke` **不报错**，还返回了 `__interrupt__`——你会以为"成了"。
直到你想 `resume` 的时候才发现：**没地方存，续不上**。

带上之后就正常了（段 ②）：

```
  返回里有 __interrupt__：True
  人看到的问题 = {'question': '是否批准退款 99 元？', 'order': 'A1201'}
  当前状态 = next=('approve',), status=drafted
  → 进程此刻可以**退出**。状态已经写进 checkpointer，下次接着跑。
```

人的决定送回去（段 ③）：

```
  继续跑完 → status=done, log=['draft', 'approve:yes', 'execute']
```

### step3：子图与多 Agent

短板一句话：**一个图 20 个节点就画不清了，想复用"客服子流程"只能复制粘贴。**

真实输出（段 ①②）：

```
① 子图：编译好的图可以直接 add_node
  [退款子流程] 处理了：能退吗
  → 共享键（question/answer）自动传进传出；子图内部字段不需要暴露给父图

② Supervisor：一个调度员决定下一步交给谁
  我要退款     trace=['supervisor→refund_agent', 'refund_agent', 'supervisor→FINISH']  result='退款已受理'
  耳机坏了     trace=['supervisor→tech_agent', 'tech_agent', 'supervisor→FINISH']  result='已安排换新'
  你们几点下班   trace=['supervisor→FINISH']  result=''
```

**注意第三行**：没命中任何分支时，直接 `FINISH`，`result` 是空字符串。
**这就是"supervisor 必须知道什么时候收工"的意思**——否则它会一直派活（我们第一版就写成了死循环，直到 `GraphRecursionError`）。

---

## 50.5 核心实现（逐行解释）

这一节把 `interrupt` 的 15 行拆开——**这是 HITL 的核心，也是最容易写错的地方**。

```python
def approve(state: S) -> Command:                              # ①
    decision = interrupt({                                     # ②
        "question": f"是否批准退款 {state['amount']} 元？",
        "order": "A1201",
    })
    if decision == "yes":                                      # ③
        return Command(goto="execute", update={"status": "approved"})
    return Command(goto=END, update={"status": "rejected"})    # ④
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | 返回 `Command`（既能跳转又能改状态） | 用普通 dict 就改不了跳转 |
| ② | **暂停整个图**，把 payload 交给外部 | 用 `input()` 会卡死 worker 线程 |
| ③ | `resume` 的返回值就是人的决定 | 以为 `interrupt` 会返回 True/False（它返回**你传进去的东西**） |
| ④ | 拒绝就 `goto=END` | 忘了改状态，`status` 会一直是 `drafted` |

**关键理解：`interrupt()` 的行为是"第二次执行到这里时，直接返回 resume 的值"。**
也就是说，**这个函数会被执行两次**：

```
第 1 次：执行到 interrupt() → 抛出一个"暂停信号" → 图停下
       （外部：invoke 返回 __interrupt__，进程可以退出）
第 2 次：图中断恢复 → 从 approve 的开头重新执行 → interrupt() 这次直接返回 "yes"
```

### ⚠️ 一个必须知道的坑：`interrupt()` 之前的副作用会重跑

真实输出（段 ⑤）：

```
  你的图如果是这样：

      charge_card  →  interrupt(等审批)  →  ship

  那么"从 checkpoint 回溯重跑"时会**再次执行 charge_card**。
  真实项目三条防线：
    1. 把有副作用的动作放在 interrupt **之后**
    2. 幂等键：charge_card(order_id, idempotency_key=f"{thread_id}:{step}")
    3. 副作用节点自己查一次"做过没有"（读 DB，不读 state）
```

**这是全章最贵的一课**：因为"恢复 = 从节点开头重跑"，不是"从 `interrupt()` 那一行继续"。
所以 `interrupt()` 之前的所有代码都会**再跑一遍**。

### 三个设计取舍

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 审批粒度 | **按"动作"而不是"步骤"** | 每步都问：用户烦死，直接点"全同意"（第 32 章） |
| 审批入口 | **`HumanInTheLoopMiddleware`**（第 46 章） | 手写 `interrupt` 容易漏分支 |
| 持久化级别 | **长任务用 `sync`** | 默认 `async`：崩溃丢当前轮 |

---

## 50.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lg/ch50/step2_persist_hitl.py`

### 问题 ①：怎么回到两步前重跑？

真实输出（段 ④）：

```
  共 5 个 checkpoint：
    0. step=3 next=() status='done'
    1. step=2 next=('execute',) status='approved'
    2. step=1 next=('approve',) status='drafted'
    3. step=0 next=('draft',) status=''
    4. step=-1 next=('__start__',) status=None

  找到 approve 之前的快照：checkpoint_id=1f1ce5ed…
  在旧快照上 resume='no' → status=done（走了拒绝分支）
```

**`get_state_history(cfg)` 返回一个列表，**倒序**（最新的在最前）**。每个元素是一份完整快照。

用法：

```python
h = next(x for x in app.get_state_history(cfg) if x.next == ("approve",))
app.invoke(Command(resume="no"),
           {**cfg, "configurable": {"checkpoint_id": h.config["configurable"]["checkpoint_id"]}})
```

**注意**：用 `checkpoint_id` 重跑会**fork 出一条新分支**，原来那条历史还在。所以你可以"两条都留着对比"。

### 问题 ②：怎么让用户看到"正在查询订单"？

```python
for mode, chunk in app.stream(inp, stream_mode=["updates", "messages"]):
    if mode == "updates":
        node = list(chunk)[0]
        yield {"event": f"正在执行 {node}"}
    else:
        msg, meta = chunk
        if type(msg).__name__ == "AIMessageChunk":
            yield {"token": text_of(msg)}
```

**决断点**：`type(msg).__name__ == "AIMessageChunk"` 才是模型 token。`ToolMessage` 不要当文本给用户。

### 问题 ③：怎么判断"该拆多 Agent"？

真实输出（段 ⑤）：

```
  任务边界清晰（退款 / 技术 / 物流）                可以拆
  每个子任务都要看完整上下文                       别拆，只会多付一遍上下文钱
  子任务能并行                              可以拆（Send）
  只是「步骤多」                             用一张图 + 多个节点，不要拆 Agent
  需要不同权限/不同工具集                        可以拆（收窄工具，第 55 章）

  → 一句话：拆多 Agent 的理由应该是「隔离」，不是「分工」。分工用节点就够了。
```

**这句话请记牢**：**分工用节点，隔离才拆 Agent。**

### 🎯 到这里，你已经掌握了 LangGraph 的全部核心机制

| 能力 | 在哪一节 |
|---|---|
| State / reducer | 第 48 章 |
| 条件边 / Send / Command / Runtime | 第 49 章 |
| 流式六种模式 | 49.3 |
| checkpointer + interrupt + 时间回溯 | 49.4–49.6 |
| 子图 / Supervisor / Handoff | 49.4 step3 |

**框架部分到此结束。** 第 50–52 章换一条线：LlamaIndex、RAGAS、LangSmith/LangFuse。

---

## 50.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数

把 `step1` ① 的 `modes` 列表加上 `"tasks"`，重跑。
**验收标准**：你能说出它和 `values` 的区别（提示：`tasks` 给的是"每个 task 的结果"，粒度更细）。

### 练习 2（20 分钟）：接到你自己的项目上

把你项目里**任意一个**"长任务"改成可续跑的。

**最低要求清单**：
- [ ] 换成 `SqliteSaver`（不要用 `InMemorySaver`，重启就丢）
- [ ] `thread_id` 用业务键（订单号/工单号），不要随机
- [ ] 有副作用的动作放在 `interrupt` **之后**
- [ ] 加一条测试：`invoke` → 中断 → 新建 app 实例 → `Command(resume=...)` 能续上

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：副作用放在 `interrupt` 之前。**
在 `step2` 的 `draft` 节点里加一行 `print("打款了")`，重跑 ②③。观察"打款了"打印了几次。
结论：**恢复会从节点开头重跑，所以"打款"执行了两次。**

**实验 B：`thread_id` 每次随机。**
把 `cfg` 改成 `{"configurable": {"thread_id": str(random.random())}}`。重跑 ②③。
观察 `Command(resume=...)` 报什么错。结论：**随机 thread_id = 每次都是新会话 = 记忆失效 + 无法恢复。**

**实验 C：把 `durability` 改成 `"exit"`。**
在 `compile(checkpointer=..., durability="exit")` 下，让图在**跑到一半时抛异常**。
观察 checkpointer 里有没有中间状态。结论：**`exit` 只在"结束或中断"时写，中途崩了就丢了。**

---

## 50.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `Cannot use Command(resume=...) without checkpointer` | 没传 checkpointer | `compile(checkpointer=...)` |
| 中断后重启，任务从头开始 | 用了 `InMemorySaver` | 换 `SqliteSaver` / PG saver |
| `thread_id` 找不到 | 每次请求都换了 thread_id | 用业务键 |
| 同一笔钱扣了两次 | 副作用在 `interrupt` 之前 | 挪到之后 + 幂等键（49.5） |
| 打字机里出现工具输出 | 把 `ToolMessage` 当 token 拼了 | 判断 `AIMessageChunk` |
| `stream_mode="messages"` 报 `No generations found` | 模型流式返回为空（假模型常见） | 确保至少吐一块（见 `_fake.py` 的说明） |
| Supervisor 一直派活 | 没有"收工"条件 | 加 `if state["result"]: goto=END` |
| `CachePolicy` 不生效 | `compile()` 没传 `cache=` | 传 `BaseCache` 实例 |
| 时间回溯后状态串了 | 用了同一个 `checkpoint_id` 但期望新分支 | 回溯会 fork，新分支不覆盖旧的 |
| `GraphRecursionError` | 循环没有终止条件 | 加计数器/条件；别依赖 `recursion_limit` |

---

## 50.9 章末自测

**Q1** `values` 和 `updates` 分别适合什么？

<details>
<summary>提示</summary>
`values`：完整快照，适合落库/整页渲染。
`updates`：这一步谁改了什么，适合进度条。
</details>

**Q2** 为什么"没有 checkpointer 就没有记忆"？

<details>
<summary>提示</summary>
历史要存在某个地方才能在下一轮续上。`InMemorySaver` 存在进程里，重启就丢；
`SqliteSaver` 落盘，才能跨进程。
</details>

**Q3** `interrupt()` 会被执行几次？为什么？

<details>
<summary>提示</summary>
两次。第一次抛出"暂停"，恢复时从**节点开头**重新执行，`interrupt()` 直接返回 resume 值。
所以它之前的副作用会重跑。
</details>

**Q4** 什么时候该拆多 Agent？

<details>
<summary>提示</summary>
需要"隔离"时（权限、工具集、上下文），不是"分工"时。分工用节点。
</details>

**加分题**

> 同事说："HITL 很简单，`interrupt()` 一行就行。"

参考思路：**`interrupt` 本身是一行，难的是它周围的三件事**：
① 状态必须持久化（要 checkpointer + 业务键 thread_id）
② 副作用必须幂等（恢复会重跑）
③ 审批体验（批量、超时、审计）——那是第 32 章和产品的事。
**所以"能不能用"取决于周围，不取决于那一行。**

---

## 50.10 可选补课：`durability` 与 `CachePolicy` 的正确姿势

> ⚠️ **这一节可以先跳过。** 等你在意"崩溃丢多少"和"缓存为什么没生效"时再看。

### `durability` 三档

```python
app = g.compile(checkpointer=saver, durability="sync")
```

| 值 | 什么时候写盘 | 崩溃丢多少 | 适合 |
|---|---|---|---|
| `"exit"` | 图结束 / 中断时 | 当前整轮 | 短任务、可重跑 |
| `"async"`（默认） | 每步异步写 | 最多一步 | 大多数场景 |
| `"sync"` | 每步同步写完才继续 | 几乎不丢 | 长任务、涉及钱 |

### `CachePolicy` 必须配 `cache=`

```python
from langgraph.types import CachePolicy

g.add_node("expensive", expensive, cache_policy=CachePolicy(ttl=60))
app = g.compile(cache=InMemoryCache())     # ← 少了这句，缓存静默不生效
```

**这个坑和"没传 checkpointer 就没记忆"是同一类**：**配置写在两处，漏一处不报错。**
第 54.6 节把这类问题统称为"装配故障"。

---

## 50.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 六种流式模式 | `code/framework/lg/ch50/step1_streaming.py` | 第 41 章 Docker 交付的 SSE 接口 |
| checkpointer + HITL + 回溯 | `code/framework/lg/ch50/step2_persist_hitl.py` | 第 32 章 HITL、第 22 章长任务 |
| 子图 + Supervisor + 策略 | `code/framework/lg/ch50/step3_subgraph_multiagent.py` | 第 36 章多 Agent 判据 |

**这一节建立的"可复用资产"**：`stream_mode=["updates","messages"]` 这段循环，在第 41 章会变成 FastAPI 的 SSE 端点。

---

## 50.12 ✅ 验收

跑完三个脚本，检查五件事：

**① 你能说出三种流式模式的区别**

不看代码，说出 `values` / `updates` / `messages` 各吐什么形状。

**② 你能复现"没有 checkpointer 就不能 resume"**

说出错误原文，以及它为什么"看起来能跑"（`__interrupt__` 还是返回了）。

**③ 你能解释"副作用会重跑"**

用 `charge_card → interrupt → ship` 这个图，说出重跑时发生了什么。

**④ 你能用 `get_state_history` 找到某个快照**

说出"列表是正序还是倒序"、"怎么用 checkpoint_id 重跑"。

**⑤ 一个数字**

`step2` ④ 的输出里有 `共 5 个 checkpoint`。

**现在算一个数**：如果每个 checkpoint 存的是完整 state（假设 2KB），
一个用户一天跑 20 个任务、每个任务 10 个 checkpoint，
**一天下来这个用户产生多少存储？1000 个用户呢？**

<details>
<summary>答案</summary>

单用户：`20 × 10 × 2KB = 400KB/天` ≈ **12MB/月**
1000 用户：`400MB/天` ≈ **12GB/月**

这就是为什么生产必须配**清理策略**（按天/按任务数删），
也是为什么"把完整文档塞进 State"会很快把数据库撑爆（第 23 章 State 设计）。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 51 章 LlamaIndex——另一套检索路线。
LangChain/LangGraph 的路线是"装配 + 画图"，LlamaIndex 的路线是"数据 + 索引 + 查询引擎"。
你会看到它在"把 1000 份 PDF 变成可查询索引"这件事上，比 LangChain 省多少代码。

> 📎 参考：本章对应基础教程第 25 章《LangGraph 高级特性》、第 26 章《LangGraph 多智能体与 A2A》的知识点。
> 本书额外补充了**"没有 checkpointer 时中断不报错却续不上"**这个真实坑，以及 `interrupt` 前后副作用的影响。
