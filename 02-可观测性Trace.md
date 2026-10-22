# 第 2 章 可观测性：把"为什么错"从猜变成查

> **这一章你会遇到什么坏事**
>
> 用户说"你的 Agent 答错了"。你打开日志，只有一行 `200 OK`。
> 你不知道它检索了什么、调了哪个工具、模型看到了什么、在哪一步跑偏。
>
> 更糟的是——**你甚至不知道"该记什么"**。

> **学完你能做到**
>
> 1. 用 30 行代码让自己的 Agent 记录每一步，并打印成一棵树
> 2. 拿着一个报错，在 2 分钟内定位到"哪一步、什么输入、模型返回了什么"
> 3. 知道业界标准（OpenTelemetry）的字段该怎么写（可选，能跳过）

---

## 2.0 先说明白四个词

这一章会出现四个新词。**先花 1 分钟看完这张表**，后面就顺了。

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **span** | 一次操作的**记录卡**：记着"做了什么、什么时候开始、多久、结果是什么" | 2.3 起 |
| **trace** | 同一件事（同一次用户请求）产生的**所有记录卡合在一起** | 2.4 |
| **trace_id** | 给这些卡片打的**同一个标签**，用来认出"它们是一伙的" | 2.4 |
| **parent_id** | 卡片上的"**我爸是谁**"，用来还原"谁调用了谁" | 2.4 |

> 还有两个名词后面才出现，这里先提一句，看到时不用慌：
> - **tracer**：负责"自动发卡片"的那个小工具类（就是你自己写的 30 行代码）
> - **OpenTelemetry（OTel）**：一个业界标准，规定"卡片上的字段该叫什么名字"。**不看也不影响你学会本章。**

---

## 2.1 先看一个具体的坏事

假设你的 Agent 做了这么一件事：用户问"我的耳机能退吗"，它回答了"可以退"。

**但事后发现这个回答是错的**（因为用户已经超过 15 天了）。

你现在手上有什么？

```
2026-10-12 14:03:21  INFO  200 OK  耗时 1402ms
```

就这一行。

**你想知道的四件事，一件也答不出来：**

| 你想知道 | 能答吗 | 为什么答不了 |
|---|---|---|
| 它查了哪些资料？ | ❌ | 日志里没有 |
| 它调了哪个工具、参数是什么？ | ❌ | 日志里没有 |
| 模型当时收到的完整消息是什么？ | ❌ | 日志里没有 |
| 哪一步花了 1.4 秒？ | ❌ | 只有总耗时 |

**结论：你不是"没找到答案"，你是"没记录答案所需的数据"。**

---

## 2.2 为什么现有手段不够（先别急着上工具）

你可能会想："那我多打几行 print 不就行了？"

我们先真的试一下，看看 print 能撑到哪一步。

```python
print("开始查询订单")
result = db.query("A12345")
print("订单查到了:", result)
print("开始生成回答")
answer = llm.invoke(...)
print("回答生成完了:", answer)
```

跑出来的日志大概长这样：

```
开始查询订单
订单查到了: 已签收 15 天
开始生成回答
回答生成完了: 可以退
```

**看起来信息都有，但有三个致命问题：**

| 问题 | 后果 |
|---|---|
| **没有耗时** | 你不知道哪步慢 |
| **没有层级** | 有 40 行日志时，你不知道哪几行属于"同一步" |
| **无法机器统计** | 你想算"平均耗时"，得自己写正则解析文本 |

**这三点加起来就是一句话：print 是给人眼看的，不是给"事后排查"用的。**

所以我们需要一个**结构化的记录方式**。这个东西叫 span。

---

## 2.3 span 到底是什么（10 行代码看懂）

### 一句话

> **span 就是一张记录卡：开始时间、结束时间、做了什么、结果是什么。**

就这么简单。什么"分布式追踪""链路追踪"，都是从这一张卡片开始的。

### 最小例子

💻 运行：

```bash
python code/ch02_trace/step1_what_is_span.py
```

完整代码只有 20 行，核心就是这个：

```python
start = time.perf_counter()          # ① 什么时候开始
name = "查询订单"                     # ② 做的是什么事
time.sleep(0.12)                     # （假装这里在查数据库）
result = "订单 A12345 已发货"          # ③ 结果是什么
end = time.perf_counter()            # ④ 什么时候结束
duration_ms = (end - start) * 1000   # ⑤ 花了多久
```

