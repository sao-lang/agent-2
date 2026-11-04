# 第 9 章 · LangChain 包结构与消息

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./docs/INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F1 包结构与模型接入 —— init_chat_model 的参数矩阵与三种结构化输出策略；F2 消息与内容块 —— 四种消息类型，content 与 content_blocks 的区别（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：一次调用在框架里被拆成哪几个对象，每个对象替掉前八章手写的哪一段，剩下的哪一段仍然要自己写
> - **示例目录**：`code/knowledge/ch09_lc_basic/`
> - **读完应当能回答**：给一段 LangChain 代码，说出每个参数落在哪一层、对应手写版的哪几行、以及框架没有接管的部分在哪

---

## 目录

[四个包的分工](#四个包的分工)\
[模型初始化的参数](#模型初始化的参数)\
[消息类型与内容块](#消息类型与内容块)\
[消息裁剪](#消息裁剪)\
[流式三接口](#流式三接口)\
[结构化输出的策略](#结构化输出的策略)\
[批量与缓存](#批量与缓存)\
[这一章建立的 8 件事](#这一章建立的-8-件事)

版本以本机安装为准：`langchain` 1.4.7、`langchain-core` 1.7.0、`langchain-openai` 1.1.9、`langchain-community` 0.4.2。框架的符号在小版本之间会挪位置，下面的报错都是本机跑出来的。 示例目录里的 `scripted_chat.py` 是脚本化后端：给 `ChatOpenAI` 换掉 httpx 的传输层，请求照常编码成真实的 chat completion 请求，响应来自脚本。所有输出都由它跑出，是原理演示，不是模型实测。换真实服务时只改构造模型那一处：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", api_key="sk-...", base_url="https://api.openai.com/v1")
```

`base_url` 指向任何兼容 OpenAI 协议的服务都可以，其余代码不动。

## 四个包的分工

第 1 到第 8 章的手写代码里，有五段几乎每个项目都要重写一遍：拼请求体、读响应、数 token 与裁剪、构造结构化输出、装配工具往返。它们的输入输出与业务无关，写法却与厂商、调用形态有关，所以有四个互相独立的可变点：

| 可变点 | 变一次要改什么 | 谁在变 |
|---|---|---|
| 厂商 | URL、认证头、字段名、`finish_reason` 的取值集合 | 换模型、接网关、做 A/B |
| 调用形态 | 同步、流式、批量、可配置参数 | 界面要打字机效果、后台要跑批 |
| 输出结构 | 纯文本、JSON、工具调用 | 从"给人看"变成"给程序用" |
| 历史长度 | 装得下、要裁剪、要压缩 | 对话轮次增加 |

四个可变点两两组合就是十几种写法。框架把它们分别收进四样东西：厂商进适配包，调用形态进 `invoke`、`stream`、`astream` 三个接口，输出结构进 `with_structured_output`，历史长度进 `trim_messages`。它搬字段，不做判断：一条回复能不能用是第 1 章的分支，花了多少钱是第 3 章的计价，值合不合理是第 4 章的语义校验，循环要不要继续是第 7 章与第 8 章的事。

第 1 章那种手拼请求体的代码，装完之后遇到的第一个问题是 import：1.x 的代码分布在四个发布包里，包名和 import 路径不同名，对不上时报错不会告诉该装哪个。`code/knowledge/ch09_lc_basic/versions.py` 把版本、依赖区间和符号归属一起打出来：

```python
import importlib
import importlib.metadata as md

PACKAGES = ("langchain-core", "langchain", "langchain-openai", "langchain-community")


def installed_versions():
    """每个包的已装版本，以及它对 langchain-core 的版本要求。"""
    rows = []
    for pkg in PACKAGES:
        version = md.version(pkg)
        reqs = [r for r in (md.requires(pkg) or []) if "langchain-core" in r and "extra" not in r]
        rows.append((pkg, version, reqs[0] if reqs else "-"))
    return rows


def who_provides(symbol, modules):
    """在候选模块里找 `symbol` 由谁提供。"""
    found = []
    for module_name in modules:
        module = importlib.import_module(module_name)
        if hasattr(module, symbol):
            found.append(module_name)
    return found
```

```
langchain-core       1.7.0      要求 -
langchain            1.4.7      要求 langchain-core<2.0.0,>=1.6.13
langchain-openai     1.1.9      要求 langchain-core<2.0.0,>=1.2.11
langchain-community  0.4.2      要求 langchain-core<2.0.0,>=1.4.0

init_chat_model  来自 ['langchain.chat_models']
ChatOpenAI       来自 ['langchain_openai']
trim_messages    来自 ['langchain_core.messages']
BaseTool         来自 ['langchain_core.tools']
```

第三列是每个包对 `langchain-core` 的需求区间：`langchain 1.4.7` 要求 core `>=1.6.13`，`langchain-openai 1.1.9` 要求 `>=1.2.11`，取交集之后 core 的最低版本由最严的那个包决定。把 core 停在 1.2 而 langchain 升到 1.4.7，pip 会直接拒绝安装；但这只在装的时候成立：用了 `--no-deps` 或镜像缓存了旧 wheel，装得上，跑起来才发现少了符号。
第二块输出是符号归属：入口在 `langchain`，厂商适配在 `langchain-openai`，消息与裁剪在 `langchain-core`，这是每个例子 import 行的依据。切法从依赖方向看得出来：core 只放与厂商无关的东西，`langchain-openai` 放与一家 SDK 对齐的请求编码与响应解析。

包拆开之后旧路径就消失了。`versions.py` 的第三块把四个旧 import 各跑了一遍：

```python
def try_import(module_name, symbol=None):
    """跑一次真正的 import 语句，把失败形态原样打出来。"""
    statement = f"import {module_name}" if symbol is None else f"from {module_name} import {symbol}"
    try:
        exec(statement, {})
        return f"成功：{statement}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"
```

```
langchain.chains         -> ModuleNotFoundError: No module named 'langchain.chains'
langchain.memory         -> ModuleNotFoundError: No module named 'langchain.memory'
langchain.chat_models    -> ImportError: cannot import name 'ChatOpenAI' from 'langchain.chat_models' (C:\Users\30895\AppData\Roaming\Python\Python314\site-packages\langchain\chat_models\__init__.py)
langchain.text_splitter  -> ModuleNotFoundError: No module named 'langchain.text_splitter'
```

四条报错有同一个来源：0.x 到 1.x 的拆包。`langchain.chains`、`langchain.memory` 不再是 `langchain` 的子模块，迁到 `langchain-classic`；文本切分迁到 `langchain-text-splitters`；厂商类迁到各自的 `langchain-<vendor>` 包。报错只说模块不存在，不说该装哪个包。第三条是 `ImportError`：`langchain.chat_models` 这个模块还在，只是里面不再有 `ChatOpenAI`。

## 模型初始化的参数

第 1 章的请求体里，`model` 是字符串、`temperature` 是数字，两个值都写在业务代码里。换厂商要动 URL、认证头、请求体那几行，换一种参数实验也要动这几行。`init_chat_model` 把这一段收成一个函数：按厂商找到适配类，把参数透传下去。先核对签名，`code/knowledge/ch09_lc_basic/model_access.py` 里的 `show_signature`：

```python
import inspect

from langchain.chat_models import init_chat_model


def show_signature():
    """打印真实签名与每个参数的默认值。"""
    for name, param in inspect.signature(init_chat_model).parameters.items():
        print(f"{name:<18} {str(param.kind):<20} 默认={param.default!r}")
```

```
model              POSITIONAL_OR_KEYWORD 默认=None
model_provider     KEYWORD_ONLY         默认=None
configurable_fields KEYWORD_ONLY         默认=None
config_prefix      KEYWORD_ONLY         默认=None
kwargs             VAR_KEYWORD          默认=<class 'inspect._empty'>
```

| 参数 | 位置 | 管什么 |
|---|---|---|
| `model` | 位置参数 | 模型名。也可以写 `厂商:模型` 的形式，此时不用给 `model_provider` |
| `model_provider` | 仅关键字 | 厂商标识，决定 import 哪个适配包、实例化哪个类 |
| `configurable_fields` | 仅关键字 | 哪些字段留到调用时再定；`"any"` 表示全部 |
| `config_prefix` | 仅关键字 | 可配置字段在 `config` 里的键名前缀 |
| `**kwargs` | 可变关键字 | 原样传给适配类：`api_key`、`base_url`、`http_client`、`timeout`、`max_retries`、`temperature`… |

参数表只能看出传什么，看不出什么时候生效。接下来的四个情形是同一个函数的四种用法，每个都打印返回类型与真实请求体：

```python
import json

import httpx
from scripted_chat import chat_completion

SEEN = []


def handler(request):
    """把请求体留下来，再回放一份响应。"""
    SEEN.append((str(request.url), json.loads(request.content)))
    return httpx.Response(200, json=chat_completion("签收后 7 天内可退。", usage=(24, 9)))


CLIENT = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def build(model=None, **kwargs):
    """统一入口：固定用同一个脚本化传输层。"""
    return init_chat_model(model, api_key="sk-test", http_client=CLIENT, **kwargs)
```

```
== 情形一：model_provider ==
返回类型: ChatOpenAI
content: 签收后 7 天内可退。
请求 URL: https://api.openai.com/v1/chat/completions
请求体里的 model: demo-model

== 情形二：厂商:模型 ==
返回类型: ChatOpenAI
请求体里的 model: demo-model
```

情形一和情形二结果相同，区别只在写法。返回类型是 `ChatOpenAI` 而不是某个通用模型：`init_chat_model` 只做一次映射，拿到 `model_provider="openai"` 就 import `langchain_openai`、实例化 `ChatOpenAI`，其余关键字原样传下去，所以不改变第 1 章那个请求体。这个 URL 是 `base_url` 的默认值；本例里请求没有离开本机，`http_client` 被换成了 `MockTransport`。这也是接兼容端点的前提：URL 由 `base_url` 决定，请求发不发得出去由传输层决定。

```
== 情形三：configurable_fields ==
返回类型: _ConfigurableModel
默认 temperature: None
config 里的 temperature=0.9 -> 0.9
with_config 改成 0.2 -> 0.2
```

`configurable_fields` 把字段从构造期挪到调用期，返回类型变成 `_ConfigurableModel`，字段值在 `invoke` 时才定型：`config={"configurable": {"llm_temperature": 0.9}}` 让这一次请求带 0.9。它替代的是第 1 章把 `temperature` 写进请求体那一行，代价是取模型属性、判断 `isinstance` 都会失效。`config_prefix` 的理由是一次调用里可能有多个对象要配：主模型一个温度、小模型另一个温度、检索器还有一个 `k`，前缀把扁平字典的命名空间分开。

```
== 情形四：base_url ==
base_url 指向本机 8080 后，请求 URL: http://127.0.0.1:8080/v1/chat/completions
```

`base_url` 只改一件事：请求打到哪个主机。自建网关、代理、本地推理服务，只要实现 OpenAI 协议的那几个路径，指过去就能用。

三个真实的失效：

```
== 情形五：config_prefix 写错 ==
键名写 temperature（少了 llm_）-> None
键名写 llm_temperature -> 0.9

== 情形六：参数名写错 ==
构造时: WARNING! foo is not default parameter. foo was transferred to model_kwargs. Please confirm that foo is what you intended.
调用时: TypeError: Completions.create() got an unexpected keyword argument 'foo'

== 情形七：缺 model_provider ==
ValueError: Unable to infer model provider for model='demo-model'. Please specify 'model_provider' directly.

Supported providers: anthropic, anthropic_bedrock, azure_ai, azure_openai, baseten, bedrock, bedrock_converse, bedrock_mantle_anthropic, bedrock_mantle_openai, cohere, deepseek, fireworks, google_anthropic_vertex, google_genai, google_vertexai, groq, huggingface, ibm, langsmith, litellm, meta, mistralai, nvidia, ollama, openai, openrouter, perplexity, together, upstage, xai

For help with specific providers, see: https://docs.langchain.com/oss/python/integrations/providers
```

情形五最危险：一行代码没生效，而且没有报错。设了 `config_prefix="llm"` 后键名必须是 `llm_temperature`，写成 `temperature` 时值被静默丢掉；而它默认是 `None`，判据是看字段在不在。情形六是同类问题的另一种时机：`foo` 不在参数表里，构造时只给一条 `UserWarning` 并塞进 `model_kwargs`，直到发请求才变成 `TypeError`。情形七是唯一立刻失败的。 边界：`init_chat_model` 只解决选类加传参。温度给多少是第 1 章的事，严格 schema、`tool_choice` 强制调用是第 4 章的事。

## 消息类型与内容块

第 1 章的 `messages` 是 dict，键由调用方随便写；框架里消息是四个类，每个类除了 `content` 还多出内容块和元信息。用错字段不会在发送时报错：dict 能编码成任何形状，错误要到回复里才显形。`code/knowledge/ch09_lc_basic/messages.py` 先造出四条消息：

```python
import json

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from scripted_chat import chat_completion, tool_call

SEEN = []


def make_llm(respond):
    """把 ChatOpenAI 接到 `respond(请求体) -> 响应字典` 上。"""

    def handler(request):
        body = json.loads(request.content)
        SEEN.append(body)
        return httpx.Response(200, json=respond(body))

    return ChatOpenAI(model="demo-model", api_key="sk-test",
                      http_client=httpx.Client(transport=httpx.MockTransport(handler), trust_env=False))


def four_roles():
    """四种消息各自的 type 与用途。"""
    messages = [
        SystemMessage("你是退货政策助手，只回答与退货相关的问题。"),
        HumanMessage("订单 A1001 能退吗？"),
        AIMessage("请提供签收时间和商品状态。"),
        ToolMessage(content='{"status": "已签收"}', tool_call_id="call_demo"),
    ]
    for m in messages:
        print(f"{type(m).__name__:<14} type={m.type:<7} content={m.content!r}")
```

```
SystemMessage  type=system  content='你是退货政策助手，只回答与退货相关的问题。'
HumanMessage   type=human   content='订单 A1001 能退吗？'
AIMessage      type=ai      content='请提供签收时间和商品状态。'
ToolMessage    type=tool    content='{"status": "已签收"}'
```

| 类 | `type` | 请求体里的 `role` | 用途 |
|---|---|---|---|
| `SystemMessage` | `system` | `system` | 指令层，第 1 章的第一个字段 |
| `HumanMessage` | `human` | `user` | 调用方的输入 |
| `AIMessage` | `ai` | `assistant` | 模型的历史回复 |
| `ToolMessage` | `tool` | `tool` | 工具结果回灌，第 6 章那一步 |

`type` 与 `role` 不是同一套词：`human` 对应 `user`，`ai` 对应 `assistant`。照抄旧教程的第二种失败形态就在这里：

```
== role 属性 ==
AttributeError: 'SystemMessage' object has no attribute 'role'
```

0.x 的消息对象有 `.role`，1.x 只有 `.type`：写代码时用 `type`，读请求体时看 `role`，混用会得到 `AttributeError` 或永远为假的条件。

```
== 文本回复的两种读法 ==
content: '签收后 7 天内可退。'
content_blocks: [{'type': 'text', 'text': '签收后 7 天内可退。'}]
```

`content` 是这条消息的文本原样；`content_blocks` 是把 `content` 连同其它字段归一化成块的视图。纯文本时两者几乎等价，差别出现在另外两种情况。

```
== 工具调用回复 ==
content: ''
tool_calls: [{'name': 'get_order', 'args': {'order_id': 'A1001'}, 'id': 'call_demo', 'type': 'tool_call'}]
content_blocks: [{'type': 'tool_call', 'name': 'get_order', 'args': {'order_id': 'A1001'}, 'id': 'call_demo'}]
```

模型要动作时 `content` 是空字符串，动作在 `tool_calls` 里，`content_blocks` 里对应一个 `tool_call` 块。第 1 章的手写版里 `content` 是 `null`；框架归一成空字符串，于是没有正文与生成了空内容在 `content` 上分不开，要区分只能看 `tool_calls` 或 `content_blocks`。

另有一处细节：`tool_calls[i]["args"]` 是 dict，请求体里仍然是 JSON 字符串，回灌工具结果时能看清：

```python
def tool_message_round_trip():
    """把工具结果回灌，看请求体里多了什么。"""
    llm = make_llm(lambda body: chat_completion("订单已签收，不能退了。", usage=(60, 12)))
    call = AIMessage(content="", tool_calls=[
        {"name": "get_order", "args": {"order_id": "A1001"}, "id": "call_1", "type": "tool_call"}])
    result = ToolMessage(content='{"status": "已签收"}', tool_call_id="call_1")
    reply = llm.invoke([HumanMessage("订单 A1001 能退吗？"), call, result])
    print("回灌后的请求体 messages:")
    for m in SEEN[-1]["messages"]:
        print("  ", json.dumps(m, ensure_ascii=False))
    print("回复:", reply.content)
```

```
回灌后的请求体 messages:
   {"content": "订单 A1001 能退吗？", "role": "user"}
   {"content": null, "role": "assistant", "tool_calls": [{"type": "function", "id": "call_1", "function": {"name": "get_order", "arguments": "{\"order_id\": \"A1001\"}"}}]}
   {"content": "{\"status\": \"已签收\"}", "role": "tool", "tool_call_id": "call_1"}
回复: 订单已签收，不能退了。
```

三行请求体是这个往返的全部内容。`assistant` 那条的 `content` 在发出时又变回了 `null`，空字符串与 `null` 只在对象层被抹平；`tool` 那条必须带 `tool_call_id`，值等于上一条的 `tool_calls[0].id`，抄错则服务端拒绝或对不上号。

内容块的归一化：

```python
def blocks_are_normalized():
    """content 是原样，content_blocks 是归一化后的块。"""
    message = AIMessage(
        content=[{"type": "text", "text": "图里是一张签收单。"}],
        additional_kwargs={"reasoning_content": "先看表的行和列"},
    )
    print("content:", message.content)
    print("content_blocks:", message.content_blocks)
```

```
content: [{'type': 'text', 'text': '图里是一张签收单。'}]
content_blocks: [{'type': 'reasoning', 'reasoning': '先看表的行和列'}, {'type': 'text', 'text': '图里是一张签收单。'}]
```

`content` 里没有推理内容，`content_blocks` 里有一个 `reasoning` 块，来自 `additional_kwargs` 里的厂商私有字段：读推理过程要读块，读正文读 `content` 就够。用类的理由是编码与解码两个方向都有逻辑，dict 没地方放它。
边界：块类型由适配层决定，各包不同；`content_blocks` 是生成出来的视图，写回去的仍然是 `content`。

### 三类元信息

第 1 章的响应只有四个字段。框架把它们拆成三个属性，其中一个专门装厂商原样；不知道去哪读，代码就退化成只读 `reply.content`，那是第 1 章开头那个写法换个属性名。`code/knowledge/ch09_lc_basic/metadata.py` 把四个属性全打出来：

```python
import json

from langchain_core.messages import HumanMessage
from scripted_chat import chat_completion, scripted_chat


def make_llm(respond):
    """`respond(请求体) -> 响应字典`，交给共享的脚本化后端。"""
    return scripted_chat(lambda index, body: respond(body))


def dump(label, reply):
    print(label)
    print("  content:", repr(reply.content))
    print("  additional_kwargs:", reply.additional_kwargs)
    print("  response_metadata:", reply.response_metadata)
    print("  usage_metadata:", reply.usage_metadata)
    print()
```

```
正常回复：
  content: '签收后 7 天内可退。'
  additional_kwargs: {'refusal': None}
  response_metadata: {'token_usage': {'completion_tokens': 9, 'prompt_tokens': 24, 'total_tokens': 33, 'completion_tokens_details': None, 'prompt_tokens_details': None}, 'model_provider': 'openai', 'model_name': 'demo-model', 'system_fingerprint': None, 'id': 'chatcmpl-demo', 'finish_reason': 'stop', 'logprobs': None}
  usage_metadata: {'input_tokens': 24, 'output_tokens': 9, 'total_tokens': 33, 'input_token_details': {}, 'output_token_details': {}}
```

| 属性 | 装什么 | 对应哪一章 |
|---|---|---|
| `additional_kwargs` | 没能归到正文的厂商字段：`refusal`、`reasoning_content` 之类 | 第 1 章没有对应，是拆包之后多出来的一层 |
| `response_metadata` | 本次响应的事实：`finish_reason`、`model_name`、`id`、`token_usage`、`system_fingerprint` | 第 1 章的 `finish_reason` 与 `usage` |
| `usage_metadata` | 归一化后的三数：`input_tokens`、`output_tokens`、`total_tokens` | 第 3 章 `usage` 三字段，改了个名 |

`usage_metadata` 是第 3 章那三个数的改名版：`prompt_tokens` 变成 `input_tokens`，`completion_tokens` 变成 `output_tokens`，明细拆进两个 `*_details`。同一个数在 `response_metadata["token_usage"]` 里还有一份、用原始字段名，跨厂商的代码只该读第一处：前者由协议层统一，后者由适配层按厂商原样填。`finish_reason` 只有一处，在 `response_metadata` 里，四个取值一个不少，处理分支也一模一样：

```
被拦截的回复：
  content: ''
  additional_kwargs: {'refusal': '无法回答该请求'}
  response_metadata: {'token_usage': {'completion_tokens': 0, 'prompt_tokens': 24, 'total_tokens': 24, 'completion_tokens_details': None, 'prompt_tokens_details': None}, 'model_provider': 'openai', 'model_name': 'demo-model', 'system_fingerprint': None, 'id': 'chatcmpl-demo', 'finish_reason': 'content_filter', 'logprobs': None}
  usage_metadata: {'input_tokens': 24, 'output_tokens': 0, 'total_tokens': 24, 'input_token_details': {}, 'output_token_details': {}}
```

这是第 1 章被拦截那一行的框架读法：`content` 是空字符串，`finish_reason` 是 `content_filter`，另外多了 `refusal` 里的拦截说明。手写版通常把这段说明丢掉，于是被拦截和模型没话说在业务代码里长得一样。四个属性各管一处，缺一个就断一类信息，而它们可能不存在：服务端不回 `usage` 时，

```
usage_metadata: None
response_metadata['token_usage']: None
```

两个属性都不报错，都是 `None`。拿不到实际值时框架给 `None`，不是估算值：直接写 `reply.usage_metadata["input_tokens"]` 会抛 `TypeError`，写成 `or {}` 兜底则这次调用的成本被记成 0，正确做法是记未知并在对账时单列。响应里多出的字段更彻底，消息对象里根本没有：

```
消息对象里能找到 x_vendor_field 吗: False
additional_kwargs 的键: ['refusal']
```

厂商私有字段在解析时被丢掉，要做对账或排查只能在传输层留一份原始响应。最后把七个字段摆在一起：

```
字段对照：
  finish_reason              'stop'
  usage.prompt_tokens        24
  usage.completion_tokens    9
  message.refusal            None
  input_tokens               24
  output_tokens              9
  total_tokens               33
```

**框架搬字段与改名，没搬口径**：`finish_reason` 的含义、四个取值怎么分支（第 1 章）、三个 token 数怎么换算成钱（第 3 章），都没进框架。
边界：跨厂商能依赖的只有 `usage_metadata` 与 `response_metadata["finish_reason"]`，其余键由适配层决定，写进业务判断就会在换厂商时炸。

## 消息裁剪

第 3 章讲过窗口满了会怎样。手写的应对是一段从后往前数 token 的循环；框架里是一个函数，参数里有几个默认值与直觉相反：`include_system` 与 `allow_partial` 都是 `False`。同一层还有 `filter_messages`，按类型与字段名筛消息，不管 token 数。先核对签名（`code/knowledge/ch09_lc_basic/trimming.py` 里的 `signature`）：

```python
import inspect

from langchain_core.messages import trim_messages


def signature():
    """真签名与每个参数的默认值。"""
    for name, param in inspect.signature(trim_messages).parameters.items():
        print(f"{name:<16} 默认={param.default!r}")
```

```
messages         默认=<class 'inspect._empty'>
max_tokens       默认=<class 'inspect._empty'>
token_counter    默认=<class 'inspect._empty'>
strategy         默认='last'
allow_partial    默认=False
end_on           默认=None
start_on         默认=None
include_system   默认=False
text_splitter    默认=None
```

| 参数 | 默认 | 管什么 |
|---|---|---|
| `max_tokens` | 必填 | 装多少 token 的上限，不是条数 |
| `token_counter` | 必填 | 怎么数：一个函数、一个模型、或字符串 `"approximate"` |
| `strategy` | `"last"` | `"last"` 从末尾往前装（保最近的），`"first"` 从头往后装 |
| `include_system` | `False` | 是否把第一条 system 单独留在最前面 |
| `allow_partial` | `False` | 放不下的那条要不要切一刀 |
| `start_on` / `end_on` | `None` | 裁完的两端必须落在哪类消息上 |
| `text_splitter` | `None` | 配合 `allow_partial` 的切法，默认按换行切 |

参数名能看懂，默认值看不出来。下面几个情形跑的是同一份六条历史、47 token，与第 3 章那段手写循环用的是同一份：

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately

HISTORY = [
    SystemMessage("你是退货政策助手，只回答与退货相关的问题。"),
    HumanMessage("订单 A1001 能退吗？"),
    AIMessage("请提供签收时间和商品状态。"),
    HumanMessage("签收 7 天，未拆封。"),
    AIMessage("符合退货条件。"),
    HumanMessage("那退款多久到账？"),
]


def show(label, messages):
    """打印一份裁剪结果的条数、token 数与每条的内容。"""
    print(label)
    print(f"  {count_tokens_approximately(messages)} token，{len(messages)} 条")
    for m in messages:
        print(f"    {m.type:<7} {m.content!r}")
    print()
```

```
原始：47 token，6 条

strategy='last', max_tokens=40:
  37 token，5 条
    human   '订单 A1001 能退吗？'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'

include_system=True:
  39 token，5 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

第一段里没有 system：默认 `include_system=False`，system 被当成普通消息一起参与裁剪，然后被挤掉。system 是指令层，丢了它等于换了一套指令，而这一步不报错、不打日志。

第二段 system 回来了，但第一条是 `ai`，对话从模型的话开始。这种序列对多数服务端都不合法，而 `trim_messages` 只管 token 数，不会修正：

```
include_system=True, start_on='human':
  30 token，4 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

`start_on="human"` 把开头修成 human，代价是又多裁掉一条：`include_system` 与 `start_on` 必须成对使用。`strategy` 决定丢哪一头：

```
strategy='first', max_tokens=40:
  34 token，4 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '订单 A1001 能退吗？'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
```

从前往后装，留下开头四条，最后那句问题被丢掉。`first` 适合前因重要的历史，`last` 适合多轮对话；`first` 与 `include_system`、`start_on` 互斥：

```
{'strategy': 'first', 'include_system': True} -> ValueError: include_system parameter is only valid with strategy='last'
{'strategy': 'first', 'start_on': 'human'} -> ValueError: start_on parameter is only valid with strategy='last'
```

两个参数只在 `strategy="last"` 下成立，配 `first` 直接 `ValueError`，开发期就能发现。默认 `last` 的理由与第 3 章一致：溢出时要保的是最近的上下文。
**裁剪的单位是条，预算是 token**：一条超长消息可以独占整个上限，裁到只剩它还是超，`allow_partial` 只能按切法切开它。要保留要点、丢掉细节时，裁剪函数解决不了。

`end_on` 修的是另一端：

```
strategy='last', max_tokens=60:
  56 token，7 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '订单 A1001 能退吗？'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
    ai      '退款 3 个工作日到账。'

strategy='last', max_tokens=60, end_on='human':
  47 token，6 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '订单 A1001 能退吗？'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

上限 60 时七条都能装下，加 `end_on="human"` 之后末尾那条 `ai` 被去掉。判据和 `start_on` 对称：以 `ai` 结尾，模型下一条回复会接在自己没说完的话后面；以 `human` 结尾才是等模型回答的状态。

两个极端：

```
max_tokens=5:
  0 token，0 条

allow_partial=False:
  7 token，1 条
    system  '你是退货政策助手。'

allow_partial=True:
  20 token，2 条
    system  '你是退货政策助手。'
    human   '问题：可以申请退货吗。\n追问：需要提供哪些材料。\n追问：退款多久到账。'
```

上限小到装不下一条时返回空列表，不报错。`allow_partial` 的效果取决于切法：那条 human 是五行文本，默认按换行切保住了后三行，换成按句号切会细到句子：

```python
from langchain_core.messages import HumanMessage, SystemMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately


def partial_with_splitter():
    """换一个按句号切的 text_splitter，切点可以更细。"""
    messages = [
        SystemMessage("你是退货政策助手。"),
        HumanMessage("签收 3 天，未拆封，包装完好。请问可以退货吗。需要哪些材料。退款多久到账。"),
    ]
    out = trim_messages(messages, max_tokens=15, token_counter=count_tokens_approximately,
                        strategy="last", include_system=True, allow_partial=True,
                        text_splitter=lambda text: [piece + "。" for piece in text.split("。") if piece])
    show("text_splitter=按句号切, max_tokens=15:", out)
```

```
text_splitter=按句号切, max_tokens=15:
  15 token，2 条
    system  '你是退货政策助手。'
    human   '需要哪些材料。退款多久到账。'
```

同一条消息、同一个上限，切法不同留下的半句不同。`allow_partial` 只是允许按 `text_splitter` 切开；没有换行的长消息配默认切法，仍然整条丢掉。

最后一个参数是计数器本身。上面的数字都用 `count_tokens_approximately`，它按字符数估。换成真实 tokenizer：

```
近似计数: 47
gpt-4o-mini 的 tokenizer: 77
用模型做 token_counter, max_tokens=40: 3 条，真实 token=34，近似 token=20
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

同一份历史，估算 47、真实 77，差 64%；同一个 `max_tokens=40`，用估算裁出 5 条，用真实 tokenizer 只裁出 3 条。`max_tokens` 的含义由 `token_counter` 决定：卡预算要用真实 tokenizer，排序、比较长短用估算即可，取值是窗口上限减输出预算再留模板 token 的余量。这里它只管输入，与请求体里那个同名参数不是同一个东西。
会怎么坏：`trim_messages` 不报错、不打点，被裁掉的消息从此消失。三个信号：system 不在第一条，说明没开 `include_system`；第一条是 `ai`，说明没设 `start_on`；句子里少了一半，说明切点不对。判据是裁剪之后第一条是不是 system。

边界：这个函数只按条裁，不做摘要，压成摘要属于第 19 章上下文装配的事；它也只能按位置与类型裁，不知道哪些消息更该保留。先裁再拼时，模板与引用编号占的 token 不在预算里，实际请求会比 `max_tokens` 大。

## 流式三接口

第 1 章讲过流式的三个事实：正文散在增量里、`finish_reason` 只在最后一块、`usage` 默认不返回。框架提供三个接口，语义不变。`code/knowledge/ch09_lc_basic/streaming.py` 里起了一个脚本化后端：

```python
import httpx
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from scripted_chat import scripted_chat, sse_content

PIECES = ("签收后", " 7 天内", "可退。", "条件：", "商品未拆封。")


def sse_response(index, body):
    """回放一份 SSE 响应体。"""
    return httpx.Response(200, content=sse_content(*PIECES),
                          headers={"content-type": "text/event-stream"})


def make_llm():
    """同步与异步两个传输层都由脚本化后端接管。"""
    return scripted_chat(sse_response)
```

```
== stream() ==
AIMessageChunk   content='签收后'      finish_reason=None
AIMessageChunk   content=' 7 天内'    finish_reason=None
AIMessageChunk   content='可退。'      finish_reason=None
AIMessageChunk   content='条件：'      finish_reason=None
AIMessageChunk   content='商品未拆封。'   finish_reason=None
AIMessageChunk   content=''         finish_reason='stop'
AIMessageChunk   content=''         finish_reason=None
```

`.stream()` 产出 `AIMessageChunk`。前五块的 `content` 是增量不是全文；第六块正文为空、只带 `finish_reason="stop"`；第七块完全为空，是流关闭时的收尾块，不能当成模型说了空话。

把块拼起来，位置关系更清楚：

```python
def aggregate():
    """把块拼成一条消息：正文、收尾原因、用量的位置各不相同。"""
    chunks = list(make_llm().stream([HumanMessage("能退吗？")]))
    total = chunks[0]
    for chunk in chunks[1:]:
        total = total + chunk
    print("块数:", len(chunks))
    print("拼出的文本:", total.content)
    print("finish_reason:", total.response_metadata.get("finish_reason"))
    print("usage_metadata:", total.usage_metadata)
```

```
块数: 7
拼出的文本: 签收后 7 天内可退。条件：商品未拆封。
finish_reason: stop
usage_metadata: None
```

拼出的文本与非流式调用一致，`finish_reason` 靠块相加带过来，`usage_metadata` 是 `None`：这个 SSE 响应体里没有 `usage`。写成 `{"include_usage": True}` 服务端才在最后一帧带用量，框架不会自己补估算值。

`.astream()` 是同一件事的异步接口，逐块产出的顺序一致：

```
== astream() ==
AIMessageChunk   content='签收后'
AIMessageChunk   content=' 7 天内'
AIMessageChunk   content='可退。'
AIMessageChunk   content='条件：'
AIMessageChunk   content='商品未拆封。'
AIMessageChunk   content=''
AIMessageChunk   content=''
```

异步接口的理由是等的时候能让出执行权，同步的 `stream` 在等下一块时会占住线程。拼接有两个问题：工具参数分块到达，`args` 在拼完前是残缺的；正文与工具调用可能同在一个响应里，要按块类型分别累积。

第三个接口不是取内容，是取过程。`astream_events` 把一次调用拆成事件流，每个事件带 `event`、`name`、`run_id` 与 `parent_ids`：

```python
async def event_tree():
    """事件名与父子关系。"""
    llm = make_llm()
    wrap = RunnableLambda(lambda text: [HumanMessage(text)])
    pipeline = wrap | llm

    names = {}
    async for event in pipeline.astream_events("能退吗？", version="v2"):
        names.setdefault(event["run_id"], event.get("name"))
        parents = [names.get(pid, "?") for pid in event.get("parent_ids") or []]
        print(f"{event['event']:<22} {event.get('name'):<18} parent={parents or '(根)'}")
```

```
on_chain_start         RunnableSequence   parent=(根)
on_chain_start         RunnableLambda     parent=['RunnableSequence']
on_chain_stream        RunnableLambda     parent=['RunnableSequence']
on_chain_end           RunnableLambda     parent=['RunnableSequence']
on_chat_model_start    ChatOpenAI         parent=['RunnableSequence']
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_stream   ChatOpenAI         parent=['RunnableSequence']
on_chain_stream        RunnableSequence   parent=(根)
on_chat_model_end      ChatOpenAI         parent=['RunnableSequence']
on_chain_end           RunnableSequence   parent=(根)
```

这张表是一次调用的完整过程记录，共四类事件：

| 事件名 | 什么时候发 | 拿它做什么 |
|---|---|---|
| `on_chain_start` / `on_chain_end` | 一段可执行单元开始 / 结束 | 计时、数层数 |
| `on_chain_stream` | 组合把中间结果往下传 | 看每一层产出了几次 |
| `on_chat_model_start` | 模型调用开始 | 请求发出时刻 |
| `on_chat_model_stream` / `on_chat_model_end` | 每个增量 / 生成结束 | 首 token 延迟、增量拼接 |

`parent` 列是父子关系：`RunnableSequence` 是根，`RunnableLambda` 与 `ChatOpenAI` 是它的子，每个模型增量都往上一层冒一次。三个接口的分工：要最终结果用 `invoke`，边生成边展示用 `stream` 或 `astream`，观察过程用 `astream_events`。
事件树还有第二个用处：把一次生成和一轮任务分开。`astream_events` 里 `on_chat_model_*` 数调用次数，`on_chain_*` 数轮数；把块数当调用次数，计费与限流都会算错。边界：块不是完整消息，工具参数会分块到达。

## 结构化输出的策略

第 4 章的五种做法都要手写请求构造与解析，第 5 章用 pydantic 定义了结构，框架把这两件事接在一处：`with_structured_output(schema, method=...)`。先核对签名，`code/knowledge/ch09_lc_basic/structured.py` 里的 `signature`：

```python
import inspect

from langchain_openai import ChatOpenAI


def signature():
    """真签名：`method` 的默认值就是最强的那一种。"""
    print(inspect.signature(ChatOpenAI.with_structured_output))
```

```
(self, schema: '_DictOrPydanticClass | None' = None, *, method: "Literal['function_calling', 'json_mode', 'json_schema']" = 'json_schema', include_raw: 'bool' = False, strict: 'bool | None' = None, tools: 'list | None' = None, **kwargs: 'Any') -> 'Runnable[LanguageModelInput, _DictOrPydantic]'
```

`method` 有三个取值，第 4 章的五种做法收敛到这三个，默认是 `json_schema`（旧版本不同，抄来的代码要核对）。目标是同一个 `RefundCheck`：

```python
from pydantic import BaseModel


class RefundCheck(BaseModel):
    """要取出的三个字段。"""

    order_id: str
    days: int
    reason: str
```

三种策略跑在同一份输入上，接线部分是：请求里带 `tools` 就回放一条工具调用，否则回放正文：

```python
import json

import httpx
from langchain_openai import ChatOpenAI
from scripted_chat import chat_completion, tool_call

GOOD = '{"order_id": "A1001", "days": 7, "reason": "签收不想要"}'
QUESTION = "订单 A1001，签收 7 天，未拆封，能退吗？"


def make_llm(reply_text=GOOD, reply_tool=None):
    """按请求形态回放：带 tools 的请求走工具调用，其余走正文。"""

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if body.get("tools"):
            return httpx.Response(200, json=chat_completion(
                tool_calls=reply_tool or [tool_call("RefundCheck", json.loads(reply_text))],
                finish_reason="tool_calls", usage=(48, 24)))
        return httpx.Response(200, json=chat_completion(reply_text, usage=(48, 24)))

    seen = []
    transport = httpx.MockTransport(handler)
    llm = ChatOpenAI(model="demo-model", api_key="sk-test",
                     http_client=httpx.Client(transport=transport, trust_env=False))
    return llm, seen


def describe(name, seen):
    """把这次请求里与结构化输出有关的三项打出来。"""
    body = seen[-1]
    print(f"  [{name}] tools:", "有" if body.get("tools") else "无")
    print(f"  [{name}] tool_choice:", body.get("tool_choice"))
    print(f"  [{name}] response_format:", json.dumps(body.get("response_format"), ensure_ascii=False))
```

三种策略各跑一次，每次打印返回对象、请求体里的 `tools`、`tool_choice`、`response_format`：

```python
def three_methods():
    for method in ("function_calling", "json_schema", "json_mode"):
        llm, seen = make_llm()
        chain = llm.with_structured_output(RefundCheck, method=method)
        result = chain.invoke(QUESTION)
        print(f"{method:<17} -> {type(result).__name__} {result}")
        describe(method, seen)
        print()
```

```
function_calling  -> RefundCheck order_id='A1001' days=7 reason='签收不想要'
  [function_calling] tools: 有
  [function_calling] tool_choice: {'type': 'function', 'function': {'name': 'RefundCheck'}}
  [function_calling] response_format: null

json_schema       -> RefundCheck order_id='A1001' days=7 reason='签收不想要'
  [json_schema] tools: 无
  [json_schema] tool_choice: None
  [json_schema] response_format: {"type": "json_schema", "json_schema": {"schema": {"description": "要取出的三个字段。", "properties": {"order_id": {"title": "Order Id", "type": "string"}, "days": {"title": "Days", "type": "integer"}, "reason": {"title": "Reason", "type": "string"}}, "required": ["order_id", "days", "reason"], "title": "RefundCheck", "type": "object", "additionalProperties": false}, "name": "RefundCheck", "strict": true}}

json_mode         -> RefundCheck order_id='A1001' days=7 reason='签收不想要'
  [json_mode] tools: 无
  [json_mode] tool_choice: None
  [json_mode] response_format: {"type": "json_object"}
```

三次返回的都是 `RefundCheck` 实例，请求体长三个样子。对应关系是：

| `method` | 请求里加了什么 | 谁保证结构 | 对应第 4 章 |
|---|---|---|---|
| `function_calling` | `tools` + 强制 `tool_choice` | schema 约束参数 | 做法三 |
| `json_schema` | `response_format.json_schema`，带 `strict: true` | 生成时约束 | 做法四 |
| `json_mode` | 只有 `response_format: {"type": "json_object"}` | 服务端只保证语法 | 做法二 |

`json_schema` 那一行值得细看：`required` 三个字段齐全，`additionalProperties: false`，`strict: true`，第 4 章做法四的三条限制框架自动生成了。`function_calling` 的 tool 名用模型类名，参数 schema 由 pydantic 生成。它替掉的是请求构造与解析；三次返回同一类型是因为解析层统一，拿到文本或工具参数后转成 dict 再交给 pydantic 校验。

第 4 章那五种做法里，失败最典型的是字段名对不上。`json_mode` 只保证语法，模型把 `order_id` 写成 `orderId` 时，框架的效果是：

```
OutputParserException : Failed to parse RefundCheck from completion {"orderId": "A1001", "days": 7, "reason": "签收不想要"}. Got: 1 validation error for RefundCheck

order_id
  Field required [type=missing, input_value={'orderId': 'A1001', 'day...son': '签收不想要'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
For troubleshooting, visit: https://docs.langchain.com/oss/python/langchain/errors/OUTPUT_PARSING_FAILURE 
```

与第 4 章那张表里 `JSON mode` 那一行完全同因：语法合法，字段缺失。框架把 pydantic 的原始报错包进 `OutputParserException`，两个原因都保留着。区别在于它抛出的是异常：异常里没有原始文本时，重试要重新调用一次；要留着回灌，需要 `include_raw=True`：

```
parsed: None
parsing_error 类型: OutputParserException
raw.content: {"orderId": "A1001", "days": 7, "reason": "签收不想要"}
```

`include_raw=True` 时返回三个键：`parsed`、`raw`、`parsing_error`，做法五那套回灌的原料就在这里，灌什么、灌几次仍然要自己定。会怎么坏：三种策略都依赖服务端能力，框架不做能力探测，不支持时照样把请求发出去，失败落在 4xx 或解析处。选择顺序：确认支持就选 `json_schema`，不确定时先用 `function_calling` 试一次，都不行退回 `json_mode` 加本地校验。
边界：这一层只做到结构对。`days` 是否在 1 到 90 之间、`order_id` 在不在库里，不在这一层；重试策略也不在，第 10 章的自愈解析器把它封装成一个对象。

## 批量与缓存

前面每节都是一次一个输入。给一批输入时，`batch` 一次提交、内部并发执行，返回值按输入顺序排，完成顺序不保证；`max_concurrency` 控制同时在跑的个数。逐个 `invoke` 是串行，结果一样，耗时按步累加。运行 `code/knowledge/ch09_lc_basic/batch_cache.py`：

```python
def slow(text: str) -> str:
    time.sleep(SLEEP[text])
    DONE.append(text)
    return text.upper()

step = RunnableLambda(slow)

got = step.batch(["a", "b", "c"], config={"max_concurrency": 3})
print("batch 结果（按输入顺序）：", got, "完成顺序：", DONE.copy())

serial = [step.invoke(x) for x in ["a", "b", "c"]]
print("逐个 invoke 结果：", serial, "完成顺序：", DONE.copy())
```

```
batch 结果（按输入顺序）： ['A', 'B', 'C'] 完成顺序： ['b', 'c', 'a']
逐个 invoke 结果： ['A', 'B', 'C'] 完成顺序： ['a', 'b', 'c']
```

三行的差别在最后一列：`batch` 的完成顺序是 `b, c, a`（谁先跑完谁先记），但返回值仍然按 `a, b, c` 排好；逐个 `invoke` 的完成顺序与输入顺序一致，因为一次只有一个在跑。对一批独立的请求，`batch` 的总耗时接近最慢那一个；`abatch` 是它的异步版本，返回 awaitable。

缓存接着解决第二件事：同一份请求第二次不该再算一遍。`set_llm_cache(InMemoryCache())` 打开进程内缓存后，模型调用按完整请求取键，命中就直接返回上次的结果：

```python
set_llm_cache(InMemoryCache())
print("同一问题第 1 次：", MODEL.invoke("能退吗？").content)
print("同一问题第 2 次：", MODEL.invoke("能退吗？").content)
print("换一个问题    ：", MODEL.invoke("多久到？").content)
```

```
同一问题第 1 次： 第一次
同一问题第 2 次： 第一次
换一个问题    ： 第二次
```

脚本里模型只有两条固定回复，第二次之所以还是"第一次"，是因为它根本没走到模型：键一样，直接取缓存。第三行换了问题，键变了，模型被调用一次，拿到第二条回复。由此有两条实践约束：缓存键是整份请求（消息数组加参数），改一个字就失效，这与第 3 章讲的"缓存只命中从头开始的连续前缀"是同一件事；进程内缓存跨用户共享，含私有内容的请求不能共用一个缓存键，多租户要按租户分键或直接关掉。

## 这一章建立的 8 件事

1. 四个包的职责、版本区间，以及两个真实报错的成因（`ModuleNotFoundError` 与 `ImportError` 要分开处理）
2. `init_chat_model` 五个参数各管什么，`model` 与 `model_provider` 两种写法等价
3. `base_url` 接兼容端点、`configurable_fields` 加 `config_prefix` 改参数，以及前缀写错的静默失效
4. 四种消息的 `type` 值与请求体 `role` 的对应，`content` 与 `content_blocks` 的分工
5. 三类元信息与第 1、3 章字段的对应，`usage_metadata` 可能为 `None`、私有字段会被丢掉
6. `trim_messages` 的默认值，`include_system` 必须配 `start_on`，`max_tokens` 的口径由 `token_counter` 决定
7. 三种流式接口的产物与事件树，三种结构化策略的请求形态，以及它们各自与第 1、4、5 章的对应
8. `batch` / `abatch` 一次提交一批输入、内部并发，返回值按输入顺序、完成顺序不保证；`set_llm_cache` 打开进程内缓存后，同一份请求第二次不再走到模型。

## 下一章

这一章的每个对象都是单独用的：一次调用、一条消息、一个裁剪函数。真实代码里它们要拼起来——校验在前、模型在中、解析在后，中间出错要能重试，还要能批量与并行。第 10 章讲这一步：可执行单元之间的输入输出约定、七个组合子、提示词模板与四种解析器，以及 `astream_events` 在组合之后才显出来的那棵树。

---

[← 第 8 章 · 循环的四种失控](./08-循环的四种失控.md)　｜　[卷 3 目录](./docs/INDEX.md#vol3)　｜　[第 10 章 · LangChain 组合与解析器 →](./10-LangChain组合与解析器.md)
