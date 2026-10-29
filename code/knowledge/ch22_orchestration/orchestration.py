"""编排的四层对照：分派、主体（四种形态）、校验、DAG 并发。

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

STEPS = ["拉订单", "算退货率", "写结论", "配图表"]


def fixed_workflow(llm: ScriptedLLM) -> dict:
    """固定工作流：步骤写死在代码里，每步一次调用。"""
    for i, step in enumerate(STEPS, 1):
        llm(f"{TASK}\n当前步骤：{step}", f"step{i}")
    return {"steps": len(STEPS), "worker": llm.calls, "judge": 0,
            "tokens": llm.tokens, "retries": 0}


def react_loop(llm: ScriptedLLM, max_steps: int = 6) -> dict:
    """ReAct：每轮由模型决定下一步，直到给出最终回答。"""
    tool_calls = 0
    for step in range(1, max_steps + 1):
        out = llm(f"{TASK}\n已完成 {tool_calls} 次工具调用，下一步？", f"think{step}")
        if out.startswith("FINAL"):
            break
        tool_calls += 1
    return {"steps": tool_calls + 1, "worker": llm.calls, "judge": 0,
            "tokens": llm.tokens, "retries": 0}


def plan_and_execute(llm: ScriptedLLM) -> dict:
    """Plan-and-Execute：先出计划，再逐条执行；计划本身可审查。"""
    plan_text = llm(f"{TASK}\n请给出执行计划", "plan")
    for i, step in enumerate(PLAN, 1):
        llm(f"{TASK}\n计划：{plan_text}\n执行第 {i} 步：{step}", f"exec{i}")
    return {"steps": len(PLAN) + 1, "worker": llm.calls, "judge": 0,
            "tokens": llm.tokens, "retries": 0}


def with_reflector(worker: ScriptedLLM, judge: ScriptedLLM,
                   max_retries: int = 2) -> dict:
    """固定工作流 + 外部裁判：每步产出后判一次，不过就重做（最多两次）。"""
    retries = 0
    for i, step in enumerate(STEPS, 1):
        attempt = 0
        while True:
            worker(f"{TASK}\n当前步骤：{step}（第 {attempt + 1} 次）", f"step{i}")
            verdict = judge(f"判定第 {i} 步是否正确：{step}", f"judge{i}")
            if verdict == "PASS":
                break
            retries += 1
            attempt += 1
            if retries >= max_retries:
                break
    return {"steps": len(STEPS), "worker": worker.calls, "judge": judge.calls,
            "tokens": worker.tokens + judge.tokens, "retries": retries}


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


def routing_account(n: int = 10, simple: int = 6, expensive: int = 5) -> tuple[int, int]:
    """分派层的一笔账：不路由 vs 路由。"""
    without = n * expensive
    with_route = n * 1 + simple * 1 + (n - simple) * expensive
    return without, with_route


def main() -> None:
    print(f"任务：{TASK}")
    print(f"每步模拟耗时 {STEP_SECONDS}s\n")

    rows = []

    llm = ScriptedLLM(responses=["ok"] * 4)
    t0 = time.perf_counter()
    r = fixed_workflow(llm)
    rows.append(("固定工作流", r, round(time.perf_counter() - t0, 2), "静默走错路"))

    llm = ScriptedLLM(responses=["调工具1", "调工具2", "调工具3", "调工具4",
                                 "调工具5", "FINAL 回答"])
    t0 = time.perf_counter()
    r = react_loop(llm)
    rows.append(("ReAct", r, round(time.perf_counter() - t0, 2), "空转、跑偏"))

    llm = ScriptedLLM(responses=["\n".join(PLAN)] + ["ok"] * 4)
    t0 = time.perf_counter()
    r = plan_and_execute(llm)
    rows.append(("P&E", r, round(time.perf_counter() - t0, 2), "计划过时"))

    worker = ScriptedLLM(responses=["ok"] * 6)
    judge = ScriptedLLM(responses=["FAIL", "PASS", "PASS", "PASS", "PASS"])
    t0 = time.perf_counter()
    r = with_reflector(worker, judge)
    rows.append(("P&E + 外部裁判", r, round(time.perf_counter() - t0, 2), "裁判不可信"))

    print("=== 1. 四种主体形态（含校验）对照 ===")
    print(f"  {'形态':<16}{'步数':>4}{'工人调用':>8}{'裁判调用':>8}{'总调用':>8}{'重做':>4}{'估算token':>10}{'用时(s)':>9}")
    for name, r, secs, _ in rows:
        total = r["worker"] + r["judge"]
        print(f"  {name:<16}{r['steps']:>4}{r['worker']:>8}{r['judge']:>8}{total:>8}{r['retries']:>4}{r['tokens']:>10}{secs:>9}")

    print()
    print("=== 2. 校验层三档：同一任务的额外开销 ===")
    base = rows[0][1]["worker"]
    for label, judge_calls, retries in [("无裁判", 0, 0), ("自评（同一模型）", 4, 0),
                                        ("外部裁判（一次不过）", 5, 1)]:
        calls = base + judge_calls + retries
        print(f"  {label:<22} 工人 {base} + 裁判 {judge_calls} + 重做 {retries} = {calls} 次调用")

    print()
    print("=== 3. DAG：4 个步骤，两条链路可并行 ===")
    for name, dep in DAG.items():
        print(f"  {name:<8} 依赖 {dep or '无'}")
    _, serial = run_dag(parallel=False)
    _, parallel = run_dag(parallel=True)
    print(f"  串行 {serial}s，并发 {parallel}s，提速 {serial / parallel:.1f}x")

    print()
    print("=== 4. 分派层的一笔账：10 条请求，6 条简单、4 条复杂 ===")
    without, with_route = routing_account()
    print(f"  不路由：10 × 5 = {without} 次调用")
    print(f"  路由后：10 次判断 + 6 × 1 + 4 × 5 = {with_route} 次调用")
    print(f"  省下 {without - with_route} 次，占原成本的 {(without - with_route) / without:.0%}")

    print()
    print("=== 5. 第 2 步失败，三种范式各自要重跑什么 ===")
    print("  固定工作流：从第 2 步继续，前 1 步结果可直接复用")
    print("  ReAct：回到循环开头，之前的推理轨迹要重新组织")
    print("  Plan-and-Execute：只重跑第 2 步，计划不变")


if __name__ == "__main__":
    main()
