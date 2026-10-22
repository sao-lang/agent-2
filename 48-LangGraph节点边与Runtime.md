# 第 48 章 LangGraph（二）：节点、边、Send/Command 与 Runtime

> **这一章你会遇到什么坏事**
> 上一章的图是一条直路。现在业务要"按问题类型走不同分支"，你写了个条件边——结果**线上 500**，
> 因为映射表里漏了一个键。你补上，又发现"一份文档要拆 5 段并行处理"根本画不出来，
> 条件边只能"选一条路"。
>
> 更糟的是——**你开始把"当前用户 ID""当前租户"塞进 State**，因为它们要跨节点用。
> 然后你发现：它们进了 checkpoint、进了 prompt、还被模型在回答里复述了出来。

> **学完你能做到**
> 1. 用条件边写"按类型分流"，并说清"映射表漏键"为什么会 500（48.3）
> 2. 用 `Send` 把"一份输入"变成"N 路并行"（48.4）
> 3. 用 `Command` 一步完成"跳转 + 改状态"（48.4）
> 4. 用 `Runtime` 传"当前请求上下文"，**不把它写进 State**（48.5）
> 5. 用 `ToolNode` + `tools_condition` 手搭一个和 `create_agent` 等价的图（48.6）

---

## 48.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **条件边** | "到了岔路口，看一个信号决定走哪条"，就是 if/elif | 48.3 |
| **映射表（path_map）** | "信号值 → 目标节点"的对照表，像交通指示牌 | 48.3 |
| **`Send`** | "一条指令：去某个节点，带上这份数据"，可以发 N 条 | 48.4 |
| **`Command`** | 节点返回值的一种："跳到哪里 + 顺便改状态" | 48.4 |
| **`Runtime`** | 运行时的"当前请求"信息，**不进 state、不进 prompt** | 48.5 |
| **`context_schema`** | 声明 Runtime 里装什么（租户、用户、权限） | 48.5 |
| **`ToolNode`** | LangGraph 预置节点：一次执行多个 `tool_calls` | 48.6 |
| **`tools_condition`** | 预置条件函数：有 `tool_calls` 就去 `tools`，否则结束 | 48.6 |

> 还有三个后面才出现：
> - **`InjectedState` / `InjectedStore`**：让工具读到 state 和长期记忆（48.6）
> - **`Command(resume=...)`**：带"人的决定"继续跑（第 49 章）
> - **`langgraph.types.RetryPolicy`**：节点级重试（第 47 章已用）

---

## 48.1 先看一个具体的坏事：条件边漏一个键，就是线上 500

真实场景：售后 Agent 要按问题类型分流——退款、物流、投诉、其它。

你写了条件边和映射表，看起来很完整。跑一下：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lg\ch48\step1_nodes_edges.py
```

真实输出（段 ①，先看正常情况）：

```
  我要退款       → [refund   ] 退款 7 个工作日到账
  物流呢        → [logistics] 包裹已到驿站
  我要投诉       → [escalate ] 已转人工，2 小时内联系您
  你们老板是谁     → [unknown  ] 没听懂，能再说一次吗？
```

然后我们把映射表里 `logistics` 那一行删掉（模拟"改了分类逻辑忘了改映射表"）：

真实输出（段 ③）：

```
③ 一个坑：条件边返回了不存在的节点名
  → KeyError: 'logistics'
  → 映射表里漏掉一个键，就是一个线上 500。所以映射表要和 classify 的返回值同步维护。
