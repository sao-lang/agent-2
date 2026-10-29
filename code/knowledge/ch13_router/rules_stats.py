"""每条规则自己的一份账：命中多少条、其中事后被判错多少条。

规则层的失效不会自己暴露：它命中率很高、错误率也很高时，
总量指标看起来最好。只有把命中数与判错数绑在规则名下才看得见。
"""

from __future__ import annotations

from dataclasses import dataclass

# 一批回放请求：(问题, 走到的规则名或 None, 人工判定"这条答复对吗")
# 判错只对规则层直接给答案的请求有意义；只给出口不给答案的规则记 None。
REPLAY: list[tuple[str, str | None, bool | None]] = [
    ("退货运费谁出", "faq_exact", True),
    ("发票怎么开", "faq_exact", True),
    ("几天能到", "faq_exact", False),      # FAQ 里有"几天能到"，但用户问的是跨境订单
    ("退货运费谁出", "faq_exact", True),
    ("订单 A1001 还能退吗", "order_id", None),
    ("订单 A1002 到哪了", "order_id", None),
    ("订单 A1003 能改地址吗", "order_id", None),
    ("这个订单几天能到", "tracking", None),
    ("大概几天到", "tracking", None),
    ("你好", "smalltalk", True),
    ("在吗", "smalltalk", True),
    ("我要退款，但先问物流", None, None),
    ("这个耳机保修几年", None, None),
]


@dataclass
class RuleStat:
    name: str
    hits: int = 0
    answered: int = 0      # 直接给出答复的次数
    wrong: int = 0         # 事后被判错的次数

    @property
    def answer_rate(self) -> float:
        return self.answered / self.hits if self.hits else 0.0

    @property
    def error_rate(self) -> float:
        return self.wrong / self.answered if self.answered else 0.0


def collect(replay: list[tuple[str, str | None, bool | None]]) -> dict[str, RuleStat]:
    stats: dict[str, RuleStat] = {}
    for _, rule, verdict in replay:
        if rule is None:
            continue
        st = stats.setdefault(rule, RuleStat(rule))
        st.hits += 1
        if verdict is not None:
            st.answered += 1
            st.wrong += int(not verdict)
    return stats


if __name__ == "__main__":
    stats = collect(REPLAY)

    print("=== 每条规则自己的账 ===")
    print(f"  {'规则':<11}{'命中':>4}{'直接答':>7}{'答错':>5}{'答错率':>7}")
    for st in stats.values():
        err = f"{st.error_rate:.0%}" if st.answered else "—"
        print(f"  {st.name:<11}{st.hits:>4}{st.answered:>7}{st.wrong:>5}{err:>7}")

    print()
    print("=== 只看总量会看到什么 ===")
    hits = sum(st.hits for st in stats.values())
    answered = sum(st.answered for st in stats.values())
    wrong = sum(st.wrong for st in stats.values())
    print(f"  规则层命中 {hits} 条（{hits / len(REPLAY):.0%} 的请求没进模型）")
    print(f"  其中直接答复 {answered} 条，答错 {wrong} 条（{wrong / answered:.0%}）")

    faq = stats["faq_exact"]
    print()
    print("=== 按规则拆开 ===")
    print(f"  faq_exact 命中 {faq.hits} 条，答错 {faq.wrong} 条（{faq.error_rate:.0%}）"
          f" <- 总量里的错答全部来自这一条")
    print("  order_id / tracking / smalltalk 只给出口，不直接答，答错率为空是设计如此")
