# 第 4 章 ReAct：最流行的 Agent 范式，以及它的边界

> **你会遇到的坏事**：照抄一篇 ReAct 教程，代码能跑通，但一换模型就乱套——它开始输出"我想先搜索一下"而不是 `Action: search`，整个循环卡在那里空转。
>
> 这一章要让你看清 ReAct 到底是什么，以及**为什么它有三种实现，只有一种能用**。

---

## 4.1 ReAct 到底是什么

ReAct = **Reasoning + Acting**，2022 年论文提出的范式。核心就一句话：

> **让模型交替地"想一步、做一步、看结果"，而不是一次把答案憋出来。**

一个循环是这样的：

```
Thought: 用户问退款几天，我得先查政策
Action: search
Action Input: {"q": "退款"}
Observation: 退款政策：签收后 7 天内无理由退货……
Thought: 我知道了
Final Answer: 7 天内无理由退货。
```

**为什么它有效**：模型不需要一次记全所有事实，它可以"边查边想"。

**为什么它有代价**：每一步都是一次完整的模型调用。3 步 ReAct 的成本是单次问答的 **3 倍以上**（因为历史不断累加）。

---

## 4.2 三种实现，只有一个能用

这是本章最重要的部分。同一个 ReAct，工程上有三代实现：

| 代际 | 实现方式 | 动作怎么表达 | 参数怎么表达 | 现状 |
|---|---|---|---|---|
| 第一代 | **手写文本解析** | 正则匹配 `Action:` | 字符串 → `json.loads` | 教学价值大，生产别用 |
| 第二代 | 早期的 `AgentExecutor` | ReAct 文本或 JSON | 字符串解析 | **已过时**（LangChain 0.x 时代） |
| 第三代 | **原生 tool_calls** | 协议字段 `tool_calls` | 结构化的 JSON 对象 | **现在唯一推荐** |

> ⚠️ 如果你在别的教程里看到 `create_tool_calling_agent` + `agent_scratchpad`，那是第二代。本书全程用第三代。

### 💻 跑一遍第一代，你就知道为什么它被淘汰

```bash
python code/ch04_react/demo_text_react.py
```

这个示例**不需要 API key**，用脚本化的假模型复现三种典型情况。完整代码：[`code/ch04_react/demo_text_react.py`](code/ch04_react/demo_text_react.py)

**场景 A：模型完全守格式**（理想情况）

```
Thought: 需要查退款政策
Action: search
Action Input: {"q": "退款"}
```

能跑通。但这是**你在替模型写代码**——它必须一个字符不差。

**场景 B：Action Input 写成自然语言**（最常见的失败）

```
Action: search
Action Input: 查询退款政策
```

解析结果：`json.loads` 失败 → 退回 `{"_raw": "查询退款政策"}` → 工具收不到 `q` → 返回"未检索到"。

**模型白白浪费了一整轮**，而且它不知道自己错了（因为 Observation 看起来是个正常返回）。

**场景 C：模型不写 Action**

```
我想先搜索一下退款政策，然后再给你答案。
```

正则匹配不到 `Action:` → 代码判定"格式错误" → 追加一条纠正提示 → **再花一次完整的模型调用**。

### 三个结构性脆弱点

| 脆弱点 | 后果 | 第三代怎么解决 |
|---|---|---|
| 参数靠字符串解析 | 模型一写自然语言就失效 | 参数是 JSON 对象，不用解析 |
| 动作靠正则匹配 | 忘写 `Action:` 就白跑一轮 | 动作是协议字段，不存在"忘写" |
| 失败是**静默**的 | 日志里看不出异常，只是成本变高 | 结构化的 `tool_calls` 为空 = 明确信号 |

**最后这条最要命**：文本 ReAct 的失败**不会抛异常**，只会让 token 悄悄变多。你在账单上看到的是"怎么贵了"，而不是"出错了"。

---

## 4.3 第三代：原生 tool_calls

### 💻 可运行代码（需要 API key）

```bash
python code/ch04_react/demo_native_react.py
```

核心循环在 [`code/common/react.py`](code/common/react.py) 的 `react_native` 与 `SafeReAct`：

