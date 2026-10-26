"""第 26 章 · 第 4 级：表示工程 —— 规则到头了，让"意思"来做判断。

运行：
    python code/ch27_intent/step4_semantic.py

第 3 级结束时剩下两种红队句子，加固 L1 仍然无解：
    这单我不要了              —— 一个关键词都没有
    那个东西我不打算留了       —— 一个关键词都没有
因为**规则匹配的是字，用户说的是意思**。中间缺的那层叫「表示（representation）」。

这一级用三步把"意思"变成数字，全程离线、可复现：

    ① 手工语义特征（3 维，能解释）  —— 表示工程的最小形态
    ② 字哈希向量（256 维，无需模型）—— 真实系统的做法：任何文本 → 定长向量
    ③ 原型句 + 余弦相似度           —— 不用重新训练，加两句就能加一个意图

然后回答三个问题：
    · 它把第 3 级漏掉的两条捞回来了吗？
    · 代价是什么？（"问尺码"被拉进了"退款"）
    · 什么时候**不该**上它？（见文末）
"""
from __future__ import annotations

import math
import zlib

# ---------------------------------------------------------------- 数据

# (句子, 真实意图)。前两条是第 3 级红队的句子，后面是「换个说法」的真实样本。
# 注意最后一条：「退换」在规则里是 product_qa 的关键词，但用户问的是**行为**。
CASES: list[tuple[str, str]] = [
    ("我要退 款", "refund"),
    ("快递到现在还没影儿", "shipping"),
    ("我不想退款，就想问问物流进度", "shipping"),
    ("这单我不要了", "refund"),
    ("那个东西我不打算留了", "refund"),
    ("有什么好电影推荐", "entertainment"),
    ("我想看个片子", "entertainment"),
    ("这个耳机参数怎么样", "product_qa"),
    ("这个尺码支持退换吗", "product_qa"),
]

# 原型句（prototypes）：每个意图给 2~3 句"最典型"的说法。
# 新增一个意图 = 加一组原型句，不用训练、不用改代码。
PROTOTYPES: dict[str, list[str]] = {
    "refund": ["我要退款", "这单我不想要了", "钱退给我", "我想退掉"],
    "shipping": ["我的快递到哪了", "包裹什么时候能到", "物流一直不动"],
    "product_qa": ["这个耳机参数怎么样", "尺码怎么选"],
    "entertainment": ["推荐一部电影", "有什么好看的片子", "想放松一下看看剧"],
}

# 故意留一个"照抄关键词"的坑：「退换」被放进 product_qa，看起来合理，
RAW_KEYWORDS: dict[str, tuple[str, ...]] = {
    "refund": ("退款", "退钱", "不要了"),
    "shipping": ("物流", "快递", "到哪", "发货"),
    "product_qa": ("参数", "怎么样", "尺码", "退换"),
}

FEATURES = (
    ("refund", ("退", "不想要", "不要了", "留了")),
    ("shipping", ("到", "快递", "物流", "影儿", "进度")),
    ("qa", ("参数", "尺码", "怎么样", "支持")),
)


# ---------------------------------------------------------------- ① 语义特征

def feature_vec(text: str) -> list[float]:
    return [float(sum(w in text for w in ws)) for _, ws in FEATURES]


# ---------------------------------------------------------------- ② 字哈希向量

def hashed_vec(text: str, dim: int = 256) -> list[float]:
    """把文本切成二元组，每个二元组哈希到一个桶并累加 —— 这就是"embedding 的穷人版"。

    真实系统用训练好的模型（text-embedding-3-small 等），
    原理一样：**文本 → 定长向量，意思相近的向量夹角小**。
    """
    vec = [0.0] * dim
    grams = [text[i : i + 2] for i in range(max(len(text) - 1, 1))]
    for g in grams:
        vec[zlib.crc32(g.encode()) % dim] += 1.0
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------- ③ 原型 + 相似度

def semantic_pick(text: str, threshold: float) -> tuple[str | None, float]:
    """和每个意图的原型句比相似度，取最高的；不够像就放弃。"""
    v = hashed_vec(text)
    scores = {
        intent: max(cosine(v, hashed_vec(p)) for p in protos)
        for intent, protos in PROTOTYPES.items()
    }
    intent = max(scores, key=scores.get)
    best = scores[intent]
    return (intent, best) if best >= threshold else (None, best)


def rule_pick(text: str) -> str | None:
    hits = {i for i, kws in RAW_KEYWORDS.items() if any(k in text for k in kws)}
    return hits.pop() if len(hits) == 1 else None


# ---------------------------------------------------------------- 主流程