```

| 你以为 | 实际 |
|---|---|
| 映射表没写 = 走默认分支 | **`KeyError`**，整次请求失败 |
| 编译期能发现 | **运行时才炸**，而且是特定输入才炸 |
| 测试能覆盖 | 除非你测了**每一种**输入类型 |

**结论：条件边不是"加个 if"，它是"一张必须和路由函数严格对齐的契约"。**

---

## 48.2 为什么"用 if 判断写在节点里"不够

你可能会想：我在一个节点里 `if ... elif ...` 全做完，不分叉不行吗？

技术上可以，但你会付出三个代价：

| 代价 | 具体表现 |
|---|---|
| **节点变成一个巨大的 if-else 树** | 20 个分支后没人敢改；改一处要重测全部 |
| **无法并行** | 所有分支都在一个节点里，只能串行 |
| **无法单独重试** | 一个分支失败，整个节点重跑（包括已经成功的分支） |
| **trace 只有一个节点** | 出问题看不出走了哪条（第 38 章） |

**所以我们需要"把分支变成图的结构"。** 这样：

- 每个分支是一个节点 → 可以单独重试、单独打点
- 分支之间可以并行 → 省时间
- 走哪条路在 trace 里是一条**边**，一眼能看出来

> 💥 **失败实验 1：让条件边返回一个"看起来对"的值**
> 把 `step1` ① 的 `classify` 改成返回 `"退款"`（中文），映射表里还是 `"refund"`。
> 重跑。观察 `KeyError: '退款'`。
> **结论：条件边是"精确匹配"，没有模糊、没有默认。**

---

## 48.3 条件边到底是什么（10 行代码看懂）

### 一句话

> **条件边 = 一个函数（看 state 返回一个字符串）+ 一张映射表（字符串 → 节点名）。**

### 最小例子

```python
g.add_conditional_edges(
    "classify",                      # 从哪个节点出发
    lambda s: s["route"],            # 依据：读 state 里的 route
    {                                # 映射表：route 的值 → 去哪
        "refund": "refund",
        "logistics": "logistics",
        "escalate": "escalate",
        "unknown": "fallback",
    },
)
```

**第二个参数也可以是函数本身**（`def router(state): return "refund"`），第三个参数（映射表）是**可选但强烈建议**的：

| 写不写映射表 | 效果 |
|---|---|
| 不写 | 函数返回什么就当节点名（拼错要到运行时才发现） |
| 写 | 返回的值必须**在表里**，否则 `KeyError`（错误更早、更明确） |

**反直觉的是**：加了映射表反而**更容易 500**（漏键就炸）。但**我们仍然推荐加**——因为"炸在明确的地方"比"炸在莫名其妙的节点名上"好排查。

### 条件边还能返回 `END`（做循环）

真实输出（段 ②）：

```
  循环 3 次 → n=3，trace=['step(0)', 'step(1)', 'step(2)']
  → 条件边返回 END 就是「结束」；这一步构成 while 循环（第 16 章的步数上限要自己加）
```

```python
def router(s): 
    return "step" if s["n"] < 3 else END
```

**这就是 LangGraph 里所有"循环"的写法**：条件边指回自己（或上游节点），条件不满足时返回 `END`。

> ⚠️ **`langgraph` 有 `recursion_limit`（默认 10007）**，但别指望它兜底——上万次空转也够烧一笔钱了。**自己要加步数上限**（第 16 章）。

### ✏️ 停下来想一想

条件边返回 `END` 会让图结束。那如果我想"暂停一下，等人确认再继续"，返回什么？

（提示：那是 `interrupt()` 的事，第 49 章。`END` 是"真的结束"。）

---

## 48.4 从"分流"到"扇出"（阶梯代码 step1 / step2 / step3）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_nodes_edges.py` | 条件边 + 映射表 + 循环 | — |
| step2 | `step2_send_command_runtime.py` | `Send` 扇出 / `Command` / `Runtime` | step1 只能"选一条路" |
| step3 | `step3_tool_node.py` | `ToolNode` + `tools_condition` 手搭 Agent | step2 还没有"模型 + 工具"的循环 |

### step2 之一：`Send` —— 一份输入变 N 路并行

痛点一句话：**条件边只能选一条路，但"一份文档拆 5 段处理"需要 5 条路同时走。**

真实输出（段 ①）：

```
  4 个块 → 得到 4 条摘要
    [0] 退货政策：30 天内…
    [1] 退款时效：7 个工作日…
    [2] 运费险：质量问题才生效…
    [3] 换货：先退回再寄出…

  → Send 的第二个参数是一个**独立的小状态**，不是父 state（这是最常错的地方）
  → summaries 必须用 reducer 拼接，否则 N 条写回会冲突（第 47 章 ③）
```

写法：

```python
def fan_out(state) -> list[Send]:
    return [Send("summarize", {"chunk": c, "idx": i}) for i, c in enumerate(state["chunks"])]

g.add_conditional_edges(START, fan_out, ["summarize"])    # ← 只能从条件边返回 Send
```

