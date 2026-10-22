# 第 42 章 LangChain（一）：包结构、模型接入与消息

> **这一章你会遇到什么坏事**
> 你按网上的教程敲完 `pip install langchain`，然后 `from langchain.memory import ConversationBufferMemory`——
> `ModuleNotFoundError`。换成另一个教程的 `from langchain.agents import initialize_agent`——
> 还是 `ModuleNotFoundError`。折腾两小时后你发现：**那些教程是 LangChain 0.x 的，你装的是 1.x。**
>
> 更糟的是——**1.x 不是"改了几个名字"，而是把整包拆成了几十个包，把记忆整个交给了另一套东西（LangGraph）。**
> 你照着旧教程改 import，改到凌晨也改不出一个能跑的版本。

> **学完你能做到**
> 1. 用 20 行代码跑通"一次调用 + 多轮消息"，并说清返回对象里每个字段是什么（42.3）
> 2. 看到任何一条 LangChain 报错，能判断它属于"core / langchain / provider 包"的哪一层（42.4）
> 3. 把提示词从"代码里的 f-string"变成"可复用的模板对象"（42.5）
> 4. （可选）知道接本地 Ollama 只改一个环境变量

---

## 42.0 先说明白七个词

这一章会出现七个新词。**先花 1 分钟看完这张表**，后面就顺了。

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **LangChain** | 一层"应用装配层"：把模型、提示词、工具、检索**接**成一个应用，它自己既不是模型也不是数据库 | 全章 |
| **`Runnable`** | 一种"可以被调用"的东西的统称，有 `invoke` / `stream` / `batch` 三件套，像电器都有插头 | 42.6 起，第 43 章重点 |
| **消息（Message）** | 一次对话里的"一句话 + 它是谁说的"，共有 system / human / ai / tool 四类 | 42.3 |
| **`content`** | 消息的**正文**，可能是字符串、也可能是"文本 + 图片"的列表 | 42.3 |
| **`usage_metadata`** | 这次调用花了多少 token 的官方记录（结构化的，不是让你自己数） | 42.3 |
| **`init_chat_model`** | 一个按名字创建模型的工厂：换厂商只改一个字符串 | 42.4 |
| **frontmatter / 模板** | 带变量的提示词，变量用 `{花括号}` 标出来 | 42.5 |

> 还有三个名词后面才出现，这里先提一句，看到时不用慌：
> - **provider（提供方）**：OpenAI / Anthropic / Ollama 这些厂商。1.x 里**一家一个包**。
> - **LCEL**：用 `|` 把几个 Runnable 串起来的写法，第 43 章整章讲。本章只需要知道 `a | b` 是"接起来"。
> - **LangGraph**：另一套"画图"的库，负责状态、记忆、中断。本章只在 42.6 提一句**为什么记忆搬到那里去了**。

---

## 42.1 先看一个具体的坏事：同一个需求，两份文档，跑不起来

真实场景：你要给售后系统接一个大模型，需求只有三步——**发一句话、收一句话、把花费记下来**。

你手里现在只有这些：

| 你想做的事 | 旧教程怎么做 | 你在 1.x 里实际遇到 |
|---|---|---|
| 发一次请求 | `OpenAI().chat(...)` | 要用 `ChatOpenAI(...).invoke(...)` |
| 记住上下文 | `ConversationBufferMemory` | `langchain.memory` **整个模块没了** |
| 流式输出 | `llm.stream(...)` | 有，但返回的是**chunk 对象**，不是字符串 |
| 看花了多少钱 | 没有这个说法 | 有 `usage_metadata` 字段，但旧教程从不提 |

先真的跑一遍看看：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lc\ch42\step1_message_io.py
```

真实输出（节选）：

```
① 一次调用的返回，是个对象而不是字符串
  type(msg)                = AIMessage
  msg.content              = '退款需要 7 个工作日到账。'
  msg.usage_metadata       = {'input_tokens': 68, 'output_tokens': 13, 'total_tokens': 81}
  msg.response_metadata    = {'model_name': 'gpt-4o-mini', 'finish_reason': 'stop'}
  msg.tool_calls           = []
