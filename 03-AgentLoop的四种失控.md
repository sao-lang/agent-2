# 第 3 章 Agent Loop 的四种失控

> **你会遇到的坏事**：半夜两点，你的 Agent 账单冲到 300 块，日志里它在用同一句话反复搜索了 400 次。
>
> 没人写错代码。只是**没有人给它踩刹车**。

---

## 3.1 为什么 Agent 比普通程序更容易"跑飞"

传统程序：你写 10 行，它就执行 10 行。执行多少次是**静态确定**的。

Agent：你写 1 个循环，它执行多少次是**模型决定的**。而模型没有"预算感"。

它不知道：

- 已经调了 8 次搜索了
- 这次搜索和上次参数一模一样
- 上下文已经 5 万 token 了
- 这一轮花了 3 毛钱

**模型的唯一目标是把问题解决。为了这个目标，它会毫不犹豫地再试一次、再搜一遍、再想想。**

工程上这叫 **thrash（空转）**，它和"多花点算力换质量"是两回事——thrash 是完全无效的重复。

所以 `while not done:` 这个循环，必须有四道刹车。

---

## 3.2 四种失控与四种信号

这是本章的核心表格，**建议背下来**：

| # | 失控形态 | 现象 | 对应的刹车 | 刹车参数 |
|---|---|---|---|---|
| ① | **无限循环** | 永不满足终止条件 | 步数 / token / 成本预算 | `max_steps`、`max_tokens`、`max_cost` |
| ② | **重复调用** | 同参数反复调同一工具 | 调用指纹检测 | `max_repeats` |
| ③ | **上下文爆炸** | 历史无限增长，input token 飙升 | 上下文裁剪 | `max_tokens`、`per_message_cap` |
| ④ | **成本击穿** | 单步极贵（贵模型 + 长输出） | 预算硬上限 | `max_cost` |

前三个解决"次数和体积"，第四个解决"单价"。**四个都要有，缺哪个都会漏。**

---

## 3.3 刹车一：预算（Budget）

完整代码：[`code/common/guards.py`](code/common/guards.py)

```python
@dataclass
class Budget:
    max_steps: int = 12
    max_tokens: int = 60_000
    max_cost: float = 0.05

    steps_used: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0

    def exhausted(self) -> str | None:
        if self.steps_used >= self.max_steps:
            return f"steps({self.max_steps})"
        if self.tokens_used >= self.max_tokens:
            return f"tokens({self.max_tokens})"
        if self.cost_used >= self.max_cost:
            return f"cost(¥{self.max_cost})"
        return None
```

### 三个设计要点

**要点 1：三个维度都要有，不能只限步数**

因为不同失控形态对应的维度不同：

- 步数限制拦得住"无限循环"，拦不住"3 步烧掉 2 块钱"（贵模型 + 长输出）
- token 限制拦得住"上下文爆炸"，拦不住"每步都调 10 次工具"（工具不耗 token）
- 成本限制是**最后的兜底**——它是最直接的业务约束

**要点 2：检查必须在执行之前**

```python
for step in range(budget.max_steps):
    hit = budget.exhausted()        # ← 先检查
    if hit:
        break
    res = think(...)                # ← 再执行
    budget.spend(...)
```

如果顺序反了（先执行再检查），那"越界的最后一次调用"**已经真的发生了**。第 21 章的成本事故里，一半是这个顺序问题。

**要点 3：`exhausted()` 返回原因字符串，而不是 bool**

```python
return f"steps({self.max_steps})"   # 不是 return True
```

因为事后排障时，"因为步数停了"和"因为钱花完了停了"是不同的两个问题，处理方式完全不一样。**刹车要留下"为什么踩的"这个信息。**

---

## 3.4 刹车二：重复调用检测

模型最典型的 thrash 行为：**它以为自己在换思路，实际上参数一模一样。**

```python
@dataclass
class LoopGuard:
    max_repeats: int = 2
    _seen: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def fingerprint(tool: str, args: dict) -> str:
        raw = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def check(self, tool: str, args: dict) -> str | None:
        fp = self.fingerprint(tool, args)
        self._seen[fp] = self._seen.get(fp, 0) + 1
        if self._seen[fp] > self.max_repeats:
            return f"重复调用 {tool}({args}) 第 {self._seen[fp]} 次"
        return None
```

### 为什么要 `sort_keys=True`

`{"a": 1, "b": 2}` 和 `{"b": 2, "a": 1}` 是同一个参数，但 `json.dumps` 出来的字符串不同。不排序就等于指纹算法失效。

### 为什么允许重复 2 次而不是 1 次

因为**合理重试是必要的**：

- 第一次调用超时了，重试一次是正常的
- 用户改了一个字重新问，也是正常的