**两个必须记住的点**：

| 点 | 说明 |
|---|---|
| `Send` **只能从条件边返回** | 从节点 `return` 会报 `InvalidUpdateError: Expected dict, got [Send(...)]`（我们踩过） |
| `Send` 的第二个参数是**子状态** | 不是父 state。所以子节点看不到多余字段（这是好事，省 token） |

### step2 之二：`Command` —— 跳转 + 改状态一步完成

真实输出（段 ②）：

```
  log = ['step 0', 'work', 'step 1', 'work', 'done']
  step = 2

  → Command 的价值：跳去哪、改什么，写在同一个返回值里。
    条件边只能选路，改状态还得另外 return —— 两件事拆在两地就容易写错。
```

```python
def node_cmd(state):
    if state["step"] >= 2:
        return Command(goto=END, update={"log": ["done"]})
    return Command(goto="work", update={"step": state["step"] + 1, "log": [...]})
```

**`Command` 也可以做扇出**：`Command(goto=[Send(...), Send(...)], update={...})`。
适合"我既要把这个任务拆成三份，又要顺手记一笔"的场景。

### step2 之三：`Runtime` —— 当前请求信息

真实输出（段 ④）：

```
  context=Ctx('acme', True) → {'answer': '[debug] 租户 acme 的答案'}

  → context 不进 checkpoint、不进消息历史：它只活在这一次调用里
  → 别把租户 ID 塞进 State（会被持久化、会被模型看到）
```

```python
@dataclass
class Ctx:
    tenant: str
    debug: bool

def get_answer(state, runtime: Runtime[Ctx]) -> dict:
    c = runtime.context
    return {"answer": f"{'[debug] ' if c.debug else ''}租户 {c.tenant} 的答案"}

g = StateGraph(S, context_schema=Ctx)
app.invoke({"answer": ""}, context=Ctx("acme", True))
```

**这张表最关键**：

| 放哪 | 会被持久化 | 模型能看到 | 适合放什么 |
|---|---|---|---|
| **State** | ✅ | ✅（在 messages 里） | 业务数据（问题、答案、检索结果） |
| **Runtime context** | ❌ | ❌ | 租户、用户、权限、debug 开关 |
| **Store** | ✅（独立存储） | ❌ | 跨会话长期记忆 |

**所以"当前用户 ID"绝对不能放 State**——它会被 checkpointer 存下来、还会被模型在回答里复述。

### step3：手搭一个和 `create_agent` 等价的图

真实输出（段 ②）：

```
② 和 create_agent 的等价性
  手搭图节点 = ['__start__', 'model', 'tools', '__end__']
  create_agent 节点 = ['__start__', 'model', 'tools', '__end__']
  → 一模一样（create_agent 多了 state 扩展、中间件节点、checkpointer 支持）
```

```python
g.add_node("model", call_model)
g.add_node("tools", ToolNode([query_order]))
g.add_edge(START, "model")
g.add_conditional_edges("model", tools_condition)   # 有 tool_calls → "tools"，否则 → END
g.add_edge("tools", "model")
```

**七个元素，就是整个 Agent。** 你在第 45 章看到的"一行代码"，展开就是这七行。

---

## 48.5 核心实现（逐行解释）

这一节逐行拆解"`Send` 扇出 + 汇总"这段——**它是 map-reduce 在 Agent 里的标准形态**。

