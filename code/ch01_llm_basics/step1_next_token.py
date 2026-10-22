"""第 1 章 step1：一个"只会接着往下写"的玩具模型（离线，1 秒出结果）。

运行：
    python code/ch01_llm_basics/step1_next_token.py

上一级的痛点：无（这是起点）。
这一级做什么：用 20 行统计，做出一个"大模型"——它做的事和 GPT 完全一样，
             只是看得少、记得少、参数少。

要看的三件事：
  1. 它学到的只是"什么字后面常跟什么字"，不是事实
  2. 温度=0 时输出固定；温度升高时同一个开头能出不同句子
  3. 语料里没有的字，它根本不认识（KeyError）
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

TEXT = "退款要几天。退款需要 7 天。退款需要审核。退货也要审核。"


def build(text: str) -> dict[str, Counter]:
    """统计"每个字后面跟过哪些字、各几次"。这就是这个玩具模型的全部参数。"""
    model: dict[str, Counter] = defaultdict(Counter)
    for a, b in zip(text, text[1:]):
        model[a][b] += 1
    return model


def predict(model: dict[str, Counter], prefix: str, temperature: float = 0.0) -> str:
    out = list(prefix)
    while out[-1] != "。":
        counts = model[out[-1]]
        if not counts:
            raise KeyError(f"语料里没有以「{out[-1]}」开头的句子")
        if temperature <= 0:
            out.append(counts.most_common(1)[0][0])
        else:
            chars = list(counts)
            weights = [counts[c] ** (1 / temperature) for c in chars]
            out.append(random.choices(chars, weights=weights)[0])
    return "".join(out)


def main() -> None:
    random.seed(0)
    model = build(TEXT)

    print("=" * 72)
    print("一个'只会接着往下写'的玩具模型")
    print("=" * 72)
    print("语料（训练材料）：")
    print(f"  {TEXT}\n")

    print("学到的'下一个词'概率（只看前一个字）：")
    for ch, counts in model.items():
        total = sum(counts.values())
        items = "  ".join(f"{c}({n / total:.0%})" for c, n in counts.most_common())
        print(f"  「{ch}」→ {items}")

    print("\n" + "=" * 72)
    print("用随机数生成一句话（温度=0，永远选最高概率）")
    print("=" * 72)
    print(f"  {predict(model, '退')}")

    print("\n同一个开头，温度=1.2，连抽 5 次：")
    for _ in range(5):
        print(f"  {predict(model, '退', temperature=1.2)}")

    print("\n" + "=" * 72)
    print("三个必须记住的结论")
    print("=" * 72)
    print("  · 它「知道」的只有一件事：哪个字后面常跟哪个字。")
    print("    「7 天」出现得多，它就说 7 天——不是因为它知道政策，是因为统计如此。")
    print("  · 温度=0 时是确定的；温度升高后，同一个开头会出不同句子。")
    print("    这就是'同一个问题问两次答案不一样'的原理：抽签结果不同。")
    print("  · 语料里没见过的开头，它直接不认识。")

    print("\n" + "=" * 72)
    print("最后：问一个语料里没有的问题，会发生什么")
    print("=" * 72)
    try:
        predict(model, "今天天气")
    except KeyError as exc:
        print(f"  ❌ KeyError: {exc}")
        print("  → 真实模型会把没见过的词切成更细的 token 再处理，")
        print("     但本质一样：它只能处理'见过的东西的组合'。")


if __name__ == "__main__":
    main()
