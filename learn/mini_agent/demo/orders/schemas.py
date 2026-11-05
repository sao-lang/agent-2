"""第 5 章 A10：这个例子的 pydantic 模型。

五个工具参数模型 + 一个最终答复模型。每份模型都是"约束表"，同时能导出
JSON Schema 给模型看（model_json_schema）——一份声明两处用。
换一道题时整个文件替换掉，core/ 只要求"存在一个 BaseModel 子类当输出结构"。
"""

from __future__ import annotations

# ── 第 5 章 A10：参数模型与输出结构 ──────────────────────────────────────────

from typing import Literal

from pydantic import BaseModel, Field


class OrderQuery(BaseModel):
    # 订单号必须是大写字母 + 4 位数字：正则约束挡住模型编造的 "A-1002"、"1002"
    order_id: str = Field(pattern=r"^[A-Z]\d{4}$", description="订单号，例如 A1002")


class PolicyQuery(BaseModel):
    # Literal 把取值锁成三选一：模型给"普通商品"会被判不合法并回灌，而不是静默走错分支
    category: Literal["普通", "生鲜", "定制"] = Field(default="普通", description="商品类别")


class FeeQuery(BaseModel):
    # 两个字段的组合约束：订单号格式 + 重量必须 >0 且 <=30
    # gt/le 是数值区间；不写的话模型给 0 或 300 公斤也会照算，结果是"算得出、但没意义"
    order_id: str = Field(pattern=r"^[A-Z]\d{4}$", description="订单号")
    weight_kg: float = Field(gt=0, le=30, description="退回包裹重量，公斤")


class ClauseQuery(BaseModel):
    # 与 PolicyQuery 同形：示例说明"同一份 schema 可以被多个工具复用"
    category: Literal["普通", "生鲜", "定制"] = Field(default="普通", description="商品类别")


class CouponQuery(BaseModel):
    # 只有订单号：这个工具会被用来演示"换参数打转"（结果是恒定值"无"）
    order_id: str = Field(pattern=r"^[A-Z]\d{4}$", description="订单号")


class Answer(BaseModel):
    """最终答复。字段少但都可判定，缺一个就回灌重来。"""

    # 结论只有三态：把"可能也许"这类自由文本压成枚举，才能被程序判断
    conclusion: Literal["可退", "不可退", "待定"]
    # ge=0：天数不能是负数；这是"结构校验"，语义对不对它管不了
    signed_days_ago: int = Field(ge=0, description="签收后第几天")
    # 同上：窗口天数也必须非负
    window_days: int = Field(ge=0, description="政策窗口天数")
    # 条款编号：min_length 挡住空串和"无"这种占位回答
    clause: str = Field(min_length=2, description="条款编号，例如 P-7")
    # 运费：ge=0 挡住负数；类型是 float，模型给 "9元" 会直接校验失败
    shipping_fee: float = Field(ge=0, description="退回运费，元")
    # 带上下界：太短没信息，太长会把整段话塞进来，破坏"结构化"的意义
    next_step: str = Field(min_length=4, max_length=60, description="给用户的一句下一步")


def describe_answer(answer: Answer) -> str:
    """把答复压成一行给人看。认识业务字段的函数只准待在 demo/ 里。"""
    return f"{answer.conclusion} / {answer.clause} / 运费 {answer.shipping_fee}"
