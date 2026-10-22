"""第 39 章 step3：多模态与"表格/图片"这类数据（离线）。

运行：
    python code/ch39_data/step3_multimodal.py

上一级的痛点：
    你的知识库是纯文本。但真实文档里 30% 的信息在**表格**里、10% 在**图片**里。
    把它们当纯文本切，会切成一堆没法读的碎片。

这一级做什么：
    ① 三种多模态输入的处理路线（转文本 / 图+文一起嵌入 / 图存引用）
    ② 表格：为什么"按行切"比"按列切"好（一个真实对比）
    ③ 图片：什么时候该"描述成文本"，什么时候该"保留原图"
    ④ 一个成本对照：多模态嵌入比纯文本贵多少

关键认知：
    **多模态不是"把图变成文字"这一条路。** 它有三条路，选哪条取决于"用户会怎么问"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------- 表格
TABLE_MD = """| 商品 | 退货期 | 换新期 | 保修期 |
|---|---|---|---|
| 耳机 | 7 天 | 15 天 | 1 年 |
| 充电盒 | 7 天 | 15 天 | 1 年 |
| 数据线 | 7 天 | 30 天 | 半年 |"""


def parse_table(md: str) -> tuple[list[str], list[list[str]]]:
    rows = [r.strip() for r in md.strip().splitlines() if r.strip().startswith("|")]
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    header, body = cells[0], [c for c in cells[2:]]      # 跳过 ---|---
    return header, body


def by_row(header: list[str], body: list[list[str]]) -> list[str]:
    """按行切：每行变成一个完整的"事实"。"""
    return ["，".join(f"{h}：{v}" for h, v in zip(header, row)) for row in body]


def by_column(header: list[str], body: list[list[str]]) -> list[str]:
    """按列切：每列变成一个"维度"。"""
    out = []
    for j, h in enumerate(header):
        vals = [row[j] for row in body]
        out.append(f"{h}（{'/'.join(vals)}）")
    return out


def by_text_split(md: str, size: int = 40) -> list[str]:
    """不做任何处理，当纯文本定长切（最常见的错误做法）。"""
    flat = re.sub(r"[\|\-\n]+", " ", md)
    return [flat[i:i + size] for i in range(0, len(flat), size)]


@dataclass
class Doc:
    text: str
    kind: str          # text / table / image
    ref: str = ""      # 图片对应的原始文件


def main() -> None:
    line("① 表格的三种切法，看哪种「语义完整」")
    header, body = parse_table(TABLE_MD)
    print("  原表：")
    for r in TABLE_MD.splitlines():
        print(f"    {r}")

    print("\n  按行切（推荐）：")
    for s in by_row(header, body):
        print(f"    · {s}")

    print("\n  按列切：")
    for s in by_column(header, body):
        print(f"    · {s}")

    print("\n  当纯文本定长切（常见错误）：")
    parts = by_text_split(TABLE_MD, 40)
    for s in parts:
        print(f"    · {s!r}")

    print(f"\n  对比：按行 {len(by_row(header, body))} 块 / 按列 {len(by_column(header, body))} 块 "
          f"/ 纯文本 {len(parts)} 块")
    print("  → 纯文本切法会把「耳机 | 7 天 | 15 天」切到两段里，检索到半行 = 答不出。")
    print("  → 按行切，每一块都是「商品：耳机，退货期：7 天，换新期：15 天，保修期：1 年」，")
    print("    用户问「耳机保修多久」时，向量能直接命中这一条。")

    line("② 但「按行切」也有代价：改一行要重建多少块？")
    print("  假设表有 500 行，改了第 200 行的「保修期」：")
    print("    按行切 → 只有第 200 块变（1 块）")
    print("    按列切 → 「保修期」整列变（1 块，但那块变长了 500 倍）")
    print("    纯文本 → 后面所有块的位置都变了（几百块）")
    print("  → 这就是为什么按行切（或者「每行一块 + 表头冗余」）是默认选择。")

    line("③ 图片的三条路线")
    routes = [
        ("A 描述成文本", "用多模态模型把图描述成文字，只存文字", "用户问「图里是什么」", "丢细节（数值、位置）"),
        ("B 图 + 文一起嵌入", "同时存原图和描述，用多模态嵌入模型", "用户会指图提问", "成本高，模型支持有限"),
        ("C 图存引用 + 文字索引", "文字部分入索引，原图 URL 放 metadata", "回答时要展示原图", "只靠文字描述召回"),
    ]
    print(f"  {'路线':<18}{'做法':<42}{'适合':<22}{'代价'}")
    print("  " + "-" * 100)
    for r in routes:
        print(f"  {r[0]:<18}{r[1]:<42}{r[2]:<22}{r[3]}")

    print("\n  → 起手推荐：**A + C 组合**。文字描述用于召回，原图 URL 放 metadata 用于展示。")
    print("    B 等你的用户真的会'指着图问'时再上（成本高一个量级）。")

    line("④ 成本对照")
    print(f"  {'类型':<20}{'单次嵌入成本':>14}{'备注'}")
    print("  " + "-" * 60)
    print(f"  {'纯文本（512 token）':<20}{'¥0.00002':>14}  基准")
    print(f"  {'文本描述（含图说明）':<20}{'¥0.00005':>14}  描述本身要一次模型调用")
    print(f"  {'多模态嵌入（原图）':<20}{'¥0.0006':>14}  约 30 倍")
    print("\n  算一笔账：1000 张产品图")
    print("    路线 A：1000 次描述调用（¥0.002） + 1000 次文本嵌入 ≈ ¥2")
    print("    路线 B：1000 次多模态嵌入 ≈ ¥0.6")
    print("  → 单看建库，B 更便宜；但 B 需要模型支持、且查询时也要用多模态嵌入。")
    print("    **所以先看「查询侧支不支持」，再算成本。**")

    line("⑤ 一张必看的分辨率陷阱")
    print("""  同一张图，喂给模型前要缩放：
    · 太大（4K 原图）→ token 爆掉，成本 ×10，还可能被模型拒收
    · 太小（300px）  → 表格里的数字看不清，模型瞎猜

  实践值（不同厂商不同，要实测）：
    · 含文字的截图 / 表格：长边 1500–2000px
    · 自然照片：长边 1000–1200px
  → **不要"保持原图质量"**，那是无效的成本。""")

    line("⑥ 一份可以直接抄的多模态入库清单")
    print("""
  [ ] PDF 先判断"是文本层还是扫描件"（有文本层就抽文本，别做 OCR）
  [ ] 表格必须单独抽出来，按行切成完整事实
  [ ] 图片：先用模型描述 → 文本入索引 → 原图 URL 放 metadata
  [ ] 每块都带 source + page + kind（text/table/image）
  [ ] 图/表要能"回链"：用户点引用能看到原位置
  [ ] 缩放策略写进配置（别藏在代码里）
  """)


if __name__ == "__main__":
    main()
