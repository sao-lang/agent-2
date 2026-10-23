# 第 51 章 LlamaIndex：另一套检索路线

> **这一章你会遇到什么坏事**
> 前四章你用 LangChain 把 Agent 搭得很顺。现在老板拿来 **1200 份 PDF + 300 个网页**，说"做成知识库"。
> 你开始写：PDF 解析、分段、清洗页眉页脚、算向量、存库、做增量更新……
> 写到第 3 天你发现：**这些"脏活"占了你 80% 的时间，而 Agent 逻辑只占 20%。**
>
> 更糟的是——**LangChain 对这些脏活只给了"零件"，没给"流水线"。**

> **学完你能做到**
> 1. 用 `IngestionPipeline` 把"文档 → 节点 → 向量"串成一条可复用的流水（50.3）
> 2. 说清 `Index` / `Retriever` / `QueryEngine` 三层各自负责什么（50.4）
> 3. 用 `PostProcessor` 在检索后过滤/压缩，并知道"先放宽再精筛"（50.5）
> 4. 用 `RouterQueryEngine` / `SubQuestionQueryEngine` 处理"多知识库"和"多跳"（50.6）
> 5. 说清它和 LangChain 的边界：**什么时候用它、什么时候别用**（50.7）

---

## 51.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **Document** | 一份原始文档 + 元数据（就像 LangChain 的 `Document`） | 50.3 |
| **Node** | 切出来的一个块，**带 id / metadata / 关系 / embedding** | 50.3 |
| **IngestionPipeline** | "文档 → 节点"的流水线，可插切分、去重、向量化 | 50.3 |
| **Index** | 索引：存原文 + 存结构 + 存向量 | 50.4 |
| **Retriever** | 只负责"给个查询，返回节点" | 50.4 |
| **QueryEngine** | 检索 + 合成（自己拼 prompt、自己调模型） | 50.4 |
| **PostProcessor** | 检索之后的过滤器/压缩器/重排器 | 50.5 |
| **RouterQueryEngine** | 按问题选"用哪个知识库"的引擎 | 50.6 |

> 还有两个后面才出现：
> - **SubQuestionQueryEngine**：把多跳问题拆成子问题分别查（50.6）
> - **StorageContext**：把 docstore / vector_store / index_store 三个存储组合起来（50.6）

---

## 51.1 先看一个具体的坏事：同样的 15 个块，两种切法差在哪

真实场景：一份 889 字的售后政策手册，你要把它变成可检索的索引。

先跑一次看切分：

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\li\ch50\step1_ingestion.py
```

真实输出（段 ①）：

```
  对照段落：182 字（一个长段落，没有分段）
  默认分隔符（英文 , . ;）
     35 字  '用户反馈右耳出现电流声，先检查蓝牙编解码是否匹配'…'匹配请重置连接。'
     33 字  '若匹配则检查耳塞网罩是否堵塞。网罩堵塞可用软毛刷'…'理，不要用针戳。'
     48 字  '清理后仍有电流声，判定为硬件故障，走保修流程。用'…'编解码是否匹配。'
     ...
  指定中文标点（，。；！？）
     35 字  '用户反馈右耳出现电流声，先检查蓝牙编解码是否匹配'…'匹配请重置连接。'
     42 字  '若匹配则检查耳塞网罩是否堵塞。网罩堵塞可用软毛刷'…'理后仍有电流声，'
     ...
