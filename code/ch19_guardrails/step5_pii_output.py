"""第 19 章 step5：输出护栏 —— PII 脱敏的顺序陷阱（离线）。

运行：
    python code/ch19_guardrails/step5_pii_output.py

上一级的痛点：入口和工具都守住了，但**模型输出**里可能带着用户的敏感信息。
这一级做什么：演示一个真实的 bug ——

    身份证号 110101199001011234
    先过手机号规则 → 中间的 11 位被当成手机号 → 结果 "110101[手机号]4"

**比不脱敏更危险**：你会以为已经脱敏了。

修法三条：长模式优先 / 边界断言 / 每个正则都配用例。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.guardrails import PII_PATTERNS, check_output  # noqa: E402

# ❌ 历史版本：手机号规则没有词边界，且先于身份证执行
LEGACY_V1 = {
    "phone": (r"1[3-9]\d{9}", "[手机号]"),
    "id_card": (r"\d{17}[\dXx]", "[身份证]"),
}

# ❌ 第一版：顺序错了，手机号在身份证前面
WRONG_ORDER = {
    "phone": (r"\b1[3-9]\d{9}\b", "[手机号]"),
    "id_card": (r"\b\d{17}[\dXx]\b", "[身份证]"),
    "card": (r"\b\d{16,19}\b", "[银行卡]"),
}

# ❌ 第二版：顺序对了，但没加边界断言
NO_BOUNDARY = {
    "id_card": (r"\d{17}[\dXx]", "[身份证]"),
    "card": (r"\d{16,19}", "[银行卡]"),
    "phone": (r"1[3-9]\d{9}", "[手机号]"),
}

SAMPLES = [
    ("身份证", "身份证 110101199001011234 已核验。"),
    ("手机号", "您的订单已发货，联系电话 13812345678。"),
    ("银行卡", "退款已打到 6222021234567890123 这张卡。"),
    ("邮箱", "发票已发送至 zhangwei@example.com。"),
    ("混合", "张伟 13812345678，身份证 110101199001011234，卡号 6222021234567890123。"),
]


def mask(text: str, patterns: dict) -> str:
    out = text
    for _name, (pat, repl) in patterns.items():
        out = re.sub(pat, repl, out)
    return out


def main() -> None:
    print("=" * 84)
    print("同一批文本，三种脱敏实现")
    print("=" * 84)
    print(f"{'输入类型':<8}{'原文':<46}{'第一版(顺序错)':<22}{'第二版(无边界)'}")
    print("-" * 84)
    for label, text in SAMPLES:
        v1 = mask(text, LEGACY_V1)
        v2 = mask(text, NO_BOUNDARY)
        print(f"{label:<8}{text[:44]:<46}{v1[:20]:<22}{v2[:22]}")

    print("\n" + "=" * 84)
    print("★ 第一版的 bug 长什么样")
    print("=" * 84)
    t = "身份证 110101199001011234 已核验。"
    # 用最贴近真实 bug 的写法：手机号规则没有词边界，先于身份证执行
    naive_phone = {"phone": (r"1[3-9]\d{9}", "[手机号]"), "id_card": (r"\d{17}[\dXx]", "[身份证]")}
    print(f"  原文：{t}")
    print(f"  第一版（手机号无边界、先执行）：{mask(t, naive_phone)}")
    print()
    print("  身份证被切成了『110101 + [手机号] + 4』——")
    print("  既没有真正脱敏（前半段还是原文），又让输出变得看不懂。")
    print()
    print("  ⚠️ 注意表格里出现的两种错法：")
    print("     · 身份证被切成 `110101[手机号]4`（短模式无边界）")
    print("     · 19 位银行卡被切成 `[身份证]3`（长模式抢先匹配）")
    print("     两种都是『顺序 + 边界』没配对 —— 而多数测试样例都是干净的整数串，")
    print("     所以你很可能一直看不到它。")
    print()
    print("  而且这比**不脱敏**更危险：日志里看起来『已经有 [手机号] 了』，")
    print("  没人会再检查一遍。")

    print("\n" + "=" * 84)
    print("★ 第二版的 bug：没有边界断言")
    print("=" * 84)
    for label, text in SAMPLES[:3]:
        print(f"  {label}：{mask(text, NO_BOUNDARY)}")
    print()
    print("  看着好像也对？那是因为样例恰好是独立的数字。")
    print("  试一个更真实的：")
    tricky = "订单号 2026101200012345678 关联身份证 110101199001011234"
    print(f"    原文：{tricky}")
    print(f"    第二版：{mask(tricky, NO_BOUNDARY)}")
    print("    → 长数字串被从中间切断，脱出来的是**错位**的占位符。")

    print("\n" + "=" * 84)
    print("★ 正式版本（本章 code/common/guardrails.py）")
    print("=" * 84)
    for label, text in SAMPLES:
        _d, out = check_output(text)
        print(f"  {label}：{out}")
    print()
    print("  规则长这样：")
    for name, (pat, repl) in PII_PATTERNS.items():
        print(f"    {name:<8}{repl:<10}{pat}")

    print("\n" + "=" * 84)
    print("修法三条（缺一不可）")
    print("=" * 84)
    print("  1. 顺序：更长的、更具体的模式先匹配")
    print("     身份证（18 位）> 银行卡（16~19 位）> 手机号（11 位）")
    print()
    print("  2. 边界断言：用 (?<!\\d) 和 (?!\\d) 包住短模式")
    print("     否则它会在长数字串的中间匹配成功")
    print()
    print("  3. 用例：每个正则都要有『容易混淆』的输入")
    print("     · 身份证（会被手机号切）")
    print("     · 19 位银行卡（会被 16 位规则切）")
    print("     · 订单号（长数字，不该被当成手机号）")

    print("\n" + "=" * 84)
    print("为什么 PII 是『脱敏』而不是『拒绝』")
    print("=" * 84)
    print("  ❌ 你的订单已发货，有问题请联系客服。      ← 拒绝了，用户拿不到信息")
    print("  ✅ 你的订单已发货，联系电话 [手机号]。      ← 脱敏了，用户仍然理解")
    print()
    print("  例外：如果输出里出现**别人的** PII（跨用户泄露），必须整段拒绝，不能只脱敏。")


if __name__ == "__main__":
    main()
