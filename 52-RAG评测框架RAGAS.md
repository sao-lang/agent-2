# 第 52 章 RAG 评测框架：RAGAS 与 TruLens

> **这一章你会遇到什么坏事**
> 你在开源数据集上跑出 `faithfulness = 0.87`、`context_recall = 0.72`，写进周报。
> 老板问："那我们能不能回答'优惠券能不能退'这个问题？"
> 你打开评测报告——**报告里没有这个问题的答案**。它只有两个字：0.87。
>
> 更糟的是——**当你以为 0.87 是"正确率"时，它其实是"答案有没有依据"**。
> 一个完全错误但"引用了原文"的答案，faithfulness 满分。

> **学完你能做到**
> 1. 手算 RAGAS 四个指标，说清每个"到底在算什么"（51.3）
> 2. 看懂 RAGAS 的数据集格式，把第 40 章的评测集直接喂进去（51.4）
> 3. 说清"你的指标"和"RAGAS 指标"的口径差异（51.5）
> 4. 说清 judge 的三个偏差，并知道要做"与人工标注的一致性校验"（51.6）
> 5. 判断什么时候该用框架、什么时候手算就够（51.7）

---

## 52.0 先说明白八个词

| 术语 | 一句话（生活类比） | 本章哪里用到 |
|---|---|---|
| **RAGAS** | 一套"RAG 评测指标"的开源实现，四个核心指标 | 全章 |
| **reference** | 参考答案（人工写的"应该怎么答"） | 51.4 |
| **context_recall** | 金标里该用的资料，有多少被检索出来了 | 51.3 |
| **context_precision** | 检索回来的资料里，有多少真的有用（**看排序**） | 51.3 |
| **faithfulness** | 答案里的每句话，能不能在上下文里找到依据 | 51.3 |
| **answer_relevancy** | 答案切不切题（RAGAS 用"从答案反推问题"来算） | 51.3 |
| **judge（裁判模型）** | 用另一个模型来打分，代替人工 | 51.6 |
| **TruLens** | 覆盖在应用外面、边跑边打分的评测工具 | 51.8 |

> 还有一个必须提前说的：
> - **answer_correctness**：**唯一**直接判"答案对不对"的指标，但需要 `ground_truth`。
>   本章的四个核心指标里**没有它**——这是最容易被误解的一点。

---

## 52.1 先看一个具体的坏事：三个 case，三种病

真实场景：售后 RAG，三条评测样本。

先手算一遍（不装任何框架）：

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\li\ch51\step1_metric_math.py
```

真实输出（段 ①）：

```
  问题                      recall  precision  faithful  answer_rel
  ----------------------------------------------------------------------------------------
  退款多久到账？                   1.00       1.00      1.00        0.12
  会员退货时优惠券能拿回来吗？            0.00       0.00      0.00        0.21
  保修期多久？                    1.00       1.00      0.50        0.12
  ----------------------------------------------------------------------------------------
  平均                        0.67       0.67      0.50        0.15