```

**看第 3 块的结尾**：默认配置是 `…走保修流程。用`——那个"用"是**下一句的开头**，被硬切了进来。
指定中文标点后，块尾落在 `。` 或 `，` 上。

**你想知道的四件事：**

| 你想知道 | 能答吗 | 为什么 |
|---|---|---|
| 切分切坏了没有？ | ✅ | 打出块尾就知道 |
| 块数变了没有？ | ✅ | 但**块数一样不代表切法一样** |
| 这对召回有多大影响？ | ❌ | 得跑评测（第 40 章） |
| 该怎么修？ | ✅ | 指定 `secondary_chunking_regex`（本章） |

**结论：你不是"不会用切分器"，你是"没验证切分结果"。**

---

## 51.2 为什么"用 LangChain 也能做"却还是想换

你可能会想：第 45 章我已经会用 `InMemoryVectorStore` + `RecursiveCharacterTextSplitter` 了，为什么还要学一套？

因为真实项目里，"喂文档"这件事会长成这样：

| 步骤 | LangChain 给你的 | 你要自己写的 |
|---|---|---|
| 读 1200 个 PDF | `PyPDFLoader`（要自己拼） | 异常处理、跳过坏文件 |
| 去页眉页脚 | ❌ | 正则 + 规则 |
| 切分 | `RecursiveCharacterTextSplitter` | 中文标点、表格保护 |
| 去重 | ❌ | 自己算 hash |
| 算向量 + 入库 | `VectorStore.add_documents` | 分批、失败重试 |
| 增量更新 | ❌ | 自己比对"哪些文件变了" |
| **串成流水线** | ❌ | **自己写编排** |

**LlamaIndex 的四件"脏活工具"**：

| 工具 | 解决上表哪一行 |
|---|---|
| `SimpleDirectoryReader` | 第 1 行（一行读整个目录） |
| `IngestionPipeline` | 第 6–7 行（流水线 + 去重 + 增量） |
| `Node` 体系 | 第 3 行（带 id/关系，方便"取相邻块"） |
| `PostProcessor` 链 | 检索后过滤/压缩（第 10 章那些技巧的现成实现） |

**所以不是"LlamaIndex 更好"，是"它把脏活做成了默认值"。**

> 💥 **失败实验 1：证明"块数一样 ≠ 切法一样"**
> 打开 `step1_ingestion.py`，把默认切法和指定中文标点切法的**节点数**都打印出来。
> 本章语料上，两者都是 **7 块**。
> 但把"块尾最后 8 个字"打出来，你会发现边界不同。
>
> **结论：用"块数"验证切分是完全无效的。** 必须看**边界**（或跑召回评测）。

---

## 51.3 IngestionPipeline 到底是什么（10 行代码看懂）

### 一句话

> **一个流水线：输入 Document，依次过"切分 → 去重 → 向量化"，输出 Node 列表。**

### 最小例子

💻 `python code/framework/li/ch51/step1_ingestion.py`

```python
from llama_index.core import Document
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.embeddings import MockEmbedding

pipe = IngestionPipeline(
    transformations=[
        SentenceSplitter(chunk_size=200, chunk_overlap=20,
                         secondary_chunking_regex="[^，。；！？]+[，。；！？]?"),
        MockEmbedding(embed_dim=8),          # 真实项目换 OpenAIEmbedding
    ],
)
nodes = pipe.run(documents=[doc])
```

**就这些。** 真实输出（段 ③）：

```
  pipeline 产出 6 个节点，每个带 embedding：
    node[0].embedding 维度 = 8
    node[0].metadata      = {'source': '售后政策手册.md', 'version': 'v3'}

  去重：同一份文档再喂一次 → 6 个节点（不会翻倍）
```

### Node 比"字符串块"多了三个字段

真实输出（段 ②）：

```
  node_id      = 3f943d5b-047b-46…
  metadata     = {'source': '售后政策手册.md', 'version': 'v3'}
  relationships = ['70ba8346…', '838f1285…', '850ed273…']
```

| 字段 | 有什么用 |
|---|---|
| `node_id` | 引用、去重、更新都靠它（第 40 章讲"用 chunk id 做评测"） |
| `metadata` | 来源、版本、章节；会被**自动拼进给模型的文本**（除非 `exclude_keys`） |
| `relationships` | 前一块 / 后一块 / 父块 → "句子窗口检索""父子块"的底层支撑 |

**`relationships` 是 LlamaIndex 最容易被忽视、也最实用的字段。** 第 9 章讲"父子块"时你要自己记 parent_id；这里框架替你记好了。

### ✏️ 停下来想一想

给模型看的内容（`metadata_mode=MetadataMode.LLM`）会**自动带上 metadata**：

```
  source: 售后政策手册.md
  version: v3
  
  ### 1.2 质量问题退换
  ...
