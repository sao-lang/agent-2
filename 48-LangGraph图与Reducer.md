# 第 48 章 LangGraph（一）：图、State 与 Reducer

> **这一章你会遇到什么坏事**
> 你把 `create_agent` 内部那张图拆开，想自己改一改。第一步就卡住：`StateGraph(dict)` 直接报错。
> 好不容易换成 `TypedDict` 跑起来了，你加了两条并行分支——**其中一条的数据不见了**，而且**没有任何报错**。
> 你盯着代码看了一小时，以为是模型的问题。
>
> 更糟的是——**这种"静默丢数据"在测试里几乎发现不了**，因为测试通常只验证"最终答案对不对"，而最终答案可能碰巧是对的。

> **学完你能做到**
> 1. 用 30 行搭一张能跑的图，并说清"节点之间到底传什么"（47.3）
> 2. 说清 `StateGraph(dict)` 为什么失败（47.4）
> 3. **亲手复现一次"并行写入冲突"，再用 reducer 修好它**（47.4）
> 4. 写三种自定义 reducer：拼接、去重、取最大（47.5）
> 5. 用 `stream_mode="updates"` 看见图是怎么一轮一轮推进的（47.6）

---

## 48.0 先说明白七个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **State（状态）** | 整张图共享的一块"白板"，所有节点都往上写 | 全章 |
| **节点（Node）** | 一个函数：读 State，返回"我要改哪几个字段" | 47.3 |
| **边（Edge）** | 节点之间的连接，决定"下一个跑谁" | 47.3 |
| **Schema** | State 的"表结构"，用 `TypedDict` 等声明每个字段的类型 | 47.4 |
| **Reducer** | 当**多个节点在同一轮写同一个字段**时，用哪个函数把值合并起来 | 47.4 |
| **`Annotated`** | Python 的类型注解扩展，用来给字段"挂一个 reducer" | 47.4 |
| **Superstep（超级步）** | 一轮执行：这一轮里能同时跑几个节点，由边决定 | 47.6 |

> 还有两个后面才出现：
> - **`compile()`**：把"图纸"（StateGraph）变成"能跑的引擎"（Pregel）
> - **`Pregel`**：LangGraph 的执行引擎名字，你不用直接用，但报错里会出现

---

## 48.1 先看一个具体的坏事：并行分支丢了一半数据

真实场景：一封用户投诉要同时做两件事——**抽关键词** 和 **判断情绪**。

你画了两条并行分支 `START → a` 和 `START → b`，两个节点都往 `items` 里写东西。跑一下：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lg\ch47\step1_state_reducer.py
```

真实输出（段 ③）：

```
③ 不加 reducer：并行分支的写入会冲突
  → InvalidUpdateError: At key 'items': Can receive only one value per step. Use an Annotated key to handle multiple values.
    原文：Can receive only one value per step. Use an Annotated key ...
```

**这次算你走运——它报错了。** 但下面这句才是重点（同一段的输出）：

```
  别高兴太早：报错只是 1.x 的**并行**场景。
  真正危险的是**顺序执行**时的覆盖 —— 它不报错，只是安静地少了一半数据。
```

而等你**将来**把两条顺序分支改成并行（一个非常常见的重构），就会踩到上面那个错。

| 你以为 | 实际 |
|---|---|
| 两个节点写同一个字段 → 自动合并 | 默认是"后写覆盖" |
| 覆盖会报错 | 顺序执行时**不报错** |
| 报错会告诉我为什么 | 只有并行、且值冲突时才报 |

**结论：你不是"代码写错了"，你是"没告诉框架怎么合并"。**

---

## 48.2 为什么"用一个 dict 传状态就行"不够

你可能会想：节点之间传个 dict，谁改了什么就改，不就行了？

这正是 `StateGraph(dict)` 想做的事。我们试一下：

真实输出（段 ②）：

```
② 必须踩的坑：StateGraph(dict) 直接失败
  → 必须是带类型注解的 schema（TypedDict / dataclass / Pydantic / 或它们组成的 dict）
