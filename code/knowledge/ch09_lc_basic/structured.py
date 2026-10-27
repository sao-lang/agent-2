"""第 9 章 9.7：结构化输出的三种策略。

运行：python code/knowledge/ch09_lc_basic/structured.py
脚本化后端：请求照常编码，响应按策略回放。原理演示，不是模型实测。
"""

import json

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from scripted_chat import chat_completion, tool_call

GOOD = '{"order_id": "A1001", "days": 7, "reason": "签收不想要"}'
WRONG_FIELDS = '{"orderId": "A1001", "days": 7, "reason": "签收不想要"}'
QUESTION = "订单 A1001，签收 7 天，未拆封，能退吗？"


class RefundCheck(BaseModel):
    """要取出的三个字段。"""

    order_id: str
    days: int
    reason: str


def make_llm(reply_text=GOOD, reply_tool=None):
    """按请求形态回放：带 tools 的请求走工具调用，其余走正文。"""

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if body.get("tools"):
            return httpx.Response(200, json=chat_completion(
                tool_calls=reply_tool or [tool_call("RefundCheck", json.loads(reply_text))],
                finish_reason="tool_calls", usage=(48, 24)))
        return httpx.Response(200, json=chat_completion(reply_text, usage=(48, 24)))

    seen = []
    transport = httpx.MockTransport(handler)
    llm = ChatOpenAI(model="demo-model", api_key="sk-test",
                     http_client=httpx.Client(transport=transport, trust_env=False))
    return llm, seen


def describe(name, seen):
    """把这次请求里与结构化输出有关的三项打出来。"""
    body = seen[-1]
    print(f"  [{name}] tools:", "有" if body.get("tools") else "无")
    print(f"  [{name}] tool_choice:", body.get("tool_choice"))
    print(f"  [{name}] response_format:", json.dumps(body.get("response_format"), ensure_ascii=False))


def signature():
    """真签名：`method` 的默认值就是最强的那一种。"""
    import inspect

    print(inspect.signature(ChatOpenAI.with_structured_output))


def three_methods():
    for method in ("function_calling", "json_schema", "json_mode"):
        llm, seen = make_llm()
        chain = llm.with_structured_output(RefundCheck, method=method)
        result = chain.invoke(QUESTION)
        print(f"{method:<17} -> {type(result).__name__} {result}")
        describe(method, seen)
        print()


def wrong_fields():
    """json_mode 只保证语法，字段名照样会错。"""
    llm, _ = make_llm(reply_text=WRONG_FIELDS)
    chain = llm.with_structured_output(RefundCheck, method="json_mode")
    try:
        chain.invoke(QUESTION)
    except Exception as e:
        print(type(e).__name__, ":", str(e).splitlines()[0])
        print()
        for line in str(e).splitlines()[1:6]:
            print(line)


def include_raw():
    """include_raw=True：把解析失败也留在返回值里。"""
    llm, _ = make_llm(reply_text=WRONG_FIELDS)
    chain = llm.with_structured_output(RefundCheck, method="json_mode", include_raw=True)
    result = chain.invoke(QUESTION)
    print("parsed:", result["parsed"])
    print("parsing_error 类型:", type(result["parsing_error"]).__name__)
    print("raw.content:", result["raw"].content)


if __name__ == "__main__":
    print("== 签名 ==")
    signature()
    print()
    print("== 三种策略 ==")
    three_methods()
    print("== 字段名不合 schema ==")
    wrong_fields()
    print()
    print("== include_raw ==")
    include_raw()
