"""跑一次 mini_agent：装配 + CLI。跟着第 1–8 章一章一章长出来。

**这个文件只做三件事**，核心逻辑一行都不在这里，示例数据一行都不在这里：

    1. 放"要你自己改的常量"（QUESTION / TOKEN_BUDGET / 四个开关的默认值）
    2. build() 把客户端、守卫、状态、打印器拼成"一次任务"的对象图
    3. main() 解析命令行，跑完打印结构化答复，用退出码表示成败

为什么叫 run.py：它回答的是"怎么跑一次"，不是"agent 是什么"。agent 本身在
core/loop.py；目录已经叫 mini_agent/，文件再叫 mini_agent.py 会让人以为它是
包入口。章节目录里的 code/knowledge/ch08_runaway/mini_agent.py 仍叫原名——
那是给旧命令用的转发门面，名字要和旧命令对得上。

文件地图（读代码顺序照章走，每个文件里都有 `# ── 第 N 章` 标记）：

    第 1 章  core/contracts.py       Turn / tool_msg / as_message：一次调用的形状
    第 3 章  core/state.py           Stats / Reporter / RunState：记账与打印
    第 4 章  demo/orders/prompt.py   SYSTEM_PROMPT 六要素、续写指令
    第 5 章  demo/orders/schemas.py  五个参数模型 + Answer；contracts.py 的 to_feedback
    第 6 章  demo/orders/tools.py    声明 + 实现 + 注册表；core/executor.py 执行管道
    第 7 章  core/handlers.py        finish_reason 分派表；core/loop.py 干净主循环
    第 8 章  core/guards.py          四个守卫（指纹 / 结果 / 裁剪 / 预算）+ 四个开关
    本文件                            装配：把上面这些拼在一次任务上

demo/ 是示例集合，orders/ 是第 1–8 章这道题（电商退货）。以后加场景就新建
demo/<场景>/，这里只改一行 import，core/ 一行不动。

跑法（在**项目根**执行，顶部常量或命令行参数二选一，命令行优先）：

    python learn/mini_agent/run.py
    python learn/mini_agent/run.py \
        --base-url http://127.0.0.1:8899/v1 --api-key sk-mock

没有 key 也能跑通全链路：先起 mock 服务（默认 8899 端口），
再把 --base-url 指过去，API_KEY 随便填。四种结局都能看到：

    python code/knowledge/ch08_runaway/mock_openai.py --scenario good
    python code/knowledge/ch08_runaway/mock_openai.py --scenario stall
    python code/knowledge/ch08_runaway/mock_openai.py --scenario result

改完代码要验收，跑同目录的 regression.py（离线，不花 key）：
    python learn/mini_agent/regression.py

验证方法见 learn/1-8章验证手册.md；生长路线见 learn/mini_agent生长路线.md。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 从项目根按文件路径加载（验证手册的 REPL 就是这么做的）时，sys.path 里没有本目录。
# 把同目录挂进去，core/ 与 demo/ 才能被 import；直接运行时这一步是多余的但无害。
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from openai import OpenAI                       # 只有装配层认识厂商 SDK（第 1 章 A1）

from core.contracts import (
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
    ROLE_USER,
    ChatClient,
    RunConfig,
    ToolRegistry,
    ToolSpec,
    Turn,
    to_feedback,
    tool_msg,
)
from core.executor import ToolExecutor
from core.guards import GuardSet, fingerprint, trim_tool_content
from core.handlers import HANDLERS, dispatch
from core.loop import run_loop
from core.state import (
    ANSWERED,
    BUDGET,
    FILTERED,
    MAX_STEPS,
    RUNNING,
    STALLED,
    Outcome,
    Reporter,
    RunState,
    Stats,
)
from demo.orders.data import CLAUSE_TEXT, ORDERS, POLICY
from demo.orders.prompt import CONTINUATION_HINT, SYSTEM_PROMPT
from demo.orders.schemas import (
    Answer,
    ClauseQuery,
    CouponQuery,
    FeeQuery,
    OrderQuery,
    PolicyQuery,
    describe_answer,
)
from demo.orders.tools import (
    REGISTRY,
    TOOL_IMPL,
    TOOLS,
    calc_shipping_fee,
    check_coupon,
    get_clause_text,
    get_order,
    get_policy,
)

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
TRIM_LIMIT = 200         # 第 8 章 B5：单条 tool 消息保留多少字符
MAX_DUP_IN_ROW = 2       # 第 8 章：连续几次重复才判空转（偶发重复不算）

# 上面这些 import 里，有一部分（Answer / fingerprint / trim_tool_content /
# CLAUSE_TEXT / TOOLS / SYSTEM_PROMPT / to_feedback / 状态常量）是**兼容门面**：
# 验证手册的 REPL 加载本文件后直接取 m.Answer、m.fingerprint、
# m.trim_tool_content、m.CLAUSE_TEXT，所以这些名字必须仍在这里可取。
# 它们只是转发，不是把示例数据搬回核心。
__all__ = [
    # 入口
    "run", "main", "build", "OpenAIChat", "run_loop", "dispatch", "HANDLERS",
    "ToolExecutor", "ToolSpec", "GuardSet", "Stats", "Reporter", "RunState",
    "Outcome", "RunConfig", "Turn", "ToolRegistry", "ChatClient",
    # 可改的常量
    "BASE_URL", "API_KEY", "MODEL", "QUESTION", "TEMPERATURE", "STEP_LIMIT",
    "TOKEN_BUDGET", "TRIM_LIMIT", "MAX_DUP_IN_ROW",
    # 终止状态与角色
    "RUNNING", "ANSWERED", "MAX_STEPS", "STALLED", "BUDGET", "FILTERED",
    "ROLE_SYSTEM", "ROLE_USER", "ROLE_ASSISTANT", "ROLE_TOOL",
    # 验证手册 REPL / A3 / A8 / B4 / B5 要用到的门面
    "Answer", "OrderQuery", "PolicyQuery", "FeeQuery", "ClauseQuery", "CouponQuery",
    "describe_answer", "to_feedback", "tool_msg", "fingerprint", "trim_tool_content",
    "SYSTEM_PROMPT", "CONTINUATION_HINT", "CLAUSE_TEXT", "ORDERS", "POLICY",
    "TOOLS", "TOOL_IMPL", "REGISTRY", "get_order", "get_policy",
    "calc_shipping_fee", "get_clause_text", "check_coupon",
]


# ── 第 1 章 A1：唯一的 SDK 适配层 ────────────────────────────────────────────
class OpenAIChat:
    """四个输入进去、一个 Turn 出来。核心只认 Turn，换厂商/框架只改这里。"""

    def __init__(self, sdk: OpenAI) -> None:
        self._sdk = sdk

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float,
    ) -> Turn:
        resp = self._sdk.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
        return Turn.from_response(resp)


# ── 第 52 章预告：所有实例化集中在 build() 一处 ──────────────────────────────
def build(
    config: RunConfig,
    *,
    base_url: str,
    api_key: str,
    no_dedupe: bool = False,
    no_result_dedupe: bool = False,
    no_trim: bool = False,
    no_budget: bool = False,
    verbose: bool = True,
    client: ChatClient | None = None,
) -> tuple[ChatClient, GuardSet, RunState, Reporter]:
    """把配置变成"一次任务"的对象图：客户端、守卫、状态、打印器。

    守卫与任务一一对应，所以 GuardSet 在这里 new，绝不做成单例（第 8 章）。
    client 可注入：离线回归与第 9 章的框架对照台都从这里换实现。
    """
    if client is None:
        # timeout 与 max_retries 是"失败面"的两道基本防线（第 6 章失败面）
        client = OpenAIChat(OpenAI(base_url=base_url, api_key=api_key, timeout=60.0, max_retries=1))

    stats = Stats()
    state = RunState(
        messages=[
            {"role": ROLE_SYSTEM, "content": config.system_prompt},
            {"role": ROLE_USER, "content": config.question},
        ],
        stats=stats,
    )
    guards = GuardSet(
        stats=stats,
        dedupe=not no_dedupe,
        result_dedupe=not no_result_dedupe,
        trim=not no_trim,
        budget=not no_budget,
        max_dup_in_row=config.max_dup_in_row,
        trim_limit=config.trim_limit,
    )
    reporter = Reporter(verbose=verbose, describe_answer=config.describe_answer)
    return client, guards, state, reporter


def run(
    question: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_steps: int | None = None,
    max_prompt_tokens: int | None = None,
    max_dup_in_row: int | None = None,
    trim_limit: int | None = None,
    verbose: bool = True,
    # 四个开关：关掉哪个，就只有那一件事消失
    no_dedupe: bool = False,
    no_result_dedupe: bool = False,
    no_trim: bool = False,
    no_budget: bool = False,
    # 替换实验的入口：换一套工具 / 输出结构 / 提示词 / 模型客户端
    client: ChatClient | None = None,
    tools: list[dict] | None = None,
    output_model: type[Answer] | None = None,
    system_prompt: str | None = None,
    registry: ToolRegistry | None = None,
    continuation_hint: str | None = None,
) -> tuple[str, Answer | None, Stats]:
    """兼容原来的调用签名：参数缺省时读顶部常量，命令行参数在 main() 里覆盖。

    这一层只做参数归一 + 装配，循环本身在 core/loop.py。
    """
    question = question or QUESTION
    base_url = base_url or BASE_URL
    api_key = api_key or API_KEY
    model = model or MODEL
    temperature = TEMPERATURE if temperature is None else temperature   # 0.0 是合法值，用 is None
    max_steps = STEP_LIMIT if max_steps is None else max_steps
    max_prompt_tokens = TOKEN_BUDGET if max_prompt_tokens is None else max_prompt_tokens
    max_dup_in_row = MAX_DUP_IN_ROW if max_dup_in_row is None else max_dup_in_row
    trim_limit = TRIM_LIMIT if trim_limit is None else trim_limit

    config = RunConfig(
        model=model,
        temperature=temperature,
        max_steps=max_steps,
        max_prompt_tokens=max_prompt_tokens,
        system_prompt=system_prompt if system_prompt is not None else SYSTEM_PROMPT,
        question=question,
        tools=tools if tools is not None else TOOLS,
        output_model=output_model or Answer,
        registry=registry or REGISTRY,
        continuation_hint=continuation_hint or CONTINUATION_HINT,
        describe_answer=describe_answer,
        trim_limit=trim_limit,
        max_dup_in_row=max_dup_in_row,
    )
    _client, guards, state, reporter = build(
        config,
        base_url=base_url,
        api_key=api_key,
        no_dedupe=no_dedupe,
        no_result_dedupe=no_result_dedupe,
        no_trim=no_trim,
        no_budget=no_budget,
        verbose=verbose,
        client=client,
    )
    return run_loop(client=_client, config=config, guards=guards, state=state, reporter=reporter)


def main(argv: list[str] | None = None) -> int:
    """入口：没有 key 时给出明确提示，而不是抛一个看不懂的 401。"""
    p = argparse.ArgumentParser(description="mini_agent v0.1（第 1–8 章）")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--api-key", default=API_KEY)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--question", default=None, help="覆盖顶部的 QUESTION")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--token-budget", type=int, default=None)
    p.add_argument("--no-dedupe", action="store_true", help="关掉请求指纹去重")
    p.add_argument("--no-result-dedupe", action="store_true", help="关掉结果指纹")
    p.add_argument("--no-trim", action="store_true", help="关掉单条裁剪")
    p.add_argument("--no-budget", action="store_true", help="关掉预算闸门")
    p.add_argument("--quiet", action="store_true", help="只打印最终答复")
    args = p.parse_args(argv)

    if not args.api_key or args.api_key.startswith("sk-在这里"):
        print(
            "先把顶部的 API_KEY 填上，或用 --api-key sk-mock 指向本地 mock_openai.py。",
            file=sys.stderr,
        )
        return 2

    print(f"模型：{args.model}　端点：{args.base_url}")
    print(f"问题：{args.question or QUESTION}")
    status, answer, _stats = run(
        question=args.question,
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        temperature=args.temperature,
        max_steps=args.max_steps,
        max_prompt_tokens=args.token_budget,
        verbose=not args.quiet,
        no_dedupe=args.no_dedupe,
        no_result_dedupe=args.no_result_dedupe,
        no_trim=args.no_trim,
        no_budget=args.no_budget,
    )
    print("\n最终答复：")
    if answer:
        # 结构化结果按字段打印：验证时可以直接核对 conclusion / clause / shipping_fee
        print(json.dumps(answer.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(f"（无结构化答复，status={status}）")
    return 0 if status == ANSWERED else 1       # 退出码可用于脚本化验证：0=成功


if __name__ == "__main__":
    raise SystemExit(main())
