"""一个完整的手写 agent 循环：把第 1–8 章的重点串起来。

场景：退货客服。用户问「订单 A1002 签收 9 天了，能退吗？退货运费多少？」

覆盖的知识点（章号对应正文）：
  第 1 章  一次调用的形状：messages、finish_reason 四取值、usage
  第 2 章  稳定性：temperature 进请求、同一输入多跑几次要比较分布
  第 3 章  预算：累计 prompt token 与窗口预留
  第 4 章  提示词：角色/任务/约束/示例/输出格式/反例六要素
  第 5 章  pydantic：工具参数模型、结构化输出模型、校验失败回灌
  第 6 章  工具调用：tools 声明、tool_calls 解析、回灌三条格式
  第 7 章  终止：answered / max_steps / stalled 三态
  第 8 章  失控：请求指纹去重、结果指纹、单条裁剪、累计预算

离线运行：模型是脚本化假后端，按剧本回放固定响应，不联网。
    python code/knowledge/ch08_runaway/mini_agent.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError

# ────────────────────────────────── 第 5 章：工具参数与结构化输出

class OrderQuery(BaseModel):
    order_id: str = Field(pattern=r"^[A-Z]\d{4}$", description="订单号，例如 A1002")


class PolicyQuery(BaseModel):
    category: Literal["普通", "生鲜", "定制"] = Field(default="普通", description="商品类别")


class FeeQuery(BaseModel):
    order_id: str = Field(pattern=r"^[A-Z]\d{4}$", description="订单号")
    weight_kg: float = Field(gt=0, le=30, description="退回包裹重量，公斤")


class ClauseQuery(BaseModel):
    category: Literal["普通", "生鲜", "定制"] = Field(default="普通", description="商品类别")


class CouponQuery(BaseModel):
    order_id: str = Field(pattern=r"^[A-Z]\d{4}$", description="订单号")


class Answer(BaseModel):
    """最终答复。字段少但都可判定，缺一个就回灌重来。"""

    conclusion: Literal["可退", "不可退", "待定"]
    signed_days_ago: int = Field(ge=0, description="签收后第几天")
    window_days: int = Field(ge=0, description="政策窗口天数")
    clause: str = Field(min_length=2, description="条款编号，例如 P-7")
    shipping_fee: float = Field(ge=0, description="退回运费，元")
    next_step: str = Field(min_length=4, max_length=60, description="给用户的一句下一步")


# ────────────────────────────────── 第 6 章：tools 声明（schema 由模型生成）

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "查订单状态、签收天数与商品类别。只查本账号订单，订单号形如 A1002。",
            "parameters": OrderQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policy",
            "description": "查某一类商品的退货窗口与条款编号。窗口以本工具返回值为准。",
            "parameters": PolicyQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clause_text",
            "description": "取条款全文。很长，只在用户要求原文时调用。",
            "parameters": ClauseQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_coupon",
            "description": "查订单有没有可用优惠券。本平台目前一律返回「无」。",
            "parameters": CouponQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc_shipping_fee",
            "description": "算退回运费：首重 1kg 8 元，续重每公斤 2 元。",
            "parameters": FeeQuery.model_json_schema(),
        },
    },
]

ORDERS = {
    "A1001": {"status": "已签收", "signed_days_ago": 3, "category": "普通"},
    "A1002": {"status": "已签收", "signed_days_ago": 9, "category": "普通"},
    "B2001": {"status": "已签收", "signed_days_ago": 2, "category": "生鲜"},
}
POLICY = {
    "普通": {"window_days": 7, "clause": "P-7"},
    "生鲜": {"window_days": 1, "clause": "P-9"},
    "定制": {"window_days": 0, "clause": "P-12"},
}


def get_order(order_id: str) -> dict:
    if order_id not in ORDERS:
        raise KeyError(f"订单不存在：{order_id}")
    return {"order_id": order_id, **ORDERS[order_id]}


def get_policy(category: str) -> dict:
    return {"category": category, **POLICY[category]}


def calc_shipping_fee(order_id: str, weight_kg: float) -> dict:
    if order_id not in ORDERS:
        raise KeyError(f"订单不存在：{order_id}")
    fee = 8 + max(0.0, (weight_kg - 1)) * 2
    return {"order_id": order_id, "weight_kg": weight_kg, "fee": round(fee, 2)}


CLAUSE_TEXT = (
    "退货政策（节选）第一条 本政策适用于本平台自营商品。第二条 本政策所称签收，指物流系统记录的妥投时间；"
    "代收点签收视同本人签收。第三条 本政策所称退货，指退回商品并返还全部或部分货款。第四条 本政策所称七日，"
    "按自然日计算，签收当日为第零日。第五条 消费者自签收之日起七日内，商品完好的，可以无理由退货。"
    "第六条 商品完好指商品本身、配件、商标标识齐全。第七条 下列商品不适用无理由退货：定作商品、鲜活易腐商品、"
    "在线下载或拆封的音像制品、交付的报纸期刊。第八条 前条各项经营者应当以显著方式提示并经消费者确认。"
    "第九条 消费者退回商品时应当一并退回配件、赠品与发票。第十条 商品存在质量问题的，不受七日限制，"
    "消费者可以自签收之日起十五日内要求退货。第十一条 质量问题退货的运费由经营者承担。"
    "第十二条 消费者主张质量问题的，应当提供能够证明问题存在的照片或检测报告。"
)


def get_clause_text(category: str) -> dict:
    """故意返回一段长文本：用来触发第 8 章的单条裁剪。"""
    return {"category": category, "text": CLAUSE_TEXT}


def check_coupon(order_id: str) -> dict:
    """所有订单都返回同一个结果：用来触发结果指纹。"""
    return {"coupon": "无", "note": "本平台目前不发券"}


TOOL_IMPL: dict[str, tuple[Callable[..., dict], type[BaseModel]]] = {
    "get_order": (get_order, OrderQuery),
    "get_policy": (get_policy, PolicyQuery),
    "calc_shipping_fee": (calc_shipping_fee, FeeQuery),
    "get_clause_text": (get_clause_text, ClauseQuery),
    "check_coupon": (check_coupon, CouponQuery),
}

# ────────────────────────────────── 第 1 章：消息与响应的形状

ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL = "system", "user", "assistant", "tool"


def system_msg(text: str) -> dict:
    return {"role": ROLE_SYSTEM, "content": text}


def user_msg(text: str) -> dict:
    return {"role": ROLE_USER, "content": text}


def tool_msg(call_id: str, content: str) -> dict:
    """回灌三条格式：role=tool、tool_call_id 配对、content 是字符串。"""
    return {"role": ROLE_TOOL, "tool_call_id": call_id, "content": content}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Reply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_assistant_message(self) -> dict:
        """原样保留：arguments 那串文字必须是模型当初生成的那一份。"""
        msg: dict[str, Any] = {"role": ROLE_ASSISTANT, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return msg


# ────────────────────────────────── 第 4 章：提示词六要素

SYSTEM_PROMPT = """# 角色
你是电商退货客服，只处理退货相关问题。

