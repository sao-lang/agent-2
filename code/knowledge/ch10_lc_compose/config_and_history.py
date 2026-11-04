"""config 不进业务签名：tags、metadata、callbacks 都从外层注入；
会话历史用 RunnableWithMessageHistory 托住，靠 session_id 区分。

不联网：模型用 langchain_core 的 FakeListChatModel。
"""

from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.language_models import FakeListChatModel
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory

MODEL = FakeListChatModel(responses=["已记录", "你叫小林"])


class TagPrinter(BaseCallbackHandler):
    """把这次运行带的 tags 打出来：它们没有出现在任何函数签名里。"""

    def on_chain_start(self, serialized, inputs, *, run_id, tags=None, metadata=None, **kwargs):
        name = (serialized or {}).get("name") or "lambda"
        print(f"  链开始 {name:24} tags={tags}")


def whoami(text: str, config: RunnableConfig) -> str:
    """业务函数只多一个 config 参数，租户与请求号都从 config 里取。"""
    metadata = config.get("metadata", {})
    return f"{text}（租户={metadata.get('tenant')}，请求={metadata.get('request_id')}）"


def show_config() -> None:
    step = RunnableLambda(whoami).with_config({"tags": ["stage:triage"]})
    out = step.invoke(
        "订单 A1001",
        config={
            "callbacks": [TagPrinter()],
            "tags": ["run:demo"],
            "metadata": {"tenant": "t-07", "request_id": "r-9"},
        },
    )
    print("  返回值：", out)


def show_history() -> None:
    store: dict[str, InMemoryChatMessageHistory] = {}

    def history_of(session_id: str) -> InMemoryChatMessageHistory:
        store.setdefault(session_id, InMemoryChatMessageHistory())
        return store[session_id]

    chat = RunnableWithMessageHistory(MODEL, history_of)
    for text in ["我叫小林", "我叫什么？"]:
        reply = chat.invoke(text, config={"configurable": {"session_id": "u1"}})
        print(f"  {text} -> {reply.content}")
    print("  会话 u1 的历史条数：", len(history_of("u1").messages))
    print("  另一会话 u2 的历史条数：", len(history_of("u2").messages))


if __name__ == "__main__":
    print("=== config 的注入 ===")
    show_config()
    print("=== 会话历史 ===")
    show_history()
