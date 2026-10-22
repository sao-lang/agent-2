# 第 46 章 LangChain（四）：`create_agent` 与中间件体系

> **这一章你会遇到什么坏事**
> 你搜到一份"LangChain Agent 教程"，敲了 40 行 `AgentExecutor` + `agent_scratchpad`，`ModuleNotFoundError`。
> 你又搜到一份 1.x 的，一行 `create_agent(...)` 就跑起来了——**于是你以为 Agent 就是"一行代码"**。
> 然后你发现：它死循环烧钱、调用超时不重试、上下文越跑越长、危险的删除工具说调就调。
>
> 更糟的是——**这些毛病一个都不会报错。** 它们只是让账单变高、答案变差，直到某天出事。

> **学完你能做到**
> 1. 用 `create_agent` 搭一个能跑的 Agent，并说清它的 12 个参数各管什么（45.3）
> 2. 说清"没有 checkpointer 就没有记忆"这句话到底在说什么（45.4）
> 3. 用 3 个内置中间件解决限流、工具报错、待办清单（45.5）
> 4. 写一个自定义中间件，知道 6 个钩子分别插在哪（45.6）
> 5. 逐条对照 0.x 写法，说清为什么不能照抄（45.7）

---

## 46.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **`create_agent`** | 一行创建一个 Agent 的函数，返回的其实是**一张编译好的状态图** | 45.3 起 |
| **中间件（Middleware）** | 在 Agent 循环的固定几个点上"插一脚"的类，像给流水线加检测站 | 45.5 |
| **钩子（Hook）** | 中间件能挂的 6 个位置：`before/after_agent`、`before/after_model`、`wrap_model/tool_call` | 45.6 |
| **`CompiledStateGraph`** | `create_agent` 的返回类型，就是 LangGraph 编译后的图 | 45.3 |
| **`thread_id`** | 给一段会话打的标签，记忆按它分区 | 45.4 |
| **checkpointer** | 存状态的组件（内存/SQLite/PG），记忆的真正载体 | 45.4 |
| **`AgentExecutor`** | 0.x 的 Agent 执行器，1.x **已不存在** | 45.7 |
| **`agent_scratchpad`** | 0.x 用来存"中间步骤"的隐式变量，1.x 由 `messages` 代替 | 45.7 |

> 还有三个后面才出现：
> - **`response_format`**：让 Agent 最终输出一个 Pydantic 对象（第 44 章的 schema 直接复用）
> - **`SummarizationMiddleware`**：上下文太长时自动摘要（第 24、26 章）
> - **`HumanInTheLoopMiddleware`**：危险动作前中断等审批（第 32 章、第 50 章）

---

## 46.1 先看一个具体的坏事：Agent 是个黑盒

真实场景：售后 Agent 要"查订单 → 判断能否退款 → 提交退款"。

你把工具塞进去，跑一下，看到最终答案是"已提交退款 99 元"。**然后呢？**

| 你想知道的 | 你能从返回值里看到的 |
|---|---|
| 它调了几次工具 | ❌ 只能自己数 |
| 每次调用花了多少 token | ❌ 返回值里没有汇总 |
| 它有没有跳过"查订单"直接退款 | ❌ 看不出来 |
| 它为什么没用另一个工具 | ❌ 看不出 |
| 中途失败过几次、重试没 | ❌ 看不到 |

先真的跑一次，把返回对象拆开看看：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lc\ch45\step1_create_agent.py
```

真实输出（段 ①⑤）：

```
① 最小 Agent：模型 + 工具 + 剧本
  返回类型 = CompiledStateGraph
  → 它不是一个「链」，而是一张编译好的状态图

  完整消息序列：
    1. HumanMessage '订单 A1201 坏了，我要退款'
    2. AIMessage    query_order{'order_id': 'A1201'}
    3. ToolMessage  'A1201: 已签收 12 天，在保修期内'
    4. AIMessage    apply_refund{'order_id': 'A1201', 'amount': 99}
    5. ToolMessage  '已为 A1201 提交退款 99.0 元，7 个工作日到账'
    6. AIMessage    '已为你提交退款 99 元，7 个工作日到账。'

