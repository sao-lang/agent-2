"""create_agent 的两种流式：updates 给每一步的增量，messages 给逐 token 的 chunk。

不联网：模型用 langchain_core 的 FakeListChatModel，按固定回复逐字符吐出。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models import FakeListChatModel

MODEL = FakeListChatModel(responses=["签收后 7 天内可退，需保持商品完好。"])
AGENT = create_agent(MODEL, tools=[])
INPUT = {"messages": [{"role": "user", "content": "能退吗？"}]}


def main() -> None:
    print("=== stream_mode='updates'：一步一次增量 ===")
    for step in AGENT.stream(INPUT, stream_mode="updates"):
        for node, payload in step.items():
            for msg in payload.get("messages", []):
                print(f"  {node:10} {type(msg).__name__:16} {msg.content[:26]!r}")

    print("=== stream_mode='messages'：逐 token 的 chunk ===")
    pieces = [chunk.content for chunk, _meta in AGENT.stream(INPUT, stream_mode="messages")]
    print("  拼接   ", "".join(pieces))
    print("  chunk 数", len(pieces))
    print("  前三个 ", pieces[:3])

    print("=== 一次性调用的对照 ===")
    result = AGENT.invoke(INPUT)
    print("  最后一条消息", type(result["messages"][-1]).__name__)


if __name__ == "__main__":
    main()
