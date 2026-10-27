"""工具调用的六种坏法，每种给出它的信号。

除第四段（回灌格式）之外，其余各段都走真实 `openai` SDK 与脚本化后端。
坏的地方全部在"调用方拿到 `tool_calls` 之后"这一段——模型管不着的那一段。
响应文本与 usage 是写死的，**原理演示，不是模型实测**。
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from fake_server import chat_completion, client_for, scripted_server
from schema_from_signature import GetOrderArgs
from sdk_round_trip import MODEL, execute
from tools import ORDER_TOOL, SYSTEM, TOOL_IMPL


def turn(respond, messages: list[dict], tools: list[dict] | None = None):
    """起一个脚本化后端，发一次请求，返回响应对象。"""
    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        kwargs: dict = {"model": MODEL, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return client.chat.completions.create(**kwargs)


def base_messages() -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "订单 A1001 还能退吗？"},
    ]


# ---------------------------------------------------------------- 一、参数不是 JSON

def broken_arguments() -> None:
    """服务端回了这样一串 arguments：键没加引号。

    真实模型也可能写出这种：JSON 里的引号被截断、数值溢出、或者平台在中间
    做了一次转义处理。SDK 不会替你判断它是不是合法 JSON，它原样交出字符串。
    """
    print("一、arguments 不是合法 JSON")
    bad = {"id": "call_1", "type": "function",
           "function": {"name": "get_order", "arguments": '{order_id: "A1001"}'}}

    def respond(index: int, body: dict) -> dict:
        return chat_completion(content=None, tool_calls=[bad],
                               finish_reason="tool_calls", usage=(96, 14), model=MODEL)

    resp = turn(respond, base_messages(), [ORDER_TOOL])
    call = resp.choices[0].message.tool_calls[0]
    print(f"  原始 arguments = {call.function.arguments!r}")
    print(f"  回灌内容 = {execute(call)['content']}")
    try:
        json.loads(call.function.arguments)
    except json.JSONDecodeError as e:
        print(f"  json.loads 直接抛：{e}")
    for label, text in (("坏 JSON", call.function.arguments),
                        ("类型不对", '{"order_id": 1001}')):
        try:
            GetOrderArgs.model_validate_json(text)
        except ValidationError as e:
            err = e.errors()[0]
            print(f"  pydantic 校验 {label}：{err['msg']}；"
                  f"loc={err['loc']}  type={err['type']}")


# ---------------------------------------------------------------- 二、工具不存在

def unknown_tool() -> None:
    """模型编出一个没声明过的工具名。名字是它生成的，不受 `tools` 限制。"""
    print()
    print("二、工具名不在实现表里")

    def respond(index: int, body: dict) -> dict:
        call = {"id": "call_2", "type": "function",
                "function": {"name": "get_order_status",
                             "arguments": '{"order_id": "A1001"}'}}
        return chat_completion(content=None, tool_calls=[call],
                               finish_reason="tool_calls", usage=(96, 14), model=MODEL)

    resp = turn(respond, base_messages(), [ORDER_TOOL])
    call = resp.choices[0].message.tool_calls[0]
    print(f"  name         = {call.function.name}")
    print(f"  TOOL_IMPL 里 = {sorted(TOOL_IMPL)}")
    print(f"  回灌内容     = {execute(call)['content']}")


# ---------------------------------------------------------------- 三、不问就答

def next_step(reply) -> str:
    """只按 finish_reason 决定下一步。content 是否为空不参与判断。"""
    reason = reply.choices[0].finish_reason
    if reason == "tool_calls":
        return "execute"
    if reason == "stop":
        return "answer"
    if reason == "length":
        return "continue"
    return "abort"


def answer_without_calling() -> None:
    """拿到 tool_calls 却直接给用户答案：用户收到的是空值。"""
    print()
    print("三、拿到 tool_calls 却直接收工")

    def respond(index: int, body: dict) -> dict:
        if index == 0:
            return chat_completion(
                content=None,
                tool_calls=[{"id": "call_3", "type": "function",
                             "function": {"name": "get_order",
                                          "arguments": '{"order_id": "A1001"}'}}],
                finish_reason="tool_calls", usage=(104, 17), model=MODEL)
        order = json.loads([m for m in body["messages"] if m["role"] == "tool"][-1]["content"])
        return chat_completion(content=f"可以退：已签收 {order['signed_days_ago']} 天，在 7 天内。",
                               finish_reason="stop", usage=(138, 12), model=MODEL)

    with scripted_server(respond) as base_url:
        client = client_for(base_url)
        messages = base_messages()
        first = client.chat.completions.create(
            model=MODEL, messages=messages, tools=[ORDER_TOOL])
        message = first.choices[0].message
        print(f"  直接取 content   = {message.content!r}   <- 用户看到的是空的")
        print(f"  finish_reason    = {first.choices[0].finish_reason}")
        print(f"  tool_calls 条数   = {len(message.tool_calls)}")
        print(f"  只看 finish_reason 决定下一步 = {next_step(first)}")

        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            messages.append(execute(call))
        second = client.chat.completions.create(
            model=MODEL, messages=messages, tools=[ORDER_TOOL])
        print(f"  执行后第二次回答 = {second.choices[0].message.content!r}")


# ---------------------------------------------------------------- 四、回灌缺字段

def bad_feedback() -> None:
    """回灌时少了 tool_call_id，或 role 写错，整段对话会被服务端拒掉。

    本机脚本化后端不做这项校验，所以这里用同一组规则在本地核对。
    真实服务端返回的是 400，`content` 不是字符串那条最容易被忽略。
    """
    print()
    print("四、回灌格式不对")
    variants = {
        "正确": {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
        "少了 tool_call_id": {"role": "tool", "content": "{}"},
        "role 写成 user": {"role": "user", "tool_call_id": "call_1", "content": "{}"},
        "content 是对象": {"role": "tool", "tool_call_id": "call_1",
                          "content": {"status": "已签收"}},
    }
    for label, message in variants.items():
        errors = []
        if message["role"] != "tool":
            errors.append("role 必须是 tool")
        if "tool_call_id" not in message:
            errors.append("缺 tool_call_id")
        if not isinstance(message["content"], str):
            errors.append("content 必须是字符串")
        print(f"  {label}：{'通过' if not errors else '；'.join(errors)}")


# ---------------------------------------------------------------- 五、结果错配

def parallel_calls() -> None:
    """一次返回两个调用：每条结果都要回灌，而且必须按 id 配回去。"""
    print()
    print("五、一次返回两个调用，结果被错配")

    def respond(index: int, body: dict) -> dict:
        orders = [("call_a", "A1001"), ("call_b", "A1002")]
        calls = [{"id": cid, "type": "function",
                  "function": {"name": "get_order",
                               "arguments": json.dumps({"order_id": oid})}}
                 for cid, oid in orders]
        return chat_completion(content=None, tool_calls=calls,
                               finish_reason="tool_calls", usage=(112, 26), model=MODEL)

    resp = turn(respond, base_messages(), [ORDER_TOOL])
    calls = resp.choices[0].message.tool_calls
    print(f"  响应里的 id = {[c.id for c in calls]}")
    results = [execute(c) for c in calls]
    print(f"  回灌顺序     = {[r['tool_call_id'] for r in results]}")

    # 错配：结果按位置而不是按 id 配回去，两条结果互换。
    # 位置拼接时 tool_call_id 也可能跟着换掉，表面上完全合法——这正是它难发现的原因。
    swapped = [dict(results[1], tool_call_id="call_a"),
               dict(results[0], tool_call_id="call_b")]
    print(f"  错配后       = {[r['tool_call_id'] for r in swapped]}   <- id 依然一一对应")
    for r in swapped:
        print(f"    {r['tool_call_id']} -> {r['content']}")
    print("  表现         = 订单 A1001 的回答里出现 A1002 的状态，格式全对，内容全错")


# ---------------------------------------------------------------- 六、副作用被重放

def replay() -> None:
    """工具本身有副作用，执行成功了，但回灌请求没送达，于是重试同一批调用。"""
    print()
    print("六、有副作用的工具被重放")
    sent: list[str] = []

    def send_sms(order_id: str) -> dict:
        sent.append(order_id)
        return {"sent": True, "seq": len(sent)}

    call = {"id": "call_x", "type": "function",
            "function": {"name": "send_sms", "arguments": '{"order_id": "A1001"}'}}

    for _ in range(2):  # 第 1 次执行 + 回灌失败后的重试
        send_sms(**json.loads(call["function"]["arguments"]))
    print(f"  执行的次数   = {len(sent)}")
    print(f"  实际发的短信 = {sent}")
    print("  根因         = 调用 id 只存在于这一轮响应的语义里，不是一个去重键")

    done: dict[str, dict] = {}

    def once(c: dict) -> dict:
        if c["id"] not in done:  # 以 tool_call_id 去重，只挡得住进程内的重试
            done[c["id"]] = send_sms(**json.loads(c["function"]["arguments"]))
        return done[c["id"]]

    sent.clear()
    done.clear()
    for _ in range(2):
        once(call)
    print(f"  以 id 去重后 = {len(sent)} 次")


# ---------------------------------------------------------------- 七、只给名字

def description_matters() -> None:
    """同一个工具，只写名字和写全说明，进请求的字符数差多少。"""
    print()
    print("七、工具说明的详细程度")
    bare = {"type": "function",
            "function": {"name": "get_order", "parameters": {"type": "object"}}}
    for label, tool in (("只有名字", bare), ("完整说明", ORDER_TOOL)):
        fn = tool["function"]
        props = fn["parameters"].get("properties", {})
        has_field_desc = any("description" in p for p in props.values())
        print(f"  {label}  定义 {len(json.dumps(fn, ensure_ascii=False)):>3} 字符  "
              f"description={'有' if fn.get('description') else '无'}  "
              f"参数说明={'有' if has_field_desc else '无'}")


def main() -> None:
    broken_arguments()
    unknown_tool()
    answer_without_calling()
    bad_feedback()
    parallel_calls()
    replay()
    description_matters()


if __name__ == "__main__":
    main()
