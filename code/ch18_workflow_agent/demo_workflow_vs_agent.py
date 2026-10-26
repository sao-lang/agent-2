"""第 19 章示例：同一任务，Agent 版 vs Workflow 版，跑出对比数字。

运行：
    python code/ch18_workflow_agent/demo_workflow_vs_agent.py

不需要 API key：两边都用同一个"假模型"决策，保证对比的是**架构**而不是模型随机性。

任务：给定一段商品评论，产出"是否退款 + 理由 + 是否升级"三件事。
这是一个典型的**步骤确定**任务，正好用来证明"这种活不该交给 Agent"。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402


COMMENT = "收到货发现屏幕有两条划痕，联系客服三次没人回，我要退款，太气人了。"


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


# ============================================================ 假模型

class FakeModel:
    """记录调用次数与 token，模拟"每次调用都要花钱"。"""

    def __init__(self) -> None:
        self.calls = 0
        self.tokens = 0

    def __call__(self, prompt: str, out_tokens: int = 120) -> str:
        self.calls += 1
        self.tokens += est_tokens(prompt) + out_tokens
        return f"<模型输出#{self.calls}>"


# ============================================================ Workflow 版

class WFState(TypedDict, total=False):
    comment: str
    need_refund: bool
    reason: str
    escalate: bool
    reply: str


def wf_classify(state: WFState, m: FakeModel) -> WFState:
    m("分类 prompt " + state["comment"])
    txt = state["comment"]
    return {
        "need_refund": "退款" in txt or "划痕" in txt,
        "escalate": "三次" in txt or "气" in txt,
    }


def wf_reason(state: WFState, m: FakeModel) -> WFState:
    m("理由抽取 prompt " + state["comment"])
    return {"reason": "商品有质量瑕疵，且客服未及时响应"}


def wf_reply(state: WFState, m: FakeModel) -> WFState:
    m("回复生成 prompt")
    return {"reply": "已为您发起退款，并升级至专员跟进。"}


def build_workflow(m: FakeModel):
    g = StateGraph(WFState)
    g.add_node("classify", lambda s: wf_classify(s, m))
    g.add_node("reason", lambda s: wf_reason(s, m))
    g.add_node("reply", lambda s: wf_reply(s, m))

    g.add_edge(START, "classify")

    # 条件边：只有需要退款才抽理由（这就是"确定性"的价值——不多做一步）
    g.add_conditional_edges(
        "classify",
        lambda s: "reason" if s["need_refund"] else "reply",
        {"reason": "reason", "reply": "reply"},
    )
    g.add_edge("reason", "reply")
    g.add_edge("reply", END)
    return g.compile()


# ============================================================ Agent 版

def run_agent_like(m: FakeModel, max_steps: int = 8) -> dict[str, Any]:
    """模拟一个 ReAct Agent 做同一件事。

    它会怎么走？我们可以预测：模型看一步、决定下一步、再确认……
    真实情况里步数会抖动，这里用"固定但更多"的步数模拟这种不确定性。
    """

    steps = 0
    # 1. 思考要不要退款
    m("agent: 这个评论需要处理吗？ " + COMMENT)
    steps += 1
    # 2. 决定调用"抽理由"工具
    m("agent: 应该抽理由吗？")
    steps += 1
    # 3. 抽理由
    m("agent: 抽取理由")
    steps += 1
    # 4. 决定要不要升级
    m("agent: 是否需要升级？")
    steps += 1
    # 5. 生成回复
    m("agent: 生成回复")
    steps += 1
    # 6. 自我检查：回复是否覆盖了所有点
    m("agent: 检查我的回复是否完整")
    steps += 1

    return {"steps": steps, "reply": "已为您发起退款，并升级至专员跟进。"}


# ============================================================ 对照

def main() -> None:
    print("=" * 66)
    print("任务：评论 → 是否退款 / 理由 / 是否升级 / 回复")
    print(f"输入：{COMMENT}")
    print("=" * 66)

    # --- Workflow ---
    wf_model = FakeModel()
    app = build_workflow(wf_model)
    wf_out = app.invoke({"comment": COMMENT})

    print("\n【Workflow 版】")
    print("  路径固定：classify → (condition) → reason → reply")
    print(f"  结果：need_refund={wf_out['need_refund']} escalate={wf_out['escalate']}")
    print(f"  模型调用：{wf_model.calls} 次   token：{wf_model.tokens:,}")

    # --- Agent ---
    ag_model = FakeModel()
    ag_out = run_agent_like(ag_model)

    print("\n【Agent 版】")
    print("  路径动态：模型每步自己决定")
    print(f"  结果：{ag_out['reply']}")
    print(f"  模型调用：{ag_model.calls} 次   token：{ag_model.tokens:,}")

    print("\n" + "=" * 66)
    print("对比")
    print("=" * 66)
    print(f"{'':<14}{'模型调用':>10}{'token':>12}{'输出可预测':>12}{'可调试':>10}")
    print("-" * 58)
    print(f"{'Workflow':<14}{wf_model.calls:>10}{wf_model.tokens:>12,}{'是':>12}{'是':>10}")
    print(f"{'Agent':<14}{ag_model.calls:>10}{ag_model.tokens:>12,}{'否':>12}{'较难':>10}")
    print(
        f"\n成本倍数：{(ag_model.tokens / wf_model.tokens):.2f}x"
        f"（Agent 多花 {ag_model.tokens - wf_model.tokens:,} token）"
    )
    print("\n👉 这个任务**每一步都是确定的**，用 Agent 只是把'你写的 if'换成了'模型猜的 if'。")
    print("   代价是多花一倍钱，换来一个更难预测、更难调试的流程。")


if __name__ == "__main__":
    main()
