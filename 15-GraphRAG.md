# 第 15 章 GraphRAG：当向量检索答不出多跳问题

> **你会遇到的坏事**：用户问"这个平台售后方面都有哪些规则"。你的 RAG 检索回来 5 个片段：退款、运费、发票、换新、会员。模型把它们拼在一起，答得零散、重复、还漏了三条。
>
> **因为没有任何一个片段是"答案"——答案是这些片段之间的关系。**

---

## 14.1 向量检索回答不了的三类问题

| 类型 | 例子 | 为什么向量失败 |
|---|---|---|
| **多跳** | "会员退货时用掉的优惠券能拿回来吗" | 答案需要先命中"会员"，再跳到"优惠券返还规则"；向量只看"整体相似" |
| **聚合** | "售后主要有哪些规则" | 答案分散在 10 个片段里，**没有一片是答案** |
| **关系** | "运费和检测费是什么关系" | 向量能给相关片段，但给不出"为什么相关" |

**GraphRAG 的核心思想**：先把知识组织成**图**（实体 + 关系），检索时沿着图走，而不是只做向量相似度匹配。

---

## 14.2 三步：抽取 → 建图 → 扩展检索

完整实现：[`code/common/graph_rag.py`](code/common/graph_rag.py)

### 第 1 步：抽取三元组

```python
@dataclass
class Relation:
    src: str        # 主体
    rel: str        # 关系
    dst: str        # 客体
    chunk_ids: set[str]   # ← 关键：记录这条关系来自哪个 chunk
```

**`chunk_ids` 是把图接回原文的桥**。没有它，你只能给出"实体关系"，说不出"证据在哪"——而 RAG 的核心要求是**可溯源**。

两种抽取方式：

**规则抽取**（零成本，精确率高，召回率低）：

```python
# 模板 1："X 由 Y 承担"
for m in re.finditer(r"([\u4e00-\u9fff]{2,6})(?:由|需支付|需缴纳)([\u4e00-\u9fff]{2,6})", text):
    a, b = m.group(1), m.group(2)
    if a in DOMAIN_TERMS and b in DOMAIN_TERMS:   # ← 词典约束，避免切坏短语
        triples.append((b, "适用于", a))

# 共现：同一块里的实体两两相连
```

⚠️ **词典约束不能省**。我第一版没加约束，抽出了"可申请无理"这种被切坏的实体，图里全是噪声。

**模型抽取**（成本高，召回率高）：

```python
class Triple(BaseModel):
    src: str = Field(description="主体实体（名词短语，尽量用原文用词）")
    rel: str = Field(description="关系（动词短语）")
    dst: str = Field(description="客体实体")

class Triples(BaseModel):
    items: list[Triple]

out = llm.with_structured_output(Triples).invoke(prompt)
```

**生产中推荐"双通道"**：规则处理高频句式（零成本），LLM 补长尾。

### 第 2 步：建图 + BFS 扩展

```python
def expand(self, seeds: Iterable[str], hops: int = 2) -> dict[str, int]:
    """从种子实体出发做 BFS，返回 {实体: 距离}"""
    dist, q = {}, deque()
    for s in seeds:
        if s in self.entities:
            dist[s] = 0; q.append((s, 0))
    while q:
        cur, d = q.popleft()
        if d >= hops:
            continue
        for r in list(self._out.get(cur, [])) + list(self._in.get(cur, [])):
            nxt = r.dst if r.src == cur else r.src
            if nxt not in dist:
                dist[nxt] = d + 1
                q.append((nxt, d + 1))
    return dist
```

**为什么是 2 跳**：3 跳以上的噪声急剧增加（几乎所有实体都会连通）。这是论文里的经验值。

### 第 3 步：图增强检索

```python
def search(self, query, k=5, hops=2, seed_k=3):
    seeds = self.index.search(query, k=seed_k)      # 1. 向量召回种子
    seed_chunks = [c.id for c, _ in seeds]

    seed_ents = set()
    for cid in seed_chunks:                          # 2. 种子里的实体
        seed_ents.update(self.chunk_entities.get(cid, []))

    dist = self.graph.expand(seed_ents, hops=hops)   # 3. 图扩展

    scored = {cid: 1.0 for cid in seed_chunks}       # 4. 按距离打分
    for ent, d in dist.items():
        for cid in self.graph.entities[ent].chunk_ids:
            scored[cid] = max(scored.get(cid, 0.0), 1.0 / (1 + d))

    return sorted(scored.items(), key=lambda x: -x[1])[:k]
```

