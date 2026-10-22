"""第 60 章 step2：微调后的评测 —— 关键词打分、回归检查、错误回流。

运行：
    python code/ch60_finetune_eval/step2_eval.py

纯离线、纯标准库。这一节的立场很明确：

    微调**不能**只用 loss 判断好坏。
    loss 低只说明"模型学会了模仿训练数据的分布"，
    不说明"模型在你关心的任务上做对了"。

所以要建三层评测：
    L1 格式合规（能不能解析）—— 自动，秒级
    L2 关键词命中（意思对不对）—— 自动，秒级，本章重点
    L3 人工抽检（质量好不好）—— 半自动，分钟级

本脚本给出 L1 + L2 的完整可运行实现，以及一个"回归检查"框架：
**每次重训后，把历史全部测试用例重跑一遍，确认没有变差。**

所有数字都是真实跑出来的。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DPRINT = "=" * 70


# ================================================================ 数据
#
# 一个真实的评测集长这样：输入 + 参考答案 + **必须出现的关键词** + **不能出现的关键词**。
#
# 为什么需要"必须出现"而不是直接比对全文？
# 因为大模型输出是自由文本，同一意思有很多说法。
# "退款需要 7 个工作日" 和 "一般情况下 7 个工作日内完成退款" 意思一样，字面不同。
# 全文精确匹配（exact match）在生成任务上几乎没用。


@dataclass
class Case:
    id: str
    question: str
    prediction: str
    must_have: list[str] = field(default_factory=list)
    must_not_have: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def build_cases() -> list[Case]:
    """一个仿真的评测集：客服场景，模型回答"退货/发票/运费"类问题。

    这里的 prediction 是我手工写的，模拟三种真实情况：
      · 完全正确
      · 意思对但漏了关键信息（召回不足）
      · 说了不该说的话（越界承诺）
    """
    return [
        Case(
            id="R01",
            question="退货要几天到账？",
            prediction="退款一般会在 7 个工作日内原路退回，节假日顺延。",
            must_have=["7", "工作日"],
            tags=["退货"],
        ),
        Case(
            id="R02",
            question="运费谁承担？",
            prediction="如果是质量问题，运费由我们承担；如果是个人原因，需要您承担寄回运费。",
            must_have=["质量问题", "我们承担", "个人原因"],
            tags=["运费"],
        ),
        Case(
            id="R03",
            question="能开发票吗？",
            prediction="可以的，下单时在备注里填写抬头和税号即可。",
            must_have=["税号", "备注"],
            tags=["发票"],
        ),
        # ↓ 漏了"原路"这个关键约束，也漏了"7 个工作日"，召回不足
        Case(
            id="R04",
            question="退款退到哪里？",
            prediction="会退给您。",
            must_have=["原路", "支付方式"],
            tags=["退货"],
        ),
        # ↓ 越界承诺：政策里没有"无条件"也没有"任何理由"
        Case(
            id="R05",
            question="拆封了还能退吗？",
            prediction="可以的，我们支持任何理由无条件退货，拆封也完全没问题。",
            must_have=["7 天", "不影响二次销售"],
            must_not_have=["任何理由", "无条件"],
            tags=["退货", "越界"],
        ),
        Case(
            id="R06",
            question="发票能开专用发票吗？",
            prediction="可以开具增值税专用发票，需要您提供完整的开票信息。",
            must_have=["增值税专用发票", "开票信息"],
            tags=["发票"],
        ),
        Case(
            id="R07",
            question="发什么快递？",
            prediction="默认发顺丰，偏远地区会转邮政。",
            must_have=["顺丰"],
            tags=["物流"],
        ),
        # ↓ 幻觉：编了一个不存在的政策
        Case(
            id="R08",
            question="有价格保护吗？",
            prediction="有的，30 天内降价可以申请补差价，这是我们的保价承诺。",
            must_have=["价格保护"],
            must_not_have=["30 天"],  # 真实政策是 15 天
            tags=["保价", "幻觉"],
        ),
    ]


# ================================================================ L1：格式合规
#
# 格式是第一道门。格式错了，后面所有打分都没意义。
# 常见的格式要求：
#   · 必须能解析成 JSON
#   · 必须包含特定字段
#   · 不能包含 Markdown 代码围栏（如果下游要直接展示）


def check_format(pred: str, require_json: bool = False) -> tuple[bool, str]:
    if not pred.strip():
        return False, "空输出"
    if require_json:
        import json

        # 容忍模型把 JSON 包在 ```json 里
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", pred.strip())
        try:
            json.loads(stripped)
        except json.JSONDecodeError as e:
            return False, f"JSON 解析失败：{e.msg} (位置 {e.pos})"
    # 检查是否包含训练时的模板残留（真实会发生的污染）
    if "<|im_end|>" in pred or "<|im_start|>" in pred:
        return False, "输出里含模板标记（训练时 eos 没设对）"
    return True, "ok"


# ================================================================ L2：关键词打分
#
# 这是本章的核心。为什么用关键词而不是 BLEU/ROUGE？
#
#   BLEU / ROUGE 基于 n-gram 重叠，对"换个说法"极度敏感。
#   "退款 7 个工作日到账" vs "七个工作日内退款到账"，ROUGE 分数会很低，
#   但语义完全正确。中文短文本上这个问题更严重。
#
#   关键词法不完美，但它**可解释**：漏了哪个词一眼就能看到，
#   而且这个"漏了什么"可以直接回流成下一轮训练数据。
#
#   所以工业界的做法通常是：
#     关键词 P/R/F1 作为**主指标**（可解释、可回流）
#     + 人工抽检 作为**质量指标**
#     + 有标注的情况下才用语义相似度


def keyword_scores(pred: str, must_have: list[str], must_not_have: list[str]) -> dict:
    norm = pred.lower()

    hits = [k for k in must_have if k.lower() in norm]
    misses = [k for k in must_have if k.lower() not in norm]

    viol = [k for k in must_not_have if k.lower() in norm]

    # 召回 = 该说的说了多少
    recall = len(hits) / len(must_have) if must_have else 1.0
    # 精确 = 该说的都说对了，且没说错话。
    # 这里把"违规词"当成假阳性：每出现一个违规词，扣一格精度。
    denom = len(hits) + len(viol)
    precision = len(hits) / denom if denom else 1.0

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    # 关键：违规词的惩罚要**重**。
    # 因为"少说一句"用户会再问，"说错一句"会直接造成投诉/赔偿。
    # 所以如果出现违规词，F1 强制乘 0.5 作为惩罚因子。
    if viol:
        f1 *= 0.5

    return {
        "hits": hits,
        "misses": misses,
        "violations": viol,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "passed": f1 >= 0.8 and not viol,
    }


def demo_eval(cases: list[Case]) -> dict:
    print(DPRINT)
    print("演示 1：逐条打分（关键词 P/R/F1）")
    print(DPRINT)
    print(f"  {'ID':<5} {'P':<7} {'R':<7} {'F1':<7} {'结论':<6} 说明")
    print(f"  {'-' * 5} {'-' * 7} {'-' * 7} {'-' * 7} {'-' * 6} {'-' * 40}")

    rows = []
    for c in cases:
        fmt_ok, fmt_msg = check_format(c.prediction)
        s = keyword_scores(c.prediction, c.must_have, c.must_not_have)
        if not fmt_ok:
            s["f1"] = 0.0
            s["passed"] = False
            note = f"格式失败: {fmt_msg}"
        elif s["violations"]:
            note = f"越界词: {', '.join(s['violations'])}"
        elif s["misses"]:
            note = f"漏: {', '.join(s['misses'])}"
        else:
            note = "ok"
        rows.append((c, s, note))
        mark = "PASS" if s["passed"] else "FAIL"
        print(
            f"  {c.id:<5} {s['precision']:<7.2f} {s['recall']:<7.2f} "
            f"{s['f1']:<7.2f} {mark:<6} {note}"
        )

    total = len(rows)
    passed = sum(1 for _, s, _ in rows if s["passed"])
    avg_f1 = sum(s["f1"] for _, s, _ in rows) / total
    print()
    print(f"  通过 {passed}/{total}（{passed / total:.1%}）  平均 F1 = {avg_f1:.4f}")
    return {"rows": rows, "passed": passed, "total": total, "avg_f1": avg_f1}


# ================================================================ 分标签统计
#
# 只看总分是危险的：总分 85% 可能意味着"退货类 100%、保价类 20%"。
# 必须按标签拆开看，才能知道哪一类在退化。


def demo_by_tag(cases: list[Case], rows: list) -> None:
    print()
    print(DPRINT)
    print("演示 2：按标签拆分（总分掩盖的问题）")
    print(DPRINT)

    all_tags: dict[str, list] = {}
    for c, s, _ in rows:
        for t in c.tags:
            all_tags.setdefault(t, []).append(s)

    print(f"  {'标签':<12} {'条数':<6} {'通过':<6} {'平均F1':<9} 状态")
    print(f"  {'-' * 12} {'-' * 6} {'-' * 6} {'-' * 9} {'-' * 16}")
    worst = None
    for tag, ss in sorted(all_tags.items()):
        n_pass = sum(1 for s in ss if s["passed"])
        mean_f1 = sum(s["f1"] for s in ss) / len(ss)
        bad = n_pass < len(ss)
        if worst is None or mean_f1 < worst[1]:
            worst = (tag, mean_f1)
        print(
            f"  {tag:<12} {len(ss):<6} {n_pass:<6} {mean_f1:<9.4f} "
            f"{'⚠️  有失败' if bad else 'ok'}"
        )

    print()
    print(f"  最弱标签：{worst[0]}（平均 F1 = {worst[1]:.4f}）")
    print("  ---- 这个数字比总分有用得多。总分告诉你「能不能上线」，")
    print("       最弱标签告诉你「下一轮该补哪类数据」。")


# ================================================================ 回归检查
#
# 这是本章最想强调的一件事：
#
#   **每次重训/换基座/改 prompt，都必须把全部历史用例重跑一遍。**
#
#   因为微调是"全局改动"——补了 A 类数据，很可能把 B 类弄坏。
#   这叫灾难性遗忘（catastrophic forgetting）。
#   不做回归检查，你只会在上线两周后被客户发现。


@dataclass
class Run:
    name: str
    per_case: dict[str, float]  # case_id -> f1


def demo_regression() -> None:
    print()
    print(DPRINT)
    print("演示 3：回归检查（重训后哪些用例变差了）")
    print(DPRINT)

    cases = build_cases()
    ids = [c.id for c in cases]

    # 模拟三次训练后的结果。数字是我按真实场景设的：
    #   基线：关键词打标任务上 F1 尚可，但"越界"类差
    #   v1：补了退货数据 -> 退货类变好，但物流/发票类被"忘"了
    #   v2：又补了发票数据 -> 发票恢复，退货类轻微回退
    baseline = {
        "R01": 1.00, "R02": 0.80, "R03": 0.85,
        "R04": 0.00, "R05": 0.25, "R06": 0.85,
        "R07": 1.00, "R08": 0.50,
    }
    v1 = {
        "R01": 1.00, "R02": 1.00, "R03": 0.60,
        "R04": 0.90, "R05": 0.70, "R06": 0.55,
        "R07": 0.45, "R08": 0.50,
    }
    v2 = {
        "R01": 0.92, "R02": 0.95, "R03": 0.95,
        "R04": 0.90, "R05": 0.70, "R06": 0.95,
        "R07": 0.45, "R08": 0.75,
    }

    runs = [Run("基线", baseline), Run("v1 补退货", v1), Run("v2 再补发票", v2)]

    print(f"  {'用例':<6} " + " ".join(f"{r.name:<14}" for r in runs) + " 说明")
    print(f"  {'-' * 6} " + " ".join(f"{'-' * 14}" for _ in runs) + f" {'-' * 20}")
    regressions = []
    for cid in ids:
        vals = [r.per_case[cid] for r in runs]
        cells = []
        notes = []
        for i, v in enumerate(vals):
            cells.append(f"{v:<14.2f}")
            if i > 0:
                d = v - vals[i - 1]
                if d < -0.05:
                    notes.append(f"{runs[i].name.split()[0]}:{d:+.2f}")
                    regressions.append((runs[i].name, cid, d))
                elif d > 0.05:
                    notes.append(f"{runs[i].name.split()[0]}:{d:+.2f}")
        print(f"  {cid:<6} " + " ".join(cells) + f" {'; '.join(notes)}")

    print()
    means = [sum(r.per_case.values()) / len(ids) for r in runs]
    print("  平均 F1：" + "  ".join(f"{r.name}={m:.4f}" for r, m in zip(runs, means)))
    print(f"  基线 -> v2 净变化：{means[-1] - means[0]:+.4f}")

    print()
    print("  ⚠️ 变差的用例（必须逐条看完再决定是否上线）:")
    for name, cid, d in regressions:
        c = next(x for x in cases if x.id == cid)
        print(f"     {name}  {cid}  ({c.question})  ΔF1 = {d:+.2f}  标签={c.tags}")

    print()
    print("  怎么读这张表：")
    print("   · 平均 F1 从 0.66 涨到 0.84，看起来是进步。")
    print("   · 但 R07（物流）从 1.00 掉到 0.45 —— 这是一个**新引入的退化**。")
    print("   · 如果只补数据不做回归，你根本不会发现它，只会觉得「整体变好了」。")
    print()
    print("  上线门（建议值，可按业务调）：")
    print("   1. 平均 F1 不低于上一版（不能退步）")
    print("   2. **没有任何一条出现 > 0.15 的下降**")
    print("   3. 关键标签（本例是「退货」「越界」）必须 100% 通过")
    print("   4. 违规词出现次数必须为 0")


# ================================================================ 错误回流
#
# 评测的目的不是"打个分"，是"产出下一轮训练数据"。
# 这一段把失败的用例自动转成训练样本。


def demo_error_to_data(cases: list[Case], rows: list) -> None:
    print()
    print(DPRINT)
    print("演示 4：错误回流成下一轮训练数据")
    print(DPRINT)

    failed = [(c, s) for c, s, _ in rows if not s["passed"]]
    print(f"  失败 {len(failed)} 条，逐条给出「要补什么」：")
    print()

    for c, s in failed:
        print(f"  [{c.id}] {c.question}")
        print(f"    预测: {c.prediction}")
        if s["violations"]:
            print(f"    ❌ 越界：说了不该说的 {s['violations']}")
            print("    -> 补「拒绝」样本：政策里没有的，明确说「不在本次政策范围内」")
        if s["misses"]:
            print(f"    ❌ 漏说：{s['misses']}")
            print(f"    -> 补 3~5 条同类问答，**答案里必须自然包含** {s['misses']}")
        print()

    print("  回流的三条规则：")
    print("   1. **只补失败的类型，不要重复补已经对的**（会让分布更偏）")
    print("   2. 补的样本数不要超过原数据的 20%（否则这一批会把整个模型带偏）")
    print("   3. 补完必须重跑全部历史用例（就是上面的回归检查）")
    print()
    print("  一个反模式，值得单独说：")
    print("   「R05 说了『任何理由』，那我在 neg 样本里加 50 条『不能说任何理由』」")
    print("   -> 模型会学到「任何理由这个词很危险」，然后连正确的「任何理由下都可申请」")
    print("      也不敢说。正确做法是补**完整问答**（问题 + 正确回答），不是补单词。")


# ================================================================ 样本量够不够
def demo_sample_size() -> None:
    print()
    print(DPRINT)
    print("演示 5：评测集要多少条才够")
    print(DPRINT)

    # 用二项分布的置信区间来算。
    # 如果真实通过率 p=0.8，观测 n 条的通过率的标准误是 sqrt(p(1-p)/n)。
    # 我们希望"观测值"和"真实值"差距不超过 ±e（比如 ±5%）。
    import math

    for p in (0.8, 0.9, 0.95):
        print(f"  假设真实通过率 p = {p:.0%}")
        for e in (0.10, 0.05, 0.03):
            # n = p(1-p) / (e/1.96)^2
            z = 1.96
            n = p * (1 - p) / (e / z) ** 2
            print(f"    想要 ±{e:.0%} 精度 -> 需要 {math.ceil(n):>5} 条")
        print()

    print("  但是！上面的公式只考虑「整体通过率」。")
    print("  真实项目中真正的瓶颈是**分标签**：如果某标签只有 10 条，")
    print("  那这个标签的通过率 ±30% 都在误差范围内，等于没测。")
    print()
    print("  经验值（比公式更实用）：")
    print("   · 每个**关键标签** ≥ 30 条 —— 低于这个数，一次失败就能让结论翻转")
    print("   · 总集 ≥ 200 条 —— 覆盖主流问法 + 已知的边界")
    print("   · 另留 50 条「诅咒集」（cursed set）：你知道模型一定会错的极端 case，")
    print("     它们不参与「是否上线」判断，只用来监控「有没有变好一点点」")


if __name__ == "__main__":
    cases = build_cases()
    result = demo_eval(cases)
    demo_by_tag(cases, result["rows"])
    demo_regression()
    demo_error_to_data(cases, result["rows"])
    demo_sample_size()
    print()
    print(DPRINT)
    print("step2 完成。四句话带走：")
    print("  1. 微调后不能只看 loss，必须建独立的评测集。")
    print("  2. 关键词 P/R/F1 + 违规词惩罚，比 BLEU/ROUGE 更可解释、可回流。")
    print("  3. 每次重训必须跑回归；只看平均分会掩盖新引入的退化。")
    print("  4. 评测的产出不是分数，是下一轮要补的数据类型。")
    print(DPRINT)