```

**为什么框架强制要 schema？** 因为要回答三个它无法自己回答的问题：

| 问题 | 没有 schema 时 | 有 schema 时 |
|---|---|---|
| 这个字段是什么类型？ | 不知道 | `int` / `list[str]` |
| 多个节点同时写，怎么合并？ | 不知道 | 你自己声明的 reducer |
| 输入缺字段怎么办？ | 静默 `KeyError` | 校验时报错（用 Pydantic 时） |

**一句话：schema 不是"给 IDE 看的注解"，是"给运行时看的合并规则"。**

> 💥 **失败实验 1：把 `Annotated` 删掉，看看顺序执行会不会报错**
> 打开 `step1_state_reducer.py`，把 ④ 的 `items: Annotated[list[str], operator.add]` 改成 `items: list[str]`。
> 重跑。观察：**并行分支那一段报 `InvalidUpdateError`**（和 ③ 一样）。
>
> 现在把两条分支改成 `START → a → b → END`（顺序），再跑。
> **它不报错，结果也"看起来对"**——因为每次只有一个节点写。
>
> 结论：**"现在不报错"不代表"将来不报错"。** 判断标准不是"当前会不会并行"，而是**这个字段是不是"累加事实"**。

---

## 48.3 图到底是什么（10 行代码看懂）

### 一句话

> **一张图 = 一块白板（State）+ 几个改白板的人（Node）+ 谁先谁后（Edge）。**

### 最小例子

💻 `python code/framework/lg/ch48/step1_state_reducer.py`

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict):
    n: int
    log: str

def inc(state: S) -> dict:
    return {"n": state["n"] + 1, "log": state["log"] + " inc"}

def double(state: S) -> dict:
    return {"n": state["n"] * 2, "log": state["log"] + " double"}

g = StateGraph(S)
g.add_node("inc", inc)
g.add_node("double", double)
g.add_edge(START, "inc")
g.add_edge("inc", "double")
g.add_edge("double", END)
app = g.compile()

print(app.invoke({"n": 3, "log": ""}))
```

真实输出（段 ①）：

```
  输入 n=3 → {'n': 8, 'log': ' inc double'}
  节点返回的 dict 会**合并**进 state，没返回的键保持原值
```

**就算清楚了**：`3 → inc → 4 → double → 8`。两个节点各返回一个 dict，框架把它们**合并**进白板。

### 关键规则：节点返回的是"补丁"，不是"整个状态"

| 你写 | 框架做 |
|---|---|
| `return {"n": 4}` | 只把 `n` 改成 4，`log` 不动 |
| `return state` | 把整个状态写回（不推荐：容易覆盖别人刚写的值） |
| `return {}` | 什么都不改 |

**这条规则很重要**：因为它直接决定了"要不要 reducer"。**补丁是"我只改这几个字段"，不是"这是我的完整版本"。**

### ✏️ 停下来想一想

上面 `inc` 返回 `{"n": state["n"] + 1, "log": ...}`——它**先读了 state 再写**。

那如果 `inc` 和 `double` 是**并行**的（都从 START 出发），它们读到的 `state["n"]` 是同一个值吗？
它们写回 `n` 的时候，谁赢？

（答案：读到的是同一份"上一轮结束时的 n"；写回时如果没有 reducer，就会冲突——这正是 47.1 的问题。）

---

## 48.4 从"能跑"到"不丢数据"（阶梯代码 step1 / step2）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_state_reducer.py` | State / 节点 / reducer / 自定义合并 | — |
| step2 | `step2_how_graph_runs.py` | Superstep（一轮跑几个）+ 重试策略 | step1 不知道为什么"先算哪个" |

### step1：reducer 的三种写法

真实输出（段 ④⑤）：

```
④ 加 reducer：Annotated[list, operator.add] 拼起来
  并行写入结果 = ['来自 A', '来自 B']
  实际条数 = 2
  → operator.add 对 list 是「拼接」；写入顺序不保证，别依赖顺序

⑤ 自定义 reducer：两种常见需求
  去重 reducer → tags = ['urgent', 'refund', 'vip']（refund 只出现一次）
  取大 reducer → score = 90（60 和 90 里取大）
```

三种 reducer，覆盖 90% 的场景：

| 需求 | 写法 | 用途 |
|---|---|---|
| 累加（追加列表） | `Annotated[list, operator.add]` | 消息、日志、命中列表 |
| 去重 | `Annotated[list, keep_unique]`（自己写） | 标签、来源 |
| 取极值 | `Annotated[int, take_max]`（自己写） | 最高分、最严重等级 |
| 覆盖（默认） | `字段: type`（不加 `Annotated`） | "当前状态"类字段 |

真实项目里最常用的其实是**第一种**——LangGraph 自带的 `add_messages` 就是它的加强版（会按 `id` 去重、支持删除）。

### step2：图是怎么一轮一轮推进的

痛点一句话：**改了条边，行为全变了，说不清原因。**

