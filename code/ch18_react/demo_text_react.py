"""第 18 章示例：手写 ReAct 文本解析版（不需要 API）。

运行：
    python code/ch18_workflow_agent/demo_text_react.py

它用一个"脚本化的假模型"演示 ReAct 循环，
并且故意让它**输出格式错误**，让你看见手写 ReAct 最脆弱的地方。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.react import TextReAct  # noqa: E402


# ---------- 假工具 ----------

def search(args: dict) -> str:
    """按关键词检索内部文档"""
    q = args.get("q", "")
    db = {
        "退款": "退款政策：签收后 7 天内无理由退货，15 天内可换货。",
        "运费": "运费规则：满 99 元包邮，偏远地区除外。",
    }
    for k, v in db.items():
        if k in q:
            return v
    return "未检索到相关内容"


def calc(args: dict) -> str:
    """计算运费"""
    amount = args.get("amount", 0)
    return "包邮" if amount >= 99 else f"需付运费 {10} 元"


TOOLS = {"search": search, "calc": calc}


class ScriptedLLM:
    """按脚本返回，模拟模型的三种表现：正常、格式跑偏、直接给答案。"""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.i = 0

    def __call__(self, prompt: str) -> str:
        out = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return out


def main() -> None:
    print("=" * 62)
    print("场景 A：模型完全守格式（理想情况）")
    print("=" * 62)
    a = TextReAct(
        llm_call=ScriptedLLM([
            "Thought: 需要查退款政策\nAction: search\nAction Input: {\"q\": \"退款\"}",
            "Thought: 知道了\nFinal Answer: 签收后 7 天内无理由退货，15 天内可换货。",
        ]),
        tools=TOOLS,
    )
    r = a.run("退款政策是什么？")
    print(f"\n结果：ok={r['ok']} steps={r['steps']} answer={r['answer']}")

    print("\n" + "=" * 62)
    print("场景 B：模型把 Action Input 写成自然语言（最常见的失败）")
    print("=" * 62)
    b = TextReAct(
        llm_call=ScriptedLLM([
            "Thought: 我需要查一下退款相关的资料。\nAction: search\nAction Input: 查询退款政策",
            "Thought: 还不够，再查一次\nAction: search\nAction Input: 退款",
            "Thought: 知道了\nFinal Answer: 签收后 7 天内无理由退货。",
        ]),
        tools=TOOLS,
    )
    r = b.run("退款政策是什么？")
    print(f"\n结果：ok={r['ok']} steps={r['steps']}")
    print("\n👉 注意第 0 步：Action Input 不是 JSON，被当成 {'_raw': '查询退款政策'} 传进工具，")
    print("   工具收不到 q，返回'未检索到'。模型白白浪费了一整轮。")

    print("\n" + "=" * 62)
    print("场景 C：模型不写 Action，直接在正文里说要做的事")
    print("=" * 62)
    c = TextReAct(
        llm_call=ScriptedLLM([
            "我想先搜索一下退款政策，然后再给你答案。",
            "Thought: 好的，守格式\nAction: search\nAction Input: {\"q\": \"退款\"}",
            "Thought: 知道了\nFinal Answer: 签收后 7 天内无理由退货。",
        ]),
        tools=TOOLS,
    )
    r = c.run("退款政策是什么？")
    print(f"\n结果：ok={r['ok']} steps={r['steps']}")

    print("\n" + "=" * 62)
    print("结论")
    print("=" * 62)
    print("手写 ReAct 的三个结构性脆弱点：")
    print("  1. 参数靠字符串解析 → 模型一写自然语言就失效（场景 B）")
    print("  2. 动作靠正则匹配 → 模型忘写 Action 就白跑一轮（场景 C）")
    print("  3. 失败不报错、只是'浪费一轮' → 故障是静默的，很难发现")
    print("\n这就是为什么现代做法改用原生 tool_calls：把'解析'交给协议，而不是给正则。")


if __name__ == "__main__":
    main()
