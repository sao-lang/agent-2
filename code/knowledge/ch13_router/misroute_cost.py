"""误分流的两个方向：放行了该升级的，升级了该放行的。

两边代价不同，差距由一个参数给出：一条"该升级却放行"的错误答复值多少条
"该放行却升级"的多余调用。
"""

from __future__ import annotations

from dataclasses import dataclass

COST_ESCALATE = 1.0    # 一条请求多进一级的成本（token + 延迟折价）
COST_WRONG = 12.0      # 一条请求被放行后答错的成本，按"多少条多余调用"折算

# (问题, 真正需要的路, 路由给出的路)
CASES: list[tuple[str, str, str]] = [
    ("退货运费谁出", "faq", "faq"),
    ("发票怎么开", "faq", "faq"),
    ("订单 A1001 还能退吗", "loop", "loop"),
    ("订单 A1002 到哪了", "loop", "loop"),
    ("这个订单几天能到", "loop", "loop"),
    ("这个耳机保修几年", "loop", "big"),      # 该查文档，却只走了一次调用
    ("我收到的是空盒子，订单 A1003", "loop", "faq"),  # 被 FAQ 规则吃掉
    ("退款失败三次了，给我个说法", "loop", "faq"),    # 同上
    ("帮我把这篇公告改成口语", "single", "loop"),     # 不需要查库，却进了循环
    ("这段话翻译成英文", "single", "loop"),
    ("你们公司还招人吗", "out_of_scope", "out_of_scope"),
    ("讲个笑话", "out_of_scope", "out_of_scope"),
]

# 路由给出的路比真正需要的"更贵"还是"更便宜"
ORDER = {"faq": 0, "single": 1, "big": 2, "loop": 3}


@dataclass
class Misroute:
    question: str
    truth: str
    given: str
    kind: str        # under（该升级却放行）/ over（该放行却升级）/ ok


def classify(truth: str, given: str) -> str:
    if truth == given:
        return "ok"
    if truth == "out_of_scope" or given == "out_of_scope":
        return "scope"     # 范围判断错了，不属于两个方向
    return "under" if ORDER[given] < ORDER[truth] else "over"


def main() -> None:
    rows = [Misroute(q, t, g, classify(t, g)) for q, t, g in CASES]

    print("=== 逐条看 ===")
    for r in rows:
        if r.kind == "ok":
            continue
        print(f"  {r.question:<26} 真实 {r.truth:<3} 实际 {r.given:<3} {r.kind}")

    under = [r for r in rows if r.kind == "under"]
    over = [r for r in rows if r.kind == "over"]
    scope = [r for r in rows if r.kind == "scope"]
    ok = [r for r in rows if r.kind == "ok"]

    print()
    print("=== 两个方向的账 ===")
    print(f"  分对 {len(ok)} 条")
    print(f"  该升级却放行 {len(under)} 条，每条代价 {COST_WRONG:g} -> {len(under) * COST_WRONG:g}")
    print(f"  该放行却升级 {len(over)} 条，每条代价 {COST_ESCALATE:g} -> {len(over) * COST_ESCALATE:g}")
    print(f"  范围判断错 {len(scope)} 条（单独统计，不计入上两行）")

    ratio = (len(under) * COST_WRONG) / (len(over) * COST_ESCALATE)
    print(f"  两个方向的代价比 {ratio:.0f}:1")

    print()
    print("=== 把阈值收紧一档，方向会怎么变 ===")
    # 收紧 = 更多请求升级：under 减半，over 翻倍
    under2, over2 = len(under) / 2, len(over) * 2
    print(f"  收紧后：under {under2:g} 条 -> {under2 * COST_WRONG:g}，"
          f"over {over2:g} 条 -> {over2 * COST_ESCALATE:g}")
    print(f"  收紧后总代价 {under2 * COST_WRONG + over2 * COST_ESCALATE:g}，"
          f"收紧前 {len(under) * COST_WRONG + len(over) * COST_ESCALATE:g}")
    print("  代价比大到一定程度，收紧就是划算的；比例接近时，收紧只是把成本换了个口袋")


if __name__ == "__main__":
    main()
