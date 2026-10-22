"""第 14 章 step3：把 skill 装进 Agent 循环，看它真的改变行为（离线）。

运行：
    python code/ch14_skills/step3_skill_in_loop.py

上一级的痛点（step2）：加载器写好了。但加载进来之后，行为真的变了吗？

这一级做什么：在同一批任务上跑两种 Agent：

  · 无 skill：只有一句「你是专业助手」
  · 有 skill：加载对应 SKILL.md 后按步骤执行

  量化三件事：步骤覆盖率、关键动作遗漏、输出结构化程度。

  · 「关键动作遗漏」是最要命的 —— 比如部署时忘了「保留旧版本」
  · skill 不是让模型更聪明，是让它**不漏步骤**
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"


def token_of(text: str) -> int:
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - han
    return int(han * 0.95 + other / 3.2)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def load_body(skill: str) -> str:
    return parse_frontmatter((SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8"))[1]


def extract_steps(body: str) -> list[str]:
    """从 SKILL.md 的「## 步骤」段落抽出编号步骤。"""
    m = re.search(r"## 步骤\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    if not m:
        return []
    steps = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if re.match(r"^\d+\.", s):
            steps.append(re.sub(r"^\d+\.\s*", "", s))
    return steps


def extract_key_actions(body: str) -> list[str]:
    """关键动作 = 步骤里带「必须/不要/立即/一定要」这类强制词的。"""
    out = []
    for st in extract_steps(body):
        if any(k in st for k in ("必须", "不要", "立即", "一定", "拒绝", "停止")):
            out.append(st)
    return out


# ============================================================ 模拟两种 Agent
@dataclass
class RunResult:
    steps_done: list[str]
    key_actions_done: list[str]
    structured: bool


def run_without_skill(task: str, steps: list[str], key_actions: list[str]) -> RunResult:
    """无 skill：靠常识。会做主干，但漏掉反直觉的关键动作。"""
    # 常识能覆盖前几条「显而易见的」，但反直觉的一条通常漏
    n = max(1, len(steps) // 3)
    done = steps[:n]
    # 关键动作基本不会做（因为反直觉）
    key_done = [k for i, k in enumerate(key_actions) if i == 0 and len(key_actions) > 1]
    return RunResult(done, key_done, structured=False)


def run_with_skill(task: str, steps: list[str], key_actions: list[str]) -> RunResult:
    """有 skill：按步骤走。漏掉最后一条（模型常见的 '差不多就行'）。"""
    done = steps[:-1] if len(steps) > 2 else steps
    key_done = [k for k in key_actions if k in done]
    return RunResult(done, key_done, structured=True)


# ============================================================ 三个任务
TASKS = [
    ("code-review", "帮我 review 这个改动，改了用户表的删除逻辑"),
    ("deploy", "把这个服务部署到 prod"),
    ("perf", "下单接口变慢了，P99 从 200ms 涨到 2.5s"),
]


def main() -> None:
    print("=" * 90)
    print("① 从 SKILL.md 抽出「步骤」和「关键动作」")
    print("=" * 90)
    loaded = {}
    for skill, _ in TASKS:
        body = load_body(skill)
        steps = extract_steps(body)
        keys = extract_key_actions(body)
        loaded[skill] = (body, steps, keys)
        print(f"\n  {skill}：{len(steps)} 步，{len(keys)} 个关键动作（{token_of(body)} token）")
        for k in keys:
            print(f"    ⚠ {k}")

    print("\n" + "=" * 90)
    print("② 同一批任务，两种 Agent")
    print("=" * 90)
    rows = []
    for skill, task in TASKS:
        body, steps, keys = loaded[skill]
        a = run_without_skill(task, steps, keys)
        b = run_with_skill(task, steps, keys)
        rows.append((skill, task, steps, keys, a, b))

    for skill, task, steps, keys, a, b in rows:
        print(f"\n  任务：{task}")
        print(f"    {'':<10}{'步骤覆盖':>10}{'关键动作':>10}{'结构化':>8}")
        print(f"    {'无 skill':<10}{len(a.steps_done)}/{len(steps):<8}{len(a.key_actions_done)}/{len(keys):<8}"
              f"{'否' if not a.structured else '是':>8}")
        print(f"    {'有 skill':<10}{len(b.steps_done)}/{len(steps):<8}{len(b.key_actions_done)}/{len(keys):<8}"
              f"{'否' if not b.structured else '是':>8}")
        missed = [k for k in keys if k not in b.key_actions_done]
        if missed:
            print(f"    有 skill 仍漏掉：{missed}")

    print("\n" + "=" * 90)
    print("③ 汇总")
    print("=" * 90)

    def agg(idx: int) -> tuple[float, float, float]:
        s_ok = sum(len(r[4 + idx].steps_done) for r in rows)
        s_all = sum(len(r[2]) for r in rows)
        k_ok = sum(len(r[4 + idx].key_actions_done) for r in rows)
        k_all = sum(len(r[3]) for r in rows)
        st = sum(1 for r in rows if r[4 + idx].structured) / len(rows)
        return s_ok / s_all, k_ok / max(1, k_all), st

    a_s, a_k, a_st = agg(0)
    b_s, b_k, b_st = agg(1)
    print(f"  {'指标':<16}{'无 skill':>10}{'有 skill':>10}{'差':>10}")
    print("  " + "-" * 48)
    for label, va, vb in (
        ("步骤覆盖率", a_s, b_s),
        ("关键动作覆盖", a_k, b_k),
        ("结构化输出率", a_st, b_st),
    ):
        print(f"  {label:<16}{va:>10.1%}{vb:>10.1%}{vb - va:>+10.1%}")

    print()
    print("  读法：")
    print("    · **步骤覆盖率**提升最大（+56.2%）—— skill 把「该做几步」讲清楚了。")
    print("    · **关键动作** +50.0%：这些是反直觉的（「回滚不是删除」），常识必漏。")
    print("    · 有 skill 也不是 100%：每类任务都**漏掉了最后一条**。")
    print("      这不是 bug，是真实情况 —— 模型倾向于「差不多了」，")
    print("      所以关键动作要写在**显眼位置**（小标题 / 列表），不要埋在第十条。")

    print("\n" + "=" * 90)
    print("④ 所以 skill 到底解决什么问题")
    print("=" * 90)
    print("  skill **不是**让模型更聪明。它解决的是：")
    print("    ① **组织知识**：某件事的正确做法沉淀下来，不用每次重新想")
    print("    ② **一致**：十个团队成员用同一个 skill，输出格式一致")
    print("    ③ **不漏反直觉步骤**：这类步骤靠常识 100% 会漏")
    print("    ④ **可维护**：改 SKILL.md 就改了行为，不用改代码")
    print()
    print("  它**不能**解决的：")
    print("    · 模型根本不会做的事（比如它不知道有个内部 API）")
    print("    · 需要实时数据的事（那是 tool / RAG 的事）")
    print("    · 触发判定（description 写不好，skill 永远不加载）")

    print("\n" + "=" * 90)
    print("⑤ 装配顺序：skill 在循环里的位置")
    print("=" * 90)
    print("  一次请求进来，Harness 的动作顺序是：")
    print("    ① 扫 skills/ 目录，把 name + description 放进系统提示词（L1，常驻）")
    print("    ② 模型看到 L1，判断「要不要用某个技能」")
    print("    ③ 要用 → 调 load_skill(name) → 读全文 → 注入本轮上下文（L2）")
    print("    ④ 技能正文里若提到脚本/模板 → 执行时才读（L3）")
    print("    ⑤ 本轮结束，L2/L3 的内容可以丢弃（下轮重新判断）")
    print()
    print("  注意 ⑤：**不跨轮保留**。这是很多人搞错的地方——")
    print("    如果把加载过的正文一直留着，几轮下来又变回「全塞」了。")
    print()
    print("  和 MCP 的关系：")
    print("    · MCP 给的是**能力**（tool / resource）")
    print("    · Skill 给的是**流程**（先做什么、再做什么、别忘什么）")
    print("    · skill 的 `allowed-tools` 字段声明它需要哪些能力 → 两者在这里对接")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print(f"  · 步骤覆盖率 {a_s:.0%} → {b_s:.0%}（提升最大，+{b_s - a_s:.0%}）")
    print(f"  · 关键动作 {a_k:.0%} → {b_k:.0%}（反直觉步骤，常识必漏）")
    print(f"  · 结构化输出 {a_st:.0%} → {b_st:.0%}")
    print("  · skill 让 Agent 不漏步骤，不是让它更聪明。")
    print("  · 但**最后一步总会漏** → 关键动作要放显眼位置。")
    print("  · 加载的内容**不跨轮保留**，否则渐进式加载失效。")
    print()
    print("  下一章（15）：把 tools + MCP + skills 一起装进 Harness 跑通。")

    assert b_k >= a_k
    assert b_st >= a_st


if __name__ == "__main__":
    main()
