# 第 9 章 · LangChain 包结构与消息

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./docs/INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F1 包结构与模型接入 —— init_chat_model 的参数矩阵与三种结构化输出策略；F2 消息与内容块 —— 四种消息类型，content 与 content_blocks 的区别（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：一次调用在框架里被拆成哪几个对象，每个对象替掉前八章手写的哪一段，剩下的哪一段仍然要自己写
> - **示例目录**：`code/knowledge/ch09_lc_basic/`
> - **读完应当能回答**：给一段 LangChain 代码，说出每个参数落在哪一层、对应手写版的哪几行、以及框架没有接管的部分在哪

---

## 目录

[一、手写的四处重复](#一手写的四处重复)\
[二、四个包的分工](#二四个包的分工)\
[三、模型接入的参数](#三模型接入的参数)\
[四、四种消息与内容块](#四四种消息与内容块)\
[五、三类元信息](#五三类元信息)\
[六、裁剪的六个参数](#六裁剪的六个参数)\
[七、三种流式接口](#七三种流式接口)\
[八、结构化输出的三种策略](#八结构化输出的三种策略)\
[九、框架没有替掉的部分](#九框架没有替掉的部分)\
[这一章建立的 7 件事](#这一章建立的-7-件事)

版本以本机安装为准：`langchain` 1.4.7、`langchain-core` 1.7.0、`langchain-openai` 1.1.9、`langchain-community` 0.4.2。框架的符号在小版本之间会挪位置，本章有几条报错只有在这几个版本上才复现，四个数字是正文的一部分。

示例目录里的 `scripted_chat.py` 是脚本化后端：给 `ChatOpenAI` 换掉 httpx 的传输层，请求照常编码成真实的 chat completion 请求，响应来自脚本。本章所有输出都是脚本化后端跑出来的，原理演示，不是模型实测，它演示的是框架怎么编码、怎么解析、怎么搬运字段。换真实服务时只改构造模型的那一处：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", api_key="sk-...", base_url="https://api.openai.com/v1")
```

`base_url` 指向任何兼容 OpenAI 协议的服务即可，其余代码不动。

## 一、手写的四处重复

第 1 到第 8 章的手写代码里，有五段几乎每个项目都要重写一遍：

| 手写位置 | 那段代码在做什么 |
|---|---|
| 第 1 章 | 拼请求体：把 system / user / assistant 的角色和文本组装成 `messages`，加上 `temperature`、`max_tokens` |
| 第 1 章 | 读响应：从 `choices[0].message` 取 `content` 与 `tool_calls`，取 `finish_reason`，取 `usage` |
| 第 3 章 | 数 token 与裁剪：估算、按上限裁掉最早的轮次 |
| 第 4 章 | 结构化输出：构造 `tools` 或 `response_format`，再把返回的字符串解析成对象 |
| 第 6 章 | 工具往返：把一次调用与它的结果装配成三条消息 |

这五段有同一个性质：它们的输入输出与业务无关，写法与厂商、与调用形态有关。换一家厂商，第一段要改 URL 与认证头，第二段要改字段名；加一种调用形态，同样的装配逻辑要再写一份。

复制带来的问题不是行数，是失效方式被混在一起。第 1 章讲过 `content` 为空有三种原因：被截断、被拦截、在要工具；第 4 章讲过 JSON mode 保证语法不保证字段名；第 6 章讲过工具参数的 `arguments` 是字符串。这些区分复制到十几个调用点之后就没有人记得哪一处漏了分支。手写版一定走向复制，因为这段代码有四个互相独立的可变点：

| 可变点 | 变一次要改什么 | 谁在变 |
|---|---|---|
| 厂商 | URL、认证头、字段名、`finish_reason` 的取值集合 | 换模型、接网关、做 A/B |
| 调用形态 | 同步、流式、批量、可配置参数 | 界面要打字机效果、后台要跑批 |
| 输出结构 | 纯文本、JSON、工具调用 | 从"给人看"变成"给程序用" |
| 历史长度 | 装得下、要裁剪、要压缩 | 对话轮次增加 |

四个可变点两两组合就是十几种写法，手写版把四个都编在同一段代码里。框架不是写一段更聪明的代码，而是把四个点分别收进四样东西：厂商进适配包，调用形态进三个接口，输出结构进 `with_structured_output`，历史长度进 `trim_messages`。

框架做的事是把与厂商有关的部分收进一层：消息变成四个类，模型变成 `ChatOpenAI`，裁剪变成一个函数。业务代码只跟这几样东西打交道，不再直接拼 JSON。框架没有做的事要一开始说清：它搬字段，不做判断。一条回复能不能用由第 1 章四个取值决定，花多少钱由第 3 章计价，值合不合理由第 4 章校验，循环要不要继续由第 7 章与第 8 章决定。这些判断依赖业务语义，框架手里没有这份信息。

主线先手写、这里再看框架，顺序不能倒：手写版讲清了这一步为什么必须有，框架版讲的是工程里这一段长什么样。反过来学的人，会在框架不覆盖的地方失去判断依据，比如 `finish_reason` 的分支。

## 二、四个包的分工

装完之后的第一个问题不是 API，是 import。LangChain 1.x 的代码分布在四个发布包里，**包名和 import 路径不同名**，两者对不上时报错不会说要装哪个。`code/knowledge/ch09_lc_basic/versions.py` 把版本、依赖区间和符号归属一起打出来：

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

第三列是每个包对 `langchain-core` 的需求区间，它解释了为什么四个包要一起看：`langchain 1.4.7` 要求 core `>=1.6.13`，`langchain-openai 1.1.9` 要求 core `>=1.2.11`，两条取交集，core 的版本由最严的那个包决定。四个包不是一个个独立升级的，core 走在前面。把 core 停在 1.2 而 langchain 升到 1.4.7，pip 会拒绝安装，这比运行时出错好；但它只在装的时候成立，用 `--no-deps` 或缓存了旧 wheel 时照样装得上。

落到工程里，就是把这四个版本号连同传递依赖一起钉住。传递依赖也要钉，因为 `langchain-openai` 对 `openai` 包有很宽的区间要求，不钉的话同一条命令在不同时间装出的版本可能不同，而响应解析的细节由它决定。

第二块输出是符号归属：模型入口在 `langchain`，厂商适配在 `langchain-openai`，消息与裁剪在 `langchain-core`。`langchain-core` 只放与厂商无关的东西，它不 import 任何厂商 SDK，所以能被所有适配包依赖；`langchain` 放编排与入口，需要时才去 import 某个厂商包；`langchain-openai` 放与一家 SDK 对齐的编码与解析。四个包这样切，查符号就有了方法：看一个符号在哪，就看它依赖谁。两个入口各替一段手写的活：`init_chat_model` 替第 1 章拼请求体加选厂商那几行，`create_agent` 是用来替代第 7 章那个最小循环的入口，到第 12 章才讲。这个切法还给出查符号的方法：**看一个符号在哪，就看它依赖谁**。`versions.py` 第二块用 `hasattr` 在每个候选模块里找一遍，比翻文档快。

包拆开之后旧路径就消失了，`versions.py` 的第三块把四个旧 import 原样跑了一遍：

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

四条报错有同一个来源：0.x 到 1.x 的拆包。`langchain.chains` 与 `langchain.memory` 不再是 `langchain` 的子模块，迁到 `langchain-classic`；厂商类迁到各自的 `langchain-<vendor>` 包。这就是从旧教程抄一行 import 的失败形态：报错只说模块不存在，不说该装哪个包。

四条里第三条值得注意：它的类型是 `ImportError` 而不是 `ModuleNotFoundError`，因为 `langchain.chat_models` 这个模块还在，它是 `init_chat_model` 的入口，只是里面不再有 `ChatOpenAI`。同一种路径变了，报错类型不同，处理方向也不同：前者去改符号归属，后者去找包。

边界：遇到 import 报错，先分清包没装与符号换了包。前者补依赖，后者改路径；猜错方向会一直改不到点上。

## 三、模型接入的参数

第 1 章的请求体里 `model` 是字符串、`temperature` 是数字，两个值都写在业务代码里；第 1 章的协议层对照把这条路摊开成 URL、认证头、请求体三行。换厂商要动这几行，换一种同一模型不同参数的实验也要动这几行。`init_chat_model` 把这一段收成一个函数，按厂商找到适配类再把参数透传下去。先核对签名，下面这段来自 `code/knowledge/ch09_lc_basic/model_access.py`：

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
| `**kwargs` | 可变关键字 | 原样传给适配类：`api_key`、`base_url`、`http_client`、`temperature`… |

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

情形一和情形二达到同一个结果，区别只在写法。返回类型是 `ChatOpenAI` 而不是某个通用模型：`init_chat_model` 做的是一次映射，拿到 `model_provider="openai"` 就 import `langchain_openai` 再实例化，其余关键字原样传下去。所以它不改变请求体，`model` 字段仍然是 `demo-model`。请求没有离开本机，`http_client` 被换成了 `MockTransport`，传输层被截住。**URL 由 `base_url` 决定，请求发不发得出去由传输层决定。**

```
== 情形三：configurable_fields ==
返回类型: _ConfigurableModel
默认 temperature: None
config 里的 temperature=0.9 -> 0.9
with_config 改成 0.2 -> 0.2
```

`configurable_fields` 把字段从构造期挪到调用期。给了它之后返回类型变成 `_ConfigurableModel`，字段值在 `invoke` 时才定型，`with_config` 把一份配置固定在对象上。这段替代的是第 1 章里把 `temperature` 写进请求体那一行，手写版每换一个值就要改代码或加参数，这里的值来自调用方传进来的 `config`。代价是类型变了：`_ConfigurableModel` 不是 `ChatOpenAI`，判断 `isinstance` 会失效。

`config_prefix` 的理由是一次调用里可能有多个对象要配：主模型一个温度、便宜的小模型另一个温度、检索器还有一个 `k`。`config` 是扁平字典，前缀把命名空间分开，两个温度才能同时存在。前缀决定键名怎么拼，写错时不会报错，只会读到一个不存在的键。

```
== 情形四：base_url ==
base_url 指向本机 8080 后，请求 URL: http://127.0.0.1:8080/v1/chat/completions
```

`base_url` 只改一件事：请求打到哪个主机。自建网关、代理、本地推理服务，只要实现 OpenAI 协议的那几个路径，把 `base_url` 指过去就是一个可用的模型。第 3 章讲换厂商时要改的东西里，URL 是第一件，第 1 章的协议层对照也把它列成一行，这里它变成一个关键字参数。三个真实的失效：

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

情形五最危险：它是一行代码没生效，而且没有报错。设了 `config_prefix="llm"` 之后键名必须是 `llm_temperature`；写成 `temperature` 时这个值被静默丢掉，请求体里没有这个字段，模型用默认温度。要读出没进请求体这一行，还得知道默认值：`temperature` 默认是 `None`，含义是这个字段不传，服务端按自己的默认值处理。没生效与传了默认值在请求体里看起来一样，判据是看字段在不在。

情形六是同类问题的另一种时机：`foo` 不在 `init_chat_model` 的参数表里，也不在 `ChatOpenAI` 的字段里，构造时只给一条 `UserWarning`，把它塞进 `model_kwargs`，直到发请求、openai 客户端组装参数时才变成 `TypeError`。情形七是唯一立刻失败的：厂商推断不出来，`ValueError` 列出支持的标识，因为推断按模型名前缀匹配。

边界：`init_chat_model` 只解决选类与传参。它不负责选参数取值，温度给多少由第 1 章那两个问题决定；也不处理厂商能力差异，严格 schema 与强制 `tool_choice` 在第 4 章讲过。它是按需 import，只有 `model_provider="openai"` 时才 import `langchain_openai`，所以装错包的报错发生在调用之后。

## 四、四种消息与内容块

第 1 章的 `messages` 是 dict，键由调用方随便写；框架里消息是四个类，每个类除了 `content` 还多出内容块与元信息。用错字段不会在发送时报错，dict 能编码成任何形状，错误要到回复里才显形。`code/knowledge/ch09_lc_basic/messages.py` 先造出四条消息，打印类名、`type` 与内容：

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

0.x 的消息对象有 `.role`，1.x 只有 `.type`。写代码时用 `type`，读请求体时看 `role`，混用会得到 `AttributeError` 或一个永远为假的条件。同一条回复有两种读法：

```
== 文本回复的两种读法 ==
content: '签收后 7 天内可退。'
content_blocks: [{'type': 'text', 'text': '签收后 7 天内可退。'}]
```

`content` 是这条消息的文本原样；`content_blocks` 是把 `content` 连同其它字段归一化成块的视图。纯文本时两者几乎等价，一个是字符串，一个是只含一个 `text` 块的列表。差别出现在下面两种情况。

```
== 工具调用回复 ==
content: ''
tool_calls: [{'name': 'get_order', 'args': {'order_id': 'A1001'}, 'id': 'call_demo', 'type': 'tool_call'}]
content_blocks: [{'type': 'tool_call', 'name': 'get_order', 'args': {'order_id': 'A1001'}, 'id': 'call_demo'}]
```

模型要动作时 `content` 是空字符串，动作在 `tool_calls` 里，对应一个 `tool_call` 块。对照第 1 章：手写版里 `content` 是 `null`，代码要判 `if content is None`；框架把它归一成空字符串，于是没有正文和生成了空内容这两件事分不开，要区分只能看 `tool_calls`。还有一处：`tool_calls[i]["args"]` 是 dict，请求体里仍然是 JSON 字符串。回灌工具结果时能看清这一点：

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

三行请求体是这个往返的全部内容。第一，`assistant` 那条的 `content` 在发出时又变回 `null`，空字符串与 `null` 只在对象层被抹平。第二，`tool` 那条必须带 `tool_call_id`，值等于上一条的 `tool_calls[0].id`，这是第 6 章手写往返里最容易错的一处。最后一种情况是内容块的归一化：

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

`content` 里没有推理内容，`content_blocks` 里有一个 `reasoning` 块，它来自 `additional_kwargs` 里的厂商私有字段。这是两种读法的真正区别：**`content` 是协议里的那个字段，`content_blocks` 把消息里所有能当成内容的东西排成一列。**

为什么不直接用 dict？因为一次调用两个方向都要转换，发送前把对象编码成 dict，收到后把 dict 解码成对象。dict 没有地方放这段逻辑，每个调用点各写一份，厂商一换就有一处漏改。`ToolMessage` 的 `content` 仍然是字符串，因为工具结果是调用方自己产出的内容，框架不该假设它是 JSON。

边界：块类型的集合由适配层决定，跨厂商不统一；`content_blocks` 是视图，写回去的仍然是 `content`。

## 五、三类元信息

第 1 章的响应只有四个字段，框架把它们拆成三个属性，其中一个专门装厂商原样。不知道去哪读，代码就会退化成只读 `reply.content`。`code/knowledge/ch09_lc_basic/metadata.py` 把一次正常回复的四个属性全打出来：

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

`usage_metadata` 是第 3 章那三个数的改名版：`prompt_tokens` 变成 `input_tokens`，`completion_tokens` 变成 `output_tokens`，明细拆进 `input_token_details` 与 `output_token_details`。同一个数在 `response_metadata["token_usage"]` 里还有一份。两层管的事不同：前者是这次调用消耗了多少，字段名由协议层统一；后者是这次响应长什么样，键由适配层原样填。第 3 章的成本代码需要稳定字段名，跨厂商只有第一处稳定。

`finish_reason` 只有一处，在 `response_metadata` 里。第 1 章讲的四个取值一个不少，处理分支也一模一样：框架搬字段，没搬分支。

```
被拦截的回复：
  content: ''
  additional_kwargs: {'refusal': '无法回答该请求'}
  response_metadata: {'token_usage': {'completion_tokens': 0, 'prompt_tokens': 24, 'total_tokens': 24, 'completion_tokens_details': None, 'prompt_tokens_details': None}, 'model_provider': 'openai', 'model_name': 'demo-model', 'system_fingerprint': None, 'id': 'chatcmpl-demo', 'finish_reason': 'content_filter', 'logprobs': None}
  usage_metadata: {'input_tokens': 24, 'output_tokens': 0, 'total_tokens': 24, 'input_token_details': {}, 'output_token_details': {}}
```

这是第 1 章被拦截那一行的框架读法：`content` 是空字符串，`finish_reason` 是 `content_filter`，另外多了一样东西，`refusal` 字段里的拦截说明。手写版通常把这段说明丢掉，于是被拦截和模型没话说在业务代码里长得一样。四个属性的位置可以这样记：**`content` 给业务看，`usage_metadata` 给账本看，`response_metadata` 给排查看，`additional_kwargs` 装这个厂商还有的字段。** 代价是字段可能不存在：

```
usage_metadata: None
response_metadata['token_usage']: None
```

两个属性都不报错，都是 `None`。这是第 3 章那条 `usage` 是实际值的反面：拿不到实际值时框架给 `None`，不是估算值。成本代码直接写 `reply.usage_metadata["input_tokens"]` 会抛 `TypeError`，写成 `or {}` 兜底则记成 0。两种都错，正确做法是记未知并在对账时单列。再一种情况是响应里多出字段：

```
消息对象里能找到 x_vendor_field 吗: False
additional_kwargs 的键: ['refusal']
```

厂商私有字段在解析时被丢掉，消息对象里没有原文。要做对账或排查，只能在传输层留一份原始响应，这也是计量那一章把抓取点放在传输层的原因。把七个字段摆在一起看框架到底搬了什么：

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

结论只有一句：框架搬字段与改名，没搬口径。 `finish_reason` 的含义与四个取值怎么分支（第 1 章）、三个 token 数怎么换算成钱、缓存部分按哪个价（第 3 章），这些都没进框架。边界：跨厂商能依赖的只有 `usage_metadata` 与 `response_metadata["finish_reason"]`，`system_fingerprint`、`logprobs` 这类字段只有部分厂商有，写进业务判断就会在换厂商时坏掉。

## 六、裁剪的六个参数

第 3 章讲过窗口满了会怎样：请求被拒、生成中途被截断、溢出时丢最早的轮次。手写的应对是一段从后往前数 token 的循环，框架里是一个函数。函数有六个参数，其中两个默认值与直觉相反：`include_system` 与 `allow_partial` 都是 `False`。`code/knowledge/ch09_lc_basic/trimming.py` 先打出真签名与默认值：

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

参数名能看懂，默认值看不出来。下面这些情形跑的是同一份六条历史，共 47 token。先看前两个，它们解释 `strategy` 与 `include_system` 为什么要分开设：

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

第一段的 5 条里没有 system：system 被当成普通消息参与裁剪，然后被挤掉。第 1 章说过 system 是指令层，丢了它等于换一套指令，而这一步不报错、不打日志。第二段开了 `include_system=True`，system 回来了，但列表第一条是 `ai`，对话从模型的话开始。这种序列对多数服务端都不合法，而 `trim_messages` 只算 token 数，不修正顺序：

```
include_system=True, start_on='human':
  30 token，4 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

`start_on="human"` 把开头修成 human，代价是又多裁掉一条。两段合起来说明：**`include_system` 与 `start_on` 必须成对使用**，只开前者会得到从 `ai` 开头的非法序列。`strategy` 决定丢哪一头：

```
strategy='first', max_tokens=40:
  34 token，4 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '订单 A1001 能退吗？'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
```

从前往后装，留下开头四条，最后那句问题被丢掉。`first` 适合历史里前因重要的场景，`last` 适合多轮对话。注意 `first` 与 `include_system`、`start_on` 互斥：

```
{'strategy': 'first', 'include_system': True} -> ValueError: include_system parameter is only valid with strategy='last'
{'strategy': 'first', 'start_on': 'human'} -> ValueError: start_on parameter is only valid with strategy='last'
```

两个参数只在 `strategy="last"` 下成立，配 `first` 直接 `ValueError`，开发期就能发现。默认 `strategy="last"` 的理由与第 3 章一致：溢出时要保最近的上下文，第 1 章讲过丢的是最早的轮次。还有一处容易被忽略：裁剪的单位是条，预算是 token。一条超长消息可以独占整个上限，这时裁到只剩它一条还是超，`allow_partial` 只能按切法切开它。真正需要保留要点、丢掉细节时，裁剪函数解决不了。`end_on` 修的是另一端：

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

上限 60 时七条都能装下，加了 `end_on="human"` 之后末尾那条 `ai` 被去掉。判据和 `start_on` 对称：以 `ai` 结尾时模型下一条会接在自己没说完的话后面，以 `human` 结尾才是等模型回答的状态。两个极端：

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

上限小到装不下一条时返回空列表，不报错。`allow_partial` 的效果取决于切法：那条 human 消息是五行文本，默认按换行切，于是保住后三行；换成按句号切，切点会细到句子：

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

同一条消息、同一个上限，切法不同，留下的半句不同。**`allow_partial` 不是切开就准，它只是允许按 `text_splitter` 切开**，切不动时仍然整条丢掉。最后一个参数是计数器本身，上面的数字都用 `count_tokens_approximately`，它按字符数估。换成真实 tokenizer：

```
近似计数: 47
gpt-4o-mini 的 tokenizer: 77
用模型做 token_counter, max_tokens=40: 3 条，真实 token=34，近似 token=20
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

同一份历史，估算 47、真实 77，差 64%。同一个上限用估算裁出 5 条，用真实 tokenizer 只裁出 3 条。这就是第 3 章估算偏差在框架里的样子：`max_tokens` 的含义由 `token_counter` 决定，卡预算要用真实 tokenizer。

`max_tokens` 该给多少也有一条顺序：窗口上限减去输出预算，再留余量给服务端可能插入的模板 token。第 1 章讲过它与窗口是两个上限，这里它只管输入部分，与请求体里那个同名参数不是同一个东西。

会怎么坏：`trim_messages` 不报错、不打点，被裁掉的消息从此消失。三个信号是 system 不在第一条、第一条是 `ai`、句子里少了一半。`include_system` 默认 `False` 有来源：这个函数按消息列表设计，system 只是第一个元素。判据很简单：裁剪之后，第一条是不是 system。

边界：这个函数只按条裁，不做摘要压缩，把长历史压成一句摘要属于「上下文装配」一章。先裁再拼时，模板与引用编号占的 token 不在预算里，实际请求会比 `max_tokens` 大。

## 七、三种流式接口

第 1 章讲过流式的三个事实：正文散在增量里、`finish_reason` 只在最后一块、`usage` 默认不返回。框架提供三个接口，语义不变。`code/knowledge/ch09_lc_basic/streaming.py` 用脚本化后端回放一份 SSE 响应体：

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

`.stream()` 产出 `AIMessageChunk`。前五块的 `content` 是增量而不是全文；第六块正文为空、只带 `finish_reason="stop"`，正是第 1 章那句收尾原因在最后一块；第七块完全为空，是流关闭时的收尾块，**不能当成模型说了空话**。把块拼起来：

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

拼出来的文本与非流式调用一致；`finish_reason` 靠块相加带过来；`usage_metadata` 是 `None`，因为响应体里没有用量。第 1 章说过 `stream_options` 这个请求参数用来让服务端在最后一帧带用量，框架不补估算值。`.astream()` 是同一件事的异步接口：

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

异步接口的理由不是更快，是等的时候能让出执行权：同步 `stream` 在等下一个块时把线程占住，所以服务端的多路输出必须用 `astream`。块的拼接有两处容易错的地方，第 6 章的工具往返会同时遇到：工具参数分块到达，`args` 在拼接完成前是残缺的；正文与工具调用可能同在一个响应里，拼接时要按块类型分别累积。第三个接口不取内容，取过程：

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

父子关系从 `parent` 列看得出来：`RunnableSequence` 是根，`RunnableLambda` 与 `ChatOpenAI` 是它的子；`on_chain_stream` 属于父层，每个模型增量都往上一层层冒一次。**这是这次调用花了多久、花在哪一层的唯一信息来源。**

三个接口的分工按要不要边生成边用、要不要过程分开：只要结果用 `invoke`；要边生成边展示用 `stream` 或 `astream`；要观察过程用 `astream_events`。首 token 延迟只有流式给得出来。

事件树还有第二个用处：把一次生成和一轮任务分开。第 1 章讲过 `finish_reason` 记的是单次生成，一轮 agent 任务里模型被调用多次；这里两者分别对应 `on_chat_model_*` 与 `on_chain_*`，数后者是轮数，数前者是调用次数，计量那一章的三个口径都从这张表取。会怎么坏：把块数当调用次数，计费与限流都会算错。日志量随输出 token 数线性涨；`astream` 是异步接口，同步脚本里要用 `asyncio.run` 包起来，否则取不到东西。边界：流式只在输出要边生成边用时值得，块不是完整消息，手写 SSE 的帧解析属于「对外形态」一章。

## 八、结构化输出的三种策略

第 4 章实现了五种把输出变成结构化数据的做法，每种都要手写请求构造与解析；第 5 章用 pydantic 定义了结构。框架里这两件事接在一处：`with_structured_output(schema, method=...)`。`code/knowledge/ch09_lc_basic/structured.py` 先打真签名：

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

`method` 有三个取值，默认是 `json_schema` 而不是 `function_calling`，旧版本默认值不同，抄来的代码要按本版本核对。目标是同一个 `RefundCheck`，第 4 章手写过这三种请求：

```python
from pydantic import BaseModel


class RefundCheck(BaseModel):
    """要取出的三个字段。"""

    order_id: str
    days: int
    reason: str
```

三种策略跑在同一份输入上，第 4 章那张表里的三种做法在这里各有一个请求体，接线部分是：请求里带 `tools` 就回放一条工具调用，否则回放正文：

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

三种策略各跑一次，模型定义沿用第 5 章那份，每次打印返回对象与请求体里的 `tools`、`tool_choice`、`response_format`：

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

`json_schema` 那一行值得细看：`required` 里三个字段齐全，`additionalProperties: false`，`strict: true`，第 4 章讲做法四时列的三条限制由框架自动生成。`function_calling` 的 tool 名用的是模型类名，参数 schema 由 pydantic 生成，这是第 5 章的定义。这就是框架替掉了什么的准确答案：它替掉了请求构造与解析。

签名里还有 `include_raw`、`strict`、`tools` 三个参数。**参数的含义要照着签名与请求体核对，不要照着教程读。** 三次返回同一类型不是巧合，解析层是统一的：拿到文本或工具参数后转成 dict，再交给 pydantic 校验。所以换 `method` 不改业务代码，只改请求体。第 4 章那五种做法里失败最典型的是字段名对不上，`json_mode` 只保证语法，模型把 `order_id` 写成 `orderId` 时：

```
OutputParserException : Failed to parse RefundCheck from completion {"orderId": "A1001", "days": 7, "reason": "签收不想要"}. Got: 1 validation error for RefundCheck

order_id
  Field required [type=missing, input_value={'orderId': 'A1001', 'day...son': '签收不想要'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
For troubleshooting, visit: https://docs.langchain.com/oss/python/langchain/errors/OUTPUT_PARSING_FAILURE 
```

与第 4 章那张表里 `JSON mode` 那一行完全同因：语法合法，字段缺失。框架把 pydantic 的报错包进 `OutputParserException`，两个原因都保留。区别在于它抛出异常，异常里没有原始文本时重试要重新调用一次；要留着回灌，需要 `include_raw=True`：

```
parsed: None
parsing_error 类型: OutputParserException
raw.content: {"orderId": "A1001", "days": 7, "reason": "签收不想要"}
```

`include_raw=True` 返回三个键：`parsed`、`raw`、`parsing_error`。第 4 章做法五那套把失败原因当证据回灌的写法，原料就在这里。框架提供原料，回灌策略仍要自己定。

会怎么坏：三种策略都依赖服务端能力，`json_schema` 要严格 schema，`function_calling` 要强制 `tool_choice`，`json_mode` 要 `json_object`。框架不做能力探测，不支持时照样把请求发出去。选哪种的顺序与第 4 章一致：能确认支持就选 `json_schema`；不确定时先用 `function_calling` 试一次，看返回里有没有 `tool_calls`；都不行才退回 `json_mode` 加本地校验。这个顺序是失败代价的排序。

边界：这一层只做到结构对。语义校验不在这一层，第 4 章讲的三层校验里只有前两层被接走。重试策略也不在这一层，下一章的自愈解析器把失败后自动再试一次封装成一个对象。

## 九、框架没有替掉的部分

第 1 章到第 8 章的手写做法在前面几节逐一对照过，把结论放在一起能填一张三行的表：

| 对照项 | 结论 | 证据 |
|---|---|---|
| 替掉了哪段 | 编码与解析：请求体、消息装配、帧到块、JSON 到对象 | 第 1 章手写的请求体在这里是一个 `init_chat_model` 加两个消息类；第 4 章的做法三到这里是一个 `method` 参数 |
| 没替掉哪段 | 判断：`finish_reason` 分支、预算与终止、语义校验、重试条件 | 元信息那一节只搬字段；裁剪那一节只算 token；结构化那节只做前两层校验 |
| 代价 | 参数变多、隐式行为变多、版本会漂 | 一行 `init_chat_model` 背后是五个参数；`config_prefix` 写错完全无声；`.role` 属性消失、`method` 默认值变化 |

判据可以简化成两个问题。**第一，这段代码换成手写版要写几行，这些行与业务有关吗？** 无关的就是框架该接管的。**第二，删掉业务规则之后这段还成立吗？** 成立的被替代，不成立的就是自己的。这两问还能判断要不要现在换框架。已经有自己的封装时，框架的价值只剩换厂商不用改业务代码，那就该比较这层封装与框架的维护成本。先把第 1 章的分支写对更要紧。代价里最需要记住的是版本漂移，这一章有三处证据：`.role` 属性在 1.x 不存在，`ChatOpenAI` 从 `langchain.chat_models` 搬到 `langchain_openai`，`with_structured_output` 的默认 `method` 是 `json_schema`。

一条排查纪律：凡是应该生效却没生效的问题，第一步不是读源码，是**把请求体打出来**。边界：一次性的单文件脚本、需要精确控制请求体来排查问题、对版本升级极敏感的长跑系统，直接用手写版更省事。框架的收益在调用点多、要换厂商、要接流式三件事同时成立时才明显。

## 这一章建立的 7 件事

1. 四个包的职责、版本需求区间，以及两个真实报错的成因（`ModuleNotFoundError` 与 `ImportError` 要分开处理）
2. `init_chat_model` 五个参数各管什么，`model` 与 `model_provider` 的两种写法等价
3. `base_url` 接兼容端点、`configurable_fields` 加 `config_prefix` 改参数的两条路径，以及前缀写错的静默失效
4. 四种消息的 `type` 值与请求体 `role` 的对应，`content` 与 `content_blocks` 的分工
5. 三类元信息与第 1、3 章字段的对应，`usage_metadata` 可能为 `None`、私有字段会被丢掉
6. `trim_messages` 六个参数的默认值，`include_system` 必须配 `start_on`，`max_tokens` 的口径由 `token_counter` 决定
7. 三种流式接口的产物与事件树，三种结构化策略的请求形态，以及它们各自与第 1、4、5 章的对应

## 下一章

把这一章的对象拼起来才是真实代码：一次调用、一条消息、一个裁剪函数，校验在前、模型在中、解析在后，中间出错要能重试，还要能批量与并行。第 10 章讲这一步：可执行单元之间的输入输出约定、七个组合子、提示词模板与四种解析器，以及 `astream_events` 在组合之后才显出来的那棵树。

---

[← 第 8 章 · 循环的四种失控](./08-循环的四种失控.md)　｜　[卷 3 目录](./docs/INDEX.md#vol3)　｜　[第 10 章 · LangChain 组合与解析器 →](./10-LangChain组合与解析器.md)