```

**这会占 token。** 那什么情况下你**不想**把 metadata 给模型看？

（提示：当 metadata 是"内部 id""调试标记""租户 ID"这类**模型不需要、也不能泄露**的东西时。用 `exclude_keys` 排除。）

---

## 51.4 从"节点"到"能问"（阶梯代码 step1 / step2 / step3）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_ingestion.py` | Document → Node 的流水线 | — |
| step2 | `step2_index_query.py` | Index / Retriever / QueryEngine / PostProcessor | 有了节点，但没法"问" |
| step3 | `step3_advanced.py` | Router / SubQuestion / 持久化 / 与 LangChain 取舍 | 单索引不够用了 |

### step2：三层分工

真实输出（段 ①②③）：

```
① VectorStoreIndex：从节点建索引
  索引类型 = VectorStoreIndex
  docstore 里的节点数 = 8
  → 索引内部持有：docstore（原文）+ index_store（结构）+ vector_store（向量）

② as_retriever：只拿检索这一层
  retrieve('退款多久到账？') → 3 条：
    0.394  运费由买家承担，且需支付检测费 20 元…
    0.363  判定为硬件故障，走换新流程…

③ as_query_engine：检索 + 合成（它会自己拼 prompt）
  query_engine 返回类型 = Response
  引用节点数 = 3
```

**三层，各管一件事**：

| 层 | 你给我什么 | 我给你什么 | 什么时候只用这一层 |
|---|---|---|---|
| **Index** | Document / Node | 一个可检索的索引对象 | 建库、更新、删文档 |
| **Retriever** | 一个查询 | `list[NodeWithScore]` | **做检索评测**（第 40 章） |
| **QueryEngine** | 一个问题 | 一个 `Response`（答案 + `source_nodes`） | 直接对外提供问答 |

**关键：评测一定要测 Retriever，不要测 QueryEngine。**
因为 QueryEngine 把"检索"和"生成"混在一起，答错了你分不清是哪段的锅。

### step3：多知识库与多跳

真实输出（段 ①②）：

```
① RouterQueryEngine：按问题选知识库
  路由引擎 = RouterQueryEngine，候选工具 = ['policy', 'product']
  → 它做的事和 create_agent(tools=[...]) 很像，区别是：
    Router 只选一次，不做多轮循环；Agent 可以连续调多个工具。

② SubQuestionQueryEngine：把多跳问题拆开
  多跳引擎 = SubQuestionQueryEngine
```

**两者的差别**：

| | Router | SubQuestion |
|---|---|---|
| 拆不拆问题 | 不拆 | 拆成子问题 |
| 调几次 | 1 次检索 + 1 次合成 | 1 + N 次检索 + N + 1 次合成 |
| 适合 | "这个问题归哪个库" | "这个问题要跨两个库" |

### ✏️ 停下来想一想

`SubQuestionQueryEngine` 要拆问题，所以它**多花了 N 次模型调用**。

那如果问题其实很简单（只涉及一个库），你会付出什么代价？

（提示：拆问题本身就要一次调用；拆错了还要走错库。所以"总是用 SubQuestion"是浪费——和 `Router` 一样，要按问题形态选。）

---

## 51.5 核心实现（逐行解释）

这一节把 `PostProcessor` 的顺序问题讲透——**这是最容易"配了但没用"的地方**。

```python
raw = index.as_retriever(similarity_top_k=6).retrieve(q)   # ① 先放宽
pp = SimilarityPostprocessor(similarity_cutoff=0.33)       # ② 再收窄
filtered = pp.postprocess_nodes(raw, query_str=q)
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | 先取 6 条（比最终需要的多） | 直接取 2 条再过滤：过滤完可能剩 0 条 |
| ② | 按相似度阈值剔除 | 不剔除：低分噪声进 prompt（第 24 章的"上下文污染"） |

真实输出（段 ④）：

```
  不给 threshold 时，top_k=6 的结果：
    0.394  运费由买家承担，且需支付检测费 20 元…
    0.363  判定为硬件故障，走换新流程…
    0.329  可先尝试重置耳机…
    0.302  新机在 48 小时内发出…
    0.295  ### 1.2 质量问题退换…
    0.266  可在 App 内点击「转人工」…

  加 SimilarityPostprocessor(cutoff=0.33) 后：2 条
