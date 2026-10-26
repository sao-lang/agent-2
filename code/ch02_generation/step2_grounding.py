"""第 2 章 step2：依据强度与输出质量（离线可运行）。

运行：
    python code/ch02_generation/step2_grounding.py

把请求按「模型能拿到的依据」分成三档，观察同一套生成机制在每一档的表现。
依据强度由调用方控制，不由模型判断。
"""

from __future__ import annotations

import sys


# 三种依据强度：系统实际提供给模型的内容
CASES = [
    {
        "level": "有依据",
        "question": "签收后多久可以申请无理由退货？",
        "context": "签收后七天内可以申请无理由退货。",
        "output": "签收后七天内可以申请无理由退货。",
        "check": "输出中的关键事实（七天）在依据中",
    },
    {
        "level": "弱依据",
        "question": "已激活的耳机能退吗？",
        "context": "定制类商品不适用无理由退货。",
        "output": "已激活的商品只要不影响二次销售就可以退。",
        "check": "依据讲的是定制类商品，与提问不是同一个对象",
    },
    {
        "level": "无依据",
        "question": "退货运费由谁承担？",
        "context": "",
        "output": "退货运费由买家承担，质量问题除外。",
        "check": "依据为空，输出中出现了具体规则",
    },
]


def contains_fact(output: str, context: str, fact: str) -> bool:
    """粗判：关键事实是否能在依据中找到。"""
    return fact in context and fact in output


def main() -> None:
    print("=" * 84)
    print("① 三档依据强度")
    print("=" * 84)
    for c in CASES:
        print(f"\n  【{c['level']}】")
        print(f"    提问：{c['question']}")
        print(f"    提供：{c['context'] or '（空）'}")
        print(f"    输出：{c['output']}")
        print(f"    判定：{c['check']}")

    print()
    print("=" * 84)
    print("② 输出的形式特征")
    print("=" * 84)
    print(f"  {'依据强度':<10}{'输出长度':<10}{'是否有具体事实':<16}{'语气确定性'}")
    print("  " + "-" * 78)
    rows = [
        ("有依据", len(CASES[0]["output"]), "是", "陈述"),
        ("弱依据", len(CASES[1]["output"]), "是", "陈述"),
        ("无依据", len(CASES[2]["output"]), "是", "陈述"),
    ]
    for a, b, c, d in rows:
        print(f"  {a:<10}{b:<10}{c:<16}{d}")

    print()
    print("  三档输出的形式完全一致：长度相当、都有具体事实、都用陈述语气。")
    print("  仅从输出文本无法区分哪一条有依据。")

    print()
    print("=" * 84)
    print("③ 判定依据强度的位置")
    print("=" * 84)
    print("  模型无法判断自己有没有依据。它只做续写。")
    print("  依据强度由调用方决定：")
    print("    · 检索是否命中           -> 决定是否有依据")
    print("    · 命中的内容是否相关       -> 决定是强依据还是弱依据")
    print("    · 是否允许在无依据时回答   -> 决定兜底方式")

    print()
    print("=" * 84)
    print("④ 三种依据强度对应的处理方式")
    print("=" * 84)
    strategies = [
        ("有依据", "直接使用输出", "关键事实能在依据中找到"),
        ("弱依据", "要求模型标注依据，或补充检索", "依据与提问对象不一致"),
        ("无依据", "拒绝回答、转人工、或明确声明无法确定", "检索结果为空"),
    ]
    print(f"  {'依据强度':<10}{'处理方式':<32}{'判定条件'}")
    print("  " + "-" * 78)
    for a, b, c in strategies:
        print(f"  {a:<10}{b:<32}{c}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
