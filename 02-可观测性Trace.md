# 第 2 章 可观测性：把"为什么错"从猜变成查

> **你会遇到的坏事**：用户说"你的 Agent 答错了"。你打开日志，只有一行 `200 OK`。
>
> 你不知道它检索了什么、调了哪个工具、模型看到了什么、在哪一步跑偏了。
>
> 这一章要把这件事变成"打开一条 trace，两分钟定位"。

---

## 2.1 可观测性的三个层次

很多人以为"打日志"就是可观测性。其实差得远。工程上有三个层次：

| 层次 | 你得到什么 | 典型做法 | 能回答的问题 |
|---|---|---|---|
| **日志**（Logging） | 文本行 | `print` / `logger.info` | 程序有没有崩 |
| **指标**（Metrics） | 数字 | 计数器、直方图 | 整体健康度如何 |
| **链路追踪**（Tracing） | 树状调用链 | span + parent_id | **这次具体错在哪一步** |

**Agent 排障 90% 的时间花在第三个层次上。** 因为 Agent 的错误形态几乎都是"路径问题"：

- 不是模型坏了，是它选错了工具
- 不是工具坏了，是传给它的参数错了
- 不是检索坏了，是检索回来的内容根本没被用上

**这些只有 trace 能看见。**

---

## 2.2 span 的正确层级

一个 Agent 运行的调用树应该是这样的（这是我实际跑出来的输出）：

```
run         mini-agent                     1453.5ms
  step        plan                             51.2ms
  step        act                            1201.7ms
    tool_call   search                          300.5ms
    tool_call   db                              800.6ms
    tool_call   api                             100.4ms  ❌
  step        answer                          200.3ms
    model_call  summarize                       200.2ms
```

四层，每层都有明确职责：

| 层级 | 数量 | 什么时候有 | 里面装什么 |
|---|---|---|---|
| `run` | 1 | 每次用户请求 | 用户原始输入、最终输出、总耗时、总成本 |
| `step` | 1–N | Agent 的每一步 | 这一步的意图（plan / act / observe / answer） |
| `model_call` | 0–N | 每次调用大模型 | 模型名、input/output token、TTFT、重试次数 |
| `tool_call` | 0–N | 每次调用工具 | 工具名、参数、返回值、错误 |

⚠️ **最常见的设计错误：把 `tool_call` 和 `model_call` 平铺在 `run` 下面。**

一旦平铺，你就丢失了"这个工具调用属于哪一步推理"的信息。当 Agent 跑了 8 轮循环，你看到 8 个工具调用，根本不知道哪个是第 3 轮的重试、哪个是第 5 轮换了策略。

**层级不是美观问题，是信息完整性问题。**

---

## 2.3 手写一个 tracer（30 行核心逻辑）

不要急着接 Langfuse。先搞懂 span 怎么组织，再谈导出到哪。

完整代码：[`code/common/trace.py`](code/common/trace.py)

### 核心数据结构

```python
@dataclass
class Span:
    name: str
    kind: str                    # run | step | model_call | tool_call | retrieval
    span_id: str                 # 唯一 ID
    parent_id: str | None        # ← 靠这个还原树
    run_id: str                  # ← 靠这个隔离不同运行
    start: float
    end: float | None = None
    attributes: dict = field(default_factory=dict)
    input: Any = None
    output: Any = None
    error: str | None = None
```

### 三个关键设计决策

**决策 1：`parent_id` 用栈维护，而不是手动传**

```python
@contextmanager
def _span(self, name: str, kind: str, **attrs):
    parent = self._stack[-1] if self._stack else None   # 自动找父节点
    span = Span(name=name, kind=kind,
                parent_id=parent.span_id if parent else None,
                run_id=parent.run_id if parent else "")
    self._stack.append(span)
    try:
        yield span
    except Exception as e:
        span.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        span.end = time.perf_counter()
        self._stack.pop()
        self.spans.append(span)
```

这样调用方只需要 `with tracer.tool_call("search"):`，父子关系自动正确。

**决策 2：`error` 记录在 span 上，然后继续抛**

```python
except Exception as e:
    span.error = f"{type(e).__name__}: {e}"
    raise    # 不吞异常
```

很多人会在这里 `pass` 掉异常"让流程继续"，结果是：trace 里看不出错，业务逻辑却静默失败了。**记下来，并且继续抛。**

**决策 3：内容要截断**

```python
def _clip(v: Any, limit: int = 2000) -> Any:
    if isinstance(v, str) and len(v) > limit:
        return v[:limit] + f"...<truncated {len(v)} chars>"
```

不做截断的话，一次带 20 条检索结果的运行，trace 能写出 30MB。**trace 是用来定位的，不是用来归档全文的。**

---

## 2.4 💻 运行示例

```bash
python code/ch02_trace/demo_trace.py
```

