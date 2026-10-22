"""第 5 章 · 第 3 级：混合模式 —— 外层固定，内层放手给 Agent。

运行：
    python code/ch05_workflow/step3_hybrid.py

新增的一个概念：**Workflow with agentic steps**（企业落地最常见的形态）。

外层（固定的三件事）：
  · 接收工单
  · 分类（能用规则就别用模型，省一半钱）
  · 按分类结果选子流程

内层（交给 Agent 的一件事）：
  · "质量问题"这类工单，要查几条政策、查几次订单，事先说不清 —— 所以内层用 ReAct

这样既拿到了"成本有上界、路径可预测"，又拿到了"细节能自适应"。
"""
from __future__ import annotations

from dataclasses import dataclass, field

COMMENT = "收到货发现屏幕有两条划痕，联系客服三次没人回，我要退款，太气人了。"


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


@dataclass
class Ledger:
    calls: int = 0
    tokens: int = 0

    def call(self, prompt: str, out_tokens: int = 100) -> None:
        self.calls += 1
        self.tokens += est_tokens(prompt) + out_tokens


# ---------------------------------------------------------------- 工具（给内层 Agent 用）

POLICIES = {
    "退款": "签收后 7 天内无理由退货，质量问题 30 天内可退。",
    "补偿": "质量问题可申请最高 50 元补偿。",
    "升级": "连续 3 次未响应，必须升级至专员。",
}


def search(args: dict) -> str:
    return POLICIES.get(args.get("q", ""), "未检索到相关内容")


def order(args: dict) -> str:
    return "订单 A12345，签收 2 天，屏幕有划痕（用户描述）"


TOOLS = {"search": search, "order": order}


# ---------------------------------------------------------------- 内层：极简 ReAct

@dataclass
class InnerAgent:
    """一个小 ReAct：最多 4 步，每步选一个工具，拿到结论就停。"""

    ledger: Ledger
    max_steps: int = 4
    script: list[dict] = field(default_factory=list)
    turn: int = 0

    def run(self, question: str) -> dict:
        facts: list[str] = []
        for step in range(self.max_steps):
            pick = self.script[self.turn % len(self.script)]
            self.turn += 1
            self.ledger.call(f"内层第{step + 1}步：{question}")
            if pick.get("done"):
                return {"answer": pick["answer"], "steps": step + 1, "facts": facts}
            facts.append(TOOLS[pick["tool"]](pick["args"]))
        return {"answer": "（达到步数上限，返回已收集信息）", "steps": self.max_steps, "facts": facts}


# ---------------------------------------------------------------- 外层：固定 Workflow

def classify(comment: str, ledger: Ledger) -> str:
    """第一层过滤用纯规则：80% 的工单靠关键词就能分对。"""
    if any(w in comment for w in ("划痕", "坏了", "质量问题", "退款")):
        return "quality"
    if any(w in comment for w in ("物流", "快递", "没收到")):
        return "logistics"
    return "other"


def main() -> None:
    print("=" * 72)
    print("第 3 级：外层固定 + 内层 Agent（混合模式）")
    print("=" * 72)
    print(f"输入：{COMMENT}\n")

    ledger = Ledger()

    # ① 外层：接收 + 分类（纯规则，0 次模型调用）
    kind = classify(COMMENT, ledger)
    print(f"① 分类（规则）→ {kind}    模型调用 {ledger.calls} 次")

    # ② 外层：按分类选子流程
    if kind != "quality":
        print("② 走固定模板回复，结束。")
        return
    print("② 分类为「质量问题」→ 交给内层 Agent 去查")

    # ③ 内层：Agent 自己决定查几次
    agent = InnerAgent(
        ledger=ledger,
        script=[
            {"tool": "order", "args": {}},
            {"tool": "search", "args": {"q": "退款"}},
            {"tool": "search", "args": {"q": "升级"}},
            {"done": True, "answer": "可退（质量问题 30 天内），并升级专员跟进。"},
        ],
    )
    inner = agent.run("这条工单该怎么处理？")
    print(f"③ 内层 Agent 跑了 {inner['steps']} 步，收集到：")
    for f in inner["facts"]:
        print(f"   · {f}")

    # ④ 外层：套模板发出去
    print(f"\n④ 固定模板回复：{inner['answer']}")
    print(f"\n总模型调用：{ledger.calls} 次   token：{ledger.tokens:,}")

    print("\n" + "=" * 72)
    print("这个结构解决了什么")
    print("=" * 72)
    print("  · 外层固定 → 成本有上界（内层最多 4 步，外层永远 2 步）")
    print("  · 外层固定 → 路径可预测（非质量问题根本不会进 Agent）")
    print("  · 内层 Agent → 查几条政策由情况决定，不用你写 8 个 if")
    print("\n  代价：内层的步数仍然抖动，所以必须给它预算（第 3 章的刹车）。")


if __name__ == "__main__":
    main()
