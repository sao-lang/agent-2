"""五层配置 + 成本估算 + 用预算反算步数。

不联网。输入是 cases.PROFILES 的三个画像，输出是三张表：
  1 每个画像的五层配置（形态 / 编排 / 供给 / 可靠性 / 交付）
  2 调用次数与 token 估算、月度成本、P95 延迟
  3 给定预算反算"最多能走几步""还能不能带裁判"

运行：python code/selection/plan.py
"""

from __future__ import annotations

import math

from cases import PROFILES

PRICE = 2.0                 # 元 / 百万 token
SEC_PER_CALL = 1.2          # 一次带工具的模型调用（含往返）的典型耗时，秒
TOKENS_SIMPLE = 700
TOKENS_COMPLEX = 2500
CHECK_RATIO = 0.25          # 裁判/校验带来的额外调用占比


def choose_form(p: dict) -> tuple[str, str]:
    steps = p["task_shape"]["steps_median"]
    simple = p["request_mix"]["simple"]
    if steps <= 2 and simple >= 0.8:
        return "一次调用", "中位 1.5 步、九成一步能答完"
    if steps <= 8:
        return "单循环", f"中位 {steps:g} 步，不需要并行与隔离"
    if steps <= 15:
        return "工作流 + 路由", f"中位 {steps:g} 步，阶段可枚举"
    return "多 agent 图", f"中位 {steps:g} 步，超出单循环的稳定范围"


def choose_orchestration(p: dict, form: str) -> dict:
    if form == "一次调用":
        return {"分派": "无（单次生成）", "主体": "单次调用 + 结构化输出",
                "校验": "schema + 拒答"}
    simple = p["request_mix"]["simple"]
    high = p["error_cost"]["level"] == "高"
    dispatch = "规则 + 小模型两级" if simple >= 0.6 else "小模型 + 大模型两级"
    body = "ReAct" if p["task_shape"]["steps_median"] <= 8 else "计划-执行（P&E）"
    check = "外部裁判 + 人工审批" if high else ("schema + 抽样复核" if p["error_cost"]["level"] == "中" else "schema + 拒答")
    return {"分派": dispatch, "主体": body, "校验": check}


def choose_supply(p: dict, name: str) -> str:
    if name == "内部知识问答":
        return "RAG（现有向量库）+ 引用回链"
    if name == "客服工单":
        return "工具（工单/退款）+ 政策 RAG + 审批卡"
    return "RAG（多源）+ 检索工具 + Skill（报告模板）"


def choose_reliability(p: dict) -> str:
    level = p["error_cost"]["level"]
    if level == "高":
        return "幂等键 + 提交前审批 + 熔断 + 限流 + 降级三档"
    if level == "中":
        return "重试（预算 + 抖动）+ 幂等 + 降级两档"
    return "重试 + 限流 + 缓存"


def choose_delivery(p: dict) -> str:
    p95 = p["budget"]["p95_latency_s"]
    if p95 <= 5:
        return "同步 + 流式（首 token）"
    if p95 <= 60:
        return "同步 + 超时降级"
    return "异步队列 + 进度回调"


def per_task_tokens(p: dict) -> int:
    steps = p["task_shape"]["steps_median"]
    mix = p["request_mix"]
    per_call = mix["simple"] * TOKENS_SIMPLE + mix["complex"] * TOKENS_COMPLEX
    return int(steps * per_call * (1 + CHECK_RATIO))


def cost_row(p: dict) -> dict:
    tokens = per_task_tokens(p)
    monthly = tokens * p["budget"]["volume_per_month"]
    budget = p["budget"]["monthly_tokens"]
    latency = p["task_shape"]["steps_p95"] * SEC_PER_CALL
    return {
        "tokens_per_task": tokens,
        "monthly_tokens": monthly,
        "budget": budget,
        "budget_use": monthly / budget,
        "monthly_cost": monthly / 1_000_000 * PRICE,
        "p95_latency": latency,
        "latency_target": p["budget"]["p95_latency_s"],
    }


def reverse(p: dict) -> dict:
    """预算反算：每月可用 token / 请求数 -> 单请求上限 -> 最多几步。"""
    budget = p["budget"]["monthly_tokens"]
    volume = p["budget"]["volume_per_month"]
    max_tokens = budget / volume
    mix = p["request_mix"]
    per_call = mix["simple"] * TOKENS_SIMPLE + mix["complex"] * TOKENS_COMPLEX
    max_steps = max_tokens / (per_call * (1 + CHECK_RATIO))
    max_steps_no_check = max_tokens / per_call
    return {"max_tokens": max_tokens, "max_steps": max_steps,
            "max_steps_no_check": max_steps_no_check}


def main() -> None:
    print("=== 1. 五层配置 ===")
    for name, p in PROFILES.items():
        form, why = choose_form(p)
        orch = choose_orchestration(p, form)
        print(f"  [{name}]")
        print(f"    形态：{form}（{why}）")
        print(f"    编排：分派={orch['分派']}；主体={orch['主体']}；校验={orch['校验']}")
        print(f"    供给：{choose_supply(p, name)}")
        print(f"    可靠性：{choose_reliability(p)}")
        print(f"    交付：{choose_delivery(p)}")
        print()

    print("=== 2. 成本与延迟 ===")
    print(f"    {'画像':<10}{'tokens/任务':>12}{'月度tokens':>14}{'预算占比':>9}"
          f"{'月成本元':>10}{'P95':>7}{'目标':>6}")
    for name, p in PROFILES.items():
        r = cost_row(p)
        print(f"    {name:<10}{r['tokens_per_task']:>12}{r['monthly_tokens']:>14}"
              f"{r['budget_use']:>9.0%}{r['monthly_cost']:>10.0f}"
              f"{r['p95_latency']:>6.0f}s{r['latency_target']:>5.0f}s")

    print()
    print("=== 3. 预算反算 ===")
    print(f"    {'画像':<10}{'单请求上限':>10}{'最多步数':>9}{'不带裁判':>10}{'结论'}")
    for name, p in PROFILES.items():
        r = reverse(p)
        conclusion = "预算够，可带裁判" if r["max_steps"] >= p["task_shape"]["steps_median"] else "预算不够"
        print(f"    {name:<10}{r['max_tokens']:>10.0f}{r['max_steps']:>9.1f}"
              f"{r['max_steps_no_check']:>10.1f}  {conclusion}")

    print()
    print("=== 4. 超预算的画像怎么改 ===")
    for name, p in PROFILES.items():
        r = cost_row(p)
        if r["budget_use"] > 1:
            need = math.ceil(r["monthly_tokens"] / r["budget"])
            print(f"    {name}：需要砍到 1/{need}，或把预算乘以 {need}")
        elif r["budget_use"] > 0.8:
            print(f"    {name}：已用 {r['budget_use']:.0%}，没有余量做 A/B")
        else:
            print(f"    {name}：已用 {r['budget_use']:.0%}，有余量")


if __name__ == "__main__":
    main()
