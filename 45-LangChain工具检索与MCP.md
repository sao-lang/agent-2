# 第 45 章 LangChain（三）：工具、检索、记忆与 MCP

> **这一章你会遇到什么坏事**
> 你照着第 13 章手写的工具调用跑通了，想换成框架版。结果发现：
> `@tool` 装饰完，模型**根本不知道有这个工具**；加了 `args_schema`，模型**还是传错参数**；
> 工具内部报错，整条链**直接 500**，模型压根没机会自救。
>
> 更糟的是——**你想加个"记忆"，搜到的全是 `ConversationBufferMemory`，而它在 1.x 里已经不存在了。**
> 你开始怀疑：是不是装错版本了？

> **学完你能做到**
> 1. 用 `@tool` 写出模型能看懂、能调对的工具，并处理"工具报错"和"要给程序留原始数据"（44.3）
> 2. 用 `InMemoryVectorStore` + `Retriever` 跑通检索链路，并说清两者的分工（44.4）
> 3. 自己写 15 行"记忆"，并说清为什么 1.x 把它交给了 LangGraph（44.5）
> 4. 说清 MCP 的 client 侧做了什么、和 `@tool` 是什么关系、安全边界在哪（44.6）

---

## 45.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **`@tool`** | 一个装饰器：把普通函数变成"模型能看见的、带参数说明的工具" | 44.3 |
| **`args_schema`** | 工具参数的"说明书"，用 Pydantic 类描述每个参数是什么 | 44.3 |
| **`ToolException`** | 工具内部的标准异常，可以被转成"给模型看的文本" | 44.3 |
| **`artifact`** | 工具返回的"原始数据"，只给程序看，不给模型看 | 44.3 |
| **`InjectedToolArg`** | 标记"这个参数由框架注入，模型不该填"（比如 user_id） | 44.3 |
| **VectorStore / Retriever** | 前者能读能写，后者只能"给个查询、返回文档" | 44.4 |
| **checkpointer** | 把图的状态存下来（内存/SQLite/PG），记忆的载体 | 44.5 |
| **MCP** | 一个标准协议：让"工具"变成"可以被任何人发现和调用的服务" | 44.6 |

> 还有两个后面才出现：
> - **`tools/list` / `tools/call`**：MCP 的两个核心动作（列出工具 / 调用工具）
> - **`langchain-mcp-adapters`**：官方把 MCP 工具转成 LangChain 工具的包

---

## 45.1 先看一个具体的坏事：工具写完了，模型看不见

真实场景：你有三个函数——查订单、算退款、发通知。你想让 Agent 自己决定调哪个。

先跑一次看看工具"被看见"是什么样子：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lc\ch44\step1_tools.py
```

真实输出（段 ①）：

```
① 最简 @tool：函数签名 + docstring 就是全部
  name        = get_weather
  description = 查询指定城市的天气。用户在问冷热、下雨、要不要带伞时用。
  args        = {'city': {'title': 'City', 'type': 'string'}}
  调用        = 北京：晴，22℃
```

**注意这三行**：`name` / `description` / `args`——这就是模型能看到的**全部信息**。

现在换成一个"没写好"的版本：

```python
@tool
def f1(x: str) -> str:
    """查询"""
    return "..."
```

模型看到的是 `f1(x: str)：查询`。它会怎么用？**不知道。** 它可能永远不调，也可能拿 `x="你好"` 乱调。

| 你想知道的 | 模型能知道的 |
|---|---|
| 这个工具干什么 | 只看 docstring |
| 什么时候该用它 | 只看 docstring 里的"何时用" |
| 参数是什么意思 | 只看参数名 + `args_schema` 的描述 |
| 参数有什么约束（枚举/范围） | 只看 schema |

**结论：工具不是"写给自己用的函数"，是"写给模型看的接口文档 + 实现"。**

---

## 45.2 为什么"函数名 + 类型注解"还不够

你可能会想：Python 有类型注解 `def query(order_id: str)`，这不就够了吗？

我们真的对比一下（`step1` ②③）：

```
② args_schema：参数语义写清楚，模型才不会乱填
  json schema 的 properties = ['order_id', 'reason', 'amount']
  参数说明会一起喂给模型：退款原因
  调用 = 已提交：A1201 / 质量问题 / 99.0 元
