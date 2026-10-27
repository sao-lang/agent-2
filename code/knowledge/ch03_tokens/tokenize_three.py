"""三种文本的真实 token 数，以及 len(text)//2 估算的偏差。

token 的切分由词表决定：tiktoken 里的词表是 BPE 合并规则统计出来的，不是按字符、
也不是按词。本脚本用两个词表（cl100k_base 与 o200k_base）各切一遍同一段文字，
同时算出最常见的估算式 len(text)//2 的偏差。

离线可跑：词表文件已在本机缓存。首次在某台机器上运行时 tiktoken 会下载词表文件。
"""

from __future__ import annotations

import tiktoken

CHINESE = "签收后 7 天内可以申请退货，商品需要保持未拆封，定制商品不支持退货。"
ENGLISH = (
    "The return window is 7 days after delivery. Items must be unopened. "
    "Custom-made products are not eligible for refund."
)
CODE = (
    "def can_return(signed_days_ago: int, opened: bool, custom: bool) -> bool:\n"
    "    if custom:\n"
    "        return False\n"
    "    return signed_days_ago <= 7 and not opened\n"
)

TEXTS = {"中文": CHINESE, "英文": ENGLISH, "代码": CODE}


def estimate_chars_div2(text: str) -> int:
    """最常见的一种估算：字数除以 2。它假设平均两个字符一个 token。"""
    return len(text) // 2


def pieces(enc: tiktoken.Encoding, text: str) -> list[str]:
    """切成可读片段：每个 token 对应的字节按 UTF-8 尽力解码。

    有的 token 只覆盖一个汉字的半个字节，单独解码会得到替换符；
    这正是"token 边界与字符边界不对齐"的直接证据。
    """
    out: list[str] = []
    for token in enc.encode(text):
        raw = enc.decode_single_token_bytes(token)
        out.append(raw.decode("utf-8", errors="replace").replace("\n", "\\n"))
    return out


def deviation(estimate: int, actual: int) -> str:
    """估算相对真实的偏差，正数表示多算。"""
    return f"{(estimate - actual) / actual:+.0%}"


def main() -> None:
    enc_cl = tiktoken.get_encoding("cl100k_base")
    enc_o = tiktoken.get_encoding("o200k_base")

    print("=" * 78)
    print("一、同一段文字，两个词表，两种数法")
    print("=" * 78)
    print(f"{'文本':<6}{'字符数':>8}{'len//2':>9}{'cl100k':>9}{'偏差':>8}{'o200k':>8}{'偏差':>8}")
    print("-" * 78)
    for name, text in TEXTS.items():
        chars = len(text)
        est = estimate_chars_div2(text)
        n_cl = len(enc_cl.encode(text))
        n_o = len(enc_o.encode(text))
        print(f"{name:<6}{chars:>8}{est:>9}{n_cl:>9}{deviation(est, n_cl):>8}"
              f"{n_o:>8}{deviation(est, n_o):>8}")

    print()
    print("=" * 78)
    print("二、cl100k_base 切出来的片段")
    print("=" * 78)
    for name, text in TEXTS.items():
        body = "|".join(pieces(enc_cl, text))
        print(f"{name}：{body}")

    print()
    print("=" * 78)
    print("三、o200k_base 切出来的片段")
    print("=" * 78)
    for name, text in TEXTS.items():
        body = "|".join(pieces(enc_o, text))
        print(f"{name}：{body}")

    print()
    print("=" * 78)
    print("四、单字与词的开销")
    print("=" * 78)
    for word in ("退货", "退货政策", "已签收", "refund", "return window", "A1001"):
        print(f"  {word!r:<18} cl100k={len(enc_cl.encode(word))}  o200k={len(enc_o.encode(word))}")


if __name__ == "__main__":
    main()