# 任务
判断某一笔订单能否退货，并算出入选退货时的退回运费。

# 约束
- 签收天数与政策窗口必须来自工具返回，不许用常识补。
- 结论只能是 可退 / 不可退 / 待定 三者之一。
- 缺少订单号时先索取，不要猜。

# 示例
问：订单 A1001 能退吗？  答：先调 get_order(A1001)，再调 get_policy(类别)，最后按两个数字判定。

# 输出格式
只输出一个 JSON 对象，字段：conclusion、signed_days_ago、window_days、clause、shipping_fee、next_step。
不要用 markdown 代码块包裹。

# 反例
不要输出「通常 7 天」这类没有来源的数字；不要在没有签收天数时给出结论。
"""

# ────────────────────────────────── 模型：脚本化假后端

class FakeModel:
    """按剧本回放响应。第 8 章的守卫要对着真实结构，所以这里只替换网络那一层。"""

    def __init__(self, plan: list[Reply], temperature: float = 0.0) -> None:
        self.plan = plan
        self.temperature = temperature
        self.calls = 0

    def complete(self, messages: list[dict]) -> Reply:
        if self.calls >= len(self.plan):
            return Reply(content='{"conclusion":"待定"}', finish_reason="stop", prompt_tokens=50, completion_tokens=5)
        reply = self.plan[self.calls]
        self.calls += 1
        return reply


# ────────────────────────────────── 第 7、8 章：循环、状态与守卫

RUNNING, ANSWERED, MAX_STEPS, STALLED, BUDGET, FILTERED, TRUNCATED_OUT = (
    "RUNNING", "ANSWERED", "MAX_STEPS", "STALLED", "BUDGET", "FILTERED", "TRUNCATED_OUT",
)


@dataclass
class Stats:
    steps: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duplicate_blocked: int = 0
    arg_errors: int = 0
    schema_retries: int = 0
    truncated: int = 0
    trimmed: int = 0
    repeated_result: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def fingerprint(name: str, arguments: str) -> str:
    """第 8 章：请求指纹。键序必须归一，否则同一请求会被当成两次。"""
    try:
        normalized = json.dumps(json.loads(arguments), sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        normalized = arguments
    return f"{name}|{normalized}"


def trim_tool_content(content: str, limit: int = 200) -> str:
    """第 8 章：单条裁剪。留头留尾，中间插入标记，不整段丢。"""
    if len(content) <= limit:
        return content
    head = content[: limit // 2]
    tail = content[-(limit // 2):]
    return f"{head}…[截断 {len(content) - limit} 字]…{tail}"


def to_feedback(exc: ValidationError) -> str:
    """第 5 章：把校验错误压成模型能读的三列，不夹带堆栈。"""
    lines = ["你上一次的输出不合法，请只输出 JSON 对象，字段如下："]
    for err in exc.errors():
        field_name = ".".join(str(p) for p in err["loc"])
        lines.append(f"- {field_name}: {err['msg']}（你给的是 {err['input']!r}）")
    return "\n".join(lines)


def run(
    question: str,
    plan: list[Reply],
    *,
    max_steps: int = 10,
    max_prompt_tokens: int = 2400,
    max_dup_in_row: int = 2,
    verbose: bool = True,
) -> tuple[str, Answer | None, Stats]:
    model = FakeModel(plan)
    messages: list[dict] = [system_msg(SYSTEM_PROMPT), user_msg(question)]
    stats = Stats()
    seen: set[str] = set()
    seen_results: dict[str, str] = {}
    dup_in_row = 0
    same_result_in_row = 0
    status = RUNNING
    answer: Answer | None = None

    for step in range(1, max_steps + 1):
        stats.steps = step
        if stats.prompt_tokens > max_prompt_tokens:
            status = BUDGET
            break

        reply = model.complete(messages)
        stats.prompt_tokens += reply.prompt_tokens
        stats.completion_tokens += reply.completion_tokens
        messages.append(reply.as_assistant_message())

        # 第 1 章：先看 finish_reason，再看 content
        if reply.finish_reason == "content_filter":
            status = FILTERED
            if verbose:
                print(f"  步 {step} 中止：content_filter，重试无效")
            break

        if reply.finish_reason == "length":
            stats.truncated += 1
            messages.append(user_msg("上一条被截断，请只输出完整的 JSON 对象，不要重复已说过的内容。"))
            if verbose:
                print(f"  步 {step} 截断：已回灌续写指令（第 {stats.truncated} 次）")
            continue

        if reply.finish_reason == "tool_calls":
            executed_any = False
            for call in reply.tool_calls:
                stats.tool_calls += 1
                fp = fingerprint(call.name, call.arguments)
                if fp in seen:
                    stats.duplicate_blocked += 1
                    dup_in_row += 1
                    messages.append(tool_msg(call.id, "重复调用：这一次请求与之前完全相同，结果上面已经有了，请直接用它。"))
                    if verbose:
                        print(f"  步 {step} 工具 {call.name}：重复指纹被拦下（本步第 {stats.duplicate_blocked} 次）")
                    continue
                seen.add(fp)
                dup_in_row = 0
                executed_any = True

                impl, arg_model = TOOL_IMPL[call.name]
                try:
                    args = arg_model.model_validate_json(call.arguments)
                except ValidationError as exc:
                    stats.arg_errors += 1
                    messages.append(tool_msg(call.id, f"参数不合法，请按 schema 重发：{to_feedback(exc)}"))
                    if verbose:
                        print(f"  步 {step} 工具 {call.name}：参数 JSON 解析失败，已回灌错误")
                    continue

                try:
                    result = impl(**args.model_dump())
                except KeyError as exc:
                    messages.append(tool_msg(call.id, json.dumps({"error": str(exc)}, ensure_ascii=False)))
                    if verbose:
                        print(f"  步 {step} 工具 {call.name}：业务错误 -> {exc}")
                    continue

                payload = json.dumps(result, ensure_ascii=False)
                trimmed = trim_tool_content(payload)
                if trimmed != payload:
                    stats.trimmed += 1
                # 结果指纹：请求换了、结果没换，说明在换参数打转
                if trimmed in seen_results:
                    stats.repeated_result += 1
                    same_result_in_row += 1
                    if verbose:
                        print(f"  步 {step} 工具 {call.name}：结果与 {seen_results[trimmed]} 那次完全相同")
                else:
                    seen_results[trimmed] = call.name
                    same_result_in_row = 0
                messages.append(tool_msg(call.id, trimmed))
                if verbose:
                    print(f"  步 {step} 工具 {call.name}：{payload[:70]}")

            if same_result_in_row >= max_dup_in_row:
                status = STALLED
                if verbose:
                    print(f"  步 {step} 判定空转：连续 {same_result_in_row} 次拿到相同结果")
                break
            if dup_in_row >= max_dup_in_row:
                status = STALLED
                if verbose:
                    print(f"  步 {step} 判定空转：连续 {dup_in_row} 次重复请求")
                break
            if not executed_any and not reply.tool_calls:
                status = STALLED
                break
            continue

        # finish_reason == "stop"：尝试结构化输出
        raw = reply.content or ""
        if raw.strip() == '{"conclusion":"待定"}':
            status = TRUNCATED_OUT
            break
        try:
            answer = Answer.model_validate_json(raw)
            status = ANSWERED
            if verbose:
                print(f"  步 {step} 结构化输出通过：{answer.conclusion} / {answer.clause} / 运费 {answer.shipping_fee}")
            break
        except ValidationError as exc:
            stats.schema_retries += 1
            messages.append(user_msg(to_feedback(exc)))
            if verbose:
                print(f"  步 {step} 结构化输出不合法，回灌字段三列（第 {stats.schema_retries} 次）")
            continue

    else:
        status = MAX_STEPS

    if verbose:
        print(
            f"  结果：status={status} 步数={stats.steps} 工具调用={stats.tool_calls} "
            f"token={stats.prompt_tokens}+{stats.completion_tokens}={stats.total_tokens} "
            f"重复拦截={stats.duplicate_blocked} 参数错误={stats.arg_errors} "
            f"结构化重试={stats.schema_retries} 截断={stats.truncated} 裁剪={stats.trimmed} "
            f"结果重复={stats.repeated_result}"
        )
    return status, answer, stats


# ────────────────────────────────── 三份剧本

QUESTION = "订单 A1002 签收 9 天了，能退吗？退货运费多少？"

GOOD_PLAN = [
    Reply(None, [ToolCall("c1", "get_order", '{"order_id":"A1002"}')], "tool_calls", 96, 12),
    Reply(None, [ToolCall("c2", "get_policy", '{"category":"普通"}')], "tool_calls", 140, 14),
    # 同一请求换一种键序与空格：指纹归一后仍应被拦下
    Reply(None, [ToolCall("c3", "get_order", '{ "order_id" : "A1002" }')], "tool_calls", 176, 12),
    # 参数不是合法 JSON
    Reply(None, [ToolCall("c4", "calc_shipping_fee", '{"order_id":"A1002", weight_kg:1.5}')], "tool_calls", 214, 16),
    # 业务错误：订单不存在
    Reply(None, [ToolCall("c5", "calc_shipping_fee", '{"order_id":"Z9999","weight_kg":1.5}')], "tool_calls", 246, 16),
    Reply(None, [ToolCall("c6", "calc_shipping_fee", '{"order_id":"A1002","weight_kg":1.5}')], "tool_calls", 280, 16),
    # 长文本：超过单条上限，触发裁剪
    Reply(None, [ToolCall("c7", "get_clause_text", '{"category":"普通"}')], "tool_calls", 300, 18),
    # 截断
    Reply("结论：不可退。依据：签收后第 9 天，", [], "length", 300, 24),
    # 合法 JSON 但缺字段
    Reply('{"conclusion":"不可退","clause":"P-7"}', [], "stop", 320, 18),
    Reply(
        json.dumps(
            {
                "conclusion": "不可退",
                "signed_days_ago": 9,
                "window_days": 7,
                "clause": "P-7",
                "shipping_fee": 9.0,
                "next_step": "已过 7 天窗口，如属质量问题请提供照片走质量通道",
            },
            ensure_ascii=False,
        ),
        [],
        "stop",
        356,
        42,
    ),
]

STALL_PLAN = [
    Reply(None, [ToolCall("d1", "get_order", '{"order_id":"A1002"}')], "tool_calls", 96, 12),
    Reply(None, [ToolCall("d2", "get_order", '{"order_id":"A1002"}')], "tool_calls", 140, 12),
    Reply(None, [ToolCall("d3", "get_order", '{"order_id":"A1002"}')], "tool_calls", 180, 12),
]

RESULT_PLAN = [
    Reply(None, [ToolCall("f1", "check_coupon", '{"order_id":"A1001"}')], "tool_calls", 96, 12),
    Reply(None, [ToolCall("f2", "check_coupon", '{"order_id":"A1002"}')], "tool_calls", 140, 12),
    Reply(None, [ToolCall("f3", "check_coupon", '{"order_id":"B2001"}')], "tool_calls", 180, 12),
]

BUDGET_PLAN = [
    Reply(None, [ToolCall("e1", "get_order", '{"order_id":"A1002"}')], "tool_calls", 380, 12),
    Reply(None, [ToolCall("e2", "get_policy", '{"category":"普通"}')], "tool_calls", 420, 14),
    Reply(None, [ToolCall("e3", "calc_shipping_fee", '{"order_id":"A1002","weight_kg":1.5}')], "tool_calls", 460, 16),
    Reply("{}", [], "stop", 500, 20),
]


def main() -> None:
    print("=== 1. 正常路径：查单 → 查政策 → 算运费 → 结构化答复 ===")
    status, answer, _ = run(QUESTION, GOOD_PLAN)
    if answer:
        print("  最终答复：", answer.model_dump())

    print("\n=== 2. 空转：同一请求第三次仍重发 ===")
    run(QUESTION, STALL_PLAN)

    print("\n=== 3. 换参数打转：请求不同、结果相同 ===")
    run("这几单有优惠券吗？", RESULT_PLAN)

    print("\n=== 4. 预算：累计 prompt token 触顶 ===")
    run(QUESTION, BUDGET_PLAN, max_prompt_tokens=400)


if __name__ == "__main__":
    main()
