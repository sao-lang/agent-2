"""裁判可信吗：一致率与 kappa，以及"总是说通过"的裁判为什么看起来还行。

不联网。20 条人工标过的用例，三个裁判各判一遍：
  always_pass  永远判通过（退化裁判）
  reasonable   大体判得对，但偏好长回答
  strict       对长回答苛刻

一致率容易被高通过率骗到；kappa 扣掉了"碰巧一致"。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Case:
    cid: str
    human: bool          # True = 人工判为通过
    answer_chars: int
    reasonable: bool
    strict: bool


CASES = [
    Case("c01", True, 120, True, True),
    Case("c02", True, 140, True, True),
    Case("c03", True, 160, True, True),
    Case("c04", True, 180, True, True),
    Case("c05", True, 200, True, True),
    Case("c06", True, 220, True, True),
    Case("c07", True, 240, True, True),
    Case("c08", True, 900, True, False),     # long，严格裁判判错
    Case("c09", True, 950, True, False),
    Case("c10", True, 1000, False, False),   # 长回答被合理裁判放过（错在宽松）
    Case("c11", True, 1100, True, False),
    Case("c12", True, 130, True, True),
    Case("c13", True, 150, True, True),
    Case("c14", True, 170, True, True),
    Case("c15", False, 130, False, False),
    Case("c16", False, 140, False, False),
    Case("c17", False, 800, True, False),    # 长回答被放过（漏检）
    Case("c18", False, 160, False, False),
    Case("c19", False, 180, False, False),
    Case("c20", False, 1200, False, False),
]


def always_pass(c: Case) -> bool:
    return True


def reasonable(c: Case) -> bool:
    return c.reasonable


def strict(c: Case) -> bool:
    return c.strict


def agreement(judge, cases=CASES) -> tuple[float, float, int]:
    """返回 (一致率, kappa, 一致条数)。"""
    n = len(cases)
    agree = sum(1 for c in cases if judge(c) == c.human)
    po = agree / n
    h_pass = sum(1 for c in cases if c.human) / n
    j_pass = sum(1 for c in cases if judge(c)) / n
    pe = h_pass * j_pass + (1 - h_pass) * (1 - j_pass)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 0.0
    return po, kappa, agree


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    n = len(CASES)
    human_pass = sum(1 for c in CASES if c.human)
    print(f"=== 1. {n} 条用例，人工判通过 {human_pass} 条（{human_pass / n:.0%}）===")

    judges = [("always_pass", always_pass), ("reasonable", reasonable), ("strict", strict)]
    print(f"  {'裁判':<14}{'一致率':>8}{'kappa':>8}{'一致条数':>10}")
    for name, fn in judges:
        po, kappa, agree = agreement(fn)
        print(f"  {name:<14}{po:>8.0%}{kappa:>8.2f}{agree:>10}")

    print()
    print("=== 2. 永远判通过的那个裁判 ===")
    po, kappa, agree = agreement(always_pass)
    print(f"  一致率 {po:.0%}（{agree}/{n}），kappa {kappa:.2f}")
    print("  <- 一致率看着不差，kappa=0：它的判断里没有任何信息")

    print()
    print("=== 3. reasonable 错在哪：按回答长度分组 ===")
    groups = {"短（<300 字）": [c for c in CASES if c.answer_chars < 300],
              "长（>=800 字）": [c for c in CASES if c.answer_chars >= 800]}
    for name, cases in groups.items():
        ok = sum(1 for c in cases if reasonable(c) == c.human)
        print(f"  {pad(name, 16)}{ok}/{len(cases)} 判对（{ok / len(cases):.0%}）")
    print("  <- 长回答上判错更多：裁判偏好'说得多的'")

    print()
    print("=== 4. 一个裁判能上线的最低门槛 ===")
    for name, fn in judges:
        po, kappa, _ = agreement(fn)
        verdict = "可用" if kappa >= 0.6 else "不可用"
        print(f"  {pad(name, 14)}kappa {kappa:.2f} -> {verdict}")


if __name__ == "__main__":
    main()
