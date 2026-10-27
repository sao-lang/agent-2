"""提示词回归测试：总数掩盖回归。

不联网。用一组固定的判定结果演示：
整体通过数从 7 升到 8，但有一条原本通过的用例失败了。

这正是"改提示词后看起来变好了"最常见的误判。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Case:
    name: str
    category: str


CASES = [
    Case("常规退货", "常规"),
    Case("超期退货", "边界"),
    Case("未拆封", "常规"),
    Case("已拆封", "边界"),
    Case("换货请求", "离题"),
    Case("政策咨询", "离题"),
    Case("空输入", "异常"),
    Case("超长输入", "异常"),
    Case("多语言混排", "异常"),
    Case("优惠券叠加", "常规"),
]

# 版本 A 的逐例结果
VERSION_A = {
    "常规退货": True, "超期退货": True, "未拆封": True, "已拆封": False,
    "换货请求": False, "政策咨询": True, "空输入": True, "超长输入": True,
    "多语言混排": False, "优惠券叠加": True,
}

# 版本 B：修好了"已拆封"，但弄坏了"多语言混排"和"超期退货"
VERSION_B = {
    "常规退货": True, "超期退货": False, "未拆封": True, "已拆封": True,
    "换货请求": True, "政策咨询": True, "空输入": True, "超长输入": True,
    "多语言混排": False, "优惠券叠加": True,
}


def summarize(results: dict[str, bool], label: str) -> None:
    total = len(results)
    passed = sum(results.values())
    print(f"{label}：{passed}/{total}  通过率 {passed/total:.0%}")
    by_cat: dict[str, list[bool]] = {}
    for c in CASES:
        by_cat.setdefault(c.category, []).append(results[c.name])
    for cat, vals in by_cat.items():
        print(f"  {cat:<6} {sum(vals)}/{len(vals)}")


def diff(a: dict[str, bool], b: dict[str, bool]) -> tuple[list[str], list[str]]:
    fixed = [k for k in a if not a[k] and b[k]]
    broke = [k for k in a if a[k] and not b[k]]
    return fixed, broke


def main() -> None:
    summarize(VERSION_A, "版本 A")
    print()
    summarize(VERSION_B, "版本 B")
    print()

    pa = sum(VERSION_A.values())
    pb = sum(VERSION_B.values())
    print(f"总数：{pa} → {pb}（+{pb - pa}）")
    print()

    fixed, broke = diff(VERSION_A, VERSION_B)
    print(f"修好的：{fixed}")
    print(f"弄坏的：{broke}")
    print()

    print("如果只看总数，结论是'变好了'。")
    print("逐例比较后，结论是'修好了两条，但弄坏了一条'。")
    print()
    print("总数掩盖的是这一条：'超期退货'原本通过，现在失败。")
    print("它属于'边界'类别，而边界用例本来就只有 2 条，")
    print("所以分类统计里看不出变化（1/2 → 1/2）：坏的这条和好的那条")
    print("落在了不同的用例上，抵消了。")
    print()

    print("分类看更清楚：")
    for cat in ("常规", "边界", "离题", "异常"):
        a_ok = sum(VERSION_A[c.name] for c in CASES if c.category == cat)
        b_ok = sum(VERSION_B[c.name] for c in CASES if c.category == cat)
        total = sum(1 for c in CASES if c.category == cat)
        mark = "" if a_ok == b_ok else f"   <- {a_ok}→{b_ok}"
        print(f"  {cat:<6} {a_ok}/{total} → {b_ok}/{total}{mark}")

    print()
    print("用例集的四条要求：")
    print("  1. 覆盖类别，不只覆盖常见输入（上面离题与异常各 3 条）")
    print("  2. 保留历史失败（'已拆封'曾经失败过，必须一直在）")
    print("  3. 逐例比较，不只看总数")
    print("  4. 每次改动跑同一批用例")


if __name__ == "__main__":
    main()
