"""第 9 章 step1：四种分块策略，同一条文档切出来差多少（离线）。

运行：
    python code/ch09_chunking/step1_strategies.py

上一级的痛点（第 8 章）：RAG 能跑通了，但 Recall@3 只有 64%。
                     你怀疑检索不行，其实**第一道关口就漏了** —— 分块。

这一级做什么：拿一份真实长度的"售后规则"文档，跑四种切法，让差异可见：
  ① 定长切分（split_fixed）：最简单，最容易切断句子
  ② 按标题切分（split_by_heading）：标题天然是主题边界
  ③ 语义切分（split_semantic）：按句子相似度找断点
  ④ 父子分块（split_parent_child）：小块检索、大块喂模型

关键判据：**答案的两个要素是否落在同一个块里。**
如果"已激活"和"不适用"被切开，任何一块单独喂给模型都答不对。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.retrieval import (  # noqa: E402
    split_by_heading,
    split_fixed,
    split_parent_child,
    split_semantic,
)

DOC = """# 售后服务规则

## 一、无理由退货

签收后七天内，商品未拆封且不影响二次销售的，可申请无理由退货。外包装轻微挤压不影响判定，但商品本体不得有使用痕迹、划痕、水渍或异味。用户对签收时间有异议的，应在发现后四十八小时内提出，逾期视为认可。退款金额以实付金额为准，不含运费。

关于已拆封的判定：外包装膜被撕开即视为已拆封。已拆封但未激活的数码产品，仍可申请无理由退货，退回时需保持包装完整、配件齐备、赠品一并退回。赠品缺失的，按赠品市场价扣除相应金额。

定制类商品、生鲜食品、已激活的数码产品不适用无理由退货。已激活是指设备完成开机引导流程并登录账号，或已产生联网记录。若用户主张仅开箱验机未激活，需提供未登录账号的截图作为凭证，平台保留检测权利。

## 二、质量问题

签收后十五天内出现非人为损坏的质量问题，可申请换新或退货。是否属于质量问题，以平台指定检测机构的检测结论为准；检测周期一般为五到七个工作日，遇节假日顺延。

用户需在申请后三日内将商品寄回指定地址，逾期未寄回的系统将自动关闭申请。商品寄回后请保留物流单号，以便查询进度。检测期间商品需寄回，无法继续使用。

检测确认为人为损坏的，检测费用由用户承担，且不支持退换。人为损坏包括进水、摔碰、私自拆机、非原厂配件导致的故障。对检测结论有异议的，用户可在收到结论后七日内申请复检一次。

## 三、运费与优惠券

退货运费在质量问题情形下由平台承担，在非质量问题情形下由买家承担。买家承担运费时，若订单享受过满减或包邮优惠，需在退款金额中扣除相应运费。运费标准按寄回地址与仓库距离计算，最低八元。

使用优惠券的订单退款时，已使用的优惠券不返还，且不补发等价积分。若整单退款且订单未发货，优惠券可原路返还，有效期不变。部分退款时，优惠券按退款金额占比折算返还。

## 四、退款到账

