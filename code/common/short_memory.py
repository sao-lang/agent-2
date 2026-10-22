"""第 16 章产出：短期记忆（工作记忆）的生产实现。

三个核心能力：
  1. 固定槽位（pinned slots）：无论多少轮，这几个事实永远在上下文里
  2. 混合压缩：事实全留 + 其余摘要（复用第 10 章的 compress_hybrid）
  3. 会话状态：当前任务、已完成步骤、待办（工作记忆，不是聊天记录）

为什么"槽位"比"选择性保留"更好？
因为选择性保留要每次重新判定"哪条重要"（可能判定错），
而槽位是**首次出现就固定下来**，之后永不丢失。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from common.context import est_tokens


# ============================================================ 固定槽位

# 注意：这些是【原始字符串】。写 pattern 时要么用 "^\s*" 这种双反斜杠转义，
# 要么在字符类里用单反斜杠（r"[-A-Za-z0-9]"）。混用是这里最容易踩的坑。
_ORDER_RE = (
    r"订单号?\s*(?:[:：]\s*|改成\s*|换成\s*|\s+)?([A-Za-z0-9][A-Za-z0-9-]{3,19})"
)

SLOT_PATTERNS: dict[str, list[str]] = {
    "name": [r"我叫(?:做)?([\u4e00-\u9fff]{2,3})"],
    "order_id": [_ORDER_RE],
    "budget": [r"预算[^0-9]{0,6}?(\d+(?:\.\d+)?)\s*(?:元|块)"],
    "city": [r"我?(?:在|住在)([\u4e00-\u9fff]{2,6}?)(?:[，。,.]|$)"],
    "product": [r"(?:买的|买了)([\u4e00-\u9fffA-Za-z0-9]{2,12})"],
}

# 改口信号：出现这些词时，允许覆盖已填的槽位
OVERRIDE_MARKERS = ("改成", "换成", "更正", "改为", "不是", "重填")


@dataclass
class Slots:
    """固定槽位：一旦填上，永不淘汰。

    这是短期记忆里"最不能丢"的那部分。
    与"选择性保留"的区别：
      · 选择性保留：每轮重新判定（有判定错误的风险）
      · 槽位：首次捕获即固定（也有捕获错误的风险，但可以人工纠正）
    """

    values: dict[str, str] = field(default_factory=dict)

    def capture(self, text: str, override: bool | None = None) -> list[str]:
        """从用户消息里捕获槽位。返回本次新填/更新的槽位名。

        override=None（默认）时自动检测改口信号（"改成/换成/更正"…）：
        出现信号就允许覆盖，否则已填的槽位保持不变。
        显式传 True/False 可以强制放行或锁定。
        """
        if override is None:
            override = any(k in text for k in OVERRIDE_MARKERS)
        updated = []
        for slot, pats in SLOT_PATTERNS.items():
            if slot in self.values and not override:
                continue
            for p in pats:
                m = re.search(p, text)
                if m:
                    self.values[slot] = m.group(1)
                    updated.append(slot)
                    break
        return updated

    def render(self) -> str:
        if not self.values:
            return ""
        lines = [f"- {k}: {v}" for k, v in self.values.items()]
        return "【已知信息（务必记住）】\n" + "\n".join(lines)

    def to_dict(self) -> dict[str, str]:
        return dict(self.values)


# ============================================================ 工作记忆

@dataclass
class WorkingMemory:
    """工作记忆：当前任务的执行状态，不是聊天记录。

    和第 9 章的 checkpoint 的区别：
      · checkpoint 是"系统状态快照"（用于恢复）
      · working memory 是"要喂给模型的上下文摘要"（用于推理）
    两者可以有重叠，但目的不同。
    """

    task: str = ""
    done: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        if self.task:
            parts.append(f"【当前任务】{self.task}")
        if self.done:
            parts.append("【已完成】\n" + "\n".join(f"- {d}" for d in self.done[-5:]))
        if self.todo:
            parts.append("【待办】\n" + "\n".join(f"- {t}" for t in self.todo[:5]))
        if self.constraints:
            parts.append("【约束】\n" + "\n".join(f"- {c}" for c in self.constraints))
        return "\n\n".join(parts)


# ============================================================ 短期记忆

@dataclass
class ShortTermMemory:
    """完整的短期记忆：槽位 + 工作记忆 + 压缩后的历史。"""

    max_tokens: int = 2000
    slots: Slots = field(default_factory=Slots)
    working: WorkingMemory = field(default_factory=WorkingMemory)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_user(self, text: str) -> list[str]:
        self.messages.append({"role": "user", "content": text})
        return self.slots.capture(text)

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    # 固定开销（槽位 + 工作记忆）最多占预算的这个比例，其余留给最近对话。
    # 为什么要有上限？见 4.5 节的复现：不加限制时，槽位一多就会挤爆预算。
    fixed_ratio: float = 0.4

    # 槽位超配额时按这个优先级保留（数字越大越不能丢）。
    # 没列出的字段默认优先级 0。
    slot_priority: dict[str, int] = field(
        default_factory=lambda: {"order_id": 5, "name": 4, "budget": 3, "city": 2, "product": 1}
    )

    def _render_fixed(self) -> str:
        """渲染固定开销，并保证它自己不超过 fixed_ratio 的预算。

        超了就按优先级逐字段丢弃——**宁可少一个字段，不要留半截值**。
        """
        fixed_budget = max(int(self.max_tokens * self.fixed_ratio), 0)

        items = sorted(self.slots.values.items(), key=lambda kv: -self.slot_priority.get(kv[0], 0))
        kept: list[str] = []
        for k, v in items:
            candidate = kept + [f"- {k}: {v}"]
            if est_tokens("【已知信息（务必记住）】\n" + "\n".join(candidate)) > fixed_budget:
                continue
            kept = candidate

        parts = []
        if kept:
            parts.append("【已知信息（务必记住）】\n" + "\n".join(kept))
        working = self.working.render()
        if working:
            parts.append(working)

        text = "\n\n".join(parts)
        # 工作记忆也可能单独超配额：整段丢，而不是截断（截断的待办列表会误导模型）
        return text if est_tokens(text) <= fixed_budget else "\n\n".join(kept_head for kept_head in parts[:1])

    def build_context(self) -> list[dict[str, Any]]:
        """组装要喂给模型的历史。

        优先级：槽位 > 工作记忆 > 最近对话
        硬约束：sum(est_tokens(m["content"])) <= max_tokens
        """
        fixed_text = self._render_fixed()
        fixed_tokens = est_tokens(fixed_text) if fixed_text else 0
        remain = max(self.max_tokens - fixed_tokens, 0)  # 下限是 0，不是 300

        # 最近对话：按 token 从后往前装，装不下就停
        recent: list[dict[str, Any]] = []
        used = 0
        for m in reversed(self.messages):
            t = est_tokens(m["content"])
            if used + t > remain:
                break
            recent.append(m)
            used += t
        recent.reverse()

        out: list[dict[str, Any]] = []
        if fixed_text and est_tokens(fixed_text) <= self.max_tokens:
            out.append({"role": "system", "content": fixed_text})
        out.extend(recent)
        return out

    def build_context_v2(self) -> list[dict[str, Any]]:
        """⚠️ 有预算问题的版本，只用于第 16 章的失败实验。

        问题：槽位 + 工作记忆是"固定开销"，它们可能**单独就超过 max_tokens**。
        build_context() 里 remain 用了 max(..., 300) 兜底，
        结果实际上下文会超出预算（示例里 294 > 120）。

        正确做法二选一：
          a) 预算里给"固定开销"单独留出配额（推荐）
          b) 槽位也做上限（比如最多 10 个字段，每个 20 字）
        """
        return self.build_context()

    def stats(self) -> dict[str, Any]:
        slots_t = est_tokens(self.slots.render())
        work_t = est_tokens(self.working.render())
        msgs_t = sum(est_tokens(m["content"]) for m in self.messages)
        ctx = self.build_context()
        ctx_t = sum(est_tokens(m["content"]) for m in ctx)
        return {
            "total_messages": len(self.messages),
            "raw_tokens": msgs_t,
            "slots_tokens": slots_t,
            "working_tokens": work_t,
            "context_tokens": ctx_t,
            "compression": 1 - ctx_t / msgs_t if msgs_t else 0,
        }