```

**`order_id: str` 只告诉模型"这是个字符串"。** 它不知道是订单号还是用户 ID，不知道格式是 `A1201` 还是 `1201`。

加了 `args_schema` 之后：

```python
class RefundArgs(BaseModel):
    order_id: str = Field(description="订单号，形如 A1201")
    reason: Literal["质量问题", "七天无理由", "发错货"] = Field(description="退款原因")
    amount: float = Field(gt=0, description="退款金额（元）")
```

差别：

| 写法 | 模型看到 | 实际效果 |
|---|---|---|
| 只有类型注解 | `order_id: string` | 常传错格式 |
| 加 description | `order_id: 订单号，形如 A1201` | 显著改善 |
| 加 `Literal` | `reason: 质量问题 \| 七天无理由 \| 发错货` | **不会传第四种值** |
| 加 `gt=0` | 有下限约束（部分 provider 会校验） | 减少负数金额 |

**所以我们需要的不只是"工具"，而是"带契约的工具"。**

> 💥 **失败实验 1：把 description 删掉**
> 把 `get_weather` 的 docstring 从"查询指定城市的天气。用户在问冷热、下雨、要不要带伞时用。"改成 `"查询"`。
> 重跑 `step1` ①，观察 `description` 字段变成什么。
> **结论：docstring 就是 description，是模型选工具的唯一依据。** 第 15 章讲 Skill 时说的"description 是门牌"，在工具这里一模一样。

---

## 45.3 工具到底是什么（10 行代码看懂）

### 一句话

> **一个工具 = 一个函数 + 一份给它看的说明书（name / description / 参数 schema）。**

### 最小例子

💻 `python code/framework/lc/ch45/step1_tools.py`

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """查询指定城市的天气。用户在问冷热、下雨、要不要带伞时用。"""
    return f"{city}：晴，22℃"
```

就这些。装饰器做了三件事：取函数名做 `name`、取 docstring 做 `description`、**从类型注解生成 JSON Schema**。

### 四个进阶点（这就是"工具"的全部复杂度）

`step1` 把四个最常用的进阶点各跑了一遍：

| 进阶点 | 解决什么问题 | 数据 |
|---|---|---|
| `args_schema` | 参数含义太模糊，模型乱填 | 44.1 的对比 |
| `ToolException` + `handle_tool_error` | 工具报错直接把链搞崩 | 见下 |
| `response_format="content_and_artifact"` | 模型要摘要，程序要原始数据 | 见下 |
| `InjectedToolCallId` / `InjectedToolArg` | 框架要偷偷塞参数给工具 | 见下 |

### ① 工具报错：从"崩溃"到"给模型看的反馈"

```python
@tool
def query_order(order_id: str) -> str:
    """按订单号查询订单状态。"""
    raise ToolException("订单不存在：check_order_id 校验失败")

query_order.handle_tool_error = "订单号可能有误，请让用户确认后重试"
```

真实输出（段 ③）：

```
  handle_tool_error 未设置时 → 直接抛：ToolException
  设置 handle_tool_error 后 → 返回文本：'订单号可能有误，请让用户确认后重试'
  → 模型看到的是这句话，它会自己决定「再问用户」还是「换个参数」
```

**这就是"能失败"的工程含义**：不是"不失败"，是**失败变成模型能读懂的一句话**。

### ② artifact：给模型摘要，给程序原始数据

```python
@tool(response_format="content_and_artifact")
def search_kb(query: str):
    """在知识库中检索。"""
    docs = [{"id": 1, "text": "...", "score": 0.91}, ...]
    return "找到 2 条：...", docs     # (content, artifact)
```

真实输出（段 ④）：

```
  以 tool_call 方式调用 → ToolMessage
  msg.content（模型看的）  = 找到 2 条：退货需在 30 天内；退款 7 个工作日到账
  msg.artifact（程序留的） = [{'id': 1, 'text': '退货需在 30 天内', 'score': 0.91}, ...]
```

**为什么重要**：前端要显示"引用来源"时，读 `artifact`；别让模型把 chunk id 抄一遍——它一定会抄错。

### ③ 注入参数：模型不该填的东西

```python
@tool
def update_todo(item: str, tool_call_id: str = InjectedToolCallId()) -> str:
    """更新待办清单。"""
    return f"已记录 {item}（call_id={tool_call_id}）"
```

真实输出（段 ⑤）：

```
  args（注意 tool_call_id 不出现在 schema 里）= ['item', 'tool_call_id']
```

**注意**：它出现在 `args` 里（Python 层要给个默认值），但**不出现在 JSON Schema 里**（模型看不到）。

### ✏️ 停下来想一想

`step1` ⑥ 展示了一次真实调用：模型返回 `tool_calls`，框架执行工具，把结果作为 `ToolMessage` 追加回消息列表。