```

**看三个 case 的分数分布，能直接读出三种病：**

| case | 现象 | 病 |
|---|---|---|
| 1 退款多久 | recall/precision/faithful 全 1.00，但 `answer_rel` 只有 0.12 | **指标口径问题**（见下） |
| 2 优惠券 | 全 0.00 | **检索完全错了** → 先修检索 |
| 3 保修期 | recall/precision 1.00，faithful 0.50 | **幻觉**：检索对了，模型自己加了一句 |

**注意 case 1 的 `answer_rel = 0.12`**——答案明明是对的。为什么？

因为 step1 用的是"字面重合"近似：问题 `退款多久到账？` 和答案 `退款将在 7 个工作日内原路退回。` **几乎没有共同的 2-gram**。

**这就是本章最重要的一课**：

> **指标的分子分母决定了它会骗你什么。**
> 字面重合会让"正确但换了说法"的答案得分极低；
> 而 RAGAS 的 `answer_relevancy` 用**反推问题**的方式，正是为了绕开这个坑。

---

## 52.2 为什么"用一个总分"不够

你可能会想：既然有四个指标，那我取平均当一个总分，盯这一个数不就行了？

看 `step1` 的平均值：`recall 0.67 / precision 0.67 / faithful 0.50 / relev 0.15`。

**如果平均成一个 0.50，你会得到什么结论？** "还行，但可以更好"。

**但真实情况是**：一条完全错、一条有幻觉、一条其实是对的。

| 你以为的"总分 0.5" | 实际 |
|---|---|
| 每条都是"半对" | 一条全错、一条有幻觉、一条对但指标测不出来 |
| 改进方向不明 | 三个不同的问题，三套不同的修法 |
| 可以上线（"及格了"） | **不能**：错误答案是硬伤 |

**所以我们需要"逐条 + 分指标"的表格，而不是一个数。**

> 💥 **失败实验 1：把"字面重合"换成"完全相等"**
> 打开 `step1_metric_math.py`，把 `overlap()` 改成"两段文字完全相等才返回 1.0"。
> 重跑。观察四个指标全部塌成 0（除了 case 1 的 faithfulness）。
>
> **结论：指标对"措辞"极其敏感。** 你换了同义词、调了语序，分数就变了——但业务上它没变。
> 这就是为什么真实评测必须**同时看数字和逐条输出**。

---

## 52.3 四个指标到底是什么（10 行代码看懂）

### 一句话

> **RAGAS 的四个核心指标，分别回答四个不同的问题：该用的资料找到了吗（recall）、找到的干净吗（precision）、答案有据可查吗（faithfulness）、答案扣题吗（relevancy）。**

### 最小例子

```python
def context_recall(case) -> float:
    ctx = " ".join(case.contexts)
    hit = sum(1 for ref in case.reference if overlap(ref, ctx) >= 0.6)
    return hit / len(case.reference)          # ① 分母是"金标句子数"

def context_precision(case) -> float:
    useful = [overlap(s, refs) >= 0.6 for s in sentences(case.contexts)]
    ...
    return total / tp                          # ② 分母是"命中数"，且按位置加权

def faithfulness(case) -> float:
    supported = sum(1 for s in sentences(case.answer) if overlap(s, ctx) >= 0.5)
    return supported / len(sentences(case.answer))   # ③ 分母是"答案句子数"

def answer_relevancy(case) -> float:
    return overlap(case.answer, case.q)        # ④ 真实 RAGAS 会"反推问题"
```

| 指标 | 分母是什么 | 它惩罚什么 |
|---|---|---|
| `context_recall` | **金标句子数** | 漏召回 |
| `context_precision` | **命中数**（且按位置加权） | 无关内容排在前面 |
| `faithfulness` | **答案句子数** | 无依据的断言（幻觉） |
| `answer_relevancy` | （相似度） | 答非所问 |

**注意 `context_recall` 和 `context_precision` 的分母完全不同**——这就是"同一个召回结果，两个指标说法相反"的原因：

- 金标只有 1 句，你召回了 10 条（含那 1 句）→ **recall = 1.0**（全找到了）
- 但 10 条里 9 条无关 → **precision 会被拉低**

### ✏️ 停下来想一想

`step1` 的 case 1 里，上下文有 2 条：一条是金标，一条是无关的运费条款。

**为什么 `context_precision` 还是 1.00？**

（提示：precision 的分母是"命中数"（`tp`），不是"总句子数"。所以"多带一条无关内容"只会让**分母**变——但分母其实是 `tp`，无关内容根本不计入。你需要在真实 RAGAS 里看它怎么定义"相关的 retrieved 条目"。）

---

## 52.4 从"手算"到"用框架"（阶梯代码 step1 / step2）

| Step | 文件 | 新增的一个概念 | 上一级的痛点 |
|---|---|---|---|
| step1 | `step1_metric_math.py` | 四个指标的手算实现 | — |
| step2 | `step2_ragas_api.py` | RAGAS 数据集格式 + API + 口径对照 + judge 偏差 | step1 只能跑 3 条 |

### step2：数据集格式只有四个字段

真实输出（段 ①）：

```
  第 1 条：
    user_input           = '退款多久到账？'
    retrieved_contexts   = ['退款将在 7 个工作日内原路退回。']
    response             = '退款将在 7 个工作日内原路退回。'
    reference            = '退款将在 7 个工作日内原路退回。'
