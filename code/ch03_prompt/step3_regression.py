"""第 3 章 step3：为什么"凭感觉改 prompt"一定会翻车（离线）。

运行：
    python code/ch03_prompt/step3_regression.py

上一级的痛点（step2）：你靠加示例把准确率从 86% 提到 100%，很爽。
                     然后老板说"再加一句'要简洁'"，你加了——准确率掉到 79%，但你没发现。
                     因为它对**你刚看的那两条**依然是对的。

这一级做什么：给 prompt 建立**版本 + 回归门**，让每次改动都留下一个能对比的数字。

三个场景，都是真实项目里最高频的"越改越差"：
  A. 加"要简洁" → 模型把关键字段省了 → 字段完整率暴跌
  B. 加"要有礼貌" → 输出变长 → 解析失败率上升
  C. 把 5 条约束塞进一句话 → 模型只记住最后一条 → 指令遵循率下降
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ---- 评测用例：每条都是一次真实的抽取任务 -----------------------------------
@dataclass
class Case:
    ticket: str
    must_have: list[str]  # 输出里必须出现的字段名
    must_contain: list[str]  # 输出里必须出现的值（事实正确性）


CASES = [
    Case("订单A12345 蓝牙耳机 右耳没声音 要退款", ["订单号", "品类", "问题", "诉求"], ["A12345", "耳机", "没声音", "退款"]),
    Case("订单B777 充电宝 充不进电 想换新", ["订单号", "品类", "问题", "诉求"], ["B777", "充电宝", "充不进", "换"]),
    Case("订单C900 手机壳 颜色发错 要退货", ["订单号", "品类", "问题", "诉求"], ["C900", "手机壳", "发错", "退"]),
    Case("订单D321 数据线 用了三天断了", ["订单号", "品类", "问题", "诉求"], ["D321", "数据线", "断", "质量"]),
    Case("订单E654 蓝牙耳机 左耳无声 咨询保修", ["订单号", "品类", "问题", "诉求"], ["E654", "耳机", "无声", "保修"]),
]


# ---- 五个 prompt 版本 -------------------------------------------------------

PROMPTS: dict[str, dict] = {
    "v1 基线": {
        "text": "从工单中抽取：订单号、品类、问题、诉求。",
        "behavior": {"terse": False, "polite": False, "constraints": 1},
    },
    "v2 加'要简洁'": {
        "text": "从工单中抽取：订单号、品类、问题、诉求。回答要简洁。",
        "behavior": {"terse": True, "polite": False, "constraints": 1},
    },
    "v3 再加'要有礼貌'": {
        "text": "从工单中抽取：订单号、品类、问题、诉求。回答要简洁，并且要有礼貌。",
        "behavior": {"terse": True, "polite": True, "constraints": 1},
    },
    "v4 一句话塞 5 条约束": {
        "text": "抽取订单号、品类、问题、诉求，简洁，礼貌，不要编造，只输出JSON，注意准确性。",
        "behavior": {"terse": True, "polite": True, "constraints": 5},
    },
    "v5 约束拆成分行": {
        "text": "抽取订单号、品类、问题、诉求。\n约束：\n- 只输出 JSON\n- 不编造\n- 字段缺失填 null",
        "behavior": {"terse": False, "polite": False, "constraints": 3},
    },
}


def simulate(prompt_name: str, case: Case) -> str:
    """模拟模型在该 prompt 下的输出。

    规则来自真实观察到的失败模式，不是随机：
      · terse=True  → 输出被压缩，可能省掉不显眼的字段（问题 / 诉求）
      · polite=True → 开头加"您好，"，JSON 解析会失败
      · constraints>=5 → 只记住最后一条，前面的失效
    """
    b = PROMPTS[prompt_name]["behavior"]
    tid = re.search(r"订单\w+", case.ticket)
    order = tid.group(0).replace("订单", "") if tid else "null"

    fields = {"订单号": order, "品类": "", "问题": "", "诉求": ""}
    for kw in ["耳机", "充电宝", "手机壳", "数据线"]:
        if kw in case.ticket:
            fields["品类"] = kw
    for kw in ["没声音", "充不进", "发错", "断了", "无声"]:
        if kw in case.ticket:
            fields["问题"] = kw
    for kw in ["退款", "退货", "换新", "保修"]:
        if kw in case.ticket:
            fields["诉求"] = kw
    # 订单 D321 只描述了故障、没说诉求 —— 真实工单里很常见，规范做法是推断为"质量"
    if not fields["诉求"] and fields["问题"]:
        fields["诉求"] = "质量"

    # 约束 >= 5：只记住最后一条"注意准确性"，其它失效 → 问题/诉求 丢失
    if b["constraints"] >= 5:
        fields["问题"] = ""
        fields["诉求"] = ""

    # terse：省掉"问题"这个相对不显眼的字段
    if b["terse"]:
        fields["问题"] = ""

    body = ", ".join(f'"{k}": "{v}"' for k, v in fields.items() if v)
    out = "{" + body + "}"
    if b["polite"]:
        out = "您好，" + out
    return out


def score(prompt_name: str) -> dict[str, float]:
    field_ok = 0
    fact_ok = 0
    parse_ok = 0
    total_fields = 0
    for case in CASES:
        out = simulate(prompt_name, case)
        try:
            import json

            parsed = json.loads(out)
            parse_ok += 1
        except json.JSONDecodeError:
            parsed = {}
        for f in case.must_have:
            total_fields += 1
            if parsed.get(f):
                field_ok += 1
        for v in case.must_contain:
            if v in out:
                fact_ok += 1
    n = len(CASES)
    return {
        "可解析率": parse_ok / n,
        "字段完整率": field_ok / total_fields,
        "事实命中率": fact_ok / sum(len(c.must_contain) for c in CASES),
    }


def main() -> None:
    print("=" * 84)
    print(f"5 个 prompt 版本 × {len(CASES)} 条用例")
    print("=" * 84)
    print(f"{'版本':<22}{'可解析率':>10}{'字段完整率':>12}{'事实命中率':>12}")
    print("-" * 84)
    results = {}
    for name in PROMPTS:
        s = score(name)
        results[name] = s
        print(f"{name:<22}{s['可解析率']:>10.0%}{s['字段完整率']:>12.0%}{s['事实命中率']:>12.0%}")
    print("-" * 84)

    base = results["v1 基线"]
    print("\n" + "=" * 84)
    print("相对 v1 基线的变化（这就是「回归门」要看的东西）")
    print("=" * 84)
    print(f"{'版本':<22}{'可解析':>10}{'字段':>10}{'事实':>10}   判定")
    print("-" * 84)
    for name, s in results.items():
        if name == "v1 基线":
            continue
        d = [s[k] - base[k] for k in ("可解析率", "字段完整率", "事实命中率")]
        worst = min(d)
        verdict = "❌ 退化，禁止上线" if worst < -0.05 else ("⚠️ 有下滑，人工看一眼" if worst < 0 else "✅ 不劣")
        print(
            f"{name:<22}{d[0]:>+10.0%}{d[1]:>+10.0%}{d[2]:>+10.0%}   {verdict}"
        )
    print("-" * 84)

    print("\n" + "=" * 84)
    print("三个真实失败模式")
    print("=" * 84)
    worst_name = max(
        (n for n in results if n != "v1 基线"),
        key=lambda n: -min(results[n][k] - base[k] for k in base),
    )
    REASONS = {
        "v2 加'要简洁'": "「简洁」让输出被压缩，模型省掉了不显眼的字段（问题）——抽取任务最忌讳'简洁'。",
        "v3 再加'要有礼貌'": "「礼貌」让输出加了『您好，』前缀，JSON 直接解析失败——格式约束必须显式禁止寒暄。",
        "v4 一句话塞 5 条约束": "约束塞成一句话，模型只记住最后一条；前面的'简洁''礼貌'反而挤掉了抽取要求。",
        "v5 约束拆成分行": "把约束拆成有序列表后，模型逐条遵守 —— 结构和内容一样重要。",
    }
    print(f"  ❌ 最差版本：{worst_name}")
    print(f"    prompt：{PROMPTS[worst_name]['text']}")
    print(f"    字段完整率 {base['字段完整率']:.0%} → {results[worst_name]['字段完整率']:.0%}")
    print(f"    原因：{REASONS.get(worst_name, '—')}")
    print()
    print("  ⚠️ 注意 v2 和 v3 —— 它们只掉了一个指标，很容易被忽略：")
    for n in ("v2 加'要简洁'", "v3 再加'要有礼貌'"):
        s = results[n]
        print(f"    {n:<18} 可解析 {s['可解析率']:.0%}  字段 {s['字段完整率']:.0%}  事实 {s['事实命中率']:.0%}")

    print("\n" + "=" * 84)
    print("结论：为什么必须建版本 + 回归门")
    print("=" * 84)
    print("  · 「简洁」「礼貌」这类词**不是免费的好话**，它们会和抽取任务抢注意力。")
    print("  · 一次改动往往只伤**一个指标**，而你肉眼只看两三条结果，看不出这一条。")
    print("  · 所以工程上必须做三件事：")
    print("      ① 版本化：每次改动存档，能回滚")
    print("      ② 固定用例：≥ 10 条真实样本，覆盖边界（不是只有 happy path）")
    print("      ③ 自动对比：任何指标掉超过 5% 就拦住")
    print()
    print("  这三件事合起来叫「prompt 回归门」，第 55 章会把它做成流水线。")

    assert results["v1 基线"]["字段完整率"] > results["v4 一句话塞 5 条约束"]["字段完整率"]


if __name__ == "__main__":
    main()
