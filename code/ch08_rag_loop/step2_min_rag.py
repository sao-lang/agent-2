"""第 8 章 step2：RAG 最小闭环——检索 + 拼 prompt + 生成（离线可跑）。

运行：
    python code/ch08_rag_loop/step2_min_rag.py

上一级的痛点（step1）：你会存向量、会检索了。但用户要的是**答案**，不是文档列表。

这一级做什么：把三步接成闭环，并**让每一步的错误都能被看见**：
  ① 检索（embed → top-k）
  ② 组装上下文（拼进 prompt，带编号）
  ③ 生成（本脚本用抽取式模拟，有 API key 可换真实模型）
  ④ **引用校验**（答案里引用的编号真的存在吗）

关键：不接真实模型也能跑通全链路——因为**大部分 bug 在①②④，不在③**。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.settings import get_settings  # noqa: E402

from step1_vector_store import Doc, FlatStore  # noqa: E402


# ============================================================ 知识库
KNOWLEDGE = [
    ("k1", "退货政策：签收后七天内可申请无理由退货，商品需完好且不影响二次销售。", {"category": "政策"}),
    ("k2", "退货例外：定制商品、生鲜食品、已激活的数码产品不支持无理由退货。", {"category": "政策"}),
    ("k3", "换货流程：签收后十五天内出现质量问题可申请换新，需经检测确认。", {"category": "政策"}),
    ("k4", "物流时效：江浙沪地区一到两天送达，其他地区三到五个工作日。", {"category": "物流"}),
    ("k5", "退款到账：审核通过后三到七个工作日原路退回，具体以银行为准。", {"category": "退款"}),
    ("k6", "运费规则：质量问题由平台承担运费，非质量问题由买家承担。", {"category": "政策"}),
    ("k7", "优惠券规则：已使用的优惠券在退款时不返还，也不补发积分。", {"category": "退款"}),
    ("k8", "发票说明：退款后发票需一并退回，否则按税点扣除相应金额。", {"category": "退款"}),
    ("k9", "检测流程：商品寄回后五到七个工作日出具检测报告。", {"category": "售后"}),
    ("k10", "会员权益：会员享受优先审核，退款时效缩短一个工作日。", {"category": "会员"}),
    ("k11", "售后入口：App 我的订单页面可发起售后申请，支持上传凭证。", {"category": "售后"}),
    ("k12", "客服时间：工作日九点到十八点可转人工，节假日仅有在线客服。", {"category": "客服"}),
]


def build_store() -> FlatStore:
    store = FlatStore()
    store.add([Doc(id=i, text=t, meta=m) for i, t, m in KNOWLEDGE])
    return store


# ============================================================ ② 组装上下文
CONTEXT_TEMPLATE = """你是一个电商售后客服。请**只根据下面的资料**回答用户问题。

资料：
{context}

要求：
- 每条资料前有编号，引用时在句末标注 [编号]
- 资料里没有的信息，直接回答"资料中未提及"，不要推测
- 回答不超过三句话

用户问题：{question}

