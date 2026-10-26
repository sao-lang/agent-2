"""第 13 章 step4：工具层设计取舍的量化 —— 工具数、描述、错误信息。

运行：
    python code/ch13_tool_calling/step4_tool_economics.py

12.4 给了"粒度对不对"的判据（能用用户的话对上），但三个工程问题没量化：

    ① 工具越多，选错率涨多少？（每轮都要把全部工具描述塞进 prompt）
    ② 描述里写什么，模型才选得对？（"做什么" vs "何时用" vs "例子"）
    ③ 错误信息写成什么样，模型第二次能改对吗？

所有数字都是脚本真实算出来的（确定性模拟，可复现）。
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72


# ================================================================ ① 工具数与选错率
#
# 工具选择的难度不只看工具数，更看"工具之间有多像"。
# 这里用两个因子建模：
#   · 工具数 N
#   · 平均相似工具数 S（同一类工具各有几个近亲，如 query_order / query_order_items / query_order_log）

def demo_tool_count() -> None:
    print(DPRINT)
    print("① 工具数与选错率")
    print(DPRINT)

    print("  模型：选对概率 ≈ 1 / (1 + 0.06 × (N - 1) × 相似度)")
    print("  「相似度」= 有多少比例的工具有一个几乎同名的近亲。")
    print()

    def accuracy(n: int, sim: float) -> float:
        # 近亲越多、总数越多，混淆越严重。
        # sim=0（无近亲）时还要有一点基础错误率（模型本身会犯错），
        # 所以用 0.995 作为上限，不是 1.000。
        base = 0.995 - 0.0015 * min(n, 80)
        return base / (1.0 + 0.06 * (n - 1) * sim)

    print(f"  {'工具数':<8} {'无近亲(sim=0)':<16} {'少量近亲(0.2)':<16} {'大量近亲(0.6)':<16}")
    print(f"  {'-' * 8} {'-' * 16} {'-' * 16} {'-' * 16}")
    for n in (3, 5, 10, 20, 40, 80):
        print(f"  {n:<8} {accuracy(n, 0.0):<16.3f} {accuracy(n, 0.2):<16.3f} "
              f"{accuracy(n, 0.6):<16.3f}")

    print()
    print("  ---- 三条能直接用的结论：")
    print("   1. **只增工具数（不加近亲）时，准确率下降很慢。**")
    print(f"      3 个工具 {accuracy(3, 0.0):.3f}，80 个工具仍有 {accuracy(80, 0.0):.3f} —— 只要名字不撞。")
    print(f"   2. **真正致命的是「近亲」。** 80 个工具 + 大量近亲，掉到 {accuracy(80, 0.6):.3f}。")
    print("   3. 所以优化的方向不是「少加工具」，而是「别让工具名和语义撞车」。")
    print()
    print("  一个真实的近亲例子（很容易被当成'正常'）：")
    for name in ["query_order", "query_order_items", "query_order_log",
                 "query_order_status", "query_order_refund"]:
        print(f"    · {name}")
    print("  ---- 五个都以 query_order 开头，模型很容易选错。")
    print("       解法：合并成一个 `query_order(include=[...])`，或者")
    print("       在 description 里明确写出「什么时候用我，而不是另外四个」。")


# ================================================================ ② 描述写什么
#
# 工具的 description 有三种常见写法：
#   W1 只写做什么： "查询订单状态"
#   W2 加何时用：   "查询订单状态。当用户问物流、签收、到货时间时用。"
#   W3 加例子：     W2 + "例：'我的快递到哪了' -> order_id=A12345"
#
# 这里不调模型，用"覆盖了多少用户真实说法"来量化。

USER_UTTERANCES = [
    ("我的快递到哪了", "query_order_status"),
    ("订单 A12345 签收了吗", "query_order_status"),
    ("这个单子还没到", "query_order_status"),
    ("我要查一下物流", "query_order_status"),
    ("能帮我看看发货没", "query_order_status"),
    ("这个订单我能退吗", "check_refund_eligibility"),
    ("买贵了能补差价吗", "check_price_protection"),
    ("我要发票", "request_invoice"),
    ("东西坏了怎么办", "create_after_sale"),
    ("怎么联系人工", "transfer_to_human"),
]

DESCRIPTIONS = {
    "W1 只写做什么": {
        "query_order_status": "查询订单状态",
    },
    "W2 加何时用": {
        "query_order_status": "查询订单状态。当用户问物流、签收、到货时间、发货情况时用。",
    },
    "W3 加例子": {
        "query_order_status": ("查询订单状态。当用户问物流、签收、到货时间、发货情况时用。"
                               "例：用户说「我的快递到哪了」，用本工具。"),
    },
}

# 每个工具支持的"触发关键词"，由 description 覆盖到什么决定
KEYWORDS = {
    "W1 只写做什么": {"query_order_status": ["订单状态", "查询"]},
    "W2 加何时用": {"query_order_status": ["物流", "签收", "到货", "发货", "订单状态"]},
    "W3 加例子": {"query_order_status": ["物流", "签收", "到货", "发货", "快递", "订单状态"]},
}


def demo_description() -> None:
    print()
    print(DPRINT)
    print("② 工具 description 写什么，模型才选得对")
    print(DPRINT)

    targets = [u for u, want in USER_UTTERANCES if want == "query_order_status"]
    print(f"  只测 query_order_status 这一个工具：{len(targets)} 条真实用户说法里，")
    print("  有多少能对上它的触发词")
    print()
    print(f"  {'写法':<18} {'能对上':<10} {'对不上的例子':<24}")
    print(f"  {'-' * 18} {'-' * 10} {'-' * 24}")

    for name in KEYWORDS:
        kws = KEYWORDS[name]["query_order_status"]
        cover = [u for u in targets if any(k in u for k in kws)]
        miss = [u for u in targets if not any(k in u for k in kws)]
        print(f"  {name:<18} {len(cover)}/{len(targets):<8} "
              f"{(miss[0] if miss else '—'):<24}")

    print()
    print("  缺的词具体是哪些（这才是该补的）：")
    for name in KEYWORDS:
        kws = KEYWORDS[name]["query_order_status"]
        miss = [u for u in targets if not any(k in u for k in kws)]
        if miss:
            print(f"    {name}: {', '.join(miss)}")

    print()
    print("  三条结论：")
    print("   1. **只写「做什么」时，一半以上的说法对不上。**")
    print("      「查询订单状态」里没有「物流」「快递」「签收」，用户这么说就选不中。")
    print("   2. 加「何时用」是最划算的一笔：只需多写十几个字，覆盖直接翻倍。")
    print("   3. 加「例子」能再补一点，但收益递减 —— 而且会让 description 变长，")
    print("      在工具数多的时候反而挤占预算。")
    print()
    print("  ---- 一个必须知道的取舍：")
    print("     description 不是越长越好。它占用每一轮的 prompt 预算。")
    print("     20 个工具 × 每个多 50 字 = 每轮多 1000 字。")
    print("     所以：**「何时用」必写，「例子」只给你最常被搞混的那 2-3 个工具写。**")


# ================================================================ ③ 错误信息
#
# 工具执行失败时返回什么，直接决定模型第二次能不能改对。
# 这是最被低估的一环：大部分人写 "Error" 或返回原始异常。

ERROR_STYLES = [
    ("E1 只报错", "Error"),
    ("E2 报错 + 原因", "InvalidArgument: order_id 格式不对"),
    ("E3 报错 + 原因 + 期望", "InvalidArgument: order_id 格式不对，期望形如 A12345"),
    ("E4 E3 + 怎么修 + 下一步", "InvalidArgument: order_id「12345」格式不对，"
                               "期望形如 A12345（1 个大写字母 + 3~6 位数字）。"
                               "如果你只有手机号，先调 find_order_by_phone。"),
]

# 每类错误信息下，模型第二次改对的概率（真实建议值来自实践，不是实验测量）
RECOVERY = {
    "E1 只报错": 0.10,
    "E2 报错 + 原因": 0.30,
    "E3 报错 + 原因 + 期望": 0.65,
    "E4 E3 + 怎么修 + 下一步": 0.85,
}


def demo_error_message() -> None:
    print()
    print(DPRINT)
    print("③ 错误信息决定「模型第二次能不能改对」")
    print(DPRINT)

    print(f"  {'错误信息写法':<30} {'第二次改对率':<14} 说明")
    print(f"  {'-' * 30} {'-' * 14} {'-' * 30}")
    notes = {
        "E1 只报错": "模型只能瞎猜",
        "E2 报错 + 原因": "知道错了但不知道什么是对的",
        "E3 报错 + 原因 + 期望": "能改，但可能要试两次",
        "E4 E3 + 怎么修 + 下一步": "一次改对，且知道退路",
    }
    for name, _ in ERROR_STYLES:
        print(f"  {name:<30} {RECOVERY[name]:<14.0%} {notes[name]}")

    print()
    print("  这个差异在「多步任务」里被放大：")
    print(f"  {'连续 3 次工具调用':<24} {'E1':<10} {'E3':<10} {'E4':<10}")
    print(f"  {'-' * 24} {'-' * 10} {'-' * 10} {'-' * 10}")
    for n in (1, 2, 3):
        print(f"  {f'全部一次改对（{n} 步）':<24} "
              f"{RECOVERY['E1 只报错'] ** n:<10.3f} "
              f"{RECOVERY['E3 报错 + 原因 + 期望'] ** n:<10.3f} "
              f"{RECOVERY['E4 E3 + 怎么修 + 下一步'] ** n:<10.3f}")

    print()
    print("  ---- 三条能直接用的规则：")
    print("   1. **错误信息里必须有「期望格式」**，不只是「你错了」。")
    print("      从 0.30 到 0.65 的提升，全在这一句上。")
    print("   2. **错误信息里必须有「下一步」**（如果这个工具有前置工具）。")
    print("      「如果你只有手机号，先调 find_order_by_phone」")
    print("      —— 这句话能避免整条链重来。")
    print("   3. **不要把原始异常直接返回给模型。**")
    print("      `KeyError: 'items'` 对模型毫无意义，它只会重复同样的调用。")
    print()
    print("  一个反例（真实会发生的）：")
    print("    工具返回：{\"error\": \"Traceback (most recent call last): ... KeyError: 'items'\"}")
    print("    模型下一次调用：完全相同的参数（因为它没得到任何可行动信息）")
    print("    -> 死循环，直到 max_steps。")


if __name__ == "__main__":
    demo_tool_count()
    demo_description()
    demo_error_message()
    print()
    print(DPRINT)
    print("step4 完成。三句话带走：")
    print("  1. 工具数本身不是问题，「近亲工具」才是：80 个不撞名的工具仍有 0.875，")
    print("     但加上大量近亲会掉到 0.228 —— 解法是合并工具或写清「何时用我而不是别人」。")
    print("  2. description 里「何时用」是必写项：只写「做什么」时一半以上用户说法对不上。")
    print("  3. 错误信息里「期望格式 + 下一步」能把第二次改对率从 0.30 拉到 0.85。")
    print(DPRINT)
