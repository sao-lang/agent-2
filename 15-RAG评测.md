# 第 15 章 RAG 评测：把"感觉变了"变成数字

> **你会遇到的坏事**：你改了一个 prompt，感觉回答变好了。上线后用户投诉变多了。
>
> 因为你没有评测集，你所谓的"感觉"只是看了 3 个样本。

---

## 15.1 为什么必须自己写评测

先说结论：**RAGAS 好用，但你必须先懂它在算什么。**

原因有三个：

1. **指标选错，结论就反**：第 3 章已经演示过——用"总 token 变少"评价裁剪，会得出"裁剪没用"的错误结论
2. **阈值/判据要按业务调**：什么算"忠实"、什么算"答上了"，只有你知道
3. **Judge 本身要校验**：LLM-as-judge 也会错，不校验等于自欺

所以本章先手写一套最小框架（[`code/common/rag_eval.py`](code/common/rag_eval.py)），再告诉你什么时候该换 RAGAS。

---

## 15.2 四层指标（从便宜到贵）

| 层 | 指标 | 需要模型 | 能发现什么 |
|---|---|---|---|
| **L1 检索** | recall@k、MRR、hit rate | ❌ | 找没找到、排得准不准 |
| **L2 引用** | 引用准确率 | ❌ | 模型有没有编造来源 |
| **L3 忠实** | faithfulness | ✅ judge | 回答是不是基于材料 |
| **L4 有用** | relevance | ✅ judge | 是不是答了问题 |

**为什么必须分层**：

> `recall@5 = 100%` 但 `faithfulness = 0.3` → 检索没问题，**生成在编**
> `recall@5 = 40%` 但 `faithfulness = 1.0` → 生成没问题，**检索不到材料**
>
> 修理方式完全不同。只看一个"总分"，你永远不知道该改哪一块。

---

## 15.3 L1：检索指标（零成本，先做这个）

```python
def retrieval_metrics(retrieved_ids, gold_ids, ks=(1, 3, 5)):
    recall = {k: any(g in retrieved_ids[:k] for g in gold_ids) for k in ks}
    rank = next((i + 1 for i, rid in enumerate(retrieved_ids) if rid in gold_ids), None)
    mrr = 1.0 / rank if rank else 0.0
    return recall, mrr
```

### ⚠️ 关键设计：用 chunk id，不用文本

```python
# ❌ 不要这样
if answer_keyword in retrieved_text:

# ✅ 要这样
if gold_chunk_id in retrieved_ids:
```

**为什么**：你一改分块策略，文本就全变了。用文本做 gold，评测集就**无法跨配置复用**。

用 id 也不行——因为**分块变了，id 也会变**。

**正确的做法**：gold 标注的是"答案所在的**语义位置**"，然后每次配置变化时**重新映射**：

```python
def gold_ids_for(case, idx):
    # 真实项目：人工标注的"答案在文档第几段"，用偏移量映射到当前 chunk
    return [c.id for c in idx.chunks if all(k in c.text for k in case.must_contain)]
```

⚠️ 这是**评测工程里最容易被做错的一件事**。教材里的示例用关键词映射是"够用但不够严谨"的方案，你自己的项目应该用**文档段落锚点**。

---

## 15.4 L2：引用校验（零成本，最被忽视）

```python
def check_citation(answer, cited_ids, valid_ids) -> bool:
    if not cited_ids:
        return False
    return all(cid in valid_ids for cid in cited_ids)
```

**它能抓住的问题**：

| 现象 | 引用校验能发现 |
|---|---|
| 模型编了一个来源 `[c99]` | ✅ 不在检索结果里 |
| 模型不给引用 | ✅ `cited_ids` 为空 |
| 模型引用的都是真实检索结果 | ❌ 但可能引用错了段（需要 L3） |

**很多系统的"引用"是装饰性的**——模型随便写个 [1]，没人校验。**这是 RAG 系统里最高性价比的一次检查**（几行规则，零成本）。

---

