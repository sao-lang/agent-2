"""成本瀑布与三级预算，以及语义缓存的三条红线。

不联网。一次 12 步任务的成本按阶段拆开，再对三级预算各算一次；
语义缓存部分演示"命中率上升"与"跨租户命中"同时发生的样子。
"""

from __future__ import annotations

from dataclasses import dataclass

PRICE = {"input": 1.0, "output": 4.0, "cache": 0.1}      # 每百万 token，示例单价

TASK_BUDGET = 0.08
TENANT_DAILY = 6.0
MONTHLY = 120.0


@dataclass
class Stage:
    name: str
    input_tokens: int
    output_tokens: int
    cache_tokens: int = 0

    @property
    def cost(self) -> float:
        return (self.input_tokens * PRICE["input"]
                + self.output_tokens * PRICE["output"]
                + self.cache_tokens * PRICE["cache"]) / 1_000_000


STAGES = [
    Stage("路由", 900, 80),
    Stage("检索改写", 2_400, 120),
    Stage("生成（主回答）", 16_000, 900, 6_000),
    Stage("子 agent 汇总", 18_000, 520),
    Stage("自审", 9_000, 300, 4_000),
    Stage("格式化输出", 1_200, 60),
]


def waterfall() -> None:
    total = sum(s.cost for s in STAGES)
    print("=== 1. 一次任务的成本瀑布 ===")
    print(f"  {'阶段':<16}{'输入':>8}{'输出':>7}{'缓存':>7}{'成本(元)':>11}{'占比':>8}")
    acc = 0.0
    for s in STAGES:
        acc += s.cost
        print(f"  {s.name:<16}{s.input_tokens:>8}{s.output_tokens:>7}"
              f"{s.cache_tokens:>7}{s.cost:>11.6f}{s.cost / total:>8.1%}")
    print(f"  {'合计':<16}{sum(s.input_tokens for s in STAGES):>8}"
          f"{sum(s.output_tokens for s in STAGES):>7}"
          f"{sum(s.cache_tokens for s in STAGES):>7}{total:>11.6f}{1:>8.1%}")

    print()
    print("=== 2. 三级预算 ===")
    checks = [("单任务", total, TASK_BUDGET),
              ("单租户/日", TENANT_DAILY * 0.82, TENANT_DAILY),
              ("平台/月", MONTHLY * 0.74, MONTHLY)]
    for name, used, limit in checks:
        print(f"  {name:<10}已用 {used:>8.2f} / {limit:<8.2f}"
              f"（{used / limit:>6.1%}）{' 超限' if used > limit else ''}")
    print(f"  <- 单任务只占日预算的 {total / TENANT_DAILY:.2%}，"
          f"但日预算已用 82%：真正该管的是租户级")


def cache_demo() -> None:
    print()
    print("=== 3. 语义缓存：命中率与红线 ===")
    base_cost = sum(s.cost for s in STAGES)
    for hit_rate in (0.0, 0.3, 0.6):
        saved = base_cost * hit_rate * 0.95
        print(f"  命中率 {hit_rate:.0%} -> 成本 {base_cost - saved:.6f} 元"
              f"（省 {saved / base_cost:.0%}）")

    print()
    print("  三条红线，各一条具体形态：")
    print("  1 缓存键不含租户：A 租户问'我的订单'，命中 B 租户的答案 -> 数据串了")
    print("  2 缓存不随文档失效：政策从 15 天改成 7 天，命中旧答案 -> 答了过期政策")
    print("  3 命中仍计全额：成本报表按 0 省，实际账单没降 -> 归因失真")

    print()
    print("=== 4. 一条缓存的正确与错误写法 ===")
    keys = {
        "错误：只按问题文本": "hash(question)",
        "正确：问题 + 租户 + 索引版本": "hash(question, tenant, index_version)",
    }
    for label, k in keys.items():
        print(f"  {label:<28}{k}")


def main() -> None:
    waterfall()
    cache_demo()


if __name__ == "__main__":
    main()
