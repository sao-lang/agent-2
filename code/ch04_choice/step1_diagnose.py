"""第 4 章 step1：先诊断，再选型——四个问题定位你的真实缺口（离线）。

运行：
    python code/ch04_choice/step1_diagnose.py

上一级的痛点（第 3 章）：你把 prompt 调到 100% 了，但老板问"要不要上微调"、
                      "要不要上 Agent"，你还是答不上来——因为这是**选型**问题，不是 prompt 问题。

这一级做什么：给一个可执行的诊断器。回答四个问题，它告诉你缺的是
  知识 / 行为 / 语言分布 / 流程，以及对应的最小方案。

关键原则：**能用轻方案稳定解决的，不要过早引入重方案。**
方案从轻到重：Prompt < RAG < Workflow < Agent < 微调 < 续训
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Question:
    key: str
    text: str  # 诊断问题
    symptom: str  # 典型现象
    answer: str  # 缺口
    plan: str  # 最小方案
    chapter: str  # 本书哪一章
    weight: int  # 严重度（越大越该优先处理）


QUESTIONS = [
    Question(
        "knowledge",
        "模型是不是没看到资料？",
        "不知道公司制度、产品手册、最新公告；回答没有引用依据",
        "缺知识",
        "RAG（先建检索）",
        "第 8–10 章",
        10,
    ),
    Question(
        "behavior",
        "模型是不是行为不稳定？",
        "格式飘、话术不统一、分类标签不稳、JSON 经常错",
        "缺行为约束",
        "先优化 Prompt + 结构化输出；仍有天花板才微调",
        "第 3、6、59 章",
        7,
    ),
    Question(
        "language",
        "模型是不是不懂这个领域的语言分布？",
        "拿到资料也读不懂；专业术语和行业逻辑经常错",
        "缺领域语言分布",
        "续训（通常再配合 RAG），成本最高，谨慎",
        "第 59–61 章（可选）",
        4,
    ),
    Question(
        "flow",
        "任务是不是需要多步执行？",
        "需要查资料、调接口、校验、重试、写入系统",
        "缺流程编排",
        "步骤固定 → Workflow；步骤开放 → Agent",
        "第 11–21 章",
        9,
    ),
]

# 六个真实场景，用 [知识, 行为, 语言, 流程] 的 0/1 评分描述
SCENARIOS = [
    ("内部制度问答", {"knowledge": 1, "behavior": 0, "language": 0, "flow": 0},
     "员工问'年假怎么算'，模型答的是国家法定标准"),
    ("工单字段抽取", {"knowledge": 0, "behavior": 1, "language": 0, "flow": 0},
     "JSON 格式经常错，字段名时有时无"),
    ("医疗病历理解", {"knowledge": 1, "behavior": 1, "language": 1, "flow": 0},
     "给了指南也读不懂'急性非ST段抬高型心梗'这类表述"),
    ("电商问数", {"knowledge": 1, "behavior": 0, "language": 0, "flow": 1},
     "要先召回表结构、再生成 SQL、再校验、再执行"),
    ("法律合同审查", {"knowledge": 1, "behavior": 1, "language": 1, "flow": 1},
     "既要查法条、又要固定输出格式、还要多步比对"),
    ("售后自动处理", {"knowledge": 1, "behavior": 0, "language": 0, "flow": 1},
     "查订单 → 判政策 → 决定退换 → 写工单"),
]


def diagnose(hits: dict[str, int]) -> list[Question]:
    """按严重度排序返回命中的缺口。

    排序规则（有讲究）：
      · 「缺流程」优先 —— 因为多步任务里的"知识"往往是在某一步检索出来的，
        先修流程能顺带解决它
      · 其次「缺知识」—— 它通常是效果问题的主因
      · 「缺行为」和「缺语言分布」放后面 —— 它们更可能是知识补齐后的残留问题
    """
    order = {"flow": 0, "knowledge": 1, "behavior": 2, "language": 3}
    return sorted(
        (q for q in QUESTIONS if hits.get(q.key)),
        key=lambda q: (order[q.key], -q.weight),
    )


def verdict(hits: dict[str, int]) -> str:
    """给出整体建议。多条命中时，先把最重的一条做透。"""
    got = diagnose(hits)
    if not got:
        return "没有缺口——问题可能是 prompt 还没写好，先回到第 3 章"
    if len(got) == 1:
        return f"单点缺口：{got[0].answer} → {got[0].plan}"
    return f"多点缺口（{len(got)} 项）→ **先做 {got[0].answer}**，做完再评估其余"


def main() -> None:
    print("=" * 92)
    print("第一步：四个诊断问题")
    print("=" * 92)
    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n  {i}. {q.text}")
        print(f"     典型现象：{q.symptom}")
        print(f"     对应缺口：{q.answer}")
        print(f"     最小方案：{q.plan}（{q.chapter}）")

    print("\n\n" + "=" * 92)
    print("第二步：六个真实场景的诊断结果")
    print("=" * 92)
    print(f"{'场景':<14}{'缺口':<28}{'建议'}")
    print("-" * 92)
    for name, hits, symptom in SCENARIOS:
        got = diagnose(hits)
        gaps = " + ".join(q.answer for q in got) if got else "无"
        v = verdict(hits)
        print(f"{name:<14}{gaps:<28}{v}")
        print(f"{'':14}现象：{symptom}")
    print("-" * 92)

    print("\n" + "=" * 92)
    print("第三步：方案成本与风险排序（从轻到重）")
    print("=" * 92)
    plans = [
        ("Prompt 优化", 1, 1, "1–3 天", "效果有天花板"),
        ("结构化输出 / 解析", 2, 2, "3–5 天", "依赖模型遵循能力"),
        ("RAG", 3, 4, "2–4 周", "检索质量是新的瓶颈"),
        ("Workflow", 4, 5, "2–4 周", "步骤变了要改代码"),
        ("Agent", 5, 7, "3–6 周", "不确定、贵、难调试"),
        ("微调（LoRA）", 6, 8, "4–8 周", "数据质量 + 需重训 + 不能消幻觉"),
        ("续训", 7, 10, "2–4 月", "语料/算力/评测三重成本"),
    ]
    print(f"{'方案':<18}{'成本':>4}{'风险':>4}{'周期':>9}   主要代价")
    print("-" * 92)
    for name, cost, risk, dur, price in plans:
        print(f"{name:<18}{cost:>4}{risk:>4}{dur:>9}   {price}")
    print("-" * 92)

    print("\n" + "=" * 92)
    print("第四步：为什么「先轻后重」是对的")
    print("=" * 92)
    print("  假设'内部制度问答'直接上微调：")
    print("    · 需要整理 500+ 条'问题-答案'对（2 周）")
    print("    · 训练 + 评测（1–2 周）")
    print("    · 制度每季度更新 → **每次都要重新训练**")
    print("    · 无法给出'依据来自哪份文件' → 合规上不可接受")
    print()
    print("  同样场景上 RAG：")
    print("    · 把制度文档切片入库（3 天）")
    print("    · 制度更新 → 重新入库即可，**当天生效**")
    print("    · 能给出引用来源 → 合规可接受")
    print()
    print("  **同样的效果，RAG 的维护成本是微调的 1/10。**")
    print("  这就是'缺知识先看 RAG'的工程原因，不是'RAG 更先进'。")

    print("\n" + "=" * 92)
    print("结论")
    print("=" * 92)
    print("  · 选型不是选'最强的'，是选'能稳定解决当前缺口的最轻方案'。")
    print("  · 四个诊断问题的顺序就是排查顺序：先看知识，再看行为，再看语言，最后看流程。")
    print("  · 多条缺口同时存在时，**先做最重的一条**，做完重新诊断——")
    print("    因为做完 RAG 以后，'行为不稳'可能自己就好了（模型有依据了，格式也更稳）。")
    print()
    print("  常见的错误顺序是反的：先上 Agent，发现答不准，再补 RAG，再回头调 prompt。")
    print("  每一步都在给前一步擦屁股。")

    assert diagnose({"knowledge": 1})[0].key == "knowledge"


if __name__ == "__main__":
    main()