回答："""


def assemble(hits: list[tuple[Doc, float]], question: str) -> str:
    blocks = []
    for i, (doc, _score) in enumerate(hits, 1):
        blocks.append(f"[{i}] {doc.text}")
    return CONTEXT_TEMPLATE.format(context="\n".join(blocks), question=question)


# ============================================================ ③ 生成
def extractive_answer(hits: list[tuple[Doc, float]], question: str) -> str:
    """抽取式"生成"：只挑**最相关的那一条**资料，加上引用标记。

    为什么只挑一条？
      因为"多挑几条拼起来"正是真实模型最常犯的错误——
      **把不相关的资料也塞进答案**。这里故意保留这个限制，
      让检索质量问题直接暴露在答案里。

    真实模型会重新组织语言，但**输入错了它一样答错**。
    """
    if not hits or hits[0][1] < 0.15:
        return "资料中未提及。"

    doc, score = hits[0]
    body = doc.text.split("：", 1)[-1].rstrip("。")
    return f"根据资料，{body}[1]。"


def llm_answer(prompt: str) -> str:
    from common.settings import make_llm

    return make_llm(temperature=0.0, max_tokens=300).invoke(prompt).content  # type: ignore[union-attr]


# ============================================================ ④ 引用校验
CITE_RE = re.compile(r"\[(\d+)\]")


def check_citations(answer: str, n_hits: int) -> dict:
    cited = {int(m) for m in CITE_RE.findall(answer)}
    return {
        "cited": sorted(cited),
        "invalid": sorted(c for c in cited if not (1 <= c <= n_hits)),
        "has_citation": bool(cited),
        "n_sentences": answer.count("。"),
        "n_cited_sentences": len(CITE_RE.findall(answer)),
    }


# ============================================================ 主流程
QUESTIONS = [
    ("退货要几天内？", True),
    ("用过的优惠券退款会退吗？", True),
    ("耳机拆封激活了还能退吗？", True),
    ("检测报告要等多久？", True),
    ("你们支持花呗分期吗？", False),
    ("能不能开发票？", True),
]


def main() -> None:
    s = get_settings()
    use_llm = s.api_key not in ("", "missing")
    store = build_store()

    print("=" * 92)
    print(f"RAG 最小闭环（生成方式：{'真实模型' if use_llm else '抽取式模拟'}）")
    print("=" * 92)
    print(f"知识库：{len(KNOWLEDGE)} 条")

    MIN_SCORE = 0.20
    print(f"拒答阈值：最高分 < {MIN_SCORE} 时直接答「资料中未提及」，不交给模型\n")

    for q, answerable in QUESTIONS:
        hits = store.search(q, k=3)
        top_score = hits[0][1] if hits else 0.0
        blocked = top_score < MIN_SCORE
        prompt = assemble(hits, q)
        if blocked:
            answer = "资料中未提及。"
            how = "阈值拦截（未调用模型）"
        else:
            answer = llm_answer(prompt) if use_llm else extractive_answer(hits, q)
            how = "正常生成"
        chk = check_citations(answer, len(hits))

        print("─" * 92)
        print(f"问：{q}   （{'知识库里有' if answerable else '知识库里没有'}）")
        print("  检索到：")
        for i, (d, sc) in enumerate(hits, 1):
            star = "★" if sc == top_score else " "
            print(f"   {star}[{i}] {sc:.3f} {d.text[:46]}")
        print(f"  处理：{how}")
        print(f"  答：{answer}")
        cite_flag = "✅ 有引用" if chk["has_citation"] else "— 无引用"
        invalid = f"  ❌ 非法编号 {chk['invalid']}" if chk["invalid"] else ""
        print(f"  引用检查：{cite_flag}{invalid}")
        if not answerable:
            ok = "未提及" in answer
            if ok:
                print("  拒答检查：✅ 正确拒答")
            else:
                print("  拒答检查：❌ **知识库里没有，但它还是答了** ← 这就是 RAG 幻觉")

    print("=" * 92)
    print("对比：三种拒答策略（同一批问题）")
    print("=" * 92)
    print(f"{'策略':<26}{'拒答正确':>10}{'误拒答':>9}{'漏答(幻觉)':>12}   说明")
    print("-" * 92)

    def evaluate_threshold(min_score: float) -> tuple[int, int, int]:
        ok_deny = miss_deny = halluc = 0
        for q, answerable in QUESTIONS:
            hits = store.search(q, k=3)
            top = hits[0][1] if hits else 0.0
            blocked = top < min_score
            if not answerable and blocked:
                ok_deny += 1
            elif answerable and blocked:
                miss_deny += 1
            elif not answerable and not blocked:
                halluc += 1
        return ok_deny, miss_deny, halluc

    for label, th in (("不设阈值", 0.0), ("固定阈值 0.20", 0.20), ("固定阈值 0.30", 0.30)):
        a, b, c = evaluate_threshold(th)
        note = {
            0.0: "该拒的也答了（幻觉）",
            0.20: "基本等于不设——两条都低于 0.20 之上",
            0.30: "幻觉挡住了，但误拒了能答的问题",
        }[th]
        print(f"{label:<26}{a:>10}{b:>9}{c:>12}   {note}")
    print("-" * 92)
    print()
    print("  **这张表说明：单一绝对阈值不可能同时做到'不误拒'和'不幻觉'。**")
    print("  原因：余弦分数不是「绝对可信度」——它只在**同一个查询内部**可比。")
    print("  「能不能开发票」最高 0.229，「花呗分期」最高 0.240 ——")
    print("  分数高的那个反而是该拒的，因为**问题本身和使用词差异太大**。")
    print()
    print("  真实的三种做法（按成本从低到高）：")
    print("    ① 相对阈值：top1 分数 - top2 分数 < 0.05 视为「不确定」→ 拒答")
    print("    ② 让模型自己判：在 prompt 里要求「资料不足时输出『不足』」，再检查它有没有这么说")
    print("    ③ **LLM 判定**：用一次调用问「这些资料能回答这个问题吗」——最准，但多一次钱")
    print()
    print("  本例用的是 ① 的简化版（固定阈值），所以两种错各留了一条。")
    print("  这不是 bug，是**故意保留**——为了让你看到阈值的真实局限。")

    print("\n" + "=" * 92)
    print("自动化的四个检查（这才是 RAG 该有的验收）")
    print("=" * 92)
    checks = [
        ("检索非空", "top-k 至少一条，且最高分 > 阈值", "检索失败 / 该拒答"),
        ("引用合法", "答案里的 [n] 都在 1..k 范围内", "模型编造引用（很常见）"),
        ("有引用", "答案至少标了一个 [n]", "模型没按格式引用 → 无法追溯"),
        ("该拒答时拒答", "知识库没有的问题答'未提及'", "**幻觉** —— 最严重"),
    ]
    print(f"  {'检查':<14}{'怎么判':<40}不通过意味着")
    print("  " + "-" * 84)
    for a, b, c in checks:
        print(f"  {a:<14}{b:<40}{c}")

    print("\n" + "=" * 92)
    print("阈值挡不住的两种错（这才是真正难的）")
    print("=" * 92)
    print("  ① **检索到了错误文档，分数还挺高**")
    print("     问「耳机拆封激活了还能退吗」→ 检索第 1 名是「售后入口」（0.360），")
    print("     真正该命中的是「退货例外：已激活数码产品不支持无理由退货」（0.357）。")
    print("     分数只差 0.003，阈值拦不住，答案就是错的。")
    print("     → 这是**分块 + 检索**问题（第 9、10 章）。")
    print()
    print("  ② **引用合法，但内容被曲解**")
    print("     资料说「已激活数码产品**不**支持无理由退货」，")
    print("     模型答「已激活也可退[2]」——编号是对的，意思反了。")
    print("     → 这需要第 43 章的 faithfulness 评测（逐句核对）。")

    print("\n" + "=" * 92)
    print("结论：RAG 不是一个模型，是一条流水线")
    print("=" * 92)
    print("  ① 检索：embed → top-k（召回率决定上限，第 9、10 章）")
    print("  ② 组装：拼 prompt，必须带编号（否则无法引用）")
    print("  ③ 生成：模型照资料回答")
    print("  ④ 校验：**分数阈值 + 引用合法 + 该拒答时拒答**（最容易跳过）")
    print()
    print("  最常见的错误认知：")
    print("    ❌ 'RAG 就是向量库 + LLM' → 那只做了 ①②③，缺 ④ 就没法上线")
    print("    ✅ 'RAG 是四个环节，每个都要能单独测' → 这才是工程")
    print()
    print("  下一级（step3）：把这条流水线接上评价指标，量化它到底好不好。")

    assert len(store.docs) == len(KNOWLEDGE)


if __name__ == "__main__":
    main()