**输出：**

```
名称   : 查询订单
耗时   : 120 ms
结果   : 订单 A12345 已发货
```

**就这五样东西。** 你在 Jaeger、Langfuse、Datadog 界面上看到的所有花哨视图，底层都是这五个字段。

### 把它包成一个类

手写五遍太麻烦，包成类就能复用：

```python
class Span:
    def __init__(self, name: str) -> None:
        self.name = name
        self.start = time.perf_counter()
        self.end: float | None = None
        self.result = ""

    def finish(self, result: str) -> None:
        self.end = time.perf_counter()
        self.result = result

    @property
    def duration_ms(self) -> float:
        end = self.end or time.perf_counter()
        return (end - self.start) * 1000
```

用起来：

```python
span = Span("查询订单")
time.sleep(0.12)
span.finish("订单 A12345 已发货")
print(span)        # [查询订单] 120ms → 订单 A12345 已发货
```

### ✏️ 停下来想一想

`step1` 的最后一段会记录**两次**操作，然后问你：

```
[查询订单] 101ms → 已发货
[生成回复] 50ms → 您的订单已发货

问：这两次操作，谁先谁后？如果中间还有 10 次操作，你怎么一眼看出它们的关系？
```

**答案是：光有卡片不够。** 你还需要"把卡片串起来的线"。

这就引出下一节。

---

## 2.4 从散落卡片到一棵树（trace_id 和 parent_id）

### 加两个字段，问题就解决了

```python
class Span:
    def __init__(self, name, parent=None):
        ...
        self.span_id = uuid.uuid4().hex[:8]                        # 我是哪张卡片
        self.parent_id = parent.span_id if parent else None        # 谁生了我
        self.trace_id = parent.trace_id if parent else self.span_id  # 属于哪次请求
```

**三个 id，各管一件事：**

| 字段 | 回答什么问题 | 类比 |
|---|---|---|
| `span_id` | 我是谁？ | 身份证号 |
| `parent_id` | 我爸是谁？ | 户口本上的父亲栏 |
| `trace_id` | 我们属于哪一家？ | 同一个户口本编号 |

### 💻 看效果

```bash
python code/ch02_trace/step2_span_tree.py
```

**第 ① 段：平铺看（人类读不了）**

```
span_id   parent    name                        耗时
1a5f1b8a  7969407f  步骤1 规划                     21ms
1d08568e  9ccbe2cf  工具 查退款政策                  120ms
0fd14f97  9ccbe2cf  工具 查订单状态                   51ms
9ccbe2cf  7969407f  步骤2 执行                    181ms
20e34467  7969407f  步骤3 生成回答                   80ms
7969407f  -         用户请求：订单能退款吗               283ms
```

**你能说出"查订单"是谁调用的吗？** 能——但要一行行比对 id。40 个 span 时彻底不可读。

**第 ② 段：按 parent_id 还原成树（人类读得了）**

```
用户请求：订单能退款吗                 283ms
  └─ 步骤1 规划                       21ms
  └─ 步骤2 执行                      181ms
    └─ 工具 查退款政策                    120ms
    └─ 工具 查订单状态                     51ms
  └─ 步骤3 生成回答                     80ms
```

**同一批数据，换个排列方式，可读性天差地别。**

### 为什么这个层级是"对的"

注意 `工具` 挂在 `步骤2 执行` 下面，不是挂在 `用户请求` 下面。

**这个设计不是美观问题，是信息完整性问题。**

如果你把所有工具调用平铺在根节点下，那么当 Agent 跑了 8 轮循环、调了 12 次工具时，你看到 12 个工具调用，**根本不知道哪个属于第 3 轮的失败重试、哪个属于第 5 轮换了策略**。

### 本章核心结论（到这里你已经掌握 80%）

> **span = 一张卡片**
> **trace = 同一 trace_id 的所有卡片**
> **parent_id = 卡片之间的父子关系**

三个概念，就这么多。后面全是工程细节。

---

## 2.5 手写太麻烦？用 with 自动维护（30 行）

上一级你需要手动写 `parent=act`。代码一多，一定会传错。

