"""第 57 章产出：Harness 成熟度自评 + 能力矩阵 + 一键体检。

Harness = Agent 之外的"运行支撑层"：
  Agent 负责"想"，Harness 负责"边界、仪表、黑匣子、刹车"。

本文件的三个作用：
  1. HarnessMatrix —— 六大能力域 × 章节回扣（书末总结表）
  2. MaturityAssessment —— L1~L5 成熟度自评（可打分）
  3. health_check() —— 检查一个项目的实际能力落地情况
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================ 六大能力域

@dataclass
class Capability:
    """一个 Harness 能力项。"""

    key: str
    domain: str
    name: str
    chapters: list[int]
    why: str                        # 不做会怎样
    probe: str                      # 怎么验证它存在（可执行的一句话）


DOMAINS = {
    "boundary": "执行边界",
    "observability": "可观测",
    "reliability": "可靠性",
    "budget": "预算控制",
    "quality": "质量门",
    "knowledge": "知识治理",
}

CAPABILITIES: list[Capability] = [
    # ---- 执行边界 ----
    Capability("perm", "boundary", "工具权限分级（只读/写/禁止）", [31],
               "模型会执行不该执行的动作（删数据、发邮件）",
               "尝试调一个未登记的工具，应被拒绝"),
    Capability("sandbox", "boundary", "沙箱隔离（路径/网络/资源）", [33],
               "Agent 能读到私钥、访问云元数据接口",
               "尝试读 ../ 路径、访问 169.254.169.254，应被拒绝"),
    Capability("hitl", "boundary", "高危动作人工确认", [32],
               "退款/发邮件这类不可逆动作被自动执行",
               "触发一次退款，应产生 pending 审批卡片"),
    Capability("injection", "boundary", "提示注入防护（含间接注入）", [31],
               "知识库被投毒后，Agent 执行注入指令",
               "构造一条含'忽略指令'的文档，应被拦截"),

    # ---- 可观测 ----
    Capability("trace", "observability", "分层 trace（run/step/call）", [38],
               "出错时不知道错在哪一步",
               "拿一个错误 run_id 能还原完整调用树"),
    Capability("meter", "observability", "token/成本/延迟计量", [37],
               "账单涨了 3 倍，查不出原因",
               "任意一次调用都能查到 input/output token 与成本"),
    Capability("audit", "observability", "动作审计日志", [32],
               "出事后无法追溯'它到底动过什么'",
               "每个工具调用都有 user_id/时间/参数记录"),

    # ---- 可靠性 ----
    Capability("budget_brake", "reliability", "循环终止与预算刹车", [16],
               "Agent 无限循环，一夜烧掉几百块",
               "去掉终止条件后，系统应在 N 步内自行停止"),
    Capability("retry", "reliability", "分级重试（瞬时/局部/全局）", [21],
               "一个工具超时导致整个任务失败",
               "模拟 503，应在 2 次内恢复"),
    Capability("durable", "reliability", "检查点与断点续跑", [22],
               "服务重启后长任务丢失",
               "跑一半 kill 进程，重启后能从断点继续且不重复执行副作用"),
    Capability("idempotent", "reliability", "副作用幂等", [22, 32],
               "恢复后重复退款、重复发邮件",
               "同一请求 resume 两次，副作用只发生一次"),

    # ---- 预算 ----
    Capability("cost_attribution", "budget", "成本分项归因", [34],
               "只知道总账单，不知道哪个环节贵",
               "能输出按 stage 的成本占比表"),
    Capability("three_level_budget", "budget", "三级预算（请求/会话/租户）", [34],
               "单个用户能把全系统配额吃满",
               "构造超限请求，应被对应层级拦截"),
    Capability("cache", "budget", "缓存（精确+语义）", [34],
               "重复问题重复付费",
               "同一问题问 5 次，应只有 1 次真实调用"),

    # ---- 质量门 ----
    Capability("eval_set", "quality", "冻结评测集（含历史故障）", [41],
               "改了之后不知道变好还是变坏",
               "能一键跑出 pass_rate 并对比基线"),
    Capability("trajectory_eval", "quality", "轨迹评估（步数/重复/超预算）", [41],
               "答案对但路径蠢，成本悄悄翻倍",
               "能识别出'重复调用 3 次'的 run"),
    Capability("stability", "quality", "稳定性检测（flaky）", [41],
               "同一问题时对时错，用户觉得不可靠",
               "同题跑 5 次，能识别出 pass_rate 在 0~1 之间"),
    Capability("ci_gate", "quality", "CI 门禁（质量/成本/延迟）", [41],
               "退化代码悄悄上线",
               "故意降质量，CI 应拦住"),

    # ---- 知识治理 ----
    Capability("context_budget", "knowledge", "上下文预算与压缩", [24, 26],
               "历史挤掉检索结果，答案跑偏",
               "能输出四槽位的使用率"),
    Capability("memory_layers", "knowledge", "记忆分层（槽位/工作/长期）", [26, 27],
               "用户 20 轮前说的事实被遗忘",
               "20 轮后仍能答对'我叫什么'"),
    Capability("wiki", "knowledge", "结构化知识层（含例外与来源）", [29, 30],
               "只能给片段，给不出'到底是什么'",
               "每个条目都有 definition/key_points/exceptions/sources"),
    Capability("conflict", "knowledge", "知识冲突检测", [30],
               "新旧政策并存，模型随机挑一个",
               "7 天改 15 天时，应触发人工审核"),
]


# ============================================================ 成熟度

LEVELS = {
    1: ("能用", "能跑通一个 demo，但没有任何护栏与观测"),
    2: ("可观测", "有 trace 和计量，出错能定位，但还不能自愈"),
    3: ("受控", "有护栏、预算、HITL，异常不会造成事故"),
    4: ("可回归", "有评测集和 CI 门禁，改动不会悄悄退化"),
    5: ("可运营", "成本/延迟/质量都有 SLO 与看板，故障可复盘可闭环"),
}

LEVEL_REQUIRES = {
    1: ["trace"],                                        # 先能看见
    2: ["trace", "meter", "audit"],
    3: ["perm", "sandbox", "hitl", "budget_brake", "retry", "durable"],
    4: ["eval_set", "trajectory_eval", "stability", "ci_gate", "idempotent"],
    5: ["cost_attribution", "three_level_budget", "wiki", "conflict", "injection"],
}


@dataclass
class MaturityAssessment:
    """成熟度自评。

    `have` 是已具备的能力 key 集合。
    等级不是"平均分"，而是**必须全部满足**——这是有意的：
    缺一个就会在那个维度上出事，不能用其他维度的高分抵消。
    """

    have: set[str] = field(default_factory=set)

    def level(self) -> int:
        lvl = 0
        for lv in sorted(LEVEL_REQUIRES):
            if all(k in self.have for k in LEVEL_REQUIRES[lv]):
                lvl = lv
            else:
                break
        return lvl

    def next_level_gaps(self) -> list[Capability]:
        lv = self.level() + 1
        if lv not in LEVEL_REQUIRES:
            return []
        return [c for c in CAPABILITIES if c.key in LEVEL_REQUIRES[lv] and c.key not in self.have]

    def by_domain(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for dom in DOMAINS:
            caps = [c for c in CAPABILITIES if c.domain == dom]
            out[dom] = (sum(1 for c in caps if c.key in self.have), len(caps))
        return out

    def report(self) -> str:
        lv = self.level()
        lines = [f"当前成熟度：L{lv}（{LEVELS[lv][0]}）" if lv in LEVELS else "当前成熟度：<L1", ""]
        if lv in LEVELS:
            lines.append(f"定义：{LEVELS[lv][1]}")
        lines += ["", "## 六大能力域", ""]
        lines.append(f"{'能力域':<12}{'已具备':>6}{'总数':>6}   进度")
        lines.append("-" * 44)
        for dom, (got, total) in self.by_domain().items():
            bar = "█" * got + "░" * (total - got)
            lines.append(f"{DOMAINS[dom]:<12}{got:>6}{total:>6}   {bar}")

        gaps = self.next_level_gaps()
        if gaps:
            lines += ["", f"## 通往 L{lv + 1}（{LEVELS[lv + 1][0]}）还缺", ""]
            for c in gaps:
                lines.append(f"- **{c.name}**（第 {','.join(map(str, c.chapters))} 章）")
                lines.append(f"  - 不做会：{c.why}")
                lines.append(f"  - 验证：{c.probe}")
        else:
            lines += ["", "## 已到最高等级 🎉"]
        return "\n".join(lines)


# ============================================================ 反模式检查

ANTIPATTERNS = [
    ("只有 trace 没有评测", ["trace"], ["eval_set"], "你能看见问题，但无法判断改动是否更好"),
    ("只有护栏没有回滚", ["hitl"], ["durable"], "拦不住的问题会让系统停在半路"),
    ("只有多 Agent 没有预算分摊", ["multi_agent"], ["three_level_budget"], "一个子 Agent 能吃掉全部配额"),
    ("只有缓存没有评测", ["cache"], ["eval_set"], "缓存命中错误答案，你无法察觉"),
    ("只有记忆没有隔离", ["memory_layers"], ["perm"], "跨租户记忆串号，数据泄露"),
    ("有预算但没归因", ["budget_brake"], ["cost_attribution"], "省了钱但不知道省在哪，无法持续优化"),
]


def check_antipatterns(have: set[str]) -> list[str]:
    out = []
    for name, needs, requires, consequence in ANTIPATTERNS:
        if any(k in have for k in needs) and not any(k in have for k in requires):
            out.append(f"⚠️ {name}：{consequence}")
    return out


# ============================================================ 项目体检

_CACHE: dict[str, str] = {}


def _has_text(root: Path, needle: str) -> bool:
    """在项目的 .py 文件里找关键词（排除虚拟环境与缓存）。"""
    key = str(root)
    if key not in _CACHE:
        buf = []
        for p in root.rglob("*.py"):
            parts = set(p.parts)
            if ".venv" in parts or "__pycache__" in parts:
                continue
            try:
                buf.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
        _CACHE[key] = "\n".join(buf)
    return needle.lower() in _CACHE[key].lower()


def health_check(project_root: Path | str) -> dict[str, Any]:
    """检查一个真实项目里，Harness 能力落地了多少。

    这是"可执行"的自检——不是打分表，而是真的去项目里找证据。
    """
    root = Path(project_root)
    found: dict[str, bool] = {}

    def exists(*patterns: str) -> bool:
        for p in patterns:
            if list(root.rglob(p)):
                return True
        return False

    found["trace"] = exists("*trace*.py", "*span*.py")
    found["meter"] = exists("*meter*.py", "*usage*.py")
    found["eval_set"] = exists("evals/*.json", "*_eval*.py")
    found["ci_gate"] = exists(".github/workflows/*.yml") and exists("*test*.py")
    found["sandbox"] = exists("*sandbox*.py", "Dockerfile")
    found["hitl"] = exists("*hitl*.py", "*approval*.py")
    found["durable"] = exists("*checkpoint*", "*durable*.py")
    found["cache"] = exists("*cache*.py")
    found["wiki"] = exists("*wiki*.py")
    found["guardrails"] = exists("*guardrail*.py", "*policy*.py")

    # 补充检查：有些能力散落在别的文件里，不能只靠文件名
    found["audit"] = exists("*audit*.py") or _has_text(root, "AuditLog")
    found["trajectory_eval"] = _has_text(root, "score_trajectory")
    found["stability"] = _has_text(root, "def stability")
    found["perm"] = _has_text(root, "ToolPolicy")
    found["injection"] = _has_text(root, "INJECTION_PATTERNS")
    found["budget_brake"] = _has_text(root, "max_steps")
    found["retry"] = _has_text(root, "retry") or _has_text(root, "attempts")
    found["idempotent"] = _has_text(root, "idempot") or _has_text(root, "幂等")
    found["cost_attribution"] = _has_text(root, "CostBreakdown")
    found["three_level_budget"] = _has_text(root, "BudgetManager")
    found["context_budget"] = _has_text(root, "ContextBudget")
    found["memory_layers"] = _has_text(root, "ShortTermMemory") or _has_text(root, "MemoryKind")
    found["conflict"] = _has_text(root, "def conflict")

    have = {k for k, v in found.items() if v}
    a = MaturityAssessment(have=have)

    return {
        "root": str(root),
        "found": found,
        "level": a.level(),
        "level_name": LEVELS.get(a.level(), ("<L1", ""))[0],
        "antipatterns": check_antipatterns(have),
        "gaps": [c.key for c in a.next_level_gaps()],
    }


# ============================================================ 章节回扣表

def chapter_map_markdown() -> str:
    lines = ["| 能力域 | 能力项 | 章节 | 不做会怎样 |", "|---|---|---|---|"]
    for dom, label in DOMAINS.items():
        for c in CAPABILITIES:
            if c.domain == dom:
                lines.append(f"| {label} | {c.name} | {','.join(map(str, c.chapters))} | {c.why} |")
    return "\n".join(lines)
