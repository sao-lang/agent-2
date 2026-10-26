"""第 4 章 step5：完整提示词的构成与开销（离线可运行）。

运行：
    python code/ch04_prompt/step5_full_prompt.py

本文件把 4.2 节给出的完整提示词拆成六个要素，
统计每部分的 token 开销，并检查六要素是否齐全。

token 计数使用 tiktoken，可复现。
"""

from __future__ import annotations

import sys

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")


# 完整提示词按要素切分
PARTS = {
    "角色": "你是售后客服系统的意图识别模块。",
    "任务": "读取用户的一句话，判断其意图，输出结构化结果。",
    "约束": (
        "1. 只处理退货、换新、物流、退款四类问题。其他问题一律标记为「超出范围」。\n"
        "2. 不得输出 JSON 以外的任何文字，不得使用代码块包裹。\n"
        "3. 不得引用具体条款内容，只标记依据来源。\n"
        "4. 用户未提供订单号时，need_order 仍填「是」，由下游追问。"
    ),
    "取值": (
        "intent：退货咨询 | 换新咨询 | 物流查询 | 退款进度 | 补充信息 | 超出范围\n"
        "need_order：是 | 否\n"
        "answer_from：政策 | 订单 | 无"
    ),
    "输出格式": '严格按以下 JSON 输出，字段顺序固定：\n{"intent": <枚举值>, "need_order": <是或否>, "answer_from": <枚举值>}',
    "示例": (
        '输入：耳机右耳有杂音，能退吗？\n输出：{"intent": "退货咨询", "need_order": "是", "answer_from": "政策"}\n\n'
        '输入：我上周买的，订单 A12345。\n输出：{"intent": "补充信息", "need_order": "否", "answer_from": "无"}\n\n'
        '输入：你们公司股票多少钱？\n输出：{"intent": "超出范围", "need_order": "否", "answer_from": "无"}'
    ),
    "反例": (
        "- 好的，根据政策您可以退货。{...}          ← 回答了问题，超出「只判断意图」范围\n"
        '- ```json {"intent": "退货咨询"} ```        ← 使用代码块\n'
        '- {"intent": "咨询", "need_order": "是"}     ← 枚举越界，缺字段\n'
        '- {"intent": "退货咨询", ..., "answer_from": "《售后规则》第三章"} ← 引用具体条款'
    ),
}

# 六要素对应的部分（取值与输出格式合并计为「输出格式」）
ELEMENT_MAP = {
    "角色": ["角色"],
    "任务": ["任务"],
    "约束": ["约束"],
    "示例": ["示例"],
    "输出格式": ["取值", "输出格式"],
    "反例": ["反例"],
}


def ntok(s: str) -> int:
    return len(ENC.encode(s))


def main() -> None:
    total = sum(ntok(v) for v in PARTS.values())

    print("=" * 82)
    print("① 各部分开销")
    print("=" * 82)
    print(f"  {'部分':<10}{'token':<8}{'占比':<8}{'首行'}")
    print("  " + "-" * 78)
    for name, text in PARTS.items():
        n = ntok(text)
        first = text.split("\n")[0][:34]
        print(f"  {name:<10}{n:<8}{n / total:<8.0%}{first}")
    print(f"  {'合计':<10}{total}")

    print()
    print("=" * 82)
    print("② 按六要素归并")
    print("=" * 82)
    print(f"  {'要素':<10}{'token':<8}{'占比'}")
    print("  " + "-" * 42)
    for elem, parts in ELEMENT_MAP.items():
        n = sum(ntok(PARTS[p]) for p in parts)
        print(f"  {elem:<10}{n:<8}{n / total:.0%}")

    print()
    print("=" * 82)
    print("③ 六要素齐全性检查")
    print("=" * 82)
    missing = [e for e in ELEMENT_MAP if not any(PARTS[p] for p in ELEMENT_MAP[e])]
    print(f"  缺失要素：{missing if missing else '无'}")
    print("  六要素共 {} 个，本提示词覆盖 {} 个。".format(len(ELEMENT_MAP), len(ELEMENT_MAP) - len(missing)))

    print()
    print("=" * 82)
    print("④ 与最小提示词的开销对比")
    print("=" * 82)
    minimal = "判断用户意图。"
    print(f"  最小提示词      {ntok(minimal)} token")
    print(f"  完整提示词      {total} token")
    print(f"  倍数            {total / ntok(minimal):.1f}")
    print()
    print("  完整提示词的开销约为最小版本的数十倍。")
    print("  这部分开销是固定的，每一轮请求都要支付。")
    print("  因此完整提示词应放在稳定层（第 4.3 节），以便命中前缀缓存。")

    print()
    print("=" * 82)
    print("⑤ 结论")
    print("=" * 82)
    print("  1. 提示词开销主要来自示例与约束，不是角色与任务")
    print("  2. 完整提示词开销是固定的，放在稳定层可被缓存")
    print("  3. 六要素齐全性可用脚本检查，不需要人工核对")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