**这一级用"栈"自动推断谁是谁爸。**

### 💻 运行

```bash
python code/ch02_trace/step3_auto_trace.py
```

**输出：**

```
用户请求                       282.5ms
  步骤1 规划                      20.1ms
  步骤2 执行                     170.9ms
    工具 查退款政策                   120.3ms
    工具 查订单状态                    50.5ms
  步骤3 生成回答                    80.2ms
  步骤4 发邮件通知                   10.2ms  ❌ RuntimeError: 上游服务 503
```

### 核心实现（逐行解释）

```python
class Tracer:
    def __init__(self) -> None:
        self.spans: list[Span] = []
        self._stack: list[Span] = []      # ← 关键：一个"栈"，记录我现在在谁里面

    @contextmanager
    def span(self, name: str, **attrs) -> Iterator[Span]:
        # ① 找父节点 = 栈顶那个（如果栈是空的，说明我是最外层）
        parent = self._stack[-1] if self._stack else None

        s = Span(
            name=name,
            parent_id=parent.span_id if parent else None,
            trace_id=parent.trace_id if parent else "",
        )
        if parent is None:
            s.trace_id = s.span_id        # 最外层自己就是 trace 的根

        self._stack.append(s)             # ② 我入栈，接下来我里面创建的都算我的子节点
        try:
            yield s                       # ③ 把控制权交回给用 with 的人
        except Exception as e:
            s.error = f"{type(e).__name__}: {e}"
            raise                         # ④ 记录后继续抛，不吞异常
        finally:
            s.end = time.perf_counter()
            self._stack.pop()             # ⑤ 我出栈，之后的兄弟节点不再是我的子节点
            self.spans.append(s)
```

**为什么"栈"就够了？**

因为你写 `with` 的时候，缩进本身就是嵌套关系：

```python
with tracer.span("步骤2 执行"):        # 入栈 → 栈 = [root, 步骤2]
    with tracer.span("工具 查退款政策"):   # 入栈 → 栈 = [root, 步骤2, 工具]
        ...
    # 工具出栈 → 栈 = [root, 步骤2]
```

**"缩进即层级"——这就是所有 tracing 库的设计核心。**

### 使用起来的样子

```python
with tracer.span("用户请求"):
    with tracer.span("步骤1 规划"):
        time.sleep(0.02)

    with tracer.span("步骤2 执行"):
        with tracer.span("工具 查退款政策"):
            time.sleep(0.12)
```

**注意你完全没写 parent。** 层级由缩进决定。

### 三个设计取舍（为什么这么写）

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| **异常要记录再抛出** | `except: s.error=...; raise` | 如果 `pass` 掉异常，trace 里看不出错，但业务静默失败了 |
| **出栈放在 `finally`** | 保证异常时也出栈 | 否则栈会乱，后续兄弟节点挂错父节点 |
| **`trace_id` 从父节点继承** | 根节点自己生成 | 否则每次 `with` 都产生新 trace，无法聚合 |

### ⚠️ 一个必须知道的坑：span 会吃内存

如果你把 `self.spans` 一直留着不清理，常驻服务跑一天就是几十万条 span 占着内存。

**生产做法：跑完一次就落盘，然后释放内存。**

```python
def flush(self) -> None:
    """把内存里的 span 写入 JSONL，然后释放内存。"""
    if not self.sink:
        return
    with self.sink.open("a", encoding="utf-8") as f:
        for s in self.spans:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
    self.spans.clear()      # ← 关键
```

**排障时从磁盘读回来：**

```python
def load_run(self, run_id: str | None = None) -> list[Span]:
    ...  # 读 JSONL，按 trace_id 过滤
```

**这条规则要记住**：

> **排障时你面对的永远是"已经跑完的 run"，而不是"内存里的 run"。**

---

## 2.6 用起来：三个问题 2 分钟答完

前面都是"造工具"。这一节验证它真的有用。

### 💻 运行

```bash
python code/ch02_trace/step5_three_questions.py
```

它模拟一次"部分失败"的 Agent 运行（库很慢、发邮件失败），然后从磁盘读回 trace，回答三个问题。

### 输出

