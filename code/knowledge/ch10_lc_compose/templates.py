"""三种提示词模板，打印装好的 messages。

不调模型：这一节看的是"模板装完之后，messages 里到底有什么"。
从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/templates.py
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import (ChatPromptTemplate, FewShotChatMessagePromptTemplate,
                                    MessagesPlaceholder)


def dump(label: str, messages: list) -> None:
    """把装好的 messages 打成一张表。"""
    print(f"== {label}：{len(messages)} 条 ==")
    print(f"  {'#':<3}{'type':<10}{'类':<16}content")
    for i, m in enumerate(messages):
        content = str(m.content).replace("\n", "\\n")
        if len(content) > 46:
            content = content[:46] + "…"
        print(f"  {i:<3}{m.type:<10}{type(m).__name__:<16}{content}")
    print()


def part_fixed() -> None:
    """最常用的一种：一串 (角色, 内容) 元组，占位符写在内容里。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。只依据政策回答，不引用外部知识。"),
        ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
        ("human", "只回答是否符合退货条件，一句话。"),
    ])
    print("模板 1 的输入变量：", prompt.input_variables)
    dump("1. ChatPromptTemplate.from_messages",
         prompt.format_messages(order_id="A1001", days=3, state="未拆封"))


def part_history() -> None:
    """对话历史这种"条数不定"的部分，用 MessagesPlaceholder 留一个洞。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。"),
        MessagesPlaceholder("history", optional=True),
        ("human", "{question}"),
    ])
    print("模板 2 的输入变量：", prompt.input_variables, "（optional 的变量不要求给）")
    dump("2a. MessagesPlaceholder，不给历史",
         prompt.format_messages(question="符合条件吗？"))
    dump("2b. MessagesPlaceholder，给两轮历史",
         prompt.format_messages(
             history=[HumanMessage("我上周买的能退吗？"), AIMessage("请问签收几天了？")],
             question="签收 3 天，未拆封，符合条件吗？"))


def part_fewshot() -> None:
    """示例也是 messages：先用一个模板描述"一问一答"的样子，再喂若干条。"""
    example_prompt = ChatPromptTemplate.from_messages([
        ("human", "{input}"),
        ("ai", "{output}"),
    ])
    few_shot = FewShotChatMessagePromptTemplate(
        example_prompt=example_prompt,
        examples=[
            {"input": "签收 3 天，未拆封", "output": "符合退货条件。"},
            {"input": "签收 20 天，未拆封", "output": "超期，不符合退货条件。"},
        ],
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是退货客服。判断是否符合退货条件。"),
        few_shot,
        ("human", "{question}"),
    ])
    print("模板 3 的输入变量：", prompt.input_variables)
    dump("3. FewShotChatMessagePromptTemplate",
         prompt.format_messages(question="签收 6 天，未拆封"))


def part_missing() -> None:
    """少给一个变量：报错在装 messages 那一步，不在调用模型那一步。"""
    prompt = ChatPromptTemplate.from_messages([
        ("human", "订单 {order_id}，签收 {days} 天。"),
    ])
    print("== 4. 少给一个变量 ==")
    try:
        prompt.format_messages(order_id="A1001")
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    print("  想输出字面的花括号，写成 {{days}}。")
    print()


def main() -> None:
    part_fixed()
    part_history()
    part_fewshot()
    part_missing()


if __name__ == "__main__":
    main()