**注意 `1.0 / (1 + d)`**：距离越远权重越低。这保证了"图扩展"不会压过"向量直接命中"。

---

## 14.3 💻 跑一遍

```bash
python code/ch14_graphrag/demo_graphrag.py
```

**不需要 API。** 我实际跑出来的（修复规则抽取之后）：

```
语料：15 块    实体：18    关系：24

D. 解释能力：为什么这两个概念相关
  优惠券 → 退货：无路径（说明这两个概念在文档里没有直接关联）
  运费 → 质量问题：运费 → 质量问题 / 运费 → 检测费 → 质量问题
  电流声 → 换新：电流声 → 网罩 → 换新
```

**最后一行是 GraphRAG 最独特的能力**：它不只能找到相关文档，还能**说出"为什么相关"**。

`电流声 → 网罩 → 换新` 这条链，直接就是"电流声可能是网罩堵了，清理无效则走换新"的推理路径。

**纯向量检索给不出这个。** 它只能告诉你"这两块都和你问题有点像"。

### 关于这份报告的可信度（必须说明）

⚠️ **这份语料的规模太小（889 字、18 个实体），GraphRAG 的优势体现不出来。**

- 第 A 组（单跳）向量就够了，图扩展没带来增益
- 第 B 组（多跳）在这个语料上向量也能命中，因为答案那块同时包含"会员"和"优惠券"
- 第 C 组（聚合）才是真正需要图的地方

**你需要在自己的真实语料上验证**（>5 万字、多跳问题占比 >20%）。否则上 GraphRAG 只是给自己增加复杂度。

---

## 14.4 社区摘要：回答"全局问题"的唯一方式

这是 GraphRAG 最贵、也最有价值的部分。

**问题**：用户问"这个平台售后主要有哪些规则"。这个问题**没有对应的文档片段**——因为每一条规则都在各自的章节里。

**做法**：

```
1. 用聚类算法（Leiden）把图分成若干"社区"（主题圈子）
2. 每个社区让模型写一段摘要
3. 检索时，除了检索原始 chunk，也检索社区摘要
```

```python
def communities(self) -> list[set[str]]:
    """连通分量近似（真正的 GraphRAG 用 Leiden 层次聚类）"""
    seen, out = set(), []
    for e in self.entities:
        if e in seen: continue
        comp, q = set(), deque([e])
        while q:
            cur = q.popleft()
            if cur in comp: continue
            comp.add(cur)
            for r in self.neighbors(cur, "both"):
                nxt = r.dst if r.src == cur else r.src
                if nxt not in comp: q.append(nxt)
        seen |= comp
        out.append(comp)
    return out


def summarize_community(llm, members, relations) -> str:
    prompt = f"""下面是知识图谱中一个主题社区的实体关系。请用 3 句话总结这个主题。
实体：{', '.join(sorted(members)[:30])}
关系：{rel_text}
总结（不要罗列，要归纳）："""
    return llm.invoke(prompt).content
```

**为什么这招有效**：它把"聚合问题"从"检索 10 个片段"变成了"检索 1 段摘要"。

**代价**：
- 建图时就要跑一遍全量摘要（10 万文档 = 几万次调用）
- 文档更新时要重新摘要

---

## 14.5 GraphRAG 的成本：为什么大多数人用不上

| 环节 | 成本 | 说明 |
|---|---|---|
| 实体抽取 | 每千字 1 次调用 | 全量文档都要做 |
| 关系抽取 | 同上 | |
| 社区聚类 | 计算密集（Leiden） | 需要图计算 |
| 社区摘要 | 每个社区 1 次调用 | 社区越多越贵 |
| 增量更新 | **最痛** | 新增文档要重新抽取 + 可能改变社区 |

**总成本通常是普通 RAG 的 5–20 倍。**

### 什么时候值得上 GraphRAG

**判据（三条全满足才上）**：

1. 你的用户问题里，**多跳/聚合类占比 > 20%**
2. 你的数据是**关系密集型**（政策、法规、医疗、供应链、组织架构）
3. 你有预算做**离线构建**（增量更新可接受的延迟）

**否则别上。** 先用第 13 章的混合检索 + 查询改写，能解决 80% 的问题。

### 轻量替代：元数据图谱