**那问题来了：如果工具返回的是一段 2000 字的文档，模型下一步会看到什么？**

（提示：全部 2000 字都会进上下文，并按 input token 计费。这就是 44.4 后面要讲的"检索结果要摘要"的动机。）

---

## 45.4 从"工具"到"检索"（阶梯代码 step1 / step2 / step3）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_tools.py` | `@tool` 与四个进阶点 | — |
| step2 | `step2_retrieval.py` | VectorStore / Retriever / 检索进链 | step1 只有"函数工具"，没有"知识" |
| step3 | `step3_memory_mcp.py` | 记忆迁移 + MCP 两侧 | step2 每次都是无状态请求 |

### step2：向量库与检索器

痛点一句话：**第 8–11 章手写过检索，真实项目不想再造一遍，也不想被某个数据库绑死。**

💻 `python code/framework/lc/ch45/step2_retrieval.py`

真实输出（段 ①）：

```
  已写入 5 条
  query='退款 到账 工作日'（假嵌入只认字面，注意这不是语义检索）
    0.7641  [p2] 退款将在 7 个工作日内原路退回。
    0.4743  [p1] 退货需在签收后 30 天内申请。
    0.3038  [p3] 保修期为一年，人为损坏不在保修范围。

  加 filter（排除 topic=退款）：['p1', 'p5', 'p3']
```

**注意那句提示**：这里用的是 `EchoEmbeddings`（假嵌入），**只认字面**。
真实语义检索要用 `OpenAIEmbeddings` 或本地模型。**用假嵌入评估检索质量是自欺欺人**——这一点第 40 章会反复强调。

`VectorStore` 和 `Retriever` 的分工（段 ②）：

```
  VectorStore  vs  Retriever
    VectorStore: add / delete / search / as_retriever   （读 + 写）
    Retriever  : invoke(query) -> list[Document]         （只读，可来自任何地方）
```

**一句话**：**写数据用 VectorStore，读数据只依赖 Retriever。**
这样将来把向量库换成 BM25、换成 API、换成 SQL，检索那一段代码都不用改。

### step3：记忆 + MCP

痛点一句话：**0.x 的 `Memory` 类没了；MCP 又常被误解成"另一种工具格式"。**

💻 `python code/framework/lc/ch45/step3_memory_mcp.py`

真实输出（段 ①）：

```
  A 全量保留     : 6 条消息，越长越贵
  B 只留最近 2 轮 : 4 条消息，用户名字已经丢了
  C 摘要 + 最近轮 : 摘要 14 字 + 1 条消息

  → 三种做法的代码都只有十行。ConversationBufferMemory 干的就是 A 那一小段。
```

**这就是"记忆"的全部**：三种裁剪策略，每行代码你都看得懂。

---

## 45.5 核心实现（逐行解释）

这一节把"为什么记忆搬到 LangGraph"讲透——**这是最多人卡住的地方**。

### 先看三段手写记忆（各 10 行）

```python
# A：全量保留
history_a.append(HumanMessage(q))
history_a.append(llm.invoke(history_a))

# B：只留最近 N 轮
history_b.append(HumanMessage(q))
history_b.append(llm.invoke(history_b))
history_b = history_b[-4:]          # ①

# C：摘要 + 最近轮
summary = "用户自称张三，上周买了耳机。"
history_c = [HumanMessage("我要退货")]
```

| 行 | 在做什么 | 后果 |
|---|---|---|
| ① | 硬截断最近 2 轮 | **用户名字丢了**（真实输出里明说了） |

### 为什么这三段不够：三个问题，Memory 类都答不了

真实输出（段 ②）：

```
  记忆的三个真问题，Memory 类回答不了：
    1. 存在哪？     进程内存 → 重启全丢（LangGraph: checkpointer = SQLite/PG）
    2. 按什么粒度？ 一轮 / 一个会话 / 一个用户（LangGraph: thread_id + namespace）
    3. 怎么裁剪？   全量 / 窗口 / 摘要（LangGraph: 中间件 SummarizationMiddleware）
  → 换句话说：记忆的本质是「状态管理」，不是「消息容器」。状态应该由运行时管。
```

**这三条里，第 1 条是决定性的**：`ConversationBufferMemory` 活在进程内存里。
你的 Agent 旁边有 nginx、有 uvicorn 多 worker、有滚动发布——**一重启用户就失忆**。
这不是"功能不够"，是"根本不能用"。

