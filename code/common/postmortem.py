"""第 27 章产出：故障复盘的结构化模板与自动分类。

复盘的目标不是"找到谁错了"，而是**把一次故障变成一条永久性的防线**。

五问法（必须在 30 分钟内回答）：
  1. 变差多少？（量化）
  2. 哪一步？（定位）
  3. 为什么？（根因）
  4. 怎么修？（修复）
  5. 怎么证明修好了？（回归）

Failure taxonomy（分类决定修复方向）：
  检索错 / 工具错 / 规划错 / 上下文错 / 模型错 / 护栏误杀 / 基础设施错
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FailureType(str, Enum):
    RETRIEVAL = "retrieval"        # 检索没找到 / 找到错的
    TOOL = "tool"                  # 工具报错 / 参数错误
    PLANNING = "planning"          # 计划错了 / 没重规划
    CONTEXT = "context"            # 上下文超限 / 被挤出
    MODEL = "model"                # 模型本身能力不足 / 幻觉
    GUARDRAIL = "guardrail"        # 被护栏误杀
    INFRA = "infra"                # 超时 / 限流 / 网络
    UNKNOWN = "unknown"

    @property
    def fix_direction(self) -> str:
        return {
            FailureType.RETRIEVAL: "查第 11/12/14 章：分块、混合检索、重排、图扩展",
            FailureType.TOOL: "查第 3/18/20 章：重试策略、参数校验、沙箱边界",
            FailureType.PLANNING: "查第 6/8 章：计划结构、重规划触发条件",
            FailureType.CONTEXT: "查第 10/16 章：预算分配、压缩策略、槽位",
            FailureType.MODEL: "查第 7 章：加裁判；或第 21 章：换模型/路由",
            FailureType.GUARDRAIL: "查第 18 章：规则过宽；加白名单；看误杀率",
            FailureType.INFRA: "查第 3/22 章：超时、降级链、并发上限",
            FailureType.UNKNOWN: "信息不足，先补 trace（第 2 章）",
        }[self]


@dataclass
class Conclusion:
    answer: str = ""
    score: float = 0.0            # 0~1，判定分数
    note: str = ""


@dataclass
class Evidence:
    """证据：没有证据的根因都是猜测。"""

    kind: str                    # trace | log | metric | reproduction
    ref: str                     # run_id / 文件路径 / 指标名
    excerpt: str = ""


@dataclass
class FiveQuestions:
    """五问法：30 分钟内必须能回答。

    任何一问答不上来，说明你的可观测性还不够（第 2 章）。
    """

    q1_how_much_worse: str = ""      # 变差多少（必须带数字）
    q2_which_step: str = ""          # 哪一步（必须指向具体 span / step）
    q3_root_cause: str = ""          # 为什么（必须带证据）
    q4_fix: str = ""                 # 怎么修
    q5_regression: str = ""          # 怎么证明修好了

    def completeness(self) -> float:
        filled = sum(1 for v in asdict(self).values() if str(v).strip())
        return filled / 5

    def missing(self) -> list[str]:
        names = ["变差多少", "哪一步", "为什么", "怎么修", "怎么证明"]
        vals = list(asdict(self).values())
        return [n for n, v in zip(names, vals) if not str(v).strip()]


@dataclass
class Postmortem:
    title: str
    occurred_at: str
    detected_at: str
    resolved_at: str
    severity: str = "P2"                 # P0~P3
    impact: str = ""                     # 影响面（用户数/金额/时长）
    failure_type: FailureType = FailureType.UNKNOWN
    five: FiveQuestions = field(default_factory=FiveQuestions)
    evidence: list[Evidence] = field(default_factory=list)
    action_items: list[dict[str, str]] = field(default_factory=list)  # {action, owner, due, status}
    new_eval_cases: list[str] = field(default_factory=list)           # ← 最重要

    # ---------- 自动检查 ----------

    def checks(self) -> dict[str, Any]:
        """自动体检：一份不合格的复盘长什么样。"""
        problems = []
        if self.five.completeness() < 1.0:
            problems.append(f"五问不完整，缺：{self.five.missing()}")
        if not any(e.kind == "trace" for e in self.evidence):
            problems.append("缺少 trace 证据（第 2 章的 run_id）")
        if not self.action_items:
            problems.append("没有行动项")
        elif not any(a.get("owner") and a.get("due") for a in self.action_items):
            problems.append("行动项缺少 owner 或 deadline")
        if not self.new_eval_cases:
            problems.append("没有把故障变成评测用例（第 26 章）")
        if self.failure_type is FailureType.UNKNOWN:
            problems.append("失败类型未分类，无法确定修复方向")

        mttr_min = _minutes(self.detected_at, self.resolved_at)
        mttd_min = _minutes(self.occurred_at, self.detected_at)

        return {
            "ok": not problems,
            "problems": problems,
            "mttd_min": mttd_min,          # mean time to detect
            "mttr_min": mttr_min,          # mean time to resolve
        }

    def to_markdown(self) -> str:
        c = self.checks()
        lines = [
            f"# 复盘：{self.title}",
            "",
            f"- 发生：{self.occurred_at}",
            f"- 发现：{self.detected_at}",
            f"- 恢复：{self.resolved_at}",
            f"- 级别：{self.severity}",
            f"- 影响：{self.impact}",
            f"- 分类：**{self.failure_type.value}** → {self.failure_type.fix_direction}",
            "",
            f"## 时间线（MTTD {c['mttd_min']} 分钟 / MTTR {c['mttr_min']} 分钟）",
            "",
            "## 五问法",
            "",
            f"1. **变差多少**：{self.five.q1_how_much_worse}",
            f"2. **哪一步**：{self.five.q2_which_step}",
            f"3. **为什么**：{self.five.q3_root_cause}",
            f"4. **怎么修**：{self.five.q4_fix}",
            f"5. **怎么证明**：{self.five.q5_regression}",
            "",
            "## 证据",
        ]
        for e in self.evidence:
            lines.append(f"- [{e.kind}] `{e.ref}` {e.excerpt}")
        lines += ["", "## 行动项", "", "| 动作 | 负责人 | 期限 | 状态 |", "|---|---|---|---|"]
        for a in self.action_items:
            lines.append(f"| {a.get('action', '')} | {a.get('owner', '')} | {a.get('due', '')} | {a.get('status', 'todo')} |")
        lines += ["", "## 新增评测用例", ""]
        lines += [f"- {c}" for c in self.new_eval_cases] or ["（无）"]
        if not c["ok"]:
            lines += ["", "## ⚠️ 复盘体检未通过", ""] + [f"- {p}" for p in c["problems"]]
        return "\n".join(lines)


def _minutes(a: str, b: str) -> int:
    """'2026-10-12 14:03' 格式的时间差（分钟）。解析失败返回 -1。"""
    from datetime import datetime

    try:
        fmt = "%Y-%m-%d %H:%M"
        return int((datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds() // 60)
    except Exception:  # noqa: BLE001
        return -1


# ============================================================ 分类器

SYMPTOMS: dict[FailureType, list[str]] = {
    FailureType.RETRIEVAL: ["未检索到", "召回为空", "答非所问", "资料里没有", "检索结果不相关"],
    FailureType.TOOL: ["TOOL_ERROR", "工具报错", "参数错误", "503", "timeout", "未知动作"],
    FailureType.PLANNING: ["计划卡住", "没有重规划", "步骤不完整", "顺序错"],
    FailureType.CONTEXT: ["token 超限", "上下文截断", "忘记之前的", "被挤出"],
    FailureType.MODEL: ["幻觉", "编造", "答错但很自信", "格式不对"],
    FailureType.GUARDRAIL: ["被拦截", "误杀", "BLOCKED", "need_human"],
    FailureType.INFRA: ["429", "限流", "连接失败", "超时"],
}


def classify(symptom_text: str) -> tuple[FailureType, float]:
    """按症状文本猜失败类型。

    真实系统里这应该是**人工分类**（因为分类决定修复方向，错了会白干）。
    自动分类的价值是"给出候选"，加速人工判断。
    """
    scores: dict[FailureType, int] = {}
    low = symptom_text.lower()
    for ft, keys in SYMPTOMS.items():
        n = sum(1 for k in keys if k.lower() in low)
        if n:
            scores[ft] = n
    if not scores:
        return FailureType.UNKNOWN, 0.0
    best = max(scores.items(), key=lambda x: x[1])
    total = sum(scores.values())
    return best[0], best[1] / total


# ============================================================ 评测用例生成

def to_eval_case(pm: Postmortem) -> dict[str, Any]:
    """把故障转成评测用例。

    这是复盘**最重要的一步**：
    没有这一步，同一个故障会在三个月后以另一种形式再来一次。
    """
    return {
        "id": f"pm-{pm.occurred_at.replace('-', '').replace(':', '').replace(' ', '')}",
        "question": pm.new_eval_cases[0] if pm.new_eval_cases else pm.title,
        "must_contain": [],
        "tags": ["regression", pm.failure_type.value, pm.severity],
        "source": "postmortem",
        "expected": pm.five.q4_fix,
    }