💻 `python code/framework/lg/ch48/step2_how_graph_runs.py`

真实输出（段 ①）：

```
  边：START→a, a→b, a→c, [b,c]→d, d→END
  逐轮观察（stream_mode='updates' 逐 chunk 打印）：
    chunk 1: ['a']
    chunk 2: ['b']
    chunk 3: ['c']
    chunk 4: ['d']
```

**注意 `[b, c]` 这条边**：它是一个**列表边**，意思是"b 和 c 都完成之后，才走 d"。

这一级解决了什么：你现在能**预期**执行顺序，而不是靠猜。

---

## 48.5 核心实现（逐行解释）

这一节把"reducer 为什么必须定义在模块级"这个真实的坑讲清楚——**这是我们写这一章时踩到的**。

```python
# ❌ 第一版：把 reducer 写在 main() 里
def main():
    def keep_unique(left, right):        # ①
        ...

    class S4(TypedDict):
        tags: Annotated[list[str], keep_unique]   # ②
    ...
```

跑起来直接崩：

```
NameError: name 'keep_unique' is not defined
```

| 行 | 问题 | 为什么 |
|---|---|---|
| ① | 函数定义在 `main()` 内部（局部作用域） | 只能被 `main` 里的代码看到 |
| ② | `TypedDict` 的注解是**字符串形式**保存的（受 `from __future__ import annotations` 影响） | 运行时 LangGraph 调 `get_type_hints()` **重新求值**，它在**模块全局作用域**里找 `keep_unique`，找不到 |

**修法：把 reducer 提到模块级。**

```python
# ✅ 正确：模块级
def keep_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for x in right:
        if x not in merged:
            merged.append(x)
    return merged

class S4(TypedDict):
    tags: Annotated[list[str], keep_unique]
```

**这条坑的普适启示**：**凡是"类型注解里出现名字"的地方（reducer、自定义类型、泛型参数），那个名字必须是模块级可见的。**
同类问题在第 49 章的**条件边函数**上也会遇到（我们同样踩了一次）：给 `router` 标注一个定义在函数内的 `TypedDict`，一样 `NameError`。

### 三个设计取舍

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 字段给不给 reducer | **看"是不是累加事实"** | 给"当前状态"字段加 reducer，会得到一串历史值（例如 `status` 变成 `['draft','approved']`） |
| 用 `operator.add` vs 自己写 | **简单场景用内置** | 自己写容易忘掉不可变（要返回新 list，不要原地 append） |
| reducer 里做去重 | **可以，但注意顺序** | 并行写入顺序不保证，去重后顺序也可能变 |

### ⚠️ 一个必须知道的坑：`Annotated` 的 reducer 会作用于**所有**写入

如果你给 `messages` 加了 `operator.add`，然后某个节点想**清空**历史（返回 `{"messages": []}`），
**它不会清空**——`[] + 旧历史 = 旧历史`。

清理上下文要用专门的机制：`RemoveMessage` 或 `ContextEditingMiddleware`（第 46 章），**不是"返回空列表"**。

> 💥 **失败实验 2：给"当前状态"字段加 reducer**
> 在 `step1` ① 的 `S1` 里，把 `n: int` 改成 `n: Annotated[int, operator.add]`。
> 重跑。观察输出从 `8` 变成了什么。
> **结论：reducer 会让"赋值"变成"累加"。** 所以 reducer 不是"加了更安全"，是**"换了一种语义"**。

---

## 48.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lg/ch48/step2_how_graph_runs.py`

### 问题 ①：入口点怎么写？

真实输出（段 ③）：

```
  写法 1 add_edge(START, 'x')  → {'log': ['x']}
  写法 2 set_entry_point('x') → {'log': ['x']}
  写法 3 add_sequence        → {'log': ['a', 'b']}
     注意：add_sequence 不建入口/出口边，START 和 END 仍要自己连
```

**结论**：推荐**写法 1**——边的方向一眼看得懂。`add_sequence` 只帮你连"中间那段"，不连入口和出口。

### 问题 ②：节点失败了怎么办？

真实输出（段 ④）：

```
④ RetryPolicy：节点失败自动重试（不用手写 try/except 循环）
  结果 = ['第 3 次成功']，共尝试 3 次
  不加重试 → 直接抛出 ConnectionError: 第 1 次连接失败
  → retry_on 写**异常类**，不是字符串；只重试你声明的那几类
```