`max_repeats=2` 的意思是"同一参数最多出现 3 次"，第 4 次才拦。

⚠️ **拦截后要做什么？** 不是直接终止，而是**告诉模型"别再试了"**：

```python
messages.append({"role": "tool", "content": f"BLOCKED: {why}，请换一种思路。"})
```

这样模型有机会改参数或换工具，而不是白白浪费一次调用就死掉。

---

## 3.5 刹车三：上下文裁剪

最容易被低估的一个。先看真实数据（我跑出来的）：

```
② 重复调用：加指纹检测        3 步      186 token
③ 上下文爆炸：不裁剪          5 步   30,346 token   ← 只有 5 步，却比 3 步贵 160 倍
③ 上下文爆炸：裁剪到 4000     9 步   25,746 token
```

**5 步消耗 30,346 token** —— 这就是上下文爆炸。它不需要跑很多步，只需要每步都处理很大的内容。

### 关键：单条消息也要截断

第一版我只做了"保留最近 N 条消息"，结果实验失败（裁剪组反而更贵）。原因：

> **一个工具返回 2000 token 的检索结果，那就一条消息，但它自己就超预算了。**
>
> 只做"少留几条"根本压不住。

正确的实现是**两层裁剪**：

```python
@dataclass
class ContextLimiter:
    max_tokens: int = 4000        # 总量上限
    per_message_cap: int = 800    # 单条上限

    def trim(self, messages, est_tokens, truncate=None):
        total, kept = 0, []
        for m in reversed(messages):
            content = str(m.get("content", ""))
            if truncate and est_tokens(content) > self.per_message_cap:
                content = truncate(content, self.per_message_cap)   # ← 单条截断
            t = est_tokens(content)
            if total + t > self.max_tokens:
                break
            kept.append({**m, "content": content})
            total += t
        return list(reversed(kept))
```

### 截断时保留头尾

```python
def truncate_tokens(text, max_tokens, est_tokens):
    t = est_tokens(text)
    if t <= max_tokens:
        return text
    keep_chars = int(len(text) * max_tokens / t)
    head = keep_chars // 2
    tail = keep_chars - head
    return f"{text[:head]}\n...<省略 {t - max_tokens} token>...\n{text[-tail:]}"
```

**为什么保留尾部**：工具返回的结论、错误信息、统计数字通常在最末尾。只保留头部的话，模型看到一堆开头就没了，等于白喂。

⚠️ **坑**：裁剪会**破坏语义**。如果你裁断了 JSON 或代码块，模型会看到残缺内容，可能比没有更糟。第 16 章会讲更聪明的做法（按结构裁剪 + 摘要兜底）。

---

## 3.6 刹车四：成本硬上限

见 3.3 节的 `max_cost`。这里只强调一件事：

> **`max_cost` 是唯一能挡住"贵模型 + 长输出"的刹车。**

看实验数据：

```
④ 成本击穿：无预算        5 步   68,030 token  ¥0.1561
④ 成本击穿：加预算        3 步   26,424 token  ¥0.0648
```

同样的任务，**步数只差 2 步，成本差 2.4 倍**——因为它每次都生成 8000 token 的"深度分析"。步数限制对这种情况几乎无效。

---

## 3.7 💻 完整对照实验

```bash
python code/ch03_loop/demo_runaway.py
```

**不需要 API key**：用 `FakeBrain` 模拟模型行为，保证四种失控可以**可复现地**观察。

完整输出（我实际跑的，`MAX_STEPS=20`，每组的对照只放开被测的那一道刹车）：

```
case                               steps    tokens      cost  stop
① 无限循环：无预算                            48    16,032    0.0513  budget:cost(¥0.05)
① 无限循环：step/token/cost 三重预算           20     3,320    0.0146  budget:steps(20)
② 重复调用：无指纹检测                          20     2,940    0.0139  budget:steps(20)
② 重复调用：加指纹检测                           3       186    0.0016  guard:重复调用 search({'q': '上
③ 上下文爆炸：不裁剪                             5    30,346    0.0614  budget:cost(¥0.05)
③ 上下文爆炸：裁剪到 4000 token                  9    25,746    0.0559  budget:cost(¥0.05)
④ 成本击穿：无预算                               5    68,030    0.1561  budget:tokens(60000)
④ 成本击穿：加预算                               3    26,424    0.0648  budget:cost(¥0.05)
```

### 从这张表能读出什么

