"""第 9 章 9.2：模型接入的参数矩阵。

运行：python code/knowledge/ch09_lc_basic/model_access.py
脚本化后端：请求照常编码成一个真实的 ChatOpenAI 调用，响应来自脚本。
原理演示，不是模型实测。
"""

import inspect
import json

import httpx
from langchain.chat_models import init_chat_model
from scripted_chat import chat_completion

SEEN = []


def handler(request):
    """把请求体留下来，再回放一份响应。"""
    SEEN.append((str(request.url), json.loads(request.content)))
    return httpx.Response(200, json=chat_completion("签收后 7 天内可退。", usage=(24, 9)))


CLIENT = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def build(model=None, **kwargs):
    """统一入口：固定用同一个脚本化传输层。"""
    return init_chat_model(model, api_key="sk-test", http_client=CLIENT, **kwargs)


def show_signature():
    """打印真实签名与每个参数的默认值。"""
    for name, param in inspect.signature(init_chat_model).parameters.items():
        print(f"{name:<18} {str(param.kind):<20} 默认={param.default!r}")


def case_provider():
    """给 model_provider，拿到具体的 ChatOpenAI。"""
    llm = build("demo-model", model_provider="openai")
    reply = llm.invoke("能退吗？")
    print("返回类型:", type(llm).__name__)
    print("content:", reply.content)
    print("请求 URL:", SEEN[-1][0])
    print("请求体里的 model:", SEEN[-1][1]["model"])


def case_prefix():
    """`厂商:模型` 的形式，不写 model_provider。"""
    llm = build("openai:demo-model")
    print("返回类型:", type(llm).__name__)
    llm.invoke("能退吗？")
    print("请求体里的 model:", SEEN[-1][1]["model"])


def case_configurable():
    """configurable_fields 把参数从构造时挪到调用时。"""
    llm = build("demo-model", model_provider="openai",
                configurable_fields=("model", "temperature"), config_prefix="llm")
    print("返回类型:", type(llm).__name__)
    print("默认 temperature:", SEEN[-1][1].get("temperature") if SEEN else "（尚未调用）")

    llm.invoke("能退吗？", config={"configurable": {"llm_temperature": 0.9}})
    print("config 里的 temperature=0.9 ->", SEEN[-1][1].get("temperature"))

    hot = llm.with_config(configurable={"llm_temperature": 0.2})
    hot.invoke("能退吗？")
    print("with_config 改成 0.2 ->", SEEN[-1][1].get("temperature"))


def case_base_url():
    """base_url 决定请求打到哪个主机。"""
    llm = build("demo-model", model_provider="openai", base_url="http://127.0.0.1:8080/v1")
    llm.invoke("能退吗？")
    print("base_url 指向本机 8080 后，请求 URL:", SEEN[-1][0])


def case_wrong_prefix():
    """config_prefix 与 config 的键名对不上时，参数被静默忽略。"""
    llm = build("demo-model", model_provider="openai", configurable_fields=("temperature",),
                config_prefix="llm")
    llm.invoke("能退吗？", config={"configurable": {"temperature": 0.9}})
    print("键名写 temperature（少了 llm_）->", SEEN[-1][1].get("temperature"))
    llm.invoke("能退吗？", config={"configurable": {"llm_temperature": 0.9}})
    print("键名写 llm_temperature ->", SEEN[-1][1].get("temperature"))


def case_unknown_kwarg():
    """参数名写错：构造时只警告，调用时才炸。"""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        llm = build("demo-model", model_provider="openai", foo=1)
    for w in caught:
        print("构造时:", " ".join(str(w.message).split()))
    try:
        llm.invoke("能退吗？")
    except TypeError as e:
        print(f"调用时: TypeError: {e}")


def case_ambiguous():
    """只给模型名，不给厂商，看报错。"""
    try:
        build("demo-model")
    except Exception as e:
        print(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    print("== 签名 ==")
    show_signature()
    print()
    print("== 情形一：model_provider ==")
    case_provider()
    print()
    print("== 情形二：厂商:模型 ==")
    case_prefix()
    print()
    print("== 情形三：configurable_fields ==")
    case_configurable()
    print()
    print("== 情形四：base_url ==")
    case_base_url()
    print()
    print("== 情形五：config_prefix 写错 ==")
    case_wrong_prefix()
    print()
    print("== 情形六：参数名写错 ==")
    case_unknown_kwarg()
    print()
    print("== 情形七：缺 model_provider ==")
    case_ambiguous()
