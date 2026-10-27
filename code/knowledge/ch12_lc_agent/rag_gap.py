"""12.7 过渡：agent 答不出自家文档。

从仓库根目录运行：
    python code/knowledge/ch12_lc_agent/rag_gap.py
"""

import json

from langchain.agents import create_agent
from langchain_core.tools import tool

from scripted_chat import chat_completion, scripted_chat, tool_call

DOCS = [
    ("policy-2024#3", "退货政策：签收后 7 天内，未拆封可退。"),
    ("policy-2025#1", "价格保护：付款后 15 天内降价可补差。"),
    ("sop#7", "退款到账时间：原路退回，3 到 5 个工作日。"),
]


@tool
def search_policy(query: str) -> str:
    """按关键词在内部政策库里检索，返回命中的段落与出处。"""
    hits = [{"source": source, "text": text}
            for source, text in DOCS if any(word in text for word in query.split())]
    return json.dumps(hits, ensure_ascii=False)


def no_retrieval(i, body):
    """没有检索工具时，模型只能凭训练数据给一个数。"""
    if i == 0:
        return chat_completion(content="我们的退货窗口是 7 天。", usage=(96, 14))
    return chat_completion(content="好的")


def with_retrieval(i, body):
    if i == 0:
        return chat_completion(finish_reason="tool_calls", usage=(110, 20),
                               tool_calls=[tool_call("search_policy",
                                                     {"query": "退货 窗口"}, "c1")])
    return chat_completion(content="按 policy-2024#3：签收后 7 天内、未拆封可退。",
                           usage=(168, 24))


def test_without_retrieval() -> None:
    print("=== 只有订单工具，没有检索")
    seen = {}

    def capture(i, body):
        seen["input"] = [m["content"] for m in body["messages"]]
        return no_retrieval(i, body)

    @tool
    def get_order(order_id: str) -> str:
        """按订单号查签收天数。"""
        return '{"order_id": "A1001", "days_since_delivery": 3}'

    agent = create_agent(model=scripted_chat(capture), tools=[get_order])
    out = agent.invoke({"messages": [{"role": "user", "content": "我们退货窗口几天"}]})
    print("  模型收到的内容:", seen["input"])
    print("  答复:", out["messages"][-1].content)
    print("  答复里的出处:", "无")


def test_with_retrieval() -> None:
    print("\n=== 加一个检索工具")
    agent = create_agent(model=scripted_chat(with_retrieval), tools=[search_policy])
    out = agent.invoke({"messages": [{"role": "user", "content": "我们退货窗口几天"}]})
    for message in out["messages"]:
        print(f"  {type(message).__name__:<14}{str(message.content)[:70]!r}")
    usage = [m.usage_metadata for m in out["messages"]
             if type(m).__name__ == "AIMessage" and m.usage_metadata]
    print("  两次模型调用的 token:", [(u["input_tokens"], u["output_tokens"]) for u in usage])


if __name__ == "__main__":
    test_without_retrieval()
    test_with_retrieval()
