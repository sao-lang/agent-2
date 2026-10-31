"""五级迁移阶梯、升级触发条件、以及同一项目的两套架构对照。

不联网。触发条件用"连续 7 天滚动均值"判定，不用单日值——单日波动会让升级/回滚反复横跳。
两套架构的对照里，token 由 plan.py 的成本模型算，"失败成本"是显式假设的单价。

运行：python code/selection/migrate.py
"""

from __future__ import annotations

LEVELS = [
    (1, "一次调用", "单次生成 + 结构化输出", "无循环、无工具"),
    (2, "单循环", "ReAct + 四终止", "有工具，无分派"),
    (3, "工作流 + 路由", "分派层 + 固定阶段", "按请求类型走不同路径"),
    (4, "P&E + 外部裁判", "计划-执行 + 裁判循环", "有重规划与验收"),
    (5, "多 agent 图", "节点即循环 + 状态归并", "上下文与权限隔离"),
]

# 14 天的兜底率与首次通过率（示例序列，用来演示触发判定）
FALLBACK = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15,
            0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.23, 0.24, 0.24]
FIRST_PASS = [0.78, 0.78, 0.77, 0.77, 0.76, 0.76, 0.75, 0.74,
              0.73, 0.72, 0.71, 0.70, 0.69, 0.68, 0.67, 0.66, 0.65, 0.64]

FAIL_COST = 8.0          # 元 / 次人工返工（假设）
PRICE = 2.0              # 元 / 百万 token
VOLUME = 60_000


def rolling(series: list[float], window: int = 7) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(series)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sum(series[i + 1 - window:i + 1]) / window)
    return out


def first_hit(series: list[float], threshold: float, above: bool = True) -> int | None:
    for i, v in enumerate(rolling(series)):
        if v is None:
            continue
        if (v > threshold) if above else (v < threshold):
            return i + 1
    return None


def tokens_per_task(steps: float, per_call: float, check: float = 0.25) -> int:
    return int(steps * per_call * (1 + check))


def main() -> None:
    print("=== 1. 五级阶梯 ===")
    for no, name, shape, note in LEVELS:
        print(f"    第 {no} 级  {name:<12}{shape:<24}{note}")

    print()
    print("=== 2. 升级触发：连续 7 天滚动均值 ===")
    fb = first_hit(FALLBACK, 0.15)
    fp = first_hit(FIRST_PASS, 0.70, above=False)
    print(f"    兜底率从 {FALLBACK[0]:.0%} 涨到 {FALLBACK[-1]:.0%}；"
          f"7 天均值首次超过 15% 是第 {fb} 天")
    print(f"    首次通过率从 {FIRST_PASS[0]:.0%} 降到 {FIRST_PASS[-1]:.0%}；"
          f"7 天均值首次低于 70% 是第 {fp} 天")
    print("    兜底率命中 -> 升级到第 3 级（加分派）；首次通过率再跌破 -> 加裁判（第 4 级的校验层）")
    print("    <- 单日值不触发：第 8 天单日 15% 只是擦线，7 天均值到第 10 天才稳定超过")

    print()
    print("=== 3. 升级前后的账（示例数字，按同一批 60000 次/月） ===")
    before = {"level": 2, "tokens": tokens_per_task(6, 1550), "fallback": 0.22,
              "fail": 0.12, "points": 3}
    after = {"level": 3, "tokens": tokens_per_task(6, 1550) + 520, "fallback": 0.09,
             "fail": 0.07, "points": 4}
    for tag, x in (("升级前", before), ("升级后", after)):
        token_cost = x["tokens"] * VOLUME / 1_000_000 * PRICE
        fail_cost = x["fail"] * VOLUME * FAIL_COST
        print(f"    {tag}（第 {x['level']} 级）：tokens/任务={x['tokens']}  "
              f"token 成本={token_cost:.0f} 元  失败率={x['fail']:.0%}  "
              f"失败成本={fail_cost:.0f} 元  失败点={x['points']} 个")
    delta = (before["fail"] - after["fail"]) * VOLUME * FAIL_COST \
        - (after["tokens"] - before["tokens"]) * VOLUME / 1_000_000 * PRICE
    print(f"    净收益 ≈ {delta:.0f} 元/月（失败成本下降 - token 成本上升）")

    print()
    print("=== 4. 同一项目两套架构对照（都是第 2 级 vs 第 3 级） ===")
    print(f"    {'项':<18}{'A 单循环':<16}{'B 工作流+路由':<16}")
    rows = [
        ("tokens/任务", f"{before['tokens']}", f"{after['tokens']}"),
        ("月 token 成本", f"{(before['tokens'] * VOLUME / 1e6 * PRICE):.0f} 元",
         f"{(after['tokens'] * VOLUME / 1e6 * PRICE):.0f} 元"),
        ("失败率", f"{before['fail']:.0%}", f"{after['fail']:.0%}"),
        ("月失败成本", f"{before['fail'] * VOLUME * FAIL_COST:.0f} 元",
         f"{after['fail'] * VOLUME * FAIL_COST:.0f} 元"),
        ("代码面", "一个循环 + 5 工具", "循环 + 分派 + 两套提示词"),
        ("失败点", "工具错、裁判缺、状态丢", "以上 + 分派误判、双份提示词漂移"),
        ("评测集", "一套", "两套（按路径各一套）"),
    ]
    for a, b, c in rows:
        print(f"    {a:<18}{b:<16}{c:<16}")
    print("    B 省下的钱来自失败率下降；多出的成本是分派调用与两套维护")
    print("    判据不是'哪个更好'，是'兜底率还会不会继续涨'——涨到 15% 才升，回落就退回")

    print()
    print("=== 5. 两级跳的代价（第 2 级直接到第 5 级） ===")
    print("    代码面：循环 + 分派 + 图 + 多套提示词，一次到位")
    print("    评测集：需要图级与节点级两层，且要先有单循环的基线才看得出图有没有用")
    print("    回滚点：一旦图不成立，没有'第 3 级'可退，只能整体重写")
    print("    <- 阶梯的意义不是渐进，是给每一步留一个可退回的位置")


if __name__ == "__main__":
    main()
