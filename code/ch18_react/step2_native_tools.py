"""第 18 章 · 第 2 级：原生 tool_calls —— 让协议替你解析。

运行：
    python code/ch18_workflow_agent/step2_native_tools.py

这一级只改一件事：动作和参数不再靠正则解析，而是模型直接返回值里的结构化字段。

为了离线可跑，这里用"假模型"返回与真实 OpenAI 协议同构的 tool_calls 结构。
跑真实模型时只需换成 `llm.bind_tools(tools).invoke(messages)`，
循环逻辑一个字都不用改 —— 这正是"协议比文本可靠"的意思。
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------- 工具

def search(args: dict) -> str:
    q = args.get("q", "")
    if q == "退款":
        return "退款政策：签收后 7 天内无理由退货，15 天内可换货。"
    return "未检索到相关内容"


TOOLS = {"search": search}


# ---------------------------------------------------------------- 假模型

@dataclass
class Reply:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class FakeToolCallingModel:
    """按剧本依次吐出"模型的回答"，结构与真实 API 一致。

    真实 API 返回的是 AIMessage，字段和这里一样：
        Reply(content="", tool_calls=[{"name": "search", "args": {"q": "退款"}, "id": "call_1"}])
    注意 args 是**已经解析好的字典**，不是待解析的字符串。
    """

    script: list[Reply]
    turn: int = 0

    def invoke(self, messages: list[dict]) -> Reply:
        out = self.script[min(self.turn, len(self.script) - 1)]
        self.turn += 1
        return out


# ---------------------------------------------------------------- 主循环

def react(llm, tools: dict, question: str, max_steps: int = 6) -> dict:
    messages: list[dict] = [{"role": "user", "content": question}]

    for step in range(max_steps):
        ai = llm.invoke(messages)
        messages.append(ai)                       # ① 先把模型说的话记进历史

        if not ai.tool_calls:                     # ② 没有工具调用 = 明确的结束信号
            return {"ok": True, "steps": step + 1, "answer": ai.content}

        for call in ai.tool_calls:                # ③ 一次可能多个，必须循环
            fn = tools.get(call["name"])
            result = fn(call["args"]) if fn else f"错误：没有名为 {call['name']} 的工具"
            messages.append({
                "role": "tool",
                "content": str(result),
                "tool_call_id": call["id"],        # ④ 必须带回，否则对不上号
            })

    return {"ok": False, "steps": max_steps, "answer": ""}


def main() -> None:
    # 剧本 A：模型规规矩矩调用工具，然后给答案
    good = FakeToolCallingModel([
        Reply(tool_calls=[{"name": "search", "args": {"q": "退款"}, "id": "call_1"}]),
        Reply(content="签收后 7 天内无理由退货，15 天内可换货。"),
    ])

    print("=" * 66)
    print("场景 A：正常的一次 ReAct 循环")
    print("=" * 66)
    r = react(good, TOOLS, "我的耳机能退吗？")
    print(f"ok={r['ok']} steps={r['steps']}")
    print(f"answer={r['answer']}")

    # 剧本 B：模型一次要并行调两个工具（查退款 + 查运费）
    multi = FakeToolCallingModel([
        Reply(tool_calls=[
            {"name": "search", "args": {"q": "退款"}, "id": "call_a"},
            {"name": "search", "args": {"q": "运费"}, "id": "call_b"},
        ]),
        Reply(content="退款 7 天，运费不退。"),
    ])

    print("\n" + "=" * 66)
    print("场景 B：模型一次返回两个 tool_calls（并行意图）")
    print("=" * 66)
    r = react(multi, TOOLS, "能退吗？运费退吗？")
    print(f"ok={r['ok']} steps={r['steps']}")
    print(f"answer={r['answer']}")
    print("\n👉 注意：两个调用被依次处理，但都带回了自己的 tool_call_id。")
    print("   如果只处理 tool_calls[0]，第二个调用会被静默丢弃。")

    # 剧本 C：对比 —— 参数写错时，协议会直接报错，而不是静默失败
    print("\n" + "=" * 66)
    print("场景 C：为什么协议比文本可靠")
    print("=" * 66)
    print("  文本 ReAct：Action Input 写成自然语言 → json.loads 失败 → 退回 {'_raw': ...}")
    print("             → 工具收到错误参数 → 返回'未检索到' → 模型以为查到了（静默失败）")
    print("  原生 tool_calls：args 已经是结构化字典 → 参数类型不对时，API 层就拒绝")
    print("             → 你当场知道错了（显式报错）")
    print("\n  👉 一句话：文本解析只会默默变差，协议会当场报错。")


if __name__ == "__main__":
    main()