这个示例**不需要 API key**（用 `time.sleep` 模拟模型调用），它演示了一个"部分失败"的运行：

- `search` 快（300ms）
- `db` 慢（800ms）
- `api` **抛异常**（503）

输出就是 2.2 节那棵树。注意 `api` 那行末尾的 ❌——它明确告诉你：

> 失败发生在第 2 步（act），是第 3 个工具调用。

这就是可观测性的价值：**从"用户说错了"到"定位到具体 span"，中间不需要任何猜测。**

---

## 2.5 run 结束时 flush：一个真实的内存陷阱

第一版我写的时候踩了这个坑，值得单独讲。

我的初版是这样的：

```python
with tracer.run("mini-agent") as run:
    ...
# run 结束后
print(tracer.tree())   # ← 打印出 <empty>
```

因为 `run.__exit__` 里的 `flush()` 把 `self.spans` 清空了（导出到文件后释放内存），之后 `tree()` 读的是空列表。

**为什么这其实是个正确的设计？**

在常驻服务里，如果 `self.spans` 只增不减，跑一天就是几十万条 span 占着内存。所以生产环境的常规做法就是**边跑边导出，内存里只留当前正在跑的 run**。

正确的排障流程是**从磁盘读回来**：

```python
spans = tracer.load_run(run_id)     # 从 JSONL 还原
print(tracer.tree(spans=spans))
```

这也是为什么真实系统里 trace 都落在外部存储（Langfuse / Jaeger / ClickHouse）——**trace 的第一属性是"可回放"，不是"可常驻内存"**。

⚠️ 记住这条：**排障时你面对的永远是"已经跑完的 run"，而不是"内存里的 run"。**

---

## 2.6 从 trace 到决策：三个必答题

有了 trace，你必须能**在 2 分钟内**回答下面三个问题。答不上来，说明 trace 设计得不够。

### 问题 1：这次运行多久？哪一步占了一半以上？

```python
for s in tracer.slowest(3, spans=spans):
    print(f"{s.kind:<11} {s.name:<12} {s.duration_ms:>8.1f}ms")
```

上面示例的结果：

```
run         mini-agent     1453.5ms
step        act            1201.7ms     ← 占 82%
tool_call   db              800.6ms
```

**结论：瓶颈在 act 步骤的 `db` 工具，占了整次运行的 55%。**

如果这是真实系统，下一步就是：`db` 加索引？换异步？并行化三个工具？（第 22 章会讲）

### 问题 2：错在哪一步？

```python
for s in spans:
    if s.error:
        print(f"{s.kind} / {s.name}: {s.error}")
```

```
tool_call / api: RuntimeError: 上游服务 503
```

**结论：第 2 步的第 3 个工具失败，属于外部依赖问题，不是模型问题。**

如果没有 trace，你可能会去改 prompt——那就完全跑偏了。

### 问题 3：模型看到了什么？

这是最容易漏的一环。`model_call` span 必须记录 `input`（完整的消息列表）和 `output`（模型原始返回）。

常见事故：

- 模型答非所问 → 一看 input，检索内容根本没被拼进去
- 模型编造事实 → 一看 input，检索结果被截断成了无意义的片段
- 模型没有调用工具 → 一看 output，它把工具调用写成了**正文里的 JSON 字符串**（没有走 tool_calls 字段）

**这三个问题，只看最终输出永远查不出来。**

---

## 2.7 接 Langfuse：把 span 送出去

手写的 tracer 适合教学和自建，但生产环境你需要：

- 按 run_id / 用户 / 时间范围检索
- 可视化时间线（甘特图）
- 与评测集联动（第 26 章）
- 多人协作查看

Langfuse 是最常见的开源选择（可自建）。核心思路很简单：**把你手写的 span 映射成它的 span**。

```python
from langfuse.callback import CallbackHandler

handler = CallbackHandler(
    public_key=..., secret_key=..., host=...,
    session_id="thread-123", user_id="u-1",
)

# LangChain / LangGraph 原生支持 callbacks
resp = llm.invoke(question, config={"callbacks": [handler]})
```

⚠️ **接之前必须先手写过**。原因：

1. 你会知道哪些字段是必要的（很多人接了 Langfuse 但没记 `input`，等于白接）
2. 出问题（比如 span 丢失）时，你能判断是平台问题还是自己的 `parent_id` 传错了
3. 迁移到别的平台（Jaeger / Phoenix / 自建）时零成本

---

## 2.8 OpenTelemetry 语义约定：不绑死平台的方法

如果你想"一次埋点，多处导出"，用 OpenTelemetry 的 GenAI 语义约定。关键属性名：

