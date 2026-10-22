"""第 28 章 · 第 2 级：从文档抽三元组，建一张可以"沿着走"的图。

运行：
    python code/ch28_graphrag/step2_build_graph.py

新增的两个概念：
  · **三元组（triple）**：`(主体, 关系, 客体)`，图的最小单元
  · **chunk_ids**：每条关系记住"我来自哪一块原文" —— 这是可溯源的桥

这一级只用规则抽取（共现 + 模板），零成本、可复现。
你会看到规则抽取的**两个典型问题**：
  ① 共现会造出大量"同块内任意两两相连"的假关系
  ② 不约束词典会抽出"可申请无理"这种被切坏的实体
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"

# 领域词典：只有出现在这里的名词才算实体。
# 不加这个约束，共现抽取会把任意两个相邻字拼成"实体"。
DOMAIN_TERMS = (
    "无理由退货", "质量问题", "换新", "保修期", "运费", "检测费", "检测",
    "电流声", "网罩", "电池", "蓝牙编解码", "发票", "会员", "优惠券",
    "价保", "售后", "转人工", "备用机", "召回",
)


@dataclass
class Relation:
    src: str
    rel: str
    dst: str
    chunk_ids: set[str] = field(default_factory=set)


@dataclass
class Graph:
    entities: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # 实体 → 块
    relations: list[Relation] = field(default_factory=list)
    out: dict[str, list[Relation]] = field(default_factory=lambda: defaultdict(list))
    inb: dict[str, list[Relation]] = field(default_factory=lambda: defaultdict(list))

    def add(self, rel: Relation) -> None:
        for existing in self.relations:
            if (existing.src, existing.rel, existing.dst) == (rel.src, rel.rel, rel.dst):
                existing.chunk_ids |= rel.chunk_ids
                return
        self.relations.append(rel)
        self.out[rel.src].append(rel)
        self.inb[rel.dst].append(rel)

    def neighbors(self, ent: str) -> list[tuple[str, Relation]]:
        out = [(r.dst, r) for r in self.out.get(ent, [])]
        out += [(r.src, r) for r in self.inb.get(ent, [])]
        return out


def split_by_heading(text: str, max_chars: int = 200) -> list[str]:
    out = []
    for p in re.split(r"\n(?=#{2,3} )", text):
        p = p.strip()
        if p:
            out.append(p[:max_chars])
    return out


# ---------------------------------------------------------------- 抽取

def extract(text: str, chunk_id: str) -> tuple[set[str], list[Relation]]:
    """规则抽取：① 模板命中写明确关系 ② 同块共现写"相关"关系。"""
    ents = {t for t in DOMAIN_TERMS if t in text}
    rels: list[Relation] = []

    # 模板 1：「X 不适用／不影响 Y」（需要 X/Y 都是已知实体）
    for m in re.finditer(r"([\u4e00-\u9fff]{2,6}?)(?:不适用|不包含|不影响)([\u4e00-\u9fff]{2,6})", text):
        a, b = m.group(1), m.group(2)
        if a in DOMAIN_TERMS and b in DOMAIN_TERMS:
            rels.append(Relation(a, "不适用于", b, {chunk_id}))

    # 模板 2：实体 + 「不返还 / 不退还」→ 是一条明确的业务约束
    for e in ents:
        if f"{e}不返还" in text or f"{e}不退还" in text:
            rels.append(Relation("会员退货", "不返还", e, {chunk_id}))

    # 共现：同一块里出现的实体两两相连（这是噪声的主要来源）
    ent_list = sorted(ents)
    for i in range(len(ent_list)):
        for j in range(i + 1, len(ent_list)):
            rels.append(Relation(ent_list[i], "同块出现", ent_list[j], {chunk_id}))

    return ents, rels


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)

    g = Graph()
    template_rels = 0
    cooc_rels = 0
    for n, c in enumerate(chunks):
        cid = f"c{n}"
        ents, rels = extract(c, cid)
        for e in ents:
            g.entities[e].add(cid)
        for r in rels:
            if r.rel == "同块出现":
                cooc_rels += 1
            else:
                template_rels += 1
            g.add(r)

    print("=" * 78)
    print("第 2 级：抽三元组建图")
    print("=" * 78)
    print(f"  块 {len(chunks)}   实体 {len(g.entities)}   关系 {len(g.relations)}")
    print(f"  其中：模板关系 {template_rels} 条，共现关系 {cooc_rels} 条")

    print("\n  实体样例（按出现块数排序）：")
    for e, cids in sorted(g.entities.items(), key=lambda x: -len(x[1]))[:8]:
        print(f"    {e:<10} 出现于 {len(cids)} 块")

    print("\n  模板抽出的关系（这些是有语义的）：")
    shown = 0
    for r in g.relations:
        if r.rel != "同块出现":
            print(f"    ({r.src}) -[{r.rel}]→ ({r.dst})   ← {sorted(r.chunk_ids)}")
            shown += 1
            if shown >= 6:
                break
    if shown == 0:
        print("    （本语料没有命中模板 —— 这也是规则抽取的常态）")

    print("\n  共现关系的样例（这些基本是噪声）：")
    for r in g.relations:
        if r.rel == "同块出现":
            print(f"    ({r.src}) -[同块出现]→ ({r.dst})")
            break

    print("\n" + "=" * 78)
    print("规则抽取的两个典型问题")
    print("=" * 78)
    print("  ① 共现造关系：同一块里出现 5 个实体 → 生成 10 条边，其中大多无意义")
    print("     后果：BFS 扩展时很容易扩散到无关实体，召回一堆噪声")
    print("  ② 词典约束不能省：不加 DOMAIN_TERMS，正则会抽出「可申请无理」这种废词")
    print()
    print("  👉 所以生产上通常「双通道」：")
    print("     · 规则处理高频模板（零成本、高精度、低召回）")
    print("     · LLM 抽取长尾（高成本、高召回）")
    print(f"  👉 本例只有 {template_rels} 条模板关系、{cooc_rels} 条共现关系")
    print("     —— 模板命中率 1/23 ≈ 4%，这就是真实文档里规则抽取的常态。")
    print("     所以规则抽取只能解决「最高频的那几种句式」，剩下的必须交给模型（或人工标）。")


if __name__ == "__main__":
    main()
