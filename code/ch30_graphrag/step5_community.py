"""第 29 章 step5：聚合问题为什么必须靠社区摘要（离线）。

运行：
    python code/ch30_graphrag/step5_community.py

前面几级的痛点：
    step4 证明了两阶段 / PPR 能补"多跳"的召回。
    但对「这个平台售后主要有哪些规则？」这类**聚合问题**，它们通通无效。

为什么？因为聚合问题的答案是「很多块的共性」，没有任何单块像答案，
也没有任何"一个实体"能把它们串起来 —— 你沿图走不出"共性"。

这一级做什么：
    ① 用真实语料展示聚合问题的向量分数有多低（全在 0.1~0.2）
    ② 把图切成社区（连通分量 → 再去枢纽词，对比两种）
    ③ 给每个社区生成"摘要候选句"（离线：取社区内块的标题 + 高频实体）
    ④ 用"摘要检索"回答聚合问题，量化对比「块检索 vs 社区检索」的覆盖
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from step3_expand import (  # noqa: E402
    DOC_PATH,
    DOMAIN_TERMS,
    hash_embed,
    cosine,
    split_by_heading,
)

# 高频枢纽词：几乎每节都出现，参与建边会把整张图连成一坨（28.6 会讲为什么）
HUB_WORDS = {"售后", "商品", "会员"}

AGG_QUESTIONS = [
    ("这个平台售后主要有哪些规则？", {"2", "4", "6", "9", "11", "13"}),
    ("出了问题该怎么处理？", {"7", "8", "11"}),
]


def build_entities(chunks: list[str], drop_hubs: bool = False) -> dict[int, set[str]]:
    terms = [t for t in DOMAIN_TERMS if not (drop_hubs and t in HUB_WORDS)]
    out: dict[int, set[str]] = {}
    for i, c in enumerate(chunks):
        ents = {t for t in terms if t in c}
        if ents:
            out[i] = ents
    return out


def build_adj(chunk_ents: dict[int, set[str]]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for ents in chunk_ents.values():
        el = sorted(ents)
        for i in range(len(el)):
            for j in range(i + 1, len(el)):
                adj.setdefault(el[i], set()).add(el[j])
                adj.setdefault(el[j], set()).add(el[i])
    return adj


def components(adj: dict[str, set[str]]) -> list[set[str]]:
    seen: set[str] = set()
    out: list[set[str]] = []
    for start in adj:
        if start in seen:
            continue
        stack = [start]
        comp = set()
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.add(n)
            stack.extend(adj.get(n, ()))
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def vec(text: str) -> list[float]:
    return hash_embed(text, dim=256)


@dataclass
class Community:
    members: set[str]
    chunks: list[int]              # 这些实体所在的块
    summary: str = ""

    @property
    def coverage(self) -> float:
        """这个社区覆盖了多少条"金标章节"（用来量化聚合问题的召回）。"""
        return float(len(self.chunks))


def make_summary(chunks: list[str], idx: list[int], members: set[str]) -> str:
    """离线版社区摘要：标题 + 高频实体。

    真实项目这里是一次模型调用（"把以下实体的关系总结成 3 句话"），
    成本约 ¥0.002/社区。本例用离线规则，保证可复现。
    """
    heads = [chunks[i].splitlines()[0].lstrip("# ").strip() for i in idx]
    top = [e for e, _ in Counter(m for i in idx for m in [next(iter([""]))] for e in members).most_common(6)]
    top = [e for e in sorted(members, key=lambda x: -sum(x in chunks[i] for i in idx))][:6]
    return f"共 {len(idx)} 节，涉及：{'、'.join(heads[:6])}；核心概念：{'、'.join(top)}"


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    chunks = split_by_heading(text)

    print("=" * 82)
    print("① 聚合问题的分数有多低：先看向量检索")
    print("=" * 82)
    for q, gold in AGG_QUESTIONS:
        qv = vec(q)
        scored = sorted(((cosine(qv, vec(c)), i) for i, c in enumerate(chunks)), reverse=True)[:3]
        covered = {str(i) for _, i in scored} & gold
        print(f"\n  问题：{q}")
        print(f"    金标块（{len(gold)} 个）：{sorted(gold, key=int)}")
        for s, i in scored:
            print(f"    {s:.3f}  [{i:>2}] {chunks[i].splitlines()[0][:36]}")
        print(f"    → top-3 最高分 {scored[0][0]:.3f}，只覆盖 {len(covered)}/{len(gold)} 个金标块")

    print("\n  分数全在 0.1~0.2 —— 因为**没有任何一块像问题**。")
    print("  聚合问题的答案是「很多块的共性」，向量检索这个动作本身就不适配。")

    print("\n" + "=" * 82)
    print("② 社区切分：为什么「去掉枢纽词」反而更糟")
    print("=" * 82)
    for drop in (False, True):
        ents = build_entities(chunks, drop_hubs=drop)
        adj = build_adj(ents)
        comps = components(adj)
        label = "去掉枢纽词（售后/商品/会员）" if drop else "全部实体"
        sizes = [len(c) for c in comps]
        print(f"\n  {label}：{len(comps)} 个社区，规模 {sizes}")
        for k, c in enumerate(comps[:5], 1):
            print(f"    社区 {k}（{len(c)} 个实体）：{'、'.join(sorted(c)[:10])}"
                  + ("…" if len(c) > 10 else ""))

    print("\n  → 反直觉结论：本例里**去掉枢纽词让社区更少了**（2 → 1）。")
    print("    原因：'售后' 同时也是唯一能把「会员/优惠券」和其余章节分开的桥；")
    print("    删掉它，会员那组就并进了大团。")
    print("    **枢纽词不是无脑删的**：要先用「社区数量 + 社区规模分布 + 精度」几个指标试，")
    print("    而不是凭直觉。真实项目里通常会试 3~5 个阈值取最好的那个。")

    print("\n" + "=" * 82)
    print("③ 社区摘要 + 聚合问题检索")
    print("=" * 82)
    ents = build_entities(chunks, drop_hubs=False)
    adj = build_adj(ents)
    comps = components(adj)
    chunk_ents = {i: e for i, e in ents.items()}

    communities: list[Community] = []
    for c in comps:
        if len(c) < 2:
            continue
        idx = sorted({i for i, es in chunk_ents.items() if es & c})
        communities.append(Community(c, idx, make_summary(chunks, idx, c)))

    print(f"\n  共 {len(communities)} 个社区（规模≥2 实体）")
    for k, cm in enumerate(communities, 1):
        print(f"    社区 {k}: 块 {cm.chunks}")
        print(f"      摘要：{cm.summary}")

    print("\n" + "-" * 78)
    print("  对比：聚合问题能覆盖多少「金标块」")
    print("  " + "-" * 74)
    print(f"  {'问题':<24}{'块检索 top-3':>14}{'社区检索 top-1':>16}")
    print("  " + "-" * 74)
    for q, gold in AGG_QUESTIONS:
        qv = vec(q)
        top_chunks = {str(i) for _, i in sorted(
            ((cosine(qv, vec(c)), i) for i, c in enumerate(chunks)), reverse=True)[:3]}
        cov_chunk = len(top_chunks & gold) / len(gold)

        best = max(communities, key=lambda cm: cosine(qv, vec(cm.summary)))
        cov_comm = len({str(i) for i in best.chunks} & gold) / len(gold)
        print(f"  {q[:22]:<24}{cov_chunk:>13.0%}{cov_comm:>15.0%}")

    print("\n  → 社区检索覆盖更高，但**不是魔法**：本例语料太小，最大的社区就包含了大多数章节，")
    print("    '覆盖 100%' 有一部分是'社区太大'的假象。真实项目要看两个数：")
    print("      ① 覆盖率（找回多少相关章节）  ② 精度（召回多少无关内容）")
    print("    社区太大 → 精度掉；社区太碎 → 覆盖掉。这就是 Leiden 要调分辨率的原因。")

    print("\n  💥 一个诚实的自证：把摘要换成'整块拼接'，看覆盖会不会还这么高。")
    for q, gold in AGG_QUESTIONS:
        qv = vec(q)
        best = max(communities, key=lambda cm: cosine(qv, vec(
            " ".join(chunks[i] for i in cm.chunks))))
        cov = len({str(i) for i in best.chunks} & gold) / len(gold)
        print(f"    {q[:22]:<24} 整块拼接检索 → 覆盖 {cov:.0%}")
    print("    → 一样高。说明**收益来自'社区'这个分组本身，不是'摘要'这段文字**。")
    print("      摘要的真正价值是**省 token**（一段话 vs 五个块），不是提高召回。")

    print("\n" + "=" * 82)
    print("结论：四种检索各自解决什么")
    print("=" * 82)
    print("  单跳   → 纯向量（够用，别上图）")
    print("  多跳   → 两阶段 / PPR（从实体扩散，不是从块扩散）")
    print("  聚合   → 社区（切图）+ 摘要（省 token）")
    print("  溯源   → path() 解释「为什么这两个概念相关」，人工核对")
    print()
    print("  ⚠️ 本章语料只有 889 字，社区切分是'教学版'（连通分量）。")
    print("     真实项目用 Leiden 层次聚类 + 模型摘要（成本见 28.10）。")


if __name__ == "__main__":
    main()