```

| 字段 | 是什么 | 谁是必需的 |
|---|---|---|
| `user_input` | 问题 | 所有指标 |
| `retrieved_contexts` | 检索到的上下文（**列表**） | context_* 与 faithfulness |
| `response` | 模型生成的答案 | faithfulness 与 answer_relevancy |
| `reference` | 参考答案 | context_recall 与 answer_correctness |

**注意它和第 40 章的 `evals/rag_cases.json` 几乎一样。** 这说明"评测集格式"是行业共识，不是某个框架的发明。

### 为什么本仓库不装 ragas

真实输出（段 ②）：

```
  ragas 状态：未安装（ModuleNotFoundError）
```

`step2` 里有这样一段守卫：

```python
try:
    import ragas
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import context_recall, context_precision, faithfulness, answer_relevancy
    HAS_RAGAS = True
except Exception as e:
    HAS_RAGAS = False
    RAGAS_VERSION = f"未安装（{type(e).__name__}）"
```

**为什么不装？** 我们真的试过：`pip install ragas --dry-run` 的输出是

```
Would install ... langchain-classic-1.0.8 langchain-community-0.4.2
              langchain-openai-1.1.9 ...
```

它会把 `langchain-openai` 从 1.7.2 **降到 1.1.9**，并拉进 `langchain-classic`。
**这会直接影响第 42–49 章的所有示例**（那些示例是按 1.7.2 的 API 写的）。

**所以策略是"可选依赖 + import 守卫"**：

| 做法 | 好处 | 代价 |
|---|---|---|
| CI 不装 | 第 42–49 章示例不受影响 | 本章的"真实 API"部分不执行 |
| 单独 venv 装 | 能跑真实评测 | 不能与框架章共用环境 |

**这不是偷懒，这是工程决策**：**一个教程的示例互相打架，比"少跑一个框架"严重得多。**

---

## 52.5 核心实现（逐行解释）

这一节拆解 `context_precision` 的"平均精度"写法——**这是全章最容易算错的一个**。

```python
def context_precision(case: Case) -> float:
    refs = " ".join(case.reference)
    useful = [overlap(s, refs) >= 0.6 for s in _sentences(case.contexts)]   # ①
    if not useful or not any(useful):
        return 0.0                                                          # ②
    total = 0.0
    tp = 0
    for i, u in enumerate(useful, 1):                                       # ③
        if u:
            tp += 1
            total += tp / i                                                 # ④
    return total / tp                                                       # ⑤
