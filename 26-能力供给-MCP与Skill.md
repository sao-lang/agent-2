# 第 26 章 · 能力供给：MCP 与 Skill

> **卷 5 · agent 进阶（第 22–26 章）**｜[全书目录](./docs/INDEX.md#vol5)｜[本卷导读](./outline/vol05-agent进阶.md)
>
> - **知识点**：B14 MCP 三角色与治理 —— Host、Client、Server 各管什么，默认拒绝拦在哪；B15 Skill 的完整构成 —— 一个目录五部分，不是一个 md；B16 三级加载 —— 元数据常驻、正文命中才读、资源执行时才读；B17 触发判定 —— description 怎么写，漏召与误召怎么分别量；B18 能力编排与冲突 —— 四类能力都能答时，谁优先要写成规则；B19 工具收窄 —— allowed-tools 把可见工具数降下来，误选率跟着降（编号定义见 [知识点-B-运行层](./outline/12-知识点-B-运行层.md)）
> - **本章回答**：进程外的能力怎么接进来；把一套流程写成 Skill 之后，凭什么只在需要时才花 token
> - **示例目录**：`code/knowledge/ch26_mcp/`（MCP server 与 client）、`code/knowledge/ch26_skills/`（skill 与三级加载）
> - **读完应当能回答**：能写出一个可用的 MCP server 与 client，能把一套流程写成 Skill 并说清它在哪一级加载

---

## 目录

[MCP](#mcp)\
[Skill](#skill)\
[这一章建立的 8 件事](#这一章建立的-8-件事)

## MCP

### 协议与三个角色

MCP 是"模型应用"和"能力提供方"之间的协议，四件事定死了它的形状。

第一，三个角色。Host 是那个跑着模型的应用，Client 是 Host 内部的一个连接件，Server 是能力提供方。一个 Host 可以挂多个 Client，每个 Client 连一个 Server；Server 不知道自己被谁用，也不知道别的 Server 存在。

第二，三类能力面。Server 对外提供工具，即可执行的动作、资源，即按 URI 读的数据、提示词，即可复用的模板。工具进清单、占上下文；资源不进清单、按名读取，这条差别是后面"按需加载"的地基。

第三，一条请求-响应通道。Host 与 Server 之间走 JSON-RPC 2.0：`initialize` 协商版本与能力，`tools/list` 取清单，`tools/call` 执行，`resources/read` 读数据。协议只规定消息形状，不规定 Server 里怎么实现。第四，传输与进程边界可换：同机常用 stdio，Host 拉起 Server 子进程、用标准输入输出通信；跨机常用 HTTP，Streamable HTTP 或 SSE 两种，换传输不改工具定义，只改连法。

一个 Host 挂多个 Server 时，工具名会撞。约定是给每个 Server 的工具加前缀，形如 `order__get_order`，前缀就是 Server 的名字。前缀不是协议要求，是 Host 侧的装配约定：它让"哪些工具来自哪个 Server"在清单里看得见，也让"某个 Server 降级了就只摘掉它那一组"成为可能。与之配套的是默认拒绝：没在清单里声明的工具一律不可见，Server 侧也不接受未声明的调用，两条合起来，工具清单就等于权限清单。

对工程来说，MCP 解决的是"能力不再写在应用里"。工具的实现、数据、权限都在 Server 侧，Host 只拿到一份清单和一条调用通道。代价是多了一条不可信的边界：Server 可能超时、可能返回畸形数据、可能被替换成别人写的。

### 一次会话里的报文

协议这一层值得看一眼原文，因为它决定了出错时能查什么。一次最小会话只有三段，下面是把 `transport_demo.py` 抓到的消息简化后的形状。

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize",
 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "probe", "version": "0.1"}}}
```

`initialize` 是唯一必须最先发的一条，客户端在这里报自己支持的协议版本与能力，服务端回一份它的名字、版本与能力集合。版本不一致时不要静默降级，宁可让连接失败，两版协议的字段语义可能变了，勉强连上去只会把错误推迟到调用时。

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
```

清单里的每一项都带 `name`、`description`、`inputSchema`，可选 `annotations` 与 `outputSchema`。这份 JSON 就是 Host 塞进模型请求的那段工具定义，字数与 token 直接对应，这也是按需加载能省钱的原理：清单可以取全，但发多少由 Host 决定。

```json
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "get_order", "arguments": {"order_id": "A1001"}}}
```

调用的参数是对象而不是字符串，这一点与第 6 章直连厂商接口不同：序列化由 SDK 做，客户端拿到的就是对象。返回里既有 `content`，即给模型读的文本块，也有 `structuredContent`（给程序读的结构），二者不一致时要以前者为准，模型看到的是它。

报文层的错误分两类，处理方式相反。协议错误是 JSON-RPC 的 `error` 字段，比如方法不存在、参数形状不对，这类说明**调用方写错了**，重试没有意义；工具错误是 `result.isError=true`，说明**业务上失败**，比如订单不存在、库存不足，这类可以把错误原文回灌给模型让它改。把两类混成一个异常，循环里就分不清该重试还是该停。

### 一个完整的 server

`code/knowledge/ch26_mcp/order_server.py` 是一个退货域的 Server：六个工具、一个资源模板、一个提示词，全部用 fastmcp 声明。

```python
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP(name="order-policy", instructions="退货域的能力面……")


@mcp.tool(annotations={"readOnlyHint": True, "title": "查询订单"})
def get_order(
    order_id: Annotated[str, Field(pattern=r"^[A-Z]\d{4}$", description="订单号，例如 A1001")],
) -> Order:
    """按订单号取状态、签收天数与商品类别。只查本账号订单。"""
    if order_id not in ORDERS:
        raise ToolError(f"订单不存在：{order_id}")
    return Order(**ORDERS[order_id])
```

六件事值得逐条看。

一是声明即契约。 函数名是工具名，docstring 是工具说明，参数注解与 `Field` 生成参数 schema。不需要另写一份 schema，也就不存在"这份 schema 和实现不一致"的问题。

二是返回类型也会进 schema。 返回一个 dataclass 时，客户端拿到的既有文本内容，也有 `structured_content`：前者给模型读，后者给程序读。

三是错误与结果分开。 参数错、订单不存在这类可预期的失败用 `ToolError` 抛出，客户端拿到的是 `is_error=True` 的结果，不是异常；传输断了才是异常。

四是标注是给 Host 看的。 `readOnlyHint`、`destructiveHint`、`title` 不改变工具行为，但 Host 可以据此决定要不要审批、怎么展示。写工具，即 `create_return`标 `readOnlyHint: False`，读工具标 `True`。

五是资源与提示词各有用途。 资源 `policy://refund/{category}` 返回条款原文，按 URI 读、不进工具清单；提示词 `review_flow` 把审查步骤固化下来，Host 可以直接取来当消息用。

还有两件容易忽略的：`instructions` 是给 Host 的整体说明，随 `initialize` 返回，Host 可以把它放进系统提示，用来交代"这一组工具是干什么的"；描述里的版本号是灰度时区分新旧两版 Server 的依据。两者都不改变单个工具的行为，但决定了模型把这一组工具当成什么来用。

六是传输在入口处选。 `mcp.run(transport="stdio")` 给同机子进程用，`mcp.run(transport="http", host=..., port=...)` 给远端用。同一份 Server 代码，两种发布方式。

### 一个 client 与按需加载

`code/knowledge/ch26_mcp/order_client.py` 连上这个 Server，走的顺序就是协议的顺序：

```python
async with Client(server) as client:
    tools = await client.list_tools()
    order = await client.call_tool("get_order", {"order_id": "A1001"})
    bad = await client.call_tool("get_order", {"order_id": "Z9999"}, raise_on_error=False)
```

```
=== 1. 工具清单 ===
  get_order      标题=查询订单  ~75 token
  get_policy     标题=查询退货政策  ~79 token
  review_refund  标题=None  ~92 token
  list_orders    标题=列出订单  ~77 token
  get_logistics  标题=查询物流  ~59 token
  create_return  标题=创建退货单  ~95 token
  6 个工具全量进上下文 ≈ 477 token
```

一次会话的时序是固定的：`initialize` 协商，协商版本、能力与 Server 信息→ `tools/list` 取清单 → 若干次 `tools/call`。三次往返各有超时，最容易被忽略的是 `initialize`，Server 起不来时它最先挂住，而调用方往往只给 `tools/call` 设了超时。工程做法是三次分别设上限，并把"连不上"与"调不通"分成两类错误：前者换 Server 或重试，后者要看 `is_error` 的具体内容。

按需加载发生在这一层。清单拿到手不等于全塞进请求：Host 按当前阶段挑子集，只把用得着的几个工具定义发给模型。

```
=== 2. 按需加载：只取本阶段要用的 ===
  本阶段只用 ['get_order', 'get_policy']，约 154 token
  省下的约 323 token：本阶段不发另外 4 个工具的 schema
```

这不是框架自带的开关，而是 Host 的装配动作：把 `tools` 数组裁到当前阶段。分成"先查后判"两个阶段时，第一阶段只发两个查询工具，第二阶段才把 `review_refund` 或 `create_return` 放进来。工具越多这一步越值钱，同时它也降低误选，候选少，选错的机会就少。

余下三件事，输出里各占一段：

```
=== 4. 工具报错是数据，不是异常 ===
  is_error = True | 订单不存在：Z9999（本 server 只有 A1001/A1002/B2001/C3001）
=== 5. 资源：不占工具清单，按名读 ===
  资源模板： ['policy://refund/{category}']
  读到的条款： # 生鲜商品退货条款（P-9） /  - 窗口：签收后 1 天内 / - 条件：签收 24 小时内且变质
=== 6. 提示词模板 ===
  提示词： ['review_flow']
  渲染首行： 审查订单 A1001 能否退货。
```

错误是数据，意味着循环里多一个分支"把错误原文转述给用户"，而不是 try/except 一整包。资源按名读，意味着条款原文只在需要时进上下文——它是按需加载在数据侧的对应物。提示词模板则把"步骤"从代码搬到了 Server 侧，改流程不用改 Host。

### 传输、收窄与冲突

同一份 Server 代码，四种连法，差别只在入口参数与客户端 URL：

| 传输 | 怎么起 | 客户端怎么连 | 适合 | 代价 |
|---|---|---|---|---|
| stdio | `order_server.py`（默认） | `Client("order_server.py")` | 同机、本地工具、单用户 | 进程生命周期与 Host 绑定 |
| streamable-http | `--transport http --port 8765` | `Client("http://127.0.0.1:8765/mcp")` | 跨机、多租户、共享能力 | 鉴权、并发、超时都要自己管 |
| sse | `--transport sse --port 8766` | `Client("http://127.0.0.1:8766/sse")` | 只支持 SSE 的老客户端 | 一条长连接，断线要重连 |
| 内存内 | 直接 import 对象 | `Client(server)` | 单元测试、示例 | 不跨进程，不验证网络 |

`code/knowledge/ch26_mcp/transport_demo.py` 把前两种真跑了一遍：用 `subprocess` 起 Server，等端口监听，再用 URL 连上去调用，跑完杀掉进程。

```
=== 1. streamable-http：独立进程 + URL ===
  服务已监听： True
  http             URL=http://127.0.0.1:8765/mcp
                   工具 6 个：get_order, get_policy, review_refund, list_orders, get_logistics, create_return
                   调用结果：不可退 / P-7
=== 2. sse：老式 Server-Sent Events 传输 ===
  服务已监听： True
  sse              URL=http://127.0.0.1:8766/sse
                   工具 6 个：get_order, get_policy, review_refund, list_orders, get_logistics, create_return
                   调用结果：不可退 / P-7
```

两处容易出错的地方。**一是本地 URL 要走 NO_PROXY。** 本机配了系统代理时，指向 `127.0.0.1` 的请求也会被代理接走，表现为 502 空响应；`transport_demo.py` 里在 import 之后设了 `NO_PROXY=127.0.0.1,localhost`，一行解决。**二是 stdio 不是"没有 URL 的简化版"**，它要求 Host 真的把 Server 当子进程拉起来，进程的生命周期、日志、退出码都由 Host 负责；URL 传输则相反，Server 自己活着，Host 只是客户端。这个差别决定了部署方式：stdio 跟着 Host 发版，URL 独立发版、独立扩容。

本机没有可用的 `pywin32` 轮子，Python 3.15 上 stdio 那条子进程路径跑不起来，所以示例跑的是 URL 两种；换成 `Client("code/knowledge/ch26_mcp/order_server.py")` 就是 stdio，工具定义与调用代码一行不用改。另外 MCP 规范里没有 websocket 传输，`streamable-http` 与 `sse` 就是两个带 URL 的选项。

HTTP 传输多出来的三件事都要在 Server 侧做。鉴权：谁来调、能调哪个 Server，用 API key 或 OAuth 在连接建立时判，别等 `tools/call` 再查；多租户：每个租户的工具清单与数据都要隔离，隔离的粒度是"连接"，不是"参数"——把租户 id 放进参数让模型填，等于让模型决定读谁的数据；限流与超时：远端 Server 的延迟不在自己手里，连接与调用要分别设上限，并把失败区分为"连不上"与"调不通"。

什么时候不值得接 MCP：三个本地函数、只给自己用、不需要独立发布，直接写成工具函数更省事。MCP 的价值出现在"能力由别人维护"或"同一个能力要给多个 Host 用"这两种场面，它换来的是解耦，付出的是多一条进程边界、一套协议往返和一份治理成本。判据是"这份能力的改动频率与归属"，不是"它是不是工具"。

工具收窄是同一件事在权限维度的延伸：清单能拿到六个工具，不等于每个阶段都该给六个。收窄的判据是当前阶段的目标——判退货只需要两个查询工具，`create_return` 要留到"用户确认退"之后，`list_orders` 只在不知道该查哪一单时给。收窄过头也有代价：删掉工具之后模型只能编答案，而编出来的答案看起来和查到的一样。

能力冲突出现在两处：同一件事多个工具都能做（`review_refund` 与"自己调两个查询再算"），以及 Skill 规定的流程与工具能力重叠。裁决顺序是固定的：Skill 里写明的流程优先，工具的细粒度能力其次，模型自由发挥最后。四类能力各回答什么、冲突时按什么顺序裁，`code/knowledge/ch26_skills/conflict_ruling.py` 有逐条对照。理由是可追踪——流程写死的那条路出问题时能定位到步骤，自由发挥的那条不能。

### 治理：鉴权、配额与版本

把 Server 挂到网络上，三件事必须在 Server 侧做完，不能指望 Host 自觉。

鉴权放在连接建立时，不放在每个工具里。stdio 的鉴权由进程边界天然给出：能拉起这个进程的只有 Host；URL 传输要自己判：静态 token 适合内部服务，OAuth 适合面向第三方，两者都要在 `initialize` 之前拒绝掉未授权连接。放到工具里判的做法看起来更灵活，实际上会让"哪些工具可用"变成调用方说了算，权限就散了。

配额按连接算，不按调用算。一个 Client 一条连接，连接上记请求数、并发数、单次耗时；超了先返回明确的"额度用尽"，不要静默排队，否则 Host 侧只会看到整体变慢，查不出是哪一段。版本同理：`initialize` 返回的版本号要能区分灰度批次，新版本先用小流量连接验证，出问题把流量切回旧版本，而不是回滚代码。

### 客户端要自己管的三件事

SDK 只负责发消息与收消息，下面三件事要调用方做。

超时分三层：连接超时、单次调用超时、整轮任务超时。三层都要有，缺一层就会出现"某个工具卡住，整个任务挂在那里"。重连交给传输层做，但重连之后要重新 `initialize`，会话状态不会自动恢复，把这一点写进重试函数，否则会出现"重连成功但工具全不见"。

并发要分组。同一批工具调用可以并发，但读与写不能并发：先读状态、再写结果，中间夹一个并发的写就会拿到旧状态。分组方式是给工具打标签，`read` 的并发、`write` 的串行，这条规则写进 Host 的调度器，不写进 Server。

### 和 Skill 的分工

两者都叫"能力供给"，边界只有一条：**MCP 给动作，Skill 给流程**。工具回答"能做什么"，Skill 回答"按什么顺序做、做到哪一步停、结果怎么自检"。同一件事两边都能承载时，先问流程是否固定：固定则写成 Skill，正文能把顺序写死，不固定则留给工具与模型自由组合。

反过来也有一处重叠要小心：Skill 的 `allowed-tools` 列的是工具名，而这些工具可能来自 MCP。两边都要维护同一份白名单，删了一边的工具，另一边会静默失效，所以白名单只在 Skill 里写一次，Host 装配时以它为准，MCP Server 侧只做"未声明即拒绝"。

日志是这一层唯一的排错入口。Server 侧每个请求记三样：方法名、耗时、结果码；Host 侧记连接 id 与工具名。两边用同一个请求 id 串起来，出问题时才能回答这一次调用到底是网络慢、服务端慢，还是工具自己慢。

## Skill

### 从提示词到目录

Skill 是把"一套做事的流程"从提示词里搬出来，变成一个目录。搬出来的动因有三层，一层比一层具体。

最早是把步骤写进系统提示词。问题很快出现：步骤一多提示词就长，长提示词等于每次请求都付一遍，改一处要动整段。

接着是把流程写进文档，让模型按需检索。问题变成另一种：检索按相似度找片段，它会找到"讲这件事的段落"，但不保证按顺序执行；而流程恰恰要求顺序。

Skill 的做法是给流程一个文件系统的形状：元数据常驻，正文命中才读，资料与脚本走到那一步才读。顺序由正文里的步骤保证，细节由目录里的文件按需供给，代价按"用了多少"付。判据只有一条：这件事是"按固定流程做"，还是"从大量文档里找依据"。前者是 Skill，后者是检索，见第 14 章起的四个环节。再具体一点——同一份资料会不会因为问题不同而读到不同部分？会，就是检索的活；每次都要整份读完才敢下结论，才放进 `references/`。一个只有三步、没有条款、没有数字的流程也不值得做成 Skill，直接写进系统提示词更省。

这样一套东西是可发布的：一个目录、一份 `SKILL.md`、若干资料与脚本，随版本走，能灰度、能回滚、能被别的 agent 复用。

### 目录的五个部分

```
refund-review/
├── SKILL.md              入口：元数据 + 步骤 + 判定规则 + 资料清单 + 边界
├── references/           长条款与例外，按需读
├── scripts/              确定性动作，走到那一步才执行
├── templates/            输出格式
└── tests/                脚本的离线单测
```

五个部分各管一件事，缺哪一项坏在哪：

| 部分 | 内容 | 缺了会怎样 |
|---|---|---|
| `SKILL.md` | frontmatter（`name`/`description`/`allowed-tools`）+ 正文 | 选不中，或选不中之后的步骤无从谈起 |
| `references/` | 完整条款、例外、速查表 | 模型只能凭记忆答条款，答错也不自知 |
| `scripts/` | 判定、校验、换算 | 该用算术的地方让模型心算，结论随机 |
| `templates/` | 回复骨架 | 每次输出结构都不一样，下游没法解析 |
| `tests/` | 上面脚本的单测 | 脚本改坏了流程照样跑，只是判错 |

frontmatter 里 `description` 是唯一参与"选不选它"的字段，所以它要写三段：这件事是什么、什么情况下用、需要什么输入。`allowed-tools` 是权限声明，Host 据此收窄工具清单。

### 渐进式披露与触发判定

三级加载，`code/knowledge/ch26_skills/progressive_load.py` 把每一级的代价算了出来：

```
=== L1：常驻的元数据 ===
  name=refund-review  description 97 字 ≈ 123 token（含全部前置项）
  命中触发词 ['能退', '签收'] -> 进入 L2；没命中就不读正文，L1 的代价到此为止
=== L2：命中后读正文 ===
  SKILL.md 正文 1768 字 ≈ 1060 token
  正文里：编号步骤 9 条（前置 3 + 执行 6）、资料名 5 处、脚本名 3 个（只读了名字，没读内容）
=== L3：走到第 4 步，只读一份资料 ===
  references/exception.md 335 字 ≈ 266 token
```

资料按"什么时候读"切份，不按主题切。政策条款、例外、速查表三份的分法是：判定前必看的是正文里的规则，条款原文只在用户质疑时才读，例外只在类别命中时才读，速查表只在跨类别比较时才读。如果按主题切（"客户服务""物流""售后"），就会出现一次读三份、其中两份用不上的情况。

三级的分界就是"什么时候需要它"：L1 回答"这次请求像不像这套流程管的事"，L2 回答"具体怎么做"，L3 回答"这一步的细节与证据"。只有 L1 是每个请求都付的，所以它要压到最短，同时把触发词写全。

触发判定是 L1 那一步的判据，它有两个方向的错，必须分开报：漏召（该用没用，模型自由发挥）与误召（不该用用了，白付一次 L2 还可能给出不适用的结论）。两个方向的修法相反——补触发词降漏召、可能升误召，所以不能只看一个准确率。做法是留出集：一组该触发的请求、一组不该触发的请求，逐条看矩阵。这份矩阵在 `code/knowledge/ch26_skills/trigger_matrix.py` 里，20 条请求、四个版本的 description 逐条对照。

```
=== 对比：全量读 vs 三级按需 ===
  全量读入（正文 + 3 份资料 + 脚本 + 测试）≈ 4636 token
  三级按需（L1 + L2 + 一份资料）≈ 1449 token
  这一次省下 ≈ 3187 token，且资料越多、省得越多
```

差值不是免费得来的：省下的 token 换成了判错的风险（触发没判对）与读的次数，每一步都可能多读一份文件。所以三级加载只在"资料明显多于一次要用的量"时才划算；一个只有五行正文的 skill，拆成三级反而更贵。

Skill 也是要改的，所以它需要一个版本位。`version` 写在 frontmatter 里，改正文改版本号，Host 侧记下"这次用的是哪一版"，出问题时才分得清是流程错了还是执行错了。灰度办法很直接：两版目录同时存在，`description` 里的触发词分开，或者按租户分流；回滚就是切回旧版本目录，不涉及代码发布。

### 发布、测试与回滚

Skill 是配置，不是代码，所以它的发布流程要单独定。三件事：目录随版本一起打标签，标签里带 `version`，Host 记录"这次用了哪一版"；改 `description` 与改正文分开评审，前者影响触发率、后者影响执行正确率，混在一次改动里出问题分不清是哪一类；每次改动先在留出集上跑一遍触发矩阵，再在样例订单上跑一遍 `decide.py`，两组数都过才发。

回滚比发布更重要。Skill 出问题时不要改正文救火，直接切回上一版目录。正文现改会让问题版本与修复版本混在一起，事后无法判断是流程错还是修错了。测试断言的写法与第 5 章的结构用例一致：断言拒在哪个理由码，而不是结果对不对，因为同一个结论可能由不同路径得到。

### 一个可用的例子

`code/knowledge/ch26_skills/skills/refund-review/` 是完整的一套，可直接抄走改。`SKILL.md` 的骨架：

```text
---
name: refund-review
description: 处理电商退货审查……当用户询问订单能否退货、需要核对签收天数与政策窗口时使用。需要订单号；缺订单号时先索取，不要推断。
allowed-tools: [order__get_order, order__get_policy, order__get_logistics]
version: 1.3
---

正文按固定八段写：
  适用范围   适用退货判定；不适用换货、维修、发票、物流投诉、价保
  前置条件   有订单号；能拿到 signed_days_ago 与 category；能拿到 window_days
  步骤       取订单 → 判能否进入 → 取窗口 → 分流特例 → 跑脚本自检 → 套模板回复
  判定规则   相等算可退；质量问题 15 天；生鲜 24 小时；定制不支持无理由
  资料       三份，各自什么时候读
  脚本与测试 decide.py 判定，check.py 校验，tests/ 单测
  输出格式   结论 / 依据 / 下一步
  失败处理   工具报错、数字缺失、脚本不一致、投诉转人工
```

判定不靠模型心算，交给脚本。`scripts/decide.py` 把窗口、条款、理由码都算出来，退出码区分"判定成立"与"输入不全"：

```
$ python scripts/decide.py '{"order_id":"A1002","signed_days_ago":9,"category":"普通"}'
{"category": "普通", "clause": "P-7", "conclusion": "不可退", "detail": "第 9 天 / 窗口 7 天（P-7）",
 "order_id": "A1002", "reason_code": "EXPIRED", "signed_days_ago": 9, "window_days": 7}
```

分工的边界值得说清楚：脚本负责"能不能退"这个判定，模型负责"怎么把判定讲成一封能发出去的回复"。前者需要可比对、可回归，后者需要措辞得体、知道该问什么。把两者混在一起是最常见的写法，也是最贵的一种：让模型算天数，它偶尔会算对，而"偶尔对"比"稳定错"更难发现；反过来让脚本组织语言，回复会僵硬到用户看不懂。所以这套例子里 `decide.py` 只输出结论与理由码，模板只负责句式，中间那句"下一步"由模型按失败处理那一节填。

理由码不是给人看的装饰，它是统计与灰区的接口。一批请求跑下来，`EXPIRED` 占多数说明窗口条款是主要争议点，`OPENED_USED` 多说明"已拆封"需要更明确的证据要求，`MISSING_ORDER_ID` 多说明入口处该先索取订单号。同一套码还能接人工：命中某几个码的直接转人工，其余自动回复，规则写在调度那一层，不写进 skill 正文。

单测覆盖边界日、生鲜、定制、质量问题与缺字段，改脚本后先跑它：

```
OK   普通第 7 天        结论=可退  理由=WITHIN             退出码=0
OK   普通第 8 天        结论=不可退 理由=EXPIRED            退出码=0
OK   生鲜 2 天         结论=不可退 理由=FRESH_EXPIRED       退出码=0
OK   定制无理由          结论=不可退 理由=CUSTOM_NO_REASON   退出码=0
OK   质量问题第 12 天     结论=可退  理由=QUALITY_WITHIN     退出码=0
OK   缺订单号           结论=待定  理由=MISSING_ORDER_ID   退出码=1

10/10 通过
```

这套东西"可用"的标准只有三条：触发判得准（`description` 三段式、有留出集）、判定不靠猜（数字与规则交给脚本，模型只组织语言）、失败有出口（缺信息、工具报错、脚本不一致各有明确处置）。再加一条：流程的范围要收窄，超范围的请求直接说不属于本流程——那一句比任何"尽量准确"都值钱。

## 这一章建立的 8 件事

1. MCP 三个角色（Host / Client / Server）与三类能力面，三类能力面，请求走 JSON-RPC，传输可换。
2. Server 侧声明即契约：函数名、docstring、参数注解同时是工具名、说明与 schema；返回类型决定 `structured_content`。
3. 工具错误用 `ToolError` 抛出，客户端拿到 `is_error=True` 的结果而不是异常；传输层失败才是异常。
4. 标注（`readOnlyHint`、`destructiveHint`）不影响行为，Host 据此决定审批与展示。
5. 按需加载发生在 Host 装配工具清单时：六个工具 477 token，本阶段只用两个是 154 token。
6. Skill 是"流程的文件系统形状"：元数据常驻、正文命中才读、资料与脚本走到那一步才读。
7. 三级加载的分界是"什么时候需要"：L1 123 token 常驻，L2 1060 命中后读，L3 按步读一份 266 token。
8. 触发判定要分开报漏召与误召；判定与校验交给脚本，模型负责组织语言与说明缺什么。

## 下一章

能力供给解决"工具与流程从哪来"。第 27 章处理它的前提：给了模型执行权，就必须给边界——路径、网络、资源与时间四条线，以及为什么这四条要装在同一个入口上。

---

[← 第 25 章 · 持久化与幂等](./25-持久化与幂等.md)　｜　[卷 5 目录](./docs/INDEX.md#vol5)　｜　[第 27 章 · 沙箱：给执行权就必须给边界 →](./27-沙箱-给执行权就必须给边界.md)
