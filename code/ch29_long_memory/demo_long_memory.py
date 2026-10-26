"""第 28 章示例：三层长期记忆的写入、冲突、衰减与隔离（不需要 API）。

运行：
    python code/ch29_long_memory/demo_long_memory.py

演示五件事：
  1. 语义记忆的去重与冲突（用户改口怎么办）
  2. 情景记忆只增不改 + 时间衰减
  3. 程序记忆必须成功才写入
  4. 多租户隔离（A 用户的记忆不能给 B 用户）
  5. 淘汰策略（分数最低的先走）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.long_memory import (  # noqa: E402
    MemoryKind,
    MemoryStore,
    MemoryWriter,
    prune,
    retrieve,
)


def main() -> None:
    store = MemoryStore()
    w = MemoryWriter(store, min_importance=0.3)
    scope = {"tenant_id": "shop-1", "user_id": "u-zhang"}

    print("=" * 72)
    print("① 语义记忆：去重与冲突")
    print("=" * 72)
    r1 = w.write_semantic("pref.mango", "用户对芒果过敏，禁止推荐含芒果的商品", 0.95, **scope)
    print(f"  第一次写入：{r1['action']}")

    r2 = w.write_semantic("pref.mango", "用户对芒果过敏，禁止推荐含芒果的商品", 0.95, **scope)
    print(f"  重复写入：{r2['action']}（不新增，只更新使用计数）")

    r3 = w.write_semantic("pref.mango", "用户说可以吃芒果了，过敏症状已消失", 0.7, **scope)
    print(f"  改口后：{r3['action']}")
    if r3["action"] == "superseded":
        print(f"    旧内容：{r3['old_content']}")
        print(f"    冲突度：{r3['conflict_ratio']}  需要人工确认：{r3['needs_review']}")
    print("  -> 高冲突场景（'过敏'vs'不过敏'）必须人工确认，否则会误伤用户")

    print("\n" + "=" * 72)
    print("② 情景记忆：只增不改 + 时间衰减")
    print("=" * 72)
    now = time.time()
    # 手工构造不同时间的记忆，演示衰减
    from common.long_memory import Memory

    for days, content in [(0, "今天处理了订单 A12345 的换新申请"), (7, "上周咨询过运费规则"),
                          (60, "两个月前问过会员权益")]:
        store.write(Memory(
            id=f"epi-{days}", kind=MemoryKind.EPISODIC, key="", content=content,
            importance=0.5, created_at=now - days * 86400, **scope,
        ))

    print(f"  {'内容':<34}{'天数':>6}{'分数':>8}")
    print("  " + "-" * 48)
    for m, s in sorted(retrieve(store, kind=MemoryKind.EPISODIC, limit=10, **scope),
                       key=lambda x: x[0].created_at, reverse=True):
        age = int((now - m.created_at) / 86400)
        print(f"  {m.content:<34}{age:>6}{s:>8.3f}")
    print("  -> 分数随时间衰减：60 天前的那条几乎不会再被检索到")

    print("\n" + "=" * 72)
    print("③ 程序记忆：只在成功时写入")
    print("=" * 72)
    failed = w.write_procedural("换新处理", ["查订单", "失败了"], success=False, **scope)
    print(f"  失败流程写入结果：{failed}（None = 不写入，符合预期）")

    ok1 = w.write_procedural("换新处理",
                             ["查订单", "验证是否在 15 天内", "上传故障视频", "寄回", "等待检测"],
                             success=True, **scope)
    print(f"  成功流程写入：{ok1 is not None}")
    ok2 = w.write_procedural("换新处理",
                             ["查订单", "验证是否在 15 天内", "上传故障视频", "寄回", "等待检测", "48h 内发新机"],
                             success=True, **scope)
    print(f"  更新后的流程：{ok2 is not None}")
    current = store.find_by_key("换新处理", kind=MemoryKind.PROCEDURAL, **scope)
    print(f"  当前生效版本步骤数：{len(__import__('json').loads(current.content))}")

    print("\n" + "=" * 72)
    print("④ 多租户隔离")
    print("=" * 72)
    w.write_semantic("pref.mango", "该用户可以吃芒果", 0.9, tenant_id="shop-2", user_id="u-li")
    zhang = store.query(tenant_id="shop-1", user_id="u-zhang")
    li = store.query(tenant_id="shop-2", user_id="u-li")
    print(f"  u-zhang 的记忆：{[m.content[:16] for m in zhang]}")
    print(f"  u-li    的记忆：{[m.content[:16] for m in li]}")
    print("  -> 同一个 key（pref.mango）在不同 scope 下完全独立")
    print("  [!]  如果 query 忘了带 tenant_id，就会串号——这是最严重的数据泄露")

    print("\n" + "=" * 72)
    print("⑤ 淘汰策略")
    print("=" * 72)
    for i in range(12):
        store.write(Memory(
            id=f"bulk-{i}", kind=MemoryKind.EPISODIC, key="", content=f"批量记忆 {i}",
            importance=0.2 + i * 0.05, created_at=now - i * 86400, **scope,
        ))
    before = len(store.query(**scope))
    dropped = prune(store, keep=8, **scope)
    after = len(store.query(**scope))
    print(f"  淘汰前：{before} 条    淘汰后：{after} 条    软删除：{dropped} 条")
    print("  -> 软删除（superseded_by='PRUNED'），数据没真删，可追溯")

    print("\n" + "=" * 72)
    print("⑥ 检索打分公式")
    print("=" * 72)
    print("  score = importance × 0.5^(age_days/30) × (1 + ln(1+use_count))")
    print("\n  三个因子各管一件事：")
    print("    · importance：这件事本身有多重要（写的时候定的）")
    print("    · 时间衰减  ：半衰期 30 天，三个月前的记忆分数只剩 1/8")
    print("    · 使用频率  ：被反复用到的记忆应该更容易被找到")
    print("\n  [!] 这个公式是起点，不是真理。你的场景可能需要调整半衰期。")

    store.close()


if __name__ == "__main__":
    main()
