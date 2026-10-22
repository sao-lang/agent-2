"""第 26 章 step2：三个判据，落到具体任务上（离线）。

运行：
    python code/ch26_multi_agent/step2_criteria.py

上一级的痛点：知道了拆了更贵，但不知道"贵得值不值"。

这一级做什么：把"该不该拆"变成三个可回答的问题，并对八个真实任务逐个判：
  · 能并行吗？        → 拆了能省墙钟时间（唯一无可替代的收益）
  · 需要互相看吗？    → 需要但装得下 → 用单 Agent + Reflection（第 7 章）
  · 上下文装不下吗？  → 拆的最强理由，但汇总者可能又装不下

判据不是"三个里满足一个就拆"，顺序很重要：
  ① 装不下 → 必须拆（再谈怎么拆）
  ② 能并行 → 值得拆（为了时间）
  ③ 只是想"分工清楚" → 不拆（单 Agent 加 prompt 就行）
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class Task:
    name: str
    parallel: bool          # 子任务之间没有依赖，可以同时做
    cross_read: bool        # 子任务必须看到彼此的结果才能判断
    over_context: bool      # 单次调用装不下全部材料
    summary_fits: bool = True   # 汇总阶段能不能一次装下所有子结果

    def verdict(self) -> tuple[bool, str]:
        if self.over_context:
            if not self.summary_fits:
                return True, "必须拆，但汇总要分层（先合并成摘要再喂）"
            return True, "必须拆：单个上下文装不下"
        if self.parallel:
            return True, "值得拆：真并行，延迟从 sum 变 max"
        if not self.cross_read:
            return False, "不拆：没有并行收益，拆了只是更贵"
        return False, "不拆：需要交叉验证但装得下 → 单 Agent + Reflection（第 7 章）"


TASKS = [
    Task("写三份不同产品的文案", parallel=True, cross_read=False, over_context=False),
    Task("写文案 + 审文案", parallel=False, cross_read=True, over_context=False),
    Task("读 500 页手册后总结", parallel=True, cross_read=False, over_context=True),
    Task("查一个订单状态", parallel=False, cross_read=False, over_context=False),
    Task("对比 5 家竞品定价", parallel=True, cross_read=False, over_context=False),
    Task("审合同时交叉核对 12 份附件", parallel=False, cross_read=True, over_context=True),
    Task("写 12 万字报告并保证术语一致", parallel=True, cross_read=True, over_context=True),
    Task("把 12 万字报告合成一页纸", parallel=False, cross_read=True, over_context=True, summary_fits=False),
]


def main() -> None:
    print("=" * 88)
    print("八个真实任务，逐条过判据")
    print("=" * 88)
    print(f"{'任务':<28}{'并行':>6}{'互看':>6}{'装不下':>7}   结论")
    print("-" * 88)

    split = 0
    for t in TASKS:
        ok, why = t.verdict()
        split += int(ok)
        flags = f"{'Y' if t.parallel else '-':>6}{'Y' if t.cross_read else '-':>6}{'Y' if t.over_context else '-':>7}"
        print(f"{t.name:<28}{flags}   {'✅' if ok else '❌'} {why}")

    print("-" * 88)
    print(f"八条里只有 {split} 条值得拆。**判据的作用是把'想拆'变成'该拆'。**")

    print("\n" + "=" * 88)
    print("最容易搞错的一条：'写文案 + 审文案'")
    print("=" * 88)
    print("  直觉：写手和审核是两个角色，该拆。")
    print("  实际：审核者只看到写手的**输出**，看不到写手的**推理**；")
    print("        单 Agent 反思时看到的是自己完整的上文，能定位到'哪一句依据不足'。")
    print("  → 上下文装得下时，单 Agent + Reflection 更便宜也更准（第 7 章实测）。")
    print("  → 只有材料大到装不下（比如 12 份合同附件），才必须拆开分头看。")

    print("\n" + "=" * 88)
    print("最隐蔽的一条：'12 万字报告合成一页纸'")
    print("=" * 88)
    print("  这一条的'需要互看'几乎是必然的：一页纸的结论横跨全文，")
    print("  分头读的每个 agent 都只看得到自己那段，谁也说不清全文主线。")
    print("  更要命的是**汇总者装不下 12 份子结果**——拆完还得再拆一层。")
    print("  正确做法是分层汇总：子结果先压成摘要，再汇总摘要。")
    print("  不做分层，你会得到'拆了 12 个 agent 却在最后一步爆上下文'。")

    print("\n" + "=" * 88)
    print("下一级：判据说'能拆'，拆出来的形态长什么样？")
    print("=" * 88)
    print("  两种形态：Supervisor（协调者分派，串行）与 fan-out（并行子任务）。")
    print("  下一级会各跑一遍，并演示三个最容易写错的地方。")


if __name__ == "__main__":
    main()
