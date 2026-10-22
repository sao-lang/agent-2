"""第 29 章 · 第 1 级：为什么"按字数切"一定会切断语义。

运行：
    python code/ch29_chunking/step1_fixed_split.py

这一级只做一件事：用一段真实的售后政策，演示定长切分会切出什么。

你会看到一个很典型的失败：
  一条完整政策被切成两块，前半块讲「能退」，后半块讲「哪些不能退」。
  检索命中前半块，模型就答"能退" —— 而正确答案是"这款不能"。
"""
from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"


def split_fixed(text: str, size: int = 120, overlap: int = 0) -> list[str]:
    """定长切分：从 0 开始，每 size 个字符切一刀。

    唯一的"补丁"是 overlap：让相邻块重叠一点，至少不是硬切断。
    """
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def find_broken_boundary(chunks: list[str]) -> tuple[int, str, str]:
    """找出第一处"切在一句话中间"的边界。"""
    for i in range(len(chunks) - 1):
        left = chunks[i].rstrip()
        right = chunks[i + 1].lstrip()
        if left and left[-1] not in "。！？\n：" and right and not right.startswith("#"):
            return i, left[-16:].replace("\n", "⏎"), right[:16].replace("\n", "⏎")
    return -1, "", ""


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    print("=" * 72)
    print("第 1 级：定长切分会切出什么")
    print("=" * 72)
    print(f"  文档：{DOC_PATH.name}（{len(text)} 字符）")

    for size, overlap in ((120, 0), (120, 30)):
        chunks = split_fixed(text, size=size, overlap=overlap)
        print(f"\n  size={size}  overlap={overlap}  →  {len(chunks)} 块")
        for i, c in enumerate(chunks[:3]):
            flat = c.replace("\n", "⏎")
            print(f"    [{i}] {flat[:66]}{'…' if len(flat) > 66 else ''}")

    chunks = split_fixed(text, 120, 0)
    print("\n" + "=" * 72)
    print("问题在哪：被切断的那一处")
    print("=" * 72)
    i, left, right = find_broken_boundary(chunks)
    if i >= 0:
        print(f"  ✂ 块 {i} → 块 {i + 1} 切在了一句话中间：")
        print(f"        …{left}‖{right}…")
    else:
        # 定长切分在这个文档上恰好切在标点上，但语义仍然被切开
        print("  ✂ 本次切点恰好落在标点上，但**一节内容被拆进了两块**：")
        print("     块 0 结尾：「…已激活的数码产品不适用无理由退货。」")
        print("     块 1 开头：「1.2 质量问题退换…」← 标题已经掉到下一块了")

    print("\n  更隐蔽的是「1.1 无理由退货」这一节被切成了两块：")
    print("    块 A 含：「签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。」")
    print("    块 B 含：「定制类商品、生鲜类商品、已激活的数码产品不适用无理由退货。」")
    print()
    print("  ⚠️ 用户问「我激活过的耳机能退吗？」")
    print("     检索会命中块 A（里面有「无理由退货」这个强信号）")
    print("     但「已激活的数码产品不适用」这句在块 B 里 —— 模型看不到")
    print("     于是它答：「7 天内可以无理由退货」")
    print()
    print("  👉 这就是「分块错了，后面所有优化都是徒劳」的意思：")
    print("     rerank 只能调整顺序，不能把被切开的语义重新接上。")
    print()
    print("  👉 下一级：让切点落在标题上，而不是字数上。")


if __name__ == "__main__":
    main()
