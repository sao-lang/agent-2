"""工具调用的六种坏法，每种给出它的信号。

这些坏法都不需要模型：它们全部发生在"调用方拿到 tool_calls 之后"这一段，
也就是模型管不着的那一段。跑完这个脚本，能看出为什么工具调用必须有调用方兜住。
"""

from __future__ import annotations

import json

from round_trip import ORDERS, execute, get_order
from transport import ORDER_TOOL, SYSTEM, Transport

TOOL_IMPL = {"get_order": get_order}


def call(call_id: str, name: str, arguments: str) -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


# ---------------------------------------------------------------- 一、参数不是 JSON

def broken_arguments() -> None:
    """模型返回的 arguments 不是合法 JSON。

    本演示里它是模型自己写坏的；真实模型可能是 JSON 的数值溢出、被截断，
    或者平台在中间对 arguments 做了字符串转义处理。
    """
    print("一、arguments 不是合法 JSON")
    c = call("call_1", "get_order", '{order_id: "A1001"}')  # 键没加引号
    msg = execute(c)
    print(f"  原始 arguments = {c['function']['arguments']!r}")
    print(f"  回灌内容       = {msg['content']}")
    try:
        json.loads(c["function"]["arguments"])
        print("  json.loads 成功：不会发生")
    except json.JSONDecodeError as e:
        print(f"  崩掉的写法      = json.loads 直接抛：{e}")
        print(f"  正确的写法      = 捕获异常，把错误文本回灌给模型，让它重发")


# ---------------------------------------------------------------- 二、工具不存在

def unknown_tool() -> None:
    """模型编出一个没声明过的工具名。"""
    print()
    print("二、工具名不在实现表里")
    c = call("call_2", "get_order_status", '{"order_id": "A1001"}')
    msg = execute(c)
    print(f"  name         = {c['function']['name']}")
    print(f"  TOOL_IMPL 里 = {sorted(TOOL_IMPL)}")
    print(f"  回灌内容     = {msg['content']}")


# ---------------------------------------------------------------- 三、不问就答

def answer_without_calling() -> None:
    """拿到 tool_calls 却直接给用户答案：模型输出的动作被丢掉了。"""
    print()
    print("三、拿到 tool_calls 却直接收工")
    transport = Transport()
    request = {
        "model": "demo-model-2024",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "订单 A1001 还能退吗？"},
        ],
        "tools": [ORDER_TOOL],
    }
    reply = transport.post(request)
    message = reply["choices"][0]["message"]

    wrong = message.get("content")
    print(f"  直接取 content   = {wrong!r}   <- 用户看到的是空的")
    print(f"  finish_reason    = {reply['choices'][0]['finish_reason']}")

    # 正确：必须先执行，再发第二次请求
    request["messages"].append(message)
    for c in message["tool_calls"]:
        request["messages"].append(execute(c))
    second = transport.post(request)
    print(f"  执行后第二次回答 = {second['choices'][0]['message']['content']!r}")


# ---------------------------------------------------------------- 四、回灌缺字段

def bad_feedback() -> None:
    """回灌时少了 tool_call_id 或 role 写错，服务端会拒绝整段对话。"""
    print()
    print("四、回灌格式不对")
    variants = {
        "正确": {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
        "少了 tool_call_id": {"role": "tool", "content": "{}"},
        "role 写成 user": {"role": "user", "tool_call_id": "call_1", "content": "{}"},
        "content 是对象不是字符串": {"role": "tool", "tool_call_id": "call_1",
                                "content": {"status": "已签收"}},
    }
    for label, m in variants.items():
        errors = []
        if m["role"] != "tool":
            errors.append("role 必须是 tool")
        if "tool_call_id" not in m:
            errors.append("缺 tool_call_id")
        if not isinstance(m["content"], str):
            errors.append("content 必须是字符串")
        print(f"  {label:<22} {'通过' if not errors else '；'.join(errors)}")


# ---------------------------------------------------------------- 五、并发调用配错了顺序

def parallel_calls() -> None:
    """一次返回多个 tool_calls：每条结果都要回灌，id 不能错配。"""
    print()
    print("五、一次返回两个调用，结果被错配")
    calls = [
        call("call_a", "get_order", '{"order_id": "A1001"}'),
        call("call_b", "get_order", '{"order_id": "A1002"}'),
    ]
    results = [execute(c) for c in calls]
    print(f"  回灌顺序 = {[r['tool_call_id'] for r in results]}")

    # 错配：结果按位置而不是按 id 配回去，两条结果互换。
    # 如果靠位置拼接，tool_call_id 也跟着换掉，表面上完全合法——这正是它难发现的原因。
    swapped = [dict(results[1], tool_call_id="call_a"),
               dict(results[0], tool_call_id="call_b")]
    print(f"  错配后   = {[r['tool_call_id'] for r in swapped]}   <- id 依然一一对应，查不出来")
    for r in swapped:
        print(f"    {r['tool_call_id']} -> {r['content']}")
    print("  表现     = 订单 A1001 的回答里出现了 A1002 的状态，格式全对，内容全错")


# ---------------------------------------------------------------- 六、副作用被重放

def replay() -> None:
    """工具本身有副作用（这里是"发短信"），执行完但回灌没成功，再用同一批调用重试。"""
    print()
    print("六、有副作用的工具被重放")
    sent: list[str] = []

    def send_sms(order_id: str) -> dict:
        sent.append(order_id)
        return {"sent": True, "seq": len(sent)}

    calls = [call("call_x", "send_sms", '{"order_id": "A1001"}')]

    # 第一次执行
    for c in calls:
        send_sms(**json.loads(c["function"]["arguments"]))
    # 回灌请求因为网络失败，调用方重试时手里还是同一批 calls
    for c in calls:
        send_sms(**json.loads(c["function"]["arguments"]))

    print(f"  执行的次数   = {len(sent)}")
    print(f"  实际发的短信 = {sent}")
    print("  根因         = 调用 id 只存在于这一轮响应的语义里，不是一个去重键")

    # 加一层去重：以 tool_call_id 为键记住已经执行过的结果
    done: dict[str, dict] = {}

    def once(c: dict) -> dict:
        if c["id"] not in done:
            done[c["id"]] = send_sms(**json.loads(c["function"]["arguments"]))
        return done[c["id"]]

    sent.clear()
    done.clear()
    for _ in range(2):
        for c in calls:
            once(c)
    print(f"  以 id 去重后 = {len(sent)} 次")


# ---------------------------------------------------------------- 七、只给名字不给说明

def description_matters() -> None:
    """同一个工具，只写 name 与写清 description/parameters，模型选它的概率不同。"""
    print()
    print("七、工具说明的详细程度")
    bare = {"type": "function", "function": {"name": "get_order", "parameters": {"type": "object"}}}
    full = ORDER_TOOL
    for label, tool in (("只有名字", bare), ("完整说明", full)):
        fn = tool["function"]
        chars = len(json.dumps(fn, ensure_ascii=False))
        print(f"  {label:<6} 定义 {chars:>3} 字符  "
              f"description={'有' if fn.get('description') else '无'}  "
              f"参数说明={'有' if 'order_id' in json.dumps(fn) else '无'}")


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
