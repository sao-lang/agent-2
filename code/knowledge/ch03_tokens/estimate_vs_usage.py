"""估算 token 与实际 usage 的偏差。

不联网。用一个简化切分器估算，再与一组"服务端返回的 usage"对照。
usage 数值是演示用的常数，代表不同内容类型下估算方法偏离的程度。
"""

from __future__ import annotations

import re

# 演示用的 usage（输入 token 数），模拟服务端统计结果
ACTUAL_PROMPT_TOKENS = {
    "中文叙述": 148,
    "英文叙述": 96,
    "代码": 213,
    "中英混排": 172,
}


def estimate_chars_div2(text: str) -> int:
    """常见的最粗估算：字符数 / 2。"""
    return len(text) // 2


def estimate_rough(text: str) -> int:
    """稍细一点：汉字按 1，英文按约 1/4 词长，标点按 1。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z]+", text))
    punct = len(re.findall(r"[^\u4e00-\u9fffA-Za-z0-9\s]", text))
    return cjk + max(1, int(words * 1.3)) + punct


SAMPLES = {
    "中文叙述": "本店商品在签收后七天内可以申请退货，需要保持商品完整，并保留原包装与发票。" * 4,
    "英文叙述": "Returns are accepted within seven days of delivery. Items must be unused and in original packaging with all tags attached. " * 3,
    "代码": "def refund(order_id: str) -> dict:\n    order = repo.get(order_id)\n    if order.shipped:\n        return {'ok': False, 'reason': 'shipped'}\n    return {'ok': True}\n\n" * 4,
    "中英混排": "退货政策：自 signment 签收日起 7 天内，可通过 /api/refund 接口提交退货申请。" * 6,
}


def main() -> None:
    print(f"{'类型':<10}{'字符数':>8}{'估算A':>8}{'估算B':>8}{'实际':>8}  {'A 偏差':>10}{'B 偏差':>10}")
    print("-" * 76)

    for kind, text in SAMPLES.items():
        actual = ACTUAL_PROMPT_TOKENS[kind]
        a = estimate_chars_div2(text)
        b = estimate_rough(text)
        da = (a - actual) / actual
        db = (b - actual) / actual
        print(f"{kind:<10}{len(text):>8}{a:>8}{b:>8}{actual:>8}  {da:>+9.0%}{db:>+9.0%}")

    print()
    print("两种估算的偏差方向不同：")
    print("  字符数/2 在中文上偏低，在代码上偏高。")
    print("  按字切分的估算在纯中文上接近，在英文与代码上偏差较大。")
    print()
    print("结论：估算只能用来做量级判断。")
    print("      任何影响成本或截断的决策，都必须用 usage 的实际值。")


if __name__ == "__main__":
    main()
