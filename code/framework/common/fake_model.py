"""一个脚本化的聊天模型：离线、确定、支持工具调用与流式。

卷 6 的所有示例都从这里取模型。它实现的是 `BaseChatModel` 的最小可用部分：
  - `_generate`：按脚本吐出一条 `AIMessage`
  - `bind_tools`：记录工具 schema，并在脚本要求时返回 `tool_calls`
  - `_stream`：把一条消息拆成 chunk，供流式示例使用
  - `with_structured_output`：由基类实现，本类只需正确响应 `bind_tools`

脚本用尽后返回一句固定文本，便于观察"模型没有下一步"的行为。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    """按脚本返回消息的聊天模型。"""

    script: list[AIMessage] = Field(default_factory=list)
    usage: tuple[int, int] = (100, 20)          # (input_tokens, output_tokens)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        """记录工具 schema；脚本里已经写好的 tool_calls 会原样返回。"""
        schemas = []
        for t in tools:
            if isinstance(t, dict):
                schemas.append(t)
            else:
                schemas.append({"name": getattr(t, "__name__", str(t))})
        return self.model_copy(update={"tools": schemas})

    def _next(self) -> AIMessage:
        if self.cursor < len(self.script):
            msg = self.script[self.cursor]
            self.cursor += 1
            return msg
        return AIMessage(content="（脚本用尽，本示例没有更多预设输出）")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        msg = self._next()
        inp, out = self.usage
        msg = msg.model_copy(update={"usage_metadata": {
            "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
        }})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        msg = self._next()
        text = msg.content if isinstance(msg.content, str) else ""
        step = max(1, len(text) // 3 or 1)
        for i in range(0, max(len(text), 1), step):
            piece = text[i:i + step]
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        if msg.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=[
                    {"name": tc["name"], "args": str(tc["args"]), "id": tc["id"], "index": 0}
                    for tc in msg.tool_calls
                ])
            )