**结论**：`retry_policy=RetryPolicy(max_attempts=3, retry_on=ConnectionError)`。
**`retry_on` 必填异常类**——写字符串会报 `'str' object has no attribute 'retry_on'`（我们踩过）。

### 问题 ③：不 compile 会怎样？

真实输出（段 ⑤）：

```
  StateGraph 实例有 invoke 吗？False
  compile() 之后有吗？        True
  → StateGraph 是「图纸」，compile() 才生成可执行的 Pregel 引擎
```

**结论**：`StateGraph` 是**图纸**，`compile()` 才是**引擎**。这就像 `Class` 和 `instance`。

### 🎯 到这里，你已经掌握了"画一张图"

| 能力 | 在哪一节 |
|---|---|
| State / 节点 / 边 | 47.3 |
| reducer 的四种语义 | 47.4 |
| 自定义 reducer + 模块级坑 | 47.5 |
| Superstep 与执行顺序 | 47.4 step2 |
| RetryPolicy | 47.6 |

**剩下的都是"让图更复杂"：条件边、Send、Command、持久化（第 48、49 章）。**

---

## 48.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数，观察变化

在 `step1` ④ 里，把 `operator.add` 改成 `lambda a, b: a + b[-1:]`（只保留最新一条）。
重跑。**验收标准**：你能说出"两个分支的结果变成了几条，为什么"。

### 练习 2（20 分钟）：接到你自己的项目上

把你项目里**任意一处**"用一个 dict 在步骤间传数据"的代码改成 LangGraph。

**最低要求清单**：
- [ ] State 用 `TypedDict` 声明，每个字段有类型
- [ ] 凡是"累加"的字段（消息、日志、命中列表）都加 reducer
- [ ] reducer 函数定义在模块级
- [ ] 用 `stream_mode="updates"` 打印一次，确认执行顺序符合预期

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：并行写同一个"无 reducer"字段。**

在 `step1` ③ 的 `S2` 里，把两个节点都改成写 `n`（而不是 `items`）。重跑。
观察 `InvalidUpdateError`。结论：**这个错误只在你真的并行时才出现——所以顺序测试是"假绿"。**

**实验 B：把 reducer 写死成"总是覆盖"。**

```python
def last_wins(left, right):
    return right
```

重跑 ④。观察结果只剩一条。结论：**这正是"没写 reducer"的默认行为。** 你等于亲手验证了默认行为是什么。

**实验 C：在 reducer 里原地修改。**

```python
def bad_add(left, right):
    left.extend(right)
    return left
```

重跑。观察**多跑几轮后结果是否重复**。结论：原地修改可能让同一批数据被合并两次——**reducer 必须返回新对象**。

---

## 48.8 补充：两种 API 与「预置 Agent 已废弃」

前面讲的全是**图式 API**（`StateGraph` + `add_node`/`add_edge`）。
LangGraph 还有第二种写法，而且预置 Agent 的入口在 1.x 已经变了。

💻 运行：`python code/framework/lg/ch48/step3_functional_and_prebuilt.py`

### 48.8.1 函数式 API：`@entrypoint` + `@task`

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint, task

@task
def double(x: int) -> int:
    return x * 2

@task
def add(a: int, b: int) -> int:
    return a + b

@entrypoint(checkpointer=InMemorySaver())
def wf(n: int) -> int:
    a = double(n).result()      # ← .result() 才是"取值"，不写拿到的是 future
    b = double(a).result()
    return add(a, b).result()

print(wf.invoke(3, {"configurable": {"thread_id": "f1"}}))   # 18
```

真实输出：

```
  wf.invoke(3) = 18
  执行过的 task = [('double', 3), ('double', 6)]
  同一 thread 再 invoke(3) = 18
  执行过的 task = [('double', 3), ('double', 6)]
