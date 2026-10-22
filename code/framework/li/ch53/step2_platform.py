"""第 53 章 step2：接平台——LangSmith / LangFuse 的最小接入（带守卫，离线可跑）。

运行：
    python code/framework/li/ch53/step2_platform.py

上一级的痛点：
    你自己写的 tracer 能跑，但"多机汇总、按租户过滤、按版本对比"要自己搭。

这一级做什么：
    ① `@traceable`：一行装饰器把函数变成 trace（LangSmith 风格）
    ② 环境变量开关：设了就上报、没设就静默降级成"本地收集"
    ③ dataset + experiment：把"评测集"变成平台上的对象
    ④ 一张对照表：你的 span 字段 ↔ 平台字段

⚠️ 本仓库**不真的上报**（需要 LangSmith / LangFuse 账号）。
   本节用 `tracing_context` 本地收集，演示"打了标但没发出去"的形状。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lc"))

from _fake import scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① 平台怎么开：三个环境变量")
    envs = [
        ("LANGSMITH_TRACING", "true", "打开上报"),
        ("LANGSMITH_API_KEY", "lsv2_...", "鉴权"),
        ("LANGSMITH_PROJECT", "refund-agent", "项目分组"),
    ]
    for k, v, why in envs:
        cur = os.getenv(k, "(未设置)")
        print(f"  {k:<22} = {cur:<16} # {why}")
    print("\n  LangFuse 是同样的三件套，只是前缀不同：")
    print("    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST")
    print("  → **它们都只读环境变量**。所以「要不要上报」是一个部署决策，不是代码决策。")

    line("② @traceable：一行装饰器")
    from langsmith import traceable

    @traceable(name="refund_answer", tags=["env:test", "exp:prompt-v2"])
    def answer(question: str) -> str:
        chain = (
            ChatPromptTemplate.from_template("根据政策回答：{q}")
            | scripted("退款 7 个工作日到账。")
            | StrOutputParser()
        )
        return chain.invoke({"q": question})

    out = answer("退款多久？")
    print(f"  返回 = {out!r}")
    print("  → 没设 LANGSMITH_TRACING 时它**照样工作**，只是不上报。")
    print("    这是好设计：可观测性不该成为「能不能跑」的前提。")

    line("③ 打标：tags / metadata / run_name 怎么传")
    tagged = RunnableLambda(lambda x: x).with_config(
        run_name="refund_qa",
        tags=["tenant:acme", "ab:prompt-v2", "env:canary"],
        metadata={"prompt_version": "v2", "model": "gpt-4o-mini"},
    )
    tagged.invoke({"q": "hi"})
    print("  with_config(run_name=..., tags=[...], metadata={...})")
    print("  → 这三个是**平台侧过滤和聚合的全部依据**：")
    print("    tags      用于'按租户/按实验组'筛选")
    print("    metadata  用于'按 prompt 版本/按模型'统计")
    print("    run_name  让同一条链在列表里可辨认（否则全叫 RunnableSequence）")

    line("④ dataset 与 experiment：把评测集搬上平台")
    print("""  本地（第 40/51 章）：
      evals/rag_cases.json  →  跑脚本  →  一张表

  平台：
      client.create_dataset("refund-evals")           # 建数据集
      client.create_examples(dataset_id=..., examples=[...])   # 灌样本
      client.evaluate(target_fn, data="refund-evals", evaluators=[...])

  → 换来的是：多机汇总、按时间看趋势、按 case 下钻、多人共享。
  → 代价是：数据出内网。**这一条要先过合规**。""")

    line("⑤ 字段对照：你的 span ↔ 平台字段")
    print("""  | 你的（step1 的 Span） | OTLP | LangSmith | LangFuse |
  |---|---|---|---|
  | trace_id              | traceId          | trace_id      | traceId |
  | span_id               | spanId           | run.id        | observationId |
  | parent_id             | parentSpanId     | run.parent_run_id | parentObservationId |
  | name                  | name             | run.name      | name |
  | kind                  | kind             | run.run_type  | type |
  | start/end             | *UnixNano        | run.start_time/end_time | startTime/endTime |
  | inputs                | attributes       | run.inputs    | input |
  | outputs               | attributes       | run.outputs   | output |
  | error                 | status/attributes | run.error   | level/statusMessage |

  → 所以"接平台"不是重写，是**字段改名 + 网络上报**。""")

    line("⑥ 不用平台也能做完第 38 章的事——什么情况下必须上平台")
    print("""  必须上：
    · 多台机器/多个 worker，要汇总成一条 trace
    · 要按租户 / 按 prompt 版本出对比看板
    · 非开发同事也要看（产品、客服主管）
    · 要保留 >7 天的历史用于回溯

  不必上：
    · 单机、单人开发
    · 只要能"事后看一次"
    · 数据不能出内网（那就自己搭 Jaeger / 落 SQLite）

  → 一句话：**平台买的是"汇总与展示"，不是"可观测性的概念"。**
    概念（span/trace/parent）你在第 38 章已经会了。""")


if __name__ == "__main__":
    main()
