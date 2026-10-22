# 第 24 章 LLMWiki（二）：生成、维护与质量

> **你会遇到的坏事**：你的 wiki 有 300 条条目，看起来很美。三个月后：
>
> - 有 40 条是模型编的（来源指向的原文里根本没有那句话）
> - 有 60 条政策已变但没更新
> - 用户问"退货几天"，检索到两条：一条说 7 天（v1），一条说 15 天（v2），模型随机挑了一条

---

## 24.1 治理的五个环节

```
① 生成（规则 + 模型 + 人工）
   ↓
② 审核（矛盾检测 + 人工确认）
   ↓
③ 发布（版本化，旧的标 outdated）
   ↓
④ 监控（使用率、举报、过时）
   ↓
⑤ 重写（低质量条目进入重写队列）
```

**每一环缺一个，wiki 都会烂。** 最常见的烂法：只做 ①③，跳过 ②④⑤。

---

## 24.2 环节②：矛盾检测（最核心）

完整实现：[`code/common/wiki.py::conflict`](code/common/wiki.py)

```python
def conflict(old: WikiEntry, new_definition: str) -> dict[str, Any]:
    """三个信号：极性翻转 / 数字不符 / 主题相似度"""
    def polarity(text: str) -> bool:
        head = text.split("，")[0]          # 只看主句
        return not any(n in head for n in NEGATIONS)

    pol_old, pol_new = polarity(old.definition), polarity(new_definition)
    nums_old, nums_new = set(_numbers(old.definition)), set(_numbers(new_definition))
    ...
    signals["needs_review"] = score >= 2
```

### ⚠️ 我踩的坑：极性判断不能看整句

第一版我写的是：

```python
def _polarity(text):
    return not any(n in text for n in NEGATIONS)   # ❌ 看整句
```

结果：

```
旧："签收后 7 天内...可申请无理由退货。"      → 有"不"字（"不影响二次销售"）→ 判成否定
新："无理由退货不可申请..."                    → 也判成否定
→ polarity_flip = False，漏检了！
```

**修法：只看第一个逗号前的主句**：

```python
head = text.split("，")[0]
```

### 💻 实测：三种矛盾

```bash
python code/ch24_wiki_ops/demo_wiki_ops.py
```

```
【数字变化（7 天 → 15 天）】⚠️ 需人工审核
  极性翻转：False    数字不符：True
  旧数字：['7']  新数字：['15']
  主题相似度：0.91  评分：3

【极性翻转（可申请 → 不可申请）】⚠️ 需人工审核
  极性翻转：True    数字不符：False
  主题相似度：0.36  评分：2

【新增例外】✅ 可自动通过
  极性翻转：False    数字不符：False
  主题相似度：0.56  评分：1
```

### 为什么这两类必须人工审核

| 类型 | 可能是 | 也可能是 |
|---|---|---|
| 数字变化（7→15 天） | 政策调整 | 模型抄错了 |
| 极性翻转（可以→不可以） | 规则收紧 | 模型理解错了 |

**自动通过 = 把这种不确定直接发布出去。** 在一个客服系统里，这意味着给客户错误的承诺。

**而"新增例外"可以自动通过**——因为它只是补充信息，不会推翻原结论。

---

## 24.3 环节③：版本与软删除

```python
def revise(store, old_id, new_definition, reviewer, auto_approve=False):
    old = store.get(old_id)
    sig = conflict(old, new_definition)

    new = WikiEntry(
        id=f"{old.id}-v{old.version + 1}",
        ...
        status=EntryStatus.PUBLISHED if (auto_approve and not sig["needs_review"]) else EntryStatus.REVIEWING,
        version=old.version + 1,
    )
    store.upsert(new)

    if new.status is EntryStatus.PUBLISHED:
        old.superseded_by = new.id
        old.status = EntryStatus.OUTDATED     # ← 软删除
        store.upsert(old)
```

### 💻 实测：修订后两个版本都在

