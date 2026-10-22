"""框架章共用的离线假模型（不需要 API Key）。

为什么需要它：
    LangChain / LangGraph 的教程一旦绑死真实 API，读者没 key 就跑不了，
    于是所有示例都变成"看着像代码的文本"。本文件提供三个替代品，
    让所有框架示例都能离线跑通：

    ScriptedChat    按剧本依次吐出 AIMessage（可含 tool_calls）
    EchoEmbeddings  确定性假向量（同一段文本永远得到同一个向量）
    run_with_llm()  需要真模型的脚本统一入口（没 key 就跳过，不污染 CI）

注意：
    ScriptedChat 不模拟"模型的能力"，只模拟"模型的接口"。
    它输出什么完全由剧本决定 —— 这正是离线测试要的效果：
    把不确定性去掉，只验证框架接线对不对。
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable, Iterable, Iterator

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk


class ScriptedChat(GenericFakeChatModel):
    """按顺序吐消息的假模型。

    · messages=iter([...])  剧本，每次调用消费一条
    · bind_tools() 直接返回自己（真模型会返回一个绑定了工具的副本）
    · _stream() 自己切块：父类遇到 content="" 且无 additional_kwargs 时
      会"一块也不吐"，LangGraph 的 stream_mode="messages" 就会直接报
      ValueError: No generations found in stream —— 所以这里显式补一块。
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChat":  # noqa: ARG002
        return self

    def _stream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        msg = next(self.messages)
        msg = AIMessage(content=msg) if isinstance(msg, str) else msg

        chunks: list[AIMessageChunk] = []
        if msg.content:
            text = msg.content if isinstance(msg.content, str) else ""
            step = max(1, len(text) // 4)
            for i in range(0, len(text), step):
                chunks.append(AIMessageChunk(content=text[i : i + step]))
        else:
            # 纯工具调用：必须吐至少一块，否则上层拿不到这个 AIMessage
            chunks.append(AIMessageChunk(content=""))

        last = chunks[-1]
        last.tool_calls = msg.tool_calls
        last.tool_call_chunks = [
            {"name": c["name"], "args": json.dumps(c["args"], ensure_ascii=False),
             "id": c["id"], "index": i, "type": "tool_call_chunk"}
            for i, c in enumerate(msg.tool_calls)
        ]
        for c in chunks:
            if run_manager:
                run_manager.on_llm_new_token(str(c.content), chunk=ChatGenerationChunk(message=c))
            yield ChatGenerationChunk(message=c)


def scripted(*messages: AIMessage | str, **kwargs: Any) -> ScriptedChat:
    """`scripted(ai("第一轮"), ai("第二轮"))` 的便捷写法。"""
    return ScriptedChat(messages=iter(list(messages)), **kwargs)


def ai(content: str = "", tool_calls: Iterable[dict] | None = None, **kw: Any) -> AIMessage:
    """造一条 AIMessage；tool_calls 的 id 可省略，自动补。"""
    calls = []
    for i, c in enumerate(tool_calls or []):
        calls.append({"id": c.get("id", f"call_{i + 1}"), "type": "tool_call", **c})
    return AIMessage(content=content, tool_calls=calls, **kw)


class EchoEmbeddings(Embeddings):
    """确定性假嵌入：按字符哈希映射到固定维度，再归一化。

    · 同样的文本永远得到同样的向量（可复现）
    · 同样的字出现得越多，向量在该维度上越大（所以"字面相近"会相似）
    · 它不懂语义 —— 别用它评估检索质量，只用来跑通管线
    """

    def __init__(self, size: int = 16) -> None:
        self.size = size

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.size
        for ch in text:
            h = int(hashlib.md5(ch.encode("utf-8")).hexdigest()[:8], 16)
            v[h % self.size] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [round(x / norm, 6) for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


# ---------------------------------------------------------------- demo_* 守卫
def run_with_llm(main: Callable[[Any], None], model: str = "gpt-4o-mini") -> None:
    """需要真模型的脚本统一入口。

    用法（demo_*_llm.py 末尾）：
        if __name__ == "__main__":
            run_with_llm(run)

    没有 OPENAI_API_KEY 时打印提示并退出（退出码 0，不污染 CI）。
    """
    import os
    import sys

    if not os.getenv("OPENAI_API_KEY"):
        print("跳过：未设置 OPENAI_API_KEY（本脚本演示真实模型行为，离线跑不了）")
        print("设置方式：$env:OPENAI_API_KEY='sk-...'  再重跑")
        sys.exit(0)

    from langchain.chat_models import init_chat_model

    llm = init_chat_model(model, model_provider="openai")
    main(llm)


def text_of(chunk: Any) -> str:
    """从流式 chunk / AIMessage 里取出纯文本（content 可能是 str 或 block 列表）。"""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p["text"] for p in content if isinstance(p, dict) and "text" in p
        )
    return ""


def stream_text(stream: Iterator[Any]) -> Iterator[str]:
    for c in stream:
        t = text_of(c)
        if t:
            yield t
