# 第 17 章 ReAct：最流行的 Agent 范式，以及它的边界

> **这一章你会遇到什么坏事**
>
> 你照着一篇 2023 年的 ReAct 教程抄了 60 行代码，本地跑通了。换一个模型之后，它开始输出
> "我想先搜索一下退款政策"，而不是 `Action: search` —— 你的正则匹配不到，整个循环卡在原地空转。
>
> 更糟的是——**它没有报错**。日志一切正常，只是 token 悄悄变多了。三周后你才发现。

> **学完你能做到**
>
> 1. 用 20 行代码写出手写版 ReAct，说清它"在哪一步靠猜"
> 2. 用原生 `tool_calls` 重写同一个循环，成本降一半且失败可见
> 3. 判断一件任务**该不该**用 ReAct（本章给出 3 个反例）

---

## 17.0 先说明白五个词

这一章会出现五个新词。**先花 1 分钟看完这张表**，后面就顺了。

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **ReAct** | "Reasoning + Acting"：让模型**想一步、做一步、看结果**，再想下一步。就像你查资料时边查边改关键词 | 4.1 起 |
| **Observation（观察结果）** | 工具返回给模型的那段文字。模型下一轮的"输入素材" | 4.2 |
| **tool_calls** | 模型返回的**结构化字段**：`[{"name": "search", "args": {"q": "退款"}, "id": "call_1"}]`。不是文本，不用解析 | 4.3 |
| **tool_call_id** | 每个工具调用自带的编号。回填结果时**必须带回去**，否则模型对不上号 | 4.3 |
| **thrash（空转）** | 模型"以为换思路了"，实际在重复同样的动作（第 16 章讲过，本章会再遇到） | 4.4 |

> 还有三个名词后面才出现，这里先提一句，看到时不用慌：
> - **AgentExecutor**：框架 0.x 时代的老写法，本章 17.5 节会说明它为什么过时
> - **`agent_scratchpad`**：老写法里那个"手动拼给模型看的中间步骤字符串"，新写法不需要
> - **bind_tools**：把工具清单"挂"到模型上的动作，之后模型才知道有哪些工具可用

---

## 17.1 ReAct 到底是什么（一句话）

> **ReAct 就是：让模型交替地"想一步、做一步、看结果"，而不是一次把答案憋出来。**

一个循环长这样（这是模型内部的推理轨迹，不是代码）：

```
Thought: 用户问退款几天，我得先查政策
Action: search
Action Input: {"q": "退款"}
Observation: 退款政策：签收后 7 天内无理由退货……
Thought: 我知道了
Final Answer: 7 天内无理由退货。
```

**为什么它有效？** 模型不需要一次记全所有事实，它可以"边查边想"。

**为什么它有代价？** 每一步都是一次**完整的模型调用**，而且历史不断累加。3 步 ReAct 的成本是一次单轮问答的 3 倍以上（本章 17.6 节会算给你看）。

**注意上面那四个英文词**：Thought / Action / Action Input / Observation。这不是协议，**只是一段约定好的格式**。既然是格式，就一定会有人写错——这就是本章所有麻烦的来源。

---

## 17.2 先看一个具体的坏事：手写 ReAct 会怎么坏

你可能会想："ReAct 不就是个循环吗？我自己写。"

我们先真的写一遍，看看它会怎么坏。

💻 运行：`python code/ch17_react/step1_text_react.py`

核心逻辑只有这些：

```python
action = parse(raw, r"Action:\s*(.+)")                 # ← 靠正则抠
raw_input = parse(raw, r"Action Input:\s*(.+)")        # ← 靠正则抠

if not action:
    history += f"\n{raw}\nObservation: 格式错误，请严格使用 Thought/Action 格式。\n"
    continue                                            # ← 白花一整轮

try:
    args = json.loads(raw_input)                        # ← 靠 json 解析
except json.JSONDecodeError:
    args = {"_raw": raw_input}                          # ← 解析失败就瞎猜
```

**场景 A：模型完全守格式**（理想情况）

