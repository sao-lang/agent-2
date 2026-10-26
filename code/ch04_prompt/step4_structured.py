"""第 4 章 step4：结构化输出的三种实现路径（离线可运行）。

运行：
    python code/ch04_prompt/step4_structured.py

三种路径：
    A 只在提示词里要求 JSON
    B 用工具调用的参数 schema 强制结构
    C 用厂商原生结构化输出（受约束解码）

本文件用规则模拟三种路径在「非法输出」上的表现，展示差异来源。
不调用真实模型。所有计数由本文件计算，运行可复现。
"""

from __future__ import annotations

import json
import random
import sys

SCHEMA_FIELDS = ["intent", "need_order", "answer_from"]
LEGAL_INTENT = {"退货咨询", "换新咨询", "补充信息", "超出范围"}

CASES = [
    ("耳机右耳有杂音，能退吗？", {"intent": "退货咨询", "need_order": "是", "answer_from": "政策"}),
    ("你们公司股票多少钱？", {"intent": "超出范围", "need_order": "否", "answer_from": "拒答"}),
    ("我想把上次那个退掉", {"intent": "补充信息", "need_order": "是", "answer_from": "政策"}),
]


def simulate_text_prompt(rng: random.Random) -> tuple[bool, str]:
    """A：只在提示词里要求 JSON。模型可能加解释、用代码块、字段名漂移。"""
    kind = rng.choice(["纯净", "带解释", "代码块", "字段名漂移", "枚举越界"])
    if kind == "纯净":
        return True, "合法"
    if kind == "带解释":
        return False, '前置说明后跟 JSON：好的，结果如下 {...}'
    if kind == "代码块":
        return False, '被 ```json 包裹，直接 json.loads 失败'
    if kind == "字段名漂移":
        return False, 'needOrder 而不是 need_order'
    return False, "intent 取了枚举外的值"


def simulate_tool_call(rng: random.Random) -> tuple[bool, str]:
    """B：用工具调用。参数结构由 schema 约束，但取值与语义仍需校验。"""
    kind = rng.choice(["合法", "合法", "合法", "枚举越界", "缺字段"])
    if kind == "合法":
        return True, "合法"
    if kind == "枚举越界":
        return False, "结构合法但 intent 不在枚举内"
    return False, "必填字段缺失，由服务端 schema 校验拒绝"


def simulate_native(rng: random.Random) -> tuple[bool, str]:
    """C：厂商原生结构化输出。结构由解码过程保证，取值仍需业务校验。"""
    kind = rng.choice(["合法"] * 9 + ["枚举越界"])
    if kind == "合法":
        return True, "合法"
    return False, "结构一定合法，但取值可能需要业务层再判断"


PATHS = [
    ("A 提示词要求 JSON", simulate_text_prompt),
    ("B 工具调用 schema", simulate_tool_call),
    ("C 原生结构化输出", simulate_native),
]


def main() -> None:
    print("=" * 90)
    print("① 三种路径的失败形态")
    print("=" * 90)
    for name, fn in PATHS:
        rng = random.Random(7)
        seen: dict[str, int] = {}
        for _ in range(500):
            ok, why = fn(rng)
            if not ok:
                seen[why] = seen.get(why, 0) + 1
        print(f"\n  【{name}】500 次中的失败形态")
        if not seen:
            print("    无失败")
        for why, n in seen.items():
            print(f"    {n:>4} 次  {why}")

    print()
    print("  说明：本表为规则模拟，用于展示三种路径的失败来源不同，不是模型实测。")

    print()
    print("=" * 90)
    print("② 三种路径分别在防什么")
    print("=" * 90)
    rows = [
        ("A 提示词要求 JSON", "输出是 JSON", "否", "需要解析、清洗、重试"),
        ("B 工具调用 schema", "参数符合 schema", "是，结构层", "可能缺字段、枚举越界"),
        ("C 原生结构化输出", "输出符合 schema", "是，解码层", "取值语义仍需业务校验"),
    ]
    print(f"  {'路径':<22}{'保证什么':<20}{'结构是否保证':<16}{'仍需处理'}")
    print("  " + "-" * 86)
    for a, b, c, d in rows:
        print(f"  {a:<22}{b:<20}{c:<16}{d}")

    print()
    print("=" * 90)
    print("③ 三种路径都需要业务校验")
    print("=" * 90)
    print("  结构合法不等于语义正确。以下问题三条路径都无法自动解决：")
    print("    · intent 取值合法，但判断错了")
    print("    · need_order 为「否」，但对这个请求应当为「是」")
    print("    · answer_from 为「政策」，但引用的条款不适用于该商品")
    print()
    print("  因此结构化输出解决的是「能否解析」，不解决「内容对不对」。")

    print()
    print("=" * 90)
    print("④ 校验与修复的层次")
    print("=" * 90)
    layers = [
        ("解析层", "能否解析为 JSON", "json.loads 失败则重试"),
        ("结构层", "字段是否齐全、类型是否正确", "缺字段则按 schema 报错"),
        ("取值层", "枚举是否越界、范围是否合法", "越界则重试或降级"),
        ("语义层", "判断是否符合业务事实", "需要外部信号，无法自动"),
    ]
    print(f"  {'层次':<10}{'检查什么':<34}{'失败后'}")
    print("  " + "-" * 86)
    for a, b, c in layers:
        print(f"  {a:<10}{b:<34}{c}")

    print()
    print("=" * 90)
    print("⑤ 结论")
    print("=" * 90)
    print("  1. 只在提示词里要求格式，失败形态最多，需要完整解析与重试")
    print("  2. 工具调用与原生结构化输出把结构错误挡在生成阶段")
    print("  3. 三条路径都不能保证语义正确")
    print("  4. 校验分四层，前三层可自动，第四层需要外部信号")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
