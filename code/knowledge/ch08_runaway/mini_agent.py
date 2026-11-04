"""一个完整的手写 agent 循环，接真实模型：把文件顶部的参数填上，直接运行。

支持任何 OpenAI 兼容端点（DeepSeek、通义、Moonshot、vLLM、Ollama 都可以）：

    # 1. 打开本文件，改这一段
    BASE_URL = "https://api.deepseek.com/v1"
    API_KEY  = "sk-你自己的key"
    MODEL    = "deepseek-chat"

    # 2. 运行
    python code/knowledge/ch08_runaway/mini_agent.py

没有 key 也能跑通全链路：先起同目录的 mock 服务，再把 BASE_URL 指到它。

    python code/knowledge/ch08_runaway/mock_openai.py      # 默认 8899 端口
    # 然后把 BASE_URL 改成 "http://127.0.0.1:8899/v1"，API_KEY 随便填

覆盖的知识点（章号对应正文）：
  第 1 章  一次调用的形状：messages、finish_reason 四取值、usage
  第 2 章  稳定性：temperature 进请求、结果要靠多次运行比较
  第 3 章  预算：累计 prompt token 与窗口预留
  第 4 章  提示词：角色/任务/约束/示例/输出格式/反例六要素
  第 5 章  pydantic：工具参数模型、结构化输出模型、校验失败回灌
  第 6 章  工具调用：tools 声明、tool_calls 解析、回灌三条格式
  第 7 章  终止：answered / max_steps / stalled 三态
  第 8 章  失控：请求指纹去重、结果指纹、单条裁剪、累计预算
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

# ────────────────────────────────── 要你自己填的参数

BASE_URL = "https://api.deepseek.com/v1"   # 换厂商只改这一行
API_KEY = "sk-在这里填你自己的key"
MODEL = "deepseek-chat"

QUESTION = "订单 A1002 签收 9 天了，能退吗？退货运费多少？"

TEMPERATURE = 0.0        # 结构化输出用低温
STEP_LIMIT = 12            # 步数上限：超了就是 MAX_STEPS
TOKEN_BUDGET = 20000       # 累计输入 token 上限：超了就是 BUDGET

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


# ────────────────────────────────── 第 6 章：tools 声明（schema 由 pydantic 生成）

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
            "name": "calc_shipping_fee",
            "description": "算退回运费：首重 1kg 8 元，续重每公斤 2 元。",
            "parameters": FeeQuery.model_json_schema(),
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
CLAUSE_TEXT = (
    "退货政策（节选）第一条 本政策适用于本平台自营商品。第二条 本政策所称签收，指物流系统记录的妥投时间；"
    "代收点签收视同本人签收。第三条 本政策所称退货，指退回商品并返还全部或部分货款。第四条 本政策所称七日，"
    "按自然日计算，签收当日为第零日。第五条 消费者自签收之日起七日内，商品完好的，可以无理由退货。"
    "第六条 商品完好指商品本身、配件、商标标识齐全。第七条 下列商品不适用无理由退货：定作商品、鲜活易腐商品、"
    "在线下载或拆封的音像制品、交付的报纸期刊。第十条 商品存在质量问题的，不受七日限制，"
    "消费者可以自签收之日起十五日内要求退货。第十二条 消费者主张质量问题的，应当提供照片或检测报告。"
)


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


def get_clause_text(category: str) -> dict:
    return {"category": category, "text": CLAUSE_TEXT}


def check_coupon(order_id: str) -> dict:
    return {"coupon": "无", "note": "本平台目前不发券"}


TOOL_IMPL: dict[str, tuple[Callable[..., dict], type[BaseModel]]] = {
    "get_order": (get_order, OrderQuery),
    "get_policy": (get_policy, PolicyQuery),
    "calc_shipping_fee": (calc_shipping_fee, FeeQuery),
    "get_clause_text": (get_clause_text, ClauseQuery),
    "check_coupon": (check_coupon, CouponQuery),
}

# ────────────────────────────────── 第 1 章：消息形状

ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL = "system", "user", "assistant", "tool"


def tool_msg(call_id: str, content: str) -> dict:
    """回灌三条格式：role=tool、tool_call_id 配对、content 是字符串。"""
    return {"role": ROLE_TOOL, "tool_call_id": call_id, "content": content}


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

# ────────────────────────────────── 第 7、8 章：状态与守卫

RUNNING, ANSWERED, MAX_STEPS, STALLED, BUDGET, FILTERED = (
    "RUNNING", "ANSWERED", "MAX_STEPS", "STALLED", "BUDGET", "FILTERED",
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
    try:
        normalized = json.dumps(json.loads(arguments), sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        normalized = arguments
    return f"{name}|{normalized}"


def trim_tool_content(content: str, limit: int = 200) -> str:
    if len(content) <= limit:
        return content
    head = content[: limit // 2]
    tail = content[-(limit // 2):]
    return f"{head}…[截断 {len(content) - limit} 字]…{tail}"


def to_feedback(exc: ValidationError) -> str:
    lines = ["你上一次的输出不合法，请只输出 JSON 对象，字段如下："]
    for err in exc.errors():
        field_name = ".".join(str(p) for p in err["loc"])
        lines.append(f"- {field_name}: {err['msg']}（你给的是 {err['input']!r}）")
    return "\n".join(lines)


def run(
    question: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_steps: int | None = None,
    max_prompt_tokens: int | None = None,
    max_dup_in_row: int = 2,
    verbose: bool = True,
) -> tuple[str, Answer | None, Stats]:
    # 参数缺省时读文件顶部的常量；放在函数体内读，改常量不必改函数签名
    question = question or QUESTION
    base_url = base_url or BASE_URL
    api_key = api_key or API_KEY
    model = model or MODEL
    temperature = TEMPERATURE if temperature is None else temperature
    max_steps = STEP_LIMIT if max_steps is None else max_steps
    max_prompt_tokens = TOKEN_BUDGET if max_prompt_tokens is None else max_prompt_tokens

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0, max_retries=1)
    messages: list[dict] = [
        {"role": ROLE_SYSTEM, "content": SYSTEM_PROMPT},
        {"role": ROLE_USER, "content": question},
    ]
    stats = Stats()
    seen: set[str] = set()
    seen_results: dict[str, str] = {}
    dup_in_row = same_result_in_row = 0
    status = RUNNING
    answer: Answer | None = None

    for step in range(1, max_steps + 1):
        stats.steps = step
        if stats.prompt_tokens > max_prompt_tokens:
            status = BUDGET
            if verbose:
                print(f"  步 {step} 预算用尽：{stats.prompt_tokens} > {max_prompt_tokens}")
            break

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            temperature=temperature,
        )
        choice = resp.choices[0]
        finish = choice.finish_reason
        if resp.usage:
            stats.prompt_tokens += resp.usage.prompt_tokens
            stats.completion_tokens += resp.usage.completion_tokens

        assistant: dict[str, Any] = {"role": ROLE_ASSISTANT, "content": choice.message.content}
        if choice.message.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in choice.message.tool_calls
            ]
        messages.append(assistant)

        if finish == "content_filter":
            status = FILTERED
            if verbose:
                print(f"  步 {step} 中止：content_filter，重试无效")
            break

        if finish == "length":
            stats.truncated += 1
            messages.append({"role": ROLE_USER, "content": "上一条被截断，请只输出完整的 JSON 对象。"})
            if verbose:
                print(f"  步 {step} 截断：已回灌续写指令")
            continue

        if finish == "tool_calls":
            for call in choice.message.tool_calls or []:
                stats.tool_calls += 1
                fp = fingerprint(call.function.name, call.function.arguments)
                if fp in seen:
                    stats.duplicate_blocked += 1
                    dup_in_row += 1
                    messages.append(tool_msg(call.id, "重复调用：这次请求与之前完全相同，结果上面已经有了。"))
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：重复指纹被拦下")
                    continue
                seen.add(fp)
                dup_in_row = 0

                impl, arg_model = TOOL_IMPL[call.function.name]
                try:
                    args = arg_model.model_validate_json(call.function.arguments)
                except ValidationError as exc:
                    stats.arg_errors += 1
                    messages.append(tool_msg(call.id, f"参数不合法，请按 schema 重发：{to_feedback(exc)}"))
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：参数解析失败，已回灌错误")
                    continue

                try:
                    result = impl(**args.model_dump())
                except KeyError as exc:
                    messages.append(tool_msg(call.id, json.dumps({"error": str(exc)}, ensure_ascii=False)))
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：业务错误 -> {exc}")
                    continue

                payload = json.dumps(result, ensure_ascii=False)
                trimmed = trim_tool_content(payload)
                if trimmed != payload:
                    stats.trimmed += 1
                if trimmed in seen_results:
                    stats.repeated_result += 1
                    same_result_in_row += 1
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：结果与上一次完全相同")
                else:
                    seen_results[trimmed] = call.function.name
                    same_result_in_row = 0
                messages.append(tool_msg(call.id, trimmed))
                if verbose:
                    print(f"  步 {step} 工具 {call.function.name}：{payload[:70]}")

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
            continue

        raw = (choice.message.content or "").strip()
        try:
            answer = Answer.model_validate_json(raw)
            status = ANSWERED
            if verbose:
                print(f"  步 {step} 结构化输出通过：{answer.conclusion} / {answer.clause} / 运费 {answer.shipping_fee}")
            break
        except ValidationError as exc:
            stats.schema_retries += 1
            messages.append({"role": ROLE_USER, "content": to_feedback(exc)})
            if verbose:
                print(f"  步 {step} 结构化输出不合法，回灌字段三列")
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


def main() -> int:
    if not API_KEY or API_KEY.startswith("sk-在这里"):
        print("先把文件顶部的 API_KEY 填上（或用 mock_openai.py 起本地服务）。", file=sys.stderr)
        return 2

    print(f"模型：{MODEL}　端点：{BASE_URL}")
    print(f"问题：{QUESTION}")
    status, answer, _stats = run(verbose=True)
    print("\n最终答复：")
    if answer:
        print(json.dumps(answer.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(f"（无结构化答复，status={status}）")
    return 0 if status == ANSWERED else 1


if __name__ == "__main__":
    raise SystemExit(main())