```
--- 第 0 轮，模型原文 ---
Thought: 需要查退款政策
Action: search
Action Input: {"q": "退款"}
  → Observation: 退款政策：签收后 7 天内无理由退货，15 天内可换货。

结果：ok=True steps=2
```

能跑通。**但这是你在替模型写代码**——它必须一个字符不差。

**场景 B：Action Input 写成自然语言**（最常见的失败）

```
--- 第 0 轮，模型原文 ---
Thought: 我需要查一下退款相关的资料。
Action: search
Action Input: 查询退款政策
  → Action Input 不是 JSON，退回 {'_raw': '查询退款政策'}
  → Observation: 未检索到相关内容
```

**这一轮彻底白费了。** 而且注意最后那行：工具返回的是"未检索到相关内容"——**一个看起来完全正常的返回值**。

模型不知道自己错了。它只会想："哦，这个库没有退款政策，我再搜一次。"

**三个结构性脆弱点：**

| 脆弱点 | 后果 | 为什么致命 |
|---|---|---|
| 参数靠字符串解析 | 模型一写自然语言就失效 | 模型天生喜欢写自然语言 |
| 动作靠正则匹配 | 忘写 `Action:` 就白跑一轮 | 一次调用就是一次计费 |
| **失败是静默的** | 日志里看不出异常，只是成本变高 | 你在账单上看到"怎么贵了"，却查不到"哪里错了" |

**第三条最要命。** 前两条会让你"一次没查成"，第三条会让你"三周不知道自己在漏钱"。

**所以现代做法换了一个思路：不让模型"写文本"，让它"填字段"。**

---

## 17.3 第三代：原生 tool_calls（10 行看懂）

### 一句话

> **tool_calls = 模型直接把"要调哪个工具、参数是什么"作为结构化的字段返回，不再写成文本让你解析。**

### 最小例子

💻 运行：`python code/ch17_react/step2_native_tools.py`

模型返回的东西从"一段文字"变成"一个对象"：

```python
# 老写法（文本）
"Thought: 需要查退款政策\nAction: search\nAction Input: {\"q\": \"退款\"}"
#   ↑ 你还得写正则去抠

# 新写法（tool_calls）
Reply(tool_calls=[{"name": "search", "args": {"q": "退款"}, "id": "call_1"}])
#   ↑ args 已经是字典，直接用
```

整个循环只有 12 行：

```python
for step in range(max_steps):
    ai = llm.invoke(messages)
    messages.append(ai)                       # ① 先记下模型说的话

    if not ai.tool_calls:                     # ② 没有工具调用 = 明确的结束信号
        return {"ok": True, "answer": ai.content}

    for call in ai.tool_calls:                # ③ 一次可能多个，必须循环
        result = tools[call["name"]](call["args"])
        messages.append({"role": "tool", "content": str(result),
                         "tool_call_id": call["id"]})   # ④ 必须带回 id
```

**真实输出：**

```
场景 A：正常的一次 ReAct 循环
ok=True steps=2
answer=签收后 7 天内无理由退货，15 天内可换货。

场景 B：模型一次返回两个 tool_calls（并行意图）
ok=True steps=2
answer=退款 7 天，运费不退。
```

**就这四步。** 你在任何框架里看到的 agent 循环，底层都是这四行。

### 三个必须知道的细节

**细节 1：`tool_call_id` 不能丢**

模型返回的是：

```python
{"name": "search", "args": {"q": "退款"}, "id": "call_abc123"}
```

你回填结果时**必须带回 id**：

```python
{"role": "tool", "content": "...", "tool_call_id": "call_abc123"}
```

不带的话，多工具并行时模型会把结果**张冠李戴**。

**这是新手最常犯的错，而且症状很诡异：回答内容看起来对，但因果关系崩了**（它把"退款政策"当成"运费政策"来回答）。

**细节 2：一次可能返回多个 tool_calls**

```python
for call in ai.tool_calls:      # ← 必须循环，不能只处理 [0]
```