def main() -> None:
    phrase = "这单我不要了"
    print("=" * 92)
    print(f"第 4 级：表示工程 —— 从「{phrase}」到数字")
    print("=" * 92)
    print("① 手工语义特征：便宜、能解释，但维度靠人挑")
    print(f"   {phrase}          → {feature_vec(phrase)}")
    print("   特征顺序（refund / shipping / qa）：退、不想要、不要了、留了 | 到、快递、物流、影儿、进度 | 参数、尺码、怎么样、支持")
    print()
    print("② 字哈希向量：不需要模型，任何句子都能变成 256 维")
    v = hashed_vec(phrase)
    nonzero = [(i, x) for i, x in enumerate(v) if x]
    print(f"   维度 256，非零 {len(nonzero)} 个：{nonzero}")
    print("   一句 6 个字的句子 → 5 个二元组 → 5 个桶，其余 251 维为 0。真实 embedding 是稠密的。")
    print(f"   和「我要退款」（只共享一个「款」字）：{cosine(v, hashed_vec('我要退款')):.3f}  ← 字面不同，向量几乎不重叠")
    print(f"   和「这单我不想要了」（换了说法但结构像）：{cosine(v, hashed_vec('这单我不想要了')):.3f}  ← 用词重叠多，所以高")

    print("\n" + "=" * 92)
    print("③ 原型句 + 余弦：新增一个意图只要加两句原型句（本行的 entertainment）")
    print("=" * 92)
    print(f"{'输入':<24}{'真实':<15}{'规则':<15}{'语义(0.35)':<16}相似度")
    print("-" * 92)
    for text, truth in CASES:
        r = rule_pick(text) or "放弃"
        s, score = semantic_pick(text, 0.35)
        mark = "" if s == truth else "  ← 错"
        print(f"{text:<22}{truth:<17}{r:<15}{(s or '放弃'):<14}{score:.3f}{mark}")

    print("\n" + "=" * 92)
    print("级别总账：每一步各修好了什么、又弄坏了什么")
    print("=" * 92)
    rows = [
        ("L1 规则（含「退换」）", lambda t: rule_pick(t)),
        ("表示工程（原型相似度）", lambda t: semantic_pick(t, 0.35)[0]),
        ("规则 + 语义（规则优先，语义兜底）", lambda t: rule_pick(t) or semantic_pick(t, 0.35)[0]),
    ]
    print(f"{'方案':<32}{'准确':>6}{'错判':>6}{'放弃':>6}")
    print("-" * 92)
    for name, decide in rows:
        preds = [(t, decide(t), truth) for t, truth in CASES]
        right = sum(p == truth for _t, p, truth in preds)
        wrong = sum(p is not None and p != truth for _t, p, truth in preds)
        abstain = sum(p is None for _t, p, _truth in preds)
        print(f"{name:<32}{right:>4}/{len(CASES):<2}{wrong:>4}/{len(CASES):<2}{abstain:>4}/{len(CASES):<2}")

    print("\n  逐条看「规则 + 语义」错在哪：")
    for text, truth in CASES:
        p = rule_pick(text) or semantic_pick(text, 0.35)[0]
        if p != truth:
            print(f"    ❌ {text:<20} 期望={truth:<14} 实际={p}")

    print("\n" + "=" * 92)
    print("四句话读完")
    print("=" * 92)
    print("  1. 表示工程解决的是「字不同、意思相同」：")
    print("     「这单我不要了」和「我要退款」字面完全不同，靠原型句就能对上；")
    print("     这是加关键词永远追不上的地方 —— 用户永远有第 11 种说法。")
    print()
    print("  2. 它的错法和规则**不一样**，这才是它有价值的原因：")
    print("     规则是「命中就判」，错在照抄关键词；")
    print("     语义是「够像才判」，错在**不敢判而放弃**（上表 5 条放弃全是它的）。")
    print("     一个漏在「错」，一个漏在「弃」，错法不重叠 → 合起来 6/9，比单用任何一种都高。")
    print("     更要紧的是：合起来以后**错判 0 条**。对路由来说这比准确率重要（14.6）。")
    print("  3. 新意图的成本从「改代码 + 重测关键词」降到「加两句话」。")
    print("     这是表示工程在工业界真正被采用的原因，不是因为它准。")
    print("  4. 阈值还是那个问题：0.35 是这里手挑的，真实系统必须用标注样本标定（第 25.4 节）。")
    print()
    print("  ⚠️ 什么时候**不该**上表示工程：")
    print("     · 意图只有 3~5 个且说法固定 —— 规则的 0 延迟更值钱")
    print("     · 拿不到「同义说法」的原型句 —— 全靠模型抽出来的原型，会带上模型的偏好")
    print("     · 有副作用的意图（退款、发货）—— 语义相似度**永远不能单独**决定执行")
    print("       必须叠一层确认（第 34 章 HITL）或升到大模型（第 25.3 节 L3）")


if __name__ == "__main__":
    main()
