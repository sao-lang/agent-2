"""第 43 章 step3：并行、分支、重试、降级、可配置（离线）。

运行：
    python code/framework/lc/ch43/step3_composition.py

上一级的痛点：
    一条直线链只够"一次问一次答"。真实业务要：
      · 三个子问题同时问（省时）
      · 按输入类型走不同分支
      · 模型抖动时自动重试
      · 主模型挂了自动降级
      · 同一个函数按配置换模型 / 换温度

这一级做什么：把这五件事各演示一遍，每件都给出"不这么做会怎样"。
所有 Runnable 都有 5 个 with_* 方法，这里逐个跑。

记住这条规律：
    with_* 全部返回**新对象**，不改原对象。所以基链可以放心复用。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    RunnableBranch,
    RunnableLambda,
    RunnableParallel,
    RunnablePassthrough,
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from _fake import scripted  # noqa: E402


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    line("① RunnableParallel：三个子问题同时问")
    t0 = time.perf_counter()
    parallel = RunnableParallel(
        summary=ChatPromptTemplate.from_template("总结：{doc}") | scripted("摘要内容") | StrOutputParser(),
        keywords=ChatPromptTemplate.from_template("提取关键词：{doc}") | scripted("词表") | StrOutputParser(),
        sentiment=ChatPromptTemplate.from_template("判断情绪：{doc}") | scripted("中性") | StrOutputParser(),
    )
    out = parallel.invoke({"doc": "屏幕有划痕"})
    print(f"  输出 dict = {out}")
    print(f"  耗时 = {(time.perf_counter() - t0) * 1000:.1f} ms")
    print("  → 三个子链拿到同一个输入 dict，各自取自己需要的键，结果合并成一个 dict")

    line("② RunnablePassthrough.assign：在流里加字段，不丢原字段")
    # 场景：保留原始问题，同时加一个"改写后的问题"和一个"答案"
    step = (
        RunnablePassthrough.assign(
            rewrite=ChatPromptTemplate.from_template("改写：{q}") | scripted("改写后的问题") | StrOutputParser()
        ).assign(
            answer=ChatPromptTemplate.from_template("回答：{rewrite}") | scripted("答案") | StrOutputParser()
        )
    )
    print(f"  {step.invoke({'q': '能退吗'})}")
    print("  → assign 的右侧能读左边已算出的字段（先算 rewrite，再算 answer）")

    line("③ RunnableBranch：按条件走不同分支")
    branch = RunnableBranch(
        (lambda x: "退款" in x["q"], ChatPromptTemplate.from_template("退款：{q}") | scripted("走退款流程")),
        (lambda x: "物流" in x["q"], ChatPromptTemplate.from_template("物流：{q}") | scripted("走物流流程")),
        ChatPromptTemplate.from_template("兜底：{q}") | scripted("转人工"),
    )
    for q in ["我要退款", "物流到哪了", "你们公司在哪"]:
        print(f"  {q:<10} → {branch.invoke({'q': q}).content!r}")

    line("④ with_retry：失败自动重试（不重试会直接抛给用户）")
    calls = {"n": 0}

    def flaky(_x):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError(f"第 {calls['n']} 次超时")
        return "第三次成功"

    retrying = RunnableLambda(flaky).with_retry(stop_after_attempt=3)
    print(f"  结果 = {retrying.invoke('x')!r}，共调用 {calls['n']} 次")

    print("\n  不加重试时：")
    calls["n"] = 0
    try:
        RunnableLambda(flaky).invoke("x")
    except TimeoutError as e:
        print(f"    直接抛出 {type(e).__name__}: {e}（用户看到 500）")

    line("⑤ with_fallbacks：主模型挂了，自动换备胎")
    primary = RunnableLambda(lambda _x: (_ for _ in ()).throw(RuntimeError("主模型 429")))
    backup = scripted("备用模型的回答") | StrOutputParser()
    safe = primary.with_fallbacks([backup])
    print(f"  结果 = {safe.invoke('hi')!r}")
    print("  → 注意：fallback 只接「抛异常」，不接「答得不好」。质量兜底要靠评测。")

    line("⑥ with_config：同一份代码，按请求切换配置")
    # with_config 是最常用也最不神秘的那个：它只是给这一条链挂上一份配置。
    # 配置里能被读取的是 tags / metadata / run_name / configurable 等标准键。
    chain = ChatPromptTemplate.from_template("{q}") | scripted("可以退。") | StrOutputParser()

    seen: dict = {}

    def record(run):  # noqa: ANN001, ARG001
        seen["tags"] = run.tags
        seen["name"] = run.name

    tuned = chain.with_config(tags=["tenant:acme", "ab:prompt-v2"], run_name="refund_qa")
    print(f"  带 config 调用 → {tuned.invoke({'q': '能退吗'})!r}")
    print("  → tags/metadata 会随调用上报到 LangSmith / LangFuse（见第 52 章），")
    print("    是按「租户 / prompt 版本」切分指标的唯一可靠办法")
    print("\n  想换的是「模型的参数」而不是「prompt 的变量」时，才用 ConfigurableField：")
    print("    ChatOpenAI(temperature=0).configurable_fields(")
    print("        temperature=ConfigurableField(id='temp', name='温度'))")
    print("    调用：chain.invoke(x, config={'configurable': {'temp': 0.7}})")
    print("  → 注意：key 必须是对象自身字段（temperature/model），不能是 prompt 里的变量名")

    line("⑦ 一次记住六个方法")
    print("""
  .with_retry(...)       失败重试（只处理异常）
  .with_fallbacks([...]) 降级到备用链（只处理异常）
  .with_config(...)      注入配置（tags/metadata/run_name/可配置字段）
  .configurable_fields() 把参数变成运行时可替换（A/B、多租户）
  .configurable_alternatives() 把「整个实现」变成可替换
  .with_listeners(...)   观测钩子（开始/结束/出错）
    """)


if __name__ == "__main__":
    main()
