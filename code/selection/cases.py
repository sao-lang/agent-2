"""三个项目画像：五类项目事实，以及每类"两天内怎么量到"。

不联网。数字是示例画像（可替换成真实项目的量法结果），量法写在 MEASURE 里。
本章所有推演都从这三个字典出发，改这里的数就能复算全部结论。

运行：python code/selection/cases.py
"""

from __future__ import annotations

PROFILES = {
    "客服工单": {
        "task_shape": {"steps_median": 6, "steps_p95": 11},
        "request_mix": {"simple": 0.70, "complex": 0.30},
        "error_cost": {"level": "高", "reversible": False, "needs_approval": True},
        "budget": {"monthly_tokens": 600_000_000, "p95_latency_s": 8, "volume_per_month": 60_000},
        "team": {"people": 4, "stack": "Python + 内部工单系统", "compliance": "审计留痕"},
    },
    "内部知识问答": {
        "task_shape": {"steps_median": 1.5, "steps_p95": 3},
        "request_mix": {"simple": 0.90, "complex": 0.10},
        "error_cost": {"level": "低", "reversible": True, "needs_approval": False},
        "budget": {"monthly_tokens": 220_000_000, "p95_latency_s": 3, "volume_per_month": 120_000},
        "team": {"people": 2, "stack": "Python + 现有向量库", "compliance": "无"},
    },
    "研究报告": {
        "task_shape": {"steps_median": 25, "steps_p95": 40},
        "request_mix": {"simple": 0.20, "complex": 0.80},
        "error_cost": {"level": "中", "reversible": True, "needs_approval": False},
        "budget": {"monthly_tokens": 300_000_000, "p95_latency_s": 300, "volume_per_month": 4_000},
        "team": {"people": 3, "stack": "Python + 检索服务", "compliance": "来源可追溯"},
    },
}

MEASURE = {
    "任务形状": "抽 30 条真实请求，数每条需要几次工具调用/几轮模型；取中位数与 P95",
    "请求分布": "同一批 30 条按'一步能否答完'打标，算占比；一周后复算一次看漂移",
    "错误代价": "列三个最坏后果：能否回滚、是否涉及资金/对外发布、是否要人签字",
    "预算": "上月账单 ÷ 请求数 = 单请求成本；P95 延迟从网关日志直接取",
    "团队与存量": "人数、现有语言与框架、合规要求（审计、数据出境、留存）",
}


def show(name: str) -> None:
    p = PROFILES[name]
    print(f"=== {name} ===")
    print(f"    任务形状：中位 {p['task_shape']['steps_median']} 步，"
          f"P95 {p['task_shape']['steps_p95']} 步")
    print(f"    请求分布：简单 {p['request_mix']['simple']:.0%} / "
          f"复杂 {p['request_mix']['complex']:.0%}")
    print(f"    错误代价：{p['error_cost']['level']}，可回滚={p['error_cost']['reversible']}，"
          f"需审批={p['error_cost']['needs_approval']}")
    print(f"    预算：{p['budget']['monthly_tokens'] / 1e6:.0f}M tokens/月，"
          f"P95 {p['budget']['p95_latency_s']}s，{p['budget']['volume_per_month']} 次/月")
    print(f"    团队：{p['team']['people']} 人，{p['team']['stack']}，"
          f"合规={p['team']['compliance']}")


def main() -> None:
    print("=== 1. 三个画像 ===")
    for name in PROFILES:
        show(name)
        print()

    print("=== 2. 每类事实怎么在两天内量到 ===")
    for k, v in MEASURE.items():
        print(f"    {k:<8}{v}")

    print()
    print("=== 3. 三个画像的关键差别（后面推演只用这三行） ===")
    for name, p in PROFILES.items():
        steps = p["task_shape"]["steps_median"]
        simple = p["request_mix"]["simple"]
        cost = p["error_cost"]["level"]
        print(f"    {name:<10}步数={steps:<5}简单占比={simple:<5}错误代价={cost}")
    print("    <- 复杂度不是打分的，是这三个数；其中步数与占比可量，代价是判断题")


if __name__ == "__main__":
    main()
