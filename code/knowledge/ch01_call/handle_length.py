"""length 的三种处理，逐一实现并对比。

不联网。用本地函数模拟"按 max_tokens 生成"，输出与真实调用结构一致。
三个方案的差别在调用次数和补充的字数上，这两项直接对应成本。
"""

from __future__ import annotations

from dataclasses import dataclass

# 完整回答，切成片段
FULL = ["签收后", "7", "天内", "可退", "，", "条件", "是", "商品", "未", "拆封", "。"]
END_MARKS = ("。", "！", "？")


@dataclass
class Result:
    content: str
    finish_reason: str
    calls: int = 1
    added: int = 0


def generate(prefix_len: int = 0, max_tokens: int = 6) -> Result:
    """从 prefix_len 处开始生成，最多 max_tokens 片。"""
    rest = FULL[prefix_len:]
    if len(rest) <= max_tokens:
        return Result("".join(rest), "stop")
    return Result("".join(rest[:max_tokens]), "length")


# ---------------------------------------------------------------- 方案一

def cut_at_sentence(text: str) -> Result:
    """本地找一个句号，丢掉之后的部分。不产生新调用。"""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in END_MARKS:
            return Result(text[: i + 1], "stop", calls=1, added=0)
    return Result("", "length", calls=1, added=0)


# ---------------------------------------------------------------- 方案二

def retry_with_more(max_tokens: int) -> Result:
    """放宽上限，从头重来。前面生成的作废。"""
    r1 = generate(0, 6)
    if r1.finish_reason == "stop":
        return Result(r1.content, "stop", calls=1)

    r2 = generate(0, max_tokens)
    return Result(r2.content, r2.finish_reason, calls=2, added=len(r2.content) - len(r1.content))


# ---------------------------------------------------------------- 方案三

def continue_from(prefix: str, max_tokens: int = 6) -> Result:
    """把已生成的部分作为前缀，请求接着写。"""
    r1 = generate(0, 6)
    if r1.finish_reason == "stop":
        return Result(r1.content, "stop", calls=1)

    consumed = len(r1.content)
    # 从已生成内容的末尾继续
    consumed_pieces = 0
    acc = ""
    for piece in FULL:
        acc += piece
        consumed_pieces += 1
        if len(acc) >= consumed:
            break

    r2 = generate(consumed_pieces, max_tokens)
    return Result(r1.content + r2.content, r2.finish_reason, calls=2, added=len(r2.content))


def main() -> None:
    first = generate(0, 6)
    print(f"原始：{first.content!r} ({first.finish_reason}, 上限=6)")
    print()

    a = cut_at_sentence(first.content)
    print(f"方案一 直接截到最后一个完整句：")
    print(f"  {a.content!r}  丢弃 {len(first.content) - len(a.content)} 个字")
    print()

    b = retry_with_more(64)
    print(f"方案二 放宽上限重来：")
    print(f"  {b.content!r}  ({b.finish_reason})  花费 {b.calls} 次调用")
    print(f"  新增内容 {b.added} 字，但重算了前面 {len(first.content)} 字的生成")
    print()

    c = continue_from(first.content)
    print(f"方案三 续写：")
    print(f"  {c.content!r}  ({c.finish_reason})  花费 {c.calls} 次调用")
    print(f"  只补了 {c.added} 字")
    print()

    print("对照：")
    print(f"  {'方案':<12}{'调用次数':<10}{'产出字符':<10}{'备注'}")
    for name, r, note in (
        ("一 截断", a, "丢失后半句"),
        ("二 重来", b, "整段重算"),
        ("三 续写", c, "需处理接缝"),
    ):
        print(f"  {name:<12}{r.calls:<10}{len(r.content):<10}{note}")


if __name__ == "__main__":
    main()