```

**结论：你不是"不会用 LangChain"，你是"在用一套已经不存在于文档里的接口"。**

这份教程从这一章起，所有代码都跑在**当前的实际版本**上：

```
langchain            1.4.7
langchain-core       1.6.13
langchain-openai     1.7.2
langgraph            1.2.16
```

> 版本写死在 `requirements.txt` 里。**你看到任何"最新版"字样，都不如看这四行数字。**

---

## 42.2 为什么 0.x 的办法不够（先别急着学新 API）

你可能会想：那我照着旧教程把 import 改一改不就行了？

我们真的试一下。旧教程的 Agent 大概长这样（0.x）：

```python
from langchain.agents import initialize_agent, AgentType
from langchain.memory import ConversationBufferMemory

memory = ConversationBufferMemory(memory_key="chat_history")
agent = initialize_agent(tools, llm, agent=AgentType.OPENAI_FUNCTIONS, memory=memory)
agent.run("我要退款")
```

在 1.x 里，这段代码有**四个**致命问题：

| 问题 | 现象 | 根本原因 |
|---|---|---|
| **模块被删了** | `langchain.agents` 里没有 `initialize_agent`；`langchain.memory` 整个不存在 | 1.x 把"记忆"交给 LangGraph，把"链"交给 LCEL |
| **`agent_scratchpad` 要你手拼** | 旧代码靠一个隐式变量把中间步骤塞回提示词 | 现在 `messages` 列表就是全部上下文，不需要"草稿纸" |
| **没法断点恢复** | `memory` 只在进程内存里，重启全丢 | 1.x 用 checkpointer（第 49 章），可以落 SQLite/PG |
| **看不到成本** | 旧代码不读 `usage_metadata` | 成本在消息里，但没人教你去读 |

**所以这不是"改个名字"的事。** 底层换了三样东西：

```
0.x：Chain（线性）  + Memory（自带）  + AgentExecutor（专用循环）
1.x：Runnable（可组合）+ State（交给 LangGraph）+ create_agent（就是一张图）
```

> 💥 **失败实验 1：亲眼看见 0.x 的写法已经不能用**
> 新建一个 `test_old.py`，写这三行然后运行：
> ```python
> import langchain.chains  # 0.x 时代这里有一堆 Chain
> ```
> 你会看到 `ModuleNotFoundError: No module named 'langchain.chains'`。
> 再试 `from langchain.memory import ConversationBufferMemory`，同样报错。
> **这不是你装错了包，是这些模块在 1.x 里被移走了。**

---

## 42.3 消息到底是什么（10 行代码看懂）

### 一句话

> **一条消息 = "谁说的" + "说了什么"。一段对话就是这些消息按顺序排成的列表。**

就这么简单。模型没有记忆，它每次都把**整个列表**重新读一遍——所谓"多轮对话"，本质是"每次都把所有历史再发一次"。

### 最小例子

💻 运行：`python code/framework/lc/ch42/step1_message_io.py`

核心就这几行：

```python
from langchain_core.messages import HumanMessage, AIMessage

history = [
    HumanMessage("我买的耳机坏了"),
    AIMessage("很抱歉。请问订单尾号是多少？"),
    HumanMessage("8848"),
]
reply = model.invoke(history)      # 把整个列表发过去
history.append(reply)              # 把回复也追加进去
```

四个类型，各管一件事：

| 类型 | 谁说的 | 典型内容 |
|---|---|---|
| `SystemMessage` | 你（开发者） | "你是售后助手，不要承诺赔付金额" |
| `HumanMessage` | 用户 | "我要退款" |
| `AIMessage` | 模型 | 文本，或 `tool_calls` |
| `ToolMessage` | 你的代码 | 工具执行结果，**必须带 `tool_call_id`** |

真实输出（`step1` ②）：

```
  1. system  '你是售后助手，不确定时不要承诺赔付金额。'
  2. human   '我买的耳机坏了'
  3. ai      '很抱歉。请问订单尾号是多少？'
  4. human   '8848'
  5. ai      ''  tool_calls=[{'name': 'query_order', 'args': {'tail': '8848'}, 'id': 'c1', 'type': 'tool_call'}]
  6. tool    '订单 A1201，状态：已签收 12 天，在保修期内'  tool_call_id=c1