## 15.5 L3/L4：Judge（有成本，必须校验）

```python
FAITHFULNESS_PROMPT = """判断【答案】里的每一句事实性陈述是否都能在【材料】里找到依据。
输出 JSON：{"score": 0.0~1.0, "unsupported": [...]}"""
```

### Judge 的三个已知偏差

| 偏差 | 现象 | 缓解 |
|---|---|---|
| **位置偏差** | 倾向给"材料在前面"的答案高分 | 随机打乱材料顺序 |
| **长度偏差** | 长答案更容易被判"完整" | 明确"简洁也算完整" |
| **自我偏好** | 自己模型生成的答案更容易过 | 换一个模型当 judge |

### 必须做的一步：校验 judge

```python
def validate_judge(llm, samples, tolerance=0.3):
    """samples: [(contexts, answer, 人工标注分数), ...]"""
    diffs = []
    for contexts, answer, human in samples:
        s = faithfulness_llm(llm, contexts, answer)
        diffs.append(abs(s - human))
    agree = sum(1 for d in diffs if d <= tolerance) / len(diffs)
    return {"agreement_rate": agree,
            "verdict": "可用" if agree >= 0.8 else "不可用，请换 judge 或改 prompt"}
```

**操作步骤**：

1. 人工标 15–20 条（faithfulness 1/0.5/0 三档就够）
2. 跑 `validate_judge`
3. `agreement_rate < 0.8` → 换 judge 模型或改 prompt，**不要继续用**

> **如果 judge 和人工的一致性只有 60%，那你之后所有"提升了 15%"的结论都在噪音范围内。**

---

## 15.6 💻 A/B 对比：一次只改一个变量

```bash
python code/ch15_rag_eval/demo_eval.py
```

**不需要 API**（只跑 L1）。

### 我实际跑出来的结果

```
配置                    recall@1  recall@3  recall@5     mrr  answer_contains_required
chunk=200                 0.800     0.800     0.933   0.830                    0.800
chunk=400                 0.733     1.000     1.000   0.856                    1.000
chunk=800                 0.933     1.000     1.000   0.967                    1.000

=== 基线 vs 最优（差值） ===
  recall@1                    0.800 →   0.933   ↑ +0.133
  recall@3                    0.800 →   1.000   ↑ +0.200
  mrr                         0.830 →   0.967   ↑ +0.137
  answer_contains_required    0.800 →   1.000   ↑ +0.200
```

### 三条必须遵守的评测纪律

**纪律 1：一次只改一个变量**

这里只改 `chunk_size`，`overlap` 固定 40。如果你同时改 overlap，你就不知道是谁的功劳。

**纪律 2：必须看失败样本，不能只看总分**

```python
fails = report.failures("contains_required")
for r in fails:
    print(r.question, r.retrieved_ids)
```

在这个示例里，最优配置的失败样本是 0 条——**这份语料太小了**。真实项目里一定会有失败样本，那才是你要修的地方。

**纪律 3：样本要够，但不必一开始就很大**

| 阶段 | 样本量 | 用途 |
|---|---|---|
| 开发阶段 | 20–30 条 | 快速迭代 |
| 上线前 | 50–100 条 | 可靠结论 |
| 生产 | 200+ 条 + 真实日志回流 | 回归检测 |

⚠️ **15 条样本的结论不可靠**。这份示例只是为了让你跑通流程。

---

## 15.7 完整流水线（需要 API）

```bash
python code/ch15_rag_eval/demo_eval_llm.py --limit 3
```

它跑完整链路：检索 → 生成（带引用）→ 规则校验 → judge 打分。

关键代码：

```python
retrieved = idx.search(case.question, k=5)
contexts = [f"[{c.id}] {c.text}" for c, _ in retrieved]

msg = llm.invoke(ANSWER_PROMPT.format(contexts="\n\n".join(contexts), question=case.question))
answer = str(msg.content)

cites = extract_citations(answer)
citation_ok = check_citation(answer, cites, set(retrieved_ids))
faith = faithfulness_llm(llm, [c for c, _ in retrieved], answer)
rel = relevance_llm(llm, case.question, answer)
```