⑤ 把 result 读干净：不要只看最后一条
  out['messages'][-1].content = '已为你提交退款 99 元，7 个工作日到账。'
  中间还发生了什么 = 2 次工具调用
```

**结论：Agent 不是黑盒，它把"每一步"都留在 `messages` 里。你只是没看。**

**但这也埋了一个坑**：`out["messages"]` 是**完整历史**，会随轮次线性增长。
如果把它整段塞进下一轮，你会得到第 54.6 节那条"上下文从 653 涨到 3,233"的曲线。

---

## 46.2 为什么"自己写个 while 循环"不够

你可能会想：Agent 不就是"调模型 → 有工具调用就执行 → 再调模型"的 while 循环吗？我手写 20 行不就完了？

第 49 章我们会真的手写一遍。先看手写版本会遇到什么：

| 手写要做的事 | 忘记会怎样 |
|---|---|
| `messages.append(reply)` | 模型看不到自己刚说过的话，无限重复同一个工具调用 |
| 配对 `tool_call_id` | 400 错误（工具结果必须对应某次调用） |
| 加**步数上限** | 死循环，账单爆炸（第 16 章） |
| 工具报错要 catch | 一个工具抖动，整条请求 500 |
| 记录每次调用的耗时/来源 | 出问题只能靠猜（第 38 章） |
| 上下文太长要摘要 | 撞上下文窗口，报 `context_length_exceeded` |
| 危险工具要拦截 | `delete_user` 说调就调（第 31、54 章） |

**所以我们要的不是"一个循环"，是"一个带七道保险的循环"。**

这个东西就是 `create_agent` + 中间件。

> 注意区分：**`create_agent` 提供"骨架"（循环 + 状态 + 图），中间件提供"保险"（限流/重试/摘要/审批）。**
> 骨架不替你思考，保险要你自己挂。

---

## 46.3 `create_agent` 到底是什么（10 行代码看懂）

### 一句话

> **`create_agent(model, tools)` = 一张图：`START → model →(有 tool_calls)→ tools → model →(没有)→ END`。**

### 最小例子

💻 `python code/framework/lc/ch46/step1_create_agent.py`

```python
from langchain.agents import create_agent
from langchain_core.tools import tool

@tool
def query_order(order_id: str) -> str:
    """按订单号查询订单状态。用户提供订单号时调用。"""
    return f"{order_id}: 已签收 12 天，在保修期内"

agent = create_agent(model, tools=[query_order])
out = agent.invoke({"messages": [HumanMessage("A1201 还能保吗")]})
```

**就这两行。** 它返回的不是一个"链"，而是一张图。真实输出（段 ②）：

```
② 这张图长什么样
  （draw_ascii 需要额外依赖：ImportError；改用节点/边列表）
  节点 = ['__start__', 'model', 'tools', '__end__']
  边   = [('__start__', 'model'), ('model', '__end__'), ('model', 'tools'), ('tools', 'model')]
  图的节点只有两类：
    model     → 调模型，判断要不要调工具
    tools     → 执行工具，把结果写回 messages
  条件边：model 有 tool_calls 就去 tools，没有就去 END
