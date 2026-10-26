"""第 4 章 step1：提示词的六个组成要素（离线可运行）。

运行：
    python code/ch04_prompt/step1_elements.py

本文件用同一组测试输入，对比「缺要素」与「全要素」两种提示词下
可检查项的数量变化。检查项是可机器判定的条件，不是模型打分。

不调用真实模型：判断逻辑写在 prompt_check 里，用规则模拟「按提示词输出」的结果。
目的是展示要素与可检查性之间的关系，不代表真实模型的输出质量。
"""

from __future__ import annotations

import sys


# 六个要素
ELEMENTS = [
    ("角色", "身份与职责范围"),
    ("任务", "要完成什么"),
    ("约束", "不许做什么"),
    ("示例", "输入输出对照"),
    ("输出格式", "结构、字段、顺序"),
    ("反例", "什么样算不合格"),
]

# 同一组输入
CASES = [
    {
        "input": "耳机右耳有杂音，能退吗？",
        "expected": {"intent": "退货咨询", "need_order": "是", "answer_from": "政策"},
    },
    {
        "input": "我上周买的，订单 A12345。",
        "expected": {"intent": "补充信息", "need_order": "否", "answer_from": "政策"},
    },
    {
        "input": "你们公司股票多少钱？",
        "expected": {"intent": "超出范围", "need_order": "否", "answer_from": "拒答"},
    },
]


def build_prompt(include: set[str]) -> str:
    """按包含的要素拼提示词。仅用于展示结构。"""
    parts = []
    if "角色" in include:
        parts.append("你是售后客服，只处理退货与换新相关问题。")
    if "任务" in include:
        parts.append("判断用户意图，并给出答复依据。")
    if "约束" in include:
        parts.append("不得回答与售后无关的问题。不得编造政策条款。")
    if "示例" in include:
        parts.append('示例输入：能换新吗？ → 输出：{"intent":"换新咨询","need_order":"是","answer_from":"政策"}')
    if "输出格式" in include:
        parts.append('输出 JSON，字段固定为 intent、need_order、answer_from，顺序不变。')
    if "反例" in include:
        parts.append("不合格：自由散文、缺少字段、回答范围外问题。")
    if not parts:
        return "回答用户问题。"
    return "\n".join(parts)


def simulate_output(case: dict, include: set[str]) -> dict:
    """模拟按提示词约束输出。要素越全，可判定的字段越多。

    这是规则模拟，不是模型输出。
    它展示的是「某个字段要可判定，需要哪些要素同时在场」。
    """
    out: dict[str, str] = {}

    # intent：需要「任务」说明要判什么，「输出格式」说明怎么表达
    if {"任务", "输出格式"} <= include:
        out["intent"] = case["expected"]["intent"]
    else:
        out["intent"] = "未指定"

    # need_order：需要「角色」限定范围（非售后问题不该问订单），加「输出格式」
    if {"角色", "输出格式"} <= include:
        out["need_order"] = case["expected"]["need_order"]
    else:
        out["need_order"] = "未指定"

    # answer_from：需要「约束」明确超范围要拒答，加「输出格式」
    if {"约束", "输出格式"} <= include:
        out["answer_from"] = case["expected"]["answer_from"]
    else:
        out["answer_from"] = "未指定"

    return out


def checkable_fields(out: dict) -> int:
    """可判定的字段数：不等于「未指定」的字段。"""
    return sum(1 for v in out.values() if v != "未指定")


CONFIGS = [
    ("最小（无要素）", set()),
    ("只有角色", {"角色"}),
    ("角色+格式", {"角色", "输出格式"}),
    ("角色+任务+格式", {"角色", "任务", "输出格式"}),
    ("角色+任务+约束+格式", {"角色", "任务", "约束", "输出格式"}),
    ("全部六项", {name for name, _ in ELEMENTS}),
]


def main() -> None:
    print("=" * 92)
    print("① 六个要素")
    print("=" * 92)
    for name, desc in ELEMENTS:
        print(f"  {name:<8}{desc}")

    print()
    print("=" * 92)
    print("② 逐个加入要素后，可判定字段数的变化")
    print("=" * 92)
    print(f"  {'配置':<24}{'可判定字段':<12}{'说明'}")
    print("  " + "-" * 88)
    for name, inc in CONFIGS:
        total = 0
        for c in CASES:
            total += checkable_fields(simulate_output(c, inc))
        max_fields = len(CASES) * 3
        print(f"  {name:<24}{total}/{max_fields:<10}{'字段越完整，越容易自动校验'}")

    print()
    print("  说明：本表为规则模拟，展示要素与可判定性之间的关系，不是模型实测。")

    print()
    print("=" * 92)
    print("③ 各要素缺失时的具体后果")
    print("=" * 92)
    rows = [
        ("角色", "范围不受限，超范围问题也被回答", "问题被归入售后流程"),
        ("任务", "不知道要产出什么，字段无法确定", "intent 无法判定"),
        ("约束", "编造政策条款，或回答范围外问题", "answer_from 无法判定"),
        ("示例", "输出风格与预期不一致", "需人工核对，无法自动校验"),
        ("输出格式", "自由散文，无法解析", "全部字段无法判定"),
        ("反例", "不知道什么算不合格", "边界情况处理不一致"),
    ]
    print(f"  {'缺失':<10}{'后果':<38}{'受影响的可判定项'}")
    print("  " + "-" * 88)
    for a, b, c in rows:
        print(f"  {a:<10}{b:<38}{c}")

    print()
    print("=" * 92)
    print("④ 六个要素中，对可判定性影响最大的是输出格式")
    print("=" * 92)
    for name, inc in CONFIGS:
        holder = inc - {"输出格式"}
        a = sum(checkable_fields(simulate_output(c, inc)) for c in CASES)
        b = sum(checkable_fields(simulate_output(c, holder)) for c in CASES)
        if a != b:
            print(f"  {name:<24}去掉输出格式：{a} → {b}")

    print()
    print("  没有输出格式，所有字段退化为不可判定，无论其他要素是否齐全。")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
