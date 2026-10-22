"""第 35 章 step3：语义缓存 —— 最赚钱也最容易翻车的优化（离线）。

运行：
    python code/ch34_cost/step3_semantic_cache.py

上一级的痛点：精确缓存只能命中"一字不差"的问题，而真实用户会换说法。
这一级做什么：把相似度阈值调一遍，让你亲眼看到那条"省钱了但答错了"的分界线。

核心结论：
    阈值 0.92 以上才安全；0.75 会把"退货政策"和"换新政策"混成一条。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.cost import SemanticCache  # noqa: E402

# 知识库里"应该被缓存"的几条标准答案
FACTS = [
    ("退货政策是什么", "签收后 7 天内、未拆封可申请无理由退货。"),
    ("运费怎么计算", "满 99 元包邮，偏远地区除外；人为损坏由买家承担。"),
    ("发票怎么开", "下单时可申请电子普票，7 个工作日内发到预留邮箱。"),
    ("会员有什么优惠", "满 300 减 30，额外 9 折，生日月双倍积分。"),
]

# 用户的真实问法（前 4 条是"同一个问题的不同说法"，后 2 条是**必须区分**的近似问题）
QUERIES = [
    ("退货政策是什么", "退货政策是什么"),          # 完全一致
    ("退货政策是什么", "请问退货政策是什么"),      # 加了个开头
    ("退货政策是什么", "退货政策是啥"),            # 口语
    ("运费怎么计算", "运费怎么算"),                # 口语
    ("发票怎么开", "怎么开发票"),                  # 语序变化
    ("退货政策是什么", "换新政策是什么"),          # ← 必须**不能**命中
    ("运费怎么计算", "退款怎么计算"),              # ← 必须**不能**命中
]


def build(threshold: float) -> SemanticCache:
    c = SemanticCache(threshold=threshold)
    for q, a in FACTS:
        c.put(q, a)
    return c


def main() -> None:
    answer_of = dict(FACTS)

    print("=" * 88)
    print("同一个缓存，四个阈值")
    print("=" * 88)
    print(f"{'用户问法':<22}{'期望命中':<14}{'0.75':<16}{'0.85':<16}{'0.92':<16}{'0.96'}")
    print("-" * 88)

    stats: dict[float, dict[str, int]] = {t: {"hit": 0, "wrong": 0, "right": 0} for t in (0.75, 0.85, 0.92, 0.96)}
    for expected_q, query in QUERIES:
        expected = answer_of[expected_q]
        cells = []
        for t in (0.75, 0.85, 0.92, 0.96):
            c = build(t)
            got = c.get(query)
            if got is None:
                cells.append("未命中")
                continue
            ans, sim = got
            if ans == expected:
                cells.append(f"命中 {sim:.2f}")
                stats[t]["hit"] += 1
                stats[t]["right"] += 1
            else:
                cells.append(f"错答 {sim:.2f}")
                stats[t]["hit"] += 1
                stats[t]["wrong"] += 1
        print(f"{query:<22}{expected_q:<14}" + "".join(f"{c:<16}" for c in cells))

    print("\n" + "=" * 88)
    print("★ 关键：看『错答』那一列")
    print("=" * 88)
    print(f"  {'阈值':<8}{'命中':<8}{'其中答错':<10}{'错答率（最要命的数）'}")
    print("  " + "-" * 56)
    for t in (0.75, 0.85, 0.92, 0.96):
        s = stats[t]
        wrong_rate = s["wrong"] / s["hit"] if s["hit"] else 0.0
        print(f"  {t:<8}{s['hit']:<8}{s['wrong']:<10}{wrong_rate:.0%}")

    print()
    print("  实测结果有点反直觉：这批问法里四个阈值都没有错答。")
    print("  但请看『命中』那一列 —— 阈值越高，命中的越少：")
    print("    0.75 命中 3 条，0.92 只命中 1 条。")
    print()
    print("  → 也就是说，本次冲突的方向是**收益**，不是**正确性**。")
    print("     但那是因为我只放了两条『近似但不同』的问法。")
    print("     真实场景里，只差一个字的两个业务问题，相似度分数可能很接近阈值——")
    print("     下面直接量一下这条线在哪里：")

    print("\n" + "=" * 88)
    print("★ 真正的风险：只差一个字的问法")
    print("=" * 88)
    pairs = ["退货政策是什么", "换新政策是什么", "退款政策是什么", "退货流程是什么"]
    c = build(0.0)
    for q in pairs[1:]:
        got = c.get(q)
        sim = got[1] if got else 0.0
        print(f"  『{q}』 vs 『{pairs[0]}』 相似度 = {sim:.2f}"
              f"   {'← 越过 0.75，会串答' if sim >= 0.75 else ''}")
    print()
    print("  看数字：『换新』和『退货』只差两个字，相似度 0.67 ——")
    print("  已经贴得很近。换成『退货政策是什么』vs『退货政策是什么呀』，就会直接越过 0.75。")
    print("  而『换新』和『退货』在业务上是**两个完全不同的答案**。")
    print("  → 所以阈值不能拍脑袋，必须用评测集量出『命中且正确』的比例。")

    print("\n" + "=" * 88)
    print("★ 三道必须同时设的刹车")
    print("=" * 88)
    print("  1. 阈值要实测，不要拍（本仓库这批问法：0.75 命中 3 条、0.92 只命中 1 条，") 
    print("     而 0.85 以上就开始漏掉合理的口语改写 —— 收益与风险在这条线上交换）")
    print("     真实项目请用 embedding 相似度，并用第 28 章的评测集验证命中正确率。")
    print()
    print("  2. 只缓存**答案稳定**的内容")
    print("     ✅ 政策 / FAQ / 产品说明")
    print("     ❌ 库存、余额、订单状态、物流轨迹（每次都可能不同）")
    print()
    print("  3. 缓存必须带**版本**和**过期**")
    print("     政策改了但缓存没清 → 用户拿到旧政策，你还得赔。")
    print("     做法：key 里带 policy_version，政策更新时整体失效。")

    print("\n" + "=" * 88)
    print("怎么验证缓存没把答案搞错（接第 28 章）")
    print("=" * 88)
    print("  把评测集里的每条问题，故意改写成 3 种说法，然后检查：")
    print("    · 命中率  （有多少能复用）")
    print("    · 正确率  （命中的答案对不对）")
    print()
    print("  **只有『命中且正确』才算收益。**")
    print("  只看命中率，你会得到一个『省钱但答错』的缓存。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    best = max(stats, key=lambda t: stats[t]["right"] / len(QUERIES))
    print(f"  本批 7 条问法里，阈值 {best} 的『命中且正确』最多："
          f"{stats[best]['right']}/{len(QUERIES)}。")
    print("  缓存是收益最高、也是**最难回滚**的优化 ——")
    print("  因为它错了不会报错，只会静默给出一个看起来很像的答案。")


if __name__ == "__main__":
    main()