如果你只是想要"一点关系能力"，不需要全量 GraphRAG：

```python
# 只建一层关系：文档 → 章节 → 关键词
# 检索时按 "文档分组" 合并结果
```

成本几乎为零，能解决"同一话题的碎片合并"这个最常见的问题。

---

## 14.6 GraphRAG 和 LLMWiki 的关系

你会问：**GraphRAG 和下一章的 LLMWiki 有什么区别？**

| 维度 | GraphRAG | LLMWiki（第 24 章） |
|---|---|---|
| 知识形态 | 实体-关系三元组 | 结构化条目（含结论、反例、来源） |
| 构建方式 | 自动抽取 | 抽取 + 人工审核 |
| 更新成本 | 高（要重建社区） | 低（改条目即可） |
| 擅长 | 关系推理、多跳 | 概念解释、口径统一 |
| 谁维护 | 无人（全自动） | 有人审核 |

**它们是互补的**：

- GraphRAG 解决"连接"（A 和 B 什么关系）
- LLMWiki 解决"定义"（A 到底是什么、什么情况下不适用）

**项目 C（企业知识中枢）会把两者串起来。**

---

## 14.7 💥 失败实验

### 实验 A：去掉词典约束

把 `extract_triples_rule` 里的 `if a in DOMAIN_TERMS and b in DOMAIN_TERMS` 删掉。

**观察**：实体列表里出现什么？

**你会看到**："可申请无理"、"码产品不适用无理" 这类切坏的短语。**图的噪声翻倍，检索质量下降。**

**这是规则抽取最常见的事故**，而它不会报错——只是图变脏了。

### 实验 B：把 hops 改成 4

**观察**：图扩展召回的 chunk 数量、质量变化？

**预期**：几乎召回全库，噪声淹没信号。**这就是"为什么是 2 跳"。**

### 实验 C：只建图不用图

把 `GraphRetriever.search` 的 `hops` 设成 0。

**观察**：和纯向量检索的结果是否完全一样？

**结论**：如果一样，说明你的图**没有带来任何增益**——你可能白建了。

---

## 14.8 ✏️ 小练习

### 练习 1（必做）：用 LLM 抽取三元组

用 `extract_triples_llm` 替换规则抽取，比较：

| 指标 | 规则 | LLM |
|---|---|---|
| 实体数 | ? | ? |
| 关系数 | ? | ? |
| 抽取准确率（人工抽查 20 条） | ? | ? |
| 成本 | 0 | ? |

**验收**：能说出"多花的钱换来了什么"。

### 练习 2：加"关系类型"的语义

现在关系只有 `适用于`、`可由`、`共现于`。设计一套**领域关系类型**：

```python
REL_TYPES = ["依赖", "冲突", "前置条件", "例外", "替代方案"]
```

**验收**：同一个问题，用语义关系比用共现关系，检索结果更准。

### 练习 3（进阶）：社区摘要接进检索

把社区摘要也当成一种"chunk"加进索引。

**验收**：聚合类问题（"售后有哪些规则"）的答案覆盖率明显提升。

---

## 14.9 📦 本章沉淀

| 产出 | 文件 | 后续使用 |
|---|---|---|
| 图数据结构 + BFS/路径 | `code/common/graph_rag.py` | 项目 C |
| 规则抽取 | `extract_triples_rule` | 低成本场景 |
| LLM 抽取 | `extract_triples_llm` | 生产场景 |
| 图增强检索 | `GraphRetriever` | 项目 C |
| 社区近似 | `communities()` | 全局问答 |

---

## 14.10 ✅ 验收

1. 向量检索回答不了哪三类问题？各举一例。
2. `Relation.chunk_ids` 为什么必须有？
3. 为什么图扩展只做 2 跳？跳数加大会怎样？
4. 社区摘要解决什么问题？它的成本在哪？
5. 什么情况下**不该**用 GraphRAG？给出三个判据。

**数字验收**：在你的语料上，图扩展相比纯向量，多跳问题的召回率提升多少？成本增加多少？

---

## 14.11 延伸阅读

- Microsoft GraphRAG 论文（2024）——Leiden 聚类 + 社区摘要的原始设计
- 第 13 章：先用混合检索解决 80% 的问题
- 第 24 章：LLMWiki 如何与图互补

---

下一页：[第 16 章 RAG 评测：把"感觉变了"变成数字](16-RAG评测.md)