```

**六个候选，过滤后剩两个。** 这就是"先放宽再精筛"的标准形态。

### 顺序反了会怎样

真实输出（段 ⑤）：

```
  顺序 A：先取 top_6 → 再按 0.33 过滤 → 2 条
  顺序 B：先取 top_2 → 再按 0.33 过滤 → 2 条
  → A 从 6 条里筛出 2 条（可保留 ≤6 条），B 最多只能有 2 条。
    先收窄再过滤 = 把"可能被过滤掉、但其实是好块"的候选提前扔了。
```

**注意：本例两者都是 2 条，看不出差别。** 但换成"阈值 0.2"就不同了——A 会留下 4 条，B 最多 2 条。

**三个设计取舍**

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| `top_k` 取多少 | **最终需要的 2–3 倍** | 取太少：过滤后不够用；取太多：浪费检索时间 |
| 阈值设多少 | **用评测集扫出来**（第 40 章） | 抄一个 0.5：可能全被过滤光（我们实测 0.5 时剩 0 条） |
| 过滤 vs 重排 | **先过滤（便宜）再重排（贵）** | 直接上重排：把明知道不相关的也送去重排，白花钱 |

### ⚠️ 一个必须知道的坑：`MockEmbedding` 会让所有块同分

我们第一版用了官方 `MockEmbedding(embed_dim=16)`，结果检索出来的分数**全是 1.000**：

```
    1.000  可在 App 内点击「转人工」…
    1.000  判定为硬件故障，走换新流程…
    1.000  运费由买家承担…
```

因为 `MockEmbedding` 对**任何**输入都返回 `[0.5] * dim` 这样一个**常量向量**——余弦相似度恒为 1。

**这不是 bug，是设计**（它本来就是给"测试链路"用的，不是给"测试检索质量"用的）。

修法：写一个"确定性但真的随内容变化"的向量（`step2` 里的 `CharHashEmbedding`）。
**这件事本身就是一课**：**用假嵌入评估检索质量，等于用温度计测长度。**

> 💥 **失败实验 2：把阈值设成 0.5**
> 打开 `step2_index_query.py`，把 `SimilarityPostprocessor(similarity_cutoff=0.33)` 改成 `0.5`。
> 重跑 ④，观察输出：**过滤后 0 条**。
>
> 那一瞬间你的 RAG 会"什么都不知道"——因为所有块都被过滤掉了。
> **结论：阈值必须用你自己的语料 + 评测集扫出来，不能抄。**（这就是第 40 章"跑基线"的意义。）

---

## 51.6 用起来：三个问题 2 分钟答完

💻 三个脚本依次跑：

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\li\ch50\step1_ingestion.py
.venv\Scripts\python.exe code\framework\li\ch50\step2_index_query.py
.venv\Scripts\python.exe code\framework\li\ch50\step3_advanced.py
```

### 问题 ①：索引怎么落盘、重启怎么加载？

真实输出（`step3` 段 ③）：

```
  落盘目录 idx/ 里有：['default__vector_store.json', 'docstore.json', 'graph_store.json', 'image__vector_store.json', 'index_store.json']
  重载后检索 → 1 条：'退货需在签收后 30 天内申请。\n退款将在 7 个工作日内原路退'
```

**三个核心文件**：`docstore.json`（原文）/ `index_store.json`（结构）/ `default__vector_store.json`（向量）。
另外两个（graph / image）是空壳。

### 问题 ②：多知识库怎么路由？

```python
tools = [
    QueryEngineTool(query_engine=policy_idx.as_query_engine(),
                    metadata=ToolMetadata(name="policy", description="售后政策…")),
    QueryEngineTool(query_engine=product_idx.as_query_engine(),
                    metadata=ToolMetadata(name="product", description="产品参数…")),
]
router = RouterQueryEngine(selector=LLMSingleSelector.from_defaults(), query_engine_tools=tools)
```

**`description` 就是路由的"门牌"**——和第 14 章 Skill 的 description、第 12 章工具的 description 是同一件事。

### 问题 ③：它和 LangChain 到底怎么选？

真实输出（`step3` 段 ⑤）：

