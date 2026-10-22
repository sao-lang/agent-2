"""第 27 章 step5：召回 —— 记忆再多，取不对就等于没有。

运行：
    python code/ch27_long_memory/step5_recall.py

上一级的痛点：三层记忆都写对了，但"该怎么取"还没定。
这一级做什么：对比两种召回方式，并演示最严重的一次事故 —— **忘了带 tenant**。

三种取法：
  A. 全量塞进 prompt（第 24 章说过的"预算灾难"）
  B. 按分数取 top-3（有背景噪音）
  C. 过滤到相关记忆 + top-3（本章方案）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import est_tokens  # noqa: E402
from common.long_memory import Memory, MemoryKind, MemoryStore, score_memory  # noqa: E402

SCOPE = {"tenant_id": "shop-1", "user_id": "u-zhang"}

MEMORIES = [
    ("pref.mango", "用户对芒果过敏，禁止推荐含芒果的商品", 0.95, 90),
    ("pref.delivery", "用户偏好周末收货", 0.6, 30),
    ("pref.member", "用户上个月退订了会员", 0.7, 20),
    ("order.history", "用户是 3 年金牌会员", 0.8, 400),
    ("pref.contact", "用户只接受短信联系，不要打电话", 0.85, 60),
]


def build_store() -> MemoryStore:
    store = MemoryStore()
    for key, content, importance, days in MEMORIES:
        store.write(
            Memory(
                id=f"m-{key}",
                kind=MemoryKind.SEMANTIC,
                key=key,
                content=content,
                importance=importance,
                created_at=time.time() - days * 86400,
                **SCOPE,
            )
        )
    # 另一个租户 / 另一个用户的记忆，用来演示越权
    store.write(
        Memory(id="other-1", kind=MemoryKind.SEMANTIC, key="pref.mango",
               content="李四对芒果过敏", importance=0.9,
               tenant_id="shop-2", user_id="u-li")
    )
    return store


def recall_all(store: MemoryStore) -> list[Memory]:
    return store.query(**SCOPE)


def recall_top3(store: MemoryStore) -> list[Memory]:
    ms = store.query(**SCOPE)
    return [m for m, _ in sorted(((m, score_memory(m)) for m in ms), key=lambda x: -x[1])][:3]


def recall_relevant(store: MemoryStore, question: str, top_k: int = 3) -> list[Memory]:
    """先按问题过滤，再按分数排序。

    为什么要先过滤？因为"分数最高的三条"里，很可能有和当前问题无关的背景信息
    （比如"用户是 3 年金牌会员"）。这类信息塞进上下文会让模型跑题。
    """
    keywords = {
        "芒果": ["芒果", "过敏"],
        "会员": ["会员", "套餐"],
        "配送": ["收货", "快递", "周末"],
        "联系": ["联系", "电话", "短信"],
    }
    wanted: set[str] = set()
    for k, words in keywords.items():
        if any(w in question for w in words):
            wanted.update(words)

    ms = store.query(**SCOPE)
    if wanted:
        ms = [m for m in ms if any(w in m.content for w in wanted)]
    scored = sorted(((m, score_memory(m)) for m in ms), key=lambda x: -x[1])
    return [m for m, _ in scored[:top_k]]


def show(label: str, ms: list[Memory]) -> None:
    text = "\n".join(f"- {m.content}" for m in ms)
    print(f"\n  {label}（{len(ms)} 条 / {est_tokens(text)} token）")
    for m in ms:
        print(f"    - {m.content}")


def main() -> None:
    store = build_store()
    q = "我能吃芒果蛋糕吗？"

    print("=" * 80)
    print(f"同一句问题：{q}")
    print("=" * 80)
    show("A 全量塞进去", recall_all(store))
    show("B 只按分数取 top-3", recall_top3(store))
    show("C 先过滤再取 top-3", recall_relevant(store, q))

    print("\n" + "=" * 80)
    print("A 的问题：预算和噪音")
    print("=" * 80)
    a = recall_all(store)
    print(f"  {len(a)} 条记忆 / {est_tokens(chr(10).join(m.content for m in a))} token。")
    print("  记忆只有 5 条时还能忍；用户用一年后变成 500 条，这条路就走不通了。")

    print("\n" + "=" * 80)
    print("B 的问题：最相关的不一定分数最高")
    print("=" * 80)
    b = recall_top3(store)
    hit = any("芒果" in m.content for m in b)
    print(f"  top-3 里有没有『芒果过敏』这条？{'有' if hit else '没有'}")
    if not hit:
        print("  → 一条和问题无关的旧事件（金牌会员）把关键信息挤掉了。")
    print("  → 分数公式衡量的是『这条记忆值不值得记』，不是『它和这个问题有没有关系』。")

    print("\n" + "=" * 80)
    print("C 的做法：先按问题缩小范围，再排序取前几条")

    print("=" * 80)
    c = recall_relevant(store, q)
    print(f"  取到的 {len(c)} 条全部和芒果相关 —— 这才是模型需要的。")

    print("\n" + "=" * 80)
    print("★ 最严重的一种错：忘了带 tenant_id")
    print("=" * 80)
    leaked = store.query(tenant_id="default", user_id="default")
    print(f"  用默认 scope 查询：{len(leaked)} 条")
    print("  用 `SELECT * FROM memories` 查询（很多'临时排查脚本'就是这么写的）：")
    rows = store.conn.execute("SELECT tenant_id, user_id, content FROM memories").fetchall()
    for t, u, content in rows:
        print(f"    [{t}/{u}] {content}")
    print()
    print("  上面这几行就是一次真实的越权：你看到了别的租户的过敏史。")
    print("  在真实系统里，这行 SQL 可能就躺在某次故障排查的脚本里，然后被复制进了生产。")

    print("\n" + "=" * 80)
    print("三条召回规则")
    print("=" * 80)
    print("  1. scope 必须是查询的**前置条件**，不是可选项（先隔离，再排序）")
    print("  2. 只取 top-3~top-5：多了就是噪声，而且贵")
    print("  3. 记忆要和检索材料**分开标注**：模型得分清『我记得的』和『查到的』")
    print()
    print("  第 3 条的原因：记忆可能是错的、可能是旧的。")
    print("  如果和检索到的资料混在一起，模型无法判断该信谁。")


if __name__ == "__main__":
    main()
