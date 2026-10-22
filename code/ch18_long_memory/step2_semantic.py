"""第 18 章 step2：语义记忆 —— 去重、取代、以及"该不该信"。

运行：
    python code/ch18_long_memory/step2_semantic.py

上一级的痛点：同一件事存了两份，改口后两条都在，检索靠运气。
这一级做什么：把语义记忆的写入策略讲透 ——
              dedupe（去重） / supersede（取代） / review（人工确认）。

关键不是"能不能覆盖"，而是 **覆盖的代价有多大**。
"过敏" 变成 "不过敏"，自动覆盖会直接伤人；必须有人确认。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.long_memory import MemoryKind, MemoryStore, MemoryWriter  # noqa: E402

SCOPE = {"tenant_id": "shop-1", "user_id": "u-zhang"}

# 一次真实的时间线：先说过敏，中间又提了一次，最后说好了
TIMELINE = [
    ("用户对芒果过敏，禁止推荐含芒果的商品", 0.95, "开场自我介绍时提到"),
    ("用户对芒果过敏，禁止推荐含芒果的商品", 0.95, "又一次确认（同一句）"),
    ("用户说可以吃芒果了，过敏症状已消失", 0.70, "客服回访时提到"),
]


def main() -> None:
    store = MemoryStore()
    w = MemoryWriter(store, min_importance=0.3)

    print("=" * 78)
    print("语义记忆的完整写入时间线")
    print("=" * 78)
    for i, (content, importance, note) in enumerate(TIMELINE, 1):
        r = w.write_semantic("pref.mango", content, importance, **SCOPE)
        print(f"\n  第 {i} 次写入（{note}）")
        print(f"    内容：{content}")
        print(f"    结果：{r['action']}")
        if r["action"] == "superseded":
            print(f"    冲突度：{r['conflict_ratio']}   需要人工确认：{r['needs_review']}")

    print("\n" + "=" * 78)
    print("现在库里有什么（不含已被取代的）")
    print("=" * 78)
    for m in store.query(kind=MemoryKind.SEMANTIC, **SCOPE):
        print(f"  {m.id[:14]}  {m.content}   use_count={m.use_count}")

    print("\n" + "=" * 78)
    print("但旧记录没删 —— 这是故意的")
    print("=" * 78)
    all_rows = store.query(kind=MemoryKind.SEMANTIC, include_superseded=True, **SCOPE)
    for m in all_rows:
        state = "已取代" if m.superseded_by else "生效中"
        print(f"  [{state}] {m.content}")
    print()
    print("  为什么必须留着？因为你要能回答这个问题：")
    print("    「为什么系统现在认为可以吃芒果了？」")
    print("  答案必须能追溯到：谁、什么时候、被什么取代。")
    print("  在医疗 / 金融场景，这不是『好习惯』，是**合规要求**。")

    print("\n" + "=" * 78)
    print("最危险的一步：什么时候必须停下来问人")
    print("=" * 78)
    print("  conflict_ratio 只衡量『字面差异』，它分不清这两类改动：")
    print("    · 无害更新：「用户喜欢蓝色」→「用户喜欢深蓝色」")
    print("    · 危险反转：「用户对芒果过敏」→「用户可以吃芒果」")
    print()
    print("  字面上，后者的差异甚至可能更小（只差一个字）。")
    print("  → 所以不能只用字符串相似度判断，必须有一条**业务规则**：")
    print("     涉及健康、金额、权限的字段，任何变更一律 needs_review=True")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  语义记忆的三个动作：去重（同句不新增）/ 取代（不同则新建旧的标记失效）/ 审核（危险必须人工）")
    print("  少任何一个，系统都会在某天给出『它明明记过』的错误答案。")


if __name__ == "__main__":
    main()
