"""第 42 章 step1：你的项目现在能回答几个问题（离线）。

运行：
    python code/ch42_harness/step1_four_questions.py

上一级的痛点：读完 41 章，能力学了一堆，但说不清"我现在到底到什么水平"。

这一级做什么：用一个盘问脚本，把项目按四个问题逐条拷问，
每个问题都要求**当场给出证据**（文件名 / 函数名 / 数字），给不出就算没有。

四个问题：
  ① 改完怎么证明变好了？    → 评测集 + A/B + 门禁
  ② 出错怎么定位？          → trace + 计量 + 审计
  ③ 坏了怎么恢复？          → 终止条件 + 重试 + 检查点 + 幂等
  ④ 花了多少钱？            → 计量 + 归因 + 预算

为什么要按这四个问题组织，而不是按章节：
  因为上线时没人问你"第几章学过什么"，只会问这四个。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code"))

from common.harness import CAPABILITIES, health_check  # noqa: E402

QUESTIONS = {
    "① 改完怎么证明变好了": ["eval_set", "trajectory_eval", "stability", "ci_gate"],
    "② 出错怎么定位": ["trace", "meter", "audit"],
    "③ 坏了怎么恢复": ["budget_brake", "retry", "durable", "idempotent"],
    "④ 花了多少钱": ["meter", "cost_attribution", "three_level_budget", "cache"],
}


@dataclass
class Answer:
    question: str
    evidence: str | None      # None = 答不上来


def probe(question: str, keys: list[str], found: dict[str, bool]) -> Answer:
    have = [k for k in keys if found.get(k)]
    if not have:
        return Answer(question, None)
    if len(have) < len(keys):
        missing = [k for k in keys if k not in found or not found[k]]
        return Answer(question, f"{len(have)}/{len(keys)}，缺 {', '.join(missing)}")
    return Answer(question, f"{len(have)}/{len(keys)}（完整）")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    hc = health_check(root)
    found = hc["found"]

    print("=" * 78)
    print("按四个问题盘问本项目")
    print("=" * 78)
    print(f"  项目：{root}")
    print(f"  成熟度：L{hc['level']}（{hc['level_name']}）\n")

    answered = 0
    for q, keys in QUESTIONS.items():
        a = probe(q, keys, found)
        if a.evidence:
            answered += 1
        mark = "✅" if a.evidence and "缺" not in a.evidence else ("⚠️" if a.evidence else "❌")
        print(f"  {mark} {q:<22}{a.evidence or '答不上来'}")

    print(f"\n  四个问题能完整回答的：{answered}/4")

    print("\n" + "=" * 78)
    print("为什么只问四个问题")
    print("=" * 78)
    print(f"  · 能力清单有 {len(CAPABILITIES)} 项，没人记得住；四个问题人人都能记住。")
    print("  · 每个问题背后都有一条完整的证据链（见上面每行的 key）：")
    for q, keys in QUESTIONS.items():
        print(f"      {q}: {', '.join(keys)}")

    print("\n" + "=" * 78)
    print("一个关键规则：必须是'当场能答'，不能'事后能查'")
    print("=" * 78)
    print("  ❌ '我回头查一下日志'")
    print("  ✅ '这次准确率 92%，比基线低 3pp，因为 retrieval 召回从 78% 掉到 71%'")
    print("\n  区别在于：前者需要 2 小时，后者需要 2 分钟。")
    print("  出事时你只有 2 分钟——用户已经在等了。")

    print("\n" + "=" * 78)
    print("下一级：把 22 项能力按六个域摆开，看等级是怎么定的")
    print("=" * 78)
    have = sum(1 for c in CAPABILITIES if found.get(c.key))
    print(f"  本项目当前具备的能力：{have}/{len(CAPABILITIES)} 项"
          f"（体检另外识别出 {sum(1 for v in found.values() if v) - have} 项辅助信号）")
    missing = [c.name for c in CAPABILITIES if not found.get(c.key)]
    print(f"  缺：{missing or '无'}")


if __name__ == "__main__":
    main()