| 属性 | 含义 | 示例 |
|---|---|---|
| `gen_ai.system` | 供应商标识 | `openai` / `deepseek` |
| `gen_ai.request.model` | 请求的模型名 | `deepseek-chat` |
| `gen_ai.response.model` | 实际响应的模型 | `deepseek-chat-0715` |
| `gen_ai.usage.input_tokens` | 输入 token | `420` |
| `gen_ai.usage.output_tokens` | 输出 token | `120` |
| `gen_ai.operation.name` | 操作类型 | `chat` / `embeddings` |

**为什么要遵守它**：这些名字是社区约定的，所有主流后端（Jaeger、Tempo、Phoenix、Langfuse）都认。自定义属性名会让你的数据变成孤岛。

在本书的 `Tracer` 里，你只需要把 `attributes` 按这个规范填：

```python
with tracer.model_call("chat", **{
    "gen_ai.system": "openai",
    "gen_ai.request.model": "deepseek-chat",
    "gen_ai.usage.input_tokens": 420,
    "gen_ai.usage.output_tokens": 120,
}) as span:
    ...
```

---

## 2.9 ⚠️ 常见坑

| 坑 | 现象 | 修法 |
|---|---|---|
| 平铺 span | 看不出工具属于哪一步 | 用栈自动推 `parent_id` |
| 不记 input | 无法回答"模型看到了什么" | `span.input = messages` |
| 记录完整全文 | trace 文件几十 MB | `_clip(2000)` 截断 |
| 异常被吞 | trace 无错但业务静默失败 | 记录后 `raise` |
| 只记成功 | 失败率永远是 0% | `finally` 里也 append |
| 内存里攒 span | 长时间运行 OOM | run 结束即 flush，用 `load_run` 回读 |
| span 无 run_id | 多次运行混在一起 | 根 span 的 id 即 run_id |

---

## 2.10 💥 失败实验

### 实验 A：去掉 parent_id，看排障难度

把 `_span` 里的 `parent_id` 全部设成 `None`，再跑一次 `demo_trace.py`。

然后尝试回答："`db` 工具是在哪一步被调用的？"

**你会发现自己答不出来。** 这就是为什么层级不能省。

### 实验 B：让 trace 丢掉 input

注释掉 `s.input = ...`，然后构造一个"模型答非所问"的假场景（把 `output` 改成明显错误的答案）。

**你会发现：没有 input，你无法区分"模型理解错了"和"我们喂错了"。**

这个区别决定了你要改 prompt 还是改检索。

---

## 2.11 ✏️ 小练习

### 练习 1（必做）：给 `Meter` 和 `Tracer` 接线

现在的 `Meter`（第 1 章）和 `Tracer`（本章）是两套独立的数据。把它们接起来：

```python
with tracer.model_call("chat") as span:
    with meter.track(model, step="chat") as rec:
        resp = llm.invoke(...)
    span.attributes.update({
        "gen_ai.usage.input_tokens": rec.input_tokens,
        "gen_ai.usage.output_tokens": rec.output_tokens,
        "cost": rec.cost,
    })
```

**验收**：一次运行后，`tree()` 能打印出每个 `model_call` 的耗时，且 JSONL 里有 token 和成本。

### 练习 2：写一个 trace 查询命令

写一个脚本，支持：

```bash
python code/ch02_trace/query.py --slowest 5      # 最慢的 5 个 span
python code/ch02_trace/query.py --errors          # 所有失败的 span
python code/ch02_trace/query.py --run-id abc123   # 某次运行的完整树
```

**验收**：能用它回答 2.6 节的三个问题。

### 练习 3（进阶）：计算每一步的成本占比

在 trace 上聚合出：

```
plan:    ¥0.00012  (12%)
act:     ¥0.00004  ( 4%)
answer:  ¥0.00031  (84%)   ← 模型生成最贵
```

**验收**：这个表能直接接到第 21 章的成本报表里。

---

## 2.12 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 最小 tracer | `code/common/trace.py` | 全书所有示例 |
| span 层级规范 | 本文 2.2 节 | 第 3 章起所有 Agent |
| 三个必答题 | 本文 2.6 节 | 第 27 章复盘方法论 |

---

## 2.13 ✅ 验收

1. 你能说清 `run / step / model_call / tool_call` 四层的职责边界吗？
2. 为什么 `parent_id` 要用栈自动维护？
3. 为什么 run 结束要 flush 并从磁盘回读？
4. 给你一条报错信息，你能在两分钟内定位到具体 span 吗？
5. 为什么必须记录 `model_call` 的 `input`？

**数字验收**：你的示例运行里，最慢的 span 占了总耗时的百分比是多少？

---

## 2.14 延伸阅读

- OpenTelemetry GenAI Semantic Conventions（属性命名的事实标准）
- Langfuse 的 trace 数据模型（理解"trace / observation / score"三层）
- 第 27 章会用 trace 做故障复盘

---

下一页：[第 3 章 Agent Loop 的四种失控](03-AgentLoop的四种失控.md)
