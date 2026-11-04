# 第 12 章 · LangChain 的 Agent 与中间件

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./docs/INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F8 create_agent 全参数 —— 十几个参数各管什么，state、context、checkpointer；F9 中间件机制 —— 六个钩子与洋葱顺序，短路规则；F10 内置中间件 —— 19 个内置中间件各管什么（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：第 7 章那个 30 行循环，在框架里被一次 `create_agent` 调用替掉了什么、没替掉什么、代价是什么
> - **示例目录**：`code/knowledge/ch12_lc_agent/`（LangChain 1.4.7；模型是脚本化后端，原理演示，不是模型实测）
> - **读完应当能回答**：给一个 `create_agent` 调用，能指出哪个参数管终止、哪个管状态；能写一个自定义中间件并说清它的钩子什么时候跑；能判断某件事该找内置中间件还是自己写

---

## 目录

[create_agent 参数表](#create_agent-参数表)\
[钩子与洋葱顺序](#钩子与洋葱顺序)\
[预算与重试中间件](#预算与重试中间件)\
[上下文与安全中间件](#上下文与安全中间件)\
[状态与检查点](#状态与检查点)\
[中断与人工审批](#中断与人工审批)\
[流式输出](#流式输出)\
[这一章建立的 6 件事](#这一章建立的-6-件事)

## create_agent 参数表

第 7 章那个 20 行循环把五件事压在同一个函数体里：终止、状态、预算、重试、审批。手写时它们被写成若干 `if`，每加一件事就多一层缩进，改一处会影响全部任务：空步计数只关心工具返回值，参数规范化只关心请求侧，指纹比对两边都要看。框架做的事只有一件：把模型调用前后、工具执行前后这四个位置变成可以按名字注册的钩子，把在每个位置做什么从循环体搬到单独的类里，需求之间唯一的耦合是注册顺序。

`create_agent` 在本机 1.4.7 上的签名，逐行打出来是这样，见 `code/knowledge/ch12_lc_agent/agent_params.py` 的 `show_signature()`：

```python
import inspect

from langchain.agents import create_agent


def show_signature() -> None:
    """把 15 个参数和默认值逐行打出来。"""
    sig = inspect.signature(create_agent)
    for name, param in sig.parameters.items():
        default = "" if param.default is inspect.Parameter.empty else f" = {param.default!r}"
        print(f"{name}{default}")


if __name__ == "__main__":
    show_signature()
```

输出：

```text
model
tools = None
system_prompt = None
middleware = ()
response_format = None
state_schema = None
context_schema = None
checkpointer = None
store = None
interrupt_before = None
interrupt_after = None
debug = False
name = None
cache = None
transformers = None
```

`model` 没有默认值，其余十四个都可以不传。不传 `middleware` 就没有钩子，不传 `checkpointer` 就没有持久化，跑起来仍是一个能调工具的最小 agent。逐个说它们管什么：

| 参数 | 管什么 | 不传时的样子 |
|---|---|---|
| `model` | 模型实例或 `"provider:model"` 字符串 | 必须传 |
| `tools` | 工具列表：普通函数、`BaseTool`、provider 内置工具的 dict | 没有工具，退化成一次问答 |
| `system_prompt` | 系统消息，等价第 4 章手写的那条 | 没有系统消息 |
| `middleware` | 钩子列表，**列表顺序即洋葱顺序** | 空元组，只有内置的模型节点与工具节点 |
| `response_format` | 最终答复的结构：pydantic 类、`ToolStrategy`、`ProviderStrategy` | 没有 `structured_response` 字段 |
| `state_schema` | 扩展 state 的字段定义 | 用默认 `AgentState`，只有 `messages` |
| `context_schema` | 每次调用传入的只读上下文类型 | `runtime.context` 是 `None` |
| `checkpointer` | 按 `thread_id` 存 state 的存储 | 无持久化，多轮与中断都用不了 |
| `store` | 跨 thread 的长期存储 | `runtime.store` 是 `None` |
| `interrupt_before` | 在哪些**节点**前停下（静态断点） | 不停 |
| `interrupt_after` | 在哪些**节点**后停下（静态断点） | 不停 |
| `debug` | 打印每个节点的输入与状态更新 | 安静 |
| `name` | 图的名字，挂成子图时用它 | `LangGraph` |
| `cache` | 图级缓存后端 | 无缓存 |
| `transformers` | 流式事件的变换器工厂 | 只有默认的 `ToolCallTransformer` |

一份把十五个参数都写出来的调用，以及它跑一次的结果：

```python
import pydantic
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver


@tool
def get_order(order_id: str) -> str:
    """按订单号查签收天数和状态。"""
    return '{"order_id": "A1001", "days_since_delivery": 3, "status": "已签收"}'


class RefundAnswer(pydantic.BaseModel):
    """最终答复的结构。"""

    can_refund: bool
    days_left: int


def build_agent():
    """一份把全部参数都写出来的调用。"""
    return create_agent(
        model=scripted_chat(respond),           # 模型：字符串或 BaseChatModel 实例
        tools=[get_order],                      # 工具：callable / BaseTool / 内置工具 dict
        system_prompt="你是退货客服，只回答退货问题。",   # 系统消息，等价第 4 章的 system
        middleware=[ModelCallLimitMiddleware(run_limit=4)],  # 钩子列表，顺序即洋葱序
        response_format=RefundAnswer,           # 最终答复的结构，落到 structured_response
        state_schema=None,                      # 扩展 state 的字段；这里用默认 AgentState
        context_schema=None,                    # 每次调用传进来、不进 checkpoint 的只读上下文
        checkpointer=InMemorySaver(),           # 按 thread_id 存 state，多轮与中断都要它
        store=None,                             # 跨 thread 的长期存储
        interrupt_before=None,                  # 在某个节点前停下来（静态断点）
        interrupt_after=None,                   # 在某个节点后停下来（静态断点）
        debug=False,                            # 打印每个节点的输入与状态更新
        name="refund_agent",                    # 图的名字，挂成子图时用
        cache=None,                             # 图级缓存后端
        transformers=None,                      # 流式事件变换器
    )
```

`scripted_chat(respond)` 是本目录的脚本化后端：把 `ChatOpenAI` 的传输层换成回放，请求照常序列化、响应来自写死的剧本。换成真实服务只改这一行；模型对象与消息对象长什么样，见第 9 章。这段跑出来的结果：

```text
图名字: refund_agent
  HumanMessage  'A1001 还能退吗'
  AIMessage     ''
  ToolMessage   '{"order_id": "A1001", "days_since_delivery": 3'
  AIMessage     ''
  ToolMessage   'Returning structured response: can_refund=True'
state 键: ['messages', 'structured_response']
structured_response: can_refund=True days_left=4
```

`response_format` 不是让模型输出 JSON 的口头约定：它在工具表里加了一个以类名命名的工具，模型调它一次，框架把参数校验成 `RefundAnswer`，再从 `messages` 之外给出 `structured_response`，所以最后一条 `ToolMessage` 的正文是框架自己写的。第 4 章那五种做法到框架里变成一个参数，底层仍是工具调用加校验。

`cache` 传了不等于会命中：两次完全相同的输入，模型被请求两次，`model` 节点的 `cache_policy` 是 `None`。

```text
=== cache：传了 cache 是否命中
  两次相同输入，模型被请求 2 次
  model 节点的 cache_policy: None
```

框架里有这个参数与这个参数起作用是两件事，中间隔着一层默认值。另外三个参数顺手交代：`middleware` 传的是实例列表而不是类，框架按 `name` 给每个实例建一个节点，所以顺序直接决定谁包住谁；`name` 只在把 agent 当子图挂进另一张图时有用；`system_prompt` 是静态的，`dynamic_prompt` 装饰器写出来的中间件每次模型调用前重算系统消息，这就是构造时定死与每轮重算两种写法。`transformers` 接流式事件的变换器，顺序固定：先 `ToolCallTransformer`，再中间件声明的，最后是这个参数传的，本章没有跑它。

## 钩子与洋葱顺序

`AgentMiddleware` 在本机 1.4.7 上提供的钩子，加上异步版本一共十二个方法，按位置分四类：

| 位置 | 钩子 | 能做什么 | 典型用途 |
|---|---|---|---|
| 整轮开始前 | `before_agent` | 返回 state 增量 | 初始化字段、检查输入 |
| 每次模型调用前 | `before_model` | 返回 state 增量；可跳转 | 改消息、加提示、拦下这一轮 |
| 每次模型调用前（包住） | `wrap_model_call` | 改请求、**不调 handler 即短路**、调多次 | 重试、换模型、缓存、限流 |
| 每次模型调用后 | `after_model` | 返回 state 增量；可跳转 | 记账、校验输出、触发中断 |
| 每次工具执行前（包住） | `wrap_tool_call` | 改调用、短路、重试 | 审批、模拟、错误兜底 |
| 整轮结束后 | `after_agent` | 返回 state 增量 | 汇总、写库 |

类上还有三个声明位置：`state_schema`、`transformers`、`name`。模块级还导出了 `hook_config` 这个装饰器与 `before_model`、`after_model`、`dynamic_prompt` 另外三个，用来写函数式中间件。

顺序用两个只会打日志的中间件就能看清，注册 `[Tracer("A"), Tracer("B")]` 跑一个调一次工具再作答的任务，见 `code/knowledge/ch12_lc_agent/middleware_order.py`：

```python
class Tracer(AgentMiddleware):
    """在每个钩子上打一行，用来看顺序。"""

    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag

    @property
    def name(self) -> str:
        return f"Tracer-{self.tag}"

    def before_agent(self, state, runtime):
        print(f"  {self.tag}.before_agent   msgs={len(state['messages'])}")
        return None

    def before_model(self, state, runtime):
        print(f"  {self.tag}.before_model   msgs={len(state['messages'])}")
        return None

    def wrap_model_call(self, request, handler):
        print(f"  {self.tag}.wrap_model_call 进入")
        response = handler(request)
        print(f"  {self.tag}.wrap_model_call 退出 {response.result[0].content!r}")
        return response

    def wrap_tool_call(self, request, handler):
        print(f"  {self.tag}.wrap_tool_call 进入 {request.tool_call['name']}")
        result = handler(request)
        print(f"  {self.tag}.wrap_tool_call 退出")
        return result

    def after_model(self, state, runtime):
        print(f"  {self.tag}.after_model")
        return None

    def after_agent(self, state, runtime):
        print(f"  {self.tag}.after_agent")
        return None
```

输出（节选两次模型调用之间的那一段）：

```text
  A.before_agent   msgs=1
  B.before_agent   msgs=1
  A.before_model   msgs=1
  B.before_model   msgs=1
  A.wrap_model_call 进入
  B.wrap_model_call 进入
  B.wrap_model_call 退出 ''
  A.wrap_model_call 退出 ''
  B.after_model
  A.after_model
  A.wrap_tool_call 进入 echo
  B.wrap_tool_call 进入 echo
        [工具函数] echo(hi)
  B.wrap_tool_call 退出
  A.wrap_tool_call 退出
```

四条规律：`before_*` 按注册顺序跑，`after_*` 按反序跑；`wrap_*` 最外层先进入、最外层后退出，与它包住的 `handler` 形成嵌套，这就是洋葱这个名字的来处；顺序不影响结果，只影响谁包住谁，把 A、B 对调，日志跟着对调，任务输出不变；`after_model` 在 `wrap_model_call` 退出之后才跑，钩子按这一轮的生命周期排，不按名字排。

短路规则只有一条：`wrap_model_call` 不调 `handler`，这次模型调用就不发生。加一个直接把 `AIMessage` 返回的中间件：

```python
class Cutter(AgentMiddleware):
    """不调用 handler，直接给一条 AIMessage。"""

    def wrap_model_call(self, request, handler):
        print("  Cutter.wrap_model_call 短路")
        return AIMessage(content="被中间件拦下")
```

输出：

```text
  A.before_agent   msgs=1
  A.before_model   msgs=1
  A.wrap_model_call 进入
  Cutter.wrap_model_call 短路
  A.wrap_model_call 退出 '被中间件拦下'
  A.after_model
  A.after_agent
  结果: 被中间件拦下
```

这容易被误读成短路等于整轮终止。它只跳过一次模型调用，`after_model`、`after_agent` 照跑，最后一条消息没有 `tool_calls`，循环自然结束。想在这一轮里真停下来，得靠 `before_model`/`after_model` 返回 `{"jump_to": ...}`。跳转有一个代码里看不出来的代价：跳过去时不自己补一条正文，最后一条 `AIMessage` 就是空的。

```text
=== 跳到 end 但不补正文
  消息: [('HumanMessage', '回声'), ('AIMessage', '')]

=== 跳到 end 并补一条正文
  消息: [('HumanMessage', '回声'), ('AIMessage', '直接收尾')]
```

目的地必须是图里真的存在的节点，往 `tools` 跳而这张图没有工具节点时，`create_agent` 当场失败：

```text
  ValueError: At 'JumpToMissingNode.before_model' node, 'jump_edge' branch found unknown target 'tools'
```

还有一条与实现细节绑定的限制：中间件按 `name` 去重，而 `name` 默认是类名，同一个类注册两次，构造就报错：

```text
  AssertionError: Please remove duplicate middleware instances.
```

要注册两份同类中间件，就得像 `Tracer` 那样覆写 `name`。短路不终止、跳转要补消息、名字不能重样，这三条是自定义中间件最常见的三个失效点。钩子的能力边界也在这三例里露出来了：它能改请求、改响应、改状态、提前结束，不能改图的形状。中间件能做的全部事情都发生在模型节点与工具节点这两个既有位置的前后，它不是插件系统，没有注册新能力的入口；要新增工具走 `tools=`，要新增节点得另建一张图，是第 36 章的题目。

不必写类。三个装饰器可以把普通函数变成中间件，其中 `dynamic_prompt` 专门用来改系统提示：

```python
@before_model
def announce(state, runtime):
    print("  [函数式 before_model] 最后一条是", type(state["messages"][-1]).__name__)
    return None


@dynamic_prompt
def rewrite_prompt(request):
    print("  [dynamic_prompt] 改写系统提示")
    return SystemMessage(content="你是退货客服，只回答退货问题。")
```

```text
=== 函数式中间件 + dynamic_prompt
  [函数式 before_model] 最后一条是 HumanMessage
  [dynamic_prompt] 改写系统提示
  模型收到的第一条: ('system', '你是退货客服，只回答退货问题。')
```

函数式的签名与类里的同名钩子一样：`before_model` 收 `(state, runtime)`，`dynamic_prompt` 收 `request` 并返回一条 `SystemMessage`；要声明可跳转的目的地，用 `@before_model(can_jump_to=[...])`。异步路径另有一套 `a*` 前缀的方法，不是必须实现：同步钩子不给异步版本时，异步路径会退回同步实现，代价是那一段不能 await。

## 预算与重试中间件

`langchain.agents.middleware` 在本机 1.4.7 上导出 16 个中间件类（大纲写的是 19 个，那是别的版本口径）。按用途分四组：预算与重试、上下文与待办、敏感信息、工具与执行。这一组对应第 7 章的 `max_steps` 与第 8 章的失控，六个各跑一遍，剧本是模型永远要调工具或工具永远失败，见 `code/knowledge/ch12_lc_agent/builtin_budget.py` 的 `test_model_call_limit()`：

```python
def test_model_call_limit() -> None:
    agent = create_agent(model=scripted_chat(always_tool), tools=[echo],
                         middleware=[ModelCallLimitMiddleware(run_limit=2)])
    out = agent.invoke({"messages": [{"role": "user", "content": "开始"}]})
    for message in out["messages"]:
        print(f"  {type(message).__name__:<14}{str(message.content)[:52]!r}")
```

```text
=== ModelCallLimitMiddleware(run_limit=2)
  HumanMessage  '开始'
  AIMessage     ''
  ToolMessage   '第0次'
  AIMessage     ''
  ToolMessage   '第1次'
  AIMessage     'Model call limits exceeded: run limit (2/2)'
```

`run_limit` 数的是这一次 invoke 里模型被调了几次，`thread_limit` 数的是同一个 thread 累计几次。到限额之后它不抛错，而是塞一条正文说明超限：停是停下了，但调用方拿到的是一个字符串，不是一个状态字段。其余五个的输出：

```text
=== ModelRetryMiddleware(max_retries=2)
  结果: 第三次成功 | 模型被请求 3 次

=== ModelFallbackMiddleware
  结果: 备用模型回答

=== ToolCallLimitMiddleware(tool_name='echo', run_limit=1)
  ToolMessage: '第0次'
  ToolMessage: "Tool call limit exceeded. Do not call 'echo' again."

=== ToolRetryMiddleware(max_retries=2)
  ToolMessage: '成功:a' | status = success
  工具函数被调用 3 次

=== ToolErrorMiddleware(on_error=...)
  ToolMessage: '工具 boom 失败：下游超时：slow' | status = error
  --- 不传 on_error 时：
  ValueError: ToolErrorMiddleware requires `on_error` and/or `aon_error`.
```

`ModelRetryMiddleware` 重试的是模型调用抛异常，`max_retries=2` 意味着最多三次请求。`ModelFallbackMiddleware` 换的是模型实例，它不重试主模型，与重试是两件事，可以串着用。`ToolCallLimitMiddleware` 与模型限额的差别在它不结束任务：被拦下的调用换成一条 `ToolMessage`，模型还能继续，只是拿不到结果，所以它必须与一个模型限额或一个会收尾的剧本一起用。`ToolErrorMiddleware` 的 `on_error` 是必须的，不传直接报错：把异常变成 `ToolMessage` 是吞掉错误，必须由调用方显式决定吞哪些。`ToolRetryMiddleware` 与它的分工是前者在失败后自己再试，后者只把错误交给模型看。

这一组与第 7 章按步算还是按调用算是同一个问题，框架把两种口径做成了两个参数。`thread_limit` 要跨轮累加，计数存在 state 里，必须配 `checkpointer`：

```python
agent = create_agent(model=scripted_chat(always_tool), tools=[echo],
                     checkpointer=InMemorySaver(),
                     middleware=[ModelCallLimitMiddleware(thread_limit=3)])
config = {"configurable": {"thread_id": "tt"}}
for round_no in range(2):
    out = agent.invoke({"messages": [{"role": "user", "content": f"第{round_no}轮"}]}, config)
    print(f"  第{round_no}轮 消息数={len(out['messages'])} 最后={out['messages'][-1].content!r}")
```

```text
=== ModelCallLimitMiddleware(thread_limit=3) + checkpointer
  第0轮 消息数=8 最后='Model call limits exceeded: thread limit (3/3)'
  第1轮 消息数=10 最后='Model call limits exceeded: thread limit (3/3)'
```

第二个现象比第一个重要：第一轮就已经撞到 3/3，第二轮仍然超限。计数累加在 state 里，不会随轮次清零，所以 `thread_limit` 管的是这条会话的一生，跑满之后后续每一轮都直接得到超限正文。想给每一轮单独限额用 `run_limit`，想给整个会话封顶用 `thread_limit`，两个都想要就都传：

| 想知道什么 | 用哪个 | 要不要 checkpointer |
|---|---|---|
| 这一次想了几个回合 | `ModelCallLimit(run_limit=)` | 不要 |
| 这条会话一共问了几次模型 | `ModelCallLimit(thread_limit=)` | 要 |
| 这一次执行了几次工具 | `ToolCallLimit(run_limit=)` | 不要 |
| 某个工具这条会话被调几次 | `ToolCallLimit(tool_name=, thread_limit=)` | 要 |

第四行是框架比手写细的地方：手写循环里查订单最多查三次要自己维护一个字典，代价是四个口径写在同一行附近，选错了不报错，只会算错账。

## 上下文与安全中间件

第 3 章讲过上下文窗口的账，第 7 章讲过历史长度按步线性长。这一组把压历史做成钩子，两种压法，见 `code/knowledge/ch12_lc_agent/builtin_context.py` 的 `test_summarization()`：

```python
def test_summarization() -> None:
    agent = create_agent(
        model=scripted_chat(three_tools_then_answer), tools=[echo],
        middleware=[SummarizationMiddleware(model=scripted_chat(summarize),
                                            trigger=("messages", 4),
                                            keep=("messages", 1))])
    out = agent.invoke({"messages": [{"role": "user", "content": "回声三次"}]})
    print("  最终消息数:", len(out["messages"]))
```

```text
=== SummarizationMiddleware(trigger=('messages', 4), keep=('messages', 1))
    [摘要模型被调用] 收到 1 条消息
    [摘要模型被调用] 收到 1 条消息
  最终消息数: 4
    HumanMessage  'Here is a summary of the conversation to date:\n\n<摘要>用户要求回声三次'
    AIMessage     ''
    ToolMessage   '第2次'
    AIMessage     '回答'
```

八条消息压成四条：最前面换成一条带摘要的 `HumanMessage`，后面保留最近的消息。`trigger` 可以是条数、token 数或比例，`keep` 决定保留多少。摘要模型被调用了两次，因为每次模型调用前都会重新判断是否超阈值：摘要是每一轮都可能发生的动作，这也是它花额外 token 的原因。`ContextEditingMiddleware` 走另一条路：不改写历史，只在发给模型的请求里把旧工具输出换成占位符。

```text
=== ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=60, keep=1)])
  call0: ['回声三次']
  call1: ['回声三次', 'None', '第0次']
  call2: ['回声三次', 'None', '[cleared]', 'None', '第1次']
  call3: ['回声三次', 'None', '[cleared]', 'None', '[cleared]', 'None', '第2次']
  state 里的工具消息: ['第0次', '第1次', '第2次']
```

对照最后两行：模型收到的是 `[cleared]`，state 里存的是原文。压缩只影响这一次请求，不影响证据。`trigger` 的单位是 token 不是条数（默认 10 万），`keep` 是保留最近几条工具结果；把 `trigger` 当条数写、设成 1 也不会有任何效果。两者怎么选取决于原来的内容还可能被用到吗：

| 情况 | 用哪个 | 理由 |
|---|---|---|
| 早期工具输出只是登账，后面不再引用 | `ContextEditing` | 只删请求里的副本，state 里仍可复查 |
| 早期对话里有结论、有被否掉的方案 | `Summarization` | 这些信息只能靠摘要保留，删了就没了 |
| 上下文超限但还要续跑很多步 | 两个一起 | 先清工具输出，压不下来再摘要 |

`TodoListMiddleware` 加的是一个工具和一个 state 字段：

```text
=== TodoListMiddleware
  state 键: ['messages', 'todos']
  todos: [{'content': '查订单', 'status': 'in_progress'}, {'content': '查政策', 'status': 'pending'}]
```

`write_todos` 是一个工具，模型自己往里写清单，`todos` 落在 state 里。进度仍然不在模型脑子里，但它现在是一个可以被读、被存的字段，下一次请求把它拼回上下文。

敏感信息在同一组里，`PIIMiddleware` 只有两个动作：改或拦，两种都在 `code/knowledge/ch12_lc_agent/builtin_context.py` 里跑过：

```text
=== PIIMiddleware('email', strategy='redact')
  模型收到: 我是 [REDACTED_EMAIL]，查 A1001
  state 里: 我是 [REDACTED_EMAIL]，查 A1001
  --- strategy='block'：
  PIIDetectionError: Detected 1 instance(s) of email in text content
```

注意 `redact` 与上一节的 `[cleared]` 相反：它改的是 state 里的原文，不只是请求。脱敏的要求是原文不再留在系统里，压缩的要求是这次少发一点。`strategy` 还有 `mask`、`hash`，三个 `apply_to_*` 参数类开关决定管哪一段。

## 状态与检查点

第 7 章说状态只存在于 messages 里，第 8 章说丢消息就丢进度。四个参数处理这件事，各管一段，见 `code/knowledge/ch12_lc_agent/state_persist.py`：

| 参数 | 存什么 | 生命周期 | 进不进 checkpoint |
|---|---|---|---|
| `state_schema` | 这一轮任务的字段（进度、计数、标记） | 一次 thread | 进 |
| `context_schema` | 这次调用的只读上下文（租户、用户、权限） | 一次 invoke | 不进 |
| `checkpointer` | 整个 state 按 `thread_id` 存 | 一条线程的全部轮次 | 它就是存档本身 |
| `store` | 跨 thread 的长期数据（事实、偏好） | 跨线程 | 不进 |

```text
=== checkpointer：同一个 thread_id 的两轮
  HumanMessage  '第一轮'
  AIMessage     '第0次回答'
  HumanMessage  '第二轮'
  AIMessage     '第1次回答'
  checkpoint id 前缀: 1f1d2485 （每次运行不同）
  这条线程的历史 checkpoint 数: 6
  新 thread_id 的消息数: 2
```

同一个 `thread_id` 的第二轮拿到了第一轮的历史，换一个 `thread_id` 就只有自己那两条。多轮的记忆在这里不是模型记性好，而是 `checkpointer` 把上一轮的 messages 读回来拼进这一轮请求。六个历史 checkpoint 是中间步骤，每经过一个节点都会存一次；`get_state_history(config)` 返回这条线程的全部快照，拿其中一份的 config 再 `invoke` 就是从那一步重跑。

`state_schema` 与中间件的 `state_schema` 会合并：

```text
=== state_schema：自定义字段
  state 键: ['messages', 'user_tier', 'tool_calls_made']
  user_tier = gold | tool_calls_made = 1
```

`user_tier` 从输入里带进来，`tool_calls_made` 由中间件在 `after_model` 里算。`CountCalls` 类自己声明了 `state_schema`，所以即使 `create_agent` 不传字段也在，但那时输入里传 `user_tier` 会被丢掉。

`context_schema` 给的字段不进 state，只在钩子里通过 `runtime.context` 读：

```text
=== context_schema：不进 checkpoint 的上下文
    runtime.context.tenant = acme
```

把它和 `state_schema` 分开的理由是持久化：租户、权限这类东西每轮都由调用方决定，存进 checkpoint 就会在下一轮变成过期值。`thread_limit` 数的就是同一个 `thread_id` 下的累计次数，所以一条线程既是持久化的单位，也是累计限额的单位。

`store` 是跨线程的那一份：

```text
=== store：跨 thread 的长期存储
    runtime.store 读到: {'window_days': 7}
```

它不是 state 的一部分，读写要显式写代码，键空间也由调用方定：checkpointer 存这次任务走到哪，store 存这个用户是谁。

## 中断与人工审批

第 8 章的失控里有一类只能靠人：工具要执行、但执行不可逆。框架给了两种停法，名字像，作用完全不同。

静态断点 `interrupt_before` / `interrupt_after` 写的是节点名，停的时候不给载荷，见 `code/knowledge/ch12_lc_agent/interrupt_demo.py`：

```text
=== interrupt_before=['tools']
  返回键: ['messages'] | 消息数: 2
  next: ('tools',)
  继续后: ['HumanMessage', 'AIMessage', 'ToolMessage', 'AIMessage'] | 最后: 退款已提交

=== interrupt_after=['tools']
  返回键: ['messages'] | 消息数: 3
  next: ('model',)
  继续后最后: 好了
```

停在 `tools` 之前时，`messages` 里只有提问和模型那条带 `tool_calls` 的消息，`get_state().next` 是 `('tools',)`。继续的办法是 `invoke(None, config)`，不传新输入，接着跑。这两个节点名不是调用方起的：`create_agent` 生成的图只有 `model` 与 `tools`，填别的直接报错：

```text
=== interrupt_before 填不存在的节点
  ValueError: Interrupt node `not_a_node` not found
```

这与上一节那个跳转失败是同一条约束的另一面：静态断点写的是节点名，而节点名由框架定。想要更细的停点，只能用动态中断。动态中断由 `HumanInTheLoopMiddleware` 发起，它带载荷，而且只在指定工具被调用时才停：

```text
=== HumanInTheLoopMiddleware(interrupt_on={'refund': True})
  返回键: ['messages', '__interrupt__']
  消息: [('HumanMessage', '退 A1001 的 99 元'), ('AIMessage', '')]
  中断载荷:
{
  "action_requests": [
    {
      "name": "refund",
      "args": {
        "order_id": "A1001",
        "amount": 99
      },
      "description": "Tool execution requires approval\n\nTool: refund\nArgs: {'order_id': 'A1001', 'amount': 99}"
    }
  ],
  "review_configs": [
    {
      "action_name": "refund",
      "allowed_decisions": [
        "approve",
        "edit",
        "reject",
        "respond"
      ]
    }
  ]
}
  get_state().next: ('HumanInTheLoopMiddleware.after_model',)
  --- 用 approve 恢复：
    HumanMessage  '退 A1001 的 99 元'
    AIMessage     ''
    ToolMessage   '已退款 99 元，订单 A1001'
    AIMessage     '退款已提交'
  恢复后还有中断吗: False
```

载荷里有两段：`action_requests` 是要执行什么，带工具名、参数、可读描述；`review_configs` 是可选怎么答，四个取值 approve / edit / reject / respond。审的人拿这段就能渲染出审批界面。恢复的载荷是有形状的：

```python
resumed = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
```

它要的是一个带 `decisions` 键的字典，每个元素对应一个待审动作，传 `{"type": "accept"}` 会被当成列表下标而报 `TypeError`。选择拒绝时工具不执行，模型收到一条说明：

```text
=== 用 reject 恢复
  HumanMessage  '退 A1001 的 99 元'
  AIMessage     ''
  ToolMessage   'User rejected the tool call for `refund` with reas'
  AIMessage     '退款已提交'
```

最后一句仍然是退款已提交，因为本目录的脚本化后端不看回灌内容、只按序号回放，真实模型读到那条 `ToolMessage` 会改口。这也是脚本化后端的边界：它能证明框架把拒绝写进了消息流，不能证明模型会因此改变答复。四个取值不是同一件事的四档，而是四种不同的动作：

| 取值 | 工具执行吗 | 模型收到什么 |
|---|---|---|
| `approve` | 执行 | 工具的真实返回值 |
| `edit` | 执行，但用审阅者改过的参数 | 改后的返回值，前面加一段 `edit_notice` |
| `reject` | 不执行 | 一条 `status="error"` 的说明，附拒绝理由 |
| `respond` | 不执行 | 审阅者直接给的内容，`status="success"` |

`edit` 与 `respond` 的实际样子：

```text
=== 用 edit 恢复：审的人改参数
  HumanMessage  '退 A1001 的 99 元'
  AIMessage     ''
  ToolMessage   'Note: a human reviewer replaced this tool call before it ran. The call recorded in your message is the one you produced, not the one that executed. This was intentional and authorized. Do not re-issue your original call. Executed instead: refund with arguments {"order_id": "A1001", "amount": 50}.\n\nTool response:\n已退款 50 元，订单 A1001'
  AIMessage     '退款已提交'

=== 用 respond 恢复：审的人代替工具回答
  HumanMessage  '退 A1001 的 99 元'
  AIMessage     ''
  ToolMessage   '线下已退款，不要再发起线上退款'
  AIMessage     '退款已提交'
```

`edit` 那条消息值得读两遍。金额从 99 变成 50，工具体收到的参数也跟着变，而模型收到的那段 `edit_notice` 是一个字段，写了三件事：原来那条调用被替换了、替换是有意的、不要重发。这段文字是给模型看的指令，没有它，模型很可能再发一次，把改过的金额覆盖回去。`respond` 走另一条路：工具体完全没执行，模型直接拿到审阅者写的那句话，适合这件事线下已经办完了的场景。两者都必须显式传 `edited_action` 参数或 `message`，少传时框架在恢复时按决策 `type` 逐项校验并指出缺哪个字段。两种中断的分工：

| | `interrupt_before/after` | `HumanInTheLoopMiddleware` |
|---|---|---|
| 触发条件 | 走到某个节点 | 调用某个工具 |
| 有没有载荷 | 没有，只有 `next` | 有，`__interrupt__` 里带待审动作 |
| 谁来判 | 外部代码看 `get_state()` | 审阅者看载荷 |
| 适合 | 调试、逐步执行、批量断点 | 金额、删除、对外发送这类不可逆操作 |
| 共同前提 | `checkpointer` 必须给 | 同左 |

最后一行是最容易漏的：不给 `checkpointer`，两种中断都用不了，因为停下来之后没有地方存停在哪。中断的实现是停下、把当前状态写进 checkpoint、让 invoke 返回，恢复是读回那份 checkpoint 从断点继续。本章用的是 `InMemorySaver`，所以两次 `invoke` 必须跑在同一个进程里；换成写磁盘的 checkpointer，审批就能跨进程，人稍后点同意，第二个请求带着同一个 `thread_id` 调 `Command(resume=...)` 仍然接得上。

## 流式输出

本章前面的例子都是 `invoke`，一次拿到全部结果。长任务里调用方需要边跑边看，`create_agent` 返回的图支持 `stream` 与 `astream`，`stream_mode` 决定给什么。

`stream_mode="values"` 每经过一个节点给出**完整 state**，适合渲染整段对话，代价是每次都重复前面已经发过的内容。`"updates"` 只给这一步的增量，形状是 `{节点名: 该节点的返回}`，想知道这一步是模型节点还是工具节点就看这个键；调试与日志用这一种。`"messages"` 逐 token 给出 `(消息片段, 元数据)` 二元组，元数据里有 `langgraph_node` 与工具调用 id，前端打字机效果靠它。三种可以同时传，传列表时每次 `stream` 吐出的元组第一项是模式名，按它分支即可。

运行一次 `code/knowledge/ch12_lc_agent/stream_modes.py`，模型用 `FakeListChatModel`（按固定回复逐字符吐出，不联网），同一份输入走两种模式：

```python
def main() -> None:
    print("=== stream_mode='updates'：一步一次增量 ===")
    for step in AGENT.stream(INPUT, stream_mode="updates"):
        for node, payload in step.items():
            for msg in payload.get("messages", []):
                print(f"  {node:10} {type(msg).__name__:16} {msg.content[:26]!r}")

    print("=== stream_mode='messages'：逐 token 的 chunk ===")
    pieces = [chunk.content for chunk, _meta in AGENT.stream(INPUT, stream_mode="messages")]
    print("  拼接   ", "".join(pieces))
    print("  chunk 数", len(pieces))
    print("  前三个 ", pieces[:3])
```

```
=== stream_mode='updates'：一步一次增量 ===
  model      AIMessage        '签收后 7 天内可退，需保持商品完好。'
=== stream_mode='messages'：逐 token 的 chunk ===
  拼接    签收后 7 天内可退，需保持商品完好。
  chunk 数 19
  前三个  ['签', '收', '后']
```

两行结果对应两种用法：`updates` 一步只给一条消息，看不出打字机效果；`messages` 把同一句话拆成 19 个片段，逐条送给前端就是逐字显示。同一次任务要同时对两种消费方供应，就传列表 `stream_mode=["updates", "messages"]`，每次吐出的第一项是模式名。

`astream_events` 给的是事件树，不是 state：节点、模型调用、工具调用各自有开始与结束事件，`tags` 与 `metadata` 把中间件与工具的来源带在事件上。第 10 章讲过这套事件树的父子关系，在 agent 上它的用处是取 token 而不解析 state：对 `on_chat_model_stream` 过滤后取 `chunk.content`。它与 `response_format` 可以并存：结构化的最终答复仍然落在 `structured_response` 上，流式只负责过程中的增量。

## 这一章建立的 6 件事

1. `create_agent` 的十五个参数里只有 `model` 必传；终止、状态、预算、审批分别落在不同参数上，选之前先定口径（模型调用数还是工具调用数）。
2. 六个钩子按"整轮—模型—工具"三层排：`before_*` 顺序执行、`after_*` 反序执行、`wrap_*` 洋葱嵌套；`wrap_model_call` 不调 `handler` 只跳过这一次模型调用，不终止整轮。
3. 自定义中间件有三个失效点：`name` 不能重样、`jump_to` 之后要自己补正文、跳转目的地必须是图里存在的节点；它能改请求、响应、state 与提前结束，不能改图的形状。
4. 内置中间件覆盖预算、重试、上下文、脱敏与审批；`HumanInTheLoopMiddleware` 是唯一会真的停下并带载荷的，且必须配 `checkpointer`。
5. `state_schema` 进 checkpoint、`context_schema` 不进、`store` 跨线程；多轮的"记忆"是 `checkpointer` 把历史读回来拼进请求，不是模型记住了。
6. `stream_mode` 的 `values`/`updates`/`messages` 分别给完整 state、节点增量与逐 token 片段，`astream_events` 给事件树；限额外那件事——任务有没有在推进——框架仍然没替。

## 下一章

本章的 agent 有一个共同的边界：它只能回答工具能查到的事。问一句"我们自己的退货政策窗口是几天"，它的输入里只有这句话，答案只能来自生成——`rag_gap.py` 跑出来的样子是：模型收到 `['我们退货窗口几天']`，答"我们的退货窗口是 7 天"，出处一栏是"无"。加上一个检索工具之后，同一次任务的 `ToolMessage` 里带回了 `{"source": "policy-2024#3", ...}`，答复才第一次有了可以核对的地方。

但这不代表每个请求都该接检索：一次检索就是一次额外的工具往返，而大部分请求根本不需要外部文档。分流一章要回答的是那个更前置的问题——一个请求进来，先判断它值不值得走检索，依据是什么。

---

[← 第 11 章 · LangChain 的工具定义与绑定](./11-LangChain的工具定义与绑定.md)　｜　[卷 3 目录](./docs/INDEX.md#vol3)　｜　[第 13 章 · 分流 →](./13-分流.md)
