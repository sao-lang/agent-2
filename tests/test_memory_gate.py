"""第 17 章产出：短期记忆的回归门禁（离线，无 API，毫秒级）。

它守住两件事：
  1. 槽位能保住"永不淘汰"的字段（滑窗保不住的那些）
  2. 上下文**绝不**超过 max_tokens（第 17 章那个静默 bug 的回归）

运行：
    pytest tests/test_memory_gate.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import est_tokens  # noqa: E402
from common.short_memory import ShortTermMemory, Slots  # noqa: E402

DIALOG = [
    ("我叫张伟，是做物流的，人在杭州。", "你好张伟。"),
    ("订单号 A12345，上周买的蓝牙耳机，预算本来 500 元以内。", "记下了。"),
    *[(f"你们最近有什么活动（第 {i} 次问）？", "满 300 减 30，会员 9 折。") for i in range(8)],
]

FACTS = ("张伟", "杭州", "A12345", "500", "蓝牙耳机")


# ---------------------------------------------------------------- 槽位

def test_slots_capture_all_facts() -> None:
    """开场三句里的事实，必须全部进槽位。"""
    slots = Slots()
    for user, _ in DIALOG[:2]:
        slots.capture(user)
    values = set(slots.values.values())
    assert {"张伟", "杭州", "A12345", "500", "蓝牙耳机"} <= values


def test_slots_do_not_overwrite_without_signal() -> None:
    """没有改口信号时，已填的槽位不能被后来的话冲掉。"""
    slots = Slots()
    slots.capture("订单号 A12345")
    slots.capture("订单号 A12345，上周买的蓝牙耳机")
    assert slots.values["order_id"] == "A12345"


def test_slots_override_on_restate() -> None:
    """明确说"改成"时必须覆盖，否则用户改口就失效。"""
    slots = Slots()
    slots.capture("订单号 A12345")
    slots.capture("订单号改成 B67890")
    assert slots.values["order_id"] == "B67890"


# ---------------------------------------------------------------- 预算

@pytest.mark.parametrize("budget", [0, 20, 60, 120, 200, 400, 2000])
def test_context_never_exceeds_budget(budget: int) -> None:
    """核心回归：任何预算下，上下文总 token 都不能超。

    这是 4.5 节那个 `max(x, 300)` bug 的门禁。
    """
    mem = ShortTermMemory(max_tokens=budget)
    for user, assistant in DIALOG:
        mem.add_user(user)
        mem.add_assistant(assistant)
    ctx = mem.build_context()
    total = sum(est_tokens(m["content"]) for m in ctx)
    assert total <= budget, f"预算 {budget}，实际 {total}"


def test_facts_survive_small_budget() -> None:
    """预算再小，槽位里的关键事实也不能被压缩掉（只要配额装得下）。"""
    mem = ShortTermMemory(max_tokens=120)
    for user, assistant in DIALOG:
        mem.add_user(user)
        mem.add_assistant(assistant)
    text = "\n".join(m["content"] for m in mem.build_context())
    kept = [f for f in FACTS if f in text]
    assert len(kept) >= 4, f"只保住了 {kept}"


def test_context_starts_with_system_or_user() -> None:
    """窗口起点不能是一个"没头"的 assistant 消息。"""
    mem = ShortTermMemory(max_tokens=60)
    for user, assistant in DIALOG:
        mem.add_user(user)
        mem.add_assistant(assistant)
    ctx = mem.build_context()
    assert ctx, "上下文为空"
    assert ctx[0]["role"] == "system"
    assert ctx[1]["role"] == "user", "system 之后的第一个角色必须是 user"
