"""第 27 章 step4：程序记忆 —— 只记成功过的流程，并且要版本化。

运行：
    python code/ch27_long_memory/step4_procedural.py

上一级的痛点：事件记下来了，但"该怎么做"还没有地方放。
这一级做什么：把 agent 的成功经验沉淀成可复用的 SOP，并证明——
             **记失败的流程比不记更糟**。

为什么失败的流程不能进程序记忆？
因为程序记忆会被"照着执行"。你没法照着一次失败跑一遍。
失败的教训属于第 20 章的 Reflexion lessons（那是一段"注意事项"，不是"步骤清单"）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.long_memory import MemoryKind, MemoryStore, MemoryWriter  # noqa: E402

SCOPE = {"tenant_id": "shop-1", "user_id": "u-zhang"}

# 三次执行同一个流程：第一次失败，第二次成功，第三次成功但步骤变多
RUNS = [
    (
        ["查订单", "验证是否在 15 天内", "上传故障视频", "寄回", "等待检测", "发货"],
        False,
        "第 3 步视频格式不对，卡住了 —— 漏了一步『转换格式』",
    ),
    (
        ["查订单", "验证是否在 15 天内", "上传故障视频", "寄回", "等待检测", "发货"],
        True,
        "标准流程跑通",
    ),
    (
        ["查订单", "验证是否在 15 天内", "上传故障视频", "转换视频格式", "寄回", "等待检测", "48h 内发新机"],
        True,
        "加了格式转换与 48 小时承诺，跑通",
    ),
]


def main() -> None:
    store = MemoryStore()
    w = MemoryWriter(store, min_importance=0.3)
    name = "换新处理"

    print("=" * 78)
    print("三次执行同一个流程")
    print("=" * 78)
    for i, (steps, ok, note) in enumerate(RUNS, 1):
        result = w.write_procedural(name, steps, success=ok, **SCOPE)
        verdict = "写入" if result else "不写入"
        print(f"  第 {i} 次：{len(steps)} 步  {'成功' if ok else '失败'}  → {verdict}")
        print(f"           （{note}）")

    print("\n" + "=" * 78)
    print("现在库里的程序记忆")
    print("=" * 78)
    active = store.query(kind=MemoryKind.PROCEDURAL, **SCOPE)
    for m in active:
        print(f"  生效中：{m.key}（{len(__import__('json').loads(m.content))} 步）")

    all_versions = store.query(kind=MemoryKind.PROCEDURAL, include_superseded=True, **SCOPE)
    print(f"\n  历史版本共 {len(all_versions)} 个（含被取代的）：")
    for m in all_versions:
        state = "已取代" if m.superseded_by else "生效中"
        print(f"    [{state}] {m.content}")

    print("\n" + "=" * 78)
    print("★ 只有成功的才进来的证据")
    print("=" * 78)
    failed = w.write_procedural(name, ["查订单", "卡住了"], success=False, **SCOPE)
    print(f"  直接写一个失败流程 → 返回值 {failed}（None 表示拒绝写入）")
    print()
    print("  如果放行会怎样？下次 Agent 检索到这个版本，会照着『卡住的那一次』做一遍。")
    print("  失败的教训应该进 Reflexion 的 lessons：")
    print("    lessons = 『上传故障视频前，先统一转成 mp4』  ← 这是一条提醒")
    print("    程序记忆 = 『查订单 → 验证时效 → 转格式 → 上传 → …』 ← 这是一份可执行清单")
    print("  形态不同，用途不同，**不要混着放**。")

    print("\n" + "=" * 78)
    print("版本化的价值：能回滚，也能追溯")
    print("=" * 78)
    print("  第 3 次成功后，第 2 次的版本被标为 superseded_by。")
    print("  这让你能回答两个问题：")
    print("    · 「48 小时承诺是哪个版本加的？」→ 看变更点")
    print("    · 「新流程出问题时，能切回旧版吗？」→ 旧版还在，只是不生效")
    print()
    print("  如果直接 UPDATE 覆盖，这两个问题就都答不出来了。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  程序记忆的两个硬规则：")
    print("    1. 只在成功时写入（失败 = 不可执行 = 不属于程序记忆）")
    print("    2. 版本化，不覆盖（要能回滚、能追溯）")
    print("  少任何一个，你的『经验积累』最后会变成一个会误导人的知识库。")


if __name__ == "__main__":
    main()
