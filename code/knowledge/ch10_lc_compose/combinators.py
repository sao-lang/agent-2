"""七个组合子，每个跑一次并打印真实输出。

没有 API key：模型换成本地脚本化后端，**原理演示，不是模型实测**。
接真实服务时把 scripted_chat(respond) 换成 ChatOpenAI(model=..., api_key=..., base_url=...)。

从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/combinators.py
"""

from __future__ import annotations

import httpx
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (RunnableBranch, RunnableLambda, RunnableParallel,
                                      RunnablePassthrough)

from scripted_chat import chat_completion, scripted_chat

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只回答是否符合退货条件，一句话。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])

CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}


def fixed_model(text: str):
    """每次请求都返回同一句话的脚本化模型。"""
    def respond(index: int, body: dict):
        return chat_completion(text, usage=(42, 7))
    return scripted_chat(respond)


def model_500():
    """按真实接口形态返回 500 的模型：用来触发 fallback。"""
    def respond(index: int, body: dict):
        return httpx.Response(500, json={"error": {"message": "upstream unavailable",
                                                  "type": "server_error"}})
    return scripted_chat(respond)


# ---------------------------------------------------------------- 1 管道
def pipe_demo() -> None:
    chain = PROMPT | fixed_model("符合退货条件。") | StrOutputParser()
    print("== 1. | 三段串联 ==")
    print("类型：", type(chain).__name__)
    print("输出：", repr(chain.invoke(CASE)))
    print()


def pipe_type_error() -> None:
    """把解析器直接接在模板后面：类型对不上，报错发生在拼链之后的调用里。"""
    chain = PROMPT | StrOutputParser()
    print("== 1b. 接错位置 ==")
    try:
        chain.invoke(CASE)
    except Exception as e:
        print(f"{type(e).__name__}: {str(e).splitlines()[0]}")
    print()


# ---------------------------------------------------------------- 2 并行
def parallel_demo() -> None:
    chain = RunnableParallel(
        verdict=PROMPT | fixed_model("符合退货条件。") | StrOutputParser(),
        chars=RunnableLambda(lambda x: len(x["state"])),
    )
    out = chain.invoke(CASE)
    print("== 2. RunnableParallel：同一份输入分给两个分支 ==")
    print(f"输出类型 {type(out).__name__}，键 {list(out)}")
    print(out)
    print()


# ---------------------------------------------------------------- 3 直通
def passthrough_demo() -> None:
    chain = RunnablePassthrough.assign(
        verdict=PROMPT | fixed_model("符合退货条件。") | StrOutputParser(),
    )
    out = chain.invoke(CASE)
    print("== 3. RunnablePassthrough.assign：保留输入，追加一个键 ==")
    print(out)
    print(f"原输入没被改：{CASE}")
    print()


# ---------------------------------------------------------------- 4 Lambda
def lambda_demo() -> None:
    def shape_input(raw: dict) -> dict:
        """把外部入参整成本章统一的三个键。"""
        return {"order_id": raw["id"], "days": raw["signed_days"], "state": raw["status"]}

    def clip(text: str) -> str:
        return text if len(text) <= 12 else text[:12] + "…"

    chain = RunnableLambda(shape_input) | PROMPT | fixed_model("符合退货条件。") | StrOutputParser() | RunnableLambda(clip)
    print("== 4. RunnableLambda：把普通函数接进链 ==")
    print(chain.invoke({"id": "A1001", "signed_days": 3, "status": "未拆封"}))
    print()


# ---------------------------------------------------------------- 5 分支
def branch_demo() -> None:
    branch = RunnableBranch(
        (lambda x: x["days"] > 7, RunnableLambda(lambda x: "超期：不退")),
        (lambda x: x["state"] == "已拆封", RunnableLambda(lambda x: "已拆封：需人工审核")),
        PROMPT | fixed_model("符合退货条件。") | StrOutputParser(),
    )
    print("== 5. RunnableBranch：按条件选一条路 ==")
    for case in [CASE,
                 {"order_id": "A1002", "days": 10, "state": "未拆封"},
                 {"order_id": "A1003", "days": 2, "state": "已拆封"}]:
        print(f"  {case} -> {branch.invoke(case)}")
    print()


def branch_raise_demo() -> None:
    """条件函数自己要读的键不存在：整条链失败，不会退到默认分支。"""
    branch = RunnableBranch(
        (lambda x: x["days"] > 7, RunnableLambda(lambda x: "超期：不退")),
        RunnableLambda(lambda x: "默认：可退"),
    )
    print("== 5b. 条件函数自己抛异常 ==")
    try:
        branch.invoke({"order_id": "A1004"})
    except Exception as e:
        print(f"{type(e).__name__}: {e}")
    print()


# ---------------------------------------------------------------- 6 兜底
def fallback_demo() -> None:
    primary = PROMPT | model_500() | StrOutputParser()
    backup = PROMPT | fixed_model("主服务不可用，这是备用模型的回答。") | StrOutputParser()
    chain = primary.with_fallbacks([backup])

    print("== 6. with_fallbacks：主路失败换备用 ==")
    print(f"返回类型 {type(chain).__name__}")
    print("输出：", chain.invoke(CASE))

    try:
        primary.invoke(CASE)
    except Exception as e:
        print(f"不走 fallback 时看到的是：{type(e).__name__}")

    with_key = RunnableLambda(
        lambda x: (_ for _ in ()).throw(ValueError("boom"))
    ).with_fallbacks([RunnablePassthrough()], exception_key="err")
    print("exception_key 的效果：", with_key.invoke({"a": 1}))
    print()


# ---------------------------------------------------------------- 7 重试
def retry_demo() -> None:
    calls = {"n": 0}

    def flaky(x: dict) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection refused")
        return f"第 {calls['n']} 次成功"

    chain = RunnableLambda(flaky).with_retry(stop_after_attempt=3, wait_exponential_jitter=False)
    print("== 7. with_retry：同一份输入重发 ==")
    print("输出：", chain.invoke({}))
    print("实际尝试次数：", calls["n"])

    calls["n"] = -100
    never = RunnableLambda(lambda x: (_ for _ in ()).throw(httpx.ConnectError("always down")))
    chain2 = never.with_retry(stop_after_attempt=2, wait_exponential_jitter=False)
    try:
        chain2.invoke({})
    except Exception as e:
        print(f"一直失败时：{type(e).__name__}: {e}")
    print()


def main() -> None:
    pipe_demo()
    pipe_type_error()
    parallel_demo()
    passthrough_demo()
    lambda_demo()
    branch_demo()
    branch_raise_demo()
    fallback_demo()
    retry_demo()


if __name__ == "__main__":
    main()