| 对比 | 数字变化 | 结论 |
|---|---|---|
| ① 无预算 → 有预算 | 48 步 / ¥0.0513 → 20 步 / ¥0.0146（**−72% 成本**） | 预算是唯一能拦住"永远不结束"的东西 |
| ② 无检测 → 有指纹检测 | 20 步 / ¥0.0139 → 3 步 / ¥0.0016（**−88% 成本**） | 性价比最高的刹车，只值 15 行代码 |
| ③ 不裁剪 → 裁剪 | 5 步 / 30,346 token → 9 步 / 25,746 token | **同样的钱，能跑近 2 倍的步数**（见下方说明） |
| ④ 无成本上限 → 有成本上限 | 5 步 / ¥0.1561 → 3 步 / ¥0.0648（**−58%**） | 单步极贵的场景，只有成本刹车有效 |

⚠️ **③ 这组要仔细看**：裁剪组的总 token（25,746）只比不裁剪组（30,346）少 15%，但**步数多了一倍**（9 步 vs 5 步）。

这说明：**裁剪的价值不是"省总量"，而是"让同样的预算能撑更多步"。**

如果你用"总 token 变少了多少"来评价裁剪，会得出"裁剪没用"的错误结论；正确的评价口径是**「单位 token 能完成多少步 / 多少有效工作」**。

这就是第 20 章"结果评估 vs 轨迹评估"的雏形——**指标选错，结论就会反。**

---

## 3.8 💥 失败实验：去掉一个刹车，看它怎么坏

现在你要**自己动手破坏**，感受每一种失控。

### 实验 A：只留步数限制（去掉 token 和成本）

把 `Budget(max_steps=20, max_tokens=10**9, max_cost=1e9)` 和 `ContextLimiter(max_tokens=10**9)` 组合起来，跑 `context` 模式。

**观察**：它会跑满 20 步，累计 token 是多少？和"有裁剪"比贵多少倍？

### 实验 B：指纹算法不做 `sort_keys`

把 `sort_keys=True` 去掉，然后构造一个"参数顺序在变"的模型（比如每次 `{"q": "x", "limit": 5}` / `{"limit": 5, "q": "x"}` 交替）。

**观察**：指纹检测是否还生效？为什么？

### 实验 C：把预算检查放在执行之后

把 `budget.exhausted()` 移到 `think()` 之后。

**观察**：`steps_used` 和实际调用次数是否对不上？超支了多少？

---

## 3.9 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 四道刹车 | `code/common/guards.py` | 第 4–9、25 章复用 |
| 指纹检测 | `LoopGuard.fingerprint` | 工具有副作用的场景更关键（第 18 章） |
| 两层裁剪 | `ContextLimiter` | 第 16 章升级为摘要 + 槽位 |
| 预算三件套 | `Budget` | 第 21 章接成本报表 |

---

## 3.10 ✏️ 小练习

### 练习 1（必做）：加入"无进展检测"

指纹检测只能发现"参数完全相同"。更高级的是**语义重复**：

> 参数不同，但检索结果几乎一样（都是那 3 条）。

实现思路：对工具返回结果做 hash 或 embedding 相似度，连续 N 次相似度 > 0.9 就判定为"无进展"。

**验收**：构造一个"每次换关键词但结果都一样"的模型，能被拦住。

### 练习 2：预算分级

不同场景要不同预算：

```python
BUDGETS = {
    "chat":    Budget(max_steps=3,  max_tokens=8_000,  max_cost=0.002),
    "analyze": Budget(max_steps=12, max_tokens=60_000, max_cost=0.05),
    "research": Budget(max_steps=40, max_tokens=200_000, max_cost=0.30),
}
```

**验收**：能根据第 13 章的意图识别结果自动选预算。

### 练习 3（进阶）：预算的"剩余量"要喂给模型

把剩余预算的提示塞进 system prompt：

```
当前预算：还剩 4 步、约 12000 token。请在预算内给出最优答案。
```

**验证**：模型的步数消耗是否真的下降了？（这属于第 10 章的上下文工程）

---

## 3.11 ✅ 验收

1. 四种失控分别对应哪道刹车？为什么必须四道都有？
2. 预算检查为什么必须在执行**之前**？
3. 为什么 `exhausted()` 要返回原因字符串？
4. 上下文裁剪为什么要做**单条消息**截断？
5. 指纹检测的容错次数为什么是 2 而不是 1？

**数字验收**：你能说出在你的场景里，加指纹检测前 vs 后的 token 消耗差异吗？（用实验 ② 的数据）

---

## 3.12 延伸阅读

- 下一章 ReAct：如何让循环本身"想得更清楚"，从源头减少 thrash
- 第 9 章：预算 + 检查点，才能让长任务真正可恢复
- 第 21 章：预算如何变成业务可运营的成本控制

---

下一页：[第 4 章 ReAct：最流行的 Agent 范式，以及它的边界](04-ReAct.md)
