"""第 4 章 step2：提示词回归测试（离线可运行）。

运行：
    python code/ch04_prompt/step2_regression.py

本文件演示：改动一句提示词后，如何判断变好还是变坏。

做法是把提示词的变化映射到一组可判定的测试用例上，
比较改动前后的通过项。不调用模型。

输出中的通过项为规则计算，运行可复现。
"""

from __future__ import annotations

import sys


# 四个测试用例，每个用例包含若干可判定项
CASES = [
    {
        "id": "C1",
        "input": "耳机右耳有杂音，能退吗？",
        "checks": {
            "含字段 intent": True,
            "intent 正确": True,
            "含字段 answer_from": True,
            "追问缺失信息": False,
        },
    },
    {
        "id": "C2",
        "input": "你们公司股票多少钱？",
        "checks": {
            "含字段 intent": True,
            "intent 正确": True,
            "含字段 answer_from": False,
            "追问缺失信息": False,
        },
    },
    {
        "id": "C3",
        "input": "我想把上次那个退掉",
        "checks": {
            "含字段 intent": True,
            "intent 正确": False,
            "含字段 answer_from": False,
            "追问缺失信息": False,
        },
    },
    {
        "id": "C4",
        "input": "签收 20 天了还能退吗？",
        "checks": {
            "含字段 intent": True,
            "intent 正确": True,
            "含字段 answer_from": True,
            "追问缺失信息": False,
        },
    },
]


def score(cases: list[dict]) -> tuple[int, int]:
    total = 0
    ok = 0
    for c in cases:
        for v in c["checks"].values():
            total += 1
            if v:
                ok += 1
    return ok, total


def apply_change(cases: list[dict], change: str) -> list[dict]:
    """模拟提示词改动对各项检查的影响。

    三版共用同一套检查项，保证分母一致、可直接比较。
    v2：加入输出格式约束  -> 字段完整性提升
    v3：加入追问规则      -> 缺失信息场景修复，但对信息齐全的场景引入过度追问
    """
    import copy

    out = copy.deepcopy(cases)
    by_id = {c["id"]: c for c in out}

    if change == "v2":
        # 补上输出格式：C2、C3 的 answer_from 字段变完整
        by_id["C2"]["checks"]["含字段 answer_from"] = True
        by_id["C3"]["checks"]["含字段 answer_from"] = True

    if change == "v3":
        by_id["C2"]["checks"]["含字段 answer_from"] = True
        by_id["C3"]["checks"]["含字段 answer_from"] = True
        # 加入追问规则：C3 修复
        by_id["C3"]["checks"]["intent 正确"] = True
        by_id["C3"]["checks"]["追问缺失信息"] = True
        # 副作用：C4 信息已齐全，却被要求追问，answer_from 因此缺失
        by_id["C4"]["checks"]["含字段 answer_from"] = False
        by_id["C4"]["checks"]["追问缺失信息"] = True

    return out


def summarize(cases: list[dict], label: str) -> None:
    ok, total = score(cases)
    print(f"  {label:<10}{ok}/{total}    {'%.0f%%' % (ok / total * 100)}")


def main() -> None:
    print("=" * 88)
    print("① 四个测试用例与检查项")
    print("=" * 88)
    for c in CASES:
        n = len(c["checks"])
        ok = sum(1 for v in c["checks"].values() if v)
        print(f"  {c['id']}  {c['input']:<22}{ok}/{n}")

    print()
    print("=" * 88)
    print("② 三版提示词的通过项")
    print("=" * 88)
    v1 = CASES
    v2 = apply_change(CASES, "v2")
    v3 = apply_change(CASES, "v3")
    ok1, total = score(v1)
    ok3, _ = score(v3)
    print(f"  {'版本':<10}{'通过':<10}{'通过率'}")
    print("  " + "-" * 40)
    summarize(v1, "v1")
    summarize(v2, "v2")
    summarize(v3, "v3")

    print()
    print("=" * 88)
    print("③ 逐用例对比：v1 与 v3")
    print("=" * 88)
    for a, b in zip(v1, v3):
        diffs = [k for k in a["checks"] if a["checks"][k] != b["checks"][k]]
        if diffs:
            print(f"  {a['id']}  {a['input']}")
            for k in diffs:
                print(f"      {k:<22}v1={a['checks'][k]}  v3={b['checks'][k]}")

    print()
    print("=" * 88)
    print("④ 总体通过率掩盖了什么")
    print("=" * 88)
    print(f"  v1 通过 {ok1}/{total}，v3 通过 {ok3}/{total}，总数上升。")
    print("  但 v3 在 C4 上引入了新的失败：信息已齐全却要求追问。")
    print()
    print("  只看总数会认为 v3 更好。逐个用例看才能发现回归。")

    print()
    print("=" * 88)
    print("⑤ 结论")
    print("=" * 88)
    print("  1. 提示词改动必须对照固定用例集，不能凭整体感觉")
    print("  2. 总数上升不代表没有回归，需要逐用例比较")
    print("  3. 修复一个问题常引入另一个问题，改动后必须重跑全部用例")
    print("  4. 用例集应包含历史故障，否则同类问题会再次出现")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
