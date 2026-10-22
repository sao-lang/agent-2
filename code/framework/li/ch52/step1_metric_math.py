"""第 52 章 step1：四个 RAGAS 指标，手算一遍再看框架（离线）。

运行：
    python code/framework/li/ch52/step1_metric_math.py

上一级（第 51 章）的痛点：
    你能把文档变成索引了，但"这套 RAG 到底好不好"还是靠感觉。

这一级做什么：
    ① 手算 RAGAS 四个核心指标（不装 ragas，纯 Python）
    ② 看清每个指标"到底在算什么"（这是本章唯一的目的）
    ③ 演示同一份数据在真实项目里会怎么被误读
    ④ 说明为什么"照抄框架默认值"会误导你

四个指标（RAGAS 的定义）：
    context_recall     参考上下文里，有多少被检索出来了      → 召回
    context_precision  检索到的上下文里，有多少真的有用      → 精度（看排序）
    faithfulness       答案里的每个论断，是否都能在上下文找到依据
    answer_relevancy   答案是否切题

⚠️ 本仓库**不强制安装 ragas**（它会要求降级 langchain-openai、并引入
   langchain-classic）。step2 用 import 守卫演示框架 API，不装也能跑。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Case:
    q: str
    answer: str
    contexts: list[str]          # 检索到的上下文
    reference: list[str]         # 金标：回答这个问题"应该用到"的句子


# ---------------------------------------------------------------- 分词（够用就好）
def tokens(text: str) -> set[str]:
    """极简中文分词：按字 + 按 2-gram。

    为什么不用 jieba？因为本章要展示"指标算法"，不是"分词效果"。
    真实项目请换成 jieba / embedding —— 否则指标会被分词误差主导。
    """
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = {"".join(chars[i:i + 2]) for i in range(len(chars) - 1)}
    return set(chars) | bigrams


def overlap(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta) if ta else 0.0


def _sentences(blocks: list[str]) -> list[str]:
    out: list[str] = []
    for b in blocks:
        for s in re.split(r"[。！？\n]", b):
            s = s.strip()
            if len(s) >= 4:
                out.append(s)
    return out


# ---------------------------------------------------------------- 四个指标
def context_recall(case: Case) -> float:
    """金标句子里，有多少能被"检索到的上下文"覆盖。

    注意口径：这**不是**"召回了几条"，而是"金标里的每个句子被覆盖了多少"。
    """
    if not case.reference:
        return 1.0
    ctx = " ".join(case.contexts)
    hit = sum(1 for ref in case.reference if overlap(ref, ctx) >= 0.6)
    return hit / len(case.reference)


def context_precision(case: Case) -> float:
    """检索到的上下文里，有多少句子是"金标用得上"的。

    它同时看**排序**：有用的排在前面比排在后面得分高（average precision）。
    这就是为什么它叫"precision"却对顺序敏感。
    """
    refs = " ".join(case.reference)
    useful = [overlap(s, refs) >= 0.6 for s in _sentences(case.contexts)]
    if not useful or not any(useful):
        return 0.0
    total = 0.0
    tp = 0
    for i, u in enumerate(useful, 1):
        if u:
            tp += 1
            total += tp / i
    return total / tp


def faithfulness(case: Case) -> float:
    """答案里每个句子，能不能在上下文里找到依据。

    真实 RAGAS 用 LLM 逐句判定（更准，但每条 case 都要花一次调用）。
    """
    ctx = " ".join(case.contexts)
    sents = _sentences([case.answer])
    if not sents:
        return 1.0
    supported = sum(1 for s in sents if overlap(s, ctx) >= 0.5)
    return supported / len(sents)


def answer_relevancy(case: Case) -> float:
    """答案和问题的相关度。

    真实 RAGAS 会"从答案反推问题"，再算反推问题与原问题的相似度
    （用来抓"答得很通顺但跑题"）。这里用直接重合做近似。
    """
    return overlap(case.answer, case.q)


# ---------------------------------------------------------------- 样例
CASES = [
    Case(
        q="退款多久到账？",
        answer="退款将在 7 个工作日内原路退回。",
        contexts=[
            "退款将在 7 个工作日内原路退回。",
            "运费由买家承担，且需支付检测费 20 元。",
        ],
        reference=["退款将在 7 个工作日内原路退回。"],
    ),
    Case(
        q="会员退货时优惠券能拿回来吗？",
        answer="优惠券可以返还，只要申请即可。",
        contexts=[
            "退货需在签收后 30 天内申请。",
            "保修期为一年，人为损坏不在保修范围。",
        ],
        reference=["会员退货时，已使用的优惠券不返还。"],
    ),
    Case(
        q="保修期多久？",
        answer="保修期为一年，人为损坏不在保修范围。另外可以免费换新。",
        contexts=["保修期为一年，人为损坏不在保修范围。"],
        reference=["保修期为一年，人为损坏不在保修范围。"],
    ),
]


def main() -> None:
    print("=" * 92)
    print("四个指标，逐条手算（不装 ragas）")
    print("=" * 92)
    print(f"  {'问题':<22}{'recall':>8}{'precision':>11}{'faithful':>10}{'answer_rel':>12}")
    print("  " + "-" * 88)

    acc = {"recall": 0.0, "precision": 0.0, "faithful": 0.0, "relev": 0.0}
    rows = []
    for c in CASES:
        r, p, f, a = context_recall(c), context_precision(c), faithfulness(c), answer_relevancy(c)
        rows.append((c, r, p, f, a))
        acc["recall"] += r
        acc["precision"] += p
        acc["faithful"] += f
        acc["relev"] += a
        print(f"  {c.q[:20]:<22}{r:>8.2f}{p:>11.2f}{f:>10.2f}{a:>12.2f}")

    n = len(CASES)
    print("  " + "-" * 88)
    print(f"  {'平均':<22}{acc['recall']/n:>8.2f}{acc['precision']/n:>11.2f}"
          f"{acc['faithful']/n:>10.2f}{acc['relev']/n:>12.2f}")

    print("\n" + "=" * 92)
    print("逐条诊断：三个 case，三种典型的病")
    print("=" * 92)
    c0, c1, c2 = rows
    print("\n  case 1（退款多久）：")
    print(f"    recall={c0[1]:.2f} precision={c0[2]:.2f}")
    print("    → 金标被召回了（recall 1.00），precision 也是 1.00：")
    print("      因为 precision = 有用句 / 命中句，那一条无关内容只是让分母 +1。")
    print("      这是「召回对了、但上下文不干净」。修法：阈值过滤 / 重排（第 10 章）。")

    print("\n  case 2（会员优惠券）：")
    print(f"    recall={c1[1]:.2f} precision={c1[2]:.2f} faithful={c1[3]:.2f}")
    print("    → 两条上下文全都不相关。recall=0 → **先修检索**，别去调提示词。")
    print("      更要注意：答案本身是错的（说可以返还），但四个指标里没有一个直接说「你错了」——")
    print("      faithfulness 只判「有没有依据」，answer_relevancy 只判「切不切题」。")
    print("      **事实对错必须靠人工金标 answer 比对**（第 40 章那套）。")

    print("\n  case 3（保修期）：")
    print(f"    faithful={c2[3]:.2f}")
    print("    → 答案第二句「可以免费换新」在上下文里**找不到依据**，faithful 掉到 0.5。")
    print("      这是幻觉：检索对了，模型自己加了一句。修法：提示词约束 + 引用校验。")

    print("\n" + "=" * 92)
    print("为什么必须手算一遍")
    print("=" * 92)
    print("""  ① 框架有成本。RAGAS 的 faithfulness 默认用 LLM 逐句判定，N 条 case 就要 N 次调用；
     你会因为"太贵"而不评测 —— 手算版可以先做粗筛，贵的只用在可疑样本上。
  ② 口径不同。RAGAS 的 context_precision 是「平均精度」（看排序），
     不是「相关比例」。你以为的"精度"和它的"精度"不是一回事。
  ③ 阈值不同。overlap >= 0.6 是我拍的；真实项目要按你的语料校准。
  ④ 分词影响巨大。本章用 2-gram，中文短句会虚高；换成 jieba 数字会变。
     **所以任何一个指标数字，都必须标注「用什么算的」。**""")

    print("\n" + "=" * 92)
    print("四个指标各揭示什么病（一张表，建议抄走）")
    print("=" * 92)
    print("""  | 现象 | recall | precision | faithful | answer_rel | 先修什么 |
  |---|---|---|---|---|---|
  | 检索没召回 | 低 | — | — | — | 分块 / 嵌入 / 查询改写 |
  | 召回一堆噪声 | 高 | 低 | — | — | 阈值 / 重排 |
  | 答非所问 | — | — | — | 低 | 提示词 / 上下文太少 |
  | 胡编内容 | — | — | 低 | — | 提示词约束 / 引用校验 |
  | 全都低 | 低 | 低 | 低 | 低 | **先修检索，别调提示词** |

  → 这张表是"看懂指标"和"只会看总分"的分水岭。""")


if __name__ == "__main__":
    main()