```
完整调用树
======================================================================
  用户请求                1401.8ms
    步骤1 规划                50.3ms
    步骤2 执行              1151.0ms
      工具 search            300.3ms
      工具 db                800.3ms
      工具 mail               50.2ms   ❌ RuntimeError: SMTP 连接超时
    步骤3 生成               200.3ms
```

### 问题 ①：这次运行多久？哪一步占了一半以上？

```
  总耗时：1402ms
    步骤2 执行              1151ms  占   82%
    步骤3 生成               200ms  占   14%
    步骤1 规划                50ms  占    4%

  → 结论：步骤2 执行 占了 82%，它是主要瓶颈。
```

**代码只有 3 行**：

```python
root = next(s for s in spans if s.parent_id is None)
steps = [s for s in spans if s.parent_id == root.span_id]
for s in sorted(steps, key=lambda x: -x.duration_ms):
    print(f"{s.name:<16}{s.duration_ms:>8.0f}ms  占 {s.duration_ms / total:>5.0%}")
```

### 问题 ②：错在哪一步？

```
  ❌ 工具 mail
     父步骤：步骤2 执行
     错误  ：RuntimeError: SMTP 连接超时

  → 结论：错误发生在「工具 mail」，属于外部依赖问题，不是模型问题。
```

**这里有一个非常重要的经验：**

> 如果没有 trace，你很可能会去**改 prompt**——因为"回答不对"听起来像是模型问题。
>
> 但真相是：一个外部工具挂了。**改 prompt 是彻底的方向错误。**

（第 38 章的数据：80% 的"模型答错"其实是检索错、上下文被挤掉、或工具失败。）

### 问题 ③：模型当时看到了什么？

```
  模型：mock-model
  输入消息：
    [system   ] 你是客服助手
    [user     ] 我的耳机能退吗？
    [tool     ] 检索到 3 条退款政策 / 订单 A12345，已签收 3 天 / TOOL_FAILED:mail
  输出：可以退货，7 天内无理由。
```

**这一条最容易被忽略，也最关键。**

你必须记录 `model_call` 的**输入消息**，因为只有这样你才能区分：

| 现象 | 真实原因 | 修复方向 |
|---|---|---|
| 模型答非所问 | 检索内容根本没拼进去 | 改检索/拼接逻辑 |
| 模型编造事实 | 检索结果被截断成无意义片段 | 改上下文预算（第 11 章） |
| 模型没调工具 | 它把 tool_call 写成了正文 JSON | 改 prompt + 加校验 |

**这三种情况，只看最终输出永远分不清。**

### 🎯 到这里，你已经掌握了可观测性

回顾一下你用了什么：

| 能力 | 在哪一节 |
|---|---|
| span 记录每一步 | 2.3 |
| parent_id 串成树 | 2.4 |
| with 自动维护 + 错误记录 | 2.5 |
| 落盘 + 回读 | 2.5 |

**剩下的都是"把数据送到更好的界面"，不影响你理解原理。**

---

## 2.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个参数，观察变化

把 `step3_auto_trace.py` 里 `工具 查退款政策` 的 `time.sleep(0.12)` 改成 `0.5`。

**观察**：树里哪一行的耗时变了？哪些变了？为什么 `步骤2 执行` 也变长了？

**验收**：能解释"父节点的耗时 = 子节点耗时之和（串行时）"。

### 练习 2（20 分钟）：给你的 Agent 加 trace

找你自己写过的任意一个"调模型 + 调工具"的小脚本，用 `step3` 的 `Tracer` 包住它。

**最低要求**：

- 至少 1 个根 span
- 至少 1 个"模型调用"span，并且记录**输入消息**
- 至少 1 个"工具调用"span，并且记录参数和结果

**验收**：跑一次，能打印出树，并且能回答"最慢的是哪一步"。

### 练习 3（15 分钟）：💥 故意破坏它

**实验 A：吞掉异常**

把 `except Exception as e: s.error = ...; raise` 改成 `pass`。

**观察**：树里还能看到 ❌ 吗？

**结论**：**记下来，并且继续抛。** 很多人会在这里 `pass` 掉"让流程继续"，结果是 trace 里看不出错，业务却静默失败了。

**实验 B：flush 后不清空内存**

把 `self.spans.clear()` 注释掉，然后循环跑 100 次。

**观察**：`len(tracer.spans)` 是多少？