```

> 💥 **两个必须知道的事实**
>
> 1. **`.result()` 是阻塞式取结果。** 写 `double(n)` 得到的是一个 future，
>    不调用 `.result()` 你拿不到值。
> 2. **同一 `thread_id` 再 invoke 不会复用上次的结果** —— 上面第二次调用
>    task 又跑了一遍。想复用要显式配 `cache_policy`（第 50 章补课）。

**函数式 vs 图式：**

| 维度 | 函数式 API | 图式 API |
|---|---|---|
| 怎么写 | `@entrypoint` + `@task` | `StateGraph` + `add_node`/`add_edge` |
| 适合 | **线性、无环、无分支**的流程 | 有分支/循环/并行/中断 |
| 可视化 | 不能画图 | `get_graph().draw_mermaid()` |
| 中断 `interrupt` | 可用但很别扭 | 原生支持 |
| 什么时候选它 | 脚本式数据处理、ETL 式流水 | Agent 这类有循环和分支的 |

> **一句话：写 Agent 用图式，写流水线用函数式。**
> 图式 API 能表达函数式能表达的一切，反之不成立。

### 48.8.2 `create_react_agent` 已废弃

在 `langgraph 1.2.16` 上，**导入**它就会触发（不用调用）：

```
LangGraphDeprecatedSinceV10: create_react_agent has been moved to
`langchain.agents`. Please update your import to
`from langchain.agents import create_agent`.
Deprecated in LangGraph V1.0 to be removed in V2.0.
```

**迁移路径：**

| 旧写法 | 新写法 |
|---|---|
| `from langgraph.prebuilt import create_react_agent` | `from langchain.agents import create_agent` |
| `create_react_agent(model, tools)` | `create_agent(model, tools=tools)` |
| `model` 需要自己 `bind_tools` | `create_agent` 内部处理 |

> **这是本书反复强调的一件事的实例：0.x 的写法到 1.x 会变。**
> 第 46 章那张 0.x→1.x 对照表就是这个原因。

### 48.8.3 离线跑通一次完整 ReAct 循环

```python
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

@tool
def get_order(order_id: str) -> str:
    """按订单号查询订单。"""
    return f"order {order_id}: 399元"

class FakeToolModel(GenericFakeChatModel):
    # GenericFakeChatModel 没实现 bind_tools，这里补一个空实现
    def bind_tools(self, tools, **kwargs):
        return self

model = FakeToolModel(messages=iter([
    AIMessage(content="", tool_calls=[
        {"name": "get_order", "args": {"order_id": "A8821"}, "id": "1"},
    ]),
    AIMessage(content="已查到：399 元"),
]))

agent = create_agent(model, tools=[get_order])
out = agent.invoke({"messages": [("user", "A8821 多少钱")]})
```

真实输出：

```
    HumanMessage   | A8821 多少钱                    | tool_calls=None
    AIMessage      |                                | tool_calls=[{'name': 'get_order', ...}]
    ToolMessage    | order A8821: 399元              | tool_calls=None
    AIMessage      | 已查到：399 元                    | tool_calls=[]