```

**四个节点、四条边。** 你在第 49 章会用 `StateGraph` + `ToolNode` 手搭出一模一样的图。

### 12 个参数，各管一件事

真实输出（段 ③）用的是下面这份完整签名（参数顺序与官方一致）：

```python
agent = create_agent(
    model,                                # str 或 BaseChatModel
    tools=[...],                          # list[BaseTool | Callable | dict]
    system_prompt="...",                  # 等价于一条 SystemMessage
    middleware=[...],                     # 中间件列表（45.5）
    response_format=Refund,               # 最终输出结构化（复用第 44 章 schema）
    state_schema=None,                    # 自定义 state（进阶）
    context_schema=None,                  # 运行时上下文类型（第 49 章 Runtime）
    checkpointer=InMemorySaver(),         # ★ 记忆的载体
    store=None,                           # 跨会话长期记忆（第 27 章）
    interrupt_before=None,                # 在某个节点前停下（HITL）
    interrupt_after=None,
    debug=False,
    name="refund_agent",
    cache=None,
)
```

| 参数 | 一句话 | 什么时候必须传 |
|---|---|---|
| `model` | 模型，字符串或对象 | 总是 |
| `tools` | 工具清单 | 有工具时 |
| `system_prompt` | 身份与硬约束 | 总是（哪怕一句） |
| `middleware` | 保险 | 生产必传 |
| `response_format` | 最终输出 schema | 需要结构化结果时 |
| `checkpointer` | 记忆 | **要多轮对话就必须** |
| `store` | 长期记忆 | 跨会话记事实时 |
| `interrupt_*` | 人为断点 | 需审批时（更推荐 `HumanInTheLoopMiddleware`） |
| `name` | 图的名字 | 多 Agent / trace 里区分时 |
| `cache` | 节点缓存 | 有昂贵且幂等的节点时 |
| `state_schema` / `context_schema` | 扩展 state / 传运行时上下文 | 进阶 |

### ✏️ 停下来想一想

上面那段代码里，`debug=False`。如果你把它改成 `True` 并且**不传 checkpointer**，会发生什么？

（提示：`debug` 只影响日志，不影响记忆。所以你会看到一堆详细日志，但第二轮对话**依然不记得第一轮**。这个组合最容易让人误判"我明明开了 debug，怎么还是没记忆"。）

---

## 46.4 从"能跑"到"能记住"（阶梯代码 step1 / step2 / step3）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_create_agent.py` | `create_agent` + 12 个参数 + checkpointer | — |
| step2 | `step2_middleware.py` | 中间件 + 6 个钩子 | step1 的 Agent 没有任何保险 |
| step3 | `step3_legacy_vs_modern.py` | 手写 AgentExecutor 循环 + 0.x 对照 | step2 会用，但说不清框架做了什么 |

### step1：记忆不是 Agent 的功能

真实输出（段 ④）：

```
④ 一个坑：没有 checkpointer，就没有记忆
  无 checkpointer → 返回 2 条消息（只剩本轮）
  有 checkpointer → 返回 4 条消息（含上一轮）
  → 记忆不是「Agent 的功能」，是「checkpointer 的功能」，靠 thread_id 分区
```

**这两行数字是全章最重要的对比。** 同一份代码，只差一个 `checkpointer=InMemorySaver()`。

```python
cfg = {"configurable": {"thread_id": "u1"}}
agent.with_mem.invoke({"messages": [HumanMessage("我叫张三")]}, cfg)
agent.with_mem.invoke({"messages": [HumanMessage("我叫什么？")]}, cfg)
```

**`thread_id` 是分区的键**：

| `thread_id` | 效果 |
|---|---|
| 同一个 | 同一个会话，历史累加 |
| 每用户一个（`u:{user_id}`） | 用户之间隔离 |
| 每工单一个（`t:{ticket_id}`） | 一个工单一个上下文 |
| 每次请求随机 | **等于没有记忆**（很常见的 bug） |

### step2：中间件

痛点一句话：**你想加"最多调 5 次模型""工具报错别崩""给我个待办清单"——总不能改 `create_agent` 源码。**

💻 `python code/framework/lc/ch46/step2_middleware.py`

真实输出（段 ①，本机真实可导入的 12 个）：

```
  ✓ ModelCallLimitMiddleware      限制模型调用次数（防死循环）
  ✓ ToolCallLimitMiddleware       限制工具调用次数
  ✓ ModelRetryMiddleware          模型调用失败重试
  ✓ ToolRetryMiddleware           工具调用失败重试
  ✓ ModelFallbackMiddleware       主模型失败换备胎
  ✓ ToolErrorMiddleware           工具异常转成给模型看的文本
  ✓ SummarizationMiddleware       上下文太长时自动摘要
  ✓ HumanInTheLoopMiddleware      危险动作前中断，等人工审批
  ✓ TodoListMiddleware            给 Agent 一个待办清单
  ✓ PIIMiddleware                 检测/脱敏个人信息
  ✓ LLMToolSelectorMiddleware     工具太多时先用小模型挑
  ✓ ContextEditingMiddleware      清理/编辑历史上下文
```

