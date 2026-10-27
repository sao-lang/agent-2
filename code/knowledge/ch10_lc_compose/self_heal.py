"""两个自愈解析器：OutputFixingParser 与 RetryOutputParser。

导入路径是本章唯一一处不在 langchain_core 的名字：
    from langchain_classic.output_parsers import OutputFixingParser, RetryOutputParser
`langchain.output_parsers` 在 1.4.7 里已经不存在，import 会报 ModuleNotFoundError。

没有 API key：模型换成本地脚本化后端，**原理演示，不是模型实测**。
从仓库根目录运行：
    $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch10_lc_compose/self_heal.py
"""

from __future__ import annotations

from langchain_classic.output_parsers import OutputFixingParser, RetryOutputParser
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from scripted_chat import chat_completion, scripted_chat

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是退货客服。只输出 JSON，不要 markdown 包裹。"),
    ("human", "订单 {order_id}，签收 {days} 天，商品状态 {state}。判定是否符合退货条件。"),
])
CASE = {"order_id": "A1001", "days": 3, "state": "未拆封"}

GOOD = '{"order_id": "A1001", "eligible": true, "days": 3, "reason": "未拆封且在七天内"}'
# 第一次的坏输出：读得懂，但不是合法 JSON（中文引号、前缀说明、缺 reason）
BAD = '判定结果：{“order_id”: “A1001”, “eligible”: true, “days”: 3}'

CALLS = {"n": 0}


class RefundVerdict(BaseModel):
    order_id: str = Field(description="订单号")
    eligible: bool = Field(description="是否符合退货条件")
    days: int = Field(description="签收天数")
    reason: str = Field(description="不超过 20 字的理由")


def bad_model():
    """每次都输出不合法 JSON 的模型。"""
    def respond(index: int, body: dict):
        CALLS["n"] += 1
        return chat_completion(BAD, usage=(42, 7))
    return scripted_chat(respond)


def fixer_model(seen: list[str]):
    """修复模型：把收到的最后一条消息记下来，返回合法 JSON。"""
    def respond(index: int, body: dict):
        CALLS["n"] += 1
        seen.append(body["messages"][-1]["content"])
        return chat_completion(GOOD, usage=(60, 20))
    return scripted_chat(respond)


def error_block(text: str) -> str:
    """从 NAIVE_FIX_PROMPT 装出来的消息里，只截 Error 那一段。"""
    marker = "Error:\n--------------\n"
    if marker not in text:
        return text[:200]
    return text.split(marker, 1)[1].split("--------------", 1)[0].strip()


def part_no_heal(parser) -> None:
    CALLS["n"] = 0
    print("== 0. 不自愈：一次调用，一个异常 ==")
    try:
        (PROMPT | bad_model() | parser).invoke(CASE)
    except Exception as e:
        print(f"{type(e).__name__}: {str(e).splitlines()[0]}")
    print(f"模型调用次数：{CALLS['n']}，解析成功 0 次")
    print()


def part_fixing(parser) -> None:
    CALLS["n"] = 0
    seen: list[str] = []
    fixing = OutputFixingParser.from_llm(parser=parser, llm=fixer_model(seen))
    out = (PROMPT | bad_model() | fixing).invoke(CASE)
    print("== 1. OutputFixingParser：只交坏文本，改格式 ==")
    print(f"输出 {type(out).__name__}：{out}")
    print(f"模型调用次数：{CALLS['n']}（第一次出坏文本，解析失败；第二次修格式）")
    print("修复模型收到的 Error 段：")
    print("  " + error_block(seen[0]).replace("\n", "\n  "))
    print()


def part_retry(parser) -> None:
    CALLS["n"] = 0
    seen: list[str] = []
    retry = RetryOutputParser.from_llm(parser=parser, llm=fixer_model(seen), max_retries=1)
    prompt_value = PROMPT.invoke(CASE)
    out = retry.parse_with_prompt(completion=BAD, prompt_value=prompt_value)
    print("== 2. RetryOutputParser：把原始 prompt 一起带回 ==")
    print(f"输出 {type(out).__name__}：{out}")
    print(f"模型调用次数：{CALLS['n']}（这次坏文本是直接给的，只有重试这一次调用）")
    print("重试请求里带上的 Prompt 段：")
    head = seen[0].split("Completion:", 1)[0].strip()
    print("  " + head.replace("\n", "\n  "))
    print()


def main() -> None:
    parser = PydanticOutputParser(pydantic_object=RefundVerdict)
    part_no_heal(parser)
    part_fixing(parser)
    part_retry(parser)


if __name__ == "__main__":
    main()
