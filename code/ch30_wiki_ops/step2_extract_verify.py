"""第 43 章 step2：模型抽取，必须配一个"回原文核对"的校验器（离线可跑）。

运行：
    python code/ch30_wiki_ops/step2_extract_verify.py

上一级的痛点：格式检查拦不住"来源造假"——sources 有值不代表那句话来自那里。

这一级做什么："抽取 → 校验 → 拒绝"的流程跑一遍：
  1. 抽取：用第 29 章的规则抽取（真实项目里这一步换模型，见 `demo_wiki_ops_llm.py`）
  2. 校验：定义里的每个数字、每个例外短语，必须能在 sources 指向的原文里找到
  3. 判定：通过 → draft；不通过 → 拒绝，并记录缺了什么

模型抽取最常见的错法是"改写时把 7 天写成 30 天"或"凭空补一条例外"，
这两种都能被"数字/短语回原文核对"抓住。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import Index, hash_embed, split_by_heading  # noqa: E402
from common.wiki import EntryStatus, EntryType, WikiEntry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

SEEDS = [
    ("无理由退货", "1.1 无理由退货"),
    ("质量问题退换", "1.2 质量问题退换"),
    ("运费承担", "1.3 运费承担"),
    ("会员权益", "4.1 会员权益"),
]


def extract(chunks: list[str], title: str) -> WikiEntry:
    """规则抽取（与第 29 章 step3 相同，换成模型时接口不变）。"""
    sents: list[str] = []
    for line in "\n".join(chunks).split("\n"):
        if line.startswith("#"):
            continue
        sents += [s.strip() for s in re.split(r"[。；]", line) if len(s.strip()) >= 6]

    points, exceptions = [], []
    for s in sents:
        if any(h in s for h in ("不适用", "不返还", "另见", "除外")):
            exceptions.append(s)
        else:
            points.append(s)

    return WikiEntry(
        id=f"w-{abs(hash(title)) % 10**8}",
        title=title,
        type=EntryType.RULE,
        definition=sents[0] if sents else "",
        key_points=list(dict.fromkeys(points))[:6],
        exceptions=list(dict.fromkeys(exceptions))[:6],
        status=EntryStatus.DRAFT,
    )


def verify(e: WikiEntry, source_text: str) -> tuple[bool, list[str]]:
    """可溯源校验：数字和例外短语必须能在来源原文里找到。"""
    problems: list[str] = []
    for n in re.findall(r"\d+", e.definition):
        if n not in source_text:
            problems.append(f"定义里的数字 {n} 不在原文")
    for exc in e.exceptions:
        core = re.split(r"[，,]", exc)[0]
        if core not in source_text:
            problems.append(f"例外「{core}」不在原文")
    return (not problems), problems


def verify_soft(e: WikiEntry, source_text: str) -> tuple[bool, list[str]]:
    """宽松版：例外只要有一个关键短语（前 6 字）能对上就算通过。

    宽松能减少误杀，但也会放过"把例外写歪"的条目——这就是取舍的代价。
    """
    problems: list[str] = []
    for n in re.findall(r"\d+", e.definition):
        if n not in source_text:
            problems.append(f"定义里的数字 {n} 不在原文")
    for exc in e.exceptions:
        if exc[:6] not in source_text:
            problems.append(f"例外「{exc[:12]}…」不在原文")
    return (not problems), problems


def main() -> None:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=300))

    print("=" * 80)
    print("抽取 → 校验：每条条目都要拿到自己的'证据'")
    print("=" * 80)
    print(f"{'条目':<16}{'要点':>4}{'例外':>4}{'严格校验':>8}{'宽松校验':>8}   严格版报的问题")
    print("-" * 80)

    entries: list[tuple[WikiEntry, str]] = []
    for title, heading in SEEDS:
        chunks = [c.text for c in idx.chunks if heading in c.text]
        e = extract(chunks, title)
        e.sources = [c.id for c in idx.chunks if heading in c.text]
        src = "\n".join(chunks)
        ok_strict, p_strict = verify(e, src)
        ok_soft, _ = verify_soft(e, src)
        entries.append((e, src))
        print(f"{title:<16}{len(e.key_points):>4}{len(e.exceptions):>4}"
              f"{('✅' if ok_strict else '❌'):>8}{('✅' if ok_soft else '❌'):>8}"
              f"   {'；'.join(p_strict) or '—'}")

    print("\n" + "=" * 80)
    print("再看一个真实会遇到的场景：模型把 7 天写成了 30 天")
    print("=" * 80)
    e0 = entries[0][0]
    tampered = WikiEntry(
        id="w-tampered", title=e0.title, type=e0.type,
        definition=e0.definition.replace("7 天", "30 天"),
        key_points=e0.key_points, exceptions=e0.exceptions, sources=e0.sources,
    )
    ok, problems = verify(tampered, entries[0][1])
    print(f"  篡改后的定义：{tampered.definition}")
    print(f"  严格校验：{'✅ 通过' if ok else '❌ 拒绝'}  {problems}")
    print("\n  👉 这就是为什么 sources 必须存 chunk id、检索引擎要能按 id 取回原文。")
    print("     只存'来源: 售后政策手册'这种模糊引用，等于没有来源。")

    print("\n" + "=" * 80)
    print("结论：三种校验，管的不是一件事")
    print("=" * 80)
    print("  · 格式校验（step1）：字段齐不齐           → 拦不住任何真实故障")
    print("  · 严格溯源（本文件 verify）：逐字对原文     → 会误杀合理的同义改写")
    print("  · 宽松溯源（verify_soft）：关键短语对原文   → 会放过写歪的例外")
    print("  真实项目通常：**抽取用严格、人工审核时放宽**——机器守底线，人管质量。")

    print("\n  还有一个更根本的问题没解决：")
    print("  抽取通过校验，只说明'这句话原文有'，")
    print("  不说明'这条条目该不该存在、旧的那条怎么办'。")
    print("  → 下一级：版本状态机。")


if __name__ == "__main__":
    main()