模型可能一次说"我要同时查退款和运费"。只处理 `[0]` 会**静默丢弃**第二个调用，模型下一轮发现"我明明调了却没结果"，要么重调（浪费钱），要么瞎编。

**细节 3：工具抛错要变成"观察结果"，不要抛给上层**

```python
try:
    out = str(tools[call["name"]](call["args"]))
except Exception as e:
    out = f"TOOL_ERROR: {type(e).__name__}: {e}"    # 让模型看到并自己补救
```

如果你直接 `raise`，整次运行就死了。**Agent 的容错一半来自"让模型知道错了"**——它经常能换个参数重试成功（17.4 节有实测）。

### ✏️ 停下来想一想

原生 `tool_calls` 解决了"解析失败"，但**没有解决"跑飞"**：

- 模型可以一直调工具（没有步数上限）
- 模型可以用同样的参数调 10 次（没有指纹）
- 模型每一步都很贵（没有成本上限）

**协议让失败可见，但不让失败变少。** 这就是下一节。

---

## 17.4 从"能跑"到"跑得住"（阶梯最后一格）

💻 运行：`python code/ch17_react/step3_guarded_react.py`

这一级只做一件事：**把第 16 章的四道刹车接到 `tool_calls` 循环上。**

```python
while True:
    hit = budget.exhausted()                  # ① 预算
    if hit:
        return {"stop": f"budget:{hit}"}
    ai = llm.invoke(messages)
    budget.steps_used += 1
    ...
    for call in ai.tool_calls:
        why = guard.check(call["name"], call["args"])   # ② 指纹
        if why:
            messages.append({"role": "tool", "content": f"BLOCKED: {why}",
                             "tool_call_id": call["id"]})
            continue                                       # ← 不 break，给模型换路的机会
        try:
            out = str(tools[call["name"]](call["args"]))
        except Exception as e:                             # ③ 工具异常降级为观察结果
            out = f"TOOL_ERROR: {type(e).__name__}: {e}"
        messages.append({"role": "tool", "content": out, "tool_call_id": call["id"]})
```

**真实输出：**

```
场景 A：模型反复用同样的参数查询（thrash）
stop=budget:steps(8)  steps=8  answer=(无)
→ 每个相同调用都被拦（BLOCKED 交回模型），但脚本模型不会自己收手，
  所以最后还是被步数预算停掉 —— 这正是「刹车要四道都有」的原因。

场景 B：工具抛异常，模型自己换成对的参数
stop=answer  steps=3  answer=签收后 7 天内无理由退货，15 天内可换货。
```

**场景 B 是这一章最值钱的 3 行输出。** 它证明：

> 工具报错**不是终点**。把错误当作 Observation 喂回去，模型下一轮就修好了参数。

对比一下两种处理：

| 处理方式 | 结果 | 成本 |
|---|---|---|
| `raise` 出去 | 整次运行崩掉，用户看到 500 | 已花的钱全浪费 |
| 转成 `TOOL_ERROR` 观察结果 | 模型换参数重试，成功率很高 | 多一次工具调用 |

---

## 17.5 核心实现逐行解释（那 20 行里最关键的部分）

以 `code/common/react.py` 里的 `react_native` 为例：

```python
def react_native(llm, tools, question, max_steps=6):
    llm_with_tools = llm.bind_tools(tools)     # ① 告诉模型"你有哪些工具"
    by_name = {t.name: t for t in tools}       # ② 名字 → 函数，备用查表
    messages = [("user", question)]            # ③ 对话历史（唯一的"状态"）

    for step in range(max_steps):              # ④ 步数上限（第 16 章的刹车一）
        ai = llm_with_tools.invoke(messages)   # ⑤ 一次完整模型调用
        messages.append(ai)                    # ⑥ 必做：把模型的话记进历史
        if not ai.tool_calls:                  # ⑦ 结束信号
            return {"answer": ai.content, "steps": step + 1, "ok": True}

        for call in ai.tool_calls:             # ⑧ 遍历，不只 [0]
            fn = by_name[call["name"]]
            result = fn.invoke(call["args"])
            messages.append({"role": "tool", "content": str(result),
                             "tool_call_id": call["id"]})   # ⑨ id 必回填
```

