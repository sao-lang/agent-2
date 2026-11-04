# 第 10 章 · LangChain 组合与解析器

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./docs/INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F3 Runnable 协议与组合子 —— invoke/batch/stream 与管道、Parallel、Branch；F4 输出解析与自愈 —— 四个解析器加两个自愈解析器；F5 提示词模板 —— ChatPromptTemplate 与 FewShot 模板（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：几段 Runnable 为什么要拼成一条链、拼的是什么；七个组合子各接哪一种接缝；三种模板装出来的 messages 长什么样；四个解析器分别校验到哪一层；解析失败之后有哪两条自愈路径；一次调用的内部步骤怎么摊成一张事件树
> - **示例目录**：`code/knowledge/ch10_lc_compose/`
> - **读完应当能回答**：给一条链，你能说出它要什么输入键、给什么输出类型、哪一步会抛异常、抛了之后哪个组合子接得住

---

## 目录

[LCEL 与四种调用入口](#lcel-与四种调用入口)\
[组合子与管道](#组合子与管道)\
[分支与兜底](#分支与兜底)\
[提示词模板](#提示词模板)\
[输出解析器](#输出解析器)\
[自愈解析器](#自愈解析器)\
[事件树的父子关系](#事件树的父子关系)\
[这一章建立的 6 件事](#这一章建立的-6-件事)

本章对照 **LangChain 1.4.7**（同环境 `langchain-core` 1.7.0、`langchain-openai` 1.1.9、`langchain-classic` 1.0.8），每个 API 都在这个版本上跑过，输出逐字粘贴。
示例目录里的 `scripted_chat.py` 是脚本化后端：把 `ChatOpenAI` 的 httpx 传输层换成本地回放，响应来自写死的字典。它是原理演示，不是模型实测：能验证形状、异常、事件、调用次数，验证不了模型会不会真按格式输出。接真实服务时把 `scripted_chat(respond)` 换成 `ChatOpenAI(...)`，其余代码不用改。

运行方式是在仓库根目录下：

```powershell
$env:PYTHONIOENCODING='utf-8'
python code/knowledge/ch10_lc_compose/protocol.py
```

---

## LCEL 与四种调用入口

第 4 章的做法五是手写的三段：拼 messages、发一次请求、把回来的文本解析成对象；第 7 章的循环把这三段放进 while。三段各自不难，难的是接缝：段与段之间传的是 dict、str 还是 `AIMessage`，只有人记着。接缝上没有检查，错到运行时才报。把 `StrOutputParser` 直接接在模板后面，拼链时一声不响，调用时才抛，见 `code/knowledge/ch10_lc_compose/combinators.py`：

```python
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只回答是否符合退货条件，一句话。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}

chain = PROMPT | StrOutputParser()
print("== 1b. 接错位置 ==")
try:
    chain.invoke(CASE)
except Exception as e:
    print(f"{type(e).__name__}: {str(e).splitlines()[0]}")
```

```
== 1b. 接错位置 ==
ValidationError: 1 validation error for Generation
```

`|` 只检查右边能不能当 Runnable（普通函数会被自动包成 `RunnableLambda`），不检查前一段给出的 `ChatPromptValue` 是不是后一段要的文本，一直到解析器内部的 pydantic 校验才认出类型不对。链一长接缝跟着涨，每加一处重试或兜底还要再挂一个判断。
这套把 Runnable 串起来的写法叫 LCEL（LangChain Expression Language），全部内容是三条约定。**串联就是函数复合**：`a | b | c` 与 `c(b(a(x)))` 等价，链上没有中途停下，想停就在链外停。**形状能算出来**：模板知道自己的变量，解析器吐对象，链能报出输入键与输出类型。**改行为的参数不进签名**：并发数、重试次数、回调都从外层通过 `config` 注入，代码一行不改。

`|` 拼出来的类就是 `RunnableSequence`，手写它与用管道完全等价。下面是不接模型的示意代码：

```python
from langchain_core.runnables import (RunnableLambda, RunnableParallel,
                                      RunnablePassthrough, RunnableSequence)

upper = RunnableLambda(str.upper)
exclaim = RunnableLambda(lambda s: s + "！")

pipe = upper | exclaim                      # 管道
same = RunnableSequence(upper, exclaim)     # 同一个序列，显式构造
print(type(pipe).__name__, pipe.invoke("ok"), pipe.invoke("ok") == same.invoke("ok"))

fan = RunnableParallel(orig=RunnablePassthrough(), shouted=upper | exclaim)
print(fan.invoke("ok"))
```

```
RunnableSequence OK！ True
{'orig': 'ok', 'shouted': 'OK！'}
```

`RunnableSequence` 按顺序喂，每一段的输出就是下一段的输入；`RunnableParallel` 里各分支拿到的是同一份原始输入，键名决定结果落在 dict 哪一格；`RunnablePassthrough` 只把输入传下去。`invoke("ok")` 走到 `"OK！"`，`fan` 出来是 `{'orig': 'ok', 'shouted': 'OK！'}`。求值先左后右，任何一段抛异常整条链就停在那一段。

### 一条链与它的形状

`protocol.py` 的开头，逐字一致：

```python
import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from scripted_chat import chat_completion, scripted_chat, sse_content

TEMPLATE = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只回答是否符合退货条件，一句话。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])

REQUESTS = {"n": 0}

def respond(index: int, body: dict):
    """脚本化后端：每次请求返回什么。流式请求返回 SSE 帧。"""
    REQUESTS["n"] += 1
    if body.get("stream"):
        return httpx.Response(200, content=sse_content("符合", "退货", "条件。"),
                              headers={"content-type": "text/event-stream"})
    return chat_completion("符合退货条件。", usage=(42, 7))

def build_chain():
    """模板 → 模型 → 解析器。三个 Runnable 用 | 连成一条 RunnableSequence。"""
    model = scripted_chat(respond)
    return TEMPLATE | model | StrOutputParser()
```

```
链的类型： RunnableSequence
```

`respond` 里数了请求次数，用它区分一次调用发几条请求。链自己会报出两头的形状：

```python
def show_shape(chain) -> None:
    """链自己声明了输入输出形状：输入是哪些键，输出是什么类型。"""
    inp = chain.get_input_schema().model_json_schema()
    out = chain.get_output_schema().model_json_schema()
    print("输入形状：")
    print(f"  required = {inp.get('required')}")
    print(f"  properties = {list(inp.get('properties', {}))}")
    print("输出形状：")
    print(f"  title = {out.get('title')}")
    print(f"  type = {out.get('type')}")
```

```
输入形状：
  required = ['days', 'order_id', 'state']
  properties = ['days', 'order_id', 'state']
输出形状：
  title = StrOutputParserOutput
  type = string
```

`required` 正是模板里那三个占位符，`type` 是 `string`，来自最后一段 `StrOutputParser`。拼错的链不必等到调用，先看这两行就能对，这一段对应第 4 章靠注释维持的约定。

### 多条的输入

`invoke` 与 `batch` 的差别只有输入是单条还是多条，其余完全一样，见 `code/knowledge/ch10_lc_compose/protocol.py` 的 `invoke_part()`：

```python
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}
CASES = [CASE,
         {"order_id": "A1002", "days": 8, "state": "已拆封"},
         {"order_id": "A1003", "days": 1, "state": "未拆封"}]

def invoke_part(chain) -> None:
    REQUESTS["n"] = 0
    print("== invoke：一次输入，一次输出 ==")
    out = chain.invoke(CASE)
    print(f"输入 {type(CASE).__name__} → 输出 {type(out).__name__}，是 str 的子类：{isinstance(out, str)}")
    print(f"值：{out!r}")
    print(f"HTTP 请求数：{REQUESTS['n']}")
    print()

def batch_part(chain) -> None:
    REQUESTS["n"] = 0
    print("== batch：多条输入 ==")
    outs = chain.batch(CASES, config={"max_concurrency": 1})
    print(f"输入 list[{len(CASES)}] → 输出 {type(outs).__name__}[{len(outs)}]")
    print(f"HTTP 请求数：{REQUESTS['n']}（不是 1：batch 是挨个发的）")
    print()
```

```
== invoke：一次输入，一次输出 ==
输入 dict → 输出 TextAccessor，是 str 的子类：True
值：'符合退货条件。'
HTTP 请求数：1

== batch：多条输入 ==
输入 list[3] → 输出 list[3]
HTTP 请求数：3（不是 1：batch 是挨个发的）
```

**输出不是裸 `str`**：类名是 `TextAccessor`，`isinstance(x, str)` 为真，它来自消息对象的 `.text`，按 `str` 用没问题，别按类名写判断。**batch 是 N 条请求**：三条输入发三次，`max_concurrency` 决定同时发几条，结果仍按输入下标排好。它省下的只是循环与结果对齐，token 与延迟一笔没省，三条输入就是三条计费、三条限流。

输入少一个键：

```python
def batch_bad_input(chain) -> None:
    """输入少一个键：报错发生在装 messages 那一步，信息比调用栈有用。"""
    print("== batch：输入缺键 ==")
    try:
        chain.batch([{"order_id": "A1001"}], config={"max_concurrency": 1})
    except Exception as e:
        msg = str(e.args[0]) if e.args else str(e)
        lines = msg.splitlines()
        print(f"{type(e).__name__}: {lines[0]}")
        print(f"  {lines[1] if len(lines) > 1 else ''}")
    print()
```

```
== batch：输入缺键 ==
KeyError: Input to ChatPromptTemplate is missing variables {'days', 'state'}.  Expected: ['days', 'order_id', 'state'] Received: ['order_id']
  Note: if you intended {days} to be part of the string and not a variable, please escape it with double curly braces like: '{{days}}'.
```

### 逐段输出

`stream` 交出的是增量，拼起来才是完整回答，见 `code/knowledge/ch10_lc_compose/protocol.py`：

```python
def stream_part(chain) -> None:
    REQUESTS["n"] = 0
    print("== stream：一次输入，逐段输出 ==")
    pieces = list(chain.stream(CASE))
    print(f"收到 {len(pieces)} 段：{pieces}")
    print(f"拼起来：{''.join(pieces)!r}")
    print(f"其中空串 {sum(1 for p in pieces if p == '')} 段（收尾帧的 delta 是空的）")
    print(f"HTTP 请求数：{REQUESTS['n']}")
    print()
```

```
== stream：一次输入，逐段输出 ==
收到 5 段：['符合', '退货', '条件。', '', '']
拼起来：'符合退货条件。'
其中空串 2 段（收尾帧的 delta 是空的）
HTTP 请求数：1
```

一次请求、五段回应，内容只有三段；第四段带 `finish_reason=stop` 但增量文本为空，第五段是框架补的收尾块：判断流结束只能看 `finish_reason` 或 `join` 完的结果。`stream` 给的是增量而不是累积文本，同一段 SSE 交给 `StrOutputParser` 得到增量片段，交给 `JsonOutputParser` 得到累积对象；只收到 `'符合'` 时不能下结论。

### 异步入口

四个入口各有一个 `a` 前缀的版本，形状与同步版一一对应，见 `code/knowledge/ch10_lc_compose/protocol.py` 的 `async_part()`：

```python
async def async_part(chain) -> None:
    print("== ainvoke ==")
    out = await chain.ainvoke(CASE)
    print(f"{type(out).__name__}：{out!r}")
    print()

    print("== abatch（max_concurrency=2）==")
    outs = await chain.abatch(CASES, config={"max_concurrency": 2})
    print(f"长度 {len(outs)}：{outs}")
    print()

    print("== astream ==")
    pieces = [piece async for piece in chain.astream(CASE)]
    print(f"{len(pieces)} 段：{pieces}")
    print()
```

```
== ainvoke ==
TextAccessor：'符合退货条件。'

== abatch（max_concurrency=2）==
长度 3：['符合退货条件。', '符合退货条件。', '符合退货条件。']

== astream ==
5 段：['符合', '退货', '条件。', '', '']
```

形状一样，代价是同步与异步走两个独立的 HTTP 客户端。删掉 `http_async_client` 那个参数，`ainvoke` 会去连真实端点：

```
openai.AuthenticationError: Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-test. ...
```

接真实服务时同样要给两份，异步连接池与超时不会从同步客户端继承。

### 过程入口

第四个入口不给结果，给过程：模型吐一段就发一条事件，父子关系靠 `parent_ids` 串起来，见 `code/knowledge/ch10_lc_compose/protocol.py` 的 `event_part()`。

```python
def event_part() -> None:
    """事件流：同一条链跑一次，数出每一类事件的条数。"""
    chain = build_chain()

    async def collect() -> list[dict]:
        events = []
        async for ev in chain.astream_events(CASE, version="v2"):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    kinds: dict[str, int] = {}
    for ev in events:
        kinds[ev["event"]] = kinds.get(ev["event"], 0) + 1

    print("== astream_events：一次 invoke 对应的事件 ==")
    for event, n in kinds.items():
        print(f"  {event:<26}{n}")
    print(f"  {'合计':<24}{len(events)}")
```

```
== astream_events：一次 invoke 对应的事件 ==
  on_chain_start            1
  on_prompt_start           1
  on_prompt_end             1
  on_chat_model_start       1
  on_chat_model_stream      5
  on_parser_start           1
  on_parser_stream          5
  on_chain_stream           5
  on_chat_model_end         1
  on_parser_end             1
  on_chain_end              1
  合计                      23
```

一次 `invoke` 在这条三段链上摊成 23 条事件，三个 `5` 说明它们都参与了流式。要边流边看中间步骤只能走事件流，只要最终文本用 `stream` 就够。四个入口放在一起：

| 入口 | 输入 | 输出 | 一次调用发几次请求 | 对应主线哪一段 |
|---|---|---|---|---|
| `invoke` | 一个 dict | 一个结果 | 1 | 第 1 章的一次调用 |
| `batch` | 一串 dict | 一串结果 | 等于条数 | 第 7 章循环里的重复调用 |
| `stream` | 一个 dict | 一串增量 | 1 | 第 1 章的流式 |
| `astream_events` | 一个 dict | 一串事件 | 1 | 第 8 章排查失控时的观察点 |
| `ainvoke` / `abatch` / `astream` | 同上 | 同上 | 同上 | 同上，换成异步客户端 |

## 组合子与管道

七个组合子在 1.4.7 里全部存在：`|`、`RunnableParallel`、`RunnablePassthrough`、`RunnableLambda`、`RunnableBranch`、`with_fallbacks`、`with_retry`。`RunnableBranch` 的签名是 `*branches`：前面若干 `(条件, 分支)` 元组，最后一项若单独是 Runnable 就作默认分支。公共件先摆出来，见 `code/knowledge/ch10_lc_compose/combinators.py`：

```python
import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (RunnableBranch, RunnableLambda, RunnableParallel,
                                      RunnablePassthrough)
from scripted_chat import chat_completion, scripted_chat

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只回答是否符合退货条件，一句话。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])

CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}

def fixed_model(text: str):
    """每次请求都返回同一句话的脚本化模型。"""
    def respond(index: int, body: dict):
        return chat_completion(text, usage=(42, 7))
    return scripted_chat(respond)

def model_500():
    """按真实接口形态返回 500 的模型：用来触发 fallback。"""
    def respond(index: int, body: dict):
        return httpx.Response(500, json={"error": {"message": "upstream unavailable",
                                                  "type": "server_error"}})
    return scripted_chat(respond)
```

### 管道

先看最基础的管道，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `pipe_demo()`：

```python
def pipe_demo() -> None:
    chain = PROMPT | fixed_model("符合退货条件。") | StrOutputParser()
    print("== 1. | 三段串联 ==")
    print("类型：", type(chain).__name__)
    print("输出：", repr(chain.invoke(CASE)))
    print()
```

```
== 1. | 三段串联 ==
类型： RunnableSequence
输出： '符合退货条件。'
```

`|` 把若干 Runnable 装进一个 `RunnableSequence`，调用时按顺序喂，替代的是第 4 章手写的那三行。省掉的不是代码行数，而是中间变量以及哪个中间变量传给谁；管道唯一的检查是右边能不能当 Runnable，所以链越长拼接错误代价越大。

### 并行分发

同一份输入要喂给两段、结果合回一个 dict 时用 `RunnableParallel`，键名决定结果落在哪一格，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `parallel_demo()`：

```python
def parallel_demo() -> None:
    chain = RunnableParallel(
        verdict=PROMPT | fixed_model("符合退货条件。") | StrOutputParser(),
        chars=RunnableLambda(lambda x: len(x["state"])),
    )
    out = chain.invoke(CASE)
    print("== 2. RunnableParallel：同一份输入分给两个分支 ==")
    print(f"输出类型 {type(out).__name__}，键 {list(out)}")
    print(out)
    print()
```

```
== 2. RunnableParallel：同一份输入分给两个分支 ==
输出类型 dict，键 ['verdict', 'chars']
{'verdict': '符合退货条件。', 'chars': 3}
```

输出是一个 dict，键就是构造时给的名字；两个分支拿到的是同一份输入，不是上一个分支的结果。同一输入要几份不同加工用它，上一步结果再加工用 `|`；搞混不报错，结果是错的，分支执行顺序也不保证。

### 直通与追加

`RunnablePassthrough` 直通，`assign` 版本追加新键，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `passthrough_demo()`：

```python
def passthrough_demo() -> None:
    chain = RunnablePassthrough.assign(
        verdict=PROMPT | fixed_model("符合退货条件。") | StrOutputParser(),
    )
    out = chain.invoke(CASE)
    print("== 3. RunnablePassthrough.assign：保留输入，追加一个键 ==")
    print(out)
    print(f"原输入没被改：{CASE}")
    print()
```

```
== 3. RunnablePassthrough.assign：保留输入，追加一个键 ==
{'order_id': 'A1001', 'days': 3, 'state': '未拆封', 'verdict': '符合退货条件。'}
原输入没被改：{'order_id': 'A1001', 'days': 3, 'state': '未拆封'}
```

原输入的三个键都还在，`verdict` 是新增的。`assign` 里每个键的值是一个 Runnable 或函数，收到的是当前这个 dict，不是别的键的结果，这对应第 4 章把资料包进提示词那一步。

### 函数包装

一小段逻辑不值得写成类时，`RunnableLambda` 把函数包成 Runnable，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `lambda_demo()`：

```python
def lambda_demo() -> None:
    def shape_input(raw: dict) -> dict:
        """把外部入参整成本章统一的三个键。"""
        return {"order_id": raw["id"], "days": raw["signed_days"], "state": raw["status"]}

    def clip(text: str) -> str:
        return text if len(text) <= 12 else text[:12] + "…"

    chain = RunnableLambda(shape_input) | PROMPT | fixed_model("符合退货条件。") | StrOutputParser() | RunnableLambda(clip)
    print("== 4. RunnableLambda：把普通函数接进链 ==")
    print(chain.invoke({"id": "A1001", "signed_days": 3, "status": "未拆封"}))
    print()
```

```
== 4. RunnableLambda：把普通函数接进链 ==
符合退货条件。
```

`shape_input` 在链头把外部入参整成模板要的三个键，是输入适配；`clip` 在链尾截断输出，是输出适配。包起来的好处是它们也出现在事件树里，也参与 batch 与重试；副作用是被包的函数会多次调用且不保证顺序，不要在里面累加外部状态。`StrOutputParser` 之后再加一段，链的输出类型就从 `TextAccessor` 变成普通 `str`。

## 分支与兜底

### 条件分支

按条件选一条路时用 `RunnableBranch`，入参是一串 `(条件, 分支)` 外加一条默认链，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `branch_demo()`：

```python
def branch_demo() -> None:
    branch = RunnableBranch(
        (lambda x: x["days"] > 7, RunnableLambda(lambda x: "超期：不退")),
        (lambda x: x["state"] == "已拆封", RunnableLambda(lambda x: "已拆封：需人工审核")),
        PROMPT | fixed_model("符合退货条件。") | StrOutputParser(),
    )
    print("== 5. RunnableBranch：按条件选一条路 ==")
    for case in [CASE,
                 {"order_id": "A1002", "days": 10, "state": "未拆封"},
                 {"order_id": "A1003", "days": 2, "state": "已拆封"}]:
        print(f"  {case} -> {branch.invoke(case)}")
    print()
```

```
== 5. RunnableBranch：按条件选一条路 ==
  {'order_id': 'A1001', 'days': 3, 'state': '未拆封'} -> 符合退货条件。
  {'order_id': 'A1002', 'days': 10, 'state': '未拆封'} -> 超期：不退
  {'order_id': 'A1003', 'days': 2, 'state': '已拆封'} -> 已拆封：需人工审核
```

三个 case 走了三条不同的路，其中两条根本没调模型：要不要调用模型由代码决定，不由模型决定。条件按顺序检查，第一个为真的生效，条件函数自己出错时整条链失败：

```python
def branch_raise_demo() -> None:
    """条件函数自己要读的键不存在：整条链失败，不会退到默认分支。"""
    branch = RunnableBranch(
        (lambda x: x["days"] > 7, RunnableLambda(lambda x: "超期：不退")),
        RunnableLambda(lambda x: "默认：可退"),
    )
    print("== 5b. 条件函数自己抛异常 ==")
    try:
        branch.invoke({"order_id": "A1004"})
    except Exception as e:
        print(f"{type(e).__name__}: {e}")
    print()
```

```
== 5b. 条件函数自己抛异常 ==
KeyError: 'days'
```

`{"order_id": "A1004"}` 里没有 `days`，第一个条件函数读它就抛 `KeyError`，它没有落到默认分支，而是把整条链带崩：兜底接的是某一段失败，不接判断本身不成立。

### 备用路径

主路抛异常时换路用 `with_fallbacks`，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `fallback_demo()`：

```python
def fallback_demo() -> None:
    primary = PROMPT | model_500() | StrOutputParser()
    backup = PROMPT | fixed_model("主服务不可用，这是备用模型的回答。") | StrOutputParser()
    chain = primary.with_fallbacks([backup])

    print("== 6. with_fallbacks：主路失败换备用 ==")
    print(f"返回类型 {type(chain).__name__}")
    print("输出：", chain.invoke(CASE))

    try:
        primary.invoke(CASE)
    except Exception as e:
        print(f"不走 fallback 时看到的是：{type(e).__name__}")

    with_key = RunnableLambda(
        lambda x: (_ for _ in ()).throw(ValueError("boom"))
    ).with_fallbacks([RunnablePassthrough()], exception_key="err")
    print("exception_key 的效果：", with_key.invoke({"a": 1}))
    print()
```

```
== 6. with_fallbacks：主路失败换备用 ==
返回类型 RunnableWithFallbacks
输出： 主服务不可用，这是备用模型的回答。
不走 fallback 时看到的是：InternalServerError
exception_key 的效果： {'a': 1, 'err': ValueError('boom')}
```

同一份输入走 `primary` 得到 `InternalServerError`，包上 `with_fallbacks` 之后得到备用模型的回答。备用链接的是原始输入而不是主路中途的产出，这是它与重试的根本区别。`exceptions_to_handle` 默认 `Exception`，`exception_key` 把异常塞进输入 dict 的某个键；默认接所有异常太宽，编程错误也会被当成故障切走。

### 重试

同一份输入重发用 `with_retry`，见 `code/knowledge/ch10_lc_compose/combinators.py` 的 `retry_demo()`：

```python
def retry_demo() -> None:
    calls = {"n": 0}

    def flaky(x: dict) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection refused")
        return f"第 {calls['n']} 次成功"

    chain = RunnableLambda(flaky).with_retry(stop_after_attempt=3, wait_exponential_jitter=False)
    print("== 7. with_retry：同一份输入重发 ==")
    print("输出：", chain.invoke({}))
    print("实际尝试次数：", calls["n"])

    never = RunnableLambda(lambda x: (_ for _ in ()).throw(httpx.ConnectError("always down")))
    chain2 = never.with_retry(stop_after_attempt=2, wait_exponential_jitter=False)
    try:
        chain2.invoke({})
    except Exception as e:
        print(f"一直失败时：{type(e).__name__}: {e}")
    print()
```

```
== 7. with_retry：同一份输入重发 ==
输出： 第 3 次成功
实际尝试次数： 3
一直失败时：ConnectError: always down
```

前两次抛 `ConnectError`，第三次成功，调用方看不到前面两次；一直失败时抛出的仍是最后一次的原始异常。`retry_if_exception_type` 默认也是 `Exception`，把不该重试的错误也重试，等于把一次失败变成三次。七个组合子按它接的接缝排一下：

| 组合子 | 接的接缝 | 主线里对应哪一段 |
|---|---|---|
| `\|` | 段与段的顺序连接 | 第 4 章手写的三段式 |
| `RunnableParallel` | 一份输入分给多段 | 第 6 章多个 `tool_calls` 的并发执行 |
| `RunnablePassthrough.assign` | 往下传的 dict 里追加东西 | 第 4 章把资料包进提示词 |
| `RunnableLambda` | 链头链尾的适配代码 | 各章里那些"顺手写一行" |
| `RunnableBranch` | 按条件选路 | 分流一章的"不值得进循环" |
| `with_fallbacks` | 主路整体失败 | 第 7 章循环里的失败处理 |
| `with_retry` | 单段失败重发 | 第 4 章的本地校验 + 重试 |

七个组合子都不改变段的语义，只改段的连接方式：重试只是多做几次，兜底只是换一条路，分支只是把判断搬进链。所以它们能自由组合，也组合不出一条自动变聪明的链。

## 提示词模板

模板只回答一个问题：变量在哪里。它把输入数据与输出格式挖成占位符。先摆打印函数，见 `code/knowledge/ch10_lc_compose/templates.py`：

```python
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import (ChatPromptTemplate, FewShotChatMessagePromptTemplate,
                                    MessagesPlaceholder)

def dump(label: str, messages: list) -> None:
    """把装好的 messages 打成一张表。"""
    print(f"== {label}：{len(messages)} 条 ==")
    print(f"  {'#':<3}{'type':<10}{'类':<16}content")
    for i, m in enumerate(messages):
        content = str(m.content).replace("\n", "\\n")
        if len(content) > 46:
            content = content[:46] + "…"
        print(f"  {i:<3}{m.type:<10}{type(m).__name__:<16}{content}")
    print()
```

### 固定条数

条数固定的模板，见 `code/knowledge/ch10_lc_compose/templates.py` 的 `part_fixed()`。

```python
def part_fixed() -> None:
    """最常用的一种：一串 (角色, 内容) 元组，占位符写在内容里。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。只依据政策回答，不引用外部知识。"),
        ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
        ("human", "只回答是否符合退货条件，一句话。"),
    ])
    print("模板 1 的输入变量：", prompt.input_variables)
    dump("1. ChatPromptTemplate.from_messages",
         prompt.format_messages(order_id="A1001", days=3, state="未拆封"))
```

```
模板 1 的输入变量： ['days', 'order_id', 'state']
== 1. ChatPromptTemplate.from_messages：3 条 ==
  #  type      类               content
  0  system    SystemMessage   你是退货客服。只依据政策回答，不引用外部知识。
  1  human     HumanMessage    订单 A1001，签收 3 天，商品状态：未拆封。
  2  human     HumanMessage    只回答是否符合退货条件，一句话。
```

条数由元组个数决定，`input_variables` 是三个占位符的并集，正好等于前面 `get_input_schema()` 报的 `required`。两条连续的 human 消息没有合并：服务端若拒绝连续同角色消息，要在模板层自己并成一条。模板改动会连带改输入形状，加一个占位符 `required` 就多一个键，所有构造输入的调用点都要跟着改。

### 条数不定的历史

条数由运行期决定的部分用 `MessagesPlaceholder`，见 `code/knowledge/ch10_lc_compose/templates.py` 的 `part_history()`：

```python
def part_history() -> None:
    """对话历史这种"条数不定"的部分，用 MessagesPlaceholder 留一个洞。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。"),
        MessagesPlaceholder("history", optional=True),
        ("human", "{question}"),
    ])
    print("模板 2 的输入变量：", prompt.input_variables, "（optional 的变量不要求给）")
    dump("2a. MessagesPlaceholder，不给历史",
         prompt.format_messages(question="符合条件吗？"))
    dump("2b. MessagesPlaceholder，给两轮历史",
         prompt.format_messages(
             history=[HumanMessage("我上周买的能退吗？"), AIMessage("请问签收几天了？")],
             question="签收 3 天，未拆封，符合条件吗？"))
```

```
模板 2 的输入变量： ['question'] （optional 的变量不要求给）
== 2a. MessagesPlaceholder，不给历史：2 条 ==
  #  type      类               content
  0  system    SystemMessage   你是退货客服。
  1  human     HumanMessage    符合条件吗？

== 2b. MessagesPlaceholder，给两轮历史：4 条 ==
  #  type      类               content
  0  system    SystemMessage   你是退货客服。
  1  human     HumanMessage    我上周买的能退吗？
  2  ai        AIMessage       请问签收几天了？
  3  human     HumanMessage    签收 3 天，未拆封，符合条件吗？
```

同一模板两次装出的条数不同：2 条与 4 条。`optional=True` 的变量不给就整段消失；`history` 的值是一串消息对象，传字符串会当场报错：

```python
def history_as_string() -> None:
    """MessagesPlaceholder 要的是一串消息对象，给字符串会当场报错。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。"),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ])
    print("== history 传字符串 ==")
    try:
        prompt.format_messages(history="我上周买的能退吗", question="能退吗？")
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    print()
```

```
== history 传字符串 ==
  ValueError: variable history should be a list of base messages, got 我上周买的能退吗 of type <class 'str'>
```

### 示例即消息

示例即消息：Few-shot 的示例本身也是消息序列。见 `code/knowledge/ch10_lc_compose/templates.py` 的 `part_fewshot()`。

```python
def part_fewshot() -> None:
    """示例也是 messages：先用一个模板描述"一问一答"的样子，再喂若干条。"""
    example_prompt = ChatPromptTemplate.from_messages([
        ("human", "{input}"),
        ("ai", "{output}"),
    ])
    few_shot = FewShotChatMessagePromptTemplate(
        example_prompt=example_prompt,
        examples=[
            {"input": "签收 3 天，未拆封", "output": "符合退货条件。"},
            {"input": "签收 20 天，未拆封", "output": "超期，不符合退货条件。"},
        ],
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。判断是否符合退货条件。"),
        few_shot,
        ("human", "{question}"),
    ])
    print("模板 3 的输入变量：", prompt.input_variables)
    dump("3. FewShotChatMessagePromptTemplate",
         prompt.format_messages(question="签收 6 天，未拆封"))
```

```
模板 3 的输入变量： ['question']
== 3. FewShotChatMessagePromptTemplate：6 条 ==
  #  type      类               content
  0  system    SystemMessage   你是退货客服。判断是否符合退货条件。
  1  human     HumanMessage    签收 3 天，未拆封
  2  ai        AIMessage       符合退货条件。
  3  human     HumanMessage    签收 20 天，未拆封
  4  ai        AIMessage       超期，不符合退货条件。
  5  human     HumanMessage    签收 6 天，未拆封
```

两条示例展开成四条消息，加 system 与真正的提问共 6 条。`example_prompt` 决定一条示例长什么样，`examples` 决定有几条；键名来自 `example_prompt` 的占位符，示例模板改成三段，`examples` 里就得多一个键。

### 少给一个变量

少给一个变量，报错落在装 messages 那一步，见 `code/knowledge/ch10_lc_compose/templates.py` 的 `part_missing()`：

```python
def part_missing() -> None:
    """少给一个变量：报错在装 messages 那一步，不在调用模型那一步。"""
    prompt = ChatPromptTemplate.from_messages([
        ("human", "订单 {order_id}，签收 {days} 天。"),
    ])
    print("== 4. 少给一个变量 ==")
    try:
        prompt.format_messages(order_id="A1001")
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    print("  想输出字面的花括号，写成 {{days}}。")
    print()
```

```
== 4. 少给一个变量 ==
  KeyError: 'days'
  想输出字面的花括号，写成 {{days}}。
```

只报一个键名，不说缺哪个位置的；链一长 `days` 可能来自三个模板，只能靠调用栈定位。示例条数还直接进 token 预算：两条示例换 4 条消息，每次调用都要付。

## 输出解析器

解析器接在链尾，校验的严格程度逐级上升。公共件在 `parsers.py`：

```python
from langchain_core.output_parsers import (CommaSeparatedListOutputParser, JsonOutputParser,
                                           PydanticOutputParser, StrOutputParser)
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from scripted_chat import chat_completion, scripted_chat

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只输出结果，不要解释。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}

def model_saying(text: str):
    def respond(index: int, body: dict):
        return chat_completion(text, usage=(42, 7))
    return scripted_chat(respond)

class RefundVerdict(BaseModel):
    """判定的结构。字段名就是要写进 JSON 的键名。"""

    order_id: str = Field(description="订单号，例如 A1001")
    eligible: bool = Field(description="是否符合退货条件")
    days: int = Field(description="签收天数")
    reason: str = Field(description="不超过 20 字的理由")
```

### 不校验的解析器

第一个几乎不校验，见 `code/knowledge/ch10_lc_compose/parsers.py` 的 `str_parser()`：

```python
def str_parser() -> None:
    chain = PROMPT | model_saying("符合退货条件。") | StrOutputParser()
    out = chain.invoke(CASE)
    print("== StrOutputParser ==")
    print(f"输出 {type(out).__name__}：{out!r}")
    print("它不做任何解析，只把 AIMessage 的 content 取出来。")
    print()
```

```
== StrOutputParser ==
输出 TextAccessor：'符合退货条件。'
它不做任何解析，只把 AIMessage 的 content 取出来。
```

`StrOutputParser` 的 `parse` 就是把输入原样返回，只做从消息里取文本这一步，对应第 1 章只取 `content` 那一节。下游一旦要读字段，就该换成 `PydanticOutputParser`。

### JSON 与字段类型

换成校验 schema 的解析器，返回模型实例，见 `code/knowledge/ch10_lc_compose/parsers.py` 的 `json_parser()`：

```python
def json_parser() -> None:
    text = '{"order_id": "A1001", "eligible": true, "days": 3, "reason": "未拆封且在七天内"}'
    parser = JsonOutputParser()
    chain = PROMPT | model_saying(text) | parser
    out = chain.invoke(CASE)
    print("== JsonOutputParser ==")
    print(f"输出 {type(out).__name__}：{out}")
    print("format_instructions：")
    print(parser.get_format_instructions())
    print()

    print("喂一段不是 JSON 的文本：")
    try:
        parser.invoke("符合退货条件。")
    except Exception as e:
        print(f"  {type(e).__name__}: {str(e).splitlines()[0]}")
    print()
```

```
== JsonOutputParser ==
输出 dict：{'order_id': 'A1001', 'eligible': True, 'days': 3, 'reason': '未拆封且在七天内'}
format_instructions：
Return a JSON object.

喂一段不是 JSON 的文本：
  OutputParserException: Invalid json output: 符合退货条件。
```

`JsonOutputParser` 校验是不是合法 JSON，返回 `dict`，但不看字段名、不看类型，`format_instructions` 只有一句 `Return a JSON object.`。`PydanticOutputParser` 才有 schema：

```python
def pydantic_parser() -> None:
    text = '{"order_id": "A1001", "eligible": true, "days": 3, "reason": "未拆封且在七天内"}'
    parser = PydanticOutputParser(pydantic_object=RefundVerdict)
    chain = PROMPT | model_saying(text) | parser
    out = chain.invoke(CASE)
    print("== PydanticOutputParser ==")
    print(f"输出 {type(out).__name__}：{out}")
    print(f"取字段：out.eligible={out.eligible}，type={type(out.eligible).__name__}")
    print("get_format_instructions()：")
    print(parser.get_format_instructions())
    print()

    print("喂一段缺字段的 JSON：")
    try:
        parser.invoke('{"order_id": "A1001", "eligible": true}')
    except Exception as e:
        lines = str(e).splitlines()
        print(f"  {type(e).__name__}: {lines[0]}")
        for line in lines[1:4]:
            print(f"  {line}")
    print()
```

前半部分输出：

```
== PydanticOutputParser ==
输出 RefundVerdict：order_id='A1001' eligible=True days=3 reason='未拆封且在七天内'
取字段：out.eligible=True，type=bool
get_format_instructions()：
The output should be formatted as a JSON instance that conforms to the JSON schema below.

As an example, for the schema {"properties": {"foo": {"title": "Foo", "description": "a list of strings", "type": "array", "items": {"type": "string"}}}, "required": ["foo"]}
the object {"foo": ["bar", "baz"]} is a well-formatted instance of the schema. The object {"properties": {"foo": ["bar", "baz"]}} is not well-formatted.

Here is the output schema:
```

紧接在后面的一行是 schema 本身：

```
{"description": "判定的结构。字段名就是要写进 JSON 的键名。", "properties": {"order_id": {"description": "订单号，例如 A1001", "title": "Order Id", "type": "string"}, "eligible": {"description": "是否符合退货条件", "title": "Eligible", "type": "boolean"}, "days": {"description": "签收天数", "title": "Days", "type": "integer"}, "reason": {"description": "不超过 20 字的理由", "title": "Reason", "type": "string"}}, "required": ["order_id", "eligible", "days", "reason"]}
```

后半部分是同一份代码的另一半：喂一段缺字段的 JSON，得到的报错是：

```
  OutputParserException: Failed to parse RefundVerdict from completion {"order_id": "A1001", "eligible": true}. Got: 2 validation errors for RefundVerdict
  days
    Field required [type=missing, input_value={'order_id': 'A1001', 'eligible': True}, input_type=dict]
      For further information visit https://errors.pydantic.dev/2.13/v/missing
```

`get_format_instructions()` 是一段现成的提示词：先说格式要求，给一个反例，再把 schema 原样贴出来，放进 system 段就等于把第 4 章输出格式要写死这一条自动化了。
错误信息是留给回灌的：逐个字段说缺什么、什么类型缺失，正是第 4 章说的回灌具体错误。
`description` 会进 schema，写清楚字段是什么等于在提示词里加一句说明。换解析器也不必改上游：四个解析器吃同一种输入，只把最后一段从 `Str` 换成 `Pydantic`，下游就从字符串变成模型实例。

### 列表格式

列表格式由 `CommaSeparatedListOutputParser` 处理，见 `code/knowledge/ch10_lc_compose/parsers.py` 的 `list_parser()`：

```python
def list_parser() -> None:
    text = "退货, 换货, 维修"
    parser = CommaSeparatedListOutputParser()
    chain = PROMPT | model_saying(text) | parser
    out = chain.invoke(CASE)
    print("== CommaSeparatedListOutputParser ==")
    print(f"输出 {type(out).__name__}：{out}")
    print("format_instructions：")
    print(parser.get_format_instructions())
    print()
```

```
== CommaSeparatedListOutputParser ==
输出 list：['退货', '换货', '维修']
format_instructions：
Your response should be a list of comma separated values, eg: `foo, bar, baz` or `foo,bar,baz`
```

它的约束最弱：只按逗号切、去空白，元素里本身带逗号时就切坏而且不报错，这是校验通过、内容已损坏的一类。要装结构化列表应该用第 5 章的 pydantic，字段类型写 `list[str]`。

### 流式下的部分对象

`JsonOutputParser` 在流式下给的是累积对象，代码在 `code/knowledge/ch10_lc_compose/stream_json.py`：

```python
import json

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只输出 JSON，不要 markdown 包裹。"),
    ("human", "订单 {order_id}，签收 {days} 天。判定是否符合退货条件。"),
])
CASE = {"order_id": "A1001", "days": 3}
# 三段增量：第一段单独看不是合法 JSON
PIECES = ('{"order_id": "A1001", ', '"eligible": true, ', '"days": 3}')

def respond(index: int, body: dict):
    if body.get("stream"):
        return httpx.Response(200, content=sse_content(*PIECES),
                              headers={"content-type": "text/event-stream"})
    return chat_completion("".join(PIECES), usage=(42, 7))

async def main() -> None:
    chain = PROMPT | scripted_chat(respond) | JsonOutputParser()

    print("== astream：每段是一份累积结果 ==")
    async for piece in chain.astream(CASE):
        print(f"  {json.dumps(piece, ensure_ascii=False)}")

    print()
    print("== ainvoke：同一份输入，一次给完整对象 ==")
    print(f"  {await chain.ainvoke(CASE)}")
```

```
== astream：每段是一份累积结果 ==
  {"order_id": "A1001"}
  {"order_id": "A1001", "eligible": true}
  {"order_id": "A1001", "eligible": true, "days": 3}

== ainvoke：同一份输入，一次给完整对象 ==
  {'order_id': 'A1001', 'eligible': True, 'days': 3}
```

三段增量单独看第一段不是合法 JSON。解析器每段都尝试解析全部文本，解析不出来就退化成部分对象，所以三段输出是三个越来越完整的对象。这与 `StrOutputParser` 正好相反：写流式 UI 时前者要自己累积，后者要整段替换。部分对象只满足能被解析，不满足 schema。

## 自愈解析器

第 4 章做法五的原则是回灌重试。框架里有两个实现，导入路径不在 `langchain_core`，见 `code/knowledge/ch10_lc_compose/self_heal.py`：

```python
from langchain_classic.output_parsers import OutputFixingParser, RetryOutputParser
```

`langchain.output_parsers` 这条路已经断了：

```
ModuleNotFoundError: No module named 'langchain.output_parsers'
```

这是 1.4.7 上的真实报错，旧代码要改包名。先造一个坏输出，模型每次返回读得懂但不是 JSON 的文本：

```python
from langchain_classic.output_parsers import OutputFixingParser, RetryOutputParser
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from scripted_chat import chat_completion, scripted_chat

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只输出 JSON，不要 markdown 包裹。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态 {state}。判定是否符合退货条件。"),
])
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}

GOOD = '{"order_id": "A1001", "eligible": true, "days": 3, "reason": "未拆封且在七天内"}'
# 第一次的坏输出：读得懂，但不是合法 JSON（中文引号、前缀说明、缺 reason）
BAD = '判定结果：{“order_id”: “A1001”, “eligible”: true, “days”: 3}'

CALLS = {"n": 0}

class RefundVerdict(BaseModel):
    order_id: str = Field(description="订单号")
    eligible: bool = Field(description="是否符合退货条件")
    days: int = Field(description="签收天数")
    reason: str = Field(description="不超过 20 字的理由")

def bad_model():
    """每次都输出不合法 JSON 的模型。"""
    def respond(index: int, body: dict):
        CALLS["n"] += 1
        return chat_completion(BAD, usage=(42, 7))
    return scripted_chat(respond)

def fixer_model(seen: list[str]):
    """修复模型：把收到的最后一条消息记下来，返回合法 JSON。"""
    def respond(index: int, body: dict):
        CALLS["n"] += 1
        seen.append(body["messages"][-1]["content"])
        return chat_completion(GOOD, usage=(60, 20))
    return scripted_chat(respond)
```

`BAD` 抄的是第 4 章那个真实坏法：中文引号、前缀说明、少一个字段。不加自愈时：

```python
def part_no_heal(parser) -> None:
    CALLS["n"] = 0
    print("== 0. 不自愈：一次调用，一个异常 ==")
    try:
        (PROMPT | bad_model() | parser).invoke(CASE)
    except Exception as e:
        print(f"{type(e).__name__}: {str(e).splitlines()[0]}")
    print(f"模型调用次数：{CALLS['n']}，解析成功 0 次")
    print()
```

```
== 0. 不自愈：一次调用，一个异常 ==
OutputParserException: Invalid json output: 判定结果：{“order_id”: “A1001”, “eligible”: true, “days”: 3}
模型调用次数：1，解析成功 0 次
```

### 只改格式

第一个只把坏文本交给修复模型改格式，见 `code/knowledge/ch10_lc_compose/self_heal.py` 的 `error_block()`：

```python
def error_block(text: str) -> str:
    """从 NAIVE_FIX_PROMPT 装出来的消息里，只截 Error 那一段。"""
    marker = "Error:\n--------------\n"
    if marker not in text:
        return text[:200]
    return text.split(marker, 1)[1].split("--------------", 1)[0].strip()

def part_fixing(parser) -> None:
    CALLS["n"] = 0
    seen: list[str] = []
    fixing = OutputFixingParser.from_llm(parser=parser, llm=fixer_model(seen))
    out = (PROMPT | bad_model() | fixing).invoke(CASE)
    print("== 1. OutputFixingParser：只交坏文本，改格式 ==")
    print(f"输出 {type(out).__name__}：{out}")
    print(f"模型调用次数：{CALLS['n']}（第一次出坏文本，解析失败；第二次修格式）")
    print("修复模型收到的 Error 段：")
    print("  " + error_block(seen[0]).replace("\n", "\n  "))
    print()
```

```
== 1. OutputFixingParser：只交坏文本，改格式 ==
输出 RefundVerdict：order_id='A1001' eligible=True days=3 reason='未拆封且在七天内'
模型调用次数：2（第一次出坏文本，解析失败；第二次修格式）
修复模型收到的 Error 段：
  OutputParserException('Invalid json output: 判定结果：{“order_id”: “A1001”, “eligible”: true, “days”: 3}\nFor troubleshooting, visit: https://docs.langchain.com/oss/python/langchain/errors/OUTPUT_PARSING_FAILURE ')
```

第一次解析失败，第二次修好，链最终返回 `RefundVerdict`。修复模型收到的提示词有固定形状：格式要求、坏文本、异常原文，正是第 4 章回灌具体错误的三件套。`from_llm` 要传 `parser` 而不是 schema。它自己也是 Runnable，能直接接在链尾，代价是异常在内部被消化，调用方看不出第一次失败过；每次失败多一次完整调用。

### 带原问题重发

第二个把原始提示词一起带回去，见 `code/knowledge/ch10_lc_compose/self_heal.py` 的 `part_retry()`：

```python
def part_retry(parser) -> None:
    CALLS["n"] = 0
    seen: list[str] = []
    retry = RetryOutputParser.from_llm(parser=parser, llm=fixer_model(seen), max_retries=1)
    prompt_value = PROMPT.invoke(CASE)
    out = retry.parse_with_prompt(completion=BAD, prompt_value=prompt_value)
    print("== 2. RetryOutputParser：把原始 prompt 一起带回 ==")
    print(f"输出 {type(out).__name__}：{out}")
    print(f"模型调用次数：{CALLS['n']}（这次坏文本是直接给的，只有重试这一次调用）")
    print("重试请求里带上的 Prompt 段：")
    head = seen[0].split("Completion:", 1)[0].strip()
    print("  " + head.replace("\n", "\n  "))
    print()
```

```
== 2. RetryOutputParser：把原始 prompt 一起带回 ==
输出 RefundVerdict：order_id='A1001' eligible=True days=3 reason='未拆封且在七天内'
模型调用次数：1（这次坏文本是直接给的，只有重试这一次调用）
重试请求里带上的 Prompt 段：
  Prompt:
  System: 你是退货客服。只输出 JSON，不要 markdown 包裹。
  Human: 订单 A1001，签收 3 天，商品状态 未拆封。判定是否符合退货条件。
```

`RetryOutputParser` 的核心方法是 `parse_with_prompt(completion, prompt_value)`，必须由调用方把当初那份 prompt 交进来，所以它通常接在链外。两个实现都建立在同一前提上：解析器要能说出哪里不对，所以自愈效果与解析器的严格程度直接相关。它发给模型的是原始问题全文，模型能重新生成内容而不只修括号，代价是可能给出完全不同的答案。两个解析器的分工：

| | `OutputFixingParser` | `RetryOutputParser` |
|---|---|---|
| 送给修复模型的内容 | 格式要求 + 坏文本 + 异常原文 | 原 prompt + 坏文本 + 失败原因 |
| 能修什么 | 语法、括号、包裹 | 内容本身（含值不对） |
| 需要调用方留 prompt 吗 | 不需要 | 需要 |
| 一次失败多花几次调用 | 1 | 1 |
| 适用场景 | 结构错、格式错 | 结构对但值可疑 |

重试只能是最后一道：能用严格 schema 把错误挡在生成时就别留给解析器，这两个解析器适合输出格式由不得我们选的场合。三条不该用的判据：错误来自内容而不是格式；链上有副作用且重试会重复执行；同一段坏输出修过两次还不过。

## 事件树的父子关系

事件流每条都带 `event`、`name`、`run_id`、`parent_ids` 与 `data`，按 `parent_ids` 的长度缩进就是一棵树，见 `code/knowledge/ch10_lc_compose/event_tree.py` 的 `pad()`：

```python
def pad(text: str, width: int) -> str:
    """按显示宽度补空格：一个中文字符占两列。"""
    used = sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)
    return text + " " * max(1, width - used)

def tree(events: list[dict]) -> None:
    """按 parent_ids 的层数缩进。流式事件只计数，不逐条打。"""
    print("  " + pad("事件名", 22) + pad("所在 Runnable", 34) + pad("run_id 尾 6 位", 16) + "层")
    print("  " + "-" * 68)
    stream_count: dict[str, int] = {}
    for ev in events:
        if ev["event"].endswith("_stream"):
            stream_count[ev["event"]] = stream_count.get(ev["event"], 0) + 1
            continue
        depth = len(ev["parent_ids"])
        indent = "  " * depth
        print("  " + pad(indent + ev["event"], 22 + 2 * depth)
              + pad(ev["name"], 34) + pad(ev["run_id"][-6:], 16) + str(depth))
    print()
    for event, n in stream_count.items():
        print(f"  （省略）{event} 共 {n} 条")
    print(f"  事件总数：{len(events)}")
```

```
== 一条平链的事件树 ==
  事件名                所在 Runnable                     run_id 尾 6 位  层
  --------------------------------------------------------------------
  on_chain_start        RunnableSequence                  37c5c7          0
    on_prompt_start       ChatPromptTemplate                1ccd2b          1
    on_prompt_end         ChatPromptTemplate                1ccd2b          1
    on_chat_model_start   ChatOpenAI                        e69913          1
    on_parser_start       StrOutputParser                   a46a48          1
    on_chat_model_end     ChatOpenAI                        e69913          1
    on_parser_end         StrOutputParser                   a46a48          1
  on_chain_end          RunnableSequence                  37c5c7          0

  （省略）on_chat_model_stream 共 5 条
  （省略）on_parser_stream 共 5 条
  （省略）on_chain_stream 共 5 条
  事件总数：23
```

事件名分三段 `on_<对象>_<阶段>`，对象有 `chain`、`prompt`、`chat_model`、`parser`，任何一次调用的骨架都是外层 start、子里程碑、外层 end。层数等于 `parent_ids` 的长度，不是靠读顺序猜。解析器的 start 在模型的 end 之前，因为流式下第一个增量一到解析器就开工。并行链会把第二层露出来：

```python
def nested_chain():
    """并行里套两段链：深度会出现第二层。"""
    return RunnableParallel(
        verdict=PROMPT | scripted_chat(respond) | StrOutputParser(),
        chars=RunnableLambda(lambda x: len(x["state"])),
    )
```

```
== 带并行的链：出现第二层 ==
  事件名                所在 Runnable                     run_id 尾 6 位  层
  --------------------------------------------------------------------
  on_chain_start        RunnableParallel<verdict,chars>   9e0d6a          0
    on_chain_start        RunnableSequence                  982545          1
    on_chain_start        RunnableLambda                    2835f8          1
      on_prompt_start       ChatPromptTemplate                c17ca8          2
      on_prompt_end         ChatPromptTemplate                c17ca8          2
    on_chain_end          RunnableLambda                    2835f8          1
      on_chat_model_start   ChatOpenAI                        7cd71a          2
      on_parser_start       StrOutputParser                   366539          2
      on_chat_model_end     ChatOpenAI                        7cd71a          2
      on_parser_end         StrOutputParser                   366539          2
    on_chain_end          RunnableSequence                  982545          1
  on_chain_end          RunnableParallel<verdict,chars>   9e0d6a          0

  （省略）on_chain_stream 共 12 条
  （省略）on_chat_model_stream 共 5 条
  （省略）on_parser_stream 共 5 条
  事件总数：34
```

两个分支的事件是交错的，按顺序读这张表会把父子关系读错，唯一依据是 `parent_ids`；谁先完成不代表因果，只代表耗时。同一棵树里 start 与 end 带的东西不一样：

```python
def payload(events: list[dict]) -> None:
    """start 事件带输入，end 事件带输出：两头形状对上才能排查。"""
    for ev in events:
        if ev["event"] == "on_chat_model_start":
            msgs = ev["data"]["input"]["messages"][0]
            print(f"  on_chat_model_start：{len(msgs)} 条，类型 {[m.type for m in msgs]}")
        if ev["event"] == "on_chat_model_end":
            out = ev["data"]["output"]
            print(f"  on_chat_model_end：{type(out).__name__}，content={out.content!r}")
            print(f"                     usage_metadata={out.usage_metadata}")
        if ev["event"] == "on_chain_end" and not ev["parent_ids"]:
            print(f"  on_chain_end（根）：output={ev['data']['output']!r}")
```

```
== start / end 两头各带什么 ==
  on_chat_model_start：2 条，类型 ['system', 'human']
  on_chat_model_end：AIMessageChunk，content='符合退货条件。'
                     usage_metadata=None
  on_chain_end（根）：output='符合退货条件。'
```

`on_chat_model_start` 的 `data["input"]` 是装好的两条消息，模板有没有拼对、占位符替换成什么都在这一格；`on_chat_model_end` 的 `data["output"]` 是 `AIMessageChunk`，`usage_metadata` 是 `None`：流式下计量信息不在增量里，要用 token 数得走非流式的 end 事件。三个排查问题各有落点：

| 问题 | 看哪一格 |
|---|---|
| 哪一步慢 | 每个 `on_*_start` 到对应 `on_*_end` 的间隔，最大的那段就是瓶颈 |
| 解析为什么失败 | `on_parser_start` 之后紧接着的事件；解析在流式下边流边做，失败会打断整条链 |
| 分支为什么没按预期跑 | `parent_ids` 缩进：分支是否真的被创建，还是被条件挡在了外面 |

这三格对应三种改法：瓶颈要换模型或减输入，解析失败要改提示词或换解析器，分支没跑要改条件。最常见的错是拿着解析失败的报错去改提示词，而问题在上游的模板变量。
链适合形状固定的流程：段数、段序、分支条件都在写代码时定死，一旦下一步要由上一步的输出决定，链就表达不了，那需要图。两段以内不值得引入框架，链的价值从同一套接缝被复用到第三处开始显现。脚本化后端能验证形状、异常、调用次数与事件树结构，不能验证模型是否真按 `format_instructions` 输出。

## 这一章建立的 6 件事

1. Runnable 的四个入口形状一致：`invoke` 一条进一条出，`batch` 一串进一串出（N 条请求，不是 1 条），`stream` 一条进逐段出，`astream_events` 给过程不给结果。异步版加 `a` 前缀，且走独立客户端。
2. 输出类型是 `TextAccessor`（`str` 的子类），不是裸 `str`；流式下有两段空增量，判断结束不能靠"最后一段非空"。
3. 七个组合子在 1.4.7 里都存在，`RunnableBranch` 的签名是 `(条件, 分支)` 元组加一个默认分支。`|` 不做类型检查，接错要到调用时才炸；条件函数自己抛异常会带崩整条链，不退到默认分支。
4. 三种模板的差别在条数由谁定：`from_messages` 写死、`MessagesPlaceholder` 调用时定、`FewShot` 由示例个数定。模板的变量并集就是链的 `required`。
5. 四个解析器层层加严：`Str` 不校验、`Json` 只校语法、`Pydantic` 校到字段类型与必填、`List` 只按逗号切。`get_format_instructions()` 是现成的提示词，`Pydantic` 的校验错误原文可以直接回灌。
6. 自愈两条路：`OutputFixingParser` 只改格式，`RetryOutputParser` 带原 prompt 重发；两者都在 `langchain_classic.output_parsers`。事件树靠 `parent_ids` 认父子，层数就是它的长度。

## 下一章

本章的链只做一件事：把一段提示词发给模型，再把回答解析成结构。模型在这一步里没有可选动作——它只能说话，不能请求做事。下一步是把动作交出去：用 `@tool` 定义工具、用 `bind_tools` 绑到模型上、把模型返回的 `tool_calls` 接到真实的函数调用。第 11 章与第 6 章手写的那次往返逐项对照：同一次往返，框架里多了什么、少了什么、哪一段仍然要自己写。

---

[← 第 9 章 · LangChain 包结构与消息](./09-LangChain包结构与消息.md)　｜　[卷 3 目录](./docs/INDEX.md#vol3)　｜　[第 11 章 · LangChain 的工具定义与绑定 →](./11-LangChain的工具定义与绑定.md)