**prompt 里的两个关键约束**：

```
1. 如果材料里没有答案，直接回答"资料中未提及"，不要猜
2. 每条结论后面用 [编号] 标注来源
```

第 1 条让你能测**拒答率**（第 9 章讲过，不拒答的 RAG 一定会编）。
第 2 条让 L2 校验成为可能。

---

## 15.8 RAGAS 什么时候用

| 场景 | 建议 |
|---|---|
| 想快速看几个标准指标 | 用 RAGAS |
| 需要自定义指标（业务口径） | 自己写 |
| 需要接 CI 做回归 | 自己写（可控、无额外依赖） |
| 需要和团队共享报表 | RAGAS 或自己写都行 |

**RAGAS 的核心指标你已经在本章手动实现过了**：

| RAGAS 指标 | 本章对应 |
|---|---|
| `context_recall` | `recall@k` |
| `context_precision` | `MRR`（近似） |
| `faithfulness` | `faithfulness_llm` |
| `answer_relevancy` | `relevance_llm` |

**理解之后再用库，你会知道每个数字怎么来的，也能判断它是否适合你的场景。**

---

## 15.9 💥 失败实验

### 实验 A：把 judge 换成一个很弱的模型

用最小的模型（甚至 Ollama 的小模型）当 judge，跑 `validate_judge`。

**观察**：agreement_rate 是多少？

**预期**：很可能 < 0.6。**这告诉你"judge 模型不能随便选"。**

### 实验 B：让 judge 改成 0-10 分制

**观察**：分数分布是不是集中在 7-8 分（中间偏上）？

**这就是"评分塌缩"**——模型倾向于给中间分数。**三档（1/0.5/0）比十档更可靠。**

### 实验 C：把相关性 prompt 改成"这个答案好不好"

**观察**：`relevance` 分数是否变得很高但实际答非所问？

**结论**：指标的定义必须**窄**。"好不好"太宽，"有没有回答问题"才可测。

---

## 15.10 ✏️ 小练习

### 练习 1（必做）：给你的项目建 30 条评测集

要求：

- 15 条单跳、10 条多跳、5 条"库外问题"（应该拒答）
- 每条标注 `must_contain` 和 `ground_truth`

**验收**：能跑出完整的四层指标。

### 练习 2：做一次真正的 A/B

选一个改动（换 chunk size / 加 rerank / 改 prompt），**只改这一个**，跑出对比表。

**验收**：能说出"提升了多少、成本增加了多少、值不值"。

### 练习 3（进阶）：把评测接进 CI

写一个 `pytest` 测试：如果 `recall@5` 低于阈值，测试失败。

**验收**：故意改坏检索逻辑，CI 能拦住。

---

## 15.11 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 四层评测框架 | `code/common/rag_eval.py` | 第 26 章、项目 C |
| Judge 校验 | `validate_judge` | 所有需要 judge 的场景 |
| 评测集格式 | `evals/rag_cases.json` | 你的项目 |
| A/B 对比器 | `Report.diff` | 第 26 章 |

---

## 15.12 ✅ 验收

1. 四层指标分别能发现什么问题？为什么不能只看总分？
2. 为什么 gold 标注不能用最终文本？应该怎么标？
3. 引用校验为什么是"最高性价比"的检查？
4. Judge 的三个已知偏差是什么？怎么缓解？
5. `agreement_rate` 低于多少就该放弃这个 judge？

**数字验收**：你的评测集有多少条？最优配置的 recall@5 和 faithfulness 分别是多少？

---

## 15.13 延伸阅读

- RAGAS 文档——对照本章的手写实现理解每个指标
- 第 26 章：把评测变成完整的回归体系（结果评估 + 轨迹评估）
- 第 27 章：怎么把评测失败变成复盘文档

---

下一页：[第 16 章 短期记忆：工作记忆与会话窗口](16-短期记忆.md)
