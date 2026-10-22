"""第 56 章 step3：复盘的最后一步——把它变成一条再也绕不过去的用例（离线）。

运行：
    python code/ch55_postmortem/step3_to_eval_case.py

上一级的痛点：复盘写合格了，但它还是一篇文档，不会阻止任何人再犯。

这一级做什么：
  ① 自动分类：从症状文本猜失败类型（只给候选，必须人工确认）
  ② 故障 → 评测用例：生成能直接放进 `evals/` 的结构
  ③ 演示"有没有这条用例"的差别：同一处代码退化，一个被拦、一个漏过去
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.postmortem import (  # noqa: E402
    Evidence,
    FailureType,
    FiveQuestions,
    Postmortem,
    classify,
    to_eval_case,
)

SYMPTOMS = [
    ("退款时效，答成了 15 天，但文档里写的是 7 天", "retrieval"),
    ("TOOL_ERROR: HTTP 503 工具调用失败", "tool"),
    ("429 rate limit exceeded", "infra"),
    ("回答被 BLOCKED，用户说这是正常问题", "guardrail"),
    ("token 超限，前面的对话被截断了", "context"),
    ("模型编造了一个不存在的订单号", "model"),
    ("用户问退款几天，答了个'不知道'", "?"),
]


def incident() -> Postmortem:
    return Postmortem(
        title="退款时效答成 15 天（检索到过期文档）",
        occurred_at="2026-10-12 14:03",
        detected_at="2026-10-12 14:11",
        resolved_at="2026-10-12 15:02",
        severity="P1",
        impact="59 分钟 / 230 次咨询 / 31 次答错",
        failure_type=FailureType.RETRIEVAL,
        five=FiveQuestions(
            q1_how_much_worse="96% → 86.5%",
            q2_which_step="retrieval，top-1 = c8812（旧版）",
            q3_root_cause="索引未剔除旧版 + 无 effective_date",
            q4_fix="时间过滤 + archived 不进索引",
            q5_regression="3 条回归用例 + CI 门禁",
        ),
        evidence=[Evidence("trace", "run_id=9f3ac2e1", "命中 c8812")],
        action_items=[{"action": "补 effective_date", "owner": "wang", "due": "2026-10-15", "status": "done"}],
        new_eval_cases=["退款几天内可申请", "旧版政策是否还会被召回"],
    )


def fake_run(answer: str) -> dict:
    """模拟一次 Agent 运行（只保留评测需要的字段）。"""
    return {"answer": answer}


def check_case(case: dict, run: dict) -> bool:
    """最小的 L1 检查：期望的 must_contain 全部出现才算过。"""
    return all(k in run["answer"] for k in case.get("must_contain", []))


def main() -> None:
    print("=" * 80)
    print("① 自动分类：从症状猜类型（只给候选）")
    print("=" * 80)
    print(f"{'症状':<36}{'自动判定':<12}{'置信度'}")
    print("-" * 80)
    for text, expect in SYMPTOMS:
        ft, conf = classify(text)
        mark = "" if expect == "?" else ("✅" if ft.value == expect else "⚠️")
        print(f"{text:<36}{ft.value:<12}{conf:>6.0%} {mark}")
    print("\n  ⚠️ 最后一条是**故意留的**：'答了个不知道'在分类器眼里信息不足。")
    print("     这时候必须人工看 trace 才能定：是检索没命中？是护栏拦了？还是模型拒答？")
    print("     → 自动分类的作用是'缩小范围'，不是'下结论'。")

    print("\n" + "=" * 80)
    print("② 故障 → 评测用例")
    print("=" * 80)
    case = to_eval_case(incident())
    print(json.dumps(case, ensure_ascii=False, indent=2))
    print("\n  ⚠️ 注意 `must_contain` 是空的：")
    print("     自动转换只能填'问题'和'标签'，**期望答案必须人写**。")
    print("     因为只有人知道'这条问题正确的答案要素是什么'。")

    # 补上人写的期望值，才能真的当门禁用
    case["must_contain"] = ["7 天"]
    print(f"\n  补上期望值后：{case['must_contain']}")

    print("\n" + "=" * 80)
    print("③ 有这条用例 vs 没有这条用例")
    print("=" * 80)
    bad_run = fake_run("根据最新政策，退款需要 15 天内申请。")   # 退化后的错误答案
    print(f"  退化后的答案：{bad_run['answer']}")
    if check_case(case, bad_run):
        print("  没有用例：只能靠用户投诉发现")
    else:
        print("  有用例：❌ 拦截 —— CI 里会红，提交合不进去")
    print("\n  这就是复盘的'价值锚点'：")
    print("    没有它 → 复盘是一次性文章，同样的错换个形式再来")
    print("    有它   → 同一个故障**无法悄悄上线**")

    print("\n" + "=" * 80)
    print("④ 一条用例不够：要把'同族'的问题一起补上")
    print("=" * 80)
    family = ["退款几天内可申请", "无理由退货时效", "价保期是多久", "旧版政策是否还会被召回"]
    print("  这次故障暴露的是'旧文档没剔除'，所以同类问题都可能中招：")
    for q in family:
        print(f"    · {q}")
    print("\n  → 补一条只能防'这一个问法'；补一族才能防'这一类知识'。")

    print("\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    print("  · 复盘的完成标准不是'写完了'，是'评测集多了一条'")
    print("  · 用例的期望值必须人写，机器只能帮你生成壳")
    print("  · 补用例要补一族，不是补一条")


if __name__ == "__main__":
    main()
