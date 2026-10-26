"""第 27 章 step3：换掉正则 —— 用 schema + 校验的方式抽取槽位。

运行：
    python code/ch28_short_memory/step3_schema_slots.py

上一级的痛点：正则能填满槽位，但会误捕获（"我叫他帮我看看" → name="他帮我"），
            而且规则一多就没人敢改。
这一级做什么：把「抽什么」和「怎么抽」分开。

  · 抽什么 → 一份 schema（字段名 + 类型 + 说明），业务方看得懂
  · 怎么抽 → 可替换的实现：正则版 / 假模型版 / 真模型版

本脚本离线跑：用一个**规则模拟的抽取器**代替模型，但它必须遵守 schema。
这样你能看清"分层"带来的好处，而不用花 API 钱。

真模型版本见 demo_short_memory_llm.py（需要 API key）。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ============================================================ ① schema：抽什么

@dataclass
class SlotSchema:
    """槽位 schema。业务方看这个就够，不需要看懂正则。"""

    name: str
    desc: str
    pattern: str  # 本文件的"离线抽取器"用它模拟模型；真模型只读 desc
    examples: list[str] = field(default_factory=list)


SCHEMA: list[SlotSchema] = [
    SlotSchema("name", "用户的姓名（不是别人的名字）", r"我叫(?:做)?([\u4e00-\u9fff]{2,3})(?:[，。,.]|$)",
               ["我叫张伟，", "我叫李四。"]),
    SlotSchema("city", "用户所在城市", r"我?(?:在|住在)([\u4e00-\u9fff]{2,6}?)(?:[，。,.]|$)",
               ["人在杭州。", "我住在上海。"]),
    SlotSchema("order_id", "订单号", r"订单号?\s*(?:[:：]\s*|改成\s*|换成\s*|\s+)?([A-Za-z0-9][A-Za-z0-9-]{3,19})",
               ["订单号 A12345", "订单号：B67890"]),
    SlotSchema("budget", "预算金额（只取数字）", r"预算[^0-9]{0,6}?(\d+(?:\.\d+)?)\s*(?:元|块)",
               ["预算本来 500 元以内"]),
    SlotSchema("product", "买的商品", r"(?:买的|买了)([\u4e00-\u9fffA-Za-z0-9]{2,12})",
               ["买的蓝牙耳机"]),
]

# 否定上下文：出现这些词时，整句不抽（模拟模型的"意图判断"）
NEGATIVE_CONTEXT = ("别人", "他", "她", "朋友", "同事", "帮我看看")
# 改口信号：出现时允许覆盖
OVERRIDE_MARKERS = ("改成", "换成", "更正", "改为")


# ============================================================ ② 抽取器：怎么抽

class RuleExtractor:
    """离线替身：按 schema 的正则抽 + 一次"意图检查"。

    它比上一级的裸正则强的地方，**不在正则本身**，而在于：
      1. 字段定义收敛到 schema 一处（加字段不改抽取逻辑）
      2. 抽之前先做一次上下文判断（"他/她/帮我看看" → 这不是在说自己）
      3. 抽完带置信度，低置信度交给用户确认
    """

    def extract(self, text: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        negated = any(k in text for k in NEGATIVE_CONTEXT)
        override = any(k in text for k in OVERRIDE_MARKERS)
        import re

        for sch in SCHEMA:
            m = re.search(sch.pattern, text)
            if not m:
                continue
            out[sch.name] = {
                "value": m.group(1),
                "confidence": 0.95 if override else (0.3 if negated else 0.9),
                "evidence": text[max(0, m.start() - 2): m.end()],
            }
        return out


class Slots2:
    """带置信度的槽位。低置信度不直接落库，先挂"待确认"。"""

    def __init__(self, threshold: float = 0.7) -> None:
        self.values: dict[str, str] = {}
        self.pending: dict[str, dict] = {}
        self.threshold = threshold
        self.history: list[tuple[str, str, str]] = []  # (字段, 旧值, 新值)

    def update(self, text: str, extractor: RuleExtractor) -> dict[str, list[str]]:
        result = {"accepted": [], "pending": [], "updated": []}
        override = any(k in text for k in OVERRIDE_MARKERS)

        for slot, info in extractor.extract(text).items():
            if info["confidence"] < self.threshold:
                self.pending[slot] = info
                result["pending"].append(slot)
                continue
            old = self.values.get(slot)
            if old is not None and old != info["value"] and not override:
                continue  # 已填且没有改口信号 → 保持原值
            if old != info["value"]:
                self.history.append((slot, old or "", info["value"]))
                result["updated" if old else "accepted"].append(slot)
                self.values[slot] = info["value"]
        return result

    def render(self) -> str:
        if not self.values:
            return ""
        lines = [f"- {k}: {v}" for k, v in self.values.items()]
        return "【已知信息】\n" + "\n".join(lines)

    def render_pending(self) -> str:
        if not self.pending:
            return ""
        lines = [f"- {k}: {v['value']} ？" for k, v in self.pending.items()]
        return "【需要确认（可能听错了）】\n" + "\n".join(lines)


# ============================================================ 演示

CASES = [
    ("我叫张伟，是做物流的，人在杭州。", "正常自我介绍"),
    ("订单号 A12345，上周买的蓝牙耳机，预算本来 500 元以内。", "正常下单信息"),
    ("我叫他帮我看看这个订单", "误捕获陷阱：主语不是自己"),
    ("我朋友叫李雷，他住在南京", "误捕获陷阱：说的是别人"),
    ("订单号改成 B67890", "改口：必须覆盖旧值"),
]


def main() -> None:
    print("=" * 78)
    print("换掉正则：把「抽什么」和「怎么抽」分开")
    print("=" * 78)
    print("schema（业务方看这一份就够了）：")
    for sch in SCHEMA:
        print(f"    {sch.name:<10}{sch.desc}")
    print()

    slots = Slots2(threshold=0.7)
    ex = RuleExtractor()

    for text, note in CASES:
        result = slots.update(text, ex)
        print(f"  输入：{text}")
        print(f"        （{note}）")
        print(f"    接受 {result['accepted']}  更新 {result['updated']}  待确认 {result['pending']}")
        print()

    print("=" * 78)
    print("最终槽位")
    print("=" * 78)
    print(slots.render() or "  （空）")
    if slots.pending:
        print()
        print(slots.render_pending())

    print("\n" + "=" * 78)
    print("这一级解决了什么")
    print("=" * 78)
    print("  ① 误捕获没被『修正』，而是被**标记出来**了：")
    print("     「我朋友叫李雷，他住在南京」→ 抽到的 city 进了待确认，没有覆盖杭州。")
    print("  ② 改口生效了：history 里能看到 A12345 → B67890 的变更记录。")
    print("  ③ 加字段只改 SCHEMA，不改抽取逻辑。")
    print()
    print("  ⚠️ 但请诚实看这件事：上面那个 RuleExtractor 依然是个规则替身。")
    print("     它被判『对』是因为我们事先知道该拦哪些词。")
    print("     换成真模型，误捕获会少很多，但会引入新的错法（见 26.7 失败实验 C）。")
    print("     **没有任何一种抽取方法是 100% 可靠的** —— 所以「待确认」这一层永远要留。")


if __name__ == "__main__":
    main()