```

| 行 | 在做什么 | 不这么写会怎样 |
|---|---|---|
| ① | 把检索结果切成句子，逐句判"是否与金标相关" | 按"条"判：一条长上下文只要含一句相关就整条算相关，虚高 |
| ② | 全都无关时返回 0 | 除以 0 报错 |
| ③ | 按**出现位置**遍历 | 不看顺序 → 丢掉"排序质量"这个维度 |
| ④ | 每命中一个，累加 `命中数 / 当前位置` | 这是平均精度（AP）的核心：**第一个就命中 = 1.0，第五个才命中 = 0.2** |
| ⑤ | 除以命中数 | 除以总数会得到"命中率"，不是"精度" |

**一句话记住**：`context_precision` 不是"相关比例"，是"排序质量的加权平均"。

### 三个设计取舍

| 取舍 | 选了 | 不这么选会怎样 |
|---|---|---|
| 按句子还是按条判 | **按句子** | 按条：一条里混了一句相关就整条算好，掩盖噪声 |
| 阈值 0.6 | 经验值 | 太高：同义改写全判无关；太低：什么都算相关 |
| 用 LLM judge 还是字面 | **先字面，可疑的再 judge** | 全用 judge：300 条 case = 300 次调用，评测预算爆炸 |

### ⚠️ 一个必须知道的坑：四个指标里没有"答案对不对"

真实输出（`step2` 段 ③）：

| 指标 | 你的手算版 | RAGAS 版 | 差异点 |
|---|---|---|---|
| `context_recall` | 金标句被覆盖比例 | 抽论断逐条判（LLM） | 粒度：句子 vs 论断 |
| `context_precision` | 命中句的平均精度 | 逐条判相关 + 平均精度 | 判定方式不同 |
| `faithfulness` | 答案句与上下文最大重合 | 抽论断逐条判 | **LLM 判定，更准也更贵** |
| `answer_relevancy` | 与问题字面重合 | **从答案反推问题**，再算相似度 | 目的：防"通顺但跑题" |
| `answer_correctness` | 没有（人工比对） | 需要 `ground_truth` | **唯一直接判"对错"的** |

**结论：** `step1` 的 case 2 答案明明是错的（说优惠券能退），但四个指标里**没有一个直接说"你错了"**。

> 💥 **失败实验 2：让"错误但流畅"的答案得高分**
> 在 `step1` 的 `CASES` 里加一条：
> ```python
> Case(
>     q="退款多久到账？",
>     answer="退款将在 7 个工作日内原路退回。另外还会额外赠送 100 元优惠券。",
>     contexts=["退款将在 7 个工作日内原路退回。"],
>     reference=["退款将在 7 个工作日内原路退回。"],
> )
> ```
> 重跑。观察 `faithfulness`：**它会掉到 0.5**（第二句无依据）——这次它抓到了。
>
> **但把第二句改成"退款将在 7 个工作日内原路退回，这是行业惯例。"**
> `faithfulness` 又会回到 1.0（"行业惯例"这几个字和上下文没有重合，但那句话被切成了同一句）。
> **结论：按"句"判的依据检查，粒度太粗。真实 RAGAS 抽的是"论断"（claim），比句子细。**

---

## 52.6 用起来：三个问题 2 分钟答完

💻 两个脚本：

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe code\framework\li\ch51\step1_metric_math.py
.venv\Scripts\python.exe code\framework\li\ch51\step2_ragas_api.py
```

### 问题 ①：judge 靠谱吗？

真实输出（`step2` 段 ④）：

```
  1. 位置偏差（position bias）
     把两段上下文换个顺序，judge 的判断会变。典型表现：排在后面的证据被忽略。
  2. 长度偏差（verbosity bias）
     更长的答案更容易被判"信息量更大"。典型表现：啰嗦的回答 faithfulness 偏高。
  3. 自我偏好（self-preference）
     用 A 模型当 judge 时，它偏爱 A 模型写的答案（同类风格）。
```

**所以 judge 必须做一致性校验**：

```
抽 30 条人工标注 → 算 judge 与人工的一致率（Kappa 或简单一致率）
低于 0.6 → 这个 judge 在你的领域不可用
```

**第 40 章那句话在这里同样适用**：**没有校验过的 judge，就是一个带随机性的指标。**

### 问题 ②：RAGAS 和 TruLens 有什么不同？

真实输出（`step2` 段 ⑤）：

| | RAGAS | TruLens |
|---|---|---|
| 形态 | 离线批评测（给数据集，出报表） | 在线 + 离线（包住应用，边跑边打分） |
| 核心概念 | Dataset + Metric | App + Feedback + Dashboard |
| RAG 三件套 | `context_*` / `faithfulness` / `answer_*` | groundedness / context_relevance / answer_relevance |
| 适合 | 回归测试、发版前门禁 | 上线后持续监控、定位单次请求 |

**一句话：RAGAS 管"发版前"，TruLens 管"上线后"。**

### 问题 ③：什么时候该用框架？

真实输出（`step2` 段 ⑥）：

| 用 RAGAS 当 | 不用 RAGAS 当 |
|---|---|
| case 数 > 100，要出报表 | case < 30（手算更快，而且你能看懂每个数字） |
| 要与业界口径对齐 | 没有 `ground_truth`（大部分指标需要它） |
| 需要 LLM judge 的细腻判定 | 预算紧（judge 是 N 次调用） |

**最好的做法：手算版做粗筛，RAGAS 做精筛，人工做仲裁。**

### 🎯 到这里，你已经掌握了 RAG 评测的"指标层"

| 能力 | 在哪一节 |
|---|---|
| 四个指标在算什么 | 51.3 |
| 平均精度（排序敏感）的写法 | 51.5 |
| RAGAS 数据集格式 | 51.4 |
| 口径差异（为什么框架的"精度"和你想的不一样） | 51.5 |
| judge 的三个偏差 | 51.6 |
| 什么时候用框架 | 51.6 |