**这 12 个，正好对上本书前面 12 章讲的能力**：

| 中间件 | 对应本书第几章 |
|---|---|
| `ModelCallLimit` / `ToolCallLimit` | 第 16 章（循环失控） |
| `ModelRetry` / `ToolRetry` / `ModelFallback` | 第 35 章（延迟工程）+ 附录 F |
| `ToolError` | 第 12 章（工具调用）+ 44.3 |
| `Summarization` | 第 24、26 章（上下文 / 短期记忆） |
| `HumanInTheLoop` | 第 32 章（HITL） |
| `TodoList` | 第 19 章（Plan-and-Execute） |
| `PII` | 第 31 章（护栏） |
| `LLMToolSelector` | 第 12 章（工具越多越选不对） |
| `ContextEditing` | 第 24 章（上下文工程） |

**所以中间件不是"新知识"，是"你已经学过的东西的落地形态"。**

### step3：和 0.x 正面对照

💻 `python code/framework/lc/ch46/step3_legacy_vs_modern.py`

真实输出（段 ②）：

```
  第 1 步：调用 query_order({'order_id': 'A1201'}) → A1201: 已签收 12 天，在保修期内
  第 2 步：模型给出最终答案 → '在保修期内，可以免费维修。'
  → 这 15 行没有一个 import 来自框架。你现在能指出 create_agent 替你做了什么：
    · messages 的管理（自动追加 / 自动配对 tool_call_id）
    · 循环上限（不设置会死循环，见第 16 章）
    · 状态持久化（checkpointer）与中断（interrupt）
    · 中间件（限流/重试/摘要/审批/脱敏）
    · 流式（stream_mode）
```

**这一级的价值**：你看过"裸循环"，以后框架报错时，你知道去内层找什么。

---

## 46.5 核心实现（逐行解释）

这一节把自定义中间件的 6 个钩子拆开——**这是全章最抽象、也最有用的部分**。

```python
class Audit(AgentMiddleware):
    def before_agent(self, state, runtime):        # ①
        events.append("before_agent")
        return None                                # ②

    def before_model(self, state, runtime):        # ③
        events.append(f"before_model(messages={len(state['messages'])})")
        return None

    def after_model(self, state, runtime):         # ④
        last = state["messages"][-1]
        calls = len(getattr(last, "tool_calls", []) or [])
        events.append(f"after_model(tool_calls={calls})")
        return None

    def after_agent(self, state, runtime):         # ⑤
        events.append("after_agent")
        return None
```

真实输出（段 ③）：

```
  钩子触发顺序：
    before_agent
    before_model(messages=1)
    after_model(tool_calls=1)
    before_model(messages=3)
    after_model(tool_calls=0)
    after_agent
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | 整个 Agent 开始前跑**一次** | 想在开始前初始化资源（连接池）就无处可放 |
| ② | 返回 `None` = 不改状态；返回 dict = 合并进 state | 返回了不该返回的东西，会污染 state |
| ③ | 每次调模型前跑 | 想做"发模型前修剪上下文"就靠它 |
| ④ | 每次调模型后跑 | 想做"数工具调用次数 / 记成本"就靠它 |
| ⑤ | 整个 Agent 结束后跑**一次** | 想做"收尾落盘/上报"就靠它 |

**六个钩子的完整位置**（`step2` ④ 打印的图）：

```
    before_agent ──┐                       ┌── after_agent
                   ├─► before_model ─► model ─► after_model ─┐
                   │                                          │
                   └────────────── 循环 ◄── tools ◄───────────┘

    wrap_model_call(request, handler)   包住「这一次模型调用」（改消息/换模型/计费）
    wrap_tool_call(request, handler)    包住「这一次工具调用」（审批/改参/重试）
