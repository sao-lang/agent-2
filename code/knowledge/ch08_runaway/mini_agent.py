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

验证方法见 learn/1-8章验证手册.md。本文件里每个 `# ── 第 N 章` 标记都是一节，
手册按标记定位，不按行号（改注释不会让手册失效）。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Literal

from openai import OpenAI                      # 只用来发 HTTP POST；协议细节由 SDK 编码
from pydantic import BaseModel, Field, ValidationError   # 第 5 章：声明式校验

# ── 第 3 章 A4/A6：要你自己填的参数（改这里，不改代码）────────────────────────
# 为什么放模块顶层：它们是"一次调用的四个输入"里由调用方决定的部分（第 1 章 A1）。
# 验证手册里所有"改一个常量"的练习，改的就是下面这几行。

BASE_URL = "https://api.deepseek.com/v1"   # 换厂商只改这一行：端点决定词表，进而决定 token 数
API_KEY = "sk-在这里填你自己的key"           # 占位符会被 main() 拦住，避免拿空 key 跑
MODEL = "deepseek-chat"                     # 模型名决定单价与窗口大小，成本算错通常错在这

QUESTION = "订单 A1002 签收 9 天了，能退吗？退货运费多少？"   # 一次任务的目标，进 user 消息

TEMPERATURE = 0.0        # 第 2 章 A7：0 表示取最高概率，不等于"取消随机"，只表示分布被压窄
STEP_LIMIT = 12          # 第 7 章 B2：步数上限。下界来自任务本身，上界来自成本
TOKEN_BUDGET = 20000     # 第 8 章：成本击穿的闸门，累计"输入 token"超了就停

# ── 第 5 章 A10：工具参数的声明式结构 ─────────────────────────────────────────
# 每个模型都是一份"约束表"：pattern/gt/le/Literal 就是校验规则，
# 同时它还能导出 JSON Schema 给模型看（model_json_schema），一份声明两处用。


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

# ── 第 6 章 B1：tools 声明（schema 由 pydantic 模型生成）──────────────────────
# 三段各管一件事：name 决定"调不调"，description 决定"该不该调"，
# parameters 决定"填什么"。schema 从模型生成，所以参数说明只写一次。

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",                    # 固定值：表明这是函数型工具
        "function": {
            "name": "get_order",               # 模型只会照抄这个名字，能不能执行取决于 TOOL_IMPL
            "description": "查订单状态、签收天数与商品类别。只查本账号订单，订单号形如 A1002。",
            "parameters": OrderQuery.model_json_schema(),   # A10：同一份声明导出的 JSON Schema
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
            # "很长，只在用户要求原文时调用"——这句话决定模型平时不会去调它，
            # 所以它天然是"上下文爆炸"的触发器（第 8 章）
            "description": "取条款全文。很长，只在用户要求原文时调用。",
            "parameters": ClauseQuery.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_coupon",
            # "一律返回「无」"——恒定结果，天然是"换参数打转"的触发器（第 8 章）
            "description": "查订单有没有可用优惠券。本平台目前一律返回「无」。",
            "parameters": CouponQuery.model_json_schema(),
        },
    },
]

# ── 第 6 章：工具的真实实现。注意它和 TOOLS 是两份东西 ────────────────────────
# 声明（给模型看）与实现（给调用方执行）分离，这是"模型没有副作用能力"的直接体现。

