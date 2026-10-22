"""第 4 章 · 第 1 级：ReAct 的原始形态 —— 把"想、做、看"拼成一段文本，再解析回来。

运行：
    python code/ch04_react/step1_text_react.py

这一级要让你看清一件事：
  ReAct 不是什么神秘框架，它就是"把格式约定写进 prompt，再用正则把答案抠出来"。

2022 年的 ReAct 论文就是这个做法。它当年是突破，现在是被淘汰的做法。
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------- 工具

def search(args: dict) -> str:
    """按关键词检索退款政策。"""
    q = args.get("q", "")
    if q == "退款":
        return "退款政策：签收后 7 天内无理由退货，15 天内可换货。"
    return "未检索到相关内容"


TOOLS = {"search": search}


# ---------------------------------------------------------------- 提示词

REACT_PROMPT = """你是一个会使用工具的助手。请严格按下面的格式回答。

可用工具：
{tools}

格式（不要输出任何多余内容）：
Thought: 你的思考
Action: 工具名
Action Input: 工具参数的 JSON

知道答案后：
Thought: 我已经知道答案了
Final Answer: 你的最终回答

问题：{question}
{history}"""


# ---------------------------------------------------------------- 解析

def parse(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------- 主循环

def run(script: list[str], question: str = "我的耳机能退吗？") -> dict:
    """script 是"模型每轮会输出的文本"。用脚本代替真实模型，保证可复现。"""
    history = ""
    for step, raw in enumerate(script):
        print(f"\n--- 第 {step} 轮，模型原文 ---")
        print(raw)

        if "Final Answer:" in raw:
            answer = raw.split("Final Answer:", 1)[1].strip()
            return {"ok": True, "steps": step + 1, "answer": answer}

        action = parse(raw, r"Action:\s*(.+)")
        raw_input = parse(raw, r"Action Input:\s*(.+)")
        if not action:
            history += f"\n{raw}\nObservation: 格式错误，请严格使用 Thought/Action 格式。\n"
            print("  → 没匹配到 Action:，追加一条纠正提示，白花一轮")
            continue

        if raw_input is None:
            print("  → 没匹配到 Action Input:，参数为空")
            args: dict = {}
        else:
            try:
                import json

                args = json.loads(raw_input)
            except json.JSONDecodeError:
                args = {"_raw": raw_input}
                print(f"  → Action Input 不是 JSON，退回 {args}")

        obs = TOOLS[action](args) if action in TOOLS else f"错误：没有名为 {action} 的工具"
        print(f"  → Observation: {obs}")
        history += f"\n{raw}\nObservation: {obs}\n"

    return {"ok": False, "steps": len(script), "answer": ""}


def main() -> None:
    print("=" * 66)
    print("场景 A：模型完全守格式（理想情况）")
    print("=" * 66)
    r = run([
        'Thought: 需要查退款政策\nAction: search\nAction Input: {"q": "退款"}',
        "Thought: 知道了\nFinal Answer: 签收后 7 天内无理由退货，15 天内可换货。",
    ])
    print(f"\n结果：ok={r['ok']} steps={r['steps']} answer={r['answer']}")

    print("\n" + "=" * 66)
    print("场景 B：Action Input 写成自然语言（最常见的失败）")
    print("=" * 66)
    r = run([
        "Thought: 我需要查一下退款相关的资料。\nAction: search\nAction Input: 查询退款政策",
        "Thought: 还不够，再查一次\nAction: search\nAction Input: 退款",
        "Thought: 知道了\nFinal Answer: 签收后 7 天内无理由退货。",
    ])
    print(f"\n结果：ok={r['ok']} steps={r['steps']}")
    print("\n👉 第 0 轮白白浪费：Action Input 不是 JSON，工具收不到 q，返回'未检索到'。")
    print("   而且模型不知道自己错了 —— Observation 看起来是个正常返回。")


if __name__ == "__main__":
    main()
