"""token 是怎么切出来的：为什么同样的字符数，token 数差很多。

不联网。用词表最长匹配模拟子词切分，演示三件事：
  1. 常见的词整块保留，罕见的词被拆开
  2. 同一个意思，写法不同，token 数不同
  3. 空格、大小写、标点都占位置

这不是真实 tokenizer。真实实现用 BPE 之类的算法在大规模语料上统计合并规则，
但"常见整块、罕见拆开"这个性质是一致的。
"""

from __future__ import annotations

from dataclasses import dataclass

# 演示用词表：常见词整块，罕见词不在表里，会被拆成单字
VOCAB = {
    "退货", "政策", "签收", "商品", "物流", "订单",
    "refund", "return", "policy", "order", "the", "a", "of",
    "7", " ", "天", "内", "可", "以", "申", "请",
}


@dataclass
class Split:
    pieces: list[str]

    @property
    def count(self) -> int:
        return len(self.pieces)


def tokenize(text: str) -> Split:
    """最长匹配：从当前位置开始，找词表里最长的匹配；找不到就取一个字符。"""
    pieces: list[str] = []
    i = 0
    max_len = max(len(w) for w in VOCAB)

    while i < len(text):
        matched = None
        for n in range(min(max_len, len(text) - i), 0, -1):
            chunk = text[i:i + n]
            if chunk in VOCAB:
                matched = chunk
                break
        if matched is None:
            matched = text[i]
        pieces.append(matched)
        i += len(matched)

    return Split(pieces)


SAMPLES = {
    "常见词组合": "退货政策",
    "同义但更口语": "可以退货吗",
    "加空格": "退货 政策",
    "英文整词": "refund policy",
    "英文连写": "refundpolicy",
    "罕见词": "签收确认单",
}


def main() -> None:
    print(f"{'写法':<12}{'字符数':>8}{'token 数':>10}  切片")
    print("-" * 80)

    for label, text in SAMPLES.items():
        s = tokenize(text)
        print(f"{label:<12}{len(text):>8}{s.count:>10}  {'|'.join(s.pieces)}")

    print()
    print("三个观察：")
    print()
    print("1. 常见词整块保留。'退货政策' 是 4 个字，但切成 2 个 token。")
    print("   词表里没有的词会被拆成单字，'签收确认单' 里的'确认单'不在表里，")
    print("   于是逐字拆开。真实 tokenizer 里，罕见专有名词、生造词都是这样被拆碎的。")
    print()
    print("2. 同一个意思，写法不同，token 不同。")
    print("   '退货政策' 与 '可以退货吗' 表达相近意图，后者多出 2 个 token。")
    print()
    print("3. 空格也算 token。'退货 政策' 比 '退货政策' 多 1 个。")
    print("   英文里空格通常并入前一个词，中文里空格是独立的。")
    print()
    print("这就是为什么不能按字符数估：")
    print("  切分单位由词表决定，不由字符数决定。")


if __name__ == "__main__":
    main()