ORDERS = {
    # 三笔订单覆盖三种场景：A1001 在窗口内、A1002 已过窗口、B2001 是生鲜（窗口只有 1 天）
    "A1001": {"status": "已签收", "signed_days_ago": 3, "category": "普通"},
    "A1002": {"status": "已签收", "signed_days_ago": 9, "category": "普通"},
    "B2001": {"status": "已签收", "signed_days_ago": 2, "category": "生鲜"},
}
# 政策表：窗口天数与条款编号是"事实"，必须来自这里，不能来自模型常识（第 2 章 A3 弱依据）
POLICY = {
    "普通": {"window_days": 7, "clause": "P-7"},
    "生鲜": {"window_days": 1, "clause": "P-9"},
    "定制": {"window_days": 0, "clause": "P-12"},
}
# 长文本，约 300 字：用来触发单条裁剪（第 8 章 B5），也是"上下文爆炸"的素材
CLAUSE_TEXT = (
    "退货政策（节选）第一条 本政策适用于本平台自营商品。第二条 本政策所称签收，指物流系统记录的妥投时间；"
    "代收点签收视同本人签收。第三条 本政策所称退货，指退回商品并返还全部或部分货款。第四条 本政策所称七日，"
    "按自然日计算，签收当日为第零日。第五条 消费者自签收之日起七日内，商品完好的，可以无理由退货。"
    "第六条 商品完好指商品本身、配件、商标标识齐全。第七条 下列商品不适用无理由退货：定作商品、鲜活易腐商品、"
    "在线下载或拆封的音像制品、交付的报纸期刊。第十条 商品存在质量问题的，不受七日限制，"
    "消费者可以自签收之日起十五日内要求退货。第十二条 消费者主张质量问题的，应当提供照片或检测报告。"
)


def get_order(order_id: str) -> dict:
    """查订单。不存在时抛 KeyError，由 run() 转成 error 回灌——不是让程序崩掉。"""
    if order_id not in ORDERS:                       # 业务校验：模型可能编出不存在的订单号
        raise KeyError(f"订单不存在：{order_id}")      # 抛出的字符串最终会进 tool 消息
    return {"order_id": order_id, **ORDERS[order_id]}  # 返回值会被 json.dumps 成字符串回灌


def get_policy(category: str) -> dict:
    """查政策。category 已被 Literal 约束，这里可以直接下标。"""
    return {"category": category, **POLICY[category]}


def calc_shipping_fee(order_id: str, weight_kg: float) -> dict:
    """算运费：首重 1kg 8 元，续重每公斤 2 元。"""
    if order_id not in ORDERS:                                   # 同样的业务校验
        raise KeyError(f"订单不存在：{order_id}")
    fee = 8 + max(0.0, (weight_kg - 1)) * 2                      # max(0,...) 让 1kg 以内不出现负数续重
    return {"order_id": order_id, "weight_kg": weight_kg, "fee": round(fee, 2)}


def get_clause_text(category: str) -> dict:
    """取长文本。它存在的意义是"一定会撞上裁剪"，不是为了有用。"""
    return {"category": category, "text": CLAUSE_TEXT}


def check_coupon(order_id: str) -> dict:
    """恒定返回「无」。结果恒定 = 无论参数怎么变，结果指纹都一样。"""
    return {"coupon": "无", "note": "本平台目前不发券"}


# 名字 -> (实现函数, 参数模型)。这张表是"工具名校验"的唯一依据：
# 模型给了表里没有的名字，就是一次必须被拦下的坏调用（第 6 章 B1 失败面）。
TOOL_IMPL: dict[str, tuple[Callable[..., dict], type[BaseModel]]] = {
    "get_order": (get_order, OrderQuery),
    "get_policy": (get_policy, PolicyQuery),
    "calc_shipping_fee": (calc_shipping_fee, FeeQuery),
    "get_clause_text": (get_clause_text, ClauseQuery),
    "check_coupon": (check_coupon, CouponQuery),
}

# ── 第 1 章 A1：消息形状（回灌三条格式）──────────────────────────────────────

# 四个角色名，拼错任何一个都会让请求被服务端拒绝
ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL = "system", "user", "assistant", "tool"