**三个设计取舍（为什么这么写）：**

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| **结束信号靠"没有 tool_calls"** | 协议字段天然有空/非空 | 用文本时得判断"有没有写 Final Answer"，模型一换措辞就失效 |
| **历史用 `messages` 列表** | 唯一的可变状态 | 把状态散在多个变量里，恢复/持久化（第 22 章）时就痛苦了 |
| **异常转成观察结果** | `except → TOOL_ERROR` | 直接抛会让整次运行死亡，且模型永远学不会"我刚才参数错了" |

### ⚠️ 一个必须知道的坑：忘记 append 模型回复

```python
ai = llm_with_tools.invoke(messages)
# ❌ 忘了 messages.append(ai)
for call in ai.tool_calls:
    messages.append({"role": "tool", ...})
```

**症状：模型会反复调用同一个工具。** 因为历史里没有"我说过要调用"这条记录，它看到一条孤立的工具结果，不知道这是自己刚查的。

这个 bug 极难从输出看出来（模型看起来"很想确认"），必须看 trace（第 38 章）才发现——**历史里缺一条 assistant 消息**。

---

## 17.6 ReAct 的成本特征（必须知道的数字）

ReAct 的成本是**超线性**的，因为历史不断累加。

一个 3 步 ReAct 的 token 消耗（假设每题 30 token，每答 200 token，每次工具返回 300 token）：

```
第 1 步：input ≈ 1,000（system + question）            output ≈ 200
第 2 步：input ≈ 1,200（+上一轮）                       output ≈ 200
第 3 步：input ≈ 1,700（+上一轮 +工具结果 300）         output ≈ 200
合计：input ≈ 3,900   output ≈ 600
```

对比"一次问答"：input ≈ 1,000，output ≈ 200。

**3 步 ReAct 的 input 是 3.9 倍，output 是 3 倍。**

如果模型从 2 步走到 6 步，成本翻的就不止 3 倍——因为**工具返回的内容也进历史**，而工具返回往往比问题长 10 倍。

**这解释了两件事：**

1. 为什么第 16 章的上下文裁剪是必需品，而非优化项
2. 为什么下一节要说"很多任务其实不该用 ReAct"

---

## 17.7 ReAct 的边界：什么时候它不该用

ReAct 不是万能药。它的**本质是"走一步看一步"**，所以：

### ❌ 不适合一：步骤可以预先确定的任务

> "把这份 PDF 转成 Markdown，然后切成 500 字一段，存进向量库。"

这有**确定的 3 步**。用 ReAct 是浪费——模型可能检查三遍才确认"真的完成了"，花 3 倍成本做一件不需要决策的事。

**该用 Workflow（第 18 章）。**

### ❌ 不适合二：需要全局规划的多跳任务

> "调研 5 家竞品的定价策略，对比后给出建议。"

ReAct 会**一路往前走不回头**：查到第 3 家发现要换维度，它不会回去重查前两家。结果是 5 家用了 5 种口径，没法对比。

**该用 Plan-and-Execute（第 19 章）。**

### ❌ 不适合三：需要验证自己是否正确

> "生成一段 SQL 并确保它对。"

ReAct 只"想下一步"，不"审上一步"。它会自信地生成一个错误 SQL 然后执行。

**该加 Reflection（第 20 章）或护栏（第 32 章）。**

### ✅ 适合：路径不确定、但每步都能验证

- 客服问答（可能查 1 次也可能查 3 次）
- 简单工具编排（查天气 + 算温差）
- 开放式探索（先看看有什么，再决定做什么）

**判据：如果你自己都不能预先写出步骤，ReAct 是对的。**

---

## 17.8 ⚠️ 关于 `AgentExecutor`：你在别处看到的写法可能已经过时

