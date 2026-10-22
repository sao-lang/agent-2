"""第 17 章示例：原生 tool_calls 版 ReAct（需要 API key）。

运行：
    python code/ch17_react/demo_native_react.py

它和第 16 章的四道刹车接在一起，是本书后续所有 Agent 的基础形态。

关键观察点：
  · 模型一次可能返回多个 tool_calls（并行），你要能处理
  · tool_call_id 必须原样带回，否则下一轮模型对不上号
  · 工具报错要作为**观察结果**回给模型，而不是抛出去让程序崩
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.tools import tool  # noqa: E402

from common import Meter, get_settings, make_llm  # noqa: E402
from common.guards import Budget, LoopGuard  # noqa: E402
from common.react import SafeReAct  # noqa: E402


@tool
def search_docs(query: str) -> str:
    """检索内部知识库。query 用中文关键词。"""
    db = {
        "退款": "退款政策：签收后 7 天内无理由退货，15 天内可换货，运费由买家承担。",
        "运费": "运费规则：单笔满 99 元包邮；不满 99 元收 10 元；新疆西藏另加 15 元。",
        "发票": "发票：下单时可申请电子普票，7 个工作日后发送到邮箱。",
    }
    hits = [v for k, v in db.items() if k in query]
    return "\n".join(hits) if hits else "未检索到相关内容"


@tool
def calc_shipping(amount: float, region: str = "普通地区") -> str:
    """计算运费。amount 是订单金额（元），region 可选 普通地区/新疆/西藏。"""
    if amount >= 99:
        return "包邮"
    fee = 10 + (15 if region in ("新疆", "西藏") else 0)
    return f"需付运费 {fee} 元"


def main() -> None:
    s = get_settings()
    if s.api_key in ("missing", ""):
        print("❌ 需要 API key。请复制 .env-example 为 .env 并填入配置。")
        print("   如果只想看 ReAct 的结构与脆弱点，请用（离线）：")
        print("   python code/ch17_react/demo_text_react.py")
        return

    meter = Meter()
    llm = make_llm()

    agent = SafeReAct(
        llm=llm,
        tools=[search_docs, calc_shipping],
        budget=Budget(max_steps=8, max_tokens=40_000, max_cost=0.05),
        guard=LoopGuard(max_repeats=2),
    )

    questions = [
        "买了 80 块钱的东西寄到新疆，要付多少运费？",
        "退款能退几天？运费谁承担？",  # 多跳：需要检索两次

    ]
    for q in questions:
        print(f"\n{'=' * 62}\n问题：{q}\n{'=' * 62}")
        with meter.track(s.model, step="react") as rec:
            r = agent.run(q)
            rec.input_tokens = 0  # 这里由 agent 内部预算统计，meter 只做兜底
        print(f"回答：{r['answer']}")
        print(f"步数：{r['steps']}  成本：¥{r.get('cost', 0)}  停止原因：{r['stop_reason']}")

    print("\n" + "=" * 62)
    print("👉 观察：'多跳问题'消耗的步数明显更多——这就是 ReAct 的成本特征。")
    print("   第 19 章的 Plan-and-Execute 会用另一种方式处理多跳，对比一下。")


if __name__ == "__main__":
    main()