def tool_msg(call_id: str, content: str) -> dict:
    """回灌三条格式：role=tool、tool_call_id 配对、content 是字符串。"""
    # 三条少一条，服务端就会 400 或让模型"忘记"自己调过工具：
    #   role=tool        告诉模型"这是执行结果"，不是用户在说话
    #   tool_call_id     必须等于发起它的那个 tool_call.id，多个调用时靠它配对（按位置配会错）
    #   content          必须是字符串；直接塞 dict 会被序列化失败
    return {"role": ROLE_TOOL, "tool_call_id": call_id, "content": content}

# ── 第 4 章 A8：提示词六要素 ─────────────────────────────────────────────────
# 六段各防一种失效：缺角色会跑题、缺任务会泛泛而谈、缺约束会用常识补、
# 缺示例会格式不稳、缺输出格式无法解析、缺反例会踩已知的坑。

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

# ── 第 7 章 B2：终止三态 + 两个非预期中止 ────────────────────────────────────
# 三态（ANSWERED / MAX_STEPS / STALLED）区分"任务没走完"的三种原因，修法各不相同；
# 另外两个（BUDGET / FILTERED）是"不让继续"的外部原因，不属于三态。

RUNNING, ANSWERED, MAX_STEPS, STALLED, BUDGET, FILTERED = (
    "RUNNING", "ANSWERED", "MAX_STEPS", "STALLED", "BUDGET", "FILTERED",
)


@dataclass
class Stats:
    """一次运行的全部可观测数字。第 3 章说的"报三个数"就从这里出。"""

    steps: int = 0                 # 走了几步（循环次数，不是工具调用次数）
    tool_calls: int = 0            # 收到几次工具调用请求（模型说"我要调"，不含重复被拦的？含）
    prompt_tokens: int = 0         # 累计输入 token：每步都重发全部历史，所以它涨得最快
    completion_tokens: int = 0     # 累计输出 token：通常不到总量的两成，却贡献一半以上成本
    duplicate_blocked: int = 0     # 第 8 章：请求指纹命中的次数（重复调用被拦）
    arg_errors: int = 0            # 第 5 章：参数校验失败次数（模型给错参数）
    schema_retries: int = 0        # 第 5 章：结构化输出不合法后的重试次数
    truncated: int = 0             # 第 1 章：finish_reason=length 的次数（输出被截断）
    trimmed: int = 0               # 第 8 章 B5：单条消息被裁剪的次数
    repeated_result: int = 0       # 第 8 章：结果指纹重复的次数（换参数打转）

    @property
    def total_tokens(self) -> int:
        # 计费口径是"输入 + 输出"，两者单价不同，所以这里只给总量，不给成本
        return self.prompt_tokens + self.completion_tokens

# ── 第 8 章 B4：请求指纹 ─────────────────────────────────────────────────────


