# 第 44 章 LangChain（二）：输出解析、结构化输出与 LCEL

> **这一章你会遇到什么坏事**
> 你让模型"返回 JSON"，它回了这么一段：
> `好的，这是结果：{"decision": "可退", "days_used": 3}`
> 你的 `json.loads()` 直接抛异常。你加了一句"请只返回 JSON"，它改成了 ` ```json ... ``` `——还是不能解析。
> 你终于加了个正则把大括号抠出来，上线一周后它开始返回 `"decision": "可以退"`（枚举值变了），你的 `if d["decision"] == "可退"` 全都不进分支。
>
> 更糟的是——**这两种失败你的监控都看不见**：前者抛异常被你 catch 掉了，后者不抛异常，只是**安静地答错**。

> **学完你能做到**
> 1. 用三种解析器把"模型说的话"变成程序对象，并说清它们的差别（43.3）
> 2. 用 Pydantic 定义输出 schema，让"枚举错了"变成**当场可见的错误**（43.4）
> 3. 校验失败时带错误信息重试一次，把失败率压下来（43.5）
> 4. 用 `|` 把 prompt、model、parser 接成一条链，并给它加重试、降级、并行、分支（43.6）

---

## 44.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **解析器（Parser）** | 一个"把模型的文字翻译成程序数据"的小零件，翻译不了就报错 | 43.3 |
| **`StrOutputParser`** | 最笨的解析器：只把 `.content` 原样拿出来 | 43.3 |
| **`JsonOutputParser`** | 能从"正文里夹着 JSON"或"```json 代码块"里抠出字典 | 43.3 |
| **`PydanticOutputParser`** | 最严的：按你定义的 schema 校验，**不合规就抛异常** | 43.3 |
| **Pydantic / `BaseModel`** | Python 里定义"数据长什么样"的库，能自动校验类型和取值 | 43.3 起 |
| **`with_structured_output`** | 让模型"以工具调用形式"返回 JSON，框架自动帮你转对象 | 43.5 |
| **LCEL** | 用 `\|` 把 Runnable 串起来：`prompt \| model \| parser` | 43.6 |
| **`Runnable`** | "可以被调用"的东西的统称，都有 `invoke/stream/batch` 三件套 | 43.6 |

> 还有三个后面才出现，先提一句：
> - **`RunnableParallel`**：同时跑几条链，结果合并成 dict（43.7）
> - **`RunnableBranch`**：按条件走不同分支，就是 if/elif/else（43.7）
> - **`configurable_fields`**：把参数变成"运行时可替换"，做 A/B 和多租户用（43.7）

---

## 44.1 先看一个具体的坏事：五种输出，只有一种能解析

真实场景：售后 Agent 要输出一个"退款判定"，字段是 `decision`（可退/不可退/需人工）、`days_used`、`reason`。

模型实际会返回什么？我们收集了五种最常见的形态：

```
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\lc\ch43\step1_parsers.py
```

真实输出（段 ①）：