| 强项 | LangChain / LangGraph | LlamaIndex |
|---|---|---|
| 编排（LCEL / 图 / 状态 / HITL / 流式） | ✅ 强 | 一般 |
| 工具 / Agent 生态 | ✅ 强 | 一般 |
| 文档接入（PDF / docx / 网页 / DB） | 有 Loader，但要自己拼 | ✅ 强（`SimpleDirectoryReader`） |
| Node 体系（id / 关系） | 无 | ✅ 强 |
| 检索后处理 | 有（`DocumentCompressor`） | ✅ 更成体系 |
| 索引持久化 | 自己配 | ✅ 默认就完整 |

**取舍建议（可直接抄）：**

```
· 项目主体是"多源文档 → 可查询知识库" → 以 LlamaIndex 为主
· 项目主体是"Agent 做多步任务"        → 以 LangGraph 为主
· 两者可以混：LlamaIndex 管索引，把 QueryEngine 包成 LangChain Tool 交给 Agent
```

真实输出（段 ⑥）给了混用的具体形状：

```python
tool = StructuredTool.from_function(
    func=lambda q: str(index.as_query_engine().query(q)),
    name="kb_search",
    description="在企业知识库里检索并回答。涉及政策、参数时用。",
)
agent = create_agent(model, tools=[tool])   # ← 第 46 章的 Agent
```

### 🎯 到这里，你已经掌握了 LlamaIndex 的主干

| 能力 | 在哪一节 |
|---|---|
| Document → Node 流水线 | 50.3 |
| Index / Retriever / QueryEngine 三层 | 50.4 |
| PostProcessor 与顺序 | 50.5 |
| Router / SubQuestion | 50.6 |
| 持久化 | 50.6 |
| 与 LangChain 取舍 | 50.6 |

**剩下的都是"接入更多数据源"：PDF / 表格 / 网页 / 数据库。**

---

## 51.7 什么时候该用它，什么时候别用

### 三个"别用"的场景

| 场景 | 为什么别用 |
|---|---|
| **只有 20 篇文档、单次问答** | 用第 8 章手写的 60 行就够，引入框架只增加理解成本 |
| **主要是 Agent 多步任务、检索只占一小块** | 用 LangChain 的 Retriever 更顺，别为了"检索"引进一整套 |
| **团队已经重度使用 LangChain** | 混用两套抽象（Document vs Node）会让人写错 |

### 三个"该用"的场景

| 场景 | 为什么 |
|---|---|
| **数据源多、格式杂（PDF/docx/网页/DB）** | `SimpleDirectoryReader` + 一堆 Reader 是现成的 |
| **需要"取相邻块 / 父子块"** | `Node.relationships` 是原生的 |
| **需要 Router / SubQuestion / Recursive 这类引擎** | 现成的，不用自己拼 |

### 一句话

> **LangChain 是"胶水"，LlamaIndex 是"知识库工厂"。**
> 要做 Agent 就把工厂的产物包成工具；要做知识库就用工厂，别自己捏。

---

### 51.7.1 补充：LlamaIndex Workflow —— 它和 LangGraph 是直接竞品

上面讲的全是"检索路线"。但 LlamaIndex 1.x 还有一块**和 LangGraph 直接竞争**的东西：**Workflow**。

💻 运行：`python code/framework/li/ch51/step6_workflow.py`

#### 最小例子

```python
from llama_index.core.workflow import (
    Context, Event, StartEvent, StopEvent, Workflow, step,
)

class Ping(Event):
    n: int

class W(Workflow):
    @step
    async def start(self, ctx: Context, ev: StartEvent) -> Ping:
        return Ping(n=ev.get("n", 1))

    @step
    async def work(self, ctx: Context, ev: Ping) -> StopEvent:
        return StopEvent(result=ev.n * 7)

print(asyncio.run(W(timeout=10).run(n=6)))   # 42
```

**三句话理解它：**

| 概念 | 含义 |
|---|---|
| `StartEvent` | 入口（就是 `run()` 的参数） |
| `StopEvent` | 出口（`result` 就是 `run()` 的返回值） |
| 自定义 `Event` | step 之间的传递物 |

#### 分支：靠「返回什么事件」来分流

