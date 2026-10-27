"""第 9 章 9.4：三类元信息。

运行：python code/knowledge/ch09_lc_basic/metadata.py
脚本化后端：响应按厂商格式回放，消息对象由 langchain-openai 真实解析。
原理演示，不是模型实测。
"""

import json

from langchain_core.messages import HumanMessage
from scripted_chat import chat_completion, scripted_chat


def make_llm(respond):
    """`respond(请求体) -> 响应字典`，交给共享的脚本化后端。"""
    return scripted_chat(lambda index, body: respond(body))


def dump(label, reply):
    print(label)
    print("  content:", repr(reply.content))
    print("  additional_kwargs:", reply.additional_kwargs)
    print("  response_metadata:", reply.response_metadata)
    print("  usage_metadata:", reply.usage_metadata)
    print()


def normal():
    """一次正常回复，三类元信息都齐。"""
    llm = make_llm(lambda body: chat_completion("签收后 7 天内可退。", usage=(24, 9)))
    dump("正常回复：", llm.invoke("能退吗？"))


def filtered():
    """被拦截的回复：正文空，原因在 additional_kwargs 里。"""
    raw = chat_completion("", usage=(24, 0))
    raw["choices"][0]["finish_reason"] = "content_filter"
    raw["choices"][0]["message"]["refusal"] = "无法回答该请求"
    llm = make_llm(lambda body: raw)
    dump("被拦截的回复：", llm.invoke("能退吗？"))


def no_usage():
    """服务端不给 usage 时，usage_metadata 是 None。"""
    raw = chat_completion("好。")
    del raw["usage"]
    llm = make_llm(lambda body: raw)
    reply = llm.invoke("能退吗？")
    print("usage_metadata:", reply.usage_metadata)
    print("response_metadata['token_usage']:", reply.response_metadata["token_usage"])
    print()


def unknown_field():
    """响应里多出来的字段不会进消息对象。"""
    raw = chat_completion("好。", usage=(24, 2))
    raw["choices"][0]["message"]["x_vendor_field"] = "厂商私有字段"
    llm = make_llm(lambda body: raw)
    reply = llm.invoke("能退吗？")
    dumped = json.dumps(reply.model_dump(), ensure_ascii=False, default=str)
    print("消息对象里能找到 x_vendor_field 吗:", "x_vendor_field" in dumped)
    print("additional_kwargs 的键:", sorted(reply.additional_kwargs))


def mapping():
    """三类元信息对上第 1 章的字段。"""
    llm = make_llm(lambda body: chat_completion("签收后 7 天内可退。", usage=(24, 9)))
    reply = llm.invoke([HumanMessage("能退吗？")])
    rows = [
        ("finish_reason", reply.response_metadata["finish_reason"]),
        ("usage.prompt_tokens", reply.response_metadata["token_usage"]["prompt_tokens"]),
        ("usage.completion_tokens", reply.response_metadata["token_usage"]["completion_tokens"]),
        ("message.refusal", reply.additional_kwargs.get("refusal")),
        ("input_tokens", reply.usage_metadata["input_tokens"]),
        ("output_tokens", reply.usage_metadata["output_tokens"]),
        ("total_tokens", reply.usage_metadata["total_tokens"]),
    ]
    for name, value in rows:
        print(f"  {name:<26} {value!r}")


if __name__ == "__main__":
    normal()
    filtered()
    no_usage()
    unknown_field()
    print()
    print("字段对照：")
    mapping()
