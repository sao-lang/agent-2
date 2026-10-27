"""第 9 章 9.5：消息裁剪的六个参数。

运行：python code/knowledge/ch09_lc_basic/trimming.py
不联网、不调模型，只裁剪消息列表。原理演示，不是模型实测。
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately

HISTORY = [
    SystemMessage("你是退货政策助手，只回答与退货相关的问题。"),
    HumanMessage("订单 A1001 能退吗？"),
    AIMessage("请提供签收时间和商品状态。"),
    HumanMessage("签收 7 天，未拆封。"),
    AIMessage("符合退货条件。"),
    HumanMessage("那退款多久到账？"),
]


def show(label, messages):
    """打印一份裁剪结果的条数、token 数与每条的内容。"""
    print(label)
    print(f"  {count_tokens_approximately(messages)} token，{len(messages)} 条")
    for m in messages:
        print(f"    {m.type:<7} {m.content!r}")
    print()


def signature():
    """真签名与每个参数的默认值。"""
    import inspect

    for name, param in inspect.signature(trim_messages).parameters.items():
        print(f"{name:<16} 默认={param.default!r}")


def baseline():
    print(f"原始：{count_tokens_approximately(HISTORY)} token，{len(HISTORY)} 条")
    print()


def keep_tail():
    """strategy='last'：从末尾往前装。"""
    show("strategy='last', max_tokens=40:",
         trim_messages(HISTORY, max_tokens=40, token_counter=count_tokens_approximately,
                       strategy="last"))


def keep_system():
    """include_system=True：system 单独留在最前面。"""
    show("include_system=True:",
         trim_messages(HISTORY, max_tokens=40, token_counter=count_tokens_approximately,
                       strategy="last", include_system=True))


def start_on_human():
    """start_on='human'：裁完的第一条必须是 human。"""
    show("include_system=True, start_on='human':",
         trim_messages(HISTORY, max_tokens=40, token_counter=count_tokens_approximately,
                       strategy="last", include_system=True, start_on="human"))


def keep_head():
    """strategy='first'：从头往后装。"""
    show("strategy='first', max_tokens=40:",
         trim_messages(HISTORY, max_tokens=40, token_counter=count_tokens_approximately,
                       strategy="first"))


def end_on_human():
    """end_on='human'：裁完的最后一条必须是 human。"""
    history = HISTORY + [AIMessage("退款 3 个工作日到账。")]
    show("strategy='last', max_tokens=60:",
         trim_messages(history, max_tokens=60, token_counter=count_tokens_approximately,
                       strategy="last"))
    show("strategy='last', max_tokens=60, end_on='human':",
         trim_messages(history, max_tokens=60, token_counter=count_tokens_approximately,
                       strategy="last", end_on="human"))


def too_small():
    """上限小于单条消息时，拿到空列表。"""
    show("max_tokens=5:", trim_messages(HISTORY, max_tokens=5,
                                        token_counter=count_tokens_approximately,
                                        strategy="last"))


def partial_with_newlines():
    """一条多行消息放不下时，allow_partial 才切得动。"""
    messages = [
        SystemMessage("你是退货政策助手。"),
        HumanMessage(
            "签收情况：3 天前签收。\n"
            "商品状态：未拆封，包装完好。\n"
            "问题：可以申请退货吗。\n"
            "追问：需要提供哪些材料。\n"
            "追问：退款多久到账。"
        ),
    ]
    for allow in (False, True):
        show(f"allow_partial={allow}:",
             trim_messages(messages, max_tokens=20, token_counter=count_tokens_approximately,
                           strategy="last", include_system=True, allow_partial=allow))


def partial_with_splitter():
    """换一个按句号切的 text_splitter，切点可以更细。"""
    messages = [
        SystemMessage("你是退货政策助手。"),
        HumanMessage("签收 3 天，未拆封，包装完好。请问可以退货吗。需要哪些材料。退款多久到账。"),
    ]
    out = trim_messages(messages, max_tokens=15, token_counter=count_tokens_approximately,
                        strategy="last", include_system=True, allow_partial=True,
                        text_splitter=lambda text: [piece + "。" for piece in text.split("。") if piece])
    show("text_splitter=按句号切, max_tokens=15:", out)


def two_errors():
    """两个参数只在 strategy='last' 下成立。"""
    for kwargs in (
        {"strategy": "first", "include_system": True},
        {"strategy": "first", "start_on": "human"},
    ):
        try:
            trim_messages(HISTORY, max_tokens=40, token_counter=count_tokens_approximately, **kwargs)
        except ValueError as e:
            print(f"{kwargs} -> ValueError: {e}")
    print()


def counter_comparison():
    """估算计数器与真实 tokenizer 的差别。"""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini", api_key="sk-test")
    print("近似计数:", count_tokens_approximately(HISTORY))
    print("gpt-4o-mini 的 tokenizer:", llm.get_num_tokens_from_messages(HISTORY))
    out = trim_messages(HISTORY, max_tokens=40, token_counter=llm, strategy="last")
    print(f"用模型做 token_counter, max_tokens=40: {len(out)} 条，"
          f"真实 token={llm.get_num_tokens_from_messages(out)}，"
          f"近似 token={count_tokens_approximately(out)}")
    for m in out:
        print(f"    {m.type:<7} {m.content!r}")


if __name__ == "__main__":
    signature()
    print()
    baseline()
    keep_tail()
    keep_system()
    start_on_human()
    keep_head()
    end_on_human()
    too_small()
    partial_with_newlines()
    partial_with_splitter()
    two_errors()
    counter_comparison()