```python
class NeedKB(Event):
    q: str

class NeedCalc(Event):
    q: str

class W(Workflow):
    @step
    async def route(self, ctx: Context, ev: StartEvent) -> NeedKB | NeedCalc:
        q = ev.get("q", "")
        await ctx.store.set("q", q)
        if any(c.isdigit() for c in q):
            return NeedCalc(q=q)      # -> calc 会收到
        return NeedKB(q=q)            # -> kb 会收到

    @step
    async def kb(self, ctx: Context, ev: NeedKB) -> BranchResult: ...
    @step
    async def calc(self, ctx: Context, ev: NeedCalc) -> BranchResult: ...
```

真实输出：

```
  无数字: {'answer': 'KB回答[退款要多久]', 'q': '退款要多久'}
  有数字: {'answer': '计算[退款 399 元多久到]', 'q': '退款 399 元多久到'}
```

#### 和 LangGraph 的关键差异

| 维度 | LlamaIndex Workflow | LangGraph |
|---|---|---|
| 怎么分流 | 返回**不同类型的事件** | 返回 `Command(goto=...)` 或条件边 |
| 下游怎么知道接谁 | 按**事件类型自动匹配** | 按**节点名显式指定** |
| 状态存在哪 | `ctx.store`（键值）+ 事件字段 | State（TypedDict，有 reducer） |
| 并行扇出 | `ctx.send_event` + `collect_events` | `Send`（第 49 章） |
| 可视化 | 没有内置图 | `get_graph().draw_mermaid()` |

> **一句话**：Workflow 是「事件路由」，LangGraph 是「显式图」。
> 前者更类型化、更松耦合；后者更可控、能画出来、有成熟的 checkpointer。

#### 三个真实坑（我们都撞过）

> 💥 **坑 1：`ctx.store` 是异步的**
>
> ```python
> # 错：不 await
> ctx.store.set("q", q)     # RuntimeWarning: never awaited
> ctx.store.get("q")        # 返回 <coroutine object>
>
> # 对：await
> await ctx.store.set("q", q)
> await ctx.store.get("q")
> ```
>
> **这个坑特别隐蔽：不报错，只是拿到一个 coroutine 对象。**
> 你会看到输出里 `q` 变成 `<coroutine object StateStoreFacade.get at 0x...>`。

> 💥 **坑 2：事件类不能用 `@dataclass`**
>
> ```python
> # 错：会导致无限递归
> @dataclass
> class One(Event):
>     item: str
> # -> RecursionError: maximum recursion depth exceeded
>
> # 对：直接继承
> class One(Event):
>     item: str
> ```
>
> 原因：`Event` 本身是 Pydantic 模型，再叠 `@dataclass` 会让属性访问无限递归。
>
> 另外：**字段名不能叫 `items`**（会 shadow 父类同名属性），会给出 `UserWarning`。

> 💥 **坑 3：step 忘了 `return` 会静默停住**
>
> | 返回什么 | 行为 |
> |---|---|
> | `StopEvent(result=...)` | 流程结束 |
> | 某个 `Event` 实例 | 该事件类型的 step 收到 |
> | `None` | 本步结束但流程继续（用于只发副作用） |
> | `list[Event]` | 并发触发多个下游 |
>
> 忘了 return → **既不报错也不返回结果，直到 timeout**。排查时极难定位。

#### 什么时候选 Workflow，什么时候选 LangGraph

| 情况 | 选 | 理由 |
|---|---|---|
| 系统已用 LlamaIndex 做检索 | **Workflow** | 同一个库，不用装两套 |
| 需要「中断 + 人工审批 + 恢复」 | **LangGraph** | checkpointer + `interrupt` 成熟 |
| 需要把流程图导出来 | **LangGraph** | 内置 mermaid |
| 流程是「事件驱动、类型安全」的 | **Workflow** | 按事件类型路由，比节点名更类型化 |
| 需要跨 session 长期记忆 | 两者都有 | 看生态 |

> **一个实务建议：不要为了"统一技术栈"把两个框架硬拼在一起。**
> 混用两套状态管理是最容易出事的地方（第 23 章讲过 State 的坑）。

---

## 51.8 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数