```python
def react_native(llm, tools, question, max_steps=6):
    llm_with_tools = llm.bind_tools(tools)
    by_name = {t.name: t for t in tools}
    messages = [("user", question)]

    for step in range(max_steps):
        ai = llm_with_tools.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:                     # ← 明确的结束信号
            return {"answer": ai.content, "steps": step + 1, "ok": True}

        for call in ai.tool_calls:
            fn = by_name[call["name"]]
            result = fn.invoke(call["args"])
            messages.append({
                "role": "tool",
                "content": str(result),
                "tool_call_id": call["id"],        # ← 必须带，否则对不上号
            })
```

### 三个必须知道的细节

**细节 1：`tool_call_id` 不能丢**

模型返回的是：

```json
{"name": "search_docs", "args": {"query": "退款"}, "id": "call_abc123"}
```

你回填结果时**必须带回 `id`**：

```python
{"role": "tool", "content": "...", "tool_call_id": "call_abc123"}
```

不带的话，多工具并行时模型会把结果张冠李戴。**这是新手最常犯的错，而且症状很诡异：回答内容对，但因果关系崩了。**

**细节 2：一次可能返回多个 tool_calls**

```python
for call in ai.tool_calls:      # ← 必须循环，不能只处理 [0]
```

模型可能一次说"我要同时查退款和运费"。串行处理会浪费它的并行意图（第 22 章会讲真正的并行执行）。

**细节 3：工具抛错要变成"观察结果"，不要抛给上层**

```python
try:
    out = str(by_name[call["name"]].invoke(call["args"]))
except Exception as e:
    out = f"TOOL_ERROR: {type(e).__name__}: {e}"    # 让模型看到并自己补救
```

如果你直接 `raise`，整次运行就死了。**Agent 的容错一半来自"让模型知道错了"**——它经常能换个参数重试成功。

---

## 4.4 ReAct 的边界：什么时候它不该用

ReAct 不是万能药。它的**本质是"走一步看一步"**，所以：

### ❌ 不适合：步骤可以预先确定的任务

> "把这份 PDF 转成 Markdown，然后切成 500 字一段，存进向量库。"

这有**确定的 3 步**，用 ReAct 是浪费——模型可能检查三遍才确认"真的完成了"，花 3 倍成本做一件不需要决策的事。

**该用 Workflow（第 5 章）。**

### ❌ 不适合：需要全局规划的多跳任务

> "调研 5 家竞品的定价策略，对比后给出建议。"

ReAct 会**一路往前走不回头**：查到第 3 家发现要换维度，它不会回去重查前两家。结果是 5 家用了 5 种口径，没法对比。

**该用 Plan-and-Execute（第 6 章）。**

### ❌ 不适合：需要验证自己是否正确

> "生成一段 SQL 并确保它对。"

ReAct 只"想下一步"，不"审上一步"。它会自信地生成一个错误 SQL 然后执行。

**该加 Reflection（第 7 章）或护栏（第 18 章）。**

### ✅ 适合：路径不确定、但每步都能验证

- 客服问答（可能查 1 次也可能查 3 次）
- 简单工具编排（查天气 + 算温差）
- 开放式探索（先看看有什么，再决定做什么）

**判据：如果你自己都不能预先写出步骤，ReAct 是对的。**

---

## 4.5 ReAct 的成本特征（必须知道的数字）

ReAct 的成本是**超线性**的，原因第 1 章已经算过：历史不断累加。

一个 3 步 ReAct 的 token 消耗（假设每题 30 token，每答 200 token）：

```
第 1 步：input ≈ 1,000（system + question）   output ≈ 200
第 2 步：input ≈ 1,200（+上一轮）             output ≈ 200
第 3 步：input ≈ 1,400（+上一轮+工具结果）    output ≈ 200
合计：input ≈ 3,600  output ≈ 600
```

对比"一次问答"：input ≈ 1,000，output ≈ 200。

**3 步 ReAct 的 input 是 3.6 倍，output 是 3 倍。** 如果模型从 2 步走到 6 步，成本翻的就不止 3 倍了——因为工具返回的内容也进历史。

