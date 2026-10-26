"""第 27 章 step4：为什么"组件都对"，拼起来仍然会超预算。

运行：
    python code/ch28_short_memory/step4_budget_overflow.py

上一级的痛点：槽位能保住事实了，但你可能没注意到 —— 上下文反而变长了。
这一级做什么：复现一个**静默的**预算超支，并给出修法。

这是本章唯一一个"看起来没 bug，实际全是 bug"的地方：
  · 代码不报错
  · 单元测试全绿
  · 只有把 token 真的算出来，才发现超了

⚠️ `code/common/short_memory.py` 里的这个 bug **已经修好**。
   本脚本把修复前的写法原样放在下面（build_buggy），用来复现它。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import est_tokens  # noqa: E402
from common.short_memory import ShortTermMemory  # noqa: E402

DIALOG: list[tuple[str, str]] = [
    ("我叫张伟，是做物流的，人在杭州。", "你好张伟，很高兴认识你。"),
    ("订单号 A12345，上周买的蓝牙耳机，预算本来 500 元以内。", "记下了订单 A12345，预算 500 元。"),
    *[(f"顺便问下你们最近有什么活动（第 {i} 次问）？", "本月满 300 减 30，会员额外 9 折。") for i in range(10)],
]


# ============================================================ 修复前的写法（保持原样，供复现）

def build_buggy(mem: ShortTermMemory) -> list[dict]:
    """这就是修复前 build_context 的逻辑。

    问题在 `remain = max(self.max_tokens - fixed_tokens, 300)`：
    固定开销一旦超了，还要**保底给最近对话 300 token**，于是总量突破上限。
    """
    slots_text = mem.slots.render()
    working_text = mem.working.render()
    fixed = [x for x in (slots_text, working_text) if x]
    fixed_tokens = sum(est_tokens(x) for x in fixed)

    remain = max(mem.max_tokens - fixed_tokens, 300)  # ← 300 这个下限就是 bug

    recent: list[dict] = []
    used = 0
    for m in reversed(mem.messages):
        t = est_tokens(m["content"])
        if used + t > remain:
            break
        recent.append(m)
        used += t
    recent.reverse()

    out: list[dict] = []
    if fixed:
        out.append({"role": "system", "content": "\n\n".join(fixed)})
    out.extend(recent)
    return out


# ============================================================ 演示

def tokens_of(ctx: list[dict]) -> int:
    return sum(est_tokens(m["content"]) for m in ctx)


def facts_in(ctx: list[dict]) -> int:
    text = "\n".join(m["content"] for m in ctx)
    return sum(1 for v in ("张伟", "杭州", "A12345", "500", "蓝牙耳机") if v in text)


def build_mem(budget: int) -> ShortTermMemory:
    mem = ShortTermMemory(max_tokens=budget)
    for u, a in DIALOG:
        mem.add_user(u)
        mem.add_assistant(a)
    return mem


def main() -> None:
    print("=" * 80)
    print("复现：组件都对，拼起来超预算")
    print("=" * 80)
    print(f"{'预算':>6}{'修复前token':>12}{'超支':>8}{'修好后token':>12}{'事实 前/后':>14}")
    print("-" * 54)
    for budget in (60, 120, 200, 400):
        mem = build_mem(budget)
        before_ctx = build_buggy(mem)
        after_ctx = mem.build_context()
        b, a = tokens_of(before_ctx), tokens_of(after_ctx)
        over = f"+{b - budget}" if b > budget else "—"
        facts = f"{facts_in(before_ctx)}/{facts_in(after_ctx)}"
        print(f"{budget:>6}{b:>12}{over:>8}{a:>12}{facts:>14}")

    print("\n" + "=" * 80)
    print("为什么它这么难发现")
    print("=" * 80)
    print("  ① 不报错：只是拼出来的字符串长了一点")
    print("  ② 不抛异常：模型照样能读，最多是慢一点、贵一点")
    print("  ③ 单元测试容易漏：你测的是『槽位有没有值』，不是『总 token 是多少』")
    print()
    print("  → 所以每个涉及预算的函数，都必须能回答：")
    print("     sum(est_tokens(m['content']) for m in 结果) <= budget ?")

    print("\n" + "=" * 80)
    print("修法：固定开销先自限，且绝不截出半截值")
    print("=" * 80)
    mem = build_mem(120)
    sys_msg = mem.build_context()[0]["content"]
    print("  预算 120 时，修好后的 system 消息：")
    for line in sys_msg.split("\n"):
        print(f"    {line}")
    used = est_tokens(sys_msg)
    print(f"\n  只占 {used} token，给最近对话留了 {120 - used}。")

    print("\n  三个关键决定：")
    print("    · 固定开销的配额 = 预算 × 0.4（写死在 fixed_ratio）")
    print("    · 超配额时**按优先级丢整个字段**，不截断（半截的订单号比没有更糟）")
    print("    · 剩余预算按 token 装最近消息，下限是 0 而不是 300")

    print("\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    print("  任何 `max(x, 某个下限)` 都可能突破上层约束。")
    print("  写完兜底逻辑，必须检查一句：兜底之后还满足硬约束吗？")


if __name__ == "__main__":
    main()
