"""第 24 章 step2：给一条知识定一个固定形状（离线，10 秒出结果）。

运行：
    python code/ch24_wiki/step2_entry_shape.py

上一级的痛点：`step1` 里"激活过的耳机能退吗"取回 3 个片段，要素命中 0/2——
因为"已激活不适用"这句藏在另一块里，而 top-3 没收进来。

这一级做什么：把每条知识写成一个**四字段对象**（是什么 / 要点 / 例外 / 来源），
再试两种取法：只取「是什么 + 例外」（约 65 字符），以及取整条（约 127 字符）。
然后说明：**形状对了，但"谁来填这四个字段"没解决**。

本文件刻意不用 `common/wiki.py`，用裸 dict 写，让你看清"形状"本身。
"""
from __future__ import annotations

# 四个固定字段。字段名就是"这一段文字在回答什么"。
ENTRIES: list[dict] = [
    {
        "title": "无理由退货",
        "definition": "签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。",
        "key_points": ["7 天内", "未拆封", "不影响二次销售"],
        "exceptions": ["定制类商品不适用", "生鲜类商品不适用", "已激活的数码产品不适用"],
        "sources": ["c2"],
    },
    {
        "title": "质量问题退换",
        "definition": "签收后 15 天内出现非人为损坏的质量问题，可申请换新或退货。",
        "key_points": ["15 天内", "非人为损坏", "可选换新或退货"],
        "exceptions": ["超过 15 天但在保修期内只能走维修"],
        "sources": ["c4"],
    },
    {
        "title": "退货运费承担",
        "definition": "非人为质量问题的往返运费由商家承担；人为损坏或非质量问题由买家承担。",
        "key_points": ["质量问题商家承担", "非质量问题买家承担", "非质量问题另付检测费 20 元"],
        "exceptions": [],
        "sources": ["c6"],
    },
]


def render(e: dict) -> str:
    """渲染顺序不是随意的：例外**紧跟**要点，不能放最后。"""
    parts = [f"# {e['title']}", e["definition"]]
    if e["key_points"]:
        parts.append("## 要点\n" + "\n".join(f"- {x}" for x in e["key_points"]))
    if e["exceptions"]:
        parts.append("## 例外\n" + "\n".join(f"- {x}" for x in e["exceptions"]))
    if e["sources"]:
        parts.append("## 来源\n" + "\n".join(f"- {x}" for x in e["sources"]))
    return "\n\n".join(parts)


def brief(e: dict) -> str:
    """只喂「是什么 + 例外」——这是回答"能不能退"所需的最小信息。"""
    return e["definition"] + "例外：" + "；".join(e["exceptions"] or ["无"])


def coverage(e: dict, q: str) -> float:
    """问题里的连续两字有多少落在条目文本里（标题 + 是什么 + 要点 + 例外）。"""
    grams = [q[i : i + 2] for i in range(len(q) - 1)]
    text = e["title"] + e["definition"] + "".join(e["key_points"]) + "".join(e["exceptions"])
    return sum(1 for g in grams if g in text) / max(len(grams), 1)


def lookup(question: str, entries: list[dict], thr: float = 0.4) -> tuple[dict | None, float]:
    """极简"查条目"：连续两字覆盖率最高的那条，≥ 阈值才算命中。

    这一级刻意不追求查得准 —— 要证明的是"条目的形状有用"，不是"路由好用"。
    查不准的后果，正是 step3 那张对照表里的数值。
    """
    best = max(entries, key=lambda e: coverage(e, question))
    score = coverage(best, question)
    return (best if score >= thr else None), score


def main() -> None:
    print("=" * 76)
    print("一条知识的固定形状：是什么 / 要点 / 例外 / 来源")
    print("=" * 76)
    print(render(ENTRIES[0]))
    print("\n" + "=" * 76)
    print(f"这条条目全文 {len(render(ENTRIES[0]))} 字符；只取「是什么 + 例外」是 {len(brief(ENTRIES[0]))} 字符")
    print("=" * 76)

    questions = [
        ("激活过的耳机能退吗？", ["已激活", "不适用"]),
        ("我买的定制款能无理由退货吗？", ["定制", "不适用"]),
        ("质量问题的运费谁出？", ["商家承担"]),
        ("超过 15 天的质量问题还能退吗？", ["维修"]),
        # 换一种问法，同一个意思
        ("耳机激活了还能无理由退吗", ["已激活", "不适用"]),
        ("无理由退货有什么商品不适用", ["定制", "生鲜", "已激活"]),
    ]

    print(f"\n{'问题':<26}{'路由':<12}{'字符':>6}{'要素命中':>10}   缺什么")
    print("-" * 84)
    ok = 0
    for q, keys in questions:
        e, score = lookup(q, ENTRIES)
        text = brief(e) if e else ""
        lack = [k for k in keys if k not in text]
        if not lack:
            ok += 1
        how = f"{score:.2f} {e['title'] if e else '未命中'}"
        print(f"{q:<26}{how:<12}{len(text):>6}{f'{len(keys) - len(lack)}/{len(keys)}':>10}   {'、'.join(lack) or '—'}")

    print("-" * 84)
    print(f"要素齐全：{ok}/{len(questions)}")

    print("\n" + "=" * 76)
    print("结论：换的不是检索算法，是'要检索的东西长什么样'")
    print("=" * 76)
    print("  · step1 检索的是**碎片**：15 块里挑 3 块，例外可能不在里面；")
    print("  · step2 检索的是**条目**：一个条目自带例外，只要命中就不会漏。")
    print()
    print("  注意这里的投入：每一条知识都是**人写**的（3 条写了 15 行）。")
    print("  语料只有 889 字时这没问题；5 万字的政策手册，手写就不现实了。")
    print("  下一级要解决的就是这个：让规则先抽一遍，人只做抽查和修正。")

    print("\n" + "=" * 76)
    print("  还有两个问题没解决：")
    print("  " + "=" * 72)
    print("  1. '运费承担'这一条没有例外字段——是真的没有例外，还是写的人漏了？")
    print("  2. 条目名字换一种说法就查不到（'激活过的耳机' → <0.4 未命中），")
    print("     但把'不适用'这类词直接写进问句就能命中（0.67）——**路由靠字面，不靠语义**。")
    print("  step3 会把条目和碎片放在一起比分，看两者的能力边界各在哪。")


if __name__ == "__main__":
    main()
