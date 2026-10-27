"""排查"忘"的第一步：把这次请求的完整 messages 打出来。

"忘"不是模型的状态问题，是调用方的装配问题。四种情形（历史被裁剪、检索没命中、
换了会话、工具结果没回灌）在 messages 数组里各有形状，所以先看数组。

不联网。两组 messages 都是手工构造的，用来演示"装配完整"与"漏了一条"的区别。
"""

from __future__ import annotations

TOOL_CALLS = [
    {
        "id": "call_abc",
        "type": "function",
        "function": {"name": "get_order", "arguments": '{"order_id": "A1001"}'},
    }
]

SYSTEM = {"role": "system", "content": "你是退货客服，只回答与退货相关的问题。"}
ASK = {"role": "user", "content": "订单 A1001 能退吗？"}
CALL = {"role": "assistant", "content": None, "tool_calls": TOOL_CALLS}
RESULT = {"role": "tool", "tool_call_id": "call_abc",
          "content": '{"order_id": "A1001", "signed_days_ago": 3, "opened": false}'}
FOLLOW_UP = {"role": "user", "content": "那退货运费谁出？"}

COMPLETE = [SYSTEM, ASK, CALL, RESULT, FOLLOW_UP]
MISSING_RESULT = [SYSTEM, ASK, CALL, FOLLOW_UP]


def dump_messages(messages: list[dict]) -> None:
    """排查"忘"的第一步：这次请求里到底有什么。"""
    print(f"共 {len(messages)} 条消息")
    for i, m in enumerate(messages):
        content = m.get("content") or ""
        role = m.get("role")
        print(f"[{i}] {role:<9} {len(content):>6} 字  {content[:40]!r}...")

        if m.get("tool_calls"):
            print(f"      tool_calls: {[t['function']['name'] for t in m['tool_calls']]}")
        if role == "tool":
            print(f"      tool_call_id: {m.get('tool_call_id')}")


def main() -> None:
    print("=== 装配完整 ===")
    dump_messages(COMPLETE)
    print()
    print("=== 工具结果没回灌 ===")
    dump_messages(MISSING_RESULT)
    print()
    print("两组的差别只有一条：role=tool 的那条消息在不在。")
    print("它不在时，[2] 仍是一条要调工具的 assistant 消息，紧接着就是新的提问，中间没有任何执行结果。")


if __name__ == "__main__":
    main()
