"""batch / abatch 一次提交多个输入；cache 让同一份请求第二次不再走到模型。

不联网：模型用 langchain_core 的 FakeListChatModel，按固定回复依次回放。
"""

from __future__ import annotations

import asyncio
import time

from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from langchain_core.language_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda

MODEL = FakeListChatModel(responses=["第一次", "第二次"])
SLEEP = {"a": 0.30, "b": 0.10, "c": 0.20}
DONE: list[str] = []


def slow(text: str) -> str:
    """每个输入的耗时不同，用来观察完成顺序。"""
    time.sleep(SLEEP[text])
    DONE.append(text)
    return text.upper()


def show_cache() -> None:
    """同一份请求第二次命中缓存，模型不再被调用一次。"""
    set_llm_cache(InMemoryCache())
    print("同一问题第 1 次：", MODEL.invoke("能退吗？").content)
    print("同一问题第 2 次：", MODEL.invoke("能退吗？").content)
    print("换一个问题    ：", MODEL.invoke("多久到？").content)


def show_batch() -> None:
    step = RunnableLambda(slow)

    DONE.clear()
    got = step.batch(["a", "b", "c"], config={"max_concurrency": 3})
    print("batch 结果（按输入顺序）：", got, "完成顺序：", DONE.copy())

    DONE.clear()
    got_async = asyncio.run(step.abatch(["a", "b", "c"]))
    print("abatch 结果（按输入顺序）：", got_async, "完成顺序：", DONE.copy())

    DONE.clear()
    serial = [step.invoke(x) for x in ["a", "b", "c"]]
    print("逐个 invoke 结果：", serial, "完成顺序：", DONE.copy())


if __name__ == "__main__":
    show_cache()
    show_batch()