```
① 五种真实输出，能直接 json.loads 的有几个？
  1. ✓ 能解析   '{"decision": "可退", "days_used": 3, "reason": "7 天无'
  2. ✗ 不能解析 '```json\n{"decision": "可退", "days_used": 3, "reason'
  3. ✗ 不能解析 '判定结果如下：\n{"decision": "可退", "days_used": 3, "reason'
  4. ✗ 不能解析 'decision: 可退, days_used: 3'
  5. ✗ 不能解析 '我认为可以退。'

  → 1/5 能直接解析。这就是「解析器」存在的理由。
```

**结论：你不是"提示词没写好"，你是"把模型当成一台严格的 JSON 机器了"。**

更糟的是第 5 种：`我认为可以退。`——**它不是格式错误，它是模型拒绝按格式回答**。
如果你的代码用默认值兜底（`decision = d.get("decision", "需人工")`），这个 case 会**静默变成"需人工"**，你以为它在工作。

---

## 44.2 为什么"提示词里加一句请返回 JSON"不够

你可能会想：那我加一句"只返回 JSON，不要解释"不就行了？

这句话**有用，但不保证**。原因有三个，全都和模型本身有关：

| 原因 | 具体表现 | 提示词能解决吗 |
|---|---|---|
| **模型的输出是逐 token 生成的** | 它先写了"好的"，再写 JSON；你拦不住已经写出去的字 | 不能 |
| **JSON 不是天然格式** | 模型只保证"像 JSON"，不保证"合法 JSON"（多一个逗号、少一个引号都很常见） | 部分能 |
| **语义错误不是语法错误** | `"decision": "可以退"` 是**合法 JSON**，但不是你要的枚举值 | **完全不能** |

**所以我们需要一个"校验层"。这个层两个作用：既做格式容错（把代码块抠出来），又做语义校验（枚举/类型/必填）。**

这个层就是**输出解析器**。

> 💥 **失败实验 1：看一下"兜底默认值"有多危险**
> 把 `step1_parsers.py` 的 ③ 里那条 `少了字段` 的用例改成这样：
> ```python
> raw = '{"decision": "可退"}'
> print(Refund.model_validate_json(raw))
> ```
> 你会看到它抛 `ValidationError`（因为 `days_used` 是必填）。**这很好。**
> 现在把 `days_used: int = Field(...)` 改成 `days_used: int = 0`（给个默认值），重跑。
> **它不报错了，返回 `days_used=0`。**
>
> 这就是线上最常见的 bug 形态：**你给字段加了默认值"防崩"，结果它把"模型忘了填"伪装成"用户没用过"。**
> 后面的退款计算就按 0 天算——多退了一笔钱。

---

## 44.3 三个解析器到底是什么（10 行代码看懂）

### 一句话

> **解析器 = 一个 `parse(text)` 函数，把字符串变成你想要的东西，变了形就抛 `OutputParserException`。**

三个常用解析器，是"从严到松"的三个档次：

| 解析器 | 它做什么 | 什么时候用 |
|---|---|---|
| `StrOutputParser` | 一个字都不改，直接返回 `.content` | 只要文本（聊天、摘要） |
| `JsonOutputParser` | 抠出 JSON → `dict`（会处理代码块、前后废话） | 要字段，但可以接受"类型不严" |
| `PydanticOutputParser` | 抠出 JSON → 按 schema 校验 → **模型实例** | 要**保证**字段合法 |

### 最小例子

同一个输入 ` ```json\n{...}\n``` `，三个解析器的真实结果（`step1` ②）：

```
  StrOutputParser      → '```json\n{"decision": "可退", "days_used": 3, "reason": "7 天'
                          （只是把 content 原样拿出来，不做校验）
  JsonOutputParser     → {'decision': '可退', 'days_used': 3, 'reason': '7 天无理由'}
                          （能从 ```json 代码块里抠出 JSON）
  PydanticOutputParser → decision='可退' days_used=3 reason='7 天无理由'
                         type = Refund
```

**差别在哪？** 看 `type` 那一行：`PydanticOutputParser` 返回的是 **`Refund` 实例**，不是 dict。
这意味着 `refund.decision` 是 IDE 能补全的，而 `refund["decision"]` 拼错了要到运行时才发现。

### 把 schema 定义成一个类（这就是"输出契约"）

```python
from typing import Literal
from pydantic import BaseModel, Field

class Refund(BaseModel):
    decision: Literal["可退", "不可退", "需人工"]     # ← 枚举：写错就是错
    days_used: int = Field(description="已使用天数")   # ← 类型：字符串"三天"会被拒
    reason: str = Field(max_length=60, description="一句话结论依据")  # ← 长度
```

**注意 `Literal`**：这是全章最重要的一个词。它把"模型写了个近义词"从**运行时逻辑错误**变成**解析时的异常**。
你在第 6 章手写过"三层解析"，这里是框架版的同一件事。

### Pydantic 还能告诉你"完整的格式要求"

```python
p = PydanticOutputParser(pydantic_object=Refund)
print(p.get_format_instructions())
```

真实输出（节选）：

```
The output should be formatted as a JSON instance that conforms to the JSON schema below.
As an example, for the schema {"properties": {"foo": {...}}} ...
```

**这段文字可以直接塞进提示词**，比你自己写"请返回 JSON，字段有..."严谨得多。

### ✏️ 停下来想一想

`PydanticOutputParser` 返回一个 `Refund` 对象，看起来很美。

**但如果模型返回的是 `{"decision": "可退", "days_used": 3, "reason": "7 天无理由", "extra": "随便加的"}`——多了一个 `extra` 字段，会怎样？**

（提示：Pydantic v2 默认 `extra="ignore"`。想想这对"模型开始乱加字段"这件事是好事还是坏事。）

---

## 44.4 从"能解析"到"能自愈"（阶梯代码 step1 / step2 / step3）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_parsers.py` | 三种解析器 + 校验失败长什么样 | — |
| step2 | `step2_lcel.py` | LCEL：`\|` 把三步接成一条链 | step1 里三步写三行，不是整体 |
| step3 | `step3_composition.py` | 并行 / 分支 / 重试 / 降级 / 配置 | step2 的直线链只够"一问一答" |

### step1：解析器与失败形态

痛点一句话：**`json.loads` 只认得"纯 JSON"，而模型很少给纯 JSON。**

💻 `python code/framework/lc/ch44/step1_parsers.py`

真实输出（段 ③，这段最重要）：

```
  枚举值写错      → OutputParserException: Failed to parse Refund from completion {"decision": "可以退", ...
  类型写错       → OutputParserException: Failed to parse Refund from completion {"decision": "可退", "days_used": "三天", ...
  少了字段       → OutputParserException: Failed to parse Refund from completion {"decision": "可退"}. Got: 2 validation errors for ...
```

**三种错误，同一个出口。** 这就是我们要的效果：**错误提前到"能看见的地方"。**

解析器**不修**数据。它只做一件事：**把"模型给了不合规的东西"变成"现在就知道"**。

### step2：LCEL —— 三步接成一条链

痛点一句话：**手写三步，没法统一重试、计费、流式。**

💻 `python code/framework/lc/ch44/step2_lcel.py`

真实输出（段 ①）：

```
  手写版第一步返回：AIMessage（不是字符串！）
  手写版最终结果  ：'token 是模型切分文本的最小单位。'
  LCEL  ：'token 是模型切分文本的最小单位。'
  链的类型 = RunnableSequence
```

**差别不只在"少写两行"。** 关键在于：`chain` 本身是一个 `Runnable`，所以它自动获得三件套（段 ②）：

```
  stream：
    向量是把文本变成一串数字。
  batch（3 个输入一次提交，返回顺序与输入一致）：
    ['甲。', '乙。', '丙。']
```

你写 `a | b | c`，得到的是一个新的 Runnable。**这就是 LCEL 的全部。**

### step3：给链加上工程能力

痛点一句话：**直线链只够"一次问一次答"，真实业务要并行、分支、重试、降级、切换配置。**

💻 `python code/framework/lc/ch44/step3_composition.py`

真实输出（段 ①～⑥ 节选）：

```
① RunnableParallel：三个子问题同时问
  输出 dict = {'summary': '摘要内容', 'keywords': '词表', 'sentiment': '中性'}
  耗时 = 39.6 ms

② RunnablePassthrough.assign：在流里加字段，不丢原字段
  {'q': '能退吗', 'rewrite': '改写后的问题', 'answer': '答案'}

③ RunnableBranch：按条件走不同分支
  我要退款       → '走退款流程'
  物流到哪了      → '走物流流程'
  你们公司在哪     → '转人工'

④ with_retry：失败自动重试（不重试会直接抛给用户）
  结果 = '第三次成功'，共调用 3 次

⑤ with_fallbacks：主模型挂了，自动换备胎
  结果 = '备用模型的回答'
```

这一级解决了什么：**一条链能扛住"模型抖一下""主模型挂了""按租户换配置"三种真实情况。**

---

## 44.5 核心实现（逐行解释）

这一节把 `step1_parsers.py` 里"带错误重试"的 20 行逐行拆开——**这是全章最有工程价值的一段**。

```python
def parse_with_repair(max_try: int = 2) -> Refund:
    prompt_extra = ""                                  # ①
    for attempt in range(1, max_try + 1):              # ②
        raw = call_model(attempt)                      # ③
        try:
            return p.parse(raw)                        # ④
        except OutputParserException as e:
            prompt_extra = f"上次输出不合法：{str(e).splitlines()[0]}"   # ⑤
            print(f"    第 {attempt} 次失败 → 反馈给模型：{prompt_extra[:60]}")
    raise RuntimeError("两次都没修好")                  # ⑥
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | 准备一段"给模型的错误反馈" | 不反馈错误，模型第二次还会犯同样的错 |
| ② | **限制重试次数** | 无限重试 = 死循环 + 账单爆炸（第 16 章） |
| ③ | 调用模型（真实项目要带上 ① 的反馈） | 只重试不改提示，等于赌运气 |
| ④ | 解析成功就直接返回 | —— |
| ⑤ | **把错误原文的前一行反馈给模型** | 只说"错了"，模型不知道错在哪 |
| ⑥ | 两次都失败就抛 | 返回默认值 = 把问题藏起来（见 43.2 失败实验） |

真实输出：

```
④ 校验失败之后怎么办：带错误信息重试（离线模拟）
    第 1 次失败 → 反馈给模型：上次输出不合法：Failed to parse Refund from completion {"decision":
  最终结果 = decision='可退' days_used=3 reason='7 天无理由'
  → 代价：多一次调用。收益：把 25% 的失败率降到接近 0（第 6 章实测 25%→75%）
```

**三个设计取舍**

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 失败后重试 vs 返回默认值 | **重试，失败率超阈值就报错** | 默认值会静默污染业务数据 |
| 反馈整个异常 vs 反馈一行 | **只反馈前一行** | 整段堆栈塞进提示词会撑爆上下文，而且模型看不懂堆栈 |
| 重试几次 | **2–3 次**（成本可控） | 5 次以上：成本线性涨，收益递减 |

### ⚠️ 一个必须知道的坑：`with_structured_output` 不是"保证"

很多人以为用了 `with_structured_output`（或者绑定 schema 的工具调用）就"一定有合法数据"。**不是。**

它做的事其实是（`step1` ⑤）：

```
    model.bind_tools([schema], tool_choice=schema.__name__)  →  读 tool_calls[0].args
```

也就是"让模型以工具调用形式返回 JSON"+"自动帮你看字段"。**好处**是去掉了"正文里夹一段 JSON"的解析风险；
**代价**是：

1. 模型仍可能**不调用工具**（尤其小模型、或者提示词里有冲突指令）；
2. 参数仍可能**违反 schema**（枚举写近义词、必填漏填）；
3. 某些 provider 的"严格模式"有自己的限制（不支持嵌套 `$ref`、不支持部分格式）。

所以：**校验照做，重试照写。** `with_structured_output` 减少的是「格式灾难」，不是「语义错误」。

> 💥 **失败实验 2：把枚举放宽，看错误怎么"消失"**
> 把 `Refund.decision` 从 `Literal["可退", "不可退", "需人工"]` 改成 `str`，重跑 `step1` ③。
> 三条错误里"枚举值写错"那条**不再报错**，直接返回 `decision='可以退'`。
>
> 现在问自己：**线上哪一处会因为这个"不报错"而算错钱？**
> 答案是所有 `if decision == "可退"` 的分支——全部走 else。**这就是"放宽校验"的代价：错误从解析层转移到了业务层，而业务层没有异常。**

---

## 44.6 用起来：三个问题 2 分钟答完

💻 `python code/framework/lc/ch44/step3_composition.py`

### 问题 ①：怎么让三个子任务同时跑？

```python
from langchain_core.runnables import RunnableParallel

parallel = RunnableParallel(
    summary=prompt_summary | model | parser,
    keywords=prompt_keywords | model | parser,
    sentiment=prompt_sentiment | model | parser,
)
out = parallel.invoke({"doc": "屏幕有划痕"})
# out = {'summary': ..., 'keywords': ..., 'sentiment': ...}
```

**结论**：`RunnableParallel`（或直接写一个 dict 字面量）就是 `map`。三条链拿到同一个输入，各自取自己需要的键。

### 问题 ②：怎么让"中途多算一步"而不丢原来的输入？

```python
from langchain_core.runnables import RunnablePassthrough

step = RunnablePassthrough.assign(
    rewrite=prompt_rewrite | model | parser      # 用 {q} 算出 rewrite
).assign(
    answer=prompt_answer | model | parser        # 用 {rewrite} 算出 answer
)
step.invoke({"q": "能退吗"})
# {'q': '能退吗', 'rewrite': ..., 'answer': ...}
```

**结论**：`assign` 的右侧能读左边**已经算出的字段**。这就是"检索 → 改写 → 回答"这种多步管线的标准写法。

### 问题 ③：怎么让"同一份代码"跑两种配置？

```python
chain = prompt | model | parser
r = chain.with_config(tags=["tenant:acme", "ab:prompt-v2"]).invoke({"q": "能退吗"})
```

**结论**：`tags` / `metadata` 会随调用上报到 LangSmith / LangFuse（第 53 章），这是"按租户 / 按 prompt 版本切分指标"的**唯一可靠办法**。

### 🎯 到这里，你已经掌握了"把模型输出变成可用数据"

| 能力 | 在哪一节 |
|---|---|
| 三种解析器的分工 | 43.3 |
| Pydantic schema + `Literal` | 43.3 |
| 校验失败带反馈重试 | 43.5 |
| LCEL 三件套（invoke/stream/batch） | 43.4 step2 |
| 并行 / 分支 / 重试 / 降级 / 配置 | 43.6 |

**剩下的都是"把这些零件接上 Agent"（第 44、45 章）。**

---

## 44.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个约束，观察变化

把 `Refund.reason` 的 `max_length=60` 改成 `max_length=10`，重跑 `step1` ②。
**验收标准**：你需要能说出"这个错误在哪一行抛出来的，属于格式错误还是语义错误"。

### 练习 2（20 分钟）：接到你自己的项目上

给你的项目里**任意一个**"让模型返回 JSON"的地方加上 Pydantic 校验。

**最低要求清单**：
- [ ] 所有"枚举型"字段改成 `Literal`
- [ ] 所有"金额/数量"字段加 `gt=0` 或 `ge=0`
- [ ] 解析失败时**不再**用默认值兜底
- [ ] 加一条测试：故意喂一个坏 JSON，断言抛 `OutputParserException`

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：让模型返回"合法但错"的 JSON。**

把 `step1` 的 `bad_cases` 加一条：

```python
"数量是负数": '{"decision": "可退", "days_used": -5, "reason": "7 天"}',
```

观察：**它不会报错**（`int` 接受 -5）。结论：**类型校验不够，业务约束要自己加**（`Field(ge=0)`）。

**实验 B：把重试改成"无限重试"。**

```python
for attempt in itertools.count(1):     # ← 危险的写法
```

然后让 `call_model` 永远返回错的那一版。观察：**它永远不退出。** 结论：**这就是第 16 章"循环失控"的微观版本**。

**实验 C：`with_fallbacks` 能不能兜住"答得不好"？**

把 `step3` ⑤ 的 `primary` 改成"永远返回'不知道'"（不抛异常）。观察：**fallback 不触发**。
结论：**`with_fallbacks` 只接"抛异常"，不接"答得差"。质量兜底要靠评测（第 40、41 章）。**

---

## 44.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `OutputParserException: Failed to parse` | 模型输出不是合法 JSON | 先用 `JsonOutputParser` 容错，再上 Pydantic |
| `ValidationError: 2 validation errors` | schema 校验失败（枚举/必填） | 把错误原文**前一行**反馈给模型重试（43.5） |
| 模型永远返回"好的，这是..." | 提示词没约束，或 system 里说了"要解释" | system 里写"只输出 JSON，不要任何解释"；仍不行就上重试 |
| `with_structured_output` 返回 `None` | 模型没调用工具 | 检查是否同时传了冲突的工具；小模型建议直接解析正文 |
| `with_fallbacks` 没生效 | 主链没抛异常，只是答案差 | fallback 只处理异常；质量要评测 |
| `configurable_fields` 报 `Configuration key not found` | key 不是对象自身字段（比如给 prompt 换变量） | 只能换模型/对象的**自身字段**（temperature 等） |
| `RunnableSequence object has no field "xxx"` | 想改链的内部属性 | Runnable 不可变，用 `.with_*` 生成新链 |
| 重试了但没变好 | 提示词没带上错误反馈 | 把上一次的异常原文（一行）传回模型 |
| 一次调用花了 5 倍钱 | 重试 3 次 + 每次都是长上下文 | 重试只重发"最后一次错误的输出"，不要重发全部历史；或降级到便宜模型 |

---

## 44.9 章末自测

**Q1** 三种解析器最大的差别是什么？举一个"只有 Pydantic 能拦住"的例子。

<details>
<summary>提示</summary>
`Str` 不管；`Json` 管语法；`Pydantic` 管**语义**（类型、枚举、范围）。
`{"decision": "可以退"}` 是合法 JSON，但 `Literal` 能拦住。
</details>

**Q2** 为什么"校验失败就返回默认值"是反模式？

<details>
<summary>提示</summary>
因为它把"模型没按格式答"伪装成"业务上就是这个值"。
线上表现为"数据看起来正常，结论悄悄错了"，监控发现不了。
</details>

**Q3** `chain = prompt | model | parser` 之后，`chain` 是什么？它有哪些方法？

<details>
<summary>提示</summary>
一个 `RunnableSequence`，属于 `Runnable`，有 `invoke` / `stream` / `batch` / `ainvoke` / `astream` 等。
</details>

**Q4** `with_retry` 和 `with_fallbacks` 都能"兜底"，它们处理的边界在哪？

<details>
<summary>提示</summary>
都只处理**异常**。`with_retry` 是"同一条链再试"，`with_fallbacks` 是"换一条链"。
答得不好但没报错，两者都不管。
</details>

**加分题**

> 你的同事说："我在提示词里写了 20 条格式要求，模型 95% 的时候都听话，所以不用解析器了。"

参考思路：**95% 听起来很高，但你要算"每次请求的失败概率"**。
如果一次请求要连续调用 11 次模型（一个 10 步的 Agent），成功率是 `0.95^11 ≈ 57%`。
也就是说 **43% 的请求会挂**——只是你不知道挂在哪。
解析器 + 重试做的就是把"57%"拉回到"99%+"，而且**让失败可见**。

---

## 44.10 可选补课：结构化输出的三种实现路线

> ⚠️ **这一节可以先跳过。** 等你要在"兼容性"和"严格性"之间做取舍时再看。

| 路线 | 写法 | 优点 | 缺点 |
|---|---|---|---|
| **A. 提示词 + 解析器** | `prompt \| model \| PydanticParser` | 兼容所有模型（包括本地小模型） | 依赖模型听话 |
| **B. 工具调用（function calling）** | `model.bind_tools([schema], tool_choice=...)` | 大多数主流模型支持，格式稳定 | 小模型支持差；部分 provider 有 schema 限制 |
| **C. 原生 structured output** | `model.with_structured_output(Schema)` | 最简洁 | 各 provider 实现不同，行为有差异 |

**选择建议**：

```
先问：模型支持 tool_calls 吗？
  支持 → 用 C（框架会选最合适的方式），并保留"校验 + 重试"
  不支持 → 用 A，提示词里塞 get_format_instructions() 的输出
任何时候：都要 try/except + 重试，不要假设"结构化了就一定对"
```

### 一个真实的兼容性坑

某些网关（尤其是代理转发 OpenAI 协议的）**不支持** `tool_choice={"type": "function", "function": {"name": ...}}` 这种强制模式，
会返回 400。这时要么降级到路线 A，要么去掉 `tool_choice` 改成"建议调用"。
**这类错误在本地测不出来**——所以上线前一定要在**真实网关**上跑一次。

---

## 44.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 三种解析器对照 | `code/framework/lc/ch44/step1_parsers.py` | 第 46 章 `create_agent(response_format=...)` |
| 带反馈重试 | 同上 ④ | 第 46 章中间件、第 56 章故障复盘 |
| LCEL 三件套 | `code/framework/lc/ch44/step2_lcel.py` | 第 45 章 RAG 链、第 47 章 LlamaIndex 对照 |
| 六种组合子 | `code/framework/lc/ch44/step3_composition.py` | 第 54 章提示词版本化、第 53 章 trace 打标 |

**这一节建立的"可复用资产"**：`Refund` 这个 schema 在第 46 章会直接变成 `create_agent(response_format=Refund)` 的参数——
**同一个 Pydantic 类，既做解析校验，又做 Agent 的最终输出契约。**

---

## 44.12 ✅ 验收

跑完三个脚本，检查五件事：

**① 你能说出"1/5"是什么意思**

`step1` ① 的输出是 `→ 1/5 能直接解析`。不看笔记，说出另外四种分别是什么问题。

**② 你能解释枚举校验的价值**

`step1` ③ 里"枚举值写错"那条报错。说出：**如果不校验，这个错误会在哪里、以什么形式暴露？**

**③ 你能画出重试的流程图**

不看代码，用箭头画出 `parse_with_repair` 的流程：调用 → 解析 → 成功/失败 → 带反馈重试 → 超次数报错。

**④ 你能说出 `with_fallbacks` 的边界**

`step3` ⑤ 的输出后面有一句提示。不看笔记复述：fallback 处理什么、不处理什么。

**⑤ 一个数字**

`step1` ④ 的输出里，第一次失败后重试成功。

**现在算一个数**：如果这个场景的首次失败率是 25%，每次重试成本是 ¥0.002，首次调用是 ¥0.002，
那么"带重试"的**平均每次请求成本**是多少？

<details>
<summary>答案</summary>

平均成本 = 首次 ¥0.002 + 25% 概率再花 ¥0.002 = `0.002 + 0.25 × 0.002 = ¥0.0025`

成本只涨 **25%**，但把失败率从 25% 压到（假设重试成功率 80%）`25% × 20% = 5%`。

**这就是"重试"的经济学**：你花 25% 的钱，买回 80% 的失败。
对照一下：如果为了省这 25% 而"返回默认值"，代价是 25% 的请求**悄悄出错**——这个成本没人算得出来，但它真实存在。

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 45 章 工具、检索、记忆与 MCP。
解析器解决了"输出"，下一章解决"输入"——怎么把函数变成模型能看见的**工具**，
怎么把向量库接成**检索器**，以及为什么"记忆"这件事已经从 LangChain 搬家到了 LangGraph。

> 📎 参考：本章对应基础教程第 14 章《输出解析器》、第 15 章《LCEL 与链式调用》的知识点，
> 但**重排了顺序**：先"五种输出只有一种能解析"，再"三个解析器"，最后才是"用 `|` 接起来"。
> 基础教程把 LCEL 当"语法"讲，本书把它当"**被重试/降级/并行能力包围的执行单元**"讲。
