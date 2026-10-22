"""第 7 章 · 第 2 级：给它一个裁判 —— 外部信号让反思真正生效。

运行：
    python code/ch07_reflection/step2_verifier.py

新增的一个概念：**裁判（verifier）**。

裁判的本质：**一个不由模型判断的、能说"对/不对"和"哪里不对"的东西。**

这一级用"标准答案 + JSON 解析"当裁判，只改上一级的一个地方：
把"你自己检查一下"换成"校验器说：数值不符，期望 [1299, 300]，实际 [12.99, 3.0]"。
"""
from __future__ import annotations

import json
import re

TEXT = "耳机 12.99 元，运费 3 元。"
TRUTH = [1299, 300]


# ---------------------------------------------------------------- 裁判

def verify(output: str) -> tuple[bool, str]:
    """注意：这个函数里没有模型。这就是"外部信号"。"""
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        return False, f"不是合法 JSON：{e}"

    got = data.get("amounts_in_cents")
    if not isinstance(got, list):
        return False, "缺少字段 amounts_in_cents 或它不是数组"

    if sorted(got) != sorted(TRUTH):
        # 关键：说清「期望什么、实际什么」，而不是「请再检查」
        return False, f"数值不符：期望 {TRUTH}，实际 {got}（提示：元转分要 ×100）"
    return True, "通过"


# ---------------------------------------------------------------- 模型

class ModelThatLearnsFromFeedback:
    """模拟一个"能给具体错误就能改对"的模型。

    真实模型也是这样：给它泛泛的"再检查一遍"，它照旧；
    给它具体的"期望 X 实际 Y"，它大概率能改。
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        nums = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*元", TEXT)]
        # 只有在 prompt 里看到具体的「期望 ... 实际 ...」时才会修正
        fixed = "期望 [" in prompt
        vals = [int(round(n * 100)) for n in nums] if fixed else nums
        return json.dumps({"amounts_in_cents": vals})


def main() -> None:
    model = ModelThatLearnsFromFeedback()
    base = f"把下面文字里的金额换算成分，JSON 输出：{TEXT}"
    prompt = base

    print("=" * 74)
    print("第 2 级：把裁判的具体错误喂回去")
    print("=" * 74)

    for round_no in range(1, 4):
        out = model(prompt)
        ok, fb = verify(out)
        print(f"\n第 {round_no} 轮")
        print(f"  输出：{out}")
        print(f"  裁判：{'✅ ' if ok else '❌ '}{fb}")
        if ok:
            break
        prompt = f"{base}\n\n你上次的输出：{out}\n校验未通过：{fb}\n请修正后重新输出。"

    print("\n" + "=" * 74)
    print("差别只有一句话")
    print("=" * 74)
    print('  上一级：「请再检查一遍」          → 模型没有新依据，结论不变')
    print('  这一级：「校验未通过：期望 [1299, 300]，实际 [12.99, 3.0]」→ 一句话就改对了')
    print()
    print("  👉 反思系统的上限，由裁判决定，不由模型决定。")
    print("     所以「怎么设计裁判」比「用哪个模型反思」重要 10 倍。")

    print("\n" + "=" * 74)
    print("你能用的六种裁判（按实现成本排序）")
    print("=" * 74)
    print("  1. JSON Schema / Pydantic   结构化输出           极低成本")
    print("  2. 正则 / 规则校验           格式、必填、数值范围   低")
    print("  3. 单元测试                  生成的代码          中（项目 A 的核心）")
    print("  4. 检索到的权威事实          RAG 事实核对        中")
    print("  5. 另一个模型（LLM judge）   主观质量            低但需要校验它自己")
    print("  6. 人工反馈                  高风险决策          高（第 20 章）")


if __name__ == "__main__":
    main()