审核通过后三到七个工作日原路退回，具体到账时间以发卡银行为准。会员享受优先审核，退款时效缩短一个工作日。跨境订单因涉及汇率与关税，退款周期可能延长至十五个工作日。
"""

QUERIES = [
    ("已激活的耳机能退吗？", ["已激活的数码产品不适用无理由退货"]),
    ("检测要等几天？", ["检测周期一般为五到七个工作日"]),
    ("退货运费谁承担？", ["质量问题情形下由平台承担"]),
    ("用过的券退款退不退？", ["已使用的优惠券不返还"]),
    ("会员退款快一点吗？", ["会员享受优先审核"]),
    ("部分退款券怎么算？", ["部分退款时，优惠券按退款金额占比折算返还"]),
    ("没激活能退吗？", ["已拆封但未激活的数码产品，仍可申请无理由退货"]),
]


def strategies() -> dict[str, list[str]]:
    pairs = split_parent_child(DOC, parent_size=500, child_size=200)
    return {
        "① 定长 400/重叠 50": split_fixed(DOC, size=400, overlap=50),
        "② 按标题（max 500）": split_by_heading(DOC, max_chars=500),
        "③ 语义切分（max 300）": split_semantic(DOC, max_chars=300, similarity_threshold=0.12),
        "④ 父子分块（child 200）": [c for c, _ in pairs],
    }


def intact(chunks: list[str], keywords: list[str]) -> bool:
    """答案的所有要素是否落在**同一个块**里。

    检索只能返回整块；要素被切开 → 单块信息不全 → 模型答错。
    """
    return any(all(k in c for k in keywords) for c in chunks)


def main() -> None:
    print("=" * 92)
    print(f"原始文档：{len(DOC)} 字符，4 个小节")
    print("=" * 92)

    results = strategies()
    notes = {
        "① 定长 400/重叠 50": "整齐，但句子常被切断",
        "② 按标题（max 500）": "语义完整，块可能过大",
        "③ 语义切分（max 300）": "按意思断，块太碎",
        "④ 父子分块（child 200）": "块小且聚焦，父块保留上下文",
    }
    print(f"\n{'策略':<24}{'块数':>6}{'平均长度':>10}{'最短':>7}{'最长':>7}   说明")
    print("-" * 92)
    for name, chunks in results.items():
        lens = [len(c) for c in chunks]
        print(
            f"{name:<24}{len(chunks):>6}{sum(lens) / len(lens):>10.0f}"
            f"{min(lens):>7}{max(lens):>7}   {notes[name]}"
        )
    print("-" * 92)

    print("\n" + "=" * 92)
    print("关键指标：答案的两个要素是否落在**同一个块**里")
    print("=" * 92)
    print(f"{'查询':<22}" + "".join(f"{k.split(' ')[0]:>7}" for k in results))
    print("-" * 92)
    totals = {k: 0 for k in results}
    for q, kws in QUERIES:
        line = f"{q:<22}"
        for name, chunks in results.items():
            ok = intact(chunks, kws)
            totals[name] += ok
            line += f"{'✅' if ok else '❌':>7}"
        print(line)
    print("-" * 92)
    line = f"{'要素完整率':<22}"
    for name in results:
        line += f"{totals[name] / len(QUERIES):>6.0%}"
    print(line)
    print("-" * 92)

    print("\n" + "=" * 92)
    print("① 定长切分：块里混进了多少个不同主题")
    print("=" * 92)
    # 每个块覆盖了哪几个小节（用标题定位）
    SECTION_MARKS = ["一、无理由退货", "二、质量问题", "三、运费与优惠券", "四、退款到账"]

    def sections_in(chunk: str) -> set[str]:
        return {m for m in SECTION_MARKS if m in chunk}

    print(f"  {'策略':<24}{'块数':>6}{'含 2+ 主题的块':>15}{'最大混杂度':>11}")
    print("  " + "-" * 72)
    for name, chunks in results.items():
        multi = [c for c in chunks if len(sections_in(c)) >= 2]
        worst = max((len(sections_in(c)) for c in chunks), default=0)
        print(f"  {name:<24}{len(chunks):>6}{len(multi):>15}{worst:>11}")
    print("  " + "-" * 72)
    print()
    print("  **一个块里混进多个主题，是检索质量的头号杀手。**")
    print("  为什么：块向量是整块文本的平均——混了 3 个主题，向量就变成了「三者的平均」，")
    print("  谁的相似度都不高。打比方：")
    print("    · 纯「退款到账」块 → 和「退款多久」相似度 0.6")
    print("    · 混杂「退货+质量+运费+退款」块 → 和「退款多久」只有 0.25")
    print("  **后者会被排到后面，甚至排不进去。**")
    print()
    print("  这就是为什么「按标题切」通常最好：")
    heading = results["② 按标题（max 500）"]
    mixed = [c for c in heading if len(sections_in(c)) >= 2]
    print(f"    · 按标题切 {len(heading)} 块，含 2+ 主题的只有 {len(mixed)} 块")

    print("\n" + "=" * 92)
    print("② 按标题切分为什么更稳")
    print("=" * 92)
    heading = results["② 按标题（max 500）"]
    print(f"  块数 {len(heading)}，每块都以标题开头：")
    for i, c in enumerate(heading):
        first = c.split("\n", 1)[0][:30]
        print(f"    [{i}] {first:<32} ({len(c)} 字)")
    print()
    print("  **标题是作者亲手标的主题边界** —— 比算法猜的断点准。")
    print("  所以：文档有结构（Markdown / HTML / 法律条款）就一定按结构切。")

    print("\n" + "=" * 92)
    print("③ 语义切分的问题：块太碎、块数暴涨")
    print("=" * 92)
    sem = results["③ 语义切分（max 300）"]
    lens = [len(c) for c in sem]
    print(f"  块数 {len(sem)}，平均 {sum(lens) / len(lens):.0f} 字，最短 {min(lens)} 字")
    print()
    print("  块太小的三个后果：")
    print("    · 单块信息量不足以回答（要命中多个块）")
    print("    · 块数暴涨 → 向量库变大、检索变慢")
    print("    · 相邻块语义高度重叠 → top-k 全是同一段的不同切片")
    print()
    print("  **语义切分不是「更高级就一定更好」**，要配 max_chars 上限 + 合并小块。")

    print("\n" + "=" * 92)
    print("④ 父子分块：生产级方案")
    print("=" * 92)
    pairs = split_parent_child(DOC, parent_size=500, child_size=200)
    print(f"  切出 {len(pairs)} 个 (child, parent) 对")
    found = next(((c, p) for c, p in pairs if "已激活" in c and "不适用" in c), pairs[0])
    child, parent = found
    print()
    print(f"  child（{len(child)} 字）—— 检索用，语义聚焦：")
    print(f"    {child[:66]}…")
    print()
    print(f"  parent（{len(parent)} 字）—— 命中后喂模型，上下文完整：")
    print(f"    {parent[:80]}…")
    print()
    print("  好处：小块命中率高 + 大块信息完整。代价：**存储翻倍**。")

    print("\n" + "=" * 92)
    print("结论")
    print("=" * 92)
    print("  · **分块是 RAG 的第一道关口。** 答案被切断，后面检索再准也没用。")
    print("  · 定长切分只在文档没有结构时用；有标题就按标题切。")
    print("  · 语义切分容易切得过碎，必须配 max_chars 上限。")
    print("  · **父子分块是生产首选**：小块检索、大块生成。")
    print()
    print("  下一级（step2）：chunk_size 到底该取多大？用数字回答，不靠感觉。")

    assert len(results) == 4
    assert totals["② 按标题（max 500）"] >= totals["① 定长 400/重叠 50"]


if __name__ == "__main__":
    main()