```python
def fan_out(state: MapState) -> list[Send]:                       # ①
    return [Send("summarize", {"chunk": c, "idx": i})             # ②
            for i, c in enumerate(state["chunks"])]

class ReduceState(TypedDict):                                      # ③
    chunks: list[str]
    summaries: Annotated[list[str], operator.add]                  # ④

def summarize(state: dict) -> dict:                                # ⑤
    return {"summaries": [f"[{state['idx']}] {state['chunk'][:12]}…"]}   # ⑥

g.add_conditional_edges(START, fan_out, ["summarize"])            # ⑦
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | 一个普通函数，返回 `list[Send]` | 从节点 `return` 会崩 |
| ② | 每个 `Send` 带一份**只属于这条分支**的数据 | 传父 state：子节点读到一堆无用字段，token 白花 |
| ③ | 父图的 State | —— |
| ④ | `summaries` 加 `operator.add` | N 条写回冲突（第 47 章 ③） |
| ⑤ | 子节点只读自己需要的两个字段 | —— |
| ⑥ | 返回的仍是"补丁"，但要经过 reducer | —— |
| ⑦ | 第三个参数是"可能的目标节点列表"（校验用） | 拼错节点名到运行时才发现 |

**三个设计取舍**

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 扇出的粒度 | **按"独立单元"切**（一段一个 Send） | 一个 Send 里塞 10 段：等于没扇出 |
| 子状态传什么 | **只传这条分支要的** | 传全量：上下文翻倍（第 24 章） |
| 汇总放哪 | **父图的 reducer** | 让某个节点"收集"：它就变成串行瓶颈 |

### ⚠️ 一个必须知道的坑：`Send` 的并发上限

`Send` 出去 1000 条，框架会**同时调度 1000 个 task**。这时候：

1. 如果节点里调模型 → **1000 个并发请求**，直接打爆 rate limit
2. 如果节点里查数据库 → 连接池耗尽
3. 内存会涨（每个 task 都有独立状态）

**生产做法：分批。**

```python
BATCH = 20
for i in range(0, len(chunks), BATCH):
    batch = chunks[i:i+BATCH]
    app.invoke({"chunks": batch, "summaries": []})
```

或者用信号量在节点内部限流。**没有"自动限流"这回事，你得自己管。**

> 💥 **失败实验 2：把条件边的映射表删掉**
> 把 `step1` ① 的 `add_conditional_edges("classify", lambda s: s["route"], {...})` 的第三个参数删掉。
> 重跑四条问题。观察 `unknown` 那条会不会报错。
> **结论：不写映射表时，返回值直接当节点名。** 如果 `classify` 返回了 `"unknown"` 而你没有叫 `unknown` 的节点，报的是 `KeyError`/`ValueError`——错误信息比"映射表漏键"难懂得多。

---

## 48.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lg/ch48/step3_tool_node.py`

### 问题 ①：怎么让工具读到 state 里的东西？

```python
from langchain_core.tools import InjectedToolArg

@tool
def recall_user_pref(user_id: Annotated[str, InjectedToolArg()]) -> str:
    """读取用户偏好（user_id 由框架注入）。"""
    return f"用户 {user_id} 偏好：不要打电话"
```

真实输出（段 ③）：

```
  recall_user_pref 的 schema = []
  → user_id 不在 schema 里，模型无法传；调用时必须由调用方补齐
  不补会怎样：ValidationError: 1 validation error for recall_user_pref
user_id  Field required
  补齐后：用户 u1 偏好：不要打电话，只用短信
```

**结论**：注入参数模型看不到，但**必须有人补**——用 `ToolNode` 时框架会补 `InjectedState` / `InjectedStore`，普通调用要自己补。

### 问题 ②：`tools_condition` 到底做了什么？

```python
g.add_conditional_edges("model", tools_condition)
```

**它只做一件事**：看最后一条消息有没有 `tool_calls`。有 → 返回 `"tools"`；没有 → 返回 `END`。

**所以你可以完全不用它**，自己写：

```python
g.add_conditional_edges(
    "model",
    lambda s: "tools" if getattr(s["messages"][-1], "tool_calls", None) else END,
)
```

### 问题 ③：手搭图 vs `create_agent`，选哪个？

真实输出（段 ⑤）：

```
  用 create_agent 当：
    · 标准「模型 + 工具」循环
    · 想直接用现成中间件（限流/摘要/审批/脱敏）
    · 需要 checkpointer / interrupt / 子图

  手搭图当：
    · 流程里有非 ReAct 的部分（先检索再生成再校验再重试）
    · 需要精确控制"哪一步能调哪个工具"
    · 需要 Send 做 map-reduce
    · 想彻底搞懂框架在干什么

  实战常见做法：外层手搭业务图，内层某个节点用 create_agent 当"任意 Agent"。
```

**最后一句话最重要**：**"外层手搭 + 内层 create_agent"是最常见的生产形态。**