在 `step2` 里把 `similarity_top_k=6` 改成 `2`，重跑 ④。
**验收标准**：说出"为什么过滤后条数变少了，而阈值完全没变"。

### 练习 2（20 分钟）：把你的文档接进来

用 `SimpleDirectoryReader` 读你自己项目里的 `docs/` 目录。

**最低要求清单**：
- [ ] 用 `IngestionPipeline` 切分 + 向量化
- [ ] 每个节点带 `source` 元数据
- [ ] 打印节点数、平均长度、最大长度
- [ ] 用 `persist` 落盘并重新加载，能检索到结果

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：把 `similarity_cutoff` 设成 0.9。**
重跑 `step2` ④。观察过滤后 0 条。结论：**阈值抄来的，系统就会"什么都不知道"。**

**实验 B：用 `MockEmbedding` 替代 `CharHashEmbedding`。**
重跑 `step2` ②。观察所有分数都是 `1.000`。结论：**假嵌入只能测链路，不能测检索。**

**实验 C：把 `RouterQueryEngine` 的 description 改成"知识库"。**
重跑 `step3` ①。观察候选工具变成"两个都叫知识库"。
结论：**路由靠 description 区分，写得一样等于没法路由**（和第 14 章 skill description 同一个坑）。

---

## 51.9 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `ModuleNotFoundError: llama_index.llms` | 只装了 `llama-index-core`，没装 LLM 集成包 | 装 `llama-index-llms-openai`，或离线用 `MockLLM` |
| `ImportError: llama-index-question-gen-openai` | `SubQuestionQueryEngine.from_defaults()` 依赖可选包 | 手动传 `question_gen` + `response_synthesizer`（50.6） |
| 检索分数全是 1.000 | 用了 `MockEmbedding`（常量向量） | 换真实嵌入，或用确定性 hash 向量 |
| 过滤后 0 条 | 阈值太高 | 用评测集扫阈值 |
| 块尾总是半句话 | 没配中文分隔符 | `secondary_chunking_regex` |
| 块数没变，以为配置生效了 | 块数不是有效的验证指标 | 打块边界 / 跑召回评测 |
| `persist` 后 `load` 报错 | 换了嵌入模型（维度不匹配） | 落盘前固定嵌入模型；换模型要重建 |
| Router 总选错 | description 写得太模糊 | 写清"问什么时用它" |
| 索引文件越存越大 | 每次 persist 都新增 | 用 `docstore.delete_document` + 重建；或接外部向量库 |
| 中文 PDF 全是乱码 | Reader 没指定编码 / 是扫描件 | 指定 `encoding`；扫描件走 OCR |

---

## 51.10 章末自测

**Q1** `Node` 比 LangChain 的 `Document` 多了哪些字段？各有什么用？

<details>
<summary>提示</summary>
`id`（去重/引用）、`relationships`（前后/父子，支撑窗口检索）、`embedding`（就地存储）。
</details>

**Q2** Index / Retriever / QueryEngine 三层分别负责什么？

<details>
<summary>提示</summary>
Index = 存（原文+结构+向量）；Retriever = 取；QueryEngine = 取 + 合成答案。
评测要测 Retriever，不要测 QueryEngine。
</details>

**Q3** 为什么 PostProcessor 要"先放宽再精筛"？

<details>
<summary>提示</summary>
先取 2 条再过滤，可能过滤完一条不剩；先取 6 条再过滤，才有筛选空间。
</details>

**Q4** 什么时候该用 Router，什么时候该用 SubQuestion？

<details>
<summary>提示</summary>
Router：一个问题归一个库。SubQuestion：一个问题要跨库，需要拆成子问题。
SubQuestion 贵（1+N 次调用），别无条件用。
</details>

**加分题**

> 同事说："LlamaIndex 比 LangChain 高级，我们全换成它吧。"

参考思路：**先问三个问题**：
① 我们的检索部分占整个系统的几成？（只占两成就别换）
② 我们需要的是"知识库工厂"还是"Agent 编排"？（后者 LangGraph 更强）
③ 换过去之后，"取相邻块""多知识库路由"这些能力我们真的会用吗？
**框架选择的标准是"能不能少写脏活"，不是"谁更新"。**

---

