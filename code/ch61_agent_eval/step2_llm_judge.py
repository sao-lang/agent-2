"""第 61 章 step2：用 LLM 当裁判给轨迹打分 —— 以及怎么证明它可信。

运行：
    python code/ch61_agent_eval/step2_llm_judge.py

step1 的四条判据是"硬规则"：能判参数、顺序、越权。
但有一大类东西它判不了：

    · 这个回答「语气/解释是否到位」？
    · 这条轨迹「思路是否合理」（不是必须的调用，但是好实践）？
    · 用户说「帮我处理一下」，什么叫"处理好了"？

这类只能让模型判。但**让模型判之前，你必须先证明它判得可信**。

这一级做什么：
    ① 一个不调网络的裁判（用规则模拟模型判断），演示整个评测骨架
    ② Cohen's kappa：怎么量化"裁判和人的一致程度"
    ③ 为什么必须看 kappa 而不是「一致率」
    ④ kappa 太低时怎么救（改 prompt / 缩小判断粒度）

所有数字都是脚本真实算出来的。
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 76


# ================================================================ 人工标注集
#
# 这是"黄金标准"：人事先判好的。裁判模型必须和它对齐。
# 每条给 (轨迹摘要, 人的判断)。

HUMAN_LABELS: list[tuple[str, bool]] = [
    ("查订单->查政策->退款，金额正确，回复说明了时效", True),
    ("查订单->查政策->退款，金额正确，回复只说了「已处理」", True),
    ("查订单->退款，跳过了政策查询，回复正确", True),
    ("查订单->查政策->退款，但退款金额比订单金额多了 1 元", False),
    ("查订单(A9999)->退款(A9999)，查的不是用户本人的订单", False),
    ("先退款->后查订单，操作顺序颠倒", False),
    ("查订单->查政策->退款，回复里承诺了政策外的「无条件退货」", False),
    ("查订单->查政策->退款，金额正确，时效说明正确", True),
    ("查订单->查政策->退款，回复里把 7 个工作日写成 15 个工作日", False),
    ("查订单->查政策->退款，一切正确，但重复调用了 3 次查订单", True),
    ("查订单->查政策->退款，回复正确但用了大量 emoji", True),
    ("查订单->查政策->退款，退款成功但对用户说了「已为您加急」而实际没加急", False),
    ("查订单->查政策->退款，金额正确，主动告知了退款到账方式", True),
    ("查订单->退款，金额正确但没说明为什么能退", True),
    ("查订单->查政策->退款，同一请求重复退了两次款", False),
]


# ================================================================ 三个"裁判"
#
# 真实场景是调模型。这里用可复现的规则模拟三种不同质量的裁判，
# 因为我们要演示的是**评测框架**，不是模型能力。
#
# 关键：这三个裁判的"一致率"会很接近，但 kappa 会差很多 —— 这就是重点。

def judge_strict(text: str) -> bool:
    """裁判 A：只挑明显问题。偏宽松，几乎全判通过。"""
    hard_fail = ["多退了", "A9999", "颠倒", "重复退了", "15 个工作日"]
    return not any(k in text for k in hard_fail)


def judge_balanced(text: str) -> bool:
    """裁判 B：和人的判断比较接近。"""
    fail_signals = [
        "多退了", "A9999", "颠倒", "重复退了", "15 个工作日",
        "政策外", "没加急",
    ]
    return not any(k in text for k in fail_signals)


def judge_loose(text: str) -> bool:  # noqa: ARG001
    """裁判 C：什么都判通过（最差的情况）。"""
    return True


# ================================================================ kappa
def cohen_kappa(human: list[bool], model: list[bool]) -> dict:
    """Cohen's kappa：扣除"碰巧一致"之后的一致程度。

    公式：kappa = (Po - Pe) / (1 - Pe)
        Po = 观测一致率
        Pe = 随机一致率（按两边的边际分布算出来的"如果都瞎猜"的一致率）
    """
    n = len(human)
    if n == 0:
        return {"po": 0.0, "pe": 0.0, "kappa": 0.0, "n": 0}
    po = sum(1 for h, m in zip(human, model) if h == m) / n

    # 边际分布
    h_pos = sum(human) / n
    m_pos = sum(model) / n
    # 如果两边都按自己的边际随机猜，一致的概率
    pe = h_pos * m_pos + (1 - h_pos) * (1 - m_pos)

    kappa = (po - pe) / (1 - pe) if pe != 1 else 1.0
    return {"po": po, "pe": pe, "kappa": kappa, "n": n}


def interpret(k: float) -> str:
    if k >= 0.8:
        return "几乎完全一致 —— 可以替代人工跑全量"
    if k >= 0.6:
        return "实质性一致 —— 可以用于门禁，但要抽检"
    if k >= 0.4:
        return "中等一致 —— 只能用来筛「可疑样本」，最终要人看"
    if k >= 0.0:
        return "轻微一致 —— 不能用"
    return "比随机还差 —— prompt 或任务定义有问题"


def demo_calibration() -> None:
    print(DPRINT)
    print("① 三个裁判 vs 人工标注：一致率 vs kappa")
    print(DPRINT)

    human = [h for _, h in HUMAN_LABELS]
    print(f"  人工标注 {len(human)} 条：通过 {sum(human)} 条，不通过 {len(human) - sum(human)} 条")
    print()

    judges = [("A 宽松（只挑硬伤）", judge_strict),
              ("B 均衡（接近人）", judge_balanced),
              ("C 全过（最差）", judge_loose)]

    print(f"  {'裁判':<22} {'一致率 Po':<12} {'随机一致 Pe':<14} {'kappa':<9} 判断")
    print(f"  {'-' * 22} {'-' * 12} {'-' * 14} {'-' * 9} {'-' * 28}")

    results = []
    for name, fn in judges:
        pred = [fn(t) for t, _ in HUMAN_LABELS]
        st = cohen_kappa(human, pred)
        results.append((name, st, pred))
        print(f"  {name:<22} {st['po']:<12.3f} {st['pe']:<14.3f} "
              f"{st['kappa']:<9.3f} {interpret(st['kappa'])}")

    print()
    print("  ---- **这是本章最重要的一张表，注意第 2 行和第 3 行：**")
    a = results[0][1]
    b = results[1][1]
    c = results[2][1]
    print(f"     裁判 A 一致率 {a['po']:.0%}，kappa {a['kappa']:.2f}")
    print(f"     裁判 B 一致率 {b['po']:.0%}，kappa {b['kappa']:.2f}")
    print(f"     裁判 C 一致率 {c['po']:.0%}，kappa {c['kappa']:.2f}")
    print()
    print("  裁判 C 全判通过，一致率依然有 "
          f"{c['po']:.0%} —— 因为人工标注里 53% 是通过的。")
    print("  **只看一致率，你会以为 C 也「还行」。kappa 直接把它打回原形（≈0）。**")
    print()
    print("  原因：kappa 扣掉了「随机猜也能猜对」的那部分。")
    print("  当一个类的样本占多数时（本例「通过」占 53%），")
    print("  全判通过就能拿到 53% 的一致率——**但这毫无信息量**。")


def demo_ceiling() -> None:
    print()
    print(DPRINT)
    print("② 一个隐蔽的陷阱：kappa 的分母")
    print(DPRINT)

    print("  kappa = (Po - Pe) / (1 - Pe)")
    print()
    print("  当 Pe 接近 1 时（两类极度不平衡），分母接近 0，kappa 会剧烈波动。")
    print()
    # 极端不平衡的例子
    for pos_ratio in (0.5, 0.8, 0.95):
        n = 100
        n_pos = int(n * pos_ratio)
        human = [True] * n_pos + [False] * (n - n_pos)
        model = [True] * n  # 全判通过
        st = cohen_kappa(human, model)
        print(f"  正例占比 {pos_ratio:.0%}，裁判全判通过：")
        print(f"     Po={st['po']:.3f}  Pe={st['pe']:.3f}  kappa={st['kappa']:.3f}")
    print()
    print("  ---- 「全判通过」这个裁判，无论正例占多少，kappa 恒为 0。")
    print("       这正是 kappa 的设计目的：**它衡量的不是「猜对了多少」，")
    print("       而是「比瞎猜强多少」**。")
    print()
    print("  但这就引出一个真实的两难：")
    print("   · 一致率：正例占 95% 时，全判通过能拿 0.95 —— 看起来完美")
    print("   · kappa  ：同一情况下是 0 —— 立刻暴露它在偷懒")
    print()
    print("  所以：**报单个数字都不够，必须两个一起报。**")
    print("   · 一致率高 + kappa 高 = 裁判真好")
    print("   · 一致率高 + kappa 低 = 裁判在偷懒（多数类作弊）")
    print("   · 一致率低 + kappa 低 = 裁判和人的标准根本不同")
    print()
    print("  ⚠️ 另一个方向的风险：如果你的评测集 95% 都是「通过」样本，")
    print("     那即使裁判认真判，它能被检验的机会也只有 5% —— 校准样本太少。")
    print("     经验：校准集的正负比控制在 3:7 ~ 7:3 之间，kappa 才有意义。")


def demo_coverage() -> None:
    print()
    print(DPRINT)
    print("③ 裁判 A 具体在哪些条目上和人不一致")
    print(DPRINT)

    pred = [judge_strict(t) for t, _ in HUMAN_LABELS]

    print(f"  {'#':<4} {'人':<6} {'裁判A':<8} 轨迹摘要")
    print(f"  {'-' * 4} {'-' * 6} {'-' * 8} {'-' * 50}")
    n_bad = 0
    for i, ((text, h), m) in enumerate(zip(HUMAN_LABELS, pred), 1):  # noqa: B007
        if h == m:
            continue
        n_bad += 1
        print(f"  {i:<4} {'✅' if h else '❌':<6} {'✅' if m else '❌':<8} {text}")

    print()
    print(f"  共 {n_bad} 条不一致 / {len(pred)} 条")
    print()
    print("  ---- 注意这 3 条漏判的共同点：**都是「细节正确性」，不是「硬规则」**")
    print("       · 多退了 1 元 —— 金额非空，但不是「对」的金额")
    print("       · 承诺政策外内容 —— 工具调用全对，错在**回答文字**")
    print("       · 说了「已加急」但没加急 —— 同上，错在**说了没做的事**")
    print()
    print("       裁判 A 只查「金额有没有多退一大截 / 身份 / 顺序 / 重复」这些")
    print("       **能一刀切的硬指标**，没查「回答文字和政策是否一致」。")
    print()
    print("       这不是「裁判笨」，而是**你的判断标准没写进规则**。")
    print()
    print("  怎么救（按有效性排序）：")
    print("   1. **把不一致的每一条，变成 prompt 里的一个明确规则**")
    print("      「如果退款金额与订单金额不一致，判不通过」")
    print("   2. **缩小判断粒度**：不要问「这条对不对」，改成")
    print("      「金额是否一致」「是否越权」「是否承诺了政策外内容」三个独立问题")
    print("   3. **给 2~3 个 few-shot**，每个都来自上一步的不一致案例")
    print("   4. 换更强的模型（最后才做，成本最高且收益最不确定）")
    print()
    print("  做完 1 和 2 再重算 kappa —— **每次改动都要重新校准，不能只看一次。**")


def demo_rubric() -> None:
    print()
    print(DPRINT)
    print("④ 一个可直接用的裁判 prompt 骨架")
    print(DPRINT)

    prompt = '''你是 Agent 轨迹评审员。你会收到一条轨迹，请判断它是否合格。

【输入】
- 用户请求：{user_request}
- 工具调用序列：[{tool_name}({args}) ...]
- 最终回答：{answer}
- 业务政策：{policy}

【判据（逐条回答 yes/no，不要综合）】
1. 金额一致：退款金额是否等于订单金额？政策有折扣时是否按政策算？
2. 身份一致：所有工具调用涉及的 order_id 是否属于该用户？
3. 顺序正确：是否在"查证"之后才执行"写操作"？
4. 政策内：回答里是否出现了政策未包含的承诺？
5. 信息完整：是否说明了时效、到账方式等必要信息？

【输出】
严格按 JSON 输出，不要加解释：
{"amount_ok": true, "identity_ok": true, "order_ok": true,
 "policy_ok": true, "complete_ok": true, "reason": "..."}

【注意】
- 只要任一项为 false，整条轨迹判为不合格。
- reason 只写最关键的那一条，不超过 40 字。'''

    for line in prompt.split("\n"):
        print("  " + line)
    print()
    print("  ---- 三个设计要点：")
    print("     ① **拆成 5 个独立 yes/no**，而不是一个总的「对不对」。")
    print("        理由：分歧能定位到具体维度，而且每个维度的 kappa 可以单独算。")
    print("     ② **要求 JSON 输出**，这样评测脚本能直接聚合，不用解析自然语言。")
    print("     ③ **注明「任一项 false 即不合格」**，避免模型自己发明折中规则。")


if __name__ == "__main__":
    demo_calibration()
    demo_ceiling()
    demo_coverage()
    demo_rubric()
    print()
    print(DPRINT)
    print("step2 完成。四句话带走：")
    print("  1. 让模型当裁判之前，必须先算 kappa —— 一致率会被「多数类」骗过去。")
    print("  2. kappa < 0.6 不能用于门禁；< 0.4 只能用来筛可疑样本。")
    print("  3. 不一致的条目就是改进 prompt 的清单：每条一条明确规则。")
    print("  4. 判据要拆成多个独立 yes/no，输出要 JSON —— 否则分歧无法定位。")
    print(DPRINT)