**这就是"常驻服务内存泄漏"的完整复现。**

**实验 C：去掉 `parent_id`**

把 `parent_id` 全设成 `None`，再打印树。

**观察**：还能看出层级吗？

**这就是为什么"平铺 span"是错误设计。**

---

## 2.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 树打印出来是空的 | `flush()` 清空了内存，之后又调 `tree()` | 用 `load_run()` 从磁盘读回 |
| 层级全错（都挂在根下） | 忘了 `self._stack.append(s)` | 检查入栈/出栈成对 |
| 出栈后兄弟节点挂错父节点 | 出栈没放 `finally` | 放 `finally` |
| 看不出错在哪 | 异常被 `pass` 掉了 | 记录后 `raise` |
| trace 文件几十 MB | 记录了完整全文 | 截断长文本（比如 2000 字符） |
| 排障时找不到"模型看到了什么" | 没记 `input_messages` | 见 2.6 问题③ |

---

## 2.9 章末：四个词的自测

合上书，用自己的话回答：

1. **span 是什么？** （提示：一张卡片，5 个字段）
2. **trace 是什么？** （提示：同一个 trace_id 的所有卡片）
3. **`parent_id` 用来干什么？** （提示：还原"谁调用了谁"）
4. **为什么 `flush()` 之后要清空内存？** （提示：常驻服务的内存）

**四个都能用自己的话说清楚 → 本章过关。**

如果你能再回答第 5 个问题，说明你真的懂了：

5. **为什么 `model_call` 必须记录输入消息？** （提示：区分"模型理解错"和"我们喂错了"）

---

## 2.10 可选补课：接 Langfuse 与 OpenTelemetry 语义约定

> ⚠️ **这一节可以先跳过。** 等你真的要"把 trace 送到一个可视化平台"或"和公司统一监控打通"时再看。
>
> 不看这一节，你已经能做完整的排障。

### 2.10.1 为什么要接平台

你手写的 `Tracer` 有两个局限：

| 局限 | 具体表现 |
|---|---|
| 只能看单次运行 | 你想"筛选出过去 7 天所有失败的退款类请求"——做不到 |
| 没有可视化 | 40 个 span 的树在终端里还是难读 |

平台解决这两件事：**检索** + **可视化**。

最常见的开源选择是 **Langfuse**（可自建）。

### 2.10.2 接入只有两步

**第一步：装依赖并配置**

```bash
pip install langfuse
```

`.env` 里加：

```
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_HOST=https://cloud.langfuse.com    # 自建则改成你的地址
```

**第二步：给调用挂上 callback**

```python
from langfuse.langchain import CallbackHandler

handler = CallbackHandler()     # 会自动读环境变量

resp = llm.invoke(
    messages,
    config={"callbacks": [handler]},      # ← 关键：挂在这里
)
```

**就这两步。** LangChain / LangGraph 会自动把每次模型调用、每个节点变成 span 发到 Langfuse。

### 2.10.3 ⚠️ 但你要先做过一件事

**在接平台之前，必须自己手写过一遍 span。** 三个理由：

| 理由 | 具体 |
|---|---|
| 你会知道哪些字段是必要的 | 很多人接了 Langfuse 但没记 `input`，等于白接 |
| 出问题能判断责任方 | span 丢了，是平台问题还是你 `parent_id` 传错？ |
| 迁移零成本 | 换 Jaeger / Phoenix / 自建，业务代码不用动 |

### 2.10.4 OpenTelemetry 语义约定：字段该叫什么名字

**这是本节唯一需要"背"的东西。**

#### 问题：自己起名会发生什么

你在 span 上记录"输入 token 数"。叫它什么？

```python
s.attributes["tokensIn"] = 420          # 你叫这个
s.attributes["input_tokens"] = 420      # 同事 A 叫这个
s.attributes["promptTokens"] = 420      # 同事 B 叫这个
```

**结果：平台不认识任何一个。** 它没法自动帮你画"token 用量趋势图"，你还得自己写解析脚本。

#### 解法：用业界约定的名字

OpenTelemetry 定义了一套 **GenAI 语义约定（Semantic Conventions for GenAI）**，所有 `gen_ai.*` 开头的属性名。

**💻 完整对照表（可直接抄）**

