"""第 7 章 step3：真实嵌入模型——同义词终于能匹配了（有 key 走真实，无 key 走离线）。

运行：
    python code/ch07_embedding/step3_real_embedding.py

上一级的痛点（step2）：哈希嵌入能救"退货政策/退货规则"，但
                     "不想要了能退吗" 依然找不到正确文档——
                     因为它和"无理由退货"零字面重合。

这一级做什么：用真实 embedding 模型跑同一批查询，看语义检索到底强在哪，
             并给出**五个必须知道的工程事实**（维度、归一化、批量、成本、一致性）。

⚠️ 没有 API key 时走**离线语义模拟**：用一个手工构建的"同义词词典 + 哈希嵌入"，
   它比纯字面强，但仍不如真实模型——脚本会明确标注"模拟"。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.settings import get_settings  # noqa: E402
from step2_hash_embedding import hash_embed  # noqa: E402


# ============================================================ 离线语义模拟
# 手工同义词组：把这些词归一成同一个"概念词"，再走哈希嵌入。
# 这是**故意做的简化**——真实模型学到的远不止这些组。
SYNONYM_GROUPS = {
    "退款": ["退钱", "钱退回来", "把钱拿回来", "返还"],
    "退货": ["不想要了", "退掉", "不要了", "退回去"],
    "换货": ["换一个", "换个新的", "调换"],
    "物流": ["快递", "配送", "发货"],
    "时效": ["多久", "几天", "什么时候到"],
    "质量": ["坏了", "有问题", "故障"],
}


def canonicalize(text: str) -> str:
    """把同义词替换成概念词。真实模型不需要这步，但离线演示需要。"""
    out = text
    for concept, words in SYNONYM_GROUPS.items():
        for w in words:
            out = out.replace(w, concept)
    return out


def offline_embed(text: str, dim: int = 256) -> list[float]:
    """离线"语义"嵌入 = 先归一化同义词，再哈希嵌入。"""
    return hash_embed(canonicalize(text), dim=dim, ngram=2)


# ============================================================ 真实嵌入
def real_embedder():
    """返回 (embed_fn, 模型名) 或 (None, 原因)。"""
    s = get_settings()
    if s.api_key in ("", "missing"):
        return None, "未配置 OPENAI_API_KEY"

    # 优先用 OpenAI 兼容的 embedding 接口
    try:
        from openai import OpenAI

        client = OpenAI(api_key=s.api_key, base_url=s.base_url)
        # 常见 embedding 模型名，按顺序探测
        for m in ("text-embedding-3-small", "text-embedding-v3", "bge-m3", "embedding-3"):
            try:
                r = client.embeddings.create(model=m, input=["测试"])
                dim = len(r.data[0].embedding)

                def fn(text: str, _m=m) -> list[float]:
                    resp = client.embeddings.create(model=_m, input=[text])
                    return resp.data[0].embedding

                return fn, f"{m}（{dim} 维）"
            except Exception:  # noqa: BLE001 —— 探测下一个模型
                continue
    except ImportError:
        return None, "未安装 openai 包"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"

    return None, "当前 base_url 不支持 embedding 接口"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ============================================================ 测试数据
DOCS = [
    "退货政策：签收后七天内可申请无理由退货",
    "退货规则：商品需保持完好且不影响二次销售",
    "换货流程：质量问题可在十五天内换新",
    "物流时效：一般三到五个工作日送达",
    "退款到账：审核通过后三到七个工作日到账",
]

QUERIES = [
    "退货政策",
    "不想要了能退吗",
    "钱什么时候到账",
    "东西坏了能换吗",
    "快递要几天",
]

# 人工标注：每个查询的正确文档下标
GOLD = {0: 0, 1: 0, 2: 4, 3: 2, 4: 3}


def main() -> None:
    fn, info = real_embedder()
    mode = "真实模型" if fn else "离线模拟"
    embed = fn or offline_embed

    print("=" * 88)
    print(f"嵌入模型：{info}　→ 使用【{mode}】")
    print("=" * 88)
    if not fn:
        print("  （离线模拟 = 同义词归一 + 哈希嵌入。它比纯字面强，但仍不如真实模型。）")
        print("   （要跑真实数据：在 .env 里配 OPENAI_API_KEY / OPENAI_BASE_URL）")

    print("\n" + "=" * 88)
    print("5 个查询的检索结果")
    print("=" * 88)
    doc_vecs = [embed(d) for d in DOCS]
    hit = 0
    for qi, q in enumerate(QUERIES):
        qv = embed(q)
        scores = sorted(
            ((cosine(qv, dv), i, d) for i, (dv, d) in enumerate(zip(doc_vecs, DOCS))),
            reverse=True,
        )
        top_score, top_i, top_doc = scores[0]
        correct = top_i == GOLD[qi]
        hit += correct
        mark = "✅" if correct else "❌"
        print(f"\n{mark} 查询：「{q}」")
        for s, i, d in scores[:3]:
            star = "★" if i == GOLD[qi] else " "
            print(f"   {star} {s:.3f}  {d[:30]}")
        if not correct:
            print(f"     ↳ 期望：{DOCS[GOLD[qi]][:30]}")

    print("\n" + "=" * 88)
    print(f"准确率：{hit}/{len(QUERIES)} = {hit / len(QUERIES):.0%}")
    print("=" * 88)

    print("\n" + "=" * 88)
    print("五个必须知道的工程事实")
    print("=" * 88)
    facts = [
        (
            "① 维度固定且不可混用",
            "不同模型维度不同（768 / 1024 / 1536）。\n"
            "     即便维度相同，不同模型的向量空间也不能混用。\n"
            "     **建库和查询必须用同一个模型**，否则结果毫无意义。",
        ),
        (
            "② 一定要归一化",
            "余弦相似度本身不受长度影响，但混合检索/内积计算时会。\n"
            "     统一 `v / ||v||` 后，cosine 和 dot product 等价，省一次除法。",
        ),
        (
            "③ 必须批量调用",
            "逐条调用 embedding API 会让成本和时间线性膨胀。\n"
            "     一次传 100 条通常比 100 次单条快 20–50 倍。",
        ),
        (
            "④ 成本极低但不能忽略",
            "text-embedding-3-small 约 ¥0.02/百万 token，\n"
            "     比 chat 便宜 100 倍。但**重复嵌入同一份文档**是纯浪费——必须缓存。",
        ),
        (
            "⑤ 结论可复现才有意义",
            "同一文本两次嵌入必须得到**完全相同**的向量（真实模型都保证）。\n"
            "     如果你发现不一致，检查是不是混用了模型或没归一化。",
        ),
    ]
    for title, detail in facts:
        print(f"\n  {title}")
        print(f"     {detail}")

    print("\n" + "=" * 88)
    print("为什么语义检索在这里赢了")
    print("=" * 88)
    print("  「不想要了能退吗」 vs 「退货政策：签收后七天内可申请无理由退货」")
    print("    · 字面重合：只有 '退' 一个字")
    print("    · 哈希嵌入（step2）：0.102（排第 3，没召回）")
    print(f"    · {'真实模型' if fn else '离线模拟'}：{cosine(embed('不想要了能退吗'), doc_vecs[0]):.3f}")
    print()
    print("  真实模型学到的是：**'不想要了' 和 '无理由退货' 出现在相似的上下文里**。")
    print("  它不需要你写同义词表——这是几十亿参数在预训练时学到的。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  · 语义嵌入解决的是「**换了说法也能找到**」，这是词袋/哈希做不到的。")
    print("  · 但用法完全相同：`embed(text)` → 算 cosine → 取 top-k。")
    print("  · 真实项目必做四件事：**统一模型 / 归一化 / 批量 / 缓存**。")
    print("  · 下一级（step4）：向量多了以后，怎么比较「不同嵌入模型」的好坏——用数字，不用感觉。")

    assert len(embed(DOCS[0])) == len(embed(QUERIES[0])), "维度必须一致"


if __name__ == "__main__":
    main()