```

**`wrap_*` 和 `before_*` 的区别**：前者能**包住**一次调用（前后都能插手，能改输入也能改输出、能拦住不调用），后者只能在点上"加一段"。

### 三个设计取舍

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 用内置中间件 vs 自己写 | **先找内置的** | 自己写限流容易漏掉并发、漏掉异步 |
| 中间件顺序 | **外层放"拦截/限流"，内层放"业务增强"** | 顺序反了，摘要会先于限流执行，等于白做 |
| 用中间件改业务规则 | **不要** | 业务规则应该在工具和提示词里，中间件只兜"系统韧性" |

### ⚠️ 一个必须知道的坑：中间件顺序是洋葱皮

真实输出（段 ④）：

```
  顺序 [A, B]：
      enter A
      enter B
      exit  B
      exit  A
  → 进入顺序 A→B，退出顺序 B→A（洋葱皮）。想「外层先拦截」就把拦截器放前面
```

**所以 `[HumanInTheLoopMiddleware(), SummarizationMiddleware()]` 的意思是**：
先审批（外层），再摘要（内层）。如果你写反了，就变成"先摘要到一半再问人要不要审批"——人能看到的上下文已经不是模型看到的了。

> 💥 **失败实验 1：删掉限流，看它转多少圈**
> 把 `step2` ② 的 `ModelCallLimitMiddleware(run_limit=5)` 删掉，同时把假模型剧本改成"永远返回 tool_calls"（比如复制 30 条 `ai(tool_calls=[...])`）。
> 重跑，观察它执行了多少次工具调用。
> **结论：框架默认**不会**帮你限制循环次数。这不是 bug，是"给你选择权"。第 16 章讲的那四种失控，在框架里一个都不少。**

---

## 46.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lc/ch46/step2_middleware.py`

### 问题 ①：怎么让"工具报错"不崩整个请求？

```python
def on_error(e: Exception, request) -> str:
    return f"工具执行失败（{type(e).__name__}）：{e}。请勿重试，直接告知用户稍后再试。"

create_agent(model, tools=[...], middleware=[ToolErrorMiddleware(on_error=on_error)])
```

真实输出（段 ②）：

```
    ToolMessage   '工具执行失败（ValueError）：数据库连不上。请勿重试，直接告知用户稍后再试。'
    AIMessage     '工具失败了，我先告诉用户稍后再试。'
```

**结论**：**异常变成一句话，模型看到后能自救。** 注意 `on_error` 必须接 **2 个参数**（异常 + request）——只写 1 个会 `TypeError`（我们踩过）。

### 问题 ②：怎么防止无限循环？

```python
middleware=[ModelCallLimitMiddleware(run_limit=5)]
```

**结论**：`run_limit` 是"整个线程内模型调用总次数"。超过之后行为取决于配置（抛异常/返回提示）。
**它不是"每轮 5 次"，是"累计 5 次"**——这点很多人搞错，导致长会话第 6 轮直接失败。

### 问题 ③：怎么在 30 个工具里选对？

```python
middleware=[LLMToolSelectorMiddleware(max_tools=5)]
```

**结论**：先用一个小模型"挑 5 个候选工具"，再让主模型在这 5 个里选。第 12 章实测：工具数越少，选对率越高。

### 🎯 到这里，你已经掌握了"用框架搭 Agent"

| 能力 | 在哪一节 |
|---|---|
| `create_agent` + 12 参数 | 45.3 |
| checkpointer + thread_id | 45.4 |
| 12 个内置中间件 | 45.4 step2 |
| 6 个钩子 + 洋葱皮顺序 | 45.5 |
| 0.x vs 1.x 对照 | 45.4 step3 |

**剩下的都是"画自己的图"（第 47–49 章）——但你已经知道一张 Agent 图长什么样了。**

---

## 46.7 全部 0.x 写法的对照表（这一节请收藏）

真实输出（`step3` ①）：