**剩下的都是"把评测接进流程"：数据集管理、门禁、看板。**

---

## 52.7 三个小练习（从易到难）

### 练习 1（5 分钟）：改一个阈值

把 `step1` 里 `context_recall` 的 `>= 0.6` 改成 `>= 0.9`，重跑。
**验收标准**：说出"哪些 case 的 recall 变了，为什么"。

### 练习 2（20 分钟）：把你的评测集接上

把第 40 章的 `evals/rag_cases.json` 转换成 RAGAS 的四字段格式。

**最低要求清单**：
- [ ] 每条都填 `user_input` / `retrieved_contexts` / `response` / `reference`
- [ ] 用 `step1` 的手算版先跑一遍
- [ ] 挑出"retrieval 正常但 faithfulness 低"的那几条（这就是幻觉样本）
- [ ] 手工核对 3 条，确认指标没在骗你

### 练习 3（15 分钟，💥 故意破坏）

**实验 A：把 `context_precision` 改成"相关比例"（除以总句子数）。**
重跑。观察 case 1 的 precision 从 1.00 变成 0.5。
**结论：同样叫 precision，口径不同结果差一倍。** 报告里必须写清用的是哪种。

**实验 B：把一个正确答案用同义词改写。**
把 `"退款将在 7 个工作日内原路退回。"` 改成 `"7 个工作日可到账。"`，重跑。
观察 recall / precision 的下降。
**结论：字面指标会把"对"判成"错"。** 这也是为什么真实 RAGAS 要用 LLM judge。

**实验 C：把 `answer_relevancy` 换成"从答案反推问题"的近似（提取答案里的名词）。**
观察 case 1 的分数从 0.12 变成多少。
**结论：这一步就是 RAGAS 的设计动机 —— 让"正确但换了说法"的答案也能拿高分。**

---

## 52.8 常见错误速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `ModuleNotFoundError: ragas` | 没装（本仓库故意不装） | 单独 venv 安装；或用 `step1` 手算版 |
| 装了 ragas 后第 42–49 章全报错 | 它降级了 `langchain-openai` | 独立 venv；或用 import 守卫 |
| 分数全是 1.0 | 用了常量嵌入（`MockEmbedding`） | 换真实嵌入（第 51 章） |
| faithfulness 高但答案是错的 | faithfulness **只判"有没有依据"** | 加 `answer_correctness` + ground_truth |
| context_precision 和预期不符 | 它是"平均精度"不是"相关比例" | 看 51.5 的口径 |
| 换了同义词分数暴跌 | 字面重合对措辞敏感 | 用 embedding 或 LLM judge |
| judge 打分忽高忽低 | judge 有位置/长度/自我偏好偏差 | 打乱顺序重复测；用不同厂商的 judge |
| judge 与人工不一致 | judge 在你的领域不可用 | 算一致率；低于 0.6 就别用 |
| 评测集越跑越少 | 用例只增不减 | 冻结 + 只增 |
| 报告里只有一个总分 | 没有逐条明细 | 必须出"逐条 × 分指标"的表 |

---

## 52.9 章末自测

**Q1** 四个核心指标里，哪个能告诉你"答案是错的"？

<details>
<summary>提示</summary>
**都不能。** 唯一能判对错的是 `answer_correctness`（需要 ground_truth），它不在"四个核心指标"里。
</details>

**Q2** `context_precision` 为什么对"顺序"敏感？

<details>
<summary>提示</summary>
它用平均精度（AP）：第一个就命中得 1.0，第五个才命中得 0.2。
所以"好块排前面"比"好块排后面"分数高。
</details>

**Q3** 为什么本仓库不在 CI 里装 RAGAS？

<details>
<summary>提示</summary>
它要求降级 `langchain-openai`（1.7.2 → 1.1.9）并引入 `langchain-classic`，
会破坏第 42–49 章的示例。用"可选依赖 + import 守卫"。
</details>

**Q4** judge 的三个偏差是什么？怎么缓解？