### 🎯 到这里，你已经掌握了"画任意复杂的图"

| 能力 | 在哪一节 |
|---|---|
| 条件边 + 映射表 + 循环 | 48.3 |
| `Send` 扇出 | 48.4 |
| `Command` 跳转+改状态 | 48.4 |
| `Runtime` context | 48.5 |
| `ToolNode` + `tools_condition` | 48.6 |

**剩下的都是"让图能存、能停、能回放"（第 49 章）。**

---

## 48.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数

把 `step2` ① 的 `chunks` 从 4 条扩到 20 条，重跑。
**验收标准**：你能说出"如果我改成 2000 条会发生什么"（提示：48.5 的并发上限）。

### 练习 2（20 分钟）：接到你自己的项目上

把你项目里**任意一条** `if/elif/else` 的分支逻辑改成图。

**最低要求清单**：
- [ ] 每个分支一个节点（不要再把逻辑塞在一个节点里）
- [ ] 条件边有**完整**的映射表
- [ ] 路由函数和映射表的键**用同一个常量集合**维护（避免漏键）
- [ ] 加一条测试：把每个分支各跑一遍

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：从节点返回 `Send`。**

```python
def fan_out_as_node(state):     # ← 当成普通节点用
    return [Send("summarize", {"chunk": c}) for c in state["chunks"]]
g.add_node("fan_out", fan_out_as_node)
```

观察 `InvalidUpdateError: Expected dict, got [Send(...)]`。结论：**`Send` 只能从条件边返回。**

**实验 B：让 `Command` 跳到一个不存在的节点。**
重跑，观察错误信息。结论：**`Command(goto=...)` 拼错没有编译期检查。**

**实验 C：把租户 ID 塞进 State。**
在 `step2` ④ 里，把 `tenant` 加进 `Rs`，并通过 state 传递。
然后用第 42 章的方式把 `state` 序列化打印出来。观察租户 ID 是否出现在里面。
结论：**State 会被持久化；敏感上下文应该走 Runtime。**

---

## 48.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `KeyError: 'xxx'`（条件边） | 映射表漏键 | 补齐；用常量集合维护键 |
| `InvalidUpdateError: Expected dict, got [Send(...)]` | 从节点 return 了 `Send` | 改成从 `add_conditional_edges` 返回 |
| `Send` 子节点读不到字段 | 第二个参数传的不是子状态 | 只传这条分支要的字段 |
| 扇出后结果只留一条 | `summaries` 没加 reducer | `Annotated[list, operator.add]` |
| 并发打爆限流 | `Send` 一次发太多 | 分批（48.5） |
| `NameError`（条件边函数标注） | 类型注解用了函数内定义的 TypedDict | 提到模块级（第 47 章同理） |
| `Command` 报节点不存在 | `goto` 拼错 | 用常量维护节点名 |
| 模型看到租户 ID | 塞进了 State | 改用 `Runtime` context |
| `InjectedToolArg` 报 `Field required` | 没人补注入参数 | 用 `ToolNode` 或自己补 |
| `tools_condition` 一直不结束 | 模型一直返回 tool_calls | 加 `ToolCallLimitMiddleware`（第 45 章） |

---

## 48.9 章末自测

**Q1** 条件边的第二个参数和第三个参数各是什么？

<details>
<summary>提示</summary>
第二个是"读 state 返回字符串"的函数；第三个是"字符串 → 节点名"的映射表（可选，强烈建议）。
</details>

**Q2** `Send` 为什么只能从条件边返回？

<details>
<summary>提示</summary>
因为节点返回值的语义是"state 补丁"（一个 dict）。`Send` 是"调度指令"，属于边的语义。
</details>

**Q3** State / Runtime context / Store 三者分别适合放什么？

<details>
<summary>提示</summary>
State：业务数据（会被持久化、模型可见）
Runtime：当前请求上下文（不持久化、模型不可见）
Store：跨会话长期记忆（持久化、模型不可见）
</details>

**Q4** 手搭 Agent 图需要哪几个元素？

<details>
<summary>提示</summary>
model 节点、tools 节点（`ToolNode`）、START→model、model→[条件→tools/END]、tools→model。
</details>