| 0.x 写法（在 1.x 里 import 不到） | 1.x 写法 |
|---|---|
| `from langchain.agents import initialize_agent` | `create_agent(model, tools=[...])` |
| `AgentExecutor(agent=..., tools=...)` | `create_agent(...)` 返回的就是图，直接 `.invoke()` |
| `agent_scratchpad` 手工拼中间步骤 | 框架自己维护 `messages` 列表 |
| `ConversationBufferMemory` / `ConversationSummaryMemory` | `checkpointer` + `SummarizationMiddleware` |
| `from langchain.memory import *` | 已移除；记忆 = 图状态 |
| `from langchain.chains import LLMChain` | `prompt \| model \| parser`（LCEL） |
| `from langchain.chains import RetrievalQA` | 自己组合 `retriever \| prompt \| model` |
| `create_stuff_documents_chain` | 自己写 8 行拼上下文（第 45 章） |
| `langchain.agents.AgentType.OPENAI_FUNCTIONS` | 不需要选类型，统一走 `tool_calls` |

**记忆口诀**：**凡是 `initialize_*`、`*Executor`、`*Memory`、`*Chain`（专有名词那种）的，都是 0.x。**

---

## 46.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `ModuleNotFoundError: langchain.agents.initialize_agent` | 0.x 写法 | `create_agent`（45.7） |
| 第二轮对话失忆 | 没传 `checkpointer`，或 `thread_id` 每次都变 | 传 checkpointer + 固定 thread_id |
| `duplicate middleware instances` | 两个同类中间件默认 `name` 相同（=类名） | 覆盖 `name` 属性 |
| `ToolErrorMiddleware requires on_error` | 没传 `on_error` | 传一个"异常 → 文本"的函数 |
| `on_error() takes 1 positional argument but 2 were given` | 签名写少了 | `def on_error(e, request)` |
| `Please remove duplicate middleware instances` | 同一个实例 `name` 冲突 | 同上 |
| 第 6 轮突然失败 | `ModelCallLimitMiddleware` 是**累计**限制 | 按会话长度调整，或改用 `ToolCallLimitMiddleware` |
| `create_agent` 里 `tools=[]` 报错/无意义 | 没工具就不是 Agent，是链 | 用 `prompt \| model \| parser` 更直接 |
| 中间件加了但没生效 | 顺序问题（内层被外层短路） | 拦截类放前面，增强类放后面 |
| `draw_ascii` 报 ImportError | 需要 `grandalf` / `pygraphviz` | `get_graph().nodes` / `.edges` 也能看结构 |

---

## 46.9 章末自测

**Q1** `create_agent` 返回什么？它由几个节点组成？

<details>
<summary>提示</summary>
`CompiledStateGraph`。四个节点：`__start__` / `model` / `tools` / `__end__`。
边：start→model、model→end、model→tools、tools→model。
</details>

**Q2** "没有 checkpointer 就没有记忆"——为什么？

<details>
<summary>提示</summary>
因为 Agent 本身只处理"这一次的 messages 列表"。
历史要留在某个地方才能下一轮续上，那个地方就是 checkpointer（按 thread_id 存）。
</details>

**Q3** 中间件的 6 个钩子分别在哪？`wrap_*` 和 `before/after_*` 的区别是什么？

<details>
<summary>提示</summary>
before/after_agent（整次运行前后）、before/after_model（每次调模型前后）、
wrap_model_call / wrap_tool_call（包住一次调用，能改输入输出、能拦）。
</details>

**Q4** 为什么 `ModelCallLimitMiddleware` 不是"每轮 5 次"？

<details>
<summary>提示</summary>
它是线程级累计。长会话里第 6 轮就会触发上限，表现为"聊着聊着突然不能用了"。
</details>

**加分题**

> 同事说："`create_agent` 就一行，那我直接用它就行了，干嘛还要学 LangGraph 画图？"

参考思路：**因为 `create_agent` 只能表达"ReAct 循环"。**
一旦你要"先检索 → 再生成 → 再校验 → 不通过就回退重写"，或者"三个子任务并行再合并"，
你需要的是一张自定义图。而这张图**就是** `create_agent` 内部的那张图——你只是把它拆开、重画。
第 47–49 章就是这件事。

---

## 46.10 可选补课：中间件的实现细节与 HITL

> ⚠️ **这一节可以先跳过。** 等你真要写"审批流"或"成本控制"时再看。

### `HumanInTheLoopMiddleware` 的配置形状

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware

