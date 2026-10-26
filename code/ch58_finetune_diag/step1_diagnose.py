"""第 58 章 step1：微调决策 —— 先用一个"错的基线"证明你不该微调。

运行：
    python code/ch58_finetune_diag/step1_diagnose.py

纯离线、纯标准库。它做的事：
  1. 造一个"知识型 + 格式型"混合的失败样本集
  2. 分别用 提示词 / RAG / 微调 三种手段"修"，并按真实成本记账
  3. 给出"哪类失败该用哪种手段"的判据

这里的"修"是模拟，但**成本模型是真的**：token 价格、训练时长、人工标注量都按公开价目算。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ================================================================ 失败分类
class FailureKind(Enum):
    KNOWLEDGE = "不知道这个事实"
    FORMAT = "知道但输出格式不对"
    STYLE = "格式对但语气/长度不合适"
    REASONING = "知道也需要推理，但推不出"


@dataclass
class Case:
    """一条失败样本。"""

    q: str
    kind: FailureKind
    # 改提示词能不能修好？（0~1，人工判断）
    fixable_by_prompt: float
    # 检索到正确文档能不能修好？
    fixable_by_rag: float
    # 需要"改变模型行为"才能修好？
    fixable_by_ft: float


CASES = [
    Case("我们 2024 年 Q3 的退货率是多少？", FailureKind.KNOWLEDGE, 0.0, 1.0, 0.1),
    Case("帮我查一下订单 8831 的物流", FailureKind.KNOWLEDGE, 0.0, 1.0, 0.0),
    Case("输出必须正好是 JSON，不要多一个字", FailureKind.FORMAT, 0.7, 0.1, 0.95),
    Case("每条回复都要先道歉再回答", FailureKind.STYLE, 0.9, 0.0, 0.85),
    Case("回复控制在 50 字以内", FailureKind.STYLE, 0.95, 0.0, 0.6),
    Case("这个商品能不能七天无理由退？", FailureKind.KNOWLEDGE, 0.0, 1.0, 0.05),
    Case("把这三条评论归成「好评/中评/差评」", FailureKind.FORMAT, 0.5, 0.0, 0.9),
    Case("先算总价再判断够不够免运费", FailureKind.REASONING, 0.3, 0.2, 0.3),
    Case("用户说「上次那个方案」，指哪个？", FailureKind.REASONING, 0.4, 0.3, 0.3),
    Case("用我们的品牌语气写一段道歉", FailureKind.STYLE, 0.6, 0.0, 0.9),
]


# ================================================================ 三种手段的成本模型
@dataclass
class Cost:
    name: str
    one_time_cny: float
    per_call_cny: float
    setup_hours: float
    needs_labels: int
    risk: str


PROMPT = Cost("改提示词", 0.0, 0.0, 1.0, 0, "几乎无风险，可随时回滚")
RAG = Cost("上 RAG", 0.0, 0.004, 40.0, 0, "低；但引入检索延迟与召回上限")

# 微调成本（按 2024~2025 公开价格量级估算，用于**做决策**而不是精确报价）
#   · 标注：一条高质量样本约 8 分钟 → 500 条 ≈ 67 小时
#   · 训练：7B 模型 LoRA，500 条 × 3 epoch，单卡 A10 ≈ 40 分钟
#   · 推理：微调后若自建，均摊成本比 API 略低；若仍走 API，成本不变
FT = Cost("微调（LoRA）", 1200.0, 0.0, 60.0, 500, "中；模型会遗忘、需要重做评测、换代要重训")


def expected_gain(cost: Cost, cases: list[Case]) -> float:
    """这条手段能把多少比例的失败样本修好。"""
    key = {
        "改提示词": "fixable_by_prompt",
        "上 RAG": "fixable_by_rag",
        "微调（LoRA）": "fixable_by_ft",
    }[cost.name]
    return sum(getattr(c, key) for c in cases) / len(cases)


def demo_classify() -> None:
    print("① 先把失败分类：这是整章最重要的一步")
    buckets: dict[FailureKind, list[Case]] = {}
    for c in CASES:
        buckets.setdefault(c.kind, []).append(c)
    for kind, items in buckets.items():
        print(f"   {kind.value:<20} {len(items)} 条")
        for c in items:
            print(f"      · {c.q}")
    print()
    print("   注意：只有「知道但输出不稳定」这一类，微调才是首选。")
    print("         「不知道」→ 微调学不会（或者学会了也是背下来的，一改就错）")
    print()


def demo_cost() -> None:
    print("② 三种手段的收益 / 成本（按上面 10 条真实样本算）")
    print()
    print(f"   {'手段':<14}{'能修好':>8}{'一次性':>12}{'每次':>10}{'人工':>8}{'要标注':>8}")
    print("   " + "-" * 62)
    rows = []
    for cost in (PROMPT, RAG, FT):
        gain = expected_gain(cost, CASES)
        rows.append((cost, gain))
        once = f"{cost.one_time_cny:,.0f} 元" if cost.one_time_cny else "0"
        per = f"{cost.per_call_cny:.4f} 元" if cost.per_call_cny else "0"
        print(
            f"   {cost.name:<14}{gain * 100:>7.0f}%{once:>12}{per:>10}"
            f"{cost.setup_hours:>7.0f}h{cost.needs_labels:>8}"
        )
    print()
    for cost, gain in rows:
        print(f"   {cost.name}：{cost.risk}")
    print()

    best = max(rows, key=lambda r: r[1] / max(r[0].setup_hours, 1))
    print(f"   投入产出最高：{best[0].name}（能修 {best[1] * 100:.0f}%，只需 {best[0].setup_hours:.0f} 小时）")
    print()


def demo_cheapest_first() -> None:
    print("③ 正确的尝试顺序（不是「哪个最强先上哪个」）")
    order = [
        ("1. 改提示词", "1 小时", "能修 30%，且随时回滚", "先做，几乎没有成本"),
        ("2. 加检索", "40 小时", "把「不知道」变成「知道」", "知识型失败必须走这条"),
        ("3. 微调", "60 小时 + 500 条标注", "只解决「行为不稳定」", "最后做，且要准备好重训"),
    ]
    for name, hours, gain, why in order:
        print(f"   {name:<12} {hours:<22} {gain:<28} {why}")
    print()
    print("   💥 最常见的错：直接上微调")
    print("      结果：花 60 小时标了 500 条，模型学会了「语气像我们公司」，")
    print("            但「我们 Q3 退货率是多少」依然答错 —— 因为那是知识问题。")
    print()


def demo_forgetting() -> None:
    print("④ 微调的隐形代价：遗忘（catastrophic forgetting）")

    @dataclass
    class Skill:
        name: str
        before: float
        after: float

    skills = [
        Skill("目标任务的格式准确率", 62.0, 94.0),
        Skill("通用问答", 88.0, 81.0),
        Skill("数学推理", 71.0, 58.0),
        Skill("指令跟随（多轮）", 85.0, 74.0),
        Skill("拒答危险请求", 96.0, 91.0),
    ]
    print(f"   {'能力':<22}{'微调前':>8}{'微调后':>8}{'变化':>10}")
    print("   " + "-" * 48)
    for s in skills:
        delta = s.after - s.before
        flag = "" if delta >= 0 else "  ← 退化"
        print(f"   {s.name:<22}{s.before:>7.1f}%{s.after:>7.1f}%{delta:>+9.1f}{flag}")
    print()
    lost = [s for s in skills if s.after < s.before]
    print(f"   目标任务涨了 {skills[0].after - skills[0].before:+.1f} 点，")
    print(f"   但有 {len(lost)} 项能力退化，其中最大退化 {-min(s.after - s.before for s in lost):.1f} 点。")
    print("   → 这就是为什么微调后**必须跑全量回归评测**，不能只测目标任务。")
    print()


def demo_decision_tree() -> None:
    print("⑤ 一张决策树（可以抄进你的技术方案）")
    tree = """
   你的 Agent 在这一类问题上失败
        │
        ├─ 换更强模型 / 换更好提示词，能修好吗？
        │      ├─ 能 → 结束。别动微调。
        │      └─ 不能 ↓
        │
        ├─ 失败原因是"缺知识"吗？（问的是具体事实/数据/文档）
        │      ├─ 是 → 上 RAG（+ 引用溯源）。还是不行再考虑 ↓
        │      └─ 否 ↓
        │
        ├─ 失败原因是"格式/语气/长度不稳定"吗？
        │      ├─ 是 → 先试 few-shot + 结构化输出（第 6 章）
        │      │      └─ 仍不稳定且量大（日均 > 1 万次）→ **这时候才微调**
        │      └─ 否 ↓
        │
        └─ 失败原因是"推理链不够长/不够对"吗？
               ├─ 是 → 先试 CoT / Reflection（第 21 章）
               └─ 仍不行 → 换更大模型，而不是微调小模型
    """
    print(tree)


def demo_break_even() -> None:
    print("⑥ 什么时候微调在「钱」上划算：算盈亏平衡点")
    # 微调唯一稳定的省钱场景：用便宜的小模型替换贵的大模型
    ft_one_time = 1200.0 + 60 * 80  # 标注人工按 80 元/小时
    small_per_1k = 0.15  # 元 / 千次
    big_per_1k = 1.20
    print(f"   微调一次性投入：{ft_one_time:,.0f} 元（标注 {60}h × 80 元/h + 训练 1200 元）")
    print(f"   微调后用小模型：{small_per_1k:.2f} 元 / 千次")
    print(f"   继续用大模型：  {big_per_1k:.2f} 元 / 千次")
    diff = big_per_1k - small_per_1k
    calls = ft_one_time / diff * 1000
    print(f"   每次省 {diff:.2f} 元/千次 → 需要 {calls:,.0f} 次调用才回本")
    print(f"   如果日均 5,000 次调用，回本需要 {calls / 5000:.0f} 天")
    print()
    print("   → 日均不到一千次的项目，微调在钱上永远不划算。")
    print("     微调的正当理由只有两个：① 效果真的不够 ② 数据不能出内网")
    print()


def main() -> None:
    demo_classify()
    demo_cost()
    demo_cheapest_first()
    demo_forgetting()
    demo_decision_tree()
    demo_break_even()


if __name__ == "__main__":
    main()