| 需求 | 0.x 的答案 | 1.x 的答案 |
|---|---|---|
| 重启不丢 | ❌（内存） | checkpointer（SQLite / PG） |
| 多会话隔离 | 手动 `conversation_id` | `thread_id`（框架保证） |
| 上下文太长 | 换一个 Memory 类 | `SummarizationMiddleware` |
| 跨会话长期记忆 | ❌ | `BaseStore`（第 28 章） |

**三个设计取舍**

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 记忆放进程内 vs 放外部存储 | **外部存储**（哪怕只是 SQLite） | 多 worker 下会话随机"失忆" |
| 按轮截断 vs 摘要 | **摘要 + 最近 N 轮**（第 27 章实测） | 只截断：早期关键事实全丢 |
| 记忆和状态分开 vs 合一 | **合一**（消息列表就是状态的一部分） | 两套真相，必然不同步 |

### ⚠️ 一个必须知道的坑：MCP 工具是别人写的

真实输出（段 ④）：

```
  三条硬约束（第 33 章沙箱 / 第 55 章 Guard 的落地）：
    1. 名字加服务前缀    order-mcp__query_order  （出事能定位到服务）
    2. allowed-tools 收窄 skill 能看到的工具集合
    3. 危险动作默认拦    delete / drop / truncate 一律人工审批

  反例：某 MCP 服务升级后新增了 delete_all_orders，
        你的 agent 第二天就把表清了 —— 因为你没做第 3 条。
```

**MCP 不是"另一种工具格式"，是"工具发现 + 调用"的标准协议。** 转换后它就是普通 `Tool`，Agent 完全不知道它来自网络。
**正因为"不知道"，你才必须在接入层做防护。** 第 55 章会把这三条做成可自动跑的断言。

> 💥 **失败实验 2：把 MCP 工具当成"自己写的工具"**
> 打开 `step3` ③，把 `to_langchain()` 生成的工具名从 `f"{server}__{spec['name']}"` 改成 `spec['name']`。
> 现在假设两个 MCP 服务都暴露了 `query`——`Registry.register` 会怎样？
> 答案：**抛"工具重名"**。如果它不抛（比如你用了 `dict[name] = tool` 覆盖），你就丢了一个工具，而且**没有任何提示**。
> 这就是第 55 章"工具名必须带来源前缀"的真正原因。

---

## 45.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lc/ch45/step2_retrieval.py` + `step3_memory_mcp.py`

### 问题 ①：检索结果怎么进链？

```python
rag = (
    {"context": retriever | fmt, "question": RunnablePassthrough()}
    | ChatPromptTemplate.from_template("资料：\n{context}\n\n问题：{question}")
    | model
    | StrOutputParser()
)
rag.invoke("怎么退货")
```

**结论**：那个 `dict` 字面量会被自动转成 `RunnableParallel`——**这是 LCEL 最常用的一招**（段 ③）。

### 问题 ②：为什么 1.x 没有 `create_stuff_documents_chain`？

真实输出（段 ④）：

```
④ 1.x 里没有 create_stuff_documents_chain —— 自己写 8 行
  答案 = '退款 7 个工作日到账。[p2]'
  → 你在 0.x 教程里看到的 AgentExecutor / create_stuff_documents_chain，
    在 1.x 都要换成「自己组合 + create_agent」，别照抄旧代码
```

**结论**：那个 chain 只做一件事——把 `Document` 列表拼成一段文本。**8 行就能写完，而且更可控。**

### 问题 ③：检索质量在哪里出问题？

真实输出（段 ⑤）：

```
  k=1 → ['p2']
  k=2 → ['p2', 'p1']
  k=4 → ['p2', 'p1', 'p3', 'p4']
  → k 越大召回越高，但上下文越长、越容易「读到无关资料」。见第 10、24 章
```

**结论**：**框架只负责"调检索"，不负责"检索得准"。** 分块、混合检索、重排是第 9、10 章的事。

### 🎯 到这里，你已经掌握了 Agent 的三类零件

| 零件 | 在哪一节 | 后面谁用 |
|---|---|---|
| 工具（本地 + MCP） | 44.3 / 44.6 | 第 46 章 `create_agent(tools=[...])` |
| 检索（VectorStore + Retriever） | 44.4 | 第 47 章 LlamaIndex 对照 |
| 记忆（交给 checkpointer） | 44.5 | 第 50 章持久化、第 26/27 章分层记忆 |

**剩下的都是"把它们装进一个 Agent"（第 46 章）。**

---

## 45.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数观察变化