mw = HumanInTheLoopMiddleware(
    interrupt_on={
        "apply_refund": True,          # 每次调用都问
        "delete_user":  {"allow_edit": True},   # 允许人改参数
        "query_order":  False,         # 不问
    }
)
```

`interrupt_on` 的 key 是**工具名**。值为 `True` 表示"必问"，为 dict 表示"细粒度策略"。
**跑起来后会走 `interrupt()`（第 50 章）**，用 `Command(resume=...)` 继续。

### `SummarizationMiddleware` 的关键参数

```python
SummarizationMiddleware(
    model=cheap_model,          # 用小模型摘要，省钱
    max_tokens_before_summary=6000,
    keep_messages=6,            # 保留最近几条原文
)
```

**注意它替换的是"早期消息"**，不是"整段历史"。所以"用户名字"这种早期事实**很可能被摘要掉**——第 26 章讲过这个坑。

### 中间件的执行成本

| 中间件 | 额外模型调用 | 额外延迟 |
|---|---|---|
| `ModelCallLimit` | 0 | ~0 |
| `ToolError` | 0 | ~0 |
| `Summarization` | 1 次（触发时） | +0.5–2s |
| `LLMToolSelector` | 1 次（每次） | +0.3–1s |
| `PII` | 0（正则）/ 1 次（模型） | 视实现 |

**所以"全挂上"不是免费的。** 生产里要按请求类型挂：内部工具调用可以不挂 `LLMToolSelector`。

---

## 46.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| `create_agent` 全参数 | `code/framework/lc/ch46/step1_create_agent.py` | 第 47–49 章手搭图的对照 |
| 12 个中间件 + 自定义钩子 | `code/framework/lc/ch46/step2_middleware.py` | 第 54 章（提示词灰度）、第 55 章（Guard） |
| 0.x 对照 + 裸循环 | `code/framework/lc/ch46/step3_legacy_vs_modern.py` | 第 49 章（ToolNode 手搭） |

**这一节建立的"可复用资产"**：`Audit` 中间件那 20 行，在第 38 章的 trace、第 55 章的 Guard 里会变成正式组件。

---

## 46.12 ✅ 验收

跑完三个脚本，检查五件事：

**① 你能说出这张图的四条边**

不看代码，画出 `create_agent` 的图（四个节点、四条边、一个条件）。

**② 你能解释 `thread_id` 的作用**

说出"同一个 thread_id / 不同 thread_id"两种情况下，第二轮对话看到的消息数。

**③ 你能说出三个"生产必挂"的中间件**

从 12 个里挑 3 个，并说明"不挂会发生什么"。

**④ 你能说出中间件顺序的影响**

`[A, B]` 的进入/退出顺序是什么？想让"审批"最先拦住，应该放前面还是后面？

**⑤ 一个数字**

`step1` ④ 的对比：无 checkpointer 返回 2 条，有 checkpointer 返回 4 条。

**现在算一个数**：如果每轮对话平均产生 2 条新消息、每条 100 token，
到第 10 轮时，**如果每次都把完整历史发给模型**，input token 是多少？如果只发最近 4 条呢？

<details>
<summary>答案</summary>

完整历史：第 n 轮时有 `2n` 条，累计发送 `2 × (1+2+...+10) × 100 = 11,000 token`
只发最近 4 条：`10 × 4 × 100 = 4,000 token`

差 **2.75 倍**。这就是第 24 章"上下文预算"和第 26 章"只留最近 N 轮会翻车"之间的张力：
**要么花更多钱，要么丢信息，要么上摘要。** 没有第四种选择。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 47 章 LlamaIndex——另一套检索路线。
框架部分换一条线：不画图、不做 Agent，只做"把文档变成可查询的索引"。你会看到它和 LangChain 的分工在哪里重叠、在哪里互补。

> 📎 参考：本章对应基础教程第 21 章《Agent 智能体》的知识点。
> **但基础教程用的是 0.x 的 `AgentExecutor` + `agent_scratchpad`**，本书第 45.7 节专门列了对照表，
> 并在 `step3` 里手写了那个循环，让你看清"框架替你做了什么"。
