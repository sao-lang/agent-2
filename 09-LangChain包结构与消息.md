# 第 9 章 · LangChain 包结构与消息

> **卷 3 · LangChain（agent 侧）（第 9–12 章）**｜[全书目录](./INDEX.md#vol3)｜[本卷导读](./outline/vol03-LangChain.md)
>
> - **知识点**：F1 包结构与模型接入 —— init_chat_model 的参数矩阵与三种结构化输出策略；F2 消息与内容块 —— 四种消息类型，content 与 content_blocks 的区别（编号定义见 [知识点-F-框架层](./outline/16-知识点-F-框架层.md)）
> - **本章回答**：一次调用在框架里被拆成哪几个对象，每个对象替掉前八章手写的哪一段，剩下的哪一段仍然要自己写
> - **示例目录**：`code/knowledge/ch09_lc_basic/`
> - **读完应当能回答**：给一段 LangChain 代码，说出每个参数落在哪一层、对应手写版的哪几行、以及框架没有接管的部分在哪

---

版本以本机安装为准：`langchain` 1.4.7、`langchain-core` 1.7.0、`langchain-openai` 1.1.9、`langchain-community` 0.4.2。框架的符号在小版本之间会挪位置，本章后面会给出几条真实的、与版本有关的报错，所以这四个数字是正文的一部分，不是装饰。

示例目录里的 `scripted_chat.py` 是脚本化后端：给 `ChatOpenAI` 换掉 httpx 的传输层，请求照常编码成一个真实的 chat completion 请求，响应来自脚本。**本章所有输出都是脚本化后端跑出来的，原理演示，不是模型实测**——它演示的是框架怎么编码、怎么解析、怎么搬运字段，不是某个模型会怎么回答。换真实服务时只改构造模型的那一处：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", api_key="sk-...", base_url="https://api.openai.com/v1")
```

`base_url` 指向任何兼容 OpenAI 协议的服务都可以，其余代码不动。

## 一、手写的四处重复

第 1 到第 8 章的手写代码里，有五段几乎每个项目都要重写一遍：

| 手写位置 | 那段代码在做什么 |
|---|---|
| 第 1 章 | 拼请求体：把 system / user / assistant 的角色和文本组装成 `messages`，加上 `temperature`、`max_tokens` |
| 第 1 章 | 读响应：从 `choices[0].message` 取 `content` 与 `tool_calls`，取 `finish_reason`，取 `usage` |
| 第 3 章 | 数 token 与裁剪：估算、按上限裁掉最早的轮次 |
| 第 4 章 | 结构化输出：构造 `tools` 或 `response_format`，再把返回的字符串解析成对象 |
| 第 6 章 | 工具往返：把一次调用与它的结果装配成三条消息 |

这五段有同一个性质：**它们的输入输出与业务无关，写法与厂商、与调用形态有关。** 换一家厂商，第一段要改 URL 与认证头，第二段要改字段名；加一种调用形态（流式、批量、可配置参数），同样的装配逻辑要再写一份；把结果变成结构化数据，同一条解析代码要在每个调用点重复一遍。

复制带来的问题不是行数，是失效方式被混在一起。第 1 章讲过 `content` 为空有三种原因：被截断、被拦截、在要工具，三种要走三条分支；第 4 章讲过 JSON mode 保证语法不保证字段名；第 6 章讲过工具参数的 `arguments` 是字符串。这些区分在单个文件里写得下，复制到十几个调用点之后，就没有人记得哪一处漏了分支。

为什么手写版一定会走向复制？因为这段代码有四个互相独立的可变点：

| 可变点 | 变一次要改什么 | 谁在变 |
|---|---|---|
| 厂商 | URL、认证头、字段名、`finish_reason` 的取值集合 | 换模型、接网关、做 A/B |
| 调用形态 | 同步、流式、批量、可配置参数 | 界面要打字机效果、后台要跑批 |
| 输出结构 | 纯文本、JSON、工具调用 | 从"给人看"变成"给程序用" |
| 历史长度 | 装得下、要裁剪、要压缩 | 对话轮次增加 |

四个可变点两两组合就是十几种写法，而手写版把四个都编在同一段代码里。框架的处理方式不是"写一段更聪明的代码"，而是把四个可变点分别收进四样东西：厂商进适配包，调用形态进三个接口（`invoke`、`stream`、`astream`），输出结构进 `with_structured_output`，历史长度进 `trim_messages`。本章的七节基本就是按这四样东西排的。

框架做的事是把"与厂商有关的部分"收进一层：消息变成四个类，模型变成 `ChatOpenAI`，裁剪变成一个函数 `trim_messages`，结构化输出变成一个包装 `with_structured_output`。业务代码只跟这几样东西打交道，不再直接拼 JSON。

框架没有做的事同样要一开始说清：**它搬字段，不做判断。** 一条回复能不能用（第 1 章四个取值的分支）、这次调用花了多少钱（第 3 章的计价）、这个值合不合理（第 4 章的语义校验）、循环要不要继续（第 7、8 章）——这些判断依赖业务语义：哪笔订单能退、什么回答算可用。框架手里没有这份信息，所以它不可能替你做。

把这两类事搞混，后果是"以为有了一层保护，实际上保护在框架之外"。这一章按"从哪 import → 怎么连 → 装什么 → 读什么 → 放不下怎么办 → 怎么一块块拿 → 怎么变成对象"走，每一节的结构相同：先给签名与参数，再给最小例子和真实输出，然后指出它替代主线哪一段，最后说它做不到什么。

主线先手写、这里再看框架，顺序不能倒。手写版讲清了"这一步为什么必须有"，框架版讲的是"工程里这一段长什么样"。反过来学的人，会在框架不覆盖的地方（比如 `finish_reason` 的分支）失去判断依据，只会在框架给的钩子里找答案。所以这一章每出现一个 API，都要能回答一句"它替代的是前面哪一章手写过的什么"——答不上来的 API，说明还不知道它解决的是哪个问题。

## 二、四个包的分工

装完之后遇到的第一个问题不是 API，是 import。LangChain 1.x 的代码分布在四个发布包里，**包名和 import 路径不同名**，两者对不上时，报错不会告诉你该装哪个。

`code/knowledge/ch09_lc_basic/versions.py` 把版本、依赖区间和符号归属一起打出来：

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

第三列是每个包对 `langchain-core` 的需求区间。这一列解释了为什么四个包要一起看：`langchain 1.4.7` 要求 core `>=1.6.13`，`langchain-openai 1.1.9` 要求 core `>=1.2.11`，两条要求取交集，core 的最低版本由最严的那个包决定。所以四个包不是一个一个独立升级的——core 走在前面，另外两个跟它对齐。把 core 停在 1.2 而 langchain 升到 1.4.7，pip 会直接拒绝安装，这比运行时出错好；但这只在装的时候成立：用 `--no-deps`、或者镜像里缓存了旧 wheel 时，装得上，跑起来才会发现少了符号。

落到工程里，就是把这四个版本号连同传递依赖一起钉住。传递依赖也钉的理由是 `langchain-openai 1.1.9` 对 `openai` 包有区间要求（`>=1.109.1,<3.0.0`），区间很宽，不钉的话同一条命令在不同时间装出的 `openai` 版本可能不同——而响应解析的细节由它决定。这一章的每个输出都是在 `openai 1.109.1` 上跑出来的。

第二块输出是符号归属。四个符号分散在三个包里：模型入口在 `langchain`，厂商适配在 `langchain-openai`，消息与裁剪在 `langchain-core`。这张表是本章每个例子的 import 行的依据。

四个包为什么这样切，从依赖方向看得出来。`langchain-core` 只放与厂商无关的东西：消息类、可执行单元协议、裁剪、回调。它不 import 任何厂商 SDK，所以它是唯一能被所有适配包依赖的一层。`langchain` 放编排与入口：`init_chat_model`、`create_agent`，它依赖 core，在需要时才去 import 某个厂商包。`langchain-openai` 放与一家 SDK 对齐的东西：请求编码、响应解析、能力声明，它依赖 core 与 `openai`。`langchain-community` 放没有正式维护者的集成，质量与更新节奏都不如官方包，本章不用它。

这两个入口各替一段手写的活：`init_chat_model` 替第 1 章"拼请求体 + 选厂商"那几行，本章讲它；`create_agent` 替第 7 章那个最小循环，到第 12 章才讲。先记住分工，比先记参数有用。

这个切法给出一个查符号的方法：**看一个符号在哪，就看它依赖谁。** 与协议无关的对象在 core；需要"选厂商"的在 `langchain`；需要一家 SDK 的在 `langchain-<vendor>`。`versions.py` 第二块用 `hasattr` 在每个候选模块里找一遍，比翻文档快——本章后面每出现一个新符号，都可以用这三行代码确认归属。

包拆开之后，旧路径就消失了。`versions.py` 的第三块把四个旧 import 原样跑了一遍：

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

四条报错有同一个来源：0.x 到 1.x 的拆包。`langchain.chains`、`langchain.memory` 不再是 `langchain` 的子模块（迁到 `langchain-classic`），文本切分迁到 `langchain-text-splitters`，厂商类迁到各自的 `langchain-<vendor>` 包。这就是"从旧教程抄一行 import"最典型的失败形态：报错只说模块不存在，不说该装哪个包。

这也解释了为什么本章的示例目录里只有一个 `scripted_chat.py` 而不带 `langchain-classic`：本章用到的符号全在 core、`langchain` 与 `langchain-openai` 三个包里，用不到迁移出去的那两块。后面处理文档与切块的章节才会碰到 `langchain-text-splitters`，那里是另一个包、另一套依赖。

四条里第三条值得单独看：它的类型是 `ImportError` 而不是 `ModuleNotFoundError`——`langchain.chat_models` 这个模块还在（它是 `init_chat_model` 的入口），只是里面不再有 `ChatOpenAI`。同一种"路径变了"的事，报错类型不同，处理方向也不同：`ModuleNotFoundError` 去找包，`ImportError` 去改符号的归属。

边界：这一节没有可替代的手写代码，它决定的是本章每个例子的 import 行，以及一条更实际的判断——遇到 import 报错，先分清"包没装"与"符号换了包"。前者补依赖，后者改路径；按报错信息猜错方向，会一直改不到点上。

## 三、模型接入的参数

第 1 章的请求体里，`model` 是字符串、`temperature` 是数字，两个值都写在业务代码里；第 1 章的协议层对照把这条路摊开过：URL、认证头、请求体，各是一行。换厂商要动这几行，换一种"同一模型不同参数"的实验也要动这几行。

`init_chat_model` 把这一段收成一个函数：按厂商找到适配类，把参数透传下去。先核对签名，这是本章所有例子核对 API 的共同做法：

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

参数表只能看出"传什么"，看不出"什么时候生效"。接下来的四个情形是同一个函数的四种用法，每个都打印返回类型与真实请求体：

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

情形一和情形二达到的是同一个结果，区别只在写法。返回类型是 `ChatOpenAI` 而不是某个"通用模型"——`init_chat_model` 不做抽象，它做的是一次映射：拿到 `model_provider="openai"`，import `langchain_openai`，实例化 `ChatOpenAI`，其余关键字原样传下去。所以它不改变请求体：`model` 字段仍然是 `demo-model`，URL 仍然是厂商地址。

这个 URL 值得单独看：`https://api.openai.com/v1/chat/completions` 是 `base_url` 的默认值。本例里请求没有离开本机——`http_client` 被换成了 `MockTransport`，传输层被截住了。这是脚本化后端的工作方式，也是后面"接兼容端点"那一节的前提：**URL 由 `base_url` 决定，请求发不发得出去由传输层决定，两件事互不影响。**

```
== 情形三：configurable_fields ==
返回类型: _ConfigurableModel
默认 temperature: None
config 里的 temperature=0.9 -> 0.9
with_config 改成 0.2 -> 0.2
```

`configurable_fields` 把字段从构造期挪到调用期。给了它之后，返回类型变成 `_ConfigurableModel`，字段值在 `invoke` 时才定型：`config={"configurable": {"llm_temperature": 0.9}}` 让这一次请求带 0.9，`with_config` 则把一份配置固定在对象上，之后每次调用都用它。

这段替代的是第 1 章里"把 `temperature` 写进请求体"的那一行。手写版每换一个值就要改一次代码或加一个参数；这里的值来自调用方传进来的 `config`，业务代码不用知道温度是多少。代价是类型变了：`_ConfigurableModel` 不是 `ChatOpenAI`，取模型属性、判断 `isinstance` 都会失效。

`config_prefix` 的存在理由是一次调用里可能有多个对象要配：主模型一个温度、便宜的小模型另一个温度、检索器还有一个 `k`。`config` 是一个扁平的字典，前缀把命名空间分开，`llm_temperature` 与 `router_temperature` 才能同时存在。所以前缀不是可有可无的装饰，它决定了键名怎么拼——也因此写错前缀时不会报错，只会读到一个不存在的键。

```
== 情形四：base_url ==
base_url 指向本机 8080 后，请求 URL: http://127.0.0.1:8080/v1/chat/completions
```

`base_url` 只改一件事：请求打到哪个主机。这就是"接兼容端点"的全部机制——自建网关、代理、本地推理服务，只要实现 OpenAI 协议的那几个路径，把 `base_url` 指过去就是一个可用的模型。第 3 章讲换厂商时要改的东西里，URL 是第一件，这里它变成一个关键字参数。

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

情形五最危险：**它是一行代码没生效，而且没有报错。** 设了 `config_prefix="llm"` 之后，键名必须是 `llm_temperature`；写成 `temperature` 时这个值被静默丢掉，请求体里没有 `temperature` 字段，模型用默认温度。这类失效在线上表现为"调了参数但输出风格没变"，从代码里看不出来，只能从请求体里看出来。

要读懂"没进请求体"这一行，还得知道默认值是什么：`temperature` 的默认值是 `None`，而 `None` 的含义是"这个字段不传"，服务端按自己的默认值处理。所以"没生效"与"传了默认值"在请求体里看起来一样——都是字段缺省。判据是看字段在不在，而不是看值等于多少。

情形六是同类问题的另一种时机：`foo` 不在 `init_chat_model` 的参数表里，也不在 `ChatOpenAI` 的字段里，构造时只给一条 `UserWarning`，把它塞进 `model_kwargs`；直到真正发请求、openai 客户端组装参数时，才变成一个 `TypeError`。**警告被日志淹没的那一刻，错误已经被推迟到了调用路径上。**

情形七是唯一"立刻失败"的：厂商推断不出来，`ValueError` 列出支持的标识。推断规则是按模型名前缀匹配，`demo-model` 不含任何已知厂商前缀，所以推不出来；`openai:demo-model` 或 `model_provider="openai"` 都能通过。

边界：`init_chat_model` 只解决"选类 + 传参"。它不替你选参数取值（温度给多少、上限给多少，第 1 章讲过这两个值各自决定什么），也不处理厂商能力差异（严格 schema、`tool_choice` 强制调用，第 4 章讲过）。还有一条容易忽略的：它是按需 import——只有在 `model_provider="openai"` 时才会 import `langchain_openai`，所以"装错包"的报错发生在调用 `init_chat_model` 之后，而不是 import 时。

## 四、四种消息与内容块

第 1 章的 `messages` 是 dict，键由调用方随便写；框架里消息是四个类，每个类除了 `content` 还多出两样东西：内容块和元信息。**用错字段不会在发送时报错**——dict 能编码成任何形状，服务端按自己的理解处理，错误要到回复里才显形。

`code/knowledge/ch09_lc_basic/messages.py` 先造出四条消息，打印类名、`type` 与内容：

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

0.x 的消息对象有 `.role`，1.x 只有 `.type`。写代码时用 `type`，读请求体时看 `role`，两套名字混用会得到 `AttributeError` 或一个永远为假的条件。

接下来是重点：同一条回复有两种读法。

```
== 文本回复的两种读法 ==
content: '签收后 7 天内可退。'
content_blocks: [{'type': 'text', 'text': '签收后 7 天内可退。'}]
```

`content` 是这条消息的文本原样；`content_blocks` 是把 `content` 连同其它字段归一化成"块"的视图。纯文本时两者几乎等价：一个是字符串，一个是只含一个 `text` 块的列表。差别出现在下面两种情况里。

```
== 工具调用回复 ==
content: ''
tool_calls: [{'name': 'get_order', 'args': {'order_id': 'A1001'}, 'id': 'call_demo', 'type': 'tool_call'}]
content_blocks: [{'type': 'tool_call', 'name': 'get_order', 'args': {'order_id': 'A1001'}, 'id': 'call_demo'}]
```

模型要动作时，`content` 是空字符串，动作在 `tool_calls` 里，`content_blocks` 里对应一个 `tool_call` 块。对照第 1 章：手写版里 `content` 是 `null`，代码要判 `if content is None`；框架把它归一成了空字符串，于是"没有正文"和"生成了空内容"这两件事在 `content` 上彻底分不开了——要区分只能看 `tool_calls` 或 `content_blocks`。

还有一处细节：`tool_calls[i]["args"]` 是 dict，而请求体里仍然是 JSON 字符串。回灌工具结果时能看清这一点：

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

三行请求体是这个往返的全部内容。要指出两点：第一，`assistant` 那条的 `content` 在发出时又变回了 `null`——空字符串与 `null` 只在对象层被抹平，协议层仍然区分。第二，`tool` 那条必须带 `tool_call_id`，值等于上一条里 `tool_calls[0].id`。**这是第 6 章手写往返里最容易错的一处**：手写时 id 是自己拼的，框架里 id 从响应带出来，回灌时照抄即可，抄错则服务端拒绝或对不上号。

最后一种情况是内容块的归一化：

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

`content` 里没有推理内容，`content_blocks` 里有一个 `reasoning` 块，它来自 `additional_kwargs` 里的厂商私有字段。这是两种读法的真正区别：**`content` 是协议里的那个字段，`content_blocks` 是把消息里所有能当成内容的东西排成一列。** 读推理过程要读块，读正文读 `content` 就够。

为什么不直接用 dict？因为一次调用有两个方向都需要转换：发送前把对象编码成 dict，收到后把 dict 解码成对象。dict 没有地方放这段逻辑，于是每个调用点各写一份，厂商一换就有一处漏改。四个类把两个方向都收在适配层里，业务代码只面对对象。这也是为什么 `ToolMessage` 的 `content` 仍然是字符串而不是对象：工具结果是调用方自己产出的内容，框架不该假设它是 JSON——`{"status": "已签收"}` 与一句自然语言在协议层是一样的，序列化由调用方负责。

边界：块类型的集合由适配层决定（文本、图片、推理、工具调用、服务端工具结果……），跨厂商不统一；`content_blocks` 是生成出来的视图，写回去的仍然是 `content`。所以"能不能用 `content_blocks` 做业务判断"取决于你锁定的适配包版本，而不是协议。

## 五、三类元信息

第 1 章的响应只有四个字段，用起来很清楚。框架把它们拆成三个属性，其中一个专门装"厂商原样"：不知道去哪读，代码就会退化成只读 `reply.content`——第 1 章开头那个写法，只是换了个属性名。

`code/knowledge/ch09_lc_basic/metadata.py` 把一次正常回复的四个属性全打出来：

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

`usage_metadata` 是第 3 章那三个数的改名版：`prompt_tokens` 变成 `input_tokens`，`completion_tokens` 变成 `output_tokens`，总量不变，明细拆进 `input_token_details` 与 `output_token_details`（缓存命中、推理 token 都在里面）。同一个数在 `response_metadata["token_usage"]` 里还有一份，用的仍是原始字段名。两处都能读到，跨厂商的代码只该读第一处。

为什么同一个数要放两处？因为两层管的事不同：`response_metadata` 是"这次响应长什么样"，键由适配层按厂商原样填；`usage_metadata` 是"这次调用消耗了多少"，字段名由协议层统一。第 3 章的成本代码需要一个稳定的字段名，跨厂商只有第二处稳定。两处不一致时（适配层只搬不改，一般不制造差异），以 `usage_metadata` 为准。

`finish_reason` 只有一处，在 `response_metadata` 里。第 1 章讲的四个取值在这里一个不少，处理分支也一模一样——框架搬了这个字段，没搬分支：

```
被拦截的回复：
  content: ''
  additional_kwargs: {'refusal': '无法回答该请求'}
  response_metadata: {'token_usage': {'completion_tokens': 0, 'prompt_tokens': 24, 'total_tokens': 24, 'completion_tokens_details': None, 'prompt_tokens_details': None}, 'model_provider': 'openai', 'model_name': 'demo-model', 'system_fingerprint': None, 'id': 'chatcmpl-demo', 'finish_reason': 'content_filter', 'logprobs': None}
  usage_metadata: {'input_tokens': 24, 'output_tokens': 0, 'total_tokens': 24, 'input_token_details': {}, 'output_token_details': {}}
```

这是第 1 章"被拦截"那一行的框架读法：`content` 是空字符串，`finish_reason` 是 `content_filter`，另外多了一样东西——`refusal` 字段里的拦截说明。手写版通常把这段说明丢掉，只留一个空字符串，于是"被拦截"和"模型没话说"在业务代码里长得一样；`additional_kwargs` 把它保住了。

四个属性各自的位置可以这样记：**`content` 是给业务看的，`usage_metadata` 是给账本看的，`response_metadata` 是给排查看的，`additional_kwargs` 是给"这个厂商还有别的字段"看的。** 四者不重叠，任何一处缺失都意味着某类信息在这条链路上断了——比如 `usage_metadata` 为 `None` 时账本断了，`response_metadata` 里没有 `finish_reason` 时排查断了。

代价是字段可能不存在。服务端不回 `usage` 时：

```
usage_metadata: None
response_metadata['token_usage']: None
```

两个属性都不报错，都是 `None`。这就是第 3 章那条"`usage` 是实际值"的反面：拿不到实际值时，框架给的是 `None`，不是估算值。成本统计代码直接写 `reply.usage_metadata["input_tokens"]`，会在这一行抛 `TypeError`；写成 `or {}` 兜底，则这一次调用的成本被记成 0——两种都错，正确的处理是记"未知"并在对账时单列。

再一种情况是响应里多出字段：

```
消息对象里能找到 x_vendor_field 吗: False
additional_kwargs 的键: ['refusal']
```

厂商私有字段在解析时被丢掉，消息对象里没有原文。要做对账或排查，只能在传输层留一份原始响应——这就是为什么后面讲计量的那一章，抓取点放在传输层而不是放在消息对象上。

最后把七个字段摆在一起，看框架到底搬了什么：

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

结论只有一句：**框架搬字段与改名，没搬口径。** `finish_reason` 的含义、四个取值怎么分支（第 1 章）、三个 token 数怎么换算成钱、缓存部分按哪个价（第 3 章）——这些都没进框架。

边界：跨厂商能依赖的只有 `usage_metadata` 与 `response_metadata["finish_reason"]` 这两样，其余键由适配层决定——`system_fingerprint`、`logprobs` 这类字段只有部分厂商有，写进业务判断就会在换厂商时炸。

## 六、裁剪的六个参数

第 3 章讲过窗口满了会怎样：请求被拒、生成中途被截断、溢出时丢的是最早的轮次。手写的应对是一段从后往前数 token 的循环；框架里是一个函数。函数有六个参数（签名里还有第七个 `text_splitter`，下面单独说），其中两个默认值与直觉相反：`include_system` 与 `allow_partial` 都是 `False`。

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

参数名能看懂，默认值看不出来。下面这些情形跑的是同一份六条历史（47 token）。先看前两个，它们解释 `strategy` 与 `include_system` 为什么要分开设：

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

第一段的 5 条里没有 system：`include_system` 默认 `False`，system 被当成普通消息一起参与了裁剪，然后被挤掉。第 1 章说过 system 是指令层，丢了它等于换了一套指令，而这一步**不报错、不打日志**。

第二段开了 `include_system=True`，system 回来了，但列表第一条是 `ai`——对话从模型的话开始。这种序列对多数服务端都不合法（第一条非 system 应当来自 user），而 `trim_messages` 不会替你修正，它只管 token 数：

```
include_system=True, start_on='human':
  30 token，4 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

`start_on="human"` 把开头修成 human，代价是又多裁掉一条。这两段合起来说明一件事：**`include_system` 与 `start_on` 必须成对使用**，只开前者会得到从 `ai` 开头的非法序列。

`strategy` 决定丢哪一头：

```
strategy='first', max_tokens=40:
  34 token，4 条
    system  '你是退货政策助手，只回答与退货相关的问题。'
    human   '订单 A1001 能退吗？'
    ai      '请提供签收时间和商品状态。'
    human   '签收 7 天，未拆封。'
```

从前往后装，留下的是开头四条，最后那句问题被丢掉了。`first` 适合"历史里前因重要"的场景（比如一次任务的开场指令），`last` 适合多轮对话。注意 `first` 与 `include_system`、`start_on` 互斥：

```
{'strategy': 'first', 'include_system': True} -> ValueError: include_system parameter is only valid with strategy='last'
{'strategy': 'first', 'start_on': 'human'} -> ValueError: start_on parameter is only valid with strategy='last'
```

两个参数只在 `strategy="last"` 下成立，配 `first` 直接 `ValueError`。这比静默忽略好——它在开发期就能发现。

默认 `strategy="last"` 的理由与第 3 章的结论一致：溢出时要保的是最近的上下文，最早那几轮最该丢。`first` 的用处是另一种：长文档任务里，开场那条 system 之后的"任务说明"和"输出格式"比中间十几轮探索更重要，这时从头保留、把末尾的中间结果丢掉反而是对的。选哪个，取决于"下一句依赖哪一段"，不取决于哪个更快。

还有一处容易被忽略：**裁剪的单位是条，预算是 token。** 一条超长消息（比如一次贴进去的日志）可以独占整个上限，这时裁到只剩它一条还是超；`allow_partial` 只能按切法切开它。真正需要"保留要点、丢掉细节"时，裁剪函数解决不了，那是摘要与压缩的活。

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

上限 60 时七条都能装下，包括最后一条 `ai`；加了 `end_on="human"` 之后，末尾那条 `ai` 被去掉。判据和 `start_on` 对称：一段历史如果以 `ai` 结尾，模型下一条回复会接在自己没说完的话后面；以 `human` 结尾才是"等模型回答"的状态。

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

上限小到装不下一条时返回空列表，不报错。`allow_partial` 的效果取决于切法：那条 human 消息是五行文本，默认按换行切，于是保住了后三行；如果换成按句号切，切点会细到句子：

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

同一条消息、同一个上限，切法不同，留下的半句不同。**`allow_partial` 不是"切开就准"，它只是"允许按 `text_splitter` 切开"；切不动时（一条没有换行的长消息配默认切法）它仍然整条丢掉。**

最后一个参数是计数器本身。上面的数字都用 `count_tokens_approximately`，它按字符数估。换成真实 tokenizer：

```
近似计数: 47
gpt-4o-mini 的 tokenizer: 77
用模型做 token_counter, max_tokens=40: 3 条，真实 token=34，近似 token=20
    human   '签收 7 天，未拆封。'
    ai      '符合退货条件。'
    human   '那退款多久到账？'
```

同一份历史，估算 47、真实 77，差 64%。同一个 `max_tokens=40`，用估算裁出 5 条（近似 37），用真实 tokenizer 只裁出 3 条（真实 34，近似 20）。这就是第 3 章"估算偏差"在框架里的样子：**`max_tokens` 的含义由 `token_counter` 决定，换一个计数器，同一个数字对应不同的东西。** 卡预算要用真实 tokenizer，做排序、比较长短用估算即可。

`max_tokens` 该给多少，也有一条判断顺序：窗口上限减去输出预算，再留一点余量给服务端可能插入的模板 token。第 1 章讲过 `max_tokens` 与窗口是两个上限，两个都超了才有问题；这里 `max_tokens` 只管输入部分，它与请求体里那个 `max_tokens` 不是同一个东西——同名，位置不同，一个在客户端的裁剪函数里，一个在服务端的生成参数里。写代码时这两个值都在手上，最容易出的错是把其中一个调对、另一个没动。

会怎么坏：`trim_messages` 不报错、不打点，被裁掉的消息从此消失。三个具体信号：system 不在第一条（没开 `include_system`）、第一条是 `ai`（没设 `start_on`）、句子里少了一半（开了 `allow_partial` 而切点不对）。

`include_system` 默认 `False` 这件事本身有来源：这个函数是按"消息列表"设计的，system 只是列表里的第一个元素，没有特殊地位。要让 system 有特殊地位，得显式声明——这与第 1 章的排序一致：指令层在最前，且不参与"最近几轮"的取舍。默认值把这件事交给了调用方，代价是忘记声明时它安静地失效。判据很简单：**裁剪之后，第一条是不是 system。**

边界：这个函数只按"条"裁，不做摘要、不做压缩——把长历史压成一句摘要属于「上下文装配」一章的事。它也不知道哪些消息相对更该保留（工具结果往往比寒暄更有用），只能按位置与类型裁。还有一处顺序问题：裁剪放在模板拼装之前还是之后，结果不同——先裁再拼，模板与引用编号占的 token 就不在预算里，实际请求会比 `max_tokens` 大。

## 七、三种流式接口

第 1 章讲过流式的三个事实：正文散在增量里、`finish_reason` 只在最后一块、`usage` 默认不返回。手写要处理的正是这三件事；框架提供的是三个接口，语义不变。

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

`.stream()` 产出 `AIMessageChunk`。三件事：前五块的 `content` 是增量，不是全文；第六块正文为空、只带 `finish_reason="stop"`，正是第 1 章那句"收尾原因在最后一块"；第七块完全为空，是流关闭时的收尾块，**不能当成"模型说了空话"**。

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

拼出来的文本与非流式调用一致；`finish_reason` 靠块相加带过来；`usage_metadata` 是 `None`——因为这个 SSE 响应体里没有 `usage`。第 1 章说过要 `stream_options={"include_usage": True}` 服务端才在最后一帧带用量，框架不会自己补一个估算值。计量的依据在这里同样是"服务端给了才有"。

`.astream()` 是同一件事的异步接口，逐块产出的顺序与 `stream()` 一致：

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

异步接口存在的理由不是"更快"，是"等的时候能让出执行权"：一个进程要同时处理多个用户的生成，同步的 `stream` 在等下一个块时会把线程占住。所以服务端的多路输出必须用 `astream`；一次性脚本用 `stream` 就够，不必把整个调用链改成异步。

块的拼接有两个坑，第 6 章的工具往返会同时遇到。一是工具参数分块到达：函数名与参数 JSON 散在多个块里，`tool_calls` 的 `args` 在拼接完成前是残缺的，边收边解析会得到半截 JSON。二是正文与工具调用可能同在一个响应里，拼接时要按块类型分别累积，不能假定 `content` 是字符串——流式下它是增量的字符串，工具块另走一路。

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

这张表就是一次调用的完整过程记录，共四类事件：

| 事件名 | 什么时候发 | 拿它做什么 |
|---|---|---|
| `on_chain_start` / `on_chain_end` | 一段可执行单元开始 / 结束 | 计时、数层数 |
| `on_chain_stream` | 组合把中间结果往下传 | 看每一层产出了几次 |
| `on_chat_model_start` | 模型调用开始 | 请求发出时刻 |
| `on_chat_model_stream` / `on_chat_model_end` | 每个增量 / 生成结束 | 首 token 延迟、增量拼接 |

父子关系从 `parent` 列看得出来：`RunnableSequence` 是根，`RunnableLambda` 与 `ChatOpenAI` 是它的子；`on_chain_stream` 属于父层，出现次数与子层的产出次数相同——每个模型增量都往上一层层冒一次。**这是"这次调用花了多久、花在哪一层"的唯一信息来源**，也是后面讲计量的那一章里 span 树的雏形。把两步拼起来才出现父子关系，拼法本身是下一章的内容，这里只借它取过程。

三个接口的分工可以按"要不要边生成边用"和"要不要过程"分开。只要最终结果，`invoke` 就够；要边生成边展示，用 `stream` 或 `astream`；要观察过程（首 token 延迟、每层耗时、出错的层），用 `astream_events`。首 token 延迟这个数只有流式给得出来：非流式调用要到整段生成结束才返回，一次往返只有一个时间点，用户实际等待的第一个字什么时候出现，从 `invoke` 里读不出来。

事件树还有第二个用处：把"一次生成"和"一轮任务"分开。第 1 章讲过 `finish_reason` 记的是单次生成，一轮 agent 任务里模型被调用多次；在 `astream_events` 里这两件事分别对应 `on_chat_model_*` 与 `on_chain_*`，数后者的次数就是轮数，数前者就是调用次数。后面讲计量时，成本、延迟、轮数这三个口径都要从这张表里取，而不是从某一次响应的 `usage` 里推。

会怎么坏：把块数当调用次数，计费与限流都会算错——一次调用是七个块；`on_chat_model_stream` 每个增量一条，日志量随输出 token 数线性涨；`astream` 与 `astream_events` 是异步接口，在同步脚本里要用 `asyncio.run` 包起来，直接 `for` 循环取不到东西。

边界：流式只在"输出要边生成边用"时值得（界面先出字、长回答提前判停）。块不是完整消息：工具参数会分块到达，正文要自己拼，`usage` 要服务端给。手写 SSE 的帧解析属于「对外形态」一章，框架替掉的正是那一层。

## 八、结构化输出的三种策略

第 4 章实现了五种把输出变成结构化数据的做法，每种都要手写请求构造与解析；第 5 章用 pydantic 定义了结构。框架里这两件事被接在一处：`with_structured_output(schema, method=...)`，`schema` 来自第 5 章的模型，`method` 选第 4 章的哪一种做法。

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

`method` 有三个取值，默认是 `json_schema`——不是 `function_calling`。旧版本的默认值不同，抄来的代码要按本版本核对。目标是同一个 `RefundCheck`：

```python
from pydantic import BaseModel


class RefundCheck(BaseModel):
    """要取出的三个字段。"""

    order_id: str
    days: int
    reason: str
```

三种策略要跑在同一份输入上，接线部分是：请求里带 `tools` 就回放一条工具调用，否则回放正文：

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

`json_schema` 那一行值得细看：`required` 里三个字段齐全，`additionalProperties: false`，`strict: true`——第 4 章讲做法四时列的三条限制，框架自动生成了。`function_calling` 的 tool 名用的是模型类名 `RefundCheck`，参数 schema 由 pydantic 生成（第 5 章）。这就是"框架替掉了什么"的准确答案：**它替掉了请求构造与解析，把第 4 章的手写请求体变成一次方法调用。**

签名里还有 `include_raw`、`strict`、`tools` 三个参数，本节只用到第一个。它们不影响三种策略的分工，改的是细节。**参数的含义要照着签名与请求体核对，不要照着教程读**：同一个参数在不同小版本里可能没有效果，跑一次、看请求体，比读一段说明快。

三次返回同一类型不是巧合：解析层是统一的——拿到文本或工具参数后，转成 dict，再交给 pydantic 校验，产出一个 `RefundCheck`。所以换 `method` 不会改业务代码，只改请求体；反之，业务代码里出现"判断这次用的是哪种 method"的写法，说明这一层被用错了。

第 4 章那五种做法里，失败最典型的是"字段名对不上"。`json_mode` 只保证语法，模型把 `order_id` 写成 `orderId` 时，框架的效果是：

```
OutputParserException : Failed to parse RefundCheck from completion {"orderId": "A1001", "days": 7, "reason": "签收不想要"}. Got: 1 validation error for RefundCheck

order_id
  Field required [type=missing, input_value={'orderId': 'A1001', 'day...son': '签收不想要'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
For troubleshooting, visit: https://docs.langchain.com/oss/python/langchain/errors/OUTPUT_PARSING_FAILURE 
```

与第 4 章"五种做法跑同一批输入"那张表里 `JSON mode` 那一行完全同因：语法合法，字段缺失。框架把 pydantic 的原始报错包进 `OutputParserException`，两个原因都保留着。区别在于它抛出的是异常：异常里没有原始文本时，重试要重新调用一次；要留着回灌，需要 `include_raw=True`：

```
parsed: None
parsing_error 类型: OutputParserException
raw.content: {"orderId": "A1001", "days": 7, "reason": "签收不想要"}
```

`include_raw=True` 时返回的是三个键：`parsed`、`raw`、`parsing_error`。第 4 章做法五那套"把失败原因当证据回灌"的写法，原料就在这里——`parsing_error` 是给模型看的错误说明，`raw` 是它上一轮说的原话。框架提供了原料，回灌的策略（灌什么、灌几次、什么时候放弃）仍然要自己定。

会怎么坏：三种策略都依赖服务端能力。`json_schema` 要服务端支持严格 schema，`function_calling` 要支持强制 `tool_choice`，`json_mode` 要支持 `json_object`。框架不做能力探测，不支持时它照样把请求发出去，失败发生在服务端（4xx）或解析处（`OutputParserException`）——两种错误的处理方向不同。

所以选哪种策略，顺序与第 4 章的结论一致：能确认服务端支持就选 `json_schema`（生成时约束，字段名不会错）；接的是兼容网关、不确定支持时先用 `function_calling` 试一次，看返回里有没有 `tool_calls`；两者都不行，退回 `json_mode` 加本地校验。这个顺序不是偏好，是失败代价的排序：约束越靠前，事后补救越少。

边界：这一层只做到"结构对"。语义校验（`days` 是否在 1 到 90 之间、`order_id` 在不在库里）不在这一层，第 4 章讲的三层校验里只有前两层被接走。重试策略也不在这一层——下一章的自愈解析器把"失败后自动再试一次"封装成一个对象，那是另一种替法。

## 九、框架没有替掉的部分

把前面七节放在一起，能填一张三行的对照表：

| 对照项 | 结论 | 证据 |
|---|---|---|
| 替掉了哪段 | 编码与解析：请求体、消息装配、帧到块、JSON 到对象 | 第 1 章手写的请求体在这里是一个 `init_chat_model` 加两个消息类；第 4 章的做法三到这里是一个 `method` 参数 |
| 没替掉哪段 | 判断：`finish_reason` 分支、预算与终止、语义校验、重试条件 | 元信息那一节只搬字段；裁剪那一节只算 token；结构化那节只做前两层校验 |
| 代价 | 参数变多、隐式行为变多、版本会漂 | 一行 `init_chat_model` 背后是五个参数；`config_prefix` 写错完全无声；`.role` 属性消失、`method` 默认值变化 |

判据可以简化成两个问题。**第一，这段代码换成手写版要写几行、这些行与业务有关吗？** 无关的就是框架该接管的（编码、解析、装配）。**第二，删掉业务规则之后这段还成立吗？** 成立的（把消息发出去）是被替代的；不成立的就是自己的（该不该发、能不能用、值不对怎么办）。

这两问还能用来判断"要不要现在换框架"。已经在写的项目里，如果每个调用点都有自己的一份请求体拼装与解析，换成这四样东西的收益最大；如果只有一处调用，换不换都无所谓，先把第 1 章的分支写对更要紧。反过来，项目里已经有一层自己的封装（比如一个 `call_model` 函数），框架的价值就只剩"换厂商时不用改业务代码"——那就该比较这层封装与框架的维护成本，而不是比较行数。

代价里最需要记住的是版本漂移。这一章出现了三处证据：`.role` 属性在 1.x 不存在，`ChatOpenAI` 从 `langchain.chat_models` 搬到了 `langchain_openai`，`with_structured_output` 的默认 `method` 是 `json_schema` 而不是 `function_calling`。三条都属于"代码没改，行为变了"。应对只有两种：锁版本（章首那四个数字），或者把框架调用收在一层很薄的适配里，让漂移只影响那一层。

顺带得到一条排查纪律：凡是"应该生效却没生效"的问题，第一步不是读源码，是**把请求体打出来**。本章的每个例子都留了请求体或消息对象，原因就在这里——温度没传、裁剪没开、结构化降级成了 `json_object`，三种问题在代码里都看不出来，在请求体里一眼可见。

边界：什么情况下不该用它。一次性的单文件脚本（第 1 章那种一次往返的手写脚本）、需要精确控制请求体来排查问题、以及对版本升级极敏感的长跑系统，直接用手写版更省事。框架的收益在"调用点多、要换厂商、要接流式"这三件事同时成立时才明显。三件事里只成立一件时，收益不够抵消上面那条代价——参数变多、隐式行为变多、版本会漂。

## 这一章建立的 7 件事

1. 四个包的职责、版本需求区间，以及两个真实报错的成因（`ModuleNotFoundError` 与 `ImportError` 要分开处理）
2. `init_chat_model` 五个参数各管什么，`model` 与 `model_provider` 的两种写法等价
3. `base_url` 接兼容端点、`configurable_fields` 加 `config_prefix` 改参数的两条路径，以及前缀写错的静默失效
4. 四种消息的 `type` 值与请求体 `role` 的对应，`content` 与 `content_blocks` 的分工
5. 三类元信息与第 1、3 章字段的对应，`usage_metadata` 可能为 `None`、私有字段会被丢掉
6. `trim_messages` 六个参数的默认值，`include_system` 必须配 `start_on`，`max_tokens` 的口径由 `token_counter` 决定
7. 三种流式接口的产物与事件树，三种结构化策略的请求形态，以及它们各自与第 1、4、5 章的对应

## 下一章

这一章的每个对象都是单独用的：一次调用、一条消息、一个裁剪函数。真实代码里它们要拼起来——校验在前、模型在中、解析在后，中间出错要能重试，还要能批量与并行。第 10 章讲这一步：可执行单元之间的输入输出约定、七个组合子、提示词模板与四种解析器，以及 `astream_events` 在组合之后才显出来的那棵树。

---

[← 第 8 章 · 循环的四种失控](./08-循环的四种失控.md)　｜　[卷 3 目录](./INDEX.md#vol3)　｜　[第 10 章 · LangChain 组合与解析器 →](./10-LangChain组合与解析器.md)
