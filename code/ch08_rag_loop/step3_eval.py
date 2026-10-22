"""第 8 章 step3：给整条 RAG 流水线打分——分环节定位问题（离线）。

运行：
    python code/ch08_rag_loop/step3_eval.py

上一级的痛点（step2）：你能跑通 RAG 了，也知道它有时答错。
                     但你不知道**错在检索还是在生成**——这两件事该修的地方完全不同。

这一级做什么：拆成四个独立指标，让"哪一环坏了"变成可查的事实：
  · **检索命中率**（Recall@k）：正确答案在 top-k 里吗
  · **拒答准确率**：知识库没有的问题，它有没有拒
  · **引用准确率**：答案里的 [n] 是否合法
  · **答案正确率**：最终答案是否包含关键事实

核心结论：**这四个数字的组合能直接告诉你该改哪一章。**
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from step1_vector_store import FlatStore  # noqa: E402
from step2_min_rag import (  # noqa: E402
    build_store,
    check_citations,
    extractive_answer,
)


@dataclass
class Case:
    q: str
    gold_ids: set[str]  # 正确文档 id（空集 = 知识库里没有，应拒答）
    must_contain: list[str]  # 答案里必须出现的关键事实
    kind: str


CASES = [
    Case("退货要几天内？", {"k1"}, ["七天"], "明确"),
    Case("用过的优惠券退款会退吗？", {"k7"}, ["不返还"], "明确"),
    Case("耳机拆封激活了还能退吗？", {"k2"}, ["不支持"], "边界"),
    Case("检测报告要等多久？", {"k9"}, ["五到七个工作日"], "明确"),
    Case("退款多久到账？", {"k5"}, ["三到七个工作日"], "明确"),
    Case("运费谁出？", {"k6"}, ["平台承担"], "明确"),
    Case("东西坏了怎么换？", {"k3"}, ["换新", "检测"], "边界"),
    Case("在哪申请售后？", {"k11"}, ["订单"], "口语化"),
    Case("会员有啥好处？", {"k10"}, ["优先审核"], "口语化"),
    Case("客服几点下班？", {"k12"}, ["十八点"], "明确"),
    Case("能不能开发票？", {"k8"}, ["发票"], "边界"),
    Case("支持花呗分期吗？", set(), [], "不可回答"),
    Case("能送货上门吗？", set(), [], "不可回答"),
    Case("有优惠活动吗？", set(), [], "不可回答"),
]

K = 3
THRESHOLD = 0.20


def main() -> None:
    store: FlatStore = build_store()

    print("=" * 96)
    print(f"RAG 分环节评测（{len(CASES)} 条用例，k={K}，拒答阈值={THRESHOLD}）")
    print("=" * 96)

    rows = []
    for c in CASES:
        hits = store.search(c.q, k=K)
        top_ids = {d.id for d, _ in hits}
        top_score = hits[0][1] if hits else 0.0
        blocked = top_score < THRESHOLD
        answer = "资料中未提及。" if blocked else extractive_answer(hits, c.q)
        chk = check_citations(answer, len(hits))

        # 四个指标
        if c.gold_ids:
            retrieval_ok = bool(c.gold_ids & top_ids)
        else:
            retrieval_ok = True  # 不可回答的问题不评检索
        deny_ok = ("未提及" in answer) if not c.gold_ids else True
        cite_ok = (not chk["invalid"]) and (chk["has_citation"] or blocked)
        answer_ok = all(m in answer for m in c.must_contain) if c.must_contain else ("未提及" in answer)

        rows.append((c, retrieval_ok, deny_ok, cite_ok, answer_ok, answer, top_score, hits))

    # ---- 汇总
    answerable = [r for r in rows if r[0].gold_ids]
    unanswerable = [r for r in rows if not r[0].gold_ids]

    recall = sum(1 for r in answerable if r[1]) / len(answerable)
    deny = sum(1 for r in unanswerable if r[2]) / len(unanswerable) if unanswerable else 1.0
    cite = sum(1 for r in rows if r[3]) / len(rows)
    acc = sum(1 for r in rows if r[4]) / len(rows)

    print(f"\n{'用例':<22}{'类型':<10}{'检索':>5}{'拒答':>5}{'引用':>5}{'答案':>5}   最高分")
    print("-" * 96)
    for c, r_ok, d_ok, ci_ok, a_ok, ans, sc, _h in rows:
        m = lambda b: "✅" if b else "❌"  # noqa: E731
        print(f"{c.q:<22}{c.kind:<10}{m(r_ok):>4}{m(d_ok):>4}{m(ci_ok):>4}{m(a_ok):>4}   {sc:.3f}")
    print("-" * 96)

    print("\n" + "=" * 96)
    print("四个指标")
    print("=" * 96)
    print(f"  检索命中率 Recall@{K}  ：{recall:.0%}   （{sum(1 for r in answerable if r[1])}/{len(answerable)}，只在可回答的问题上算）")
    print(f"  拒答准确率            ：{deny:.0%}   （{sum(1 for r in unanswerable if r[2])}/{len(unanswerable)}，知识库没有的问题）")
    print(f"  引用准确率            ：{cite:.0%}   （{sum(1 for r in rows if r[3])}/{len(rows)}）")
    print(f"  答案正确率            ：{acc:.0%}   （{sum(1 for r in rows if r[4])}/{len(rows)}）")

    print("\n" + "=" * 96)
    print("怎么用这四个数字定位问题（这是本节的精髓）")
    print("=" * 96)
    print(f"  {'检索':<6}{'拒答':<6}{'答案':<6}诊断 / 该改哪一章")
    print("  " + "-" * 78)
    diag = [
        ("高", "高", "高", "✅ 都正常——可以去做成本/延迟优化了（第 36、37 章）"),
        ("低", "高", "低", "❌ **检索问题**：分块或检索方式 → 第 9、10 章"),
        ("高", "高", "低", "❌ **生成问题**：资料给了但答错 → 换更会遵循指令的模型（第 3 章）"),
        ("低", "低", "低", "❌ **两处都坏**：先修检索，再修生成（别同时改）"),
        ("高", "低", "高", "⚠️ 检索生成都对，但**该拒的没拒** → 阈值/提示词（本章 step2）"),
    ]
    for a, b, c, d in diag:
        print(f"  {a:<6}{b:<6}{c:<6}{d}")
    print("  " + "-" * 78)

    print("\n" + "=" * 96)
    print("逐条看失败的用例")
    print("=" * 96)
    fails = [r for r in rows if not all(r[1:5])]
    if not fails:
        print("  没有失败用例。")
    for c, r_ok, d_ok, ci_ok, a_ok, ans, sc, hits in fails:
        print(f"\n  「{c.q}」（{c.kind}）")
        print(f"    检索到的 top-{K}：")
        for i, (d, s) in enumerate(hits, 1):
            gold = "★" if d.id in c.gold_ids else " "
            print(f"      {gold}[{i}] {s:.3f} [{d.id}] {d.text[:40]}")
        print(f"    答案：{ans}")
        bad = []
        if not r_ok:
            bad.append(f"检索没命中（期望 {c.gold_ids}）")
        if not d_ok:
            bad.append("该拒答却答了")
        if not a_ok:
            bad.append(f"答案缺关键事实 {c.must_contain}")
        print(f"    ← {'；'.join(bad)}")

    print("\n" + "=" * 96)
    print("结论")
    print("=" * 96)
    print("  · **不要只说'RAG 效果不好'。** 要说出是四个数字里的哪一个低。")
    print("  · 检索低 → 修分块/检索（第 9、10 章）；答案低但检索高 → 修生成（第 3 章）")
    print("  · 拒答低 → 修阈值/提示词；引用低 → 修输出格式（第 6 章）")
    print("  · **一次只改一处，改完重跑这四个数**——否则你不知道是谁起的作用。")
    print()
    print("  这就是为什么本书把「评测」拆成第 42、43 章：")
    print("  不是学工具，是学**怎么把'效果不好'变成'第 X 章的哪个问题'**。")

    print("\n" + "=" * 96)
    print("本章小结：RAG 的四个环节 + 四个指标")
    print("=" * 96)
    print("  环节          代码在哪            指标            坏了去哪修")
    print("  " + "-" * 88)
    for a, b, c, d in [
        ("① 分块", "第 9 章", "块大小/重叠", "第 9 章"),
        ("② 检索", "step1 FlatStore", f"Recall@{K}", "第 10 章"),
        ("③ 生成", "step2 extractive_answer", "答案正确率", "第 3 章"),
        ("④ 校验", "step2 check_citations", "拒答率/引用率", "本章"),
    ]:
        print(f"  {a:<14}{b:<20}{c:<16}{d}")

    assert len(rows) == len(CASES)


if __name__ == "__main__":
    main()