**加分题**

> 同事说："`Send` 真香，我把 500 段文档一次全扇出去，10 秒就处理完了。"

参考思路：**先问三个问题**：
① 每段是不是都调了模型？如果是，500 个并发请求会不会触发限流？
② 如果中途 3 段失败，其他 497 段的结果还有效吗（要不要整批重跑）？
③ 内存里同时存在 500 份子状态，你的容器扛得住吗？
**扇出的收益是"延迟"，成本是"并发压力 + 失败恢复复杂度"。** 分批是默认答案。

---

## 48.10 可选补课：`InjectedStore` 与跨会话记忆

> ⚠️ **这一节可以先跳过。** 等你需要"用户偏好跨会话保留"时再看。

```python
from langgraph.store.memory import InMemoryStore
from langgraph.prebuilt import InjectedStore

@tool
def save_pref(pref: str, store: Annotated[Any, InjectedStore()]) -> str:
    """保存用户偏好。"""
    store.put(("user", "u1"), "pref", {"value": pref})
    return "已保存"
```

| 概念 | 说明 |
|---|---|
| `store.put(namespace, key, value)` | 写入，`namespace` 是元组（像"user/u1"这样的路径） |
| `store.get(namespace, key)` | 读取 |
| `store.search(namespace, query=...)` | 语义检索（如果配置了 embedding） |

**和 checkpointer 的区别**：

| | checkpointer | store |
|---|---|---|
| 存什么 | 一次会话的**完整状态** | 长期事实（偏好、画像） |
| 按什么分 | `thread_id` | 自定义 namespace |
| 生命周期 | 会话 | 永久（除非删） |

这两者是**互补**的：checkpointer 管"这次聊了什么"，store 管"这个人是什么样"。第 27 章讲过这个分层。

---

## 48.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 条件边 + 循环 | `code/framework/lg/ch48/step1_nodes_edges.py` | 第 49 章 Supervisor |
| `Send` / `Command` / `Runtime` | `code/framework/lg/ch48/step2_send_command_runtime.py` | 第 49 章多 Agent、第 36 章判据 |
| `ToolNode` 手搭 Agent | `code/framework/lg/ch48/step3_tool_node.py` | 第 54 章 Harness 装配 |

**这一节建立的"可复用资产"**：`fan_out` + reducer 的 map-reduce 形态，在第 49 章会复用到多 Agent 的并行分支上。

---

## 48.12 ✅ 验收

跑完三个脚本，检查五件事：

**① 你能说出映射表漏键的后果**

不看笔记，说出"删掉 `logistics` 那一行后，输入'物流呢'会发生什么"。

**② 你能写出 `Send` 扇出的三行核心代码**

`def fan_out(state): return [Send(target, {...}) for ...]` + `add_conditional_edges`。

**③ 你能说出 State 和 Runtime 的边界**

用一个例子说明"为什么租户 ID 不能放 State"。

**④ 你能画出 `ToolNode` 版的 Agent 图**

四个节点、四条边。

**⑤ 一个数字**

`step2` ① 的输出：4 个块 → 4 条摘要。

**现在算一个数**：如果每段处理需要调一次模型（¥0.002）、耗时 1.2 秒，
串行 vs 并行（4 并发）两种方式的总耗时与成本各是多少？

<details>
<summary>答案</summary>

成本：**一样**，都是 `4 × ¥0.002 = ¥0.008`（扇出不省钱，省时间）
耗时：串行 `4 × 1.2 = 4.8s`；并行（4 并发）`1.2s`

**这就是"并行"的准确定义**：**省钱要靠模型选择（第 34 章），省时间才靠并行。**
很多人以为并行能省钱，这是误解。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 49 章 流式、持久化、HITL、时间回溯、子图与多 Agent。
前面两张图都"一次跑完"。下一章让它**边跑边说**（流式）、**能停下来等人**（HITL）、
**能回到两步前重跑**（时间回溯），以及**把图拆成子图复用**。

> 📎 参考：本章对应基础教程第 24 章《API：节点、边与进阶》的知识点。
> 本书额外补了两个**基础教程没有的坑**：`Send` 只能从条件边返回、以及 `Runtime` 与 State 的边界。
