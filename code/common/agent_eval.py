"""第 26 章产出：Agent 评测体系（结果评估 + 轨迹评估）。

和第 15 章的 RAG 评测的区别：
  第 15 章评的是"检索+生成"（单步）
  本章评的是"Agent 的整个执行过程"（多步、有工具、有路径）

四个层次：
  L1 结果：答案对不对
  L2 轨迹：路径对不对（步数、重复调用、绕远路）
  L3 稳定性：同一输入跑 N 次，结果一致吗
  L4 成本：完成一个任务花多少
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


# ============================================================ 数据结构

@dataclass
class TraceStep:
    """轨迹中的一步（对应第 2 章的 step span）。"""

    idx: int
    kind: str                       # plan | tool | model | answer
    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    cost: float = 0.0
    tokens: int = 0
    error: str | None = None


@dataclass
class AgentRun:
    """一次 Agent 运行的完整记录。"""

    case_id: str
    question: str
    answer: str
    steps: list[TraceStep] = field(default_factory=list)
    cost: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def tool_calls(self) -> list[TraceStep]:
        return [s for s in self.steps if s.kind == "tool"]

    @property
    def n_steps(self) -> int:
        return len(self.steps)


@dataclass
class AgentCase:
    id: str
    question: str
    # 结果层：答案里必须包含的要素
    must_contain: list[str] = field(default_factory=list)
    # 轨迹层：期望的工具（可选）
    expected_tools: list[str] = field(default_factory=list)
    # 轨迹层：最多允许多少步（超过 = 绕远路）
    max_steps: int = 12
    # 是否允许拒答
    allow_refusal: bool = False
    tags: list[str] = field(default_factory=list)


# ============================================================ L1 结果评估

def score_result(run: AgentRun, case: AgentCase) -> dict[str, Any]:
    """结果层：只看最终答案对不对。"""
    ans = run.answer or ""
    missing = [k for k in case.must_contain if k not in ans]
    correct = len(case.must_contain) - len(missing) if case.must_contain else (1 if ans else 0)
    total = len(case.must_contain) or 1
    refused = ("未提及" in ans) or ("不知道" in ans) or ("无法回答" in ans)

    return {
        "passed": not missing and not run.error,
        "score": correct / total,
        "missing": missing,
        "refused": refused,
        "refusal_ok": (not refused) or case.allow_refusal,
        "error": run.error,
    }


# ============================================================ L2 轨迹评估

def score_trajectory(run: AgentRun, case: AgentCase) -> dict[str, Any]:
    """轨迹层：只看路径对不对。

    这是 Agent 评测和普通 RAG 评测最大的区别。
    "答案对但路径蠢" 在生产里会变成成本和延迟问题。
    """
    used = [s.name for s in run.tool_calls]

    # 1. 必需工具是否用到
    missing_tools = [t for t in case.expected_tools if t not in used]

    # 2. 是否有重复调用（相同工具+相同参数）
    fps = [json.dumps({"t": s.name, "a": s.args}, sort_keys=True, ensure_ascii=False) for s in run.tool_calls]
    dup = len(fps) - len(set(fps))

    # 3. 步数是否超出预算
    over_budget = max(0, run.n_steps - case.max_steps)

    # 4. 是否有失败的工具调用
    tool_errors = [s for s in run.tool_calls if s.error]

    return {
        "missing_tools": missing_tools,
        "duplicate_calls": dup,
        "steps": run.n_steps,
        "over_budget": over_budget,
        "tool_errors": len(tool_errors),
        "clean": not missing_tools and dup == 0 and over_budget == 0 and not tool_errors,
    }


# ============================================================ L3 稳定性

def stability(runs: Sequence[AgentRun], case: AgentCase) -> dict[str, Any]:
    """同一输入跑 N 次，结果一致吗？

    为什么重要：Agent 是概率系统。如果同一问题今天对明天错，
    用户就会觉得"不可靠"——而这无法从单次评测里看出来。
    """
    if not runs:
        return {"n": 0}
    scores = [score_result(r, case)["passed"] for r in runs]
    answers = [r.answer for r in runs]

    pass_rate = sum(scores) / len(scores)
    # 答案完全一致的比例（粗粒度一致性）
    uniq = len(set(answers))
    consistent = uniq == 1

    return {
        "n": len(runs),
        "pass_rate": pass_rate,
        # 稳定性 = 1 - 结果的标准差（用伯努利近似）
        "stability": 1 - 2 * abs(pass_rate - 0.5) if 0 < pass_rate < 1 else 1.0,
        "unique_answers": uniq,
        "consistent": consistent,
        "flaky": 0 < pass_rate < 1,
    }


# ============================================================ L4 成本与延迟

def cost_latency(runs: Sequence[AgentRun]) -> dict[str, float]:
    if not runs:
        return {}
    costs = [r.cost for r in runs]
    lat = [r.latency_ms for r in runs]

    def p(vals: list[float], q: float) -> float:
        s = sorted(vals)
        return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]

    return {
        "avg_cost": sum(costs) / len(costs),
        "p95_cost": p(costs, 0.95),
        "avg_latency_ms": sum(lat) / len(lat),
        "p95_latency_ms": p(lat, 0.95),
        "total_cost": sum(costs),
    }


# ============================================================ 报表

@dataclass
class AgentReport:
    results: list[tuple[AgentCase, AgentRun, dict, dict]]  # case, run, result_score, traj_score

    def summary(self) -> dict[str, Any]:
        n = len(self.results)
        if not n:
            return {}
        return {
            "n": n,
            "pass_rate": sum(1 for _, _, r, _ in self.results if r["passed"]) / n,
            "trajectory_clean_rate": sum(1 for _, _, _, t in self.results if t["clean"]) / n,
            "avg_steps": sum(t["steps"] for _, _, _, t in self.results) / n,
            "duplicate_calls": sum(t["duplicate_calls"] for _, _, _, t in self.results),
            "over_budget_cases": sum(1 for _, _, _, t in self.results if t["over_budget"] > 0),
            "avg_cost": sum(r.cost for _, r, _, _ in self.results) / n,
            "p95_latency_ms": cost_latency([r for _, r, _, _ in self.results])["p95_latency_ms"],
        }

    def failures(self) -> list[tuple[AgentCase, AgentRun, dict, dict]]:
        """失败清单——永远比总分更有用。"""
        return [x for x in self.results if not x[2]["passed"] or not x[3]["clean"]]

    def diff(self, other: "AgentReport") -> dict[str, tuple[float, float, float]]:
        a, b = self.summary(), other.summary()
        out = {}
        for k in a:
            if k == "n" or k not in b:
                continue
            out[k] = (a[k], b[k], b[k] - a[k])
        return out


def print_diff(baseline: AgentReport, current: AgentReport) -> str:
    """打印 A/B 对比，并自动标注"好"还是"坏"。

    ⚠️ 方向很重要：pass_rate 上升是好事，cost 上升是坏事。
       不加方向标注，人很容易看反（这是我第一次做报表时的真实体验）。
    """
    higher_better = {"pass_rate", "trajectory_clean_rate"}
    lower_better = {"avg_steps", "duplicate_calls", "over_budget_cases", "avg_cost", "p95_latency_ms"}

    lines = [f"{'指标':<24}{'基线':>10}{'当前':>10}{'变化':>10}  评价"]
    lines.append("-" * 68)
    for k, (a, b, d) in baseline.diff(current).items():
        if k in higher_better:
            verdict = "✅ 变好" if d > 0.005 else ("❌ 变差" if d < -0.005 else "＝")
        elif k in lower_better:
            verdict = "✅ 变好" if d < -0.005 else ("❌ 变差" if d > 0.005 else "＝")
        else:
            verdict = "＝"
        lines.append(f"{k:<24}{a:>10.3f}{b:>10.3f}{d:>+10.3f}  {verdict}")
    return "\n".join(lines)


# ============================================================ 一次只改一个变量

@dataclass
class Experiment:
    """A/B 实验：只允许改一个变量。

    为什么必须在代码层面强制？
    因为人太容易"顺手优化一下"——然后你就不知道是哪个起作用了。
    """

    name: str
    variable: str
    baseline_config: dict[str, Any]
    variant_config: dict[str, Any]

    def validate(self) -> tuple[bool, str]:
        diff = {
            k
            for k in set(self.baseline_config) | set(self.variant_config)
            if self.baseline_config.get(k) != self.variant_config.get(k)
        }
        if len(diff) == 0:
            return False, "两个配置完全相同，测不出差异"
        if len(diff) > 1:
            return False, f"改了 {len(diff)} 个变量 {sorted(diff)}，违反'一次只改一个'"
        only = next(iter(diff))
        if only != self.variable:
            return False, f"改动的是 {only}，但声明的变量是 {self.variable}"
        return True, "ok"


# ============================================================ 报告导出

def export_markdown(path: Path | str, report: AgentReport, title: str = "Agent 评测报告") -> None:
    s = report.summary()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# {title}", "", "## 总览", ""]
    for k, v in s.items():
        lines.append(f"- **{k}**：{v:.4f}" if isinstance(v, float) else f"- **{k}**：{v}")

    lines += ["", "## 失败清单", ""]
    fails = report.failures()
    if not fails:
        lines.append("（无）")
    for case, run, rs, ts in fails:
        lines.append(f"### {case.id}: {case.question}")
        lines.append(f"- 缺要素：{rs['missing']}")
        lines.append(f"- 缺工具：{ts['missing_tools']}")
        lines.append(f"- 步数：{ts['steps']}（预算 {case.max_steps}）")
        lines.append(f"- 重复调用：{ts['duplicate_calls']}")
        lines.append("")

    p.write_text("\n".join(lines), encoding="utf-8")