```
结果：ok=True  新 id=w-refund-v2
状态：reviewing（自动批准=False）
冲突：{'number_mismatch': True, 'old_numbers': ['7'], 'new_numbers': ['10'],
       'needs_review': True, ...}

当前所有版本：
  v1  [published] 签收后 7 天内...   ← 当前（v2 还在审核）
  v2  [reviewing] 签收后 10 天内...
```

**注意：v2 在 `reviewing` 状态时，v1 仍然是 published。**

这是关键设计——**新版本没通过审核前，旧版本继续生效**。否则审核期间系统会没有可用答案。

### 为什么软删除，不真删

因为你要能回答：

> "上个月客户被告知 7 天，为什么现在变成 10 天？"

答案链：`v1(published, 3/1) → v2(reviewing, 3/5) → v2(published, 3/6)`。

**这条链是合规要求**（尤其在医疗、金融、法务场景）。

---

## 24.4 环节④：质量信号

```python
@dataclass
class WikiEntry:
    ...
    hit_count: int = 0           # 被检索命中次数
    helpful_votes: int = 0       # "这条有用"的反馈
    outdated_reports: int = 0    # "这条过时了"的举报
```

💻 实测：

```
条目                 有用票      过时举报     需重写
--------------------------------------------
无理由退货                0         0       否
运费承担                 0         0       否
价格保护                12         0       否
已过期条款                3         8       是
```

**规则：`outdated_reports >= 3` → 进入重写队列。**

### 这些信号怎么接进检索

```python
def score_entry(e: WikiEntry, query: str, now: float | None = None) -> float:
    ...
    quality = (1 + e.helpful_votes * 0.1) / (1 + e.outdated_reports * 0.5)
    usage = 1 + min(e.hit_count, 100) * 0.01
    return overlap * freshness * quality * usage
```

💻 实测：

```
查询：运费谁承担
  0.8000  运费承担        有用票=0 举报=0
  ...
```

**这是 wiki 相对纯 RAG 的核心优势：知识质量是可度量的，而且能直接影响排序。**

纯向量库里，一条"过期 3 年但语义相似"的片段，和"昨天刚更新"的片段，排名可能一样。

---

## 24.5 环节⑤：覆盖率指标（对业务方汇报用）

💻 实测：

```
条目总数：5（当前有效 4）
有来源的比例：100%   ← 可溯源率
有例外说明的比例：25%   ← 例外覆盖率
```

### 这两个指标比"条目数"重要得多

| 指标 | 为什么重要 |
|---|---|
| **可溯源率** | 190 条没来源的条目 < 20 条有来源的条目 |
| **例外覆盖率** | 例外覆盖率低 → 把"通常情况"当"全部情况" → 直接答错 |

**如果业务方问"wiki 做得怎么样"，不要回答"有 300 条"，要回答"可溯源率 92%，例外覆盖率 68%"。**

---

## 24.6 治理的三个自动化

### 自动化 1：定时体检

```python
def health_check(store, tenant_id="default") -> dict:
    published = store.list(status=EntryStatus.PUBLISHED, tenant_id=tenant_id)
    now = time.time()
    return {
        "total": len(published),
        "no_source": [e.id for e in published if not e.sources],
        "no_exceptions": [e.id for e in published if not e.exceptions],
        "stale_90d": [e.id for e in published if (now - e.updated_at) / 86400 > 90],
        "reported": [e.id for e in published if e.outdated_reports >= 3],
        "never_used": [e.id for e in published if e.hit_count == 0],
    }
```

**每周跑一次，输出四类待处理清单**：

| 清单 | 处理方式 |
|---|---|
| 无来源 | 补来源，补不上就下架 |
| 无例外 | 人工复查（可能真没有，也可能漏了） |
| 90 天未更新 | 跟业务确认是否变更 |
| 被举报 ≥3 次 | 进入重写队列 |

### 自动化 2：从对话中发现缺口