<details>
<summary>提示</summary>
位置偏差（打乱顺序）、长度偏差（控制长度/同时报长度）、自我偏好（换不同厂商的 judge）。
并且必须做与人工的一致性校验。
</details>

**加分题**

> 同事说："我们 faithfulness 0.9，可以上线了。"

参考思路：**先问三个问题**：
① faithfulness 只判"有没有依据"，那**答案对不对**你测了吗？
② 0.9 是在多少条 case 上算的？切片里有没有掉到 0.5 的？
③ 上下文召回率多少？如果检索就没召回到，faithfulness 0.9 只是在"基于错的资料答得很忠实"。

**三个数字缺一个，都说明不了的。**

---

## 52.10 可选补课：TruLens 的落地形态

> ⚠️ **这一节可以先跳过。** 等你要"上线后持续监控"时再看。

### 它和 RAGAS 的根本区别

| | RAGAS | TruLens |
|---|---|---|
| 数据从哪来 | 你准备好的数据集 | **每次真实调用**（自动记录） |
| 什么时候跑 | 发版前 | 上线后持续 |
| 输出 | 一张报表 | 一个可下钻的仪表盘 |

### 三个核心反馈函数（对应第 40 章的三个指标）

| 反馈函数 | 问什么 | 对应本书 |
|---|---|---|
| `Groundedness` | 答案是否基于上下文 | faithfulness / 引用校验 |
| `Context Relevance` | 检索到的上下文是否相关 | context_precision |
| `Answer Relevance` | 答案是否切题 | answer_relevancy |

### 一个务实的接入顺序

```
1. 先在应用外面包一层 trace（第 38 章自己写的 tracer 也行）
2. 把"每次调用的 input / contexts / output"落盘
3. 对这些落盘数据跑离线评测（RAGAS 或手算）
4. 只有在"每天要看板"时，才上 TruLens 这类在线工具
```

**顺序很重要**：**先有数据，再有工具。** 没有落盘的调用记录，任何评测工具都是空转。

---

## 52.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 四个指标手算实现 | `code/framework/li/ch52/step1_metric_math.py` | 直接改成你的粗筛脚本 |
| RAGAS 格式 + 守卫 | `code/framework/li/ch52/step2_ragas_api.py` | 装上 ragas 就能跑 |
| "指标揭示什么病"对照表 | 本章 51.6 | 每次看评测报告时对照 |

**这一节建立的方法论**：**"指标的分子分母"比"指标的名字"重要。**
你以后看到任何 RAG 评测数字，先问"分母是什么"。

---

## 52.12 ✅ 验收

跑完两个脚本，检查五件事：

**① 你能说出三个 case 各是什么病**

不看笔记：case 1 是指标口径问题、case 2 是检索全错、case 3 是幻觉。

**② 你能写出 `context_precision` 的核心两行**

`total += tp / i` 和 `return total / tp`，并解释为什么不是除以总数。

**③ 你能说清"四个核心指标里没有答案对错"**

这是本章最重要的一句。

**④ 你能说出 judge 的三个偏差**

位置、长度、自我偏好，各一句。

**⑤ 一个数字**

`step1` 的输出里，case 1 的 `answer_relevancy = 0.12`。

**现在算一个数**：这条 case 的答案**是对的**，但 relevancy 只有 0.12。
如果"relevancy < 0.3 就判失败"，你的通过率会掉多少？

<details>
<summary>答案</summary>

3 条 case 里有 3 条 relevancy < 0.3（0.12 / 0.21 / 0.12）→ **通过率 0%**。

一个"全部正确"的系统，在错误的指标口径下会显示"全部失败"。
**这就是为什么第 40 章强调"先看逐条，再看总分"。**

</details>

五件事都能独立完成，这一章就过了。

---

**下一章预告**：第 53 章 LangSmith 与 LangFuse。
指标讲完了，下一章讲"数据从哪来"——怎么让每一次调用自动上报，
以及为什么"不用平台也能做完第 38 章的事"。

> 📎 参考：本章对应基础教程第 1-3 章提到但没有独立章节的"RAG 评测"部分，
> 以及第 20 章《RAG 检索增强生成》里"如何衡量效果"的小节。
> 本书把它独立成章，因为**评测不是附属功能，是发版门禁**。