如果你搜到任何一篇"ReAct + 某个框架"的教程，它大概率长这样：

```python
# ❌ 0.x 的写法，本书全程不用
from langchain.agents import AgentExecutor, create_react_agent
agent = create_react_agent(llm, tools, prompt)   # 内部靠 agent_scratchpad 拼文本
executor = AgentExecutor(agent=agent, tools=tools, max_iterations=5)
```

**为什么它是上一代：**

| 维度 | `AgentExecutor`（0.x） | 原生 `tool_calls`（1.x） |
|---|---|---|
| 动作怎么表达 | 文本 + `agent_scratchpad` 拼接 | 协议字段 `tool_calls` |
| 参数怎么落 | prompt 里教模型写 JSON，再解析 | 模型直接返回字典 |
| 失败形态 | 静默（解析不出来就重试一轮） | 显式（结构不对当场报错） |
| 并行调用 | 需要额外配置 | 天然支持一个消息多个调用 |
| 是否需兼容包 | 需要 `langchain-classic` | 不需要 |

**本书只教第三种（原生 `tool_calls`）。** 你在旧教程里看到的 `agent_scratchpad`、`create_react_agent`、`max_iterations`，都属于上一代——**它们还能跑，但你学的是要被淘汰的东西**。

（第 30 章会讲 1.x 里替代它的 `create_agent`，它返回的就是一个能 `invoke` 的图。）

---

## 17.9 三个小练习（从易到难）

> 💡 **这一节是练习，不是阅读材料**，可以先挑着做。

### 练习 1（5 分钟）：把一个参数改错，看失败长什么样

在 `step2_native_tools.py` 里，把 `search` 的 `args.get("q")` 改成 `args["q"]`，然后让剧本里某个调用**不带 q**。

**观察**：抛的是什么异常？循环停在哪一行？

**验收**：能说出"为什么这个错误应该被 `except` 掉，而不是让它往上冒"。

### 练习 2（20 分钟）：把 ReAct 的 trace 接上第 38 章

用第 38 章的 `Tracer` 包住每次 `llm.invoke()` 和每次工具调用：

```python
with tracer.span("模型调用", model="fake"):
    ai = llm.invoke(messages)
with tracer.span("工具调用", name=call["name"]):
    result = tools[call["name"]](call["args"])
```

**验收**：跑一次多步任务，能打印出完整调用树，并回答"最慢的是哪一步"。

### 练习 3（15 分钟）：💥 故意破坏它

**实验 A：去掉 `tool_call_id`**

在 `step2` 的 `react()` 里删掉 `"tool_call_id": call["id"]`，跑场景 B（并行两个工具）。

**观察**：结果还正确吗？把剧本改成"两个工具返回不同内容、答案依赖两者"，看看会不会张冠李戴。

**结论**：协议要求 tool 消息与 call 严格对应。**少了 id，多调用场景下因果关系就崩了。**

---

**实验 B：只处理 `tool_calls[0]`**

把 `for call in ai.tool_calls:` 改成 `call = ai.tool_calls[0]`。

**观察**：场景 B 的答案是什么？第二个工具的结果去哪了？

**结论**：**静默丢弃**。没有异常、没有日志，只是少了点东西。

---

**实验 C：工具异常直接 `raise`**

把 `except Exception as e: out = f"TOOL_ERROR: ..."` 改成 `raise`，跑场景 B（第一次调用缺参数）。

**观察**：循环还能继续吗？模型有没有机会修正？

**结论**：**一次参数错误 = 整次任务失败**。而在真实系统里，参数错误占工具失败的多数。

---

## 17.10 常见错误速查（💡 可以先跳过，当字典查）

> 💡 **这一节可以先跳过。** 遇到具体症状再回来查。

