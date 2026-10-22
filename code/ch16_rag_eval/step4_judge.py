"""第 15 章 step4：加上"引用校验"和"忠实度 judge"，并证明 judge 必须先被校验。

运行：
    python code/ch14_rag_eval/step4_judge.py

上一级的痛点：L1 只能告诉你"材料找到了没有"，不能告诉你"答案有没有编"。
这一级做什么：演示三件事，全部离线可跑：
  1. 引用校验（零成本）怎么抓出"编造来源"
  2. 模拟 judge 的三个偏差长什么样
  3. validate_judge() 怎么判断"这个 judge 能不能用"

[!] 这里用的是**规则模拟的 judge**（按"实词覆盖率"打分），不是真模型。
   目的不是让你相信它的分数，而是让你看清**校验流程**。
   真实 judge 见 demo_eval_llm.py（需要 API key）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.rag_eval import check_citation, extract_citations, validate_judge  # noqa: E402

CONTEXTS = [
    "签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。",
    "定制类商品、生鲜类商品、已激活的数码产品不适用无理由退货。",
]
VALID_IDS = {"c2", "c3"}

ANSWERS = {
    "好答案": "签收后 7 天内、未拆封可申请无理由退货 [c2]。定制商品不适用 [c2]。",
    "编造来源": "签收后 7 天内可以退 [c9]。",
    "不给引用": "7 天内可以退。",
    "编造事实": "签收后 30 天内可以退，而且生鲜也能退 [c2]。",
    "答非所问": "我们的客服很专业，随时为您服务 [c2]。",
}


def _terms(s: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]{2}|\d+|[a-zA-Z]+", s))


def fake_faithfulness(contexts: list[str], answer: str) -> float:
    """规则版 judge：答案里的"实词"有多少能在材料里找到。

    它有三个可复现的已知毛病，正好用来演示 judge 偏差：
      · 只认字面，不认同义（"退" vs "退货"）
      · 答案越长，越容易"蒙中"更多词（长度偏差）
      · 只看到一两段材料时，覆盖率会偏高（上下文偏差）
    """
    got = _terms(answer)
    if not got:
        return 0.0
    pool: set[str] = set()
    for c in contexts:
        pool |= _terms(c)
    return len(got & pool) / len(got)


class RuleJudge:
    """把规则打分包装成 llm.invoke(prompt).content 的形状，好复用 validate_judge。"""

    def invoke(self, prompt: str):
        ctx = prompt.split("【材料】")[-1].split("【答案】")[0]
        ans = prompt.split("【答案】")[-1]
        score = fake_faithfulness([ctx], ans)
        return type("M", (), {"content": json.dumps({"score": score})})()


def main() -> None:
    print("=" * 78)
    print("① L2 引用校验：零成本，抓「编造来源」")
    print("=" * 78)
    print(f"{'答案类型':<10}{'引用':<14}{'校验':<8}答案")
    print("-" * 92)
    for label, ans in ANSWERS.items():
        cites = extract_citations(ans)
        ok = check_citation(ans, cites, VALID_IDS)
        print(f"{label:<10}{str(cites):<14}{'[v] 通过' if ok else '[x] 拦截':<8}{ans}")

    print("\n  结论：引用校验只回答一个问题——「它引用的东西是不是真的检索到了」。")
    print("  它**不能**回答「这段话有没有事实错误」，那是 L3 忠实度的工作。")

    print("\n" + "=" * 78)
    print("② 模拟 judge 打分（看它怎么错）")
    print("=" * 78)
    for label, ans in ANSWERS.items():
        print(f"  {label:<10} faithfulness = {fake_faithfulness(CONTEXTS, ans):.2f}")

    print("\n  注意「编造事实」那条：它混进了正确答案的词，所以分数不低。")
    print("  → 只看分数会漏掉它；真实 judge 还要输出 unsupported 明细给人看。")

    print("\n" + "=" * 78)
    print("③ validate_judge：判断这个 judge 能不能用")
    print("=" * 78)
    # 人工标注：1 = 完全有依据，0.5 = 一半有依据，0 = 基本是编的
    samples = [
        (CONTEXTS, ANSWERS["好答案"], 1.0),
        (CONTEXTS, ANSWERS["编造事实"], 0.5),
        (CONTEXTS, ANSWERS["答非所问"], 0.0),
        (CONTEXTS, ANSWERS["不给引用"], 1.0),
    ]
    result = validate_judge(RuleJudge(), samples, tolerance=0.3)
    for k, v in result.items():
        print(f"  {k:<16}{v if isinstance(v, str) else round(v, 3)}")

    print("\n  这个规则 judge 的一致性不高（它认不出同义改写）——这就是它不该被用的证据。")
    print("  [!] 关键：**先校验，再相信**。没有这一步，后面所有「提升了 X%」都是幻觉。")

    print("\n" + "=" * 78)
    print("这一级解决了什么")
    print("=" * 78)
    print("  · 你现在能回答「答案是不是基于材料」了（L3）")
    print("  · 但 judge 本身有偏，必须先和人工标注对齐（agreement_rate ≥ 0.8）")


if __name__ == "__main__":
    main()
