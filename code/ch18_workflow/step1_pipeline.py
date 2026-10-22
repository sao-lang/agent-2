"""第 18 章 · 第 1 级：最朴素的 Workflow —— 一个函数接一个函数。

运行：
    python code/ch18_workflow/step1_pipeline.py

这一级没有任何框架、没有图、没有模型。
它只证明一件事：**当步骤能预先写出来时，最便宜的方案就是直接写出来。**
"""
from __future__ import annotations

from dataclasses import dataclass, field

COMMENT = "收到货发现屏幕有两条划痕，联系客服三次没人回，我要退款，太气人了。"


def est_tokens(text: str) -> int:
    cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cn * 0.7 + (len(text) - cn) / 4) + 1


@dataclass
class Ledger:
    """记下每次模型调用，用来和 Agent 版对比。"""

    calls: int = 0
    tokens: int = 0
    trace: list[str] = field(default_factory=list)

    def call(self, label: str, prompt: str, out_tokens: int = 100) -> str:
        self.calls += 1
        self.tokens += est_tokens(prompt) + out_tokens
        self.trace.append(label)
        return f"<{label}的输出>"


# ---------------------------------------------------------------- 三个步骤

def classify(comment: str, m: Ledger) -> dict:
    """第 1 步：判断要不要退款、要不要升级。"""
    m.call("分类", "判断这条评论是否需要退款：" + comment)
    return {
        "need_refund": "退款" in comment or "划痕" in comment,
        "escalate": "三次" in comment or "气" in comment,
    }


def extract_reason(comment: str, m: Ledger) -> str:
    """第 2 步：抽取退款理由。"""
    m.call("抽理由", "抽取退款理由：" + comment)
    return "商品有质量瑕疵，且客服未及时响应"


def gen_reply(reason: str, escalate: bool, m: Ledger) -> str:
    """第 3 步：生成回复。"""
    m.call("生成回复", f"根据理由生成回复（升级={escalate}）：{reason}")
    tail = "并升级至专员跟进" if escalate else ""
    return f"已为您发起退款{('，' + tail) if tail else ''}。"


# ---------------------------------------------------------------- 主流程

def handle(comment: str, m: Ledger) -> dict:
    """整个流程就是这三行 —— 这就是 Workflow 的全部。"""
    cls = classify(comment, m)
    if not cls["need_refund"]:                       # ← 你的代码在做判断
        return {"reply": "感谢反馈，已记录。", "flow": ["分类", "回复"]}
    reason = extract_reason(comment, m)
    reply = gen_reply(reason, cls["escalate"], m)
    return {"reply": reply, "flow": ["分类", "抽理由", "生成回复"]}


def main() -> None:
    print("=" * 66)
    print("第 1 级：手写管线")
    print("=" * 66)
    print(f"输入：{COMMENT}\n")

    for title, text in [
        ("需要退款的评论", COMMENT),
        ("不需要退款的评论", "快递很快，包装完好，谢谢。"),
    ]:
        m = Ledger()
        out = handle(text, m)
        print(f"【{title}】")
        print(f"  实际路径：{' → '.join(out['flow'])}")
        print(f"  回复：{out['reply']}")
        print(f"  模型调用：{m.calls} 次  token：{m.tokens}\n")

    print("观察两件事：")
    print("  ① 路径由 if 决定 —— 不需要退款时，抽理由那一步根本不会被调用")
    print("  ② 同样的输入，永远走同样的路径，成本可预测")
    print("\n👉 这就是 Workflow 的全部价值：把不确定性挤出去。")


if __name__ == "__main__":
    main()
