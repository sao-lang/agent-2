# 第 11 章 · LangChain 的工具定义与绑定

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./docs/INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F6 工具定义与注入 —— @tool、BaseTool、bind_tools 与三种注入（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：第 6 章手写的那份 `tools` 字典与往返，换成框架以后哪几段被接走、哪几段仍在调用方手里；函数怎么变成请求里那段 `parameters`；一次响应给出多个调用时按什么顺序执行；注入的参数为什么不进 schema；异常、收窄、模拟各落在哪个中间件上
> - **示例目录**：`code/knowledge/ch11_lc_tools/`
> - **读完应当能回答**：给一个工具函数和一次 `bind_tools`，你能说出请求体里 `tools` 与 `tool_choice` 长什么样、工具抛异常时消息怎么回到模型，以及哪一件事框架仍然没替你做

---

## 目录

[工具定义三写法](#工具定义三写法)\
[参数模型与校验](#参数模型与校验)\
[绑定与请求体](#绑定与请求体)\
[一次响应里的多个调用](#一次响应里的多个调用)\
[注入参数](#注入参数)\
[失败、重试与回灌](#失败重试与回灌)\
[工具收窄与模拟](#工具收窄与模拟)\
[这一章建立的 7 件事](#这一章建立的-7-件事)

本章 API 以本机 **LangChain 1.4.7**（`langchain-core` 1.7.0）为准。例子没有 API key，`ChatOpenAI` 换成了 `httpx.MockTransport`，请求照常编码，响应来自写死的脚本：原理演示，不是模型实测。换真实服务时把 `scripted_chat(respond)` 换成 `ChatOpenAI(...)`，其余代码不动；消息对象见第 9 章。

---

## 工具定义三写法

第 6 章那一次工具往返，在调用方这一侧切得出四段：编码、解析、拼装、配对。框架接走前三段，定义从函数长出来，响应解析成消息对象，结果用 `ToolMessage` 携带 `tool_call_id`；执行没有接走，配对的选择仍然在调用方。根因是同一个工具存在两份描述：字典与函数，两者之间没有机制保证一致。函数加参数而字典不动，模型就永远不填它，实现拿到默认值，行为悄悄变了，没有报错。第 6 章的 `tool_audit.py` 写静态检查比对声明与实现，就是因为这个分叉只能靠外部脚本发现。框架版让参数名、类型、默认值、说明全部来自函数签名与 pydantic 模型，改函数等于改 schema。三种写法产出的是同一个对象类型，区别只在参数说明写在哪：`define_tools.py` 用三种写法定义同一个 `get_order`，把四个属性和最终的 `parameters` 一起打出来。

```python
class OrderQuery(BaseModel):
    """get_order 的参数。字段说明原样进 schema，也原样进请求。"""

    order_id: str = Field(description="订单号，例如 A1001")
    detail: bool = Field(default=False, description="是否返回明细")


@tool("get_order", args_schema=OrderQuery)
def get_order(order_id: str, detail: bool = False) -> str:
    """查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。只查本账号订单。"""
    return fetch(order_id, detail)


class GetOrderTool(BaseTool):
    """子类写法：名字、说明、参数模型都是类属性，执行逻辑在 `_run`。"""

    name: str = "get_order"
    description: str = DESCRIPTION
    args_schema: Type[BaseModel] = OrderQuery

    def _run(self, order_id: str, detail: bool = False) -> str:
        return fetch(order_id, detail)


structured = StructuredTool.from_function(
    func=fetch,
    name="get_order",
    description=DESCRIPTION,
    args_schema=OrderQuery,
)
```

装饰器写法把 docstring 当 `description`，子类写法把三样写成类属性、执行逻辑放进 `_run`，`from_function` 把函数、名字、说明、参数模型当四个关键字传进去，三种写法的输出完全一致：

```
=== 一、三个属性与一份 parameters ===
  装饰器 @tool(args_schema=OrderQuery)
    name        = get_order
    description = 查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。只查本账号订单。
    args        = {"order_id": {"description": "订单号，例如 A1001", "title": "Order Id", "type": "string"}, "detail": {"default": false, "description": "是否返回明细", "title": "Detail", "type": "boolean"}}
    args_schema = OrderQuery
    进请求的 parameters = {"properties": {"order_id": {"description": "订单号，例如 A1001", "type": "string"}, "detail": {"default": false, "description": "是否返回明细", "type": "boolean"}}, "required": ["order_id"], "type": "object"}
  BaseTool 子类
    name        = get_order
    description = 查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。只查本账号订单。
    args        = {"order_id": {"description": "订单号，例如 A1001", "title": "Order Id", "type": "string"}, "detail": {"default": false, "description": "是否返回明细", "title": "Detail", "type": "boolean"}}
    args_schema = OrderQuery
    进请求的 parameters = {"properties": {"order_id": {"description": "订单号，例如 A1001", "type": "string"}, "detail": {"default": false, "description": "是否返回明细", "type": "boolean"}}, "required": ["order_id"], "type": "object"}
  StructuredTool.from_function(args_schema=OrderQuery)
    name        = get_order
    description = 查询订单状态。返回 JSON：{"status": "已签收", "signed_days_ago": 3}。只查本账号订单。
    args        = {"order_id": {"description": "订单号，例如 A1001", "title": "Order Id", "type": "string"}, "detail": {"default": false, "description": "是否返回明细", "title": "Detail", "type": "boolean"}}
    args_schema = OrderQuery
    进请求的 parameters = {"properties": {"order_id": {"description": "订单号，例如 A1001", "type": "string"}, "detail": {"default": false, "description": "是否返回明细", "type": "boolean"}}, "required": ["order_id"], "type": "object"}

=== 二、三份定义编码出来的 tools 项逐字相同 ===
  互不相同的份数 = 1（1 表示三份完全相同）
  每份的长度     = 492 字符
  调用结果       = {"status": "已签收", "signed_days_ago": 3, "detail": false}
```

三份定义编出来的东西逐字相同，三种写法没有能力差别，只有接线位置的差别，选法是这个工具的状态放在哪：

| 工具的样子 | 用哪个 | 原因 |
|---|---|---|
| 一个纯函数，参数来自模型 | 装饰器 | 说明写在 docstring 里，不用重复一遍 |
| 需要持有连接、配置、重试策略 | `BaseTool` 子类 | 这些东西是类属性或构造参数，不经过模型 |
| 已有函数，只想给它加名字与说明 | `StructuredTool.from_function` | 不改函数定义，包装一层就多一个工具 |
| 参数说明要写得很细（格式、枚举、边界） | 三者都行，都传 `args_schema` | 细说明放 pydantic 的 `Field` 里最省事 |

## 参数模型与校验

`args` 里每个字段带一个 `title`，进请求的 `parameters` 里没有，差别来自中间那次编码：`convert_to_openai_tool` 只保留 `type`、`description`、`default`、`required`。想让某个字段出现在请求里，必须落在 pydantic 的字段声明上；想让一个说明不可见，得改 `description` 或删掉字段。

`args_schema` 不只是给模型看的说明书，也是执行前的校验器。三种坏参数的表现，输出见 `code/knowledge/ch11_lc_tools/define_tools.py`：

```
=== 三、参数校验发生在本地，不花一次调用 ===
  缺必填 -> ValidationError：Field required [type=missing, input_value={}, input_type=dict]
  类型错 -> ValidationError：Input should be a valid string [type=string_type, input_value=1001, input_type=int]
  多余键 -> {"status": "已签收", "signed_days_ago": 3, "detail": false}
```

前两条是好事：参数名写错、把字符串写成数字，都在本地被拦住，成本是零次调用。第三条要留意：多余的键被静默丢弃，不报错，所以只该依赖缺必填会报错。模型把参数名写成近义词时，报出来的也是缺必填；看到缺必填而模型坚称自己填了，先怀疑键名。

### 报错的时机

还有两处错误要到调用时才出现。第一处是没有 docstring 也没给 `description`，装饰器要求两者有其一，输出见 `code/knowledge/ch11_lc_tools/define_tools.py`：

```
=== 四、两处不在定义时出现的报错 ===
  没有 docstring 也没有 description -> ValueError: Function must have a docstring if description not provided.
```

批量生成工具时最容易撞上：用循环造五个工具，函数体是同一个闭包，没有天然的 docstring，必须显式传 `description`。它是必须有的字段，不是注释。

第二处是 `args_schema` 与函数签名对不上：定义照样成功，`parameters` 也照样编得出来，等到执行才报：

```
  args_schema 与签名不符 -> TypeError: fetch() got an unexpected keyword argument 'city'
```

模型按 `args_schema` 填了 `city`，函数要的是 `order_id`，`_run` 直接把关键字参数转给函数，于是炸在调用点上。两份东西仍然可能分叉，只是分叉点从字典与函数挪到了模型与签名；修法是把参数模型当唯一来源，签名照着模型写。

## 绑定与请求体

`bind_tools(tools, tool_choice=...)` 做两件事：把工具列表编成请求体的 `tools` 字段，把 `tool_choice` 编进去。它不改变消息、不改模型、不发请求，返回的是一个绑定了参数的模型对象，实际发请求还是 `invoke`，代码见 `code/knowledge/ch11_lc_tools/bind_and_call.py` 的 `one_shot()`。它也不执行任何东西：工具被调用几次全部发生在调用方那一行。

```python
def one_shot(choice: object) -> None:
    """只关心请求体：`tool_choice` 的各种取值编成什么。`None` 表示不传。"""

    def respond(index: int, body: dict) -> dict:
        SENT.append(body)
        return chat_completion(content="好的，")

    model = scripted_chat(respond)
    if choice is None:
        model.bind_tools(TOOLS).invoke([HumanMessage("A1001 还能退吗？")])
    else:
        model.bind_tools(TOOLS, tool_choice=choice).invoke([HumanMessage("A1001 还能退吗？")])
    wire = SENT[-1]
    encoded = json.dumps(wire["tool_choice"], ensure_ascii=False) if "tool_choice" in wire else "（请求体里没有这个键）"
    print(f"  tool_choice={choice!r:16} -> {encoded}")
```

六种取值编出来的东西：

```
=== 一、tool_choice 的各种取值编进请求的样子 ===
  tool_choice=None             -> （请求体里没有这个键）
  tool_choice='auto'           -> "auto"
  tool_choice='none'           -> "none"
  tool_choice='required'       -> "required"
  tool_choice='any'            -> "required"
  tool_choice='get_order'      -> {"type": "function", "function": {"name": "get_order"}}
```

第一行是最容易忽略的一条：不传 `tool_choice` 时请求体里根本没有这个键，不是 `"auto"`。两者行为由服务端决定，多数实现把缺省当作 `auto`，但这是约定不是协议保证，要行为确定就显式写。`'any'` 与 `'required'` 编出来是同一个值，直接给工具名的写法被转成 `{"type": "function", "function": {"name": "get_order"}}`。几种取值用途各不相同：

| 取值 | 约束什么 | 用在哪 |
|---|---|---|
| 不传 / `auto` | 模型自己决定调不调 | 常规 agent 循环 |
| `none` | 不许调，但仍把工具定义编进请求 | 只要正文、又要让模型知道有哪些工具 |
| `required` | 必须调，调哪个不限 | 强制先取一次数据再回答 |
| 指定名字 | 必须调这一个 | 第 4 章那种"把结果按格式交回来"的提交工具 |

最后一行在第 4 章出现过：把输出结构声明成一个工具，用 `tool_choice` 强制必须调它。同一个机制在这里的用途是这一步必须查订单、不许直接回答，模型的选择空间从 N 个工具缩到 1 个。

### 另外两个参数编在哪

`bind_tools` 还有两个参数不在 `tool_choice` 上，输出见 `code/knowledge/ch11_lc_tools/bind_and_call.py`：

```
=== 二、strict 与 parallel_tool_calls 的位置 ===
  不传                           顶层键=无  function 的键=['description', 'name', 'parameters']
  strict=True                  顶层键=无  function 的键=['description', 'name', 'parameters', 'strict']
  parallel_tool_calls=False    顶层键={'parallel_tool_calls': False}  function 的键=['description', 'name', 'parameters']
```

`strict=True` 加在每个工具自己的 `function` 里，`parallel_tool_calls` 加在请求体顶层。`strict` 要求服务端按 schema 严格校验生成的参数，适合字段名不能错的工具；`parallel_tool_calls=False` 要求一次只给一个调用。两者都不改善参数语义：`strict` 保证 `order_id` 是字符串，保证不了它属于当前用户的订单；关掉并行让执行次数可预期，代价是同一个任务多跑几轮。

## 一次响应里的多个调用

模型一步里想做的事不止一件时，一次响应会带多个 `tool_calls`。`code/knowledge/ch11_lc_tools/bind_and_call.py` 让响应带三个调用，然后逐个执行：

```python
def execute_all(first: object, tools: list[BaseTool]) -> tuple[list[ToolMessage], float]:
    """把一条响应要的调用逐个执行。返回 (ToolMessage 列表, 执行耗时)。"""
    by_name: dict[str, BaseTool] = {t.name: t for t in tools}
    started = time.perf_counter()
    results: list[ToolMessage] = [by_name[call["name"]].invoke(call) for call in first.tool_calls]
    elapsed = time.perf_counter() - started
    return results, elapsed
```

执行落在 `by_name[call["name"]].invoke(call)` 这一行：把整个 `call` 字典交给工具，拿回来的直接是一条 `ToolMessage`，`tool_call_id` 已经填好。第 6 章要自己写三段字典，这里一个 `invoke` 就够，而且不可能漏 `id`。

```
=== 三、一次响应里的三个调用 ===
  第 1 次响应的 content = ''
  一次给出 3 个调用：
    id=call_a   name=get_order    args={'order_id': 'A1001'}
    id=call_b   name=get_order    args={'order_id': 'A1002'}
    id=call_c   name=get_weather  args={'city': '杭州'}
  args 已经是对象，不是 JSON 字符串 = dict

  逐个执行，拿回的是 ToolMessage：
    tool_call_id=call_a   status=success  content={"status": "已签收", "signed_days_ago": 3}
    tool_call_id=call_b   status=success  content={"status": "已签收", "signed_days_ago": 3}
    tool_call_id=call_c   status=success  content={"temp": 24, "unit": "c"}
```

第一行值得对照第 6 章：手写版里 `content` 是 `None`，框架版是空字符串。`args` 已是 `dict` 而不是 JSON 字符串，这是解析被接走的标志：手写版 `json.loads` 抛异常的分支，在框架版里变成了 `invalid_tool_calls`。

### 顺序执行的证据

三个调用各睡 0.2 秒，一次响应里的三个调用串起来跑，总耗时 0.60 秒，输出见 `code/knowledge/ch11_lc_tools/bind_and_call.py`：

```
  3 次调用各睡 0.2 秒，总耗时 0.60 秒  <- 顺序执行，不是并发
```

如果是并发，总耗时应该在 0.2 秒附近。多个调用是一次说出来的，不是同时执行的，顺序由执行这一侧的代码决定；要真并发得自己用线程池，代价是同一次响应里的两个写操作可能互相覆盖。

### 返回值的两段

第 6 章 4.2 分过工具返回值的两难：返回结论，模型会把结论当依据；返回全量记录，白占窗口。框架给了一个显式的位置：`response_format="content_and_artifact"`，工具返回二元组，第一段进上下文，第二段留在消息对象上。

```python
@tool("get_order", response_format="content_and_artifact")
def get_order(order_id: str) -> tuple[str, dict]:
    """查询订单状态。返回 JSON：{"status": ..., "signed_days_ago": ...}。"""
    summary = {"status": FULL_RECORD["status"], "signed_days_ago": FULL_RECORD["signed_days_ago"]}
    return json.dumps(summary, ensure_ascii=False), FULL_RECORD
```

```
=== 一、一条 ToolMessage 里的两段 ===
  type     = ToolMessage
  content  = {"status": "已签收", "signed_days_ago": 3}
  artifact = {'status': '已签收', 'signed_days_ago': 3, 'items': [{'sku': 'X1', 'qty': 2}, {'sku': 'X2', 'qty': 1}], 'audit': {'operator': 'w_17', 'at': '2025-06-02T09:14:00'}}
  content 长度 = 39 字符，artifact 长度 = 160 字符

=== 二、进请求的那条 tool 消息 ===
  {"content": "{\"status\": \"已签收\", \"signed_days_ago\": 3}", "role": "tool", "tool_call_id": "call_a"}
  'items' 出现在请求里 = False
  'audit' 出现在请求里 = False
```

一条有明细、有审计字段的记录，进上下文的只有 39 个字符，160 个字符留在 `artifact` 上。这就是第 6 章那句话的框架版：给事实，不给结论。代价是这个字段不在消息里，序列化、检查点、跨进程传递都要确认它还在。

### 与手写版的对照

| 环节 | 第 6 章手写 | 框架版 | 谁负责 |
|---|---|---|---|
| schema | 手写 dict，与函数两份 | 从函数或 pydantic 生成 | 框架 |
| 编码进请求 | 自己塞 `tools` | `bind_tools` | 框架 |
| 解析 `arguments` | `json.loads` + 三个 `except` | `tool_calls[].args` 已是 dict | 框架 |
| 参数校验 | 自己写 | `args_schema` 校验，失败转 error `ToolMessage` | 框架 |
| 执行 | 自己写 `TOOL_IMPL[name](**args)` | 自己写（`tool.invoke(call)`） | **调用方** |
| 结果配对 | 自己填 `tool_call_id` | `invoke(call)` 自动填 | 框架 |
| 重试 | 自己写 | `ToolRetryMiddleware` | 框架（可选） |
| 幂等 | 自己去重表 | **没有** | **调用方** |

最后一行是这一章最该带走的一格。第 6 章 5.1 讲过有副作用的工具被重放，那是幂等键的问题；下一节会看到，重试恰恰会放大这一类问题。

## 注入参数

有些参数不该由模型填：当前用户是谁、这次的调用 id、持久化 store、可用工具清单。让模型填等于让它猜，猜错就是越权。框架在工具签名里声明一个特殊参数，执行时由运行环境填进去，不进 `parameters`。`inject.py` 定义四个这样的工具，打请求体确认模型看不到它们：

```
=== 一、进请求的 parameters 里没有注入参数 ===
  get_my_order   parameters={"properties": {"order_id": {"type": "string"}}, "required": ["order_id"], "type": "object"}
  who_am_i       parameters={"properties": {}, "type": "object"}
  bump_counter   parameters={"properties": {"key": {"type": "string"}}, "required": ["key"], "type": "object"}
  mark_handled   parameters={"properties": {"order_id": {"type": "string"}}, "required": ["order_id"], "type": "object"}

=== 二、执行时拿到的注入值 ===
  call_a   {"user_id": "u_42", "order_id": "A1001", "status": "已签收"}
  call_b   {"user_id": "u_42", "tool_call_id": "call_b", "tools": ["get_my_order", "who_am_i", "bump_counter", "mark_handled"]}
  call_c   {"key": "refund", "n": 1}
  call_d   {"key": "refund", "n": 2}
  call_e   {"order_id": "A1001", "tool_call_id": "call_e"}

=== 三、store 里留下的计数 === {'n': 2}
=== 四、state 的键（模型没有写进去的能力）=== ['user_id']
```

`who_am_i` 的 `parameters` 是空对象，它一个参数也不需要模型填，但执行时拿到了 `user_id`、`tool_call_id` 和全部工具名。三种注入的写法：

```python
@tool("get_my_order")
def get_my_order(order_id: str, state: Annotated[dict, InjectedState]) -> str:
    """查询当前用户自己的订单。用户身份由 state 提供，模型不需要也不应该填。"""
    return json.dumps({"user_id": state.get("user_id"), "order_id": order_id,
                       "status": "已签收"}, ensure_ascii=False)


@tool("who_am_i")
def who_am_i(runtime: ToolRuntime) -> str:
    """返回本次执行拿到的 state、tool_call_id 与可用工具名。"""
    return json.dumps({"user_id": runtime.state.get("user_id"),
                       "tool_call_id": runtime.tool_call_id,
                       "tools": [t.name for t in runtime.tools]}, ensure_ascii=False)


@tool("bump_counter")
def bump_counter(key: str, store: Annotated[Any, InjectedStore]) -> str:
    """把一个计数加一。计数存在 store 里，模型不需要也不应该提供 store。"""
    item = store.get(("counters",), key)
    n = (item.value["n"] if item else 0) + 1
    store.put(("counters",), key, {"n": n})
    return json.dumps({"key": key, "n": n}, ensure_ascii=False)


@tool("mark_handled")
def mark_handled(order_id: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
    """返回这次调用自己的 id。要自己造幂等键时，从它派生。"""
    return json.dumps({"order_id": order_id, "tool_call_id": tool_call_id}, ensure_ascii=False)
```

四个标记的导入位置都是 `langchain.tools`（本机 1.4.7 实测）：`InjectedState`、`InjectedStore`、`InjectedToolCallId`、`ToolRuntime`。它们底层的实现类在 `langgraph.prebuilt`，`langchain_core.tools` 里没有这几个名字，按习惯去找会拿到 `ImportError`，这是从 0.x 迁过来时最常见的报错。

### 四个标记的分工

| 标记 | 填进去的是什么 | 用在哪 |
|---|---|---|
| `InjectedState` | 整份 state 字典 | 需要当前用户、会话、任务上下文的读操作 |
| `InjectedStore` | 跨会话的长期存储 | 计数、偏好、缓存这类不该进 state 的东西 |
| `InjectedToolCallId` | 只要这次的调用 id | 工具要自己生成幂等键，或者返回值里要带凭据 |
| `ToolRuntime` | 一个对象：`state`/`context`/`config`/`store`/`tool_call_id`/`tools`/`stream_writer` | 想一次拿全，或者需要其中三样以上 |

前三个是 `Annotated[T, 标记]` 的写法，`ToolRuntime` 只要参数名是 `runtime` 且类型标对就会被识别。判据：只要一个值，用前三个里对应的那个；要三样以上，用 `ToolRuntime`。

### 两份存储的分工

第三段的计数从 1 变到 2，两个调用在同一次响应里顺序执行，第一个写进去，第二个读到了，这是顺序执行带来的，不是 store 的保证。换成并发，两个可能都读到 0、都写 1，最终计数是 1 而不是 2。判据只有一条：这份数据是不是只属于这一次会话？走完就丢的放 state，要跨会话留下的放 store。第四段的输出只列了 `user_id`，`messages` 被排除在外：模型能把内容写进对话，不能把字段写进 state。工具拿到的身份不该来自模型。

## 失败、重试与回灌

这一节的输出来自 `retry_error.py`。第 6 章手写的 `execute` 有三个 `except`：参数不是合法 JSON、工具名不存在、执行抛异常，都编成 `tool` 消息回灌。框架版拆成两层：参数与工具名在执行之前被拦下，执行期间的异常另有中间件管。先看没装中间件时会发生什么：

```
=== 一、不加中间件 ===
  没有中间件，工具抛 TimeoutError
    抛出 TimeoutError：上游网关超时（第 1 次）
    工具执行次数 = 1
```

异常一路冒到 `agent.invoke` 外面，整个运行中断。这与第 6 章手写版相反：手写版把所有异常都变成了回灌消息，而框架的默认值是中断。

### 重试的三个参数

`ToolRetryMiddleware` 的控制面是三个参数，代码在 `code/knowledge/ch11_lc_tools/retry_error.py` 里：

```python
ToolRetryMiddleware(max_retries=2,
                    retry_on=default_retry_on,
                    on_failure="continue",
                    backoff_factor=2.0,
                    initial_delay=1.0,
                    max_delay=60.0,
                    jitter=True)
```

`max_retries` 是重试次数，不是总次数：`max_retries=2` 意味着最多执行 3 次。`retry_on` 收异常类型元组或判断函数，默认对所有 `Exception` 返回 `True`。后三个参数是退避：第 n 次重试等 `initial_delay * backoff_factor ** (n-1)` 秒，加抖动，封顶 `max_delay`；本节把它设成 0.01 秒并关掉抖动，否则演示要十几秒。

```
=== 二、只加重试 ===
  max_retries=2，前两次失败第三次成功
    回灌 status=success content={"ok": true, "order_id": "A1001", "attempt": 3}
    工具执行次数 = 3
  max_retries=2，一直失败（默认 on_failure='continue'）
    回灌 status=error content=Tool 'charge_card' failed after 3 attempts with TimeoutError: 上游网关超时（第 3 次）. Please try again.
    工具执行次数 = 3
  max_retries=2，一直失败，on_failure 传函数
    回灌 status=error content=扣款失败：上游网关超时（第 3 次）；请不要重试同一订单。
    工具执行次数 = 3
```

第二段的失败文案是框架写死的英文句子，与中文对话混在一起；它说 `Please try again`，而这一次扣款已经失败三次，再试就是第四次扣款请求。第三段把 `on_failure` 换成函数，文案变成自己的，可以写清楚不要重试。

| 取值 | 重试耗尽之后 | 模型看到什么 | 适合 |
|---|---|---|---|
| `"continue"`（默认） | 编一条 error `ToolMessage` | 框架的英文失败文案 | 只读工具，失败了让模型换个办法 |
| `"error"` | 重新抛出，运行中断 | 什么都看不到 | 有副作用的工具，失败必须人工处理 |
| 函数 | 用函数返回值编 error `ToolMessage` | 你写的内容 | 想把错误语义写清楚，又不想中断 |

```
=== 七、retry_on 只重试值得重试的异常 ===
  默认 retry_on（所有 Exception）        工具执行 = 3
  retry_on=(TimeoutError,)         工具执行 = 1  抛出 ValueError
```

同一个工具抛 `ValueError`，默认配置下执行三次，每次都在同一个地方错；把 `retry_on` 收窄成 `(TimeoutError,)` 之后执行一次就抛出去。不会因为重试而改变结果的错误，重试三次只买到三倍日志和三倍时间。判据只有一条：这个错误再执行一次，结果可能不同吗？

### 错误回灌的中间件

`ToolErrorMiddleware` 只管一件事：把执行期间的异常转成 error `ToolMessage`。它不重试，参数只有 `on_error`、`aon_error`、`tools` 三个，其中 `aon_error` 是异步版，代码见 `code/knowledge/ch11_lc_tools/retry_error.py` 的 `on_error()`。

```python
def on_error(exc: Exception, request: ToolCallRequest) -> str:
    """把异常转成给模型看的内容。返回 None 表示交给上层抛。"""
    return f"{type(exc).__name__}：{exc}（工具 {request.tool_call['name']}）"
```

`on_error` 的签名是两个参数：异常与 `ToolCallRequest`，返回字符串就转成 `ToolMessage(status="error")`，返回 `None` 就让异常继续往上抛，这是一条明确的出口：处理哪些异常是逐类型选的。第 6 章手写版的三个 `except` 是全捕获，好处是对话不断，坏处是一个程序 bug 也会被当成工具结果喂给模型。

```
=== 三、只加错误回灌 ===
  ToolErrorMiddleware(on_error=...)
    回灌 status=error content=TimeoutError：上游网关超时（第 1 次）（工具 charge_card）
    工具执行次数 = 1
  on_error 返回 None，异常照样抛出去
    抛出 TimeoutError：上游网关超时（第 1 次）
    工具执行次数 = 1
```

### 两个中间件的里外顺序

重试与回灌一起用时顺序是固定的：重试在内，回灌在外。重试要先接到异常才会重试，所以贴着工具；回灌要接到重试也失败的异常，所以在更外层。中间件列表的顺序从外到内，回灌写在前面，输出见 `code/knowledge/ch11_lc_tools/retry_error.py`：

```
=== 四、两个一起用：重试在内，回灌在外 ===
  retry(on_failure='error') + ToolErrorMiddleware
    回灌 status=error content=TimeoutError：上游网关超时（第 2 次）（工具 charge_card）
    工具执行次数 = 2
```

`max_retries=1` 加上外层回灌，工具执行了 2 次，第 2 次的异常被回灌。注意重试中间件这里配的是 `on_failure="error"`：保持默认的 `"continue"` 时它自己就把异常编成消息了，外层根本收不到。两个中间件同时处理失败时，内层的赢，因为异常没有机会往外走。

### 工具自己的异常声明

中间件是从外面套上去的做法，还有一层在工具自己身上：`ToolException` 加 `handle_tool_error`。这个属性设在 `BaseTool` 子类上，异常一越过工具边界就变成消息，一个中间件都不用配，代码见 `code/knowledge/ch11_lc_tools/retry_error.py`。

```python
class FragileTool(BaseTool):
    name: str = "fragile"
    description: str = "查询库存。上游偶尔返回 409。"
    args_schema: Type[BaseModel] = FragileArgs
    handle_tool_error: bool | str = "库存不足，请换一个商品。"

    def _run(self, sku: str) -> str:
        raise ToolException(f"上游返回 409：{sku}")
```

```
=== 六、工具自己声明怎么处理 ToolException ===
    直接 invoke 拿到 ToolMessage status=error
    内容 = 库存不足，请换一个商品。
    回灌 status=error content=库存不足，请换一个商品。
```

行为与中间件版一致，差别在适用范围：`handle_tool_error` 只对这一种异常、这一个工具生效；中间件是全局的，能按 `tools=` 列表筛。只有 `ToolException` 会被它处理，`RuntimeError` 仍照常抛出。失败处理到这里有四层，从内到外：

| 层 | 管什么 | 谁配 |
|---|---|---|
| `args_schema` 校验 | 参数结构错 | 工具定义（自动） |
| `handle_tool_error` | 这个工具自己的 `ToolException` | 工具定义（可选） |
| `ToolRetryMiddleware` | 值得重试的失败，重试几次、退避多长 | agent 配置 |
| `ToolErrorMiddleware` | 重试耗尽后怎么告诉模型 | agent 配置 |

## 工具收窄与模拟

第 6 章算过一笔账：注册 40 个工具，每次请求都多带 40 段说明；另一个账是工具越多，不选任何工具这条路越容易被走。两个中间件分别处理这两笔账。

### 选择器多加一轮请求

`LLMToolSelectorMiddleware` 在主模型之前先发一次请求，让模型从全部工具里选出相关的几个，然后只把选中的工具编进主请求，输出见 `code/knowledge/ch11_lc_tools/narrow.py`：

```
=== 一、选择器：进请求的工具数 ===
  不装选择器
    请求总数 = 1（选择器 0 次 + 主模型 1 次）
    主模型收到的工具 = ['search_docs', 'search_code', 'get_order', 'send_sms', 'refund']
  LLMToolSelectorMiddleware(max_tools=2)
    请求总数 = 2（选择器 1 次 + 主模型 1 次）
    主模型收到的工具 = ['search_docs', 'search_code']
    选择器请求的键 = ['messages', 'model', 'response_format', 'stream']  tools 字段 = None
    选择器给出的候选 = ['search_docs', 'search_code', 'get_order', 'send_sms', 'refund']
  max_tools=2 + always_include=['refund']
    请求总数 = 2（选择器 1 次 + 主模型 1 次）
    主模型收到的工具 = ['search_docs', 'search_code', 'refund']
    选择器请求的键 = ['messages', 'model', 'response_format', 'stream']  tools 字段 = None
    选择器给出的候选 = ['search_docs', 'search_code', 'get_order', 'send_sms']
```

选择器那一轮自己不带 `tools`，它把工具名与说明放进 `response_format` 的 JSON Schema，取值为五个 `const`；省下的是主模型的 token，不是总量。`max_tools` 是上限不是下限，`always_include` 的工具直接进主请求并从候选里拿掉；`on_parsing_failure` 默认为 `"error"`，工具数没到那个量级时这一轮纯属白花。

### 调用上限

`ToolCallLimitMiddleware` 数工具调用次数，`run_limit` 是单次运行的，`thread_limit` 是跨运行累计的，需要带上 `thread_id`。看一个反复要查同一个工具的模型，跑 5 轮，输出见 `code/knowledge/ch11_lc_tools/narrow.py`：

```
=== 二、调用上限：拦的是执行，不是轮数 ===
  5 轮工具调用，不装中间件
    模型轮数 = 6  工具执行 = 5  被拦回的 ToolMessage = 0
    最后一条 = AIMessage '结束。'
  5 轮工具调用，run_limit=2
    模型轮数 = 6  工具执行 = 2  被拦回的 ToolMessage = 3
    拦回内容 = Tool call limit exceeded. Do not make additional tool calls.
    最后一条 = AIMessage '结束。'
```

模型轮数 6 对 6 两行一样：上限拦住的是执行，不是轮数。第 3、4、5 轮照样发请求、拿回 `tool_calls`、被编成 error `ToolMessage`，执行从 5 降到 2，请求一次没少。限额能让循环不再产生副作用，拦不住它继续烧 token，轮数要靠第 12 章的 `ModelCallLimitMiddleware` 管。

```
=== 三、exit_behavior 与只限一个工具 ===
  exit_behavior='continue'（默认）       工具执行 = 2  最后一条 = AIMessage '结束。'
  exit_behavior='end'                工具执行 = 2  最后一条 = AIMessage 'Tool call limit reached: run limit exceeded (3/2 calls).'
  只限 get_order，run_limit=1           工具执行 = 1  最后一条 = AIMessage '结束。'
```

`exit_behavior` 的三种取值：`"continue"` 拦住超限的调用让循环继续，是默认值；`"end"` 立刻收尾并追加一条说明为什么停的 AI 消息；`"error"` 直接抛异常。`thread_limit` 按 `thread_id` 累计，同一条会话跑第二次接着数；`run_limit` 每次 `invoke` 从零开始。前者防单次失控，后者防用户一直点重试，两者的计数都靠 state，所以前者需要配 `checkpointer` 或 `thread_id`。同一个 `thread_id` 上连跑四次：

```
=== 四、thread_limit 跨运行累计 ===
  第 0 次运行：工具执行 = 1  被拦回 = 0
  第 1 次运行：工具执行 = 1  被拦回 = 0
  第 2 次运行：工具执行 = 1  被拦回 = 0
  第 3 次运行：工具执行 = 0  被拦回 = 1
```

`thread_limit=3` 在第 4 次运行被拦住，前三次各放行一次。这就是用户连点四次重试的情形：`run_limit` 每次都从零数，一次都拦不住。

### 模拟替掉执行

跑评测时不能真的发短信，`LLMToolEmulator` 在工具调用的位置上再发一次模型请求，让模型扮演这个工具返回什么，真实实现一次都不执行。不传 `model=` 时它去初始化 anthropic 的模型，而本机没装那个包：

```
=== 一、不传 model 的失败 ===
  ImportError：LLMToolEmulator's default model requires `langchain-anthropic` to be installed. Install it with `pip install langchain-anthropic`, or pass `model=...` explicitly to use a different provider.
```

同时打出一条 `DeprecationWarning`：默认模型已标记弃用。结论是必须显式传 `model=`，这既是可用性问题，也是版本风险。传了自己的模型之后：

```
=== 二、模拟器替掉工具执行 ===
  模拟器收到的提示词：
    You are emulating a tool call for testing purposes.

Tool: send_sms
Description: 给用户发一条短信。有副作用。
Arguments: {'order_id': 'A1001'}

Generate a realistic response that this tool would return given these arguments.
Return ONLY the tool's output, no explanation or preamble. Introduce variation into your responses.
  模拟器没有带 tools 字段 = True
  回灌 status=success content={"sent": true, "order_id": "A1001"}
  真实实现被调用次数 = {'get_order': 0, 'send_sms': 0}

=== 三、只模拟有副作用的工具 ===
  tools=['send_sms'] 时真实实现被调用次数 = {'get_order': 1, 'send_sms': 0}
```

模拟器那一轮请求没有 `tools` 字段，它把工具名、`description`、`arguments` 拼成一段用户消息，要求只返回工具的输出。第三段是选择性模拟：`tools=["send_sms"]` 时只有发短信被模拟，查询走真实实现。

### 模拟输出的可复现性

这段提示词的最后一个词是 `Introduce variation`：要求模型给出有变化的输出。跑通流程时这是优点，当评测基线就是问题：同一个用例跑两次，工具返回值不同，不比不知道哪个是模型的问题。模拟器的用途是让循环跑完，不是提供正确的结果，判定只能看轨迹；结果必须用真实工具跑，两者混用，得到的是评测通过、上线失败。

## 这一章建立的 7 件事

1. 工具在框架里有四个可见属性：`name`、`description`、`args`、`args_schema`；三种定义写法产出的 `tools` 项逐字相同（492 字符）。
2. `args` 与进请求的 `parameters` 差一次编码，pydantic 的 `title` 在那一步被丢掉；`args_schema` 同时是执行前的校验器，多余的键被静默丢弃，缺必填会报错。
3. `bind_tools` 只编请求体、不执行任何东西：不传 `tool_choice` 时请求里没有这个键，`'any'` 与 `'required'` 编成同一个值；`strict` 进 `function`，`parallel_tool_calls` 进顶层。
4. 一次响应里的多个 `tool_calls` 按顺序执行（三次各 0.2 秒总耗时 0.60 秒），`tool.invoke(call)` 返回带好 `tool_call_id` 的 `ToolMessage`。
5. 工具返回值可以分成两段：`content` 进上下文，`artifact` 留在消息上（本例 39 字符对 160 字符）。
6. 注入参数（`InjectedState`/`InjectedStore`/`ToolRuntime`/`InjectedToolCallId`）不进 `parameters`；漏写标记会让模型自己编一个值，而且不报错。
7. 失败处理分四层：`args_schema` 校验、`handle_tool_error`、`ToolRetryMiddleware`（`retry_on` 要收窄）、`ToolErrorMiddleware`（回灌在外）；调用上限拦的是执行不是轮数。

## 下一章

工具这一侧到这里就完整了：怎么定义、怎么绑定、怎么注入、出错怎么办、怎么收窄、怎么模拟。剩下的问题全在"谁来决定下一步"——本章的例子都只跑了一两轮，第二轮之所以发生，是我在脚本里写好了它发生。第 12 章把这段循环交给 `create_agent`：它的参数各管什么，钩子在一次运行里的顺序，`ModelCallLimitMiddleware` 怎么补上上一节留下的那个洞，中断与检查点怎么让一次运行停在半路再继续。

---

[← 第 10 章 · LangChain 组合与解析器](./10-LangChain组合与解析器.md)　｜　[卷 3 目录](./docs/INDEX.md#vol3)　｜　[第 12 章 · LangChain 的 Agent 与中间件 →](./12-LangChain的Agent与中间件.md)
