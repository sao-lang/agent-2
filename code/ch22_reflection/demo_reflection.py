"""第 21 章示例：三种反思策略的对照实验（不需要 API）。

运行：
    python code/ch22_reflection/demo_reflection.py

结论先行：
  · 纯自我反思 —— 第 1 轮失败后，第 2 轮**依然失败**（因为它没有新信息）
  · 带外部信号 —— 第 2 轮修好（因为校验器告诉了它具体错在哪）
  · Reflexion   —— 把教训存下来，下一个任务**第 1 轮就对**

这就是"反思必须有外部信号"的实证。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.reflection import MockModel, ReflectionLoop  # noqa: E402


TEXTS = [
    "订单 A 金额 12.99 元，订单 B 金额 3 元。",
    "商品原价 99 元，优惠 20 元，实付 79 元。",
    "运费 10 元，包装费 1.5 元。",
]


def run_all(mode: str, fail_mode: str) -> dict[str, Any]:
    loop = ReflectionLoop(llm=MockModel(fail_mode), mode=mode)
    results = [loop.run(t) for t in TEXTS]
    return {
        "mode": mode,
        "results": results,
        "rounds": [r["rounds"] for r in results],
        "success": [r["success"] for r in results],
        "lessons": loop.lessons,
    }


def main() -> None:
    print("=" * 70)
    print("场景 1：模型第一次把金额换算错了（12.99 → 12.99 而不是 1299）")
    print("=" * 70)
    rows = []
    for mode in ["none", "self", "external"]:
        r = run_all(mode, "cents")
        rows.append(r)
        print(f"\n[{mode}]")
        for i, res in enumerate(r["results"]):
            a = res["attempts"]
            print(
                f"  文本{i + 1}: {a[-1].ok and '✅' or '❌'} "
                f"轮数={res['rounds']} "
                f"最后一轮输出={a[-1].output[:50]}"
            )

    print(f"\n{'策略':<12}{'总轮数':>8}{'成功数':>8}")
    print("-" * 28)
    for r in rows:
        print(f"{r['mode']:<12}{sum(r['rounds']):>8}{sum(r['success']):>8}/3")

    print("\n" + "=" * 70)
    print("场景 2：Reflexion —— 把教训跨任务复用")
    print("=" * 70)
    loop = ReflectionLoop(llm=MockModel("format"), mode="reflexion")
    for i, t in enumerate(TEXTS):
        r = loop.run(t)
        first_try = r["attempts"][0].ok
        print(f"  任务{i + 1}: 首轮{'✅成功' if first_try else '❌失败'} 轮数={r['rounds']} 教训数={len(loop.lessons)}")
    print("\n  累计教训：")
    for l in loop.lessons:
        print(f"    - {l}")

    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)
    print("  1. 纯自我反思（self）：模型重复同样的错误，因为它没有新信息可用")
    print("  2. 外部信号反思（external）：一次修正就成功，因为校验器给出了具体错误")
    print("  3. Reflexion：教训沉淀后，后续任务首轮就正确——成本降下来了")
    print("\n  👉 所以：**不要问模型'你觉得对吗'，要给它一个能判对错的裁判。**")
    print("     这个裁判可以是单元测试、JSON schema、规则校验、检索到的事实、人工反馈。")
    print("     Agent 工程里，'反思'的实现质量 = '裁判'的实现质量。")


if __name__ == "__main__":
    main()
