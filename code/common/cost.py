"""第 34 章产出：成本引擎（分项归因 + 预算控制 + 缓存 + 模型路由）。

第 57 章只做了"记账"。本章要做"经营"：
  1. 归因：钱花在哪个环节（plan / retrieve / tool / answer）
  2. 控制：单请求、单会话、单租户三级预算
  3. 优化：精确缓存 + 语义缓存 + 模型路由
  4. 报表：能对着业务方讲清楚"为什么这个月贵了 30%"
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from common.meter import CallRecord, price_of


# ============================================================ 分项归因

@dataclass
class CostBreakdown:
    """按"环节"归因的成本。

    为什么按环节而不是按模型？
    因为业务方问的是"聊天为什么比查询贵"，不是"为什么 qwen-plus 花得多"。
    """

    by_stage: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_stage_tokens: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    records: list[CallRecord] = field(default_factory=list)

    def add(self, rec: CallRecord) -> None:
        stage = rec.step or "unknown"
        self.by_stage[stage] += rec.cost
        self.by_stage_tokens[stage] += rec.input_tokens + rec.output_tokens
        self.records.append(rec)

    @property
    def total(self) -> float:
        return sum(self.by_stage.values())

    def top(self, n: int = 3) -> list[tuple[str, float, float]]:
        """返回 [(stage, cost, 占比)]，按成本降序。"""
        total = self.total or 1.0
        items = sorted(self.by_stage.items(), key=lambda x: -x[1])[:n]
        return [(k, v, v / total) for k, v in items]

    def report(self) -> str:
        lines = [f"{'环节':<16}{'成本(¥)':>12}{'占比':>8}{'token':>10}"]
        lines.append("-" * 48)
        for stage, cost, ratio in self.top(10):
            lines.append(f"{stage:<16}{cost:>12.6f}{ratio:>7.0%}{self.by_stage_tokens[stage]:>10,}")
        lines.append("-" * 48)
        lines.append(f"{'合计':<16}{self.total:>12.6f}{1.0:>7.0%}")
        return "\n".join(lines)


# ============================================================ 三级预算

@dataclass
class BudgetScope:
    """三级预算：请求 / 会话 / 租户。

    为什么要三级？
    单请求预算防"一次跑飞"；
    会话预算防"用户反复重试刷爆"；
    租户预算防"某个客户把整个系统吃满"。
    """

    name: str
    limit: float
    used: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


@dataclass
class BudgetManager:
    request: BudgetScope
    session: BudgetScope
    tenant: BudgetScope

    def check(self, cost: float) -> tuple[bool, str]:
        """检查是否还能再花 cost。返回 (是否允许, 拒绝原因)。"""
        for scope in (self.request, self.session, self.tenant):
            if scope.used + cost > scope.limit:
                return False, f"{scope.name} 预算不足（剩余 ¥{scope.remaining:.4f}，需要 ¥{cost:.4f}）"
        return True, ""

    def spend(self, cost: float) -> None:
        for scope in (self.request, self.session, self.tenant):
            scope.used += cost

    def snapshot(self) -> dict[str, Any]:
        return {
            s.name: {"limit": s.limit, "used": round(s.used, 6), "pct": round(s.used / s.limit, 3) if s.limit else 0}
            for s in (self.request, self.session, self.tenant)
        }


# ============================================================ 缓存

@dataclass
class ExactCache:
    """精确缓存：同样的输入 → 同样的输出。

    命中条件完全一致（prompt + model + 关键参数）。
    适合：固定 FAQ、模板化生成。
    """

    store: dict[str, str] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @staticmethod
    def key(prompt: str, model: str, extra: dict | None = None) -> str:
        raw = json.dumps({"p": prompt, "m": model, "x": extra or {}}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, prompt: str, model: str, extra: dict | None = None) -> str | None:
        k = self.key(prompt, model, extra)
        if k in self.store:
            self.hits += 1
            return self.store[k]
        self.misses += 1
        return None

    def put(self, prompt: str, model: str, value: str, extra: dict | None = None) -> None:
        self.store[self.key(prompt, model, extra)] = value

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


@dataclass
class SemanticCache:
    """语义缓存：相似的问题 → 复用答案。

    ⚠️ 这是**有风险**的优化，必须配合阈值和场景限制：
      · 阈值太低 → 把不同问题的答案混用（事故）
      · 只适合"答案稳定"的场景（政策、FAQ）
      · 不适合"实时数据"（库存、余额）

    用简化版"字符 bigram 余弦"代替真实 embedding，保证离线可跑。
    """

    threshold: float = 0.92
    entries: list[tuple[list[str], str, str]] = field(default_factory=list)  # (bigrams, answer, question)
    hits: int = 0
    misses: int = 0

    @staticmethod
    def _bigrams(text: str) -> list[str]:
        t = "".join(ch for ch in text if ch.isalnum())
        return [t[i : i + 2] for i in range(len(t) - 1)] or [t]

    def _sim(self, a: list[str], b: list[str]) -> float:
        from collections import Counter

        ca, cb = Counter(a), Counter(b)
        common = sum((ca & cb).values())
        denom = math.sqrt(sum(ca.values()) * sum(cb.values()))
        return common / denom if denom else 0.0

    def get(self, question: str) -> tuple[str, float] | None:
        q = self._bigrams(question)
        best, best_score = None, 0.0
        for grams, answer, _ in self.entries:
            s = self._sim(q, grams)
            if s > best_score:
                best, best_score = answer, s
        if best is not None and best_score >= self.threshold:
            self.hits += 1
            return best, best_score
        self.misses += 1
        return None

    def put(self, question: str, answer: str) -> None:
        self.entries.append((self._bigrams(question), answer, question))


# ============================================================ 模型路由

@dataclass
class ModelRouter:
    """按任务难度选模型。

    三档：
      cheap    → 分类、抽取、改写（简单但量大）
      default  → 一般问答
      strong   → 复杂推理、代码生成

    关键：**路由规则必须显式**，不能"让模型自己选模型"。
    """

    cheap: str = "deepseek-chat"
    default: str = "deepseek-chat"
    strong: str = "deepseek-reasoner"

    # 规则表：命中即用对应档位
    rules: list[tuple[str, str, str]] = field(
        default_factory=lambda: [
            ("intent", "cheap", "意图分类，简单但有量"),
            ("extract", "cheap", "结构化抽取"),
            ("rewrite", "cheap", "查询改写"),
            ("answer", "default", "常规问答"),
            ("plan", "default", "计划生成"),
            ("code", "strong", "代码生成/审查"),
            ("reason", "strong", "多步推理"),
        ]
    )

    def pick(self, stage: str) -> tuple[str, str]:
        for key, tier, why in self.rules:
            if key in stage:
                model = {"cheap": self.cheap, "default": self.default, "strong": self.strong}[tier]
                return model, f"{tier}（{why}）"
        return self.default, "default（未命中规则）"

    def compare_cost(self, stage: str, tokens_in: int, tokens_out: int) -> dict[str, float]:
        """对比"用 strong"和"用路由选择"的成本。"""
        chosen, _ = self.pick(stage)
        def cost_of(model: str) -> float:
            pin, pout = price_of(model)
            return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout
        return {
            "all_strong": cost_of(self.strong),
            "routed": cost_of(chosen),
            "saved": cost_of(self.strong) - cost_of(chosen),
        }
