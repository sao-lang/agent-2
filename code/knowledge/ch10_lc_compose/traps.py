"""三个默认行为造成的坑：编程错误被当成故障、被重试、被当成类型错。

没有 API key：这里的模型只用脚本化后端或干脆不用模型。
**原理演示，不是模型实测。**

从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/traps.py
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda

import httpx

from scripted_chat import chat_completion, scripted_chat


def fallback_on_code_error() -> None:
    """with_fallbacks 默认接所有异常，编程错误也会被当成故障切走。"""
    primary = RunnableLambda(lambda x: x["missing"])          # 一定是 KeyError
    chain = primary.with_fallbacks([RunnableLambda(lambda x: "备用接住了")])
    print("== with_fallbacks 接住了 KeyError ==")
    print("输出：", chain.invoke({}))
    print("主路的错误没有出现在返回值里，只留在回调里。")
    print()


def retry_on_code_error() -> None:
    """with_retry 默认也接所有异常，编程错误会被重试到次数用完。"""
    calls = {"n": 0}

    def boom(x):
        calls["n"] += 1
        raise TypeError("编程错误")

    chain = RunnableLambda(boom).with_retry(stop_after_attempt=3,
                                            wait_exponential_jitter=False)
    print("== with_retry 重试 TypeError ==")
    try:
        chain.invoke({})
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    print(f"  尝试次数：{calls['n']}（一次输入，三次调用）")
    print()


def history_as_string() -> None:
    """MessagesPlaceholder 要的是一串消息对象，给字符串会当场报错。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。"),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ])
    print("== history 传字符串 ==")
    try:
        prompt.format_messages(history="我上周买的能退吗", question="能退吗？")
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    print()


def fallback_keeps_bad_output() -> None:
    """兜底只保证有返回，不保证返回对：两条路都返回同一句话时看不出来。"""
    def broken_uplink(index: int, body: dict):
        return httpx.Response(500, json={"error": {"message": "upstream"}})

    primary = scripted_chat(broken_uplink)
    backup = scripted_chat(lambda index, body: chat_completion("备用模型：符合退货条件。"))
    chain = primary.with_fallbacks([backup])

    print("== 兜底成功后，调用方看到的是什么 ==")
    out = chain.invoke("订单 A1001 能退吗")
    print(f"  返回 {type(out).__name__}，content={out.content!r}")
    print(f"  response_metadata 里的 model_name={out.response_metadata.get('model_name')!r}")
    print("  从返回值能认出这是备用模型的回答，前提是备用模型的输出形态不同；")
    print("  如果两条路都只回一句话，调用方与日志都分不出是哪条路给的。")


def main() -> None:
    fallback_on_code_error()
    retry_on_code_error()
    history_as_string()
    fallback_keeps_bad_output()


if __name__ == "__main__":
    main()