这解释了为什么第 3 章的裁剪、第 10 章的上下文工程是**必需品而非优化项**。

---

## 4.6 💥 失败实验

### 实验 A：让模型输出"半个"格式

在 `demo_text_react.py` 的场景 A 里，把 `Action Input` 改成 `{"q": "退款"`（少一个右括号）。

**观察**：`json.loads` 抛什么异常？代码怎么处理的？工具收到了什么？

**你会看到**：它退回 `{"_raw": ...}`，然后工具返回"未检索到"——**又是一个静默失败**。

### 实验 B：去掉 `tool_call_id`

在 `react_native` 里删掉 `"tool_call_id": call["id"]`，然后问一个需要**并行两个工具**的问题。

**观察**：多数厂商的 API 会直接报错（提示 tool 消息必须对应 tool_call）。少数宽容的会让你运行，但结果可能错位。

**这个实验的意义**：它让你明白为什么"协议字段"比"文本解析"可靠——**协议会当场报错，文本解析只会默默变差**。

### 实验 C：把 ReAct 用在"确定 3 步"的任务上

写一个 ReAct，任务是"读 3 个文件并总结"。故意把 system prompt 写成 ReAct 风格。

**观察**：它是不是反复确认"我读完了吗"？步数是多少？比固定 Workflow 多花多少？

---

## 4.7 ✏️ 小练习

### 练习 1（必做）：给 ReAct 加"每步预算提示"

在每轮调用的 system 里追加：

```
剩余预算：{remaining_steps} 步
```

**验收**：同样的任务，步数是否下降？（这是第 10 章上下文工程的最小版本）

### 练习 2：把 ReAct 的 trace 接上第 2 章

用 `Tracer` 包住每次 `llm.invoke` 和每次工具调用。

**验收**：跑一次多步任务，能打印出完整调用树，并看出"哪个工具最慢"。

### 练习 3（进阶）：实现"工具选择错误"的自动纠正

当工具返回 `TOOL_ERROR` 时，追加一条明确的提示：

```
工具 {name} 报错：{err}。可选工具：{list}。请选择正确的工具或修正参数。
```

**验收**：构造一个"故意传错参数类型"的用例，看模型能否自我修复。

---

## 4.8 ⚠️ 常见坑

| 坑 | 现象 | 原因 |
|---|---|---|
| 忘记 append `ai` 消息 | 模型重复调用同一工具 | 历史里没有"我说过要调用"这条记录 |
| `tool_call_id` 丢失 | API 报错或结果错位 | 协议要求 tool 消息与 call 严格对应 |
| 工具报错直接 `raise` | 整次运行崩掉 | 应该转成 `TOOL_ERROR` 观察结果 |
| 只处理 `tool_calls[0]` | 并行调用丢失 | 要遍历全部 |
| 用 ReAct 做固定流程 | 成本翻倍、步数不稳 | 该用 Workflow |
| 没有 max_steps | 无限循环 | 见第 3 章 |

---

## 4.9 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 文本 ReAct（教学） | `code/common/react.py::TextReAct` | 对照实验 |
| 原生 tool_calls 版 | `code/common/react.py::react_native` | 第 5、6 章基础 |
| 带刹车的 ReAct | `code/common/react.py::SafeReAct` | 第 7、8、18、25 章 |

---

## 4.10 ✅ 验收

1. ReAct 的三个组成部分是什么？为什么它比"直接回答"贵？
2. 手写文本 ReAct 的三个结构性脆弱点分别是什么？
3. `tool_call_id` 为什么不能丢？丢了的症状是什么？
4. 什么任务不该用 ReAct？举两个例子。
5. 工具抛错时，正确的处理方式是什么？为什么？

**数字验收**：你的场景里，一次 3 步 ReAct 的成本是一次单轮问答的多少倍？

---

## 4.11 延伸阅读

- ReAct 原论文（2022）：理解它为什么在当时是突破
- 第 5 章：把"确定的步骤"换成 Workflow，成本立刻降下来
- 第 6 章：把"多跳任务"换成 Plan-and-Execute，质量立刻提上去

---

下一页：[第 5 章 Workflow：什么时候不该用 Agent](05-Workflow编排.md)
