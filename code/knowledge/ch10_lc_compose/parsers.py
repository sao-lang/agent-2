"""四个输出解析器，各跑一次，附 format_instructions。

没有 API key：模型换成本地脚本化后端，**原理演示，不是模型实测**。
从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/parsers.py
"""

from __future__ import annotations

from langchain_core.output_parsers import (CommaSeparatedListOutputParser, JsonOutputParser,
                                           PydanticOutputParser, StrOutputParser)
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from scripted_chat import chat_completion, scripted_chat

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只输出结果，不要解释。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态：{state}。"),
])
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}


def model_saying(text: str):
    def respond(index: int, body: dict):
        return chat_completion(text, usage=(42, 7))
    return scripted_chat(respond)


class RefundVerdict(BaseModel):
    """判定的结构。字段名就是要写进 JSON 的键名。"""

    order_id: str = Field(description="订单号，例如 A1001")
    eligible: bool = Field(description="是否符合退货条件")
    days: int = Field(description="签收天数")
    reason: str = Field(description="不超过 20 字的理由")


def str_parser() -> None:
    chain = PROMPT | model_saying("符合退货条件。") | StrOutputParser()
    out = chain.invoke(CASE)
    print("== StrOutputParser ==")
    print(f"输出 {type(out).__name__}：{out!r}")
    print("它不做任何解析，只把 AIMessage 的 content 取出来。")
    print()


def json_parser() -> None:
    text = '{"order_id": "A1001", "eligible": true, "days": 3, "reason": "未拆封且在七天内"}'
    parser = JsonOutputParser()
    chain = PROMPT | model_saying(text) | parser
    out = chain.invoke(CASE)
    print("== JsonOutputParser ==")
    print(f"输出 {type(out).__name__}：{out}")
    print("format_instructions：")
    print(parser.get_format_instructions())
    print()

    print("喂一段不是 JSON 的文本：")
    try:
        parser.invoke("符合退货条件。")
    except Exception as e:
        print(f"  {type(e).__name__}: {str(e).splitlines()[0]}")
    print()


def pydantic_parser() -> None:
    text = '{"order_id": "A1001", "eligible": true, "days": 3, "reason": "未拆封且在七天内"}'
    parser = PydanticOutputParser(pydantic_object=RefundVerdict)
    chain = PROMPT | model_saying(text) | parser
    out = chain.invoke(CASE)
    print("== PydanticOutputParser ==")
    print(f"输出 {type(out).__name__}：{out}")
    print(f"取字段：out.eligible={out.eligible}，type={type(out.eligible).__name__}")
    print("get_format_instructions()：")
    print(parser.get_format_instructions())
    print()

    print("喂一段缺字段的 JSON：")
    try:
        parser.invoke('{"order_id": "A1001", "eligible": true}')
    except Exception as e:
        lines = str(e).splitlines()
        print(f"  {type(e).__name__}: {lines[0]}")
        for line in lines[1:4]:
            print(f"  {line}")
    print()


def list_parser() -> None:
    text = "退货, 换货, 维修"
    parser = CommaSeparatedListOutputParser()
    chain = PROMPT | model_saying(text) | parser
    out = chain.invoke(CASE)
    print("== CommaSeparatedListOutputParser ==")
    print(f"输出 {type(out).__name__}：{out}")
    print("format_instructions：")
    print(parser.get_format_instructions())
    print()


def main() -> None:
    str_parser()
    json_parser()
    pydantic_parser()
    list_parser()


if __name__ == "__main__":
    main()
