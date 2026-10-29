"""三种编排范式：固定工作流、ReAct、Plan-and-Execute，以及 DAG 决定的并发。

模型是脚本化替身（按预设顺序返回内容），只统计调用次数、token 估算与用时，
不判断答案质量。每一步用 sleep 模拟真实耗时，便于看串行与并发的差别。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

STEP_SECONDS = 0.25      # 每一步的模拟耗时
TOKENS_PER_CHAR = 0.6    # 粗略的 token 估算


@dataclass
class ScriptedLLM:
    """按顺序返回预设内容，并记录调用次数与估算 token。"""

    responses: list[str]
    calls: int = 0
    tokens: int = 0
    log: list[str] = field(default_factory=list)

    def __call__(self, prompt: str, purpose: str) -> str:
        self.calls += 1
        self.tokens += int(len(prompt) * TOKENS_PER_CHAR) + 40
        time.sleep(STEP_SECONDS)
        out = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        self.log.append(f"{purpose} -> {out[:16]}")
        return out


TASK = "给三个商品出一份退货率简报：拉订单、算退货率、写结论、配图表说明"

PLAN = [
    "1. 拉取近 30 天订单数据",
    "2. 按商品计算退货率",
    "3. 写一段结论",
    "4. 生成图表说明",
]


def fixed_workflow(llm: ScriptedLLM) -> dict:
    """固定工作流：步骤写死在代码里，每步一次调用。"""
    steps = ["拉订单", "算退货率", "写结论", "配图表"]
    for i, step in enumerate(steps, 1):
        llm(f"{TASK}\n当前步骤：{step}", f"step{i}")
    return {"steps": len(steps), "calls": llm.calls, "tokens": llm.tokens}


def react_loop(llm: ScriptedLLM, max_steps: int = 6) -> dict:
    """ReAct：每轮由模型决定下一步，直到给出最终回答。"""
    tool_calls = 0
    for step in range(1, max_steps + 1):
        out = llm(f"{TASK}\n已完成 {tool_calls} 次工具调用，下一步？", f"think{step}")
        if out.startswith("FINAL"):
            break
        tool_calls += 1
    return {"steps": tool_calls + 1, "calls": llm.calls, "tokens": llm.tokens}


def plan_and_execute(llm: ScriptedLLM) -> dict:
    """Plan-and-Execute：先出计划，再逐条执行；计划本身可审查。"""
    plan_text = llm(f"{TASK}\n请给出执行计划", "plan")
    n = len(PLAN)
    for i in range(1, n + 1):
        llm(f"{TASK}\n计划：{plan_text}\n执行第 {i} 步：{PLAN[i - 1]}", f"exec{i}")
    return {"steps": n + 1, "calls": llm.calls, "tokens": llm.tokens}


# ---------------------------------------------------------------- DAG 执行

DAG = {
    "拉订单": [],
    "算退货率": ["拉订单"],
    "算客单价": ["拉订单"],
    "写结论": ["算退货率", "算客单价"],
}


def run_dag(parallel: bool) -> tuple[dict, float]:
    done: dict[str, str] = {}
    order: list[str] = []

    def run_step(name: str) -> str:
        time.sleep(STEP_SECONDS)
        return f"{name} 完成"

    t0 = time.perf_counter()
    if parallel:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for name, deps in DAG.items():
                for d in deps:
                    futures[d].result()
                futures[name] = pool.submit(run_step, name)
                order.append(name)
            for name, fut in futures.items():
                done[name] = fut.result()
    else:
        for name, deps in DAG.items():
            for d in deps:
                assert d in done
            done[name] = run_step(name)
            order.append(name)
    return done, round(time.perf_counter() - t0, 2)


def main() -> None:
    print(f"任务：{TASK}")
    print(f"每步模拟耗时 {STEP_SECONDS}s\n")

    results = {}
    for name, fn, responses in [
        ("固定工作流", fixed_workflow, ["ok"] * 4),
        ("ReAct", react_loop, ["调工具1", "调工具2", "调工具3", "调工具4", "调工具5", "FINAL 回答"]),
        ("Plan-and-Execute", plan_and_execute, ["\n".join(PLAN)] + ["ok"] * 4),
    ]:
        llm = ScriptedLLM(responses=responses)
        t0 = time.perf_counter()
        r = fn(llm)
        r["seconds"] = round(time.perf_counter() - t0, 2)
        results[name] = r

    print("=== 1. 三种范式的步数与成本 ===")
    print(f"  {'范式':<18}{'步数':>4}{'模型调用':>8}{'估算token':>10}{'用时(s)':>9}")
    for name, r in results.items():
        print(f"  {name:<18}{r['steps']:>4}{r['calls']:>8}{r['tokens']:>10}{r['seconds']:>9}")

    print()
    print("=== 2. DAG：4 个步骤，两条链路可并行 ===")
    for name, dep in DAG.items():
        print(f"  {name:<8} 依赖 {dep or '无'}")
    _, serial = run_dag(parallel=False)
    _, parallel = run_dag(parallel=True)
    print(f"  串行 {serial}s，并发 {parallel}s，提速 {serial / parallel:.1f}x")

    print()
    print("=== 3. 第 2 步失败，三种范式各自要重跑什么 ===")
    print("  固定工作流：从第 2 步继续，前 1 步结果可直接复用")
    print("  ReAct：回到循环开头，之前的推理轨迹要重新组织")
    print("  Plan-and-Execute：只重跑第 2 步，计划不变")


if __name__ == "__main__":
    main()

