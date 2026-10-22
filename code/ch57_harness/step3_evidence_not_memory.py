"""第 57 章 step3：自评会骗自己——去代码里找证据（离线）。

运行：
    python code/ch57_harness/step3_evidence_not_memory.py

上一级的痛点：等级是"我说我有"，但"我记得我加过"不算证据。

这一级做什么：
  ① 对本书代码库跑一次真体检，看每一项能力是从哪段代码里找到的
  ② 演示"改名一个文件，等级就掉一级"（能力必须是可执行的证据）
  ③ 说明什么是"弱证据"：文件名像，但里面没有实现

⚠️ 本脚本用临时目录构造 mini 项目，不会动你自己的文件。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.harness import health_check  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# 每项能力在本书里的"证据位置"，由人工核对过一次
EVIDENCE_MAP = {
    "trace": "code/common/trace.py",
    "meter": "code/common/meter.py",
    "audit": "code/common/hitl.py（AuditLog）",
    "perm": "code/common/guardrails.py（ToolPolicy）",
    "sandbox": "code/common/sandbox.py",
    "hitl": "code/common/hitl.py",
    "injection": "code/common/guardrails.py（INJECTION_PATTERNS）",
    "budget_brake": "code/common/react.py（max_steps）",
    "retry": "code/common/reliability.py（重试）",
    "durable": "code/common/durable.py / checkpoints",
    "idempotent": "code/common/durable.py（幂等键）",
    "cost_attribution": "code/common/cost.py（CostBreakdown）",
    "three_level_budget": "code/common/cost.py（BudgetManager）",
    "cache": "code/common/cache.py",
    "eval_set": "evals/ + code/ch38_eval/",
    "trajectory_eval": "code/common/agent_eval.py（score_trajectory）",
    "stability": "code/common/agent_eval.py（stability）",
    "ci_gate": ".github/workflows/ci.yml + tests/",
    "context_budget": "code/common/context.py（ContextBudget）",
    "memory_layers": "code/common/short_memory.py / long_memory.py",
    "wiki": "code/common/wiki.py",
    "conflict": "code/common/wiki.py（conflict）",
}


def mini_project() -> Path:
    """造一个"看起来有 trace、其实只是个空文件"的项目。"""
    d = Path(tempfile.mkdtemp(prefix="harness-mini-"))
    (d / "trace.py").write_text("# TODO: 还没写\n", encoding="utf-8")
    (d / "meter.py").write_text("def usage_of(resp):\n    return {}\n", encoding="utf-8")
    return d


def main() -> None:
    print("=" * 82)
    print("① 本书代码库的体检：每一项能力的证据在哪")
    print("=" * 82)
    hc = health_check(ROOT)
    found = hc["found"]
    print(f"{'能力':<22}{'落地':<6}证据位置")
    print("-" * 82)
    for key, where in EVIDENCE_MAP.items():
        mark = "✅" if found.get(key) else "❌"
        print(f"{key:<22}{mark:<6}{where}")
    print("-" * 82)
    print(f"成熟度：L{hc['level']}（{hc['level_name']}）；缺：{hc['gaps'] or '无'}")

    print("\n  注意：这张表是**人工核对过一遍**的。")
    print("  体检脚本只能告诉你'找到了'，不能告诉你'它是对的'——")
    print("  所以最后一步永远是：打开那个文件，看一眼它真的在做这件事。")

    print("\n" + "=" * 82)
    print("② 弱证据：文件名像，但里面没实现")
    print("=" * 82)
    d = mini_project()
    mini = health_check(d)
    print("  一个只有 trace.py（内容是 TODO）和 meter.py 的项目：")
    print(f"    trace   → {'✅ 认为有' if mini['found']['trace'] else '❌ 认为没有'}"
          f"   ← 空文件也算（文件名匹配）")
    print(f"    meter   → {'✅ 认为有' if mini['found']['meter'] else '❌ 认为没有'}"
          f"   ← 只有 usage_of，也算")
    print(f"    等级     → L{mini['level']}")
    d2 = Path(tempfile.mkdtemp(prefix="harness-empty-"))
    print(f"  一个空目录：等级 L{health_check(d2)['level']}（连 L1 都没有）")
    print("    → 所以'有没有'这件事，脚本只能在**文件名/关键词**这一层判断。")
    print("      真正可信的证据是 **probe**（每项能力那条'怎么验'）。")

    print("\n" + "=" * 82)
    print("③ 为什么每条能力都必须带一个 probe")
    print("=" * 82)
    from common.harness import CAPABILITIES

    for c in CAPABILITIES[:3]:
        print(f"  · {c.name}")
        print(f"      不做会：{c.why}")
        print(f"      怎么验：{c.probe}")
    print("  …（其余 19 项同理，见 common/harness.py）")
    print("\n  probe 的价值：它把'我有这个能力'变成一条**可执行的检查**。")
    print("  没有 probe 的能力项，等于没有验收标准——也就会被悄悄改成'看起来有'。")

    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(d2, ignore_errors=True)

    print("\n" + "=" * 82)
    print("结论：体检的正确用法")
    print("=" * 82)
    print("  1. 用它找出'你以为有、其实没有'的能力（最常见的意外）")
    print("  2. 再用 probe 逐条验证'有，但能不能用'（这一步只能人做）")
    print("  3. 把等级记进 README，每次提 PR 时看一眼有没有掉")
    print("\n  ⚠️ 不要用它打分排名——它只认文件名和关键词，")
    print("     对自己写简历没用，对'别把能力改坏了'才有用。")


if __name__ == "__main__":
    main()