def fingerprint(name: str, arguments: str) -> str:
    """把 (工具名, 参数原文) 归一成一个指纹字符串。"""
    try:
        # sort_keys=True 是全部关键所在：模型生成参数的键序是随机的，
        # 不排序的话 {"a":1,"b":2} 与 {"b":2,"a":1} 会被算成两个不同的请求，
        # 去重彻底失效——这是本节最大的一行。
        normalized = json.dumps(json.loads(arguments), sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        # 参数不是合法 JSON 时不能让它炸：退回原文当指纹，让"坏参数"也能被去重（虽然拦不住变体）
        normalized = arguments
    return f"{name}|{normalized}"      # 工具名也要进指纹：同名不同工具、同参数不同工具必须区分

# ── 第 8 章 B5：单条消息级裁剪 ───────────────────────────────────────────────


def trim_tool_content(content: str, limit: int = 200) -> str:
    """把一条 tool 消息裁到 limit 字符：留头 + 留尾，中间插截断标记。"""
    if len(content) <= limit:          # 没超就直接返回，不做任何改动（避免无意义 diff）
        return content
    head = content[: limit // 2]       # 留头：通常是结构信息（order_id、status 在前面）
    tail = content[-(limit // 2):]     # 留尾：通常是结论或最后一条记录
    # 标记里带"截掉了多少字"：丢失必须被记录，否则排查方向必然错（第 3 章）
    return f"{head}…[截断 {len(content) - limit} 字]…{tail}"

# ── 第 5 章 A10：校验失败 → 回灌文案 ─────────────────────────────────────────


def to_feedback(exc: ValidationError) -> str:
    """把 pydantic 的错误结构转成模型能读懂的修复指令。"""
    lines = ["你上一次的输出不合法，请只输出 JSON 对象，字段如下："]   # 先重申格式，再列具体错误
    for err in exc.errors():                                          # errors() 是结构化列表，可逐条转述
        field_name = ".".join(str(p) for p in err["loc"])             # loc 是路径，嵌套字段会变成 a.b.c
        # 一行里给出三样：字段名、为什么错（msg）、你给的是什么（input）。
        # 只回灌"格式错了"等于让模型重猜；带上原值它才知道改哪里。
        lines.append(f"- {field_name}: {err['msg']}（你给的是 {err['input']!r}）")
    return "\n".join(lines)

# ── 第 7、8 章：主循环 ───────────────────────────────────────────────────────


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
    question = question or QUESTION                          # 验证时可以传别的问题，不动常量
    base_url = base_url or BASE_URL                          # 指向 mock 服务就靠这个参数/常量
    api_key = api_key or API_KEY
    model = model or MODEL
    temperature = TEMPERATURE if temperature is None else temperature   # 注意用 is None 判断：0.0 是合法值
    max_steps = STEP_LIMIT if max_steps is None else max_steps
    max_prompt_tokens = TOKEN_BUDGET if max_prompt_tokens is None else max_prompt_tokens

    # 一次调用的入口：timeout 与 max_retries 是"失败面"的两道基本防线（第 6 章失败面）
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0, max_retries=1)
    # 初始 messages 只有两条：系统提示（长期规则）+ 用户问题（本次数据）
    messages: list[dict] = [
        {"role": ROLE_SYSTEM, "content": SYSTEM_PROMPT},
        {"role": ROLE_USER, "content": question},
    ]
    stats = Stats()                    # 全程唯一的计数容器，最后一次性打印
    seen: set[str] = set()             # 第 8 章：见过的请求指纹（全集，不是只比上一次）
    seen_results: dict[str, str] = {}  # 第 8 章：见过的结果指纹（键是裁剪后的内容）
    dup_in_row = same_result_in_row = 0  # 连续计数：用于判定"空转"（连续才判，偶发不算）
    status = RUNNING                   # 当前状态，退出时写进返回值
    answer: Answer | None = None       # 只有真的解析成功才会被赋值

    # for-else：循环正常跑完（没 break）才会执行 else 分支 → 那就是"步数到顶"（第 7 章）
    for step in range(1, max_steps + 1):
        stats.steps = step             # 记录当前步数（断点恢复时它就是"从第几步继续"）
        # 第 8 章：预算闸门放在调用之前——已经花掉的钱收不回来，所以只能事前拦
        if stats.prompt_tokens > max_prompt_tokens:
            status = BUDGET
            if verbose:
                print(f"  步 {step} 预算用尽：{stats.prompt_tokens} > {max_prompt_tokens}")
            break

        # 第 1 章 A1：这就是"一次调用"本身。四个输入全由这里决定：
        # model / messages（历史）/ tools（可选项集合）/ temperature（采样）
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            temperature=temperature,
        )
        choice = resp.choices[0]       # 通常只有一个候选；>1 时是 n 参数，本示例不涉及
        finish = choice.finish_reason  # 第 1 章 A2：一切分歧都从这四个取值开始
        if resp.usage:                 # 第 3 章 A4：计费只认服务端 usage，本地估算只用于兜底
            stats.prompt_tokens += resp.usage.prompt_tokens        # 累计输入：每步都含全部历史
            stats.completion_tokens += resp.usage.completion_tokens  # 累计输出

        # 先把 assistant 消息原样放回历史：回灌时服务端要求"产生 tool_calls 的那条 assistant 必须在"
        assistant: dict[str, Any] = {"role": ROLE_ASSISTANT, "content": choice.message.content}
        if choice.message.tool_calls:                       # 有动作时，把 tool_calls 原样带回去
            assistant["tool_calls"] = [
                {
                    "id": c.id,                             # id 只在一轮响应内唯一，不能当幂等键
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in choice.message.tool_calls              # arguments 是 JSON 字符串，不是对象
            ]
        messages.append(assistant)      # 追加到历史 = 下一次调用会看到它

        # 第 1 章 A2 分支一：被内容过滤。产物为空，且重试无效（同一输入大概率还是被过滤）
        if finish == "content_filter":
            status = FILTERED
            if verbose:
                print(f"  步 {step} 中止：content_filter，重试无效")
            break

        # 第 1 章 A2 分支二：输出被 max_tokens 截断。产物不完整，重试无效，要"续写"
        if finish == "length":
            stats.truncated += 1                                 # 计数：截断是最难发现的失效（不报错）
            # 第 1 章"length 的三种补法"之一：回灌续写指令，让模型接着写
            messages.append({"role": ROLE_USER, "content": "上一条被截断，请只输出完整的 JSON 对象。"})
            if verbose:
                print(f"  步 {step} 截断：已回灌续写指令")
            continue                                             # 注意是 continue 不是 break：还能救

        # 第 6 章 B1 分支三：模型请求执行工具。一次响应可能带多个调用，必须逐个处理
        if finish == "tool_calls":
            for call in choice.message.tool_calls or []:
                stats.tool_calls += 1
                # 第 8 章 B4：先算请求指纹，再做别的——顺序反了会先执行再发现重复
                fp = fingerprint(call.function.name, call.function.arguments)
                if fp in seen:                                   # 同一个请求第二次出现 = 重复调用
                    stats.duplicate_blocked += 1
                    dup_in_row += 1
                    # 回灌一句"这次重复了"：让模型知道，而不是静默丢弃（否则它会一直重试）
                    messages.append(tool_msg(call.id, "重复调用：这次请求与之前完全相同，结果上面已经有了。"))
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：重复指纹被拦下")
                    continue                                     # 跳过执行
                seen.add(fp)                                     # 记入全集
                dup_in_row = 0                                   # 有新的请求，连续计数清零

                # 工具名校验：模型可能给出未声明的名字，直接下标会 KeyError 崩掉
                impl, arg_model = TOOL_IMPL[call.function.name]
                try:
                    # 第 5 章 A10：把字符串解析成模型实例，所有 Field 约束在这里一次性生效
                    args = arg_model.model_validate_json(call.function.arguments)
                except ValidationError as exc:
                    stats.arg_errors += 1
                    # 参数不合法也要回灌（而不是丢弃）：模型下一轮才知道该怎么改
                    messages.append(tool_msg(call.id, f"参数不合法，请按 schema 重发：{to_feedback(exc)}"))
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：参数解析失败，已回灌错误")
                    continue

                try:
                    # 真正执行：这是唯一有副作用的时刻，也是"调用方负责执行"的落点（第 0 章）
                    result = impl(**args.model_dump())
                except KeyError as exc:
                    # 业务错误：转成 error 回灌，让模型自己决定换参数还是换策略
                    messages.append(tool_msg(call.id, json.dumps({"error": str(exc)}, ensure_ascii=False)))
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：业务错误 -> {exc}")
                    continue

                # 第 8 章 B5：回灌前裁剪。注意裁的是"这一条的 content"，不是整段历史
                payload = json.dumps(result, ensure_ascii=False)   # 回灌内容必须是字符串
                trimmed = trim_tool_content(payload)
                if trimmed != payload:                             # 只有真的变了才计数
                    stats.trimmed += 1
                # 结果指纹用裁剪后的内容：同一份长文本每次都会被裁成同样的样子，才能比对
                if trimmed in seen_results:
                    stats.repeated_result += 1                     # 换参数打转：请求在变、结果不变
                    same_result_in_row += 1
                    if verbose:
                        print(f"  步 {step} 工具 {call.function.name}：结果与上一次完全相同")
                else:
                    seen_results[trimmed] = call.function.name     # 新结果：记下并清零
                    same_result_in_row = 0
                messages.append(tool_msg(call.id, trimmed))        # 回灌（用裁剪后的版本）
                if verbose:
                    print(f"  步 {step} 工具 {call.function.name}：{payload[:70]}")

            # 第 7 章 B2：空转判定用"连续"次数，偶发重复不算。两种空转各有各的信号：
            if same_result_in_row >= max_dup_in_row:               # 结果不变：换参数打转
                status = STALLED
                if verbose:
                    print(f"  步 {step} 判定空转：连续 {same_result_in_row} 次拿到相同结果")
                break
            if dup_in_row >= max_dup_in_row:                       # 请求不变：一模一样的重复
                status = STALLED
                if verbose:
                    print(f"  步 {step} 判定空转：连续 {dup_in_row} 次重复请求")
                break
            continue                                               # 还有下一步

        # 第 5 章 A10 分支四：没有工具调用 = 模型给了最终答复。这是唯一"可能成功"的分支
        raw = (choice.message.content or "").strip()
        try:
            # 结构化校验：语法（是不是 JSON）+ 结构（字段齐不齐、类型对不对）一起做
            answer = Answer.model_validate_json(raw)
            status = ANSWERED                                      # 三态里的"答完"
            if verbose:
                print(f"  步 {step} 结构化输出通过：{answer.conclusion} / {answer.clause} / 运费 {answer.shipping_fee}")
            break
        except ValidationError as exc:
            stats.schema_retries += 1
            # 第三层（语义）这里做不到：clause 是不是真存在、天数对不对，只能靠外部裁判
            messages.append({"role": ROLE_USER, "content": to_feedback(exc)})
            if verbose:
                print(f"  步 {step} 结构化输出不合法，回灌字段三列")
            continue
    else:
        # 循环没 break 就跑完了 → 步数到顶。这是"可能还能继续，但不让继续了"
        status = MAX_STEPS

    if verbose:
        # 第 3 章"三个数"：token / 步数 / 工具调用；后面几项是各章验证时要看的信号
        print(
            f"  结果：status={status} 步数={stats.steps} 工具调用={stats.tool_calls} "
            f"token={stats.prompt_tokens}+{stats.completion_tokens}={stats.total_tokens} "
            f"重复拦截={stats.duplicate_blocked} 参数错误={stats.arg_errors} "
            f"结构化重试={stats.schema_retries} 截断={stats.truncated} 裁剪={stats.trimmed} "
            f"结果重复={stats.repeated_result}"
        )
    # 返回三样：状态（为什么停）、答复（成功时才有）、统计（验证时要看的数）
    return status, answer, stats


def main() -> int:
    """入口：没有 key 时给出明确提示，而不是抛一个看不懂的 401。"""
    if not API_KEY or API_KEY.startswith("sk-在这里"):
        print("先把文件顶部的 API_KEY 填上（或用 mock_openai.py 起本地服务）。", file=sys.stderr)
        return 2

    print(f"模型：{MODEL}　端点：{BASE_URL}")
    print(f"问题：{QUESTION}")
    status, answer, _stats = run(verbose=True)      # 用模块常量跑一次完整流程
    print("\n最终答复：")
    if answer:
        # 结构化结果按字段打印：验证时可以直接核对 conclusion / clause / shipping_fee
        print(json.dumps(answer.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(f"（无结构化答复，status={status}）")
    return 0 if status == ANSWERED else 1           # 退出码可用于脚本化验证：0=成功


if __name__ == "__main__":
    raise SystemExit(main())