| 症状 | 原因 | 修法 |
|---|---|---|
| 模型反复调同一工具 | 忘了 `messages.append(ai)` | 补上 |
| 并行调用时答案张冠李戴 | 没回填 `tool_call_id` | 补上 `tool_call_id` |
| 第二个工具调用"消失了" | 只处理了 `tool_calls[0]` | 遍历全部 |
| 一次工具报错整次运行崩掉 | 直接 `raise` | 转成 `TOOL_ERROR` 观察结果 |
| 用 ReAct 做固定流程，成本翻倍 | 选错了范式 | 用 Workflow（第 18 章） |
| 循环不停 | 没有 `max_steps` | 见第 16 章 |
| 文本 ReAct "看起来能跑"但很贵 | 解析失败静默重试 | 换原生 `tool_calls` |
| 模型输出 `Final Answer` 但没被识别 | 正则太严 / 模型换了措辞 | 用结构化结束信号 |

---

## 17.11 章末自测

合上书，用自己的话回答：

1. **ReAct 的三个组成部分是什么？** （提示：想、做、看）
2. **手写文本 ReAct 的三个结构性脆弱点？** （提示：参数、动作、失败可见性）
3. **`tool_call_id` 为什么不能丢？** （提示：多调用时怎么知道哪个结果对应哪个请求）
4. **工具抛错时正确的处理方式？** （提示：谁会因此受益）

**四题都能用自己的话说清楚 → 本章过关。**

如果你能再回答这题，说明你真的懂了：

5. **为什么"文本 ReAct 能跑通"不代表它是好方案？** （提示：失败的时候会发生什么？）

---

## 17.12 可选补课：ReAct 论文的原始设定与"为什么它当年是突破"

> ⚠️ **这一节可以先跳过。** 等你面试被问到"Why ReAct"时再看。不看这一节，你照样能写出可用的循环。
2022 年的 ReAct 论文解决的是一个真问题：**当时的模型不会用工具。**

当时的做法有两种，各有硬伤：

| 做法 | 硬伤 |
|---|---|
| 纯推理（Chain-of-Thought） | 会**编造**事实，因为它没有任何外部信息 |
| 纯行动（只调工具） | 没有"想"这一步，不知道该调哪个、调几次 |

ReAct 的贡献是**把它们交替起来**：想 → 调 → 看 → 想，让推理被事实校正。

**所以它的核心价值从来不是"格式"**，而是"让推理和环境交替"。这也是为什么现代实现可以完全换掉格式（文本 → `tool_calls`），而 ReAct 的思想一点没变。

**面试时的正确说法：**

> "ReAct 的思想是推理与行动交替；文本格式是当年的实现手段，已经被淘汰；
> 现在用原生 tool_calls 实现同一个思想，好处是解析可靠、支持并行、失败可见。"

**这句话比背格式有用得多。**

---

## 17.13 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 文本 ReAct（教学对照） | `code/ch17_react/step1_text_react.py` | 讲"为什么被淘汰"时的证据 |
| 原生 tool_calls 版 | `code/ch17_react/step2_native_tools.py` | 循环骨架，第 5–9 章都从这里派生 |
| 带刹车的 ReAct | `code/ch17_react/step3_guarded_react.py` | 第 20/21/34/43 章的基础形态 |
| 生产版（框架模型） | `code/common/react.py::SafeReAct` | 接真实模型的版本，含 token 计费 |

---

## 17.14 ✅ 验收

1. 你能用 20 行写出手写 ReAct，并指出"哪一行靠猜"
2. 你的循环里，`if not ai.tool_calls` 是**唯一**的结束信号，没有靠正则判断
3. 你回填工具结果时带了 `tool_call_id`
4. 你遍历了 `ai.tool_calls`，而不是只取 `[0]`
5. 工具异常被转成 `TOOL_ERROR` 观察结果，而不是 `raise`

**数字验收：** 你的场景里，一次 3 步 ReAct 的 input token 是一次单轮问答的多少倍？

> 参考值（本章估算）：**3.9 倍**（1,000 → 3,900）。
> 如果你的实测远高于这个数，说明你的**工具返回太长**——去看第 16.6 节的裁剪和第 29 章的上下文工程。

---

下一页：[Workflow：什么时候不该用 Agent](18-Workflow编排.md)
