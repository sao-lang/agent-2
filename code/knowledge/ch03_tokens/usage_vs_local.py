"""本地 tiktoken 计数与服务端 usage 的差，来自哪几段。

服务端是脚本化的（`fake_server`）：它按 OpenAI 兼容格式回放响应。但这里回放的
`usage` 不是写死的常数——它用同一份词表把请求里的 messages 渲染成 chat 模板再数
一遍，再加上 tools 的 schema。这样"本地数出来的数"与"服务端报的数"的差额可以逐段
解释清楚。

它是口径演示，不是厂商实测：真实服务端的模板、每消息固定开销、工具转写方式都与这里
略有不同。换成真实服务时，只需要把 client_for(base_url) 换成一个指向厂商的客户端。
"""

from __future__ import annotations

import json

import tiktoken

from fake_server import chat_completion, client_for, scripted_server

ENC = tiktoken.get_encoding("cl100k_base")

# 服务端把 messages 拼成一段带特殊标记的文本再切词。这份模板是示意：
# 真实厂商各有一套，形状不同，固定开销也不同。
CHAT_TEMPLATE = "<|im_start|>{role}\n{content}<|im_end|>\n"
REPLY_PRIMER = "<|im_start|>assistant\n"

SYSTEM = "你是退货客服，只回答退货政策问题。"
QUESTION = "订单 A1001 三天前签收，未拆封，能退吗？"
FOLLOW_UP = "那定制商品呢？"
ANSWER = "可以退：签收 3 天，未拆封。"
LONG_DOC = (
    "退货政策全文如下：签收后 7 天内可以申请退货；商品需要保持未拆封且不影响二次销售；"
    "定制商品、生鲜、已激活的电子产品不支持退货；退货运费由买家承担，质量问题除外；"
    "申请退货后 48 小时内会有人联系确认；退款在收货后 3 个工作日内原路返回；"
    "超过 7 天但在 15 天内可以申请换货；换货需保留原包装和全部配件。"
)

ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_order",
        "description": "查询订单信息。返回 JSON，字段为 {\"status\": 字符串, \"signed_days_ago\": 整数}。",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "订单号，例如 A1001"}},
            "required": ["order_id"],
        },
    },
}


def render(messages: list[dict]) -> str:
    """服务端口径：把 messages 渲染成带特殊标记的一段文本。"""
    body = "".join(CHAT_TEMPLATE.format(role=m["role"], content=m["content"]) for m in messages)
    return body + REPLY_PRIMER


def server_usage(messages: list[dict], tools: list[dict] | None = None) -> int:
    """服务端数出来的 prompt token：模板文本 + 工具 schema。"""
    total = len(ENC.encode(render(messages)))
    if tools:
        total += len(ENC.encode(json.dumps(tools, ensure_ascii=False)))
    return total


def local_usage(messages: list[dict]) -> int:
    """调用方本地能自己算的部分：只数 content，不带任何模板。"""
    return sum(len(ENC.encode(m["content"])) for m in messages)


def main() -> None:
    request_log: list[dict] = []

    def respond(index: int, body: dict) -> dict:
        request_log.append(body)
        prompt = server_usage(body["messages"], body.get("tools"))
        return chat_completion(content=ANSWER, usage=(prompt, len(ENC.encode(ANSWER))))

    scenarios = {
        "一轮问答": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": QUESTION},
        ],
        "两轮追问": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": QUESTION},
            {"role": "assistant", "content": ANSWER},
            {"role": "user", "content": FOLLOW_UP},
        ],
        "带工具定义": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": QUESTION},
        ],
        "带长文档": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": LONG_DOC + "\n\n问题：" + QUESTION},
        ],
    }

    with scripted_server(respond) as base_url:
        client = client_for(base_url)

        print("=" * 84)
        print("一、本地数出来的 prompt 与服务端报的 usage")
        print("=" * 84)
        print(f"{'场景':<10}{'消息数':>6}{'本地 content':>14}{'len//2 估算':>13}"
              f"{'服务端 usage':>14}{'差额':>8}")
        print("-" * 84)

        for name, messages in scenarios.items():
            tools = [ORDER_TOOL] if name == "带工具定义" else None
            kwargs: dict = {"model": "demo-model", "messages": messages}
            if tools:
                kwargs["tools"] = tools
            reply = client.chat.completions.create(**kwargs)

            local = local_usage(messages)
            chars = sum(len(m["content"]) for m in messages)
            usage = reply.usage.prompt_tokens
            print(f"{name:<10}{len(messages):>6}{local:>14}{chars // 2:>13}"
                  f"{usage:>14}{usage - local:>+8}")

        print()
        print("=" * 84)
        print("二、差额拆开：模板开销与工具 schema")
        print("=" * 84)
        base = scenarios["一轮问答"]
        base_usage = server_usage(base)
        print(f"  一轮问答：content {local_usage(base)}  →  usage {base_usage}"
              f"   （模板开销 {base_usage - local_usage(base)}，来自两条消息的角色标记与结束标记）")
        print("  逐条补 assistant 消息，每次的增量：")
        answer_tokens = len(ENC.encode(ANSWER))
        prev = base_usage
        for i in range(1, 4):
            part = base + [{"role": "assistant", "content": ANSWER}] * i
            cur = server_usage(part)
            delta = cur - prev
            print(f"    补第 {i} 条：usage {cur}  增量 {delta}"
                  f" = content {answer_tokens} + 模板 {delta - answer_tokens}")
            prev = cur
        tool_tokens = len(ENC.encode(json.dumps([ORDER_TOOL], ensure_ascii=False)))
        print(f"  tools 里这一个工具：{tool_tokens} token，"
              f"是一轮问答 content（{local_usage(base)}）的 {tool_tokens / local_usage(base):.1f} 倍")

        print()
        print("=" * 84)
        print("三、同一段 messages，两种口径的比例")
        print("=" * 84)
        for name, messages in scenarios.items():
            local = local_usage(messages)
            usage = server_usage(messages, [ORDER_TOOL] if name == "带工具定义" else None)
            print(f"  {name:<10} 本地 content {local:>5}  usage {usage:>5}"
                  f"  usage/本地 = {usage / local:.2f}")

        print()
        print("=" * 84)
        print("四、请求体里被计费的原始字段")
        print("=" * 84)
        print(json.dumps(request_log[2], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
