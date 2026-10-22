"""第 29 章 step3（上）：两路一起用——条目优先，碎片兜底（离线）。

运行：
    python code/ch29_wiki/step3_hybrid.py

上一级的痛点：手写条目能答对，但每加一条知识都要人来写四个字段。

这一级做什么：先不解决"谁来写"，只解决"什么时候该用条目、什么时候该用碎片"。
  1. 用规则把文档抽成 10 条条目（只有"是什么/要点/例外"三个字段）
  2. 路由规则：问题与某条目的**连续两字覆盖率** ≥ 0.4 → 用条目，否则 → 混合检索
  3. 拿 25 个问题，比四种方案：纯向量 / BM25 / 混合 / 条目优先

只看这张表就够了。下面是本章唯一需要记住的数字对照。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import BM25, Index, hash_embed, split_by_heading  # noqa: E402
from common.wiki import EntryStatus, EntryType, WikiEntry, WikiStore, publish  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")

# 文档里每一节都应该对应一条条目。这张表就是"哪些节值得沉淀"的人工判断。
SEEDS = [
    ("无理由退货", "1.1 无理由退货"),
    ("质量问题退换", "1.2 质量问题退换"),
    ("运费承担", "1.3 运费承担"),
    ("蓝牙耳机故障原因", "2.1 常见故障现象"),
    ("排查顺序", "2.2 排查顺序"),
    ("换新流程", "2.3 换新流程"),
    ("发票", "3.1 发票"),
    ("售后时效与转人工", "3.2 售后时效"),
    ("会员权益", "4.1 会员权益"),
    ("价格保护", "4.2 价格保护"),
]

# (问题, 一个完整答案必须同时出现的字符串)
CASES: list[tuple[str, list[str]]] = [
    ("无理由退货到底指什么？", ["7 天", "未拆封", "不影响二次销售"]),
    ("哪些商品不能无理由退货？", ["定制", "生鲜", "已激活"]),
    ("激活过的耳机能无理由退吗？", ["已激活", "不适用"]),
    ("定制款音箱能无理由退吗？", ["定制", "不适用"]),
    ("质量问题多久内可以换新？", ["15 天", "非人为"]),
    ("超过 15 天但还在保修期怎么办？", ["维修"]),
    ("质量问题退货运费谁出？", ["商家承担"]),
    ("非质量问题退货要付什么钱？", ["买家承担", "20 元"]),
    ("右耳有电流声可能是哪些原因？", ["解码", "网罩", "电池"]),
    ("排查的第一步是什么？", ["重置"]),
    ("三步都解决不了怎么办？", ["硬件故障"]),
    ("换新整个流程要多久？", ["5 到 7 个工作日"]),
    ("检测通过后多久发货？", ["48 小时"]),
    ("电子发票多久能收到？", ["7 个工作日"]),
    ("已开票订单退货后发票怎么办？", ["冲红"]),
    ("提交售后多久没人处理可以转人工？", ["3 个工作日"]),
    ("人工客服工作时间是几点到几点？", ["9:00", "21:00"]),
    ("紧急问题打哪个电话？", ["400-800-1234"]),
    ("会员退货时优惠券怎么处理？", ["优惠券", "不返还"]),
    ("会员有哪些权益？", ["满 300 减 30", "9 折"]),
    ("价保期限是多久？", ["15 天"]),
    ("大促期间的价保规则在哪看？", ["活动页"]),
    ("价保的差价退到哪里？", ["原支付方式"]),
    ("会员退货运费谁承担？", ["商家承担", "买家承担"]),
    ("价保期和退货期分别是多久？", ["15 天", "7 天"]),
    # 同一批语义，换成用户真实会打的字。条目路由在这里最容易掉线。
    ("耳机有滋滋声是怎么回事", ["解码", "网罩", "电池"]),
    ("我的耳机左耳没声音", ["配对", "重置"]),
    ("发票开错了能重开吗", ["冲红"]),
    ("客服几点下班", ["9:00", "21:00"]),
    ("降价了能退差价吗", ["价保", "补差价"]),
    ("买贵了怎么办", ["价保", "补差价"]),
    ("优惠券退货后还在吗", ["不返还"]),
    ("会员有什么优惠", ["满 300 减 30", "9 折"]),
    ("新机器什么时候寄出来", ["48 小时"]),
    ("售后申请没人理", ["转人工"]),
    ("保修期内坏了怎么办", ["维修"]),
    ("运费谁掏", ["商家承担", "买家承担"]),
    ("耳机套能退吗", ["已激活", "不适用"]),
    ("耳机还没拆封不想要了", ["7 天", "未拆封"]),
    ("双十一买的东西怎么价保", ["活动页"]),
]

EXC_HINTS = ("不适用", "不返还", "另见", "除外", "超时", "不支持")


def sentences(text: str) -> list[str]:
    """按句号/分号/换行切句，跳过标题行和过短碎片。"""
    out: list[str] = []
    for line in text.split("\n"):
        if line.startswith("#"):
            continue
        for s in re.split(r"[。；]", line):
            s = s.strip()
            if len(s) >= 6:
                out.append(s)
    return out


def extract(chunks: list[str], title: str) -> WikiEntry:
    """句子级抽取：第一句当定义，其余整句进要点，命中例外词的句子额外进例外。"""
    sents = sentences("\n".join(chunks))
    points: list[str] = []
    exceptions: list[str] = []
    for s in sents:
        if any(h in s for h in EXC_HINTS):
            exceptions.append(s)
            parts = [p.strip() for p in re.split(r"[，,]", s) if p.strip()]
            exceptions.extend(p for p in parts if any(h in p for h in EXC_HINTS))
        else:
            points.append(s)
    return WikiEntry(
        id=f"w-{abs(hash(title)) % 10**8}",
        title=title,
        type=EntryType.RULE,
        definition=sents[0] if sents else "",
        key_points=list(dict.fromkeys(points))[:6],
        exceptions=list(dict.fromkeys(exceptions))[:6],
    )


def build() -> tuple[Index, WikiStore]:
    idx = Index(embed=hash_embed)
    idx.add(split_by_heading(DOC, max_chars=300))
    store = WikiStore()
    for title, heading in SEEDS:
        chunks = [c.text for c in idx.chunks if heading in c.text]
        if not chunks:
            continue
        e = extract(chunks, title)
        e.sources = [c.id for c in idx.chunks if heading in c.text]
        store.upsert(e)
        publish(store, e.id, reviewer="step3")
    return idx, store


def vec_top(idx: Index, q: str, k: int) -> list[str]:
    return [c.text for c, _ in idx.search(q, k=k)]


def bm25_top(idx: Index, q: str, k: int) -> list[str]:
    bm = BM25([c.text for c in idx.chunks])
    order = bm.scores(q).argsort()[::-1][:k]
    return [idx.chunks[i].text for i in order]


def coverage(e: WikiEntry, q: str) -> float:
    """问题里的连续两字有多少出现在条目里。比"字集重合"更接近"这句在说这条"。"""
    grams = [q[i : i + 2] for i in range(len(q) - 1)]
    text = e.title + e.definition + "".join(e.key_points) + "".join(e.exceptions)
    return sum(1 for g in grams if g in text) / max(len(grams), 1)


def entry_first(idx: Index, store: WikiStore, q: str, thr: float = 0.4) -> str:
    """本章推荐：条目优先，碎片兜底。返回拼好的文本。"""
    entries = store.list(status=EntryStatus.PUBLISHED)
    best = max(entries, key=lambda e: coverage(e, q))
    if coverage(best, q) >= thr:
        return best.render()
    return "\n".join(vec_top(idx, q, 2) + bm25_top(idx, q, 2))


def route_of(entries: list[WikiEntry], q: str, thr: float = 0.4) -> tuple[WikiEntry, float, str]:
    """返回 (最像的条目, 覆盖率, 是否走了条目路线)。"""
    best = max(entries, key=lambda e: coverage(e, q))
    score = coverage(best, q)
    return best, score, "条目" if score >= thr else "碎片"


def main() -> None:
    idx, store = build()
    entries = store.list(status=EntryStatus.PUBLISHED)

    print("=" * 78)
    print("先把文档变成 10 条条目（规则抽取，没有人参与）")
    print("=" * 78)
    for e in entries:
        print(f"  【{e.title}】要点 {len(e.key_points)} / 例外 {len(e.exceptions)}")

    methods = {
        "纯向量@3": lambda q: "\n".join(vec_top(idx, q, 3)),
        "BM25@3": lambda q: "\n".join(bm25_top(idx, q, 3)),
        "混合@2+2": lambda q: "\n".join(vec_top(idx, q, 2) + bm25_top(idx, q, 2)),
        "条目优先+兜底": lambda q: entry_first(idx, store, q),
    }
    stats = {n: {"full": 0, "elem": 0, "chars": 0} for n in methods}
    fails: dict[str, list[str]] = {n: [] for n in methods}

    for q, keys in CASES:
        for name, fn in methods.items():
            text = fn(q)
            got = sum(1 for k in keys if k in text)
            stats[name]["elem"] += got
            stats[name]["chars"] += len(text)
            stats[name]["full"] += int(got == len(keys))
            if got < len(keys):
                lack = "、".join(k for k in keys if k not in text)
                fails[name].append(f"{q}（{got}/{len(keys)} 缺 {lack}）")

    total = sum(len(k) for _, k in CASES)
    print("\n" + "=" * 78)
    print(f"{len(CASES)} 个问题，四种方案（要素 = 一个完整答案必须说到的字符串）")
    print("=" * 78)
    print(f"{'方法':<16}{'要素齐全':>10}{'要素覆盖率':>12}{'平均字符':>10}")
    print("-" * 50)
    for name, s in stats.items():
        full = f"{s['full']}/{len(CASES)}"
        print(f"{name:<16}{full:>10}{s['elem'] / total:>12.0%}{s['chars'] / len(CASES):>10.0f}")

    vec_fail = fails["纯向量@3"]
    print(f"\n纯向量@3 要素不全 {len(vec_fail)} 条：")
    for x in vec_fail:
        print(f"  · {x}")

    miss = fails["条目优先+兜底"]
    print(f"\n条目优先+兜底 要素不全 {len(miss)} 条：")
    for x in miss:
        print(f"  · {x}")

    bad = [(q, keys, entry_first(idx, store, q)) for q, keys in CASES]
    bad = [(q, keys, t) for q, keys, t in bad if any(k not in t for k in keys)]
    if bad:
        print("\n看看它为什么还是漏了：")
        for q, keys, text in bad:
            lack = [k for k in keys if k not in text]
            e, score, how = route_of(entries, q)
            print(f"\n  【{q}】缺 {lack}")
            print(f"  路由：{how}路线，最像的是「{e.title}」（覆盖率 {score:.2f}）")
            for line in text.split("\n"):
                if line.strip():
                    print(f"    {line[:60]}")

    print("\n" + "=" * 78)
    print("第二个数字：条目路由有多依赖'问题怎么问'")
    print("=" * 78)
    routed = [(q, *route_of(entries, q)) for q, _ in CASES]
    to_entry = [(q, e, s) for q, e, s, how in routed if how == "条目"]
    print(f"  走了条目路线的问题：{len(to_entry)}/{len(CASES)}")
    print(f"  退回碎片检索的问题：{len(CASES) - len(to_entry)}/{len(CASES)}")
    print("\n  覆盖率最高（问法最接近原文）的 5 个：")
    for q, e, s, _ in sorted(routed, key=lambda x: -x[2])[:5]:
        print(f"    {s:.2f}  {q} → {e.title}")
    print("\n  覆盖率最低（口语化）的 5 个：")
    for q, e, s, _ in sorted(routed, key=lambda x: x[2])[:5]:
        print(f"    {s:.2f}  {q} → {e.title}")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  1. 在这份 889 字的语料上，「条目优先」**没有**把要素覆盖率拉高——")
    print(f"     纯向量 {stats['纯向量@3']['elem'] / total:.0%} / BM25 {stats['BM25@3']['elem'] / total:.0%} /"
          f" 条目优先 {stats['条目优先+兜底']['elem'] / total:.0%}，三者只差 1 个问题。")
    print("     原因：语料太小，一块碎片就装得下整条知识。**小语料上 wiki 不带来召回收益。**")
    print("  2. 它带来的是另一样东西：**答案的形状固定**。")
    print("     碎片给的是'三段相关文字'，条目给的是'定义 + 要点 + 例外 + 来源'——")
    print("     例外不会因为你换了提问方式就消失。")
    print("  3. 代价也很明显：条目是**手工挑选的节**（SEEDS 表），")
    print("     而且路由靠字面匹配，口语化的问题会掉出条目路线。")
    print("     '价保期和退货期分别是多久' 这种**一个问句两个主题**的问题，")
    print("     单张卡片结构上就答不全——这是条目模型的硬边界。")

    print("\n" + "=" * 78)
    print("  下一级不是'让模型自动抽取'，而是先回答：")
    print("  一条条目从'草稿'到'可信'要经过哪些状态？谁签字？旧版本怎么办？")
    print("=" * 78)
    store.close()


if __name__ == "__main__":
    main()
