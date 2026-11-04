# 第 12 章 · LangChain 的 Agent 与中间件

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./docs/INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F8 create_agent 全参数 —— 十几个参数各管什么，state、context、checkpointer；F9 中间件机制 —— 六个钩子与洋葱顺序，短路规则；F10 内置中间件 —— 19 个内置中间件各管什么（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：第 7 章那个 30 行循环，在框架里被一次 `create_agent` 调用替掉了什么、没替掉什么、代价是什么
> - **示例目录**：`code/knowledge/ch12_lc_agent/`（LangChain 1.4.7；模型是脚本化后端，原理演示，不是模型实测）
> - **读完应当能回答**：给一个 `create_agent` 调用，能指出哪个参数管终止、哪个管状态；能写一个自定义中间件并说清它的钩子什么时候跑；能判断某件事该找内置中间件还是自己写

---

## 目录

[一、循环里挤着的五件事](#一循环里挤着的五件事)\
[二、一次调用的参数表](#二一次调用的参数表)\
[三、钩子与洋葱顺序](#三钩子与洋葱顺序)\
[四、内置中间件的四组](#四内置中间件的四组)\
[五、状态与检查点](#五状态与检查点)\
[六、两种中断](#六两种中断)\
[七、逐项对照](#七逐项对照)\
[八、代价](#八代价)\
[九、覆盖清单](#九覆盖清单)\
[这一章建立的 6 件事](#这一章建立的-6-件事)

## 一、循环里挤着的五件事

第 7 章的 `loop` 只有 20 行，却把五件互不相干的事压在同一个函数体里：

| 压在循环里的 | 代码长什么样 | 换一个任务要改什么 |
|---|---|---|
| 终止 | `for step in range(1, max_steps + 1)` 加 `finish_reason` 分支 | 上限取值、要不要加去重 |
| 状态 | `request["messages"].append(...)` 与 `trace` 列表 | 要不要另存字段、存到哪 |
| 预算 | `max_steps` 一个计数器 | 要不要按调用数再算一遍 |
| 重试 | 循环体里没有，出问题靠外面 `try` | 加在哪一层、退几次 |
| 审批 | 没有 | 在执行工具那一行插一个"停下来问人" |

第 8 章又往上加了守卫：连续空步、结果指纹、参数规范化。这些补丁都落在同一处，模型调用的前后与工具执行的前后，一共四个位置；手写时它们是一串 `if`，每加一件事就多一层缩进，改一处会影响全部任务。

这个形状是结构问题：一个 agent 的全部可变点只有这两处。预算要拦模型调用，重试要包工具执行，摘要要在模型调用前改消息，审批要在工具执行前停下，它们改的是同一个函数里相邻的几行。

框架做的事只有一件：把这四个位置变成可以按名字注册的钩子，把在这个位置做什么从循环体里搬到单独的类里。第 7 章那 30 行的功能没有消失，只是被拆到参数和中间件上；第 8 章那三件事的纠缠也因此解开，每个需求一个独立的类，它们之间唯一的耦合是注册顺序。

## 二、一次调用的参数表

`code/knowledge/ch12_lc_agent/agent_params.py` 把 `create_agent` 在本机 1.4.7 上的签名逐行打出来，也就是第 7 章那 30 行循环在框架里的参数面：

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

`model` 没有默认值，其余十四个都可以不传。这个分布说明了框架的判断：只有用哪个模型是必须回答的，其余全是可选项，不传 `middleware` 就没有钩子，不传 `checkpointer` 就没有持久化，跑起来仍是一个能调工具的最小 agent，这与第 7 章最小循环先跑通再谈别的是同一个次序。逐个说它们管什么：

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

同一个脚本里还有一份把十五个参数都写出来的调用，以及它跑一次的结果：

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

`scripted_chat(respond)` 是本目录的脚本化后端：它把 `ChatOpenAI` 的传输层换成回放，请求照常序列化、响应来自写死的剧本，属于原理演示而不是模型实测。换成真实服务只改这一行：`ChatOpenAI(model="gpt-4.1", api_key=..., base_url=...)`，其余代码不动。

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

第一处：`response_format` 不是让模型输出 JSON 的口头约定，它在工具表里加了一个以类名命名的工具，模型调它一次，框架把参数校验成 `RefundAnswer` 实例，再从 `messages` 之外单独给出 `structured_response`；第 4 章那五种结构化输出做法，到框架里变成了一个参数，底层仍是工具调用加校验。

第二处：`cache` 传了不等于会命中，本机实测两次完全相同的输入，模型被请求两次，`model` 节点的 `cache_policy` 是 `None`：

```text
=== cache：传了 cache 是否命中
  两次相同输入，模型被请求 2 次
  model 节点的 cache_policy: None
```

`cache` 只是把缓存后端挂到图上，节点自己不声明缓存策略就不会写缓存。这说明了框架里一个有这个参数与这个参数起作用是两件事，中间还隔着一层默认值。`middleware` 传的是实例列表，不是类；框架按 `name` 给每个实例建一个节点，所以传进去的顺序直接决定谁包住谁。`name` 只在把 agent 挂进另一张图时有用，

`system_prompt` 是静态的，`dynamic_prompt` 装饰器写出来的中间件是动态的，每次模型调用前重新算一遍系统消息；第 4 章讲提示词要与输入拼装，框架给的两种写法就是构造时定死与每轮重算。

`transformers` 接的是流式事件的变换器，与第 10 章的 `astream_events` 是同一套事件树，顺序固定：先 `ToolCallTransformer`，再中间件声明的，最后是这个参数传的。`response_format` 收三种东西：pydantic 类、`ToolStrategy` 与 `ProviderStrategy`。后两者里，`ToolStrategy` 是强制走工具那条路的策略，`ProviderStrategy` 是走 provider 自带结构化输出的策略；三者对调用方是同一个出口，state 里多一个 `structured_response` 字段，代价是选了哪种策略在调用处看不出来。

## 三、钩子与洋葱顺序

`AgentMiddleware` 在本机 1.4.7 上提供的钩子，加上异步版本一共十二个方法，按位置分四类；顺序用两个只会打日志的中间件就能看清，代码见 `code/knowledge/ch12_lc_agent/middleware_order.py`：

| 位置 | 钩子 | 能做什么 | 典型用途 |
|---|---|---|---|
| 整轮开始前 | `before_agent` | 返回 state 增量 | 初始化字段、检查输入 |
| 每次模型调用前 | `before_model` | 返回 state 增量；可跳转 | 改消息、加提示、拦下这一轮 |
| 每次模型调用前（包住） | `wrap_model_call` | 改请求、**不调 handler 即短路**、调多次 | 重试、换模型、缓存、限流 |
| 每次模型调用后 | `after_model` | 返回 state 增量；可跳转 | 记账、校验输出、触发中断 |
| 每次工具执行前（包住） | `wrap_tool_call` | 改调用、短路、重试 | 审批、模拟、错误兜底 |
| 整轮结束后 | `after_agent` | 返回 state 增量 | 汇总、写库 |

类上还有三个声明位置：`state_schema`、`transformers`、`name`，前两个决定这个中间件往 state 里加什么、能改哪一段流，最后一个 是去重依据。模块级还导出四个装饰器，`hook_config` 是给函数式中间件声明配置的那个，另三个是 `before_model`、`after_model`、`dynamic_prompt`。

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

输出节选两次模型调用之间的那一段，第 7 章的 `trace` 在这里换成了钩子日志：

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

四条规律，全在这张输出里：

1. `before_*` 按注册顺序跑，`after_*` 按反序跑，A 先进 B 后进，出来时 B 先 A 后。
2. `wrap_*` 是最外层先进入、最外层后退出，与它包住的 `handler` 形成嵌套，这就是洋葱这个名字的来处。
3. 顺序不影响结果，只影响谁包住谁；把 A、B 对调，日志顺序跟着对调，任务的输出不变。
4. `after_model` 在 `wrap_model_call` 退出之后才跑，钩子不是按名字排的，是按这一轮的生命周期排的。

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

短路看起来像整轮终止，但它只跳过一次模型调用：`after_model`、`after_agent` 照跑，整轮照常收尾，因为最后一条消息没有 `tool_calls`，循环自然结束；想在这一轮里真停下来，得靠 `before_model`/`after_model` 返回 `{"jump_to": ...}`。

```text
=== 跳到 end 但不补正文
  消息: [('HumanMessage', '回声'), ('AIMessage', '')]

=== 跳到 end 并补一条正文
  消息: [('HumanMessage', '回声'), ('AIMessage', '直接收尾')]
```

跳转有一个代价，代码里看不出来：跳过去时如果不自己补一条正文，最后一条 `AIMessage` 是空的。而且目的地必须是图里真的存在的节点，往 `tools` 跳而这批图里没有工具节点时，`create_agent` 当场失败：

```text
  ValueError: At 'JumpToMissingNode.before_model' node, 'jump_edge' branch found unknown target 'tools'
```

还有一条与实现细节绑定的限制：中间件按 `name` 去重，而 `name` 默认是类名，同一个类注册两次，构造就报错：

```text
  AssertionError: Please remove duplicate middleware instances.
```

要注册两份同类中间件，比如两个不同限额的限流器，就得像 `Tracer` 那样覆写 `name`。这三条，短路不终止、跳转要补消息、名字不能重样，是自定义中间件最常见的三处限制。

钩子的能力边界也在这三例里露出来了：它能改请求、改响应、改状态、提前结束，不能改图的形状。中间件能做的全部事情，都发生在模型节点与工具节点这两个既有位置的里面或前后。这也解释了一个常见误解：中间件不是插件系统，它没有注册新能力的入口。要新增工具，走 `tools=` 或中间件的 `tools` 属性；要新增节点，得改图。不必写类，三个装饰器可以把普通函数变成中间件，其中 `dynamic_prompt` 专门用来改系统提示：

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

函数式的签名与类里的同名钩子一样：`before_model` 收 `(state, runtime)`，`dynamic_prompt` 收 `request` 并返回一条 `SystemMessage`；要声明可跳转的目的地，用 `@before_model(can_jump_to=[...])` 这个带参形式。

异步路径另有一套，名字是在同步钩子前加一个 a：`abefore_model` 是 `before_model` 的异步版，`awrap_tool_call` 是 `wrap_tool_call` 的异步版。它们不是必须实现，同步钩子不给异步版本时异步路径会退回同步实现，代价是那一段不能 await；脚本化后端不存在真正的网络等待，异步版本看不出差别。

## 四、内置中间件的四组

`langchain.agents.middleware` 在本机 1.4.7 上导出 16 个中间件类，大纲写的是 19 个，那是别的版本口径。按用途分四组：

| 组 | 中间件 | 一句话 |
|---|---|---|
| 预算与重试 | `ModelCallLimitMiddleware`、`ModelRetryMiddleware`、`ModelFallbackMiddleware`、`ToolCallLimitMiddleware`、`ToolRetryMiddleware`、`ToolErrorMiddleware` | 拦调用次数、包重试、兜错误 |
| 上下文 | `SummarizationMiddleware`、`ContextEditingMiddleware`、`TodoListMiddleware` | 压历史、清工具输出、加待办 |
| 敏感信息 | `PIIMiddleware`、`HumanInTheLoopMiddleware` | 脱敏或拦截、停下等人 |
| 工具与执行 | `LLMToolSelectorMiddleware`、`LLMToolEmulator`、`FilesystemFileSearchMiddleware`、`ShellToolMiddleware`、`ProviderToolSearchMiddleware` | 收窄工具表、模拟工具、给文件与 shell |

### 4.1 预算与重试

预算与重试这一组直接对应第 7 章的 `max_steps` 与第 8 章的失控。`code/knowledge/ch12_lc_agent/builtin_budget.py` 里六个各跑一遍，剧本是模型永远要调工具，或工具永远失败：

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

`run_limit` 数的是这一次 invoke 里模型被调了几次，`thread_limit` 数的是同一个 thread 累计几次。到限额之后它不抛错，而是塞一条正文说明超限、让整轮正常结束，这正是第 7 章第 4 节讲的超步之后该说什么的框架版：停是停下了，但调用方拿到的是一个字符串，不是一个状态字段。

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

`ModelRetryMiddleware` 重试的是模型调用抛异常，`max_retries=2` 意味着最多三次请求。`ModelFallbackMiddleware` 换的是模型实例，主模型抛错就换下一个，它不重试主模型，所以和重试是两件事。

`ToolCallLimitMiddleware` 与模型限额的差别在它不结束任务：被拦下的那次调用换成一条 `ToolMessage`，模型还能继续，只是拿不到工具结果。所以它必须和一个模型限额或一个会收尾的剧本一起用，单独用会得到一个一直要工具、一直被拦的循环。`ToolErrorMiddleware` 的 `on_error` 是必须的，不传直接报错。这条设计是对的：把异常变成 `ToolMessage` 是吞掉错误，必须由调用方显式决定吞哪些。`ToolRetryMiddleware` 与 `ToolErrorMiddleware` 的分工：前者在失败后自己再试，后者不重试、只把错误交给模型看；先重试、重试完还不成就交出去，是两个一起用。这一组与第 7 章 2.3 讲的按步算还是按调用算是同一个问题，框架把两种口径做成了两个参数。

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

第二个现象比第一个重要：第一轮就已经撞到 3/3，第二轮仍然超限。因为计数是像消息列表那样累加在 state 里的，不会随轮次清零，`thread_limit` 管的是这条会话的一生，不是每一轮的上限；一条线程跑满之后，后续每一轮都会直接得到那句超限正文。

| 想知道什么 | 用哪个 | 要不要 checkpointer |
|---|---|---|
| 这一次想了几个回合 | `ModelCallLimit(run_limit=)` | 不要 |
| 这条会话一共问了几次模型 | `ModelCallLimit(thread_limit=)` | 要 |
| 这一次执行了几次工具 | `ToolCallLimit(run_limit=)` | 不要 |
| 某个工具这条会话被调几次 | `ToolCallLimit(tool_name=, thread_limit=)` | 要 |

这里的第四行是框架比手写细的地方：第 7 章手写循环里查订单最多查三次要自己维护一个字典，框架给了一个参数。但它也带来第七节要讲的代价，四个口径写在同一行附近，选错了不会报错，只会算错账。

### 4.2 上下文与待办

第 3 章讲过上下文窗口的账，第 7 章讲过历史长度是按步线性长的。这一组把压历史做成钩子，三种压法，代码见 `code/knowledge/ch12_lc_agent/builtin_context.py`：

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

八条消息压成四条：最前面换成一条带摘要的 `HumanMessage`，后面保留最近的消息。`trigger` 可以是 `("messages", 4)`、`("tokens", 3000)`、`("fraction", 0.8)`，`keep` 决定保留多少；摘要模型被调用了两次，因为每次模型调用前都会重新判断是否超阈值，摘要不是一次性动作，是每一轮都可能发生的动作。

```text
=== ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=60, keep=1)])
  call0: ['回声三次']
  call1: ['回声三次', 'None', '第0次']
  call2: ['回声三次', 'None', '[cleared]', 'None', '第1次']
  call3: ['回声三次', 'None', '[cleared]', 'None', '[cleared]', 'None', '第2次']
  state 里的工具消息: ['第0次', '第1次', '第2次']
```

对照输出末尾两条：模型收到的是 `[cleared]`，state 里存的是原文，压缩只影响这一次请求，不影响证据；第 7 章 5.3 说上限截断之后不能丢掉历史，框架在这里的做法是请求瘦身、存档不动。`trigger` 的单位是 token 不是消息条数，默认 10 万，把它当条数写不会有效果。

| 情况 | 用哪个 | 理由 |
|---|---|---|
| 早期工具输出只是登账，后面不再引用 | `ContextEditing` | 只删请求里的副本，state 里仍可复查 |
| 早期对话里有结论、有被否掉的方案 | `Summarization` | 这些信息只能靠摘要保留，删了就没了 |
| 上下文超限但还要续跑很多步 | 两个一起 | 先清工具输出，压不下来再摘要 |

两者怎么选，取决于原来的内容还可能被用到吗：

两者的分工在上下文装配一章里会变成一条装配顺序：先放必须保留的、再放可压缩的、最后放可丢的，框架的两个中间件正好对应后两类。

```text
=== TodoListMiddleware
  state 键: ['messages', 'todos']
  todos: [{'content': '查订单', 'status': 'in_progress'}, {'content': '查政策', 'status': 'pending'}]
```

`TodoListMiddleware` 加的是一个工具和一个 state 字段，它注册一个叫 `write_todos` 的工具，模型自己往里写清单，`todos` 落在 state 里。这是把第 7 章进度只存在于调用方代码里这件事翻了个面：进度仍然不在模型脑子里，但它现在是一个可以被读、被存的字段。

### 4.3 敏感信息

`PIIMiddleware` 只有两个动作：改或拦，脚本见 `code/knowledge/ch12_lc_agent/builtin_tools.py`：

```text
=== PIIMiddleware('email', strategy='redact')
  模型收到: 我是 [REDACTED_EMAIL]，查 A1001
  state 里: 我是 [REDACTED_EMAIL]，查 A1001
  --- strategy='block'：
  PIIDetectionError: Detected 1 instance(s) of email in text content
```

注意 `redact` 与 `ContextEditingMiddleware` 的 `[cleared]` 相反：它改的是 state 里的原文，不只是请求。这个差别是故意的，脱敏的要求是原文不再留在系统里，压缩的要求是这次少发一点；`strategy` 还有 `mask`、`hash`，内置类型是 email、credit_card、ip、mac_address、url 五种。

### 4.4 工具收窄

工具一多，请求里的 schema 就占掉大量 token，模型挑错的概率也上升，第 6 章算过这笔账。两个中间件处理这件事，方向相反，代码见 `code/knowledge/ch12_lc_agent/builtin_tools.py`：

```text
=== LLMToolSelectorMiddleware(max_tools=2, always_include=['refund'])
    [选择器] 收到 2 条消息，从中挑工具
  主模型看到的工具: ['weather', 'refund']
  最后: 完成
  --- 选了一个不在工具表里的名字：
  ValueError: Model selected invalid tools: ['refund']
```

选择器自己是一次模型调用：拿用户的问题和工具清单，返回 `{"tools": [...]}`，框架据此改写这次请求的工具表。`always_include` 里的工具退出候选池、直接保留，所以选择器再点名它们就是非法选择；这条错误比它看起来重要，选择器的输出是一个会被校验的结构，名字对不上就整轮失败。

```python
agent = create_agent(model=scripted_chat(respond), tools=[refund2],
                     middleware=[LLMToolEmulator(
                         model=scripted_chat(lambda i, body: chat_completion(
                             content="[模拟] 退款已受理，未真实执行")))])
```

```text
=== LLMToolEmulator
  ToolMessage: '[模拟] 退款已受理，未真实执行'
  真实工具函数被调用次数: 0
```

`LLMToolEmulator` 走另一条路：工具照常被调用，但工具体不执行，返回值来自模型；它需要一个 `model=`，默认是 `anthropic:claude-sonnet-4-5`，而 `langchain_anthropic` 是 anthropic 的 LangChain 包，本机没装，不传就 `ModuleNotFoundError`。用途是评测，第 6 章讲过工具往返的形状，评测模型会不会正确发起调用时，让真实工具执行既慢又有副作用。

这两个中间件改的都是模型看到什么，不是系统做了什么：选择器让模型少看到几个工具，模拟器让模型看到一个假的执行结果，真实工具表与副作用都没变，所以它们适合压在评测与调试路径上，不适生产主路径。

### 4.5 执行环境

`code/knowledge/ch12_lc_agent/builtin_tools.py` 里的 `FilesystemFileSearchMiddleware` 直接给两个工具：

```text
=== FilesystemFileSearchMiddleware
  注册的工具: ['glob_search', 'grep_search']
  工具返回: '/cn.md\n/price.md\n/policy.md'
  工具返回: '/policy.md:2:window: 7 days'
  --- 同一个目录里搜中文：
  grep_search: 'No matches found'
```

`path` 参数要传目录，`"/"` 表示根，传单个文件名匹配不到任何东西，报错信息是 `No matches found`，看起来像文件里没有这个词。`use_ripgrep=False` 表示走纯 Python 兜底，本机没有安装 `rg`，于是含中文的文件整篇匹配不到：兜底实现按非 UTF-8 解码，一条也搜不出来，这个失败不报错、只返回空结果。

```text
=== ShellToolMiddleware（本机三次尝试）
  [powershell] 'Error: Command timed out after 10.0 seconds.'
  [cmd.exe /Q] 'Error: Command timed out after 10.0 seconds.'
  [默认（不传 shell_command）] FileNotFoundError: [WinError 2] 系统找不到指定的文件。
```

`ShellToolMiddleware` 在本机三次都没跑起来：它开的是一个常驻 shell 会话，靠写一行命令加等一个结束标记来同步，这套协议按 POSIX shell 设计；Windows 上不传 `shell_command` 时默认 shell 不存在，传 PowerShell 或 `cmd.exe` 会启动成功但等不到结束标记，十秒后超时。

```text
=== ProviderToolSearchMiddleware
  TypeError: unsupported operand type(s) for +: 'NoneType' and 'NoneType'
```

`ProviderToolSearchMiddleware` 把工具标成延迟加载，让 provider 在服务端按需取 schema。OpenAI 这条路走 Responses API，而脚本化后端回放的是 `chat.completions` 形状，所以在解析 usage 时崩在 `None + None` 上，它需要真实的 OpenAI 或 Anthropic 服务。

## 五、状态与检查点

第 7 章说状态只存在于 messages 里，第 8 章说丢消息就丢进度。`code/knowledge/ch12_lc_agent/state_persist.py` 里的四个参数处理这件事，各管一段：

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

同一个 `thread_id` 的第二轮拿到了第一轮的历史，换一个 `thread_id` 就只有自己那两条。多轮的记忆在这里不是模型记性好，而是 `checkpointer` 把上一轮的 messages 读回来、拼进这一轮请求；第 2 章讲每次调用相互独立，到框架里就是这一行代码。

六个历史 checkpoint 是中间步骤：每经过一个节点都会存一次，所以能回退到任意一步。`get_state_history(config)` 返回这条线程的全部快照，拿其中一份的 config 再 `invoke` 就是从那里重跑；代价是每个节点一份，长任务里存档数量与步数同阶，清理策略要另外定。

```text
=== state_schema：自定义字段
  state 键: ['messages', 'user_tier', 'tool_calls_made']
  user_tier = gold | tool_calls_made = 1
```

`state_schema` 与中间件的 `state_schema` 会合并：`user_tier` 从输入里带进来，`tool_calls_made` 由中间件在 `after_model` 里算。计数用的中间件自己声明了 `state_schema`，所以即使 `create_agent` 不传，字段也在，但那时输入里传 `user_tier` 会被丢掉，两处都声明最稳。

```text
=== context_schema：不进 checkpoint 的上下文
    runtime.context.tenant = acme
```

`context_schema` 给的字段不进 state，只在钩子里通过 `runtime.context` 读。把它和 `state_schema` 分开的理由是持久化：租户、权限这类东西每轮都由调用方决定，存进 checkpoint 就会在下一轮变成过期值。还有一个更实际的理由：`thread_id` 由调用方给，一旦它被复用，存在 state 里的租户字段就会串到别人身上；上下文参数每次都重新传，复用 `thread_id` 也不会串。第 11 章讲持久化与幂等时，哪些字段该跟着任务走是一个必须回答的问题。

`thread_id` 与限额的关系也要说清：`thread_limit` 数的就是同一个 `thread_id` 下的累计次数。所以一条线程在框架里有两重身份，既是持久化的单位，也是累计限额的单位；设成用户 id 就是每个用户一生能用几次模型，设成会话 id 就是每次对话的上限。

```text
=== store：跨 thread 的长期存储
    runtime.store 读到: {'window_days': 7}
```

`store` 是跨线程的那一份，它不是 state 的一部分，读写都要显式写代码，键空间也由调用方定。这与长期记忆一章的分工一致：checkpointer 存这次任务走到哪，store 存这个用户是谁。

## 六、两种中断

第 8 章的失控里有一类只能靠人：工具要执行、但执行不可逆，`code/knowledge/ch12_lc_agent/interrupt_demo.py` 里的两种停法名字像，作用完全不同。

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

静态断点 `interrupt_before` / `interrupt_after` 写的是节点名，停的时候不给任何载荷。停在 `tools` 之前时，`messages` 里只有提问和模型那条带 `tool_calls` 的消息，`get_state().next` 是 `("tools",)`，继续的办法是 `invoke(None, config)`，不传新输入。

```text
=== interrupt_before 填不存在的节点
  ValueError: Interrupt node `not_a_node` not found
```

这两个节点名不是调用方起的：`create_agent` 生成的图只有 `model` 与 `tools` 两个节点，填别的直接报错。这与第三节那个跳转失败是同一条约束的另一面，静态断点写的是节点名，而节点名由框架定，想要更细的停点只能用动态中断。

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

动态中断由 `HumanInTheLoopMiddleware` 发起，它带载荷，而且只在指定工具被调用时才停。载荷里有两段：`action_requests` 是要执行什么，带工具名、参数、可读描述；`review_configs` 是允许怎么答，四个取值 approve / edit / reject / respond。

```python
resumed = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
```

恢复的载荷是有形状的，不是随便一个值。写成 `Command(resume=[{"type": "accept"}])` 会报 `TypeError: list indices must be integers or slices, not str`，它要的是一个带 `decisions` 键的字典，每个元素对应一个待审动作。

```text
=== 用 reject 恢复
  HumanMessage  '退 A1001 的 99 元'
  AIMessage     ''
  ToolMessage   'User rejected the tool call for `refund` with reas'
  AIMessage     '退款已提交'
```

选择拒绝时，工具不执行，模型收到一条说明。最后一句仍然是退款已提交，因为脚本化后端不看回灌内容、只按序号回放，真实模型读到那条 `ToolMessage` 会改口；这也是脚本化后端的边界，它能证明框架把拒绝写进了消息流，不能证明模型会因此改变答复。

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

`edit` 那条消息值得读两遍。金额从 99 变成 50，工具体收到的参数也跟着变，而模型收到的那段被框架叫作 `edit_notice` 的说明明确写了三件事：原来那条调用被替换了、替换是有意的、不要重发；这段文字是给模型看的指令，不是给人看的日志。

没有它，模型很可能以为自己的调用失败了，再发一次，把改过的金额覆盖回去。`respond` 走另一条路：工具体完全没执行，模型直接拿到审阅者写的那句话，并且 `status` 是 `success`，适合这件事线下已经办完了、别让 agent 再动一次。两者都必须显式传 `edited_action` 或 `message`，少传字段时框架按决策 `type` 逐项校验，报错会指出缺了哪个。

| | `interrupt_before/after` | `HumanInTheLoopMiddleware` |
|---|---|---|
| 触发条件 | 走到某个节点 | 调用某个工具 |
| 有没有载荷 | 没有，只有 `next` | 有，`__interrupt__` 里带待审动作 |
| 谁来判 | 外部代码看 `get_state()` | 审阅者看载荷 |
| 适合 | 调试、逐步执行、批量断点 | 金额、删除、对外发送这类不可逆操作 |
| 共同前提 | `checkpointer` 必须给 | 同左 |

两种中断的分工：静态断点看的是走到哪个节点，动态中断看的是调用哪个工具；前者没有载荷只有 `next`，后者在 `__interrupt__` 里带待审动作，适合金额、删除、对外发送这类不可逆操作。

最容易漏的一条是不给 `checkpointer`，两种中断都用不了，因为停下来之后没有地方存停在哪。中断的实现是在节点里停下、把当前状态写进 checkpoint、让 invoke 返回，恢复是读回那份 checkpoint 从断点继续；本章用 `InMemorySaver`，所以两次 `invoke` 必须跑在同一个进程里。

换成写磁盘或数据库的 checkpointer，审批就能跨进程：第一次调用停下并返回载荷，人过半小时点了同意，第二个请求带着同一个 `thread_id` 调 `Command(resume=...)`，仍然接得上。`description_prefix` 改的是载荷里那句文案，`interrupt_mode` 决定多个待审动作是合成一个还是分成多个。

## 七、逐项对照

把第 7 章那份循环与 `create_agent` 摆在一起，同一份三步剧本，顺序是查订单、查政策、作答，脚本见 `code/knowledge/ch12_lc_agent/handwritten_vs_framework.py`：

```text
=== 手写循环 ===
  status = done | steps = 3 | messages = 6
  trace  = ['1: get_order', '2: get_policy']

=== create_agent ===
  消息: ['HumanMessage', 'AIMessage', 'ToolMessage', 'AIMessage', 'ToolMessage', 'AIMessage']
  模型调用次数: 3
  state 键: ['messages'] （没有 status / steps）

=== create_agent + ModelCallLimitMiddleware(run_limit=1) ===
  模型调用次数: 1
  最后一条: Model call limits exceeded: run limit (1/1)
```

模型调用次数一样，消息条数一样。差别全在留下了什么：手写版返回 `status` 与 `steps`，框架版的 state 里只有 `messages`。逐项拆开：

| 对照项 | 第 7 章手写 | 框架里 | 差在哪 |
|---|---|---|---|
| 终止 | `Run.status` 三态 + `max_steps` | 循环由图结构决定；限额靠 `ModelCallLimitMiddleware` | 停止信号从"状态字段"变成"一条正文消息"，超步与空转不可区分 |
| 步数 | `Run.steps` | 没有，要自己数 `AIMessage` 或用钩子记 | 记账要自己补 |
| 状态 | `request["messages"]` + 自定义字段 | `state_schema` + `checkpointer` | 从"一个 dict"变成"按 thread 存档"，多了恢复能力 |
| 预算 | `max_steps` 一个数 | `run_limit`/`thread_limit`/`ToolCallLimit` | 口径分开（模型调用数 vs 工具调用数），比手写细 |
| 审批 | 自己插一行 `input()` | `HumanInTheLoopMiddleware` + `Command(resume=...)` | 从"阻塞在进程里"变成"存下来、换个进程继续" |
| 工具执行 | `execute(call)` 一行 | `wrap_tool_call` 钩子链 | 执行前后都能插东西，但顺序要按洋葱推 |
| 重试 | 外面包 `try` | `ModelRetry`/`ToolRetry` 两个中间件 | 模型与工具分开重试，策略可配 |
| 裁剪 | 自己改 messages | `Summarization`/`ContextEditing` | 一个改 state、一个只改请求，语义更清楚 |
| 去重（空转） | `seen_calls` 签名比对 | 没有对应中间件 | **这一项框架没替**，仍要自己写 |

最后一行值得单独说。第 8 章 5.1 讲空转判断只能拦住一模一样的调用，换参数打转拦不住；框架的 16 个中间件里没有一个做这件事，限额只能等它撞墙，撞完给一句 `Model call limits exceeded`。

有没有在往前走是一个任务语义问题，框架不知道任务是什么，所以它替不了。另一处没替的是成本曲线：第 7 章算过第 k 步的 prompt 包含前 k−1 步的全部内容，总成本随步数超线性增长，框架没有改变这条曲线，`Summarization` 只是把斜率压下来，而且摘要自己也要一次模型调用。

这就是替掉了什么、没替掉什么的答案：循环骨架、工具执行与回灌、多轮存档、限额计数、重试退避、摘要与裁剪、审批暂停都替掉了，因为它们有统一的形状；任务是否在推进、什么算答对、限额撞上之后怎么向用户交代，这些依赖任务本身，只能是调用方的事。

三态丢在哪，可以补在哪：`after_model` 能拿到这一步模型调了几次工具，`wrap_tool_call` 能拿到每次执行，想恢复第 7 章的 `status` 与 `steps`，就在中间件里累加 `steps`、记调用签名做去重。框架不提供三态，但提供的钩子足够把它写回去。至于答完还是超步，框架给的是一个字符串正文而不是字段，这条差异没法在框架内消除，只能看最后一条消息是不是以 `Model call limits exceeded` 开头。

## 八、代价

三条代价，都是这一章里真实撞到的，想看中间件那一层只有 `code/knowledge/ch12_lc_agent/middleware_order.py` 的钩子日志。参数多，而且参数之间会互相影响。十五个参数里，终止散在四个地方：图结构、`ModelCallLimit`、`ToolCallLimit`、剧本自己收尾；想让一个任务最多五步就停，得先回答步是模型调用还是工具调用，而第 7 章手写版的 `max_steps` 只有一种含义。

版本升级会改这些名字与默认值。本章所有签名都是 `inspect.signature` 打出来的，锁在 1.4.7；大纲写 19 个内置中间件，本机实际 16 个，`LLMToolEmulator` 的默认模型本机装不上。把 `inspect.signature` 那一段留在仓库里，跑一遍就知道这十五个参数有没有变，比读发布说明更直接。

```text
[values] {'messages': [HumanMessage(content='hi', ...)]}
[updates] {'model': {'messages': [AIMessage(content='ok', ...)]}}
```

调试层级变深。第 7 章手写循环出错看 `trace` 就知道第几步；框架里一次 `before_model` 可能被三个中间件包住，一次工具执行可能被两个包住，日志顺序要按洋葱推。`debug=True` 打的是节点级信息，它能说明有哪几个节点、状态怎么变，但不说明哪个中间件改了什么。

还有一处边界必须写清：本章所有输出都来自脚本化后端，它证明的是框架的控制流，不是模型行为。`ModelRetry` 重试三次、`Summarization` 压成四条这些是代码决定的，可以照抄；模型会不会因此答得更好必须换真实服务再量。

一条边界判据：如果任务在三步内就能答完，而且不需要审批、不需要多轮、不需要存档，手写那 20 行更省。框架的收益随要接的东西数量增长，接两件事时手写更省，接到五件以上才划算。

反过来，一旦要按会话累计限额、要暂停等人再恢复、要给不同工具配不同重试策略、要把 agent 挂进另一张图，手写的边际成本会迅速超过框架，这四件事在框架里各有一个参数或中间件。

### 8.1 框架不管的那一段

把第六节的审批与第七节的对照放在一起，会看到一个空缺：框架能停下来等人，但等多久、谁来审、审的人看到什么它不管。`HumanInTheLoopMiddleware` 给的是载荷与恢复接口，剩下的都要自己接：审批请求存哪、超时怎么办、同一个人能不能连着批十次、拒了之后要不要重试。

### 8.2 真实服务的接法

`code/knowledge/ch12_lc_agent/scripted_chat.py` 的第一处写着这句注释，抄在这里：

```python
import os

from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4.1", api_key=os.environ["OPENAI_API_KEY"],
                   base_url="https://api.openai.com/v1")
```

把 `scripted_chat(respond)` 换成这个实例，其余代码不动。但换过去之后有四件事会变：剧本消失，模型真的会自己决定调几次工具，本章那些三次模型调用、两次工具调用的数字不再成立；`usage_metadata` 有了真实值；重试与退避的参数要按真实延迟调；`ProviderToolSearchMiddleware` 才能跑。

前三条都会让本章某些输出不再可复现，这正好是脚本化后端证明控制流、不证明模型行为这句话的具体含义。

## 九、覆盖清单

本章对 1.4.7 这套 API 的覆盖，逐项交代清楚，没跑的不算讲过：

| 中间件 | 本章在哪 | 跑到什么程度 |
|---|---|---|
| `ModelCallLimitMiddleware` | 4.1 | 跑通，超限后注入正文并结束 |
| `ModelRetryMiddleware` | 4.1 | 跑通，失败两次后成功 |
| `ModelFallbackMiddleware` | 4.1 | 跑通，换成备用实例 |
| `ToolCallLimitMiddleware` | 4.1 | 跑通，被拦的调用换成说明 |
| `ToolRetryMiddleware` | 4.1 | 跑通，工具体调用三次 |
| `ToolErrorMiddleware` | 4.1 | 跑通，异常变成 `status="error"` |
| `SummarizationMiddleware` | 4.2 | 跑通，八条压成四条 |
| `ContextEditingMiddleware` | 4.2 | 跑通，请求里出现占位符 |
| `TodoListMiddleware` | 4.2 | 跑通，`todos` 进 state |
| `PIIMiddleware` | 4.3 | 跑通，脱敏与拦截两种 |
| `HumanInTheLoopMiddleware` | 六 | 跑通，四种决策各一次 |
| `LLMToolSelectorMiddleware` | 4.4 | 跑通，工具表被改写 |
| `LLMToolEmulator` | 4.4 | 跑通，工具体调用零次 |
| `FilesystemFileSearchMiddleware` | 4.5 | 跑通，附中文匹配失败 |
| `ShellToolMiddleware` | 4.5 | **未跑通**，Windows 会话协议 |
| `ProviderToolSearchMiddleware` | 4.5 | **未跑通**，需要真实 provider |

十六个里跑通十四个，两个受环境限制。没讲的部分同样列清楚：`transformers` 只说了顺序没有跑，要流式消费才看得到效果，那是第 10 章的射程；两个 ExecutionPolicy 只提了名字，本机没有 Docker。

这份清单的用法是改代码之前先看它跑通过没有。上面每一个跑通都对应本目录一个脚本的一行输出，重跑一遍能复现；两个未跑通也各自贴了失败原文，照着失败信息判断是环境问题还是用法问题。

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