```

**就这几样东西。** 你在任何 Agent 框架里看到的花哨流程（ReAct、工具循环、多轮记忆），底层都是这六条消息在变。

### 把它包成一个类（不需要，但要知道为什么不需要）

0.x 里这些角色是字符串（`{"role": "user", "content": ...}`）。1.x 换成类，好处是**类型安全**：

```python
# 字符串写法（0.x 风格）：拼错 role 不会报错
{"role": "usre", "content": "..."}      # 运行时才知道错

# 类写法（1.x）：写错立刻报错
HumanMessage("...")                      # 拼错就是 NameError
```

### ✏️ 停下来想一想

上面 `step1` 的 ③ 里有一件事很反直觉：**`content` 不一定是字符串**。

```
③ 一个必须知道的坑：content 不一定是纯文本
  type(content) = list
  content       = [{'type': 'text', 'text': '图里是一张退货单。'}, {'type': 'image_url', ...}]
  str(content)  = [{'type': 'text', 'text': '图里是一张退货单。'}, {'type': 'image_url'...
```

那问题来了：**如果你线上用 `f"{msg.content}"` 给用户显示答案，遇到多模态消息会发生什么？**

（答案在 42.8 常见错误速查第 1 条。）

---

## 42.4 从"能调一次"到"能换厂商"（阶梯代码 step1 / step2 / step3）

> 这是本章最重要的结构。每上一个 step，只增加一个新概念。

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_message_io.py` | 消息对象与 `usage_metadata` | — |
| step2 | `step2_packages.py` | 包结构 + `init_chat_model` 多 provider | step1 里模型是写死的假对象 |
| step3 | `step3_prompts.py` | 提示词模板（变量、多角色、few-shot） | step2 里提问是硬编码字符串 |

### step1：把返回值拆到底

痛点一句话：**"模型返回一个字符串"是最大的误解。**

💻 `python code/framework/lc/ch42/step1_message_io.py`

输出见 42.3。这一级解决了什么：你现在知道该从 `.content` 取文字、从 `.usage_metadata` 取成本。

### step2：包结构 + 多 provider

痛点一句话：**"装一个 langchain 就够了"是 0.x 的经验，1.x 装错包会直接 ImportError。**

💻 `python code/framework/lc/ch42/step2_packages.py`

真实输出（段 ①）：

```
  包名                            作用                        安装?     版本
  ----------------------------------------------------------------------------
  langchain-core                接口与基础类型                   ✓       1.6.13
  langchain                     主包：create_agent、中间件       ✓       1.4.7
  langchain-openai              OpenAI / 兼容接口的实现          ✓       1.7.2
  langchain-anthropic           Claude 实现                 —       （可选）
  langchain-ollama              Ollama 实现                 —       （本地模型时）
  langgraph                     图编排（create_agent 的底座）     ✓       1.2.16
```

**为什么 1.x 要拆包？** 因为 0.x 一个 `langchain` 包把 40 多家厂商的 SDK 全拽进来，装一次 2GB。
1.x 的做法是：`core` 只放接口，**一家厂商一个包**，用什么装什么。

| 包 | 里面有什么 | 什么时候需要 |
|---|---|---|
| `langchain-core` | `BaseChatModel`、`Runnable`、各种 Message、Prompt 模板、Parser | 永远需要 |
| `langchain` | `create_agent`、中间件 | 做 Agent 时 |
| `langchain-openai` | OpenAI / 任何兼容 OpenAI 协议的网关 | 用 OpenAI 或国产兼容网关时 |
| `langchain-ollama` | 本地 Ollama | 本地跑模型时 |
| `langgraph` | 状态图引擎 | 做 Agent 时自动带上 |

**排错的黄金问题：这个类属于 core，还是属于某个 provider 包？**

- `NameError: HumanMessage` → 忘了 `from langchain_core.messages import ...`（core）
- `ModuleNotFoundError: langchain_openai` → 没装 `langchain-openai`（provider）
- `ValueError: Unsupported provider='opnai'` → provider 名字拼错（`init_chat_model` 的）

真实输出（段 ③）：

```
③ 写错 provider 会发生什么
  ValueError: Unsupported provider='opnai'.
  Supported model providers are: anthropic, anthropic_bedrock, azure_ai, azure_openai, ...
```

**注意这个错误多好定位**：它直接把合法值列出来了。所以**尽量用 `init_chat_model`，不要自己 `import` 某个厂商的类**。

真实输出（段 ②，离线环境）：

```
  init_chat_model 构造失败：OpenAIError（离线环境没有 API Key 时属正常）
    原文：Missing credentials. Please pass an `api_key`, ...
  → 它只做两件事：按 provider 找实现类、把参数塞进去。不发请求。
```

> **这里有个容易误解的点**：`init_chat_model` 在**构造阶段**就要凭据（因为要建 HTTP 客户端），
> 不是"发请求时才要"。所以离线环境会失败——这正常，不是 bug。

这一级解决了什么：**换厂商从"改 20 行 import"变成"改一个字符串"。**

### step3：提示词模板

痛点一句话：**每次手拼 f-string，变量漏填时静默变成 `None`。**

💻 `python code/framework/lc/ch42/step3_prompts.py`

真实输出（段 ②③④ 节选）：

```
② ChatPromptTemplate：多角色（真实项目 90% 用这个）
  SystemMessage  '你是售后的助手，回答不超过50字。'
  HumanMessage   '能退吗？'

③ MessagesPlaceholder：把历史消息原样插进去
  SystemMessage  '你是售后助手。'
  HumanMessage   '我上周买的'
  AIMessage      '好的，请问什么问题？'
  HumanMessage   '耳机没声了'
  共 4 条消息（history 占了 2 条）

④ few-shot：用示例固定输出风格
  渲染出 6 条消息
```

三种模板，一个选择口诀：

| 用哪个 | 什么时候 |
|---|---|
| `PromptTemplate` | 只有一段文本（补全类模型、或者拼一段上下文） |
| `ChatPromptTemplate` | **聊天模型**（99% 的场景） |
| `FewShotChatMessagePromptTemplate` | 想用示例固定输出风格 |

这一级解决了什么：提示词变成**对象**，可以复用、可以测试、可以从文件加载。

---

## 42.5 核心实现（逐行解释）

这一节把 `step3_prompts.py` 里最关键的 15 行逐行拆开。

```python
chat = ChatPromptTemplate.from_messages([          # ①
    ("system", "你是{guild}的助手，回答不超过{max_words}字。"),   # ②
    MessagesPlaceholder("history"),                 # ③
    ("human", "{question}"),                        # ④
])

msgs = chat.format_messages(                        # ⑤
    guild="售后", max_words="50",                   # ⑥
    history=[HumanMessage("我上周买的"), AIMessage("好的，请问什么问题？")],
    question="耳机没声了",
)
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | `from_messages` 接受"元组列表"或 Message 对象 | 用字符串列表也能跑，但角色写错不报错 |
| ② | `("system", ...)` 就是一条 SystemMessage | 把身份写进 human 里，模型会当成"用户在自称" |
| ③ | 占位符：**渲染时把整个列表原样插进去** | 手工 `for m in history: msgs.append(m)`，容易漏 |
| ④ | `{question}` 是变量，渲染时替换 | 变量名写错，`format` 会抛 `KeyError`（比静默好） |
| ⑤ | `format_messages` 返回 **list[BaseMessage]** | 用 `.format()` 拿到字符串，还得自己再包一层 |
| ⑥ | 关键字参数就是变量 | 传多余变量会被忽略（不算错，但说明有 bug） |

**三个设计取舍（为什么这么写）**

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 提示词放代码里 vs 放文件 | **小项目放代码，大项目放文件**（`load_prompt`） | 全放代码：改一个字要发版；全放文件：diff 不好 review |
| 用 `MessagesPlaceholder` vs 手拼 | **用占位符** | 手拼容易忘记把 `tool_calls` 一起传，导致 400 |
| 变量名 vs 位置参数 | **变量名（关键字参数）** | 位置参数一旦顺序变，全员静默错位 |

### ⚠️ 一个必须知道的坑：Windows 上从文件加载会 UnicodeDecodeError

`step3` 的 ⑤ 里，我们写了一个 `templates/review.json` 再用 `load_prompt` 读它。第一版**直接崩了**：

```
UnicodeDecodeError: 'gbk' codec can't decode byte 0xa7 in position 91: illegal multibyte sequence
```

原因：Windows 上 Python 的**默认文件编码是 GBK**，而 `load_prompt` 不传 `encoding` 时用系统默认。

修法：

```python
loaded = load_prompt(TEMPLATE_FILE, encoding="utf-8")   # ← 必须显式传
```

而且 `load_prompt` 在 1.x 已经**标记弃用**：

```
LangChainDeprecationWarning: The function `load_prompt` was deprecated in LangChain 1.2.21 ...
  Use `load`/`loads` from `langchain_core.load` instead.
```

生产做法：**别用 `load_prompt`**，自己 3 行读完更可控，也不受版本影响：

```python
import json
from langchain_core.prompts import ChatPromptTemplate

cfg = json.loads(Path("prompts/refund.json").read_text(encoding="utf-8"))
prompt = ChatPromptTemplate.from_messages(cfg["messages"])
```

---

## 42.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lc/ch42/step2_packages.py` + `step3_prompts.py`

### 问题 ①：模型返回了，我该读哪个字段？

```python
msg = llm.invoke("退款多久到账？")
text = msg.content              # ← 唯一的正确答案
# 不要：
# str(msg)                      ← 带 additional_kwargs，是调试表示
# msg.response_metadata["..."]  ← 里面是厂商原始返回，字段名各家不同
```

**结论：`.content` 取文字，`.usage_metadata` 取 token，`.response_metadata` 只用来排错。**

### 问题 ②：怎么换厂商？

```python
from langchain.chat_models import init_chat_model

# 想换厂商？改这两个字符串，别的都不动
llm = init_chat_model("gpt-4o-mini", model_provider="openai", temperature=0)
# llm = init_chat_model("claude-sonnet-4", model_provider="anthropic")
# llm = init_chat_model("qwen2.5:7b",  model_provider="ollama")
```

**结论：业务代码里永远不要 `from langchain_openai import ChatOpenAI`，用 `init_chat_model` 收口。**

### 问题 ③：怎么确认提示词没写错？

```python
t = ChatPromptTemplate.from_messages([("human", "你好{name}")])
assert set(t.input_variables) == {"name"}      # ← 一行断言，进 CI
```

**结论：提示词的变量集合是可以断言的。把它写进测试，比"上线后发现变量名拼错"便宜一万倍。**

### 🎯 到这里，你已经掌握了 LangChain 的"输入层"

回顾一下你用了什么：

| 能力 | 在哪一节 |
|---|---|
| 消息对象与四类角色 | 42.3 |
| `content` / `usage_metadata` / `tool_calls` | 42.3 |
| 包结构与排错三问 | 42.4 step2 |
| `init_chat_model` 多 provider | 42.4 step2 |
| 三种提示词模板 | 42.4 step3 |
| 从文件加载 + 编码坑 | 42.5 |

**剩下的都是"把输出变成数据"（第 43 章）和"把东西接起来"（LCEL，第 43 章）。**

---

## 42.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数，观察变化

把 `step1_message_io.py` 里 `usage_metadata` 的 `output_tokens` 从 13 改成 300，重跑。

**验收标准**：你需要能说出"为什么这个改动不会让程序报错，但会让成本计算完全失真"——因为它只是一个字段，没有校验。

### 练习 2（20 分钟）：接到你自己的项目上

把你项目里**任意一处** `f"你是XX助手，请..."` 改成 `ChatPromptTemplate`。

**最低要求清单**：
- [ ] 变量全部提取成 `{}`
- [ ] 用 `format_messages` 而不是 `format`
- [ ] 加一条断言：`set(t.input_variables) == {...}`
- [ ] 重跑你的测试，输出与改动前**一致**

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：把 system 写成 human。**

```python
# 改前
("system", "你是售后助手，不能承诺赔偿金额。"),
# 改后
("human", "你是售后助手，不能承诺赔偿金额。"),
```

重跑 `step3`，观察消息列表第 1 条的类型变化。结论：**模型会把这句话当成"用户在要求它扮演"，约束力显著下降。**（第 3 章讲过：system 的权重高于 human。）

**实验 B：故意拼错变量名。**

```python
t = ChatPromptTemplate.from_template("你好{name}")
t.format(nmae="张三")
```

观察：抛 `KeyError: 'name'`。结论：**这个错误至少是"当场炸"。真正危险的是变量有默认值兜底成空串——那时模型只会"答得怪"，不会报错。**

**实验 C：多模态消息直接用 f-string。**

```python
from langchain_core.messages import AIMessage
m = AIMessage(content=[{"type": "text", "text": "看这张图"}])
print(f"回复：{m.content}")
```

观察输出。结论：**用户会看到 `[{'type': 'text', ...}]`。** 一定要写 `text_of()` 这类提取函数（见 42.8 第 1 条）。

---

## 42.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 输出里出现 `[{'type': 'text'...}]` | 直接对 `content` 做 f-string | 写一个 `text_of(msg)`：字符串直接返回，列表只取 `type=="text"` 的 `text` 字段 |
| `ModuleNotFoundError: langchain.memory` | 0.x 写法，1.x 已移除 | 用 checkpointer（第 49 章）+ `SummarizationMiddleware` |
| `ModuleNotFoundError: langchain.chains` | 同上 | `prompt \| model \| parser`（LCEL，第 43 章） |
| `ImportError: cannot import name 'ChatOpenAI'` | 没装 `langchain-openai` | `pip install langchain-openai==1.7.2` |
| `ValueError: Unsupported provider='xxx'` | provider 名拼错 | 用错误信息里列出的合法值 |
| `OpenAIError: Missing credentials` | 没设 `OPENAI_API_KEY`，或用了离线脚本 | 设环境变量；离线脚本改用 `ScriptedChat` |
| `KeyError: 'name'`（渲染提示词时） | 变量名不一致 | 断言 `input_variables` |
| `UnicodeDecodeError: 'gbk' codec` | Windows 默认编码 + 读文件没传 `encoding` | 所有 `read_text` / `open` 显式 `encoding="utf-8"` |
| `StopIteration`（用假模型时） | 假模型剧本是迭代器，用完了 | 每次新建剧本（`scripted(...)`） |
| `LangChainDeprecationWarning: load_prompt` | 1.x 已弃用 | 自己 `json.load` 或 `langchain_core.load` |

---

## 42.9 章末自测

合上书，用自己的话回答下面四题。**答对 3 题算过关。**

**Q1** `AIMessage` 里，文字在哪个字段？token 花在哪个字段？

<details>
<summary>提示</summary>
文字在 `.content`；token 在 `.usage_metadata`（里面有 input/output/total）。
不要用 `str(msg)`。
</details>

**Q2** 为什么 1.x 要把 0.x 的一个大包拆成 `core` + `langchain` + 一堆 provider 包？说一个好处。

<details>
<summary>提示</summary>
安装体积：不用为了用一个模型把 40 家厂商的 SDK 全装进来。
另外：接口（core）和实现（provider）分离，换厂商不影响业务代码。
</details>

**Q3** `langchain.memory` 为什么被删了？现在用什么替代？

<details>
<summary>提示</summary>
因为"记住对话"本质是**状态管理**：存在哪、按什么粒度分、怎么裁剪。
这些是运行时的事，交给 LangGraph 的 checkpointer + `thread_id`。
</details>

**Q4** `content` 可能是 list，这对你的代码有什么要求？

<details>
<summary>提示</summary>
凡是要把 `content` 当字符串用的地方，都要先 `text_of()` 判断类型。
否则多模态消息会让你输出一堆 dict。
</details>

**加分题（答对说明你真的懂了）**

> 你同事说："我用 f-string 拼提示词十年了，也没出事，为什么要用 `ChatPromptTemplate`？"

参考思路：**在于"提示词是不是资产"。** f-string 写在业务流程里，改一个字要发版、无法单独测试、无法做 A/B、无法按租户切换。
`ChatPromptTemplate` 是对象：可以断言变量、可以从文件加载、可以 `with_config` 换版本（第 43 章）、可以统计每个版本的通过率（第 53 章）。
**"没出事"不等于"没成本"**——只是成本被摊在了每次改动里。

---

## 42.10 可选补课：本地 Ollama 与私有化网关

> ⚠️ **这一节可以先跳过。** 等你真的要本地跑模型时再看。不看这一节，你已经能用 `init_chat_model` 接任何厂商。

### 接 Ollama（本地模型）

两条路，推荐第二条：

```python
# 路 1：装 langchain-ollama
from langchain_ollama import ChatOllama
llm = ChatOllama(model="qwen2.5:7b", temperature=0)

# 路 2：走 OpenAI 兼容协议（不用多装包，很多国产网关也这么接）
import os
os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"
os.environ["OPENAI_API_KEY"] = "ollama"        # 随便填，本地不校验
llm = init_chat_model("qwen2.5:7b", model_provider="openai")
```

**局限要知道**：本地小模型的 `tool_calls` 支持常常不完整，Agent 场景下会"调工具调一半"。
先跑通"单轮问答"，再试 Agent。

### 私有化网关的通用写法

```python
os.environ["OPENAI_BASE_URL"] = "https://your-gateway.internal/v1"
llm = init_chat_model(model_name, model_provider="openai", temperature=0, timeout=30, max_retries=2)
```

**必须设置的两个参数**：`timeout`（默认可能很长）和 `max_retries`（默认可能不重试）。见第 35 章延迟工程。

### 参考

> 📎 基础教程里有更细的 Ollama 部署（下载、模型列表、显存要求）：
> 第 12 章《Ollama 本地部署与调用》—— https://github.com/didilili/ai-agents-from-zero
> 本书只讲"接进来怎么写"，不讲"怎么装 Ollama"。

---

## 42.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 离线假模型 | `code/framework/lc/_fake.py` | **第 42–49 章全部复用**（`ScriptedChat` / `EchoEmbeddings` / `run_with_llm`） |
| 消息与返回对象 | `code/framework/lc/ch42/step1_message_io.py` | 第 43、45、49 章都靠它读结果 |
| 包结构与多 provider | `code/framework/lc/ch42/step2_packages.py` | 第 45 章 `create_agent` 的模型入口 |
| 提示词模板 | `code/framework/lc/ch42/step3_prompts.py` | 第 43 章（解析器）、第 53 章（提示词版本化） |

`_fake.py` 说明：它对应第 45 章"企业级封装"的最低级形态——**把模型创建收口到一个函数**。
`run_with_llm()` 是给 `demo_*_llm.py` 用的守卫：没 key 就打印提示并退出 0，不污染 CI。

---

## 42.12 ✅ 验收

跑完这三个脚本，检查五件事：

**① 你能说出返回对象的四个字段**

`step1` ① 的输出里应该有 `content` / `usage_metadata` / `response_metadata` / `tool_calls`。
不看笔记，说出每个字段"什么时候该用"。

**② 你能回答"这个类属于哪一层"**

`step2` ① 打印了 7 个包的安装状态。自测：`InMemoryVectorStore` 属于哪个包？`create_agent` 呢？`ChatOpenAI` 呢？

<details><summary>答案</summary>core / langchain / langchain-openai</details>

**③ 你能说出拼接提示词的三种模板**

`step3` 输出里出现了 `PromptTemplate`、`ChatPromptTemplate`、`FewShotChatPromptTemplate`，以及一个 `MessagesPlaceholder`。
说出"什么时候用哪种"。

**④ 你能解释 Windows 上那个编码坑**

`step3` ⑤ 会打印一条关于 `load_prompt` 弃用的提示。
不看笔记，说出"为什么第一版会 UnicodeDecodeError，怎么修"。

**⑤ 一个数字**

`step1` ① 里 `usage_metadata` 显示 `input_tokens=68, output_tokens=13`。

**用这两个数字算一件事**：如果按 ¥0.001/1k input、¥0.004/1k output 计（第 34 章的口径），
这次调用花了多少钱？

<details><summary>答案</summary>

`68/1000 × 0.001 + 13/1000 × 0.004 = 0.000068 + 0.000052 = ¥0.00012`

→ 约 **0.012 分**。这就是"一句话问答"的真实成本量级。
你算出来了，就说明你理解了"input 和 output 的单价不同"——这正是第 34 章"省 token ≠ 省钱"的起点。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 43 章 输出解析与 LCEL。
模型总会多说一句"好的，这是结果："，然后才是 JSON。下一章教你把"模型说的话"变成程序能用的**对象**，
以及怎么用 `|` 把提示词、模型、解析器串成一条**能重试、能降级、能流式**的链。

> 📎 参考：本章对应基础教程第 9 章《LangChain 概述与架构》、第 10 章《快速上手与 HelloWorld》、
> 第 11 章《Model I/O 与模型接入》、第 13 章《提示词与消息模板》的知识点，
> 但**叙述顺序完全重写**：先"旧写法为什么不能用"，再"消息是什么"，最后"怎么换厂商"。
