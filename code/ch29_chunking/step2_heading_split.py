"""第 29 章 · 第 2 级：按标题切 —— 让切点落在"主题边界"上。

运行：
    python code/ch29_chunking/step2_heading_split.py

新增的一个概念：**结构感知切分（structure-aware chunking）**。

原始文档里本来就写着"一章 / 一节"的结构（`##` / `###`）。
按标题切，等于让**写文档的人**帮你决定语义边界 —— 这比任何算法都准。

代价：切出来的块大小不均匀，超长的节还要再退化成定长切。
"""
from __future__ import annotations

import re
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"


def split_by_heading(text: str, max_chars: int = 220) -> list[str]:
    """按 `## ` / `### ` 切；超长的节退化成定长切，并保留标题前缀。

    为什么要保留标题前缀？
    因为"签收后 7 天内可以退"这句话本身**没说是关于什么的**。
    加上 `【1.1 无理由退货】` 之后，嵌入向量才会带上主题信息。
    """
    parts = re.split(r"\n(?=#{2,3} )", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            out.append(p)
            continue
        head = p.split("\n", 1)[0].lstrip("# ").strip()
        for sub in _split_fixed(p, max_chars, overlap=40):
            out.append(sub if sub.startswith("#") else f"【{head}】\n{sub}")
    return out


def _split_fixed(text: str, size: int, overlap: int) -> list[str]:
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def split_fixed(text: str, size: int = 120, overlap: int = 0) -> list[str]:
    return _split_fixed(text, size, overlap)


def check_policy_integrity(chunks: list[str]) -> tuple[bool, str]:
    """核心检查：39.1 节的两句话（"可退" 与 "哪些不可退"）是否在同一块里。"""
    for c in chunks:
        if "可申请无理由退货" in c and "已激活的数码产品不适用" in c:
            return True, "✅ 「能退」和「哪些不能退」在同一块"
    return False, "❌ 「能退」和「哪些不能退」被切散了 — 模型会答错"


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    print("=" * 74)
    print("第 2 级：按标题切")
    print("=" * 74)

    fixed = split_fixed(text, 50, 0)
    heading = split_by_heading(text)

    for name, chunks in (("定长 50", fixed), ("按标题", heading)):
        sizes = sorted(len(c) for c in chunks)
        avg = sum(sizes) / len(sizes)
        print(f"\n  [{name}]  {len(chunks)} 块  平均 {avg:.0f} 字  "
              f"最短 {sizes[0]}  最长 {sizes[-1]}")
        for i, c in enumerate(chunks[:4]):
            first = c.split("\n")[0][:52]
            print(f"    [{i}] ({len(c):>3} 字) {first}")

    print("\n" + "=" * 74)
    print("关键检查：政策完整性")
    print("=" * 74)
    for name, chunks in (("定长 50", fixed), ("按标题", heading)):
        ok, msg = check_policy_integrity(chunks)
        print(f"  {name:<10}{msg}")

    print("\n" + "=" * 74)
    print("按标题切为什么更好（三个具体理由）")
    print("=" * 74)
    print("  ① 边界是「作者定的」：一节讲一件事，天然不跨主题")
    print("  ② 块自带主题：标题前缀让嵌入向量带上「这段是关于什么的」")
    print("  ③ 人能读懂：存储和排障时，一眼知道这块属于哪章哪节")
    print()
    print("  代价：块大小不均匀（本例最长 106 字、最短 12 字）。")
    print("  检索系统要能接受这种不均匀 —— 大多数向量库都能。")


if __name__ == "__main__":
    main()