## 51.11 可选补课：接入外部向量库与增量更新

> ⚠️ **这一节可以先跳过。** 等你要把索引放到 Postgres / Qdrant 时再看。

### 三个存储分开换

```python
from llama_index.core.storage import StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.storage.docstore.redis import RedisDocumentStore

storage = StorageContext.from_defaults(
    docstore=RedisDocumentStore.from_host_and_port("localhost", 6379),
    vector_store=QdrantVectorStore(client=client, collection_name="kb"),
)
index = VectorStoreIndex.from_documents(docs, storage_context=storage)
```

| 存储 | 放什么 | 推荐 |
|---|---|---|
| docstore | 原文 + metadata | Redis / Postgres |
| vector_store | 向量 | Qdrant / pgvector / Milvus |
| index_store | 索引结构 | Redis |

### 增量更新（这是最容易被低估的一步）

```python
# 只处理"内容变了"的文档
pipe = IngestionPipeline(transformations=[...], docstore=index.docstore)
nodes = pipe.run(documents=changed_docs)     # 相同内容会被 docstore 去重跳过
index.insert_nodes(nodes)
```

**关键在"怎么知道哪些文档变了"**：按内容 hash（不是按修改时间——时间会骗人）。
第 40 章"数据层"会细讲。

### 一个成本对照

| 动作 | 成本 |
|---|---|
| 全量重建（1000 篇） | 1000 次嵌入 + 1000 次切分 |
| 增量（10 篇变了） | 10 次嵌入 + 10 次切分 |

**差 100 倍。** 这就是为什么"增量"不是优化项，是必需项。

---

## 51.12 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| Ingestion 流水线 | `code/framework/li/ch51/step1_ingestion.py` | 第 40 章数据层 |
| 三层分工 + PostProcessor | `code/framework/li/ch51/step2_index_query.py` | 第 40 章 RAG 评测 |
| Router / SubQuestion / 持久化 | `code/framework/li/ch51/step3_advanced.py` | 项目 C（企业知识中枢） |

**这一节建立的"可复用资产"**：`CharHashEmbedding`（确定性、内容相关的假嵌入）。
它比官方 `MockEmbedding` 更有用——因为后者对任何输入都返回同一个向量，**只能测链路，不能测检索**。

---

## 51.13 ✅ 验收

跑完三个脚本，检查五件事：

**① 你能说出 Node 比 Document 多了什么**

不看笔记，说出至少两个字段及其用途。

**② 你能解释"块数一样但切法不同"**

复述 `step1` ① 里两种切法的块尾差异。

**③ 你能画出三层分工**

Index / Retriever / QueryEngine，各给你什么、你给它什么。

**④ 你能说出"阈值不能抄"的理由**

结合 `step2` ④ 和失败实验 2（阈值 0.5 → 0 条）。

**⑤ 一个数字**

`step2` ④ 的输出里，`top_k=6` 加 `cutoff=0.33` 后剩 **2 条**。

**现在算一个数**：如果每条节点平均 150 字（约 143 token），
`top_k=6` 不过滤 vs 过滤后 2 条，进 prompt 的 token 差多少？按每天 5,000 次查询算，每天省多少？

<details>
<summary>答案</summary>

单次差：`(6 - 2) × 143 = 572 token`
每天：`572 × 5,000 = 2,860,000 token` ≈ **286 万 token/天**

按 ¥0.001/1k input 计 = **¥2.86/天** ≈ ¥86/月。
数字不大，但**更重要的是质量**：那 4 条低分噪声会干扰模型，而且越长的上下文越容易"lost in the middle"（第 24 章）。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 52 章 RAGAS 与 TruLens。
前面所有评测都是"自己写指标"。下一章看业界框架怎么定义"忠实度""上下文精度"，
以及**为什么你仍然需要自己算一遍**（框架的指标口径和你的业务不一定一致）。

> 📎 参考：本章对应基础教程第 18 章《向量数据库与 Embedding 实战》、第 19 章《RAG 检索增强生成》的知识点，
> 但**换了一条主线**：不重复"什么是向量/什么是 RAG"（第 7–10 章讲过），
> 只讲"怎么把 1000 份文档喂进去、怎么验证喂得对"。