把 `step2` 的 `as_retriever(search_kwargs={"k": 2})` 改成 `k=1`，重跑 ④。
**验收标准**：你要能说出"为什么 k=1 时 ④ 的答案仍然是 p2，但换成别的问题就会错"。

### 练习 2（20 分钟）：接到你自己的项目上

把你项目里**任意一个** `def xxx(...)` 改成 `@tool`。

**最低要求清单**：
- [ ] docstring 里写清"做什么 + 何时用 + 不适用什么"
- [ ] 参数用 `args_schema` 描述清楚，枚举值用 `Literal`
- [ ] 可能失败的地方抛 `ToolException`，并设置 `handle_tool_error`
- [ ] 加一条测试：喂错参数，断言返回的是"给模型看的文本"而不是异常

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：把 `handle_tool_error` 删掉。**
重跑 `step1` ③。观察：异常直接冒泡。结论：**在生产里这等于"工具一抖，用户看到 500"。**

**实验 B：让工具返回 2000 字。**
把 `search_kb` 的 `content` 改成把 5 条文档全文拼起来。然后用第 2 章的口径算一下 input token。
结论：**工具返回值就是上下文，它按 input 计费。所以"检索回来 10 条全文"是很贵的习惯。**

**实验 C：`InjectedToolArg` 忘了补参数。**
重跑 `step1` ⑤，观察 `ValidationError`。结论：**注入参数不会被模型填，必须由调用方（或中间件）补齐。**

---

## 45.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 模型永远不调这个工具 | docstring 没写"何时用"/ 写成了函数注释风格 | 用三段式：做什么 / 何时用 / 不适用什么 |
| 模型传错参数 | 只有类型注解，没有 `description` | 加 `args_schema` + `Field(description=...)` |
| 传了枚举外的值 | 用了 `str` 而不是 `Literal` | `Literal["a","b"]` |
| 工具报错导致整链 500 | 没设 `handle_tool_error` | 抛 `ToolException` + 设兜底文本 |
| `artifact` 一直是 `None` | 用 `Tool.invoke({...})` 直接调，而不是 `tool_call` 形式 | 以 `{"type": "tool_call", ...}` 调用，或让 Agent 调 |
| `ModuleNotFoundError: langchain.chains` | 0.x 写法 | 参考 44.6 问题 ② |
| `InjectedToolArg` 报 `Field required` | 注入参数没人补 | 由调用方补，或用中间件/`ToolNode` 自动补 |
| 检索结果驴唇不对马嘴 | 用了假嵌入做语义检索 | 换成真嵌入；假嵌入只能跑通管线 |
| 工具重名被静默覆盖 | 直接 `dict[name] = tool` | 用会抛错的 registry（第 55 章） |
| 多 worker 下会话失忆 | 记忆在进程内存 | 上 checkpointer（第 50 章） |

---

## 45.9 章末自测

**Q1** `@tool` 装饰器到底加了什么信息？模型靠什么选工具？

<details>
<summary>提示</summary>
加了 `name`、`description`（来自 docstring）、参数 JSON Schema。
模型只靠这三样选，**看不到函数体**。
</details>

**Q2** `VectorStore` 和 `Retriever` 的分工是什么？为什么检索层只该依赖后者？

<details>
<summary>提示</summary>
VectorStore 能写能读；Retriever 只有 `invoke(query) -> docs`。
依赖 Retriever 之后，换 BM25 / API / SQL 都不用改链。
</details>

**Q3** 为什么 1.x 把"记忆"交给了 LangGraph？

<details>
<summary>提示</summary>
因为记忆的三个真问题是"存在哪 / 按什么粒度分 / 怎么裁剪"，
这是**状态管理**，该由运行时负责。0.x 的 Memory 类只解决了"内存里存消息列表"。
</details>

**Q4** MCP 和 `@tool` 是什么关系？

<details>
<summary>提示</summary>
MCP 是"工具发现 + 调用"的协议；转换成 LangChain 工具后，它就是一个普通 `Tool`。
区别在于**它来自网络、是别人写的**，所以要加来源前缀、收窄权限、危险动作拦截。
</details>

**加分题**

> 同事说："`content_and_artifact` 没什么用，反正模型看不到 artifact，直接返回 dict 不就完了？"

参考思路：**返回 dict 会被序列化进 content，然后占 input token。**
artifact 的价值是"给程序留一份结构化数据，**不进上下文**"。
前端要显示引用来源时读 artifact，模型只看到摘要——**这是省 token 的正确姿势**，也是第 34 章"省 token ≠ 省钱"的反例（这里省 token 就是省钱，因为模型根本不需要那些 id）。

