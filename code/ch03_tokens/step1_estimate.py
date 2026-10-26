"""第 3 章 step1：估算口径与真实分词器的偏差（离线可运行）。

运行：
    python code/ch03_tokens/step1_estimate.py

依赖 tiktoken。词表随包分发，不需要联网。

本文件对比两种估算口径与真实分词结果，给出偏差方向与幅度。
所有数字由本文件计算得出，运行可复现。
"""

from __future__ import annotations

import sys

import tiktoken

SAMPLES = {
    "中文": "签收后七天内可以申请无理由退货，定制类商品不适用。",
    "长中文": "签收后七天内，商品未封箱且不影响二次销售的，可以申请无理由退货；"
              "定制类商品、生鲜类商品、已激活的数码产品不适用无理由退货。",
    "英文": "Orders can be returned within seven days of delivery.",
    "代码": 'def check(order_id: str) -> bool:\n    return order_id.startswith("A")',
    "混合": "订单 A12345 的 status 是 delivered，可以申请 return。",
}


def real(text: str, encoding: str = "cl100k_base") -> int:
    return len(tiktoken.get_encoding(encoding).encode(text))


def est_chars(text: str) -> int:
    return len(text)


def est_cjk_en(text: str) -> int:
    """经验公式：汉字 1 个算 1，其余每 4 字符算 1。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + round(other / 4))


ESTIMATORS = [("字符数", est_chars), ("汉字1/英文4", est_cjk_en)]


def main() -> None:
    print("=" * 94)
    print("① 真实分词数与两种估算口径")
    print("=" * 94)
    print(f"  {'类型':<8}{'真实':<8}{'字符数':<9}{'偏差':<10}{'汉字1/英文4':<14}{'偏差'}")
    print("  " + "-" * 90)
    for name, text in SAMPLES.items():
        r = real(text)
        a = est_chars(text)
        b = est_cjk_en(text)
        print(f"  {name:<8}{r:<8}{a:<9}{a / r - 1:+.0%}     {b:<14}{b / r - 1:+.0%}")

    print()
    print("  偏差 = 估算 / 真实 - 1，正数表示高估。")

    print()
    print("=" * 94)
    print("② 偏差的方向")
    print("=" * 94)
    cjk_dev = [est_cjk_en(SAMPLES[k]) / real(SAMPLES[k]) - 1 for k in ("中文", "长中文")]
    other_dev = [est_cjk_en(SAMPLES[k]) / real(SAMPLES[k]) - 1 for k in ("英文", "代码", "混合")]
    print(f"  中文样本偏差        ：{', '.join(f'{d:+.0%}' for d in cjk_dev)}")
    print(f"  英文/代码/混合偏差  ：{', '.join(f'{d:+.0%}' for d in other_dev)}")
    print()
    print("  中文被低估，英文与混合被高估，代码接近真实值。")
    print()
    print("  原因：真实分词器对中文的切分粒度比「一个字」更细，")
    print("  常见双字词、标点都可能单独成 token，因此按字数折算偏小。")
    print("  英文与代码中大量常见单词、缩进、符号被合并为一个 token，")
    print("  按每 4 字符折算则偏大。")

    print()
    print("=" * 94)
    print("③ 同一段文本在不同词表下的计数")
    print("=" * 94)
    text = SAMPLES["长中文"]
    for enc_name in ("cl100k_base", "o200k_base"):
        print(f"  {enc_name:<14}{real(text, enc_name)} token")
    print()
    print("  同一段文本在不同词表下得到不同计数。")
    print("  跨厂商对比成本时，除了单价还要确认 token 计数口径。")

    print()
    print("=" * 94)
    print("④ 结论")
    print("=" * 94)
    print("  1. 字符数口径对四类文本都严重高估，不能用于预算")
    print("  2. 经验公式的偏差方向随文本类型变化：中文低估、英文高估、代码接近")
    print("  3. 不存在对所有文本都准的固定公式")
    print("  4. 计费与预算必须使用服务端返回的 usage")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
