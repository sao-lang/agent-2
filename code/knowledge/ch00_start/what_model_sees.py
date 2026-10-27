"""同一段意思，三种写法，切出来的 token 数不同。

不联网。这里用的是一个简化的切分器：按"一个汉字一个 token、一个英文单词一个 token、
一个标点一个 token"估算，用来演示"模型看到的不是字，是切好的片段"这件事。

真实 tokenizer 的切法与此不同（子词切分，常见英文单词可能一个 token、罕见词会被
拆成几个），但"同一意思、不同写法、token 数不同"这个结论不变。
"""

from __future__ import annotations

import re


def rough_tokenize(text: str) -> list[str]:
    """极简切分：中文按字，英文按词，标点与空白按符号。"""
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z]+|[0-9]+|\S", text)


SAMPLES = {
    "只回答天数": "7天",
    "完整句子": "商品签收后7天内可以申请退货。",
    "加了客套与限定": "您好，根据我们的退货政策，商品在签收之日起7天内可以申请退货，需保持商品完好。",
}


def main() -> None:
    print(f"{'写法':<16}{'字符数':>8}{'token 数':>10}{'内容':>6}")
    print("-" * 60)
    for label, text in SAMPLES.items():
        tokens = rough_tokenize(text)
        print(f"{label:<16}{len(text):>8}{len(tokens):>10}    {text}")

    print()
    base = len(rough_tokenize(SAMPLES["只回答天数"]))
    full = len(rough_tokenize(SAMPLES["加了客套与限定"]))
    print(f"同样一个事实，“加了客套与限定”的写法是“只回答天数”的 {full / base:.1f} 倍 token。")

    print()
    print("模型看到的不是字，是上面切出来的片段：")
    print(" ", " | ".join(rough_tokenize(SAMPLES["只回答天数"])))


if __name__ == "__main__":
    main()
