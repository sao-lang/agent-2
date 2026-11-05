"""第 8 章 B3/B4/B5：四种守卫，每个都能单独关掉。

四个开关是 learn/mini_agent生长路线.md 里 v0.1 的硬要求：
    --no-dedupe          请求指纹（重复调用）
    --no-result-dedupe   结果指纹（换参数打转）
    --no-trim            单条消息裁剪（上下文爆炸）
    --no-budget          预算闸门（成本击穿）

关掉其中任何一个，**只有那一件事消失**，循环本身一行不改。
GuardSet 与一次任务一一对应（正文"守卫必须与任务同生命周期"），由装配层 new。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .state import Stats


# ── 第 8 章 B4：请求指纹 ─────────────────────────────────────────────────────
def fingerprint(name: str, arguments: str) -> str:
    """把 (工具名, 参数原文) 归一成一个指纹字符串。"""
    try:
        # sort_keys=True 是全部关键所在：模型生成参数的键序是随机的，
        # 不排序的话 {"a":1,"b":2} 与 {"b":2,"a":1} 会被算成两个不同的请求，
        # 去重彻底失效——这是本节最值钱的一行。
        normalized = json.dumps(json.loads(arguments), sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        # 参数不是合法 JSON 时不能让它炸：退回原文当指纹，让"坏参数"也能被去重
        normalized = arguments
    return f"{name}|{normalized}"      # 工具名也要进指纹：同名不同工具必须区分


# ── 第 8 章 B5：单条消息级裁剪 ───────────────────────────────────────────────
def trim_tool_content(content: str, limit: int = 200) -> str:
    """把一条 tool 消息裁到 limit 字符：留头 + 留尾，中间插截断标记。

    只裁这一条的 content，不动整段历史；只裁 tool 消息（system 是缓存前缀，
    user 是需求本身，assistant 与 tool 配对，都不能动）。
    """
    if len(content) <= limit:          # 没超就直接返回，不做任何改动
        return content
    head = content[: limit // 2]       # 留头：通常是结构信息
    tail = content[-(limit // 2):]     # 留尾：通常是结论或最后一条记录
    # 标记里带"截掉了多少字"：丢失必须被记录，否则排查方向必然错
    return f"{head}…[截断 {len(content) - limit} 字]…{tail}"


@dataclass
class GuardSet:
    """四个守卫 + 两个连续计数，收在一个对象里（正文"守卫对象"那一节）。

    检查顺序按正文排：先"确定在空转"的指纹/结果/连续，后"可能太贵"的预算。
    守卫只判断还要不要继续，不修数据、不重新生成、不决定交付什么。
    """

    stats: Stats
    dedupe: bool = True
    result_dedupe: bool = True
    trim: bool = True
    budget: bool = True
    max_dup_in_row: int = 2
    trim_limit: int = 200

    seen: set[str] = field(default_factory=set)              # 请求指纹全集
    seen_results: dict[str, str] = field(default_factory=dict)  # 结果指纹（键是裁剪后内容）
    dup_in_row: int = 0                                      # 连续重复请求
    same_result_in_row: int = 0                              # 连续相同结果

    # ① 事前闸门：已经花掉的钱收不回来，所以只能在发请求之前拦（第 8 章）
    def budget_exceeded(self, limit: int) -> bool:
        if not self.budget:
            return False
        return self.stats.prompt_tokens > limit

    # ② 请求指纹：先算指纹再做别的，顺序反了会先执行再发现重复
    def is_duplicate_call(self, name: str, arguments: str) -> bool:
        if not self.dedupe:
            return False
        fp = fingerprint(name, arguments)
        if fp in self.seen:
            self.stats.duplicate_blocked += 1
            self.dup_in_row += 1
            return True
        self.seen.add(fp)
        self.dup_in_row = 0
        return False

    # ③ 单条裁剪：裁的是这一条的 content，不是整段历史
    def trim_content(self, content: str) -> tuple[str, bool]:
        if not self.trim:
            return content, False
        trimmed = trim_tool_content(content, self.trim_limit)
        changed = trimmed != content
        if changed:                 # 只有真的变了才计数
            self.stats.trimmed += 1
        return trimmed, changed

    # ④ 结果指纹：用裁剪后的内容，长文本每次才会被裁成同一个样子
    def is_repeated_result(self, content: str, name: str) -> bool:
        if not self.result_dedupe:
            return False
        if content in self.seen_results:
            self.stats.repeated_result += 1       # 换参数打转：请求在变、结果不变
            self.same_result_in_row += 1
            return True
        self.seen_results[content] = name
        self.same_result_in_row = 0
        return False

    # ⑤ 空转判定：用"连续"次数，偶发重复不算；两种空转各有各的信号
    def stall_reason(self) -> str | None:
        if self.same_result_in_row >= self.max_dup_in_row:
            return f"连续 {self.same_result_in_row} 次拿到相同结果"
        if self.dup_in_row >= self.max_dup_in_row:
            return f"连续 {self.dup_in_row} 次重复请求"
        return None
