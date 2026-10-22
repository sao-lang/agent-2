"""第 20 章 · 第 1 级：最直觉的反思 —— 让模型自己检查自己。

运行：
    python code/ch20_reflection/step1_self_reflect.py

这一级只演示一个反直觉的事实：
  **模型"再想一遍"几乎不会改对，因为它没有获得任何新信息。**

这里不用真实模型也能复现，因为原因不是"模型笨"，是"信息量没变"。
"""
from __future__ import annotations

import json
import re

TEXT = "耳机 12.99 元，运费 3 元。"
TRUTH = [1299, 300]


class ModelWithoutNewInfo:
    """模拟"看完自己上次输出后再想一遍"的模型。

    它每次拿到的信息完全一样（同一段文本 + 自己上次的输出），
    所以它每次都会做出同样的判断 —— 这不是它不肯改，是**没有新依据**。
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*元", TEXT)
        # 它把"12.99 元"直接填进了 amounts_in_cents，忘了 ×100
        return json.dumps({"amounts_in_cents": [float(n) for n in nums]})


def self_check(output: str) -> str:
    """让它自己检查。它的检查逻辑也是"没有新信息"的 —— 只能说"看起来对"。"""
    data = json.loads(output)
    return (
        f"我检查了一下：输入里有 {len(data['amounts_in_cents'])} 个金额，"
        f"输出里也有 {len(data['amounts_in_cents'])} 个，数量对得上。"
        "格式是合法 JSON。看起来没问题。"
    )


def main() -> None:
    model = ModelWithoutNewInfo()

    print("=" * 72)
    print("任务：把文本里的金额换算成「分」，输出 JSON")
    print(f"文本：{TEXT}")
    print(f"标准答案：{TRUTH}")
    print("=" * 72)

    prompt = TASK = f"把下面文字里的金额换算成分，JSON 输出：{TEXT}"
    for round_no in range(1, 4):
        out = model(prompt)
        ok = json.loads(out)["amounts_in_cents"] == TRUTH
        print(f"\n第 {round_no} 轮")
        print(f"  输出：{out}")
        print(f"  对不对：{'✅' if ok else '❌'}")
        if ok:
            break

        feedback = self_check(out)
        print(f"  自我检查：{feedback}")
        prompt = f"{TASK}\n\n你上次的输出：{out}\n自我检查：{feedback}\n请再检查一遍，如有问题请修正。"

    print("\n" + "=" * 72)
    print("为什么它改不对")
    print("=" * 72)
    print(f"  模型调用了 {model.calls} 次，但每次输入里的**事实完全一样**：")
    print("    · 原文本一样")
    print("    · 上次输出一样")
    print("    · 自我检查的内容也一样（因为它也只能看到上次输出）")
    print()
    print("  信息论上：**没有新信息，就不会有新结论。**")
    print("  它甚至会给错误找理由，比如「12.99 可能就是分」——")
    print("  因为它的任务是「检查」，而检查的结果只能是「对/不对」，它倾向选「对」。")
    print()
    print("  👉 下一级：给它一个**不依赖它判断**的裁判。")


if __name__ == "__main__":
    main()