```bash
python code/ch02_trace/step4_otel_conventions.py
```

```
你想记的信息                标准属性名                            示例值
--------------------------------------------------------------------------------
哪个厂商的模型              gen_ai.system                       openai / deepseek / dashscope
这次请求的模型名             gen_ai.request.model                deepseek-chat
服务端实际用的模型            gen_ai.response.model               deepseek-chat-0715
操作类型                   gen_ai.operation.name               chat / embeddings
输入 token 数             gen_ai.usage.input_tokens           420
输出 token 数             gen_ai.usage.output_tokens          120
temperature 参数         gen_ai.request.temperature          0.0
max_tokens 参数          gen_ai.request.max_tokens           800
结束原因                   gen_ai.response.finish_reasons      ["stop"]
工具名（工具调用时）          gen_ai.tool.name                    search_policy
对话所属会话                 gen_ai.conversation.id              thread-42
Agent 名称                gen_ai.agent.name                   refund-agent
```

**三条记忆规律**（比背 12 条更重要）：

1. 全部以 `gen_ai.` 开头 → 这是 GenAI 的命名空间，不会和其他系统撞名
2. `request.*` = 我要什么，`response.*` = 实际发生了什么
3. `usage.*` 专门放 token 用量 → **成本分析全靠它**

#### 怎么用在你的代码里

**如果你用官方 OTel SDK：**

```python
from opentelemetry import trace

tracer = trace.get_tracer("my-agent")

with tracer.start_as_current_span("chat " + model_name) as span:
    resp = llm.invoke(messages)

    # ↓ 这 4 行就是"按语义约定埋点"
    span.set_attribute("gen_ai.system", "deepseek")
    span.set_attribute("gen_ai.request.model", model_name)
    span.set_attribute("gen_ai.usage.input_tokens", usage["input_tokens"])
    span.set_attribute("gen_ai.usage.output_tokens", usage["output_tokens"])
```

**如果你不想装 OTel 全套（本书的选择）：**

就在自己的 `Tracer` 上加属性，**字段名照样遵守约定**：

```python
with tracer.span("chat", **{
    "gen_ai.system": "deepseek",
    "gen_ai.request.model": "deepseek-chat",
    "gen_ai.usage.input_tokens": 420,
    "gen_ai.usage.output_tokens": 120,
}):
    resp = llm.invoke(messages)
```

**好处**：以后要换成真 OTel，只改"导出那一层"，业务代码一个字不用动。

#### 自查清单

- [ ] 每个 model_call 都记了 `gen_ai.request.model`
- [ ] 每次调用都记了 input/output tokens
- [ ] 工具调用记了 `gen_ai.tool.name`
- [ ] 错误记在 span 上，而不是只打日志
- [ ] span 的 name 能一眼看出是什么操作（`chat deepseek-chat`，不是 `span1`）

**前 3 条是"能算成本"的前提；第 4 条是"能定位问题"的前提。**

---

## 2.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| span 最小实现 | `code/ch02_trace/step1_what_is_span.py` | 理解用 |
| 树形结构 | `code/ch02_trace/step2_span_tree.py` | 理解用 |
| **可复用 Tracer** | `code/ch02_trace/step3_auto_trace.py` | 全书所有示例 |
| 排障实战 | `code/ch02_trace/step5_three_questions.py` | 你的日常工具 |
| OTel 属性表 | `code/ch02_trace/step4_otel_conventions.py` | 接平台时查 |

**本书 `code/common/trace.py` 是第 3 级的增强版**（加了内容截断、更完整的回读接口）。你现在回头看它，应该能一眼看懂每个方法在干什么。

---

## 2.12 ✅ 验收

1. 用自己的话说清 span / trace / parent_id 三个词
2. 为什么"模型调用"必须记录**输入消息**？
3. `flush()` 之后为什么要清空内存？排障时怎么读回来？
4. 异常为什么要"记录后继续抛"，而不是吞掉？
5. （可选）`gen_ai.usage.input_tokens` 这个字段名，为什么不能自己起名叫 `tokensIn`？

**数字验收**：你给 trace 加上之后，一次运行的 span 数量是多少？最慢的 span 占多少？

---

下一页：[第 3 章 Agent Loop 的四种失控](03-AgentLoop的四种失控.md)