---

## 45.10 可选补课：MCP 的传输方式与真实接入

> ⚠️ **这一节可以先跳过。** 等你真要接一个 MCP 服务时再看。

### 两种传输

| 传输 | 场景 | 写法 |
|---|---|---|
| **stdio** | 本地进程，最简单 | `StdioServerParameters(command="python", args=["server.py"])` |
| **http / streamable-http** | 远程服务 | `StreamableHttpTransport(url="https://...")`（旧版是 SSE） |

### 官方适配器（装它就不用自己写转换）

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "order": {"command": "python", "args": ["order_server.py"], "transport": "stdio"},
})
tools = await client.get_tools()      # ← 这就是本章手写的 to_langchain()
```

`get_tools()` 返回的就是 `list[BaseTool]`，可以直接丢给 `create_agent`。

### 三个必须查文档的时刻

1. **服务端声明了 `inputSchema` 里的 `$ref` / `anyOf`**：不同客户端支持度不同，可能转换失败
2. **工具返回的是图片/资源而不是文本**：需要 `content blocks` 支持
3. **需要认证**：http 传输要带 `headers`，stdio 要通过环境变量传 token

### 安全清单（抄进你的接入层）

```
[ ] 每个 MCP 服务的工具都加服务名前缀
[ ] 只暴露白名单里的工具（不要 tools/list 全量透传）
[ ] 危险动作（delete/drop/truncate/write）默认拦，走人工审批
[ ] 调用超时（默认可能是无限等）
[ ] 记录 server_name + tool_name + 耗时 + 成败
```

---

## 45.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| `@tool` 四件套 | `code/framework/lc/ch45/step1_tools.py` | 第 46 章 `create_agent(tools=...)` |
| 检索三写法 | `code/framework/lc/ch45/step2_retrieval.py` | 第 47 章 LlamaIndex 对照 |
| 记忆三段 / MCP 转换 | `code/framework/lc/ch45/step3_memory_mcp.py` | 第 50 章 checkpointer、第 55 章 Guard |

**这一节建立的"可复用资产"**：`to_langchain()` 那 15 行 MCP 转换，在第 55 章的 `Registry.register_mcp()` 里会变成正式实现。

---

## 45.12 ✅ 验收

跑完三个脚本，检查五件事：

**① 你能说出模型"看到"的工具长什么样**

不看笔记，写出 `get_weather` 在模型眼里是什么（三行：name / description / args）。

**② 你能解释 `handle_tool_error` 的意义**

说出"没有它"和"有它"两种情况下，用户分别看到什么。

**③ 你能画出 retriever 进链的图**

```
{"context": retriever | fmt, "question": passthrough} → prompt → model → parser
```

**④ 你能说出记忆迁移的三个理由**

不听"因为新版这样"，要说出"存在哪 / 粒度 / 裁剪"具体怎么被解决。

**⑤ 一个数字**

`step2` ② 里 `retriever.invoke('保修 一年')` 返回 2 条，第一条是 `p3`。

**现在算一个数**：如果每次检索返回 3 条、每条 120 字，按第 2 章口径（中文 1 字 ≈ 0.95 token），
这些文档占多少 input token？如果一次会话有 8 轮，每轮都检索，**多花多少 token？**

<details>
<summary>答案</summary>

单轮：`3 × 120 × 0.95 ≈ 342 token`
8 轮：`342 × 8 ≈ 2,736 token`

对照 `step2` 的 `k=1 / k=2 / k=4` 那三行输出：**k 从 2 提到 4，上下文直接翻倍，而召回未必提升**。
这就是"检索的 token 预算"必须单独管的原因（第 25 章）。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 46 章 `create_agent` 与中间件。
零件齐了（模型 / 提示词 / 解析 / 工具 / 检索 / 记忆），下一章把它们装成一个**能跑、能限流、能重试、能摘要、能审批**的 Agent，
并且逐条对照"你在别处看到的 0.x 写法为什么现在不能用了"。

> 📎 参考：本章对应基础教程第 18 章《Tools 工具调用》、第 19 章《向量数据库与 Embedding》、
> 第 20 章《RAG 检索增强生成》、第 21 章《MCP 模型上下文协议》、第 17 章《记忆与对话历史》的知识点。
> 本书把"记忆"这一节**整体改写**为"记忆为什么搬家"，因为基础教程第 17 章讲的 `Memory` 类在 1.x 已经不在了。