```

**这就是第 17 章 ReAct 的标准形状：**

```
HumanMessage -> AIMessage(带 tool_calls) -> ToolMessage -> AIMessage(最终答案)
```

> 💥 **一个必须知道的技术坑**
>
> `GenericFakeChatModel` **没有实现 `bind_tools`**。
> 直接用 `create_react_agent` / `create_agent` 会抛 `NotImplementedError`。
>
> 解法：派生一个子类，补一个什么都不做的 `bind_tools`（如上）。

> ⚠️ **一个评测上的提醒**
>
> 这里的答案是「我写死的剧本」决定的，
> 所以这种离线测试**只能验证「接线通不通」**。
>
> 「模型会不会选对工具、参数对不对」—— 必须用真实模型 + 评测集（**第 61 章**）。

---

## 48.9 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `StateGraph(dict)` 报错 | 必须用带类型注解的 schema | `TypedDict` / `dataclass` / Pydantic |
| `InvalidUpdateError: Can receive only one value per step` | 并行分支写同一字段，没 reducer | `Annotated[list, operator.add]` |
| 数据"少了一半"但不报错 | 顺序执行时的默认覆盖 | 给累加字段加 reducer |
| `NameError: name 'xxx' is not defined`（定义 reducer 时） | reducer 定义在函数内部 | 提到模块级 |
| `status` 变成 `['draft', 'approved']` | 给"当前状态"字段加了累加 reducer | 去掉 reducer |
| 想清空 `messages` 却清不掉 | `operator.add` 里 `[] + 旧 = 旧` | 用 `RemoveMessage` 或 ContextEditing |
| `'str' object has no attribute 'retry_on'` | `retry_policy` 传了 dict | 用 `RetryPolicy(...)` 对象 |
| `Graph must have an entrypoint` | 没连 `START` | `add_edge(START, "第一个节点")` |
| `StateGraph` 没有 `invoke` | 忘了 `compile()` | `app = g.compile()` |
| 同一 superstep 的节点互相干扰 | 节点里有共享可变全局状态 | 改成纯函数，状态只走 State |

---

## 48.10 章末自测

**Q1** 节点返回的 dict 是"完整状态"还是"补丁"？

<details>
<summary>提示</summary>
补丁。没返回的键保持不变。
所以 `return state` 虽然能跑，但容易覆盖别人刚写的东西。
</details>

**Q2** 什么时候必须给字段加 reducer？

<details>
<summary>提示</summary>
这个字段可能被**多个节点在同一轮**写，或者它语义上是"累加事实"（消息、日志、命中列表）。
判断依据不是"现在会不会并行"。
</details>

**Q3** 为什么 reducer 必须定义在模块级？

<details>
<summary>提示</summary>
`TypedDict` 的类型注解在运行时被 `get_type_hints()` 重新求值，
它在模块全局作用域找名字，看不到函数内部的局部函数。
</details>

**Q4** `add_sequence` 和 `add_edge(START, ...)` 的区别？

<details>
<summary>提示</summary>
`add_sequence` 只帮你连"节点之间"的边，**不连 START/END**。所以入口还得自己写。
</details>

**加分题**

> 同事说："我用顺序执行，测试全绿，为什么上线后偶发数据丢失？"

参考思路：**因为"顺序"可能不是你以为的顺序。**
LangGraph 里如果两条分支从同一个节点出发，它们属于**同一 superstep**，会并发调度。
即使你写的是"先 a 后 b"，只要 a 和 b 之间没有边，它们就是并行的。
**判定方法**：`stream_mode="updates"` 打印一次，看它们是不是在同一个 step 里。

---

## 48.11 可选补课：`add_messages` 与消息去重

> ⚠️ **这一节可以先跳过。** 等你发现"消息越长越多、出现重复"时再看。

`langgraph.graph.message.add_messages` 不是简单的 `operator.add`，它做了三件事：

| 行为 | 说明 |
|---|---|
| **按 `id` 去重** | 新消息的 id 和已有消息相同 → **替换**而不是追加 |
| **支持删除** | 传入 `RemoveMessage(id="...")` → 从列表里删掉 |
| **保持顺序** | 按写入顺序合并（同一轮内不保证） |

```python
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]
```

**这就是为什么 Agent 的 State 永远用 `add_messages` 而不是 `operator.add`**：
工具结果要能"更新"一条已有消息（比如流式增量），而不是每次都新增一条。

---

## 48.12 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| State + 四种 reducer | `code/framework/lg/ch48/step1_state_reducer.py` | 第 48/49 章所有图 |
| Superstep + RetryPolicy | `code/framework/lg/ch48/step2_how_graph_runs.py` | 第 50 章流式、第 35 章延迟 |

**这一节建立的判断力**：看到任何一个 State 字段，能立刻回答"它要不要 reducer"——这是后面所有图设计的前置技能。

---

## 48.13 ✅ 验收

跑完两个脚本，检查五件事：

**① 你能说出 `3 → 8` 是怎么来的**

不看代码，写出 `inc` 和 `double` 各做了什么。

**② 你能复现 `InvalidUpdateError`**

不看笔记，说出它的触发条件（并行 + 同字段 + 无 reducer）。

**③ 你能解释"为什么顺序测试是假绿"**

说出"顺序执行为什么不报错"。

**④ 你能写出三种 reducer**

拼接、去重、取最大，各 3 行。

**⑤ 一个数字**

`step2` ① 的输出里，`a→b` 和 `a→c` 是并行分支。

**现在算一个数**：如果 b 和 c 各需要 1 秒，`a` 和 `d` 各 0.1 秒，
那"并行"和"串行"两种画法，总耗时各是多少？

<details>
<summary>答案</summary>

并行（`a → [b,c] → d`）：`0.1 + max(1,1) + 0.1 = 1.2s`
串行（`a → b → c → d`）：`0.1 + 1 + 1 + 0.1 = 2.2s`

**但注意**：并行省时间的前提是"两条分支互不依赖"。
如果 c 需要 b 的结果，强行并行的结果就是**用错数据**——这比慢 1 秒严重得多。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 49 章 节点、边、Send/Command 与 Runtime。
上一章的图只有"一条直路"。下一章给它加上**条件边**（按情况走）、**Send**（一份输入变 N 路并行）、
**Command**（跳转和改状态一步完成），以及**Runtime**（怎么把"当前租户"传进节点而不污染状态）。

> 📎 参考：本章对应基础教程第 22 章《LangGraph 概述与快速入门》、第 23 章《API：图与状态》的知识点。
> 本书增加了一段基础教程没有的内容：**"不加 reducer 在顺序执行下不报错"**——这是最容易在真实项目里漏掉的前提。