用户问了但 wiki 没有的问题（检索得分全部低于阈值）→ **知识缺口**。

```python
def log_gap(question: str, top_score: float) -> None:
    if top_score < 0.3:
        gaps.append({"q": question, "ts": time.time()})
```

**每周看一次 gap 列表，就是天然的"该写什么条目"清单。**

⚠️ **这比"凭感觉决定写什么"有效 10 倍。**

### 自动化 3：从工单中发现过期

客户投诉"你们说的和实际不一致"→ 关联的 wiki 条目自动 +1 outdated_report。

---

## 24.7 一个必须面对的问题：谁来维护

**这是 wiki 项目失败的第一原因，不是技术问题。**

| 模式 | 可持续性 |
|---|---|
| "AI 全自动生成" | ❌ 三个月后全是垃圾 |
| "让工程师顺便维护" | ❌ 没人顺便 |
| **"每个领域指定 owner + 季度复盘"** | ✅ 可行 |
| "把维护嵌入现有流程" | ✅ 最可行 |

### 最可行的做法：嵌入现有流程

```
政策文档变更 → 触发 wiki 条目 draft → 变更人审核 → 发布
```

**不要让 wiki 成为"额外的工作"，要让它成为"改政策时必须做的一步"。**

这也解释了为什么 `EntryStatus.REVIEWING` 必须存在——**它是审核流程的载体**。

---

## 24.8 💥 失败实验

### 实验 A：把极性判断改回"看整句"

**观察**：极性翻转的样本能不能被检出？

**你会亲眼看到"一个 `split` 决定检测成败"。**

### 实验 B：让 v2 一创建就 published

把 `revise` 里的 `auto_approve` 默认改成 True。

**观察**：数字变化（7→15）会不会被直接发布？

**这就是"模型抄错一个数字，客户拿到错误承诺"的完整路径。**

### 实验 C：给所有条目 hit_count = 0

让 wiki 从来没有被检索过。然后问业务方"这 300 条有用吗"——你会发现无法回答。

**`hit_count` 是 wiki 的"使用率证据"。** 没有它，wiki 就是自嗨。

---

## 24.9 ✏️ 小练习

### 练习 1（必做）：实现 health_check

按 24.6 节的清单实现 `health_check()`，跑一遍你的 wiki（哪怕只有 3 条）。

**验收**：输出四类清单，并能对每类说出处理动作。

### 练习 2：接入"知识缺口"日志

在 `search()` 里，当 top1 得分低于 0.3 时记录问题。

**验收**：跑 20 个问题，能输出"该补哪些条目"的清单。

### 练习 3（进阶）：把 wiki 变更接入 HITL

用第 19 章的 `HitlService` 处理 `revise` 的审核环节。

**验收**：`needs_review=True` 的修订会生成审批卡片，批准后才发布。

---

## 24.10 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 矛盾检测 | `code/common/wiki.py::conflict` | 变更流程 |
| 版本修订 | `revise` | 政策更新 |
| 质量信号 | `score_entry` | 检索排序 |
| 覆盖率指标 | `demo_wiki_ops.py` | 汇报材料 |

---

## 24.11 ✅ 验收

1. wiki 治理的五个环节是什么？跳过哪个最致命？
2. 极性判断为什么不能看整句？
3. 新版本在 `reviewing` 时，旧版本应该是什么状态？为什么？
4. 可溯源率和例外覆盖率分别反映什么？
5. 为什么"AI 全自动生成 wiki"不可行？给出一个可持续的模式。

**数字验收**：你的 wiki 可溯源率和例外覆盖率分别是多少？

---

## 24.12 延伸阅读

- 第 19 章：把审核做成 HITL
- 第 26 章：把 wiki 质量指标纳入评测体系
- 项目 C：知识中枢的完整设计

---

下一页：[第 25 章 多 Agent：什么时候该拆，什么时候不该](25-多Agent.md)
