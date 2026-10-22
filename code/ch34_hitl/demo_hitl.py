"""第 33 章示例：HITL 的完整链路（不需要 API）。

运行：
    python code/ch33_hitl/demo_hitl.py

演示五个场景：
  1. 自动执行（只读动作，不打扰人）
  2. 中断 + 确认 + 恢复
  3. 中断 + 拒绝
  4. 中断 + 修改参数后批准（人改金额）
  5. 幂等：恢复两次不会重复执行副作用
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.hitl import HitlService, ACTION_LEVELS, make_card  # noqa: E402


def main() -> None:
    svc = HitlService()

    print("=" * 74)
    print("① 只读动作：自动执行，不打扰人")
    print("=" * 74)
    r = svc.start("t-auto", "帮我查一下订单状态")
    print(f"  状态：{r['status']}")
    print(f"  结果：{r.get('result')}")
    print(f"  日志：{r.get('log')}")

    print("\n" + "=" * 74)
    print("② 写动作：中断 → 人工确认 → 恢复执行")
    print("=" * 74)
    r = svc.start("t-1", "帮我给 A12345 退款 299 元")
    print(f"  状态：{r['status']}")
    card = r["card"]
    print("  审批卡片：")
    print(f"    动作：{card['action']} {card['args']}")
    print(f"    影响：{card['impact']}")
    print(f"    回滚：{card['rollback']}")
    print(f"    有效期：{card['expires_in_sec']} 秒")

    snap = svc.state("t-1")
    print(f"\n  挂起时的执行位置：next={snap['next']}")
    print(f"  已执行的动作：{snap['values'].get('executed')}")

    print("\n  人工点击【批准】……")
    r = svc.approve("t-1", "approve")
    print(f"  状态：{r['status']}")
    print(f"  结果：{r.get('result')}")
    print(f"  日志：{r.get('log')}")

    print("\n" + "=" * 74)
    print("③ 写动作：中断 → 人工拒绝")
    print("=" * 74)
    svc.start("t-2", "帮我给 A12345 退款 299 元")
    r = svc.approve("t-2", "reject")
    print(f"  状态：{r['status']}")
    print(f"  结果：{r.get('result')}")
    print(f"  日志：{r.get('log')}")

    print("\n" + "=" * 74)
    print("④ 写动作：中断 → 人修改参数 → 批准")
    print("=" * 74)
    svc.start("t-3", "帮我给 A12345 退款 299 元")
    r = svc.approve("t-3", "modify", new_args={"order": "A12345", "amount": 199.0})
    print(f"  状态：{r['status']}")
    print(f"  结果：{r.get('result')}   ← 注意金额变成了 199")
    print(f"  日志：{r.get('log')}")

    print("\n" + "=" * 74)
    print("⑤ 幂等：恢复两次不会重复执行")
    print("=" * 74)
    svc.start("t-4", "帮我给 A12345 退款 299 元")
    r1 = svc.approve("t-4", "approve")
    print(f"  第一次恢复：{r1.get('result')}")
    r2 = svc.approve("t-4", "approve")
    print(f"  第二次恢复：{r2.get('result')}")
    print(f"  日志：{r2.get('log')}")
    print("  → 幂等键命中，跳过执行。这就是第 36 章讲的副作用保护。")

    print("\n" + "=" * 74)
    print("⑥ 审批分级表")
    print("=" * 74)
    print(f"  {'动作':<16}{'级别':<10}说明")
    print("  " + "-" * 60)
    for action, level in ACTION_LEVELS.items():
        note = {
            "auto": "自动执行",
            "notify": "执行后通知",
            "confirm": "需人工确认",
            "forbid": "禁止执行",
        }[level.value]
        print(f"  {action:<16}{level.value:<10}{note}")

    print("\n  ⚠️ 未登记的动作默认 = confirm（而不是 auto）。")
    print("     这是 HITL 版本的 default deny。")

    print("\n" + "=" * 74)
    print("⑦ 一张好的审批卡片长什么样")
    print("=" * 74)
    c = make_card("refund", {"order": "A12345", "amount": 299})
    print(f"  请求 ID：{c.request_id}")
    print(f"  影响面：{c.impact}")
    print(f"  回滚方案：{c.rollback}")
    print(f"  有效期：{c.expires_at - __import__('time').time():.0f} 秒")
    print("\n  三要素缺一个，人就无法判断：")
    print("    · 没有影响面 → 不知道要改什么")
    print("    · 没有回滚方案 → 不敢点批准")
    print("    · 没有有效期 → 人不在时任务永远挂着，或者三天后又执行了")


if __name__ == "__main__":
    main()
