"""终止条件的几种写法对照：缺一种会怎样。

不联网。它不调用模型，而是把"终止判断"单独抽出来，用固定的循环记录检验：
哪几种写法在某些形态下不会停。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Step:
    finish_reason: str
    signature: str        # 本步所有调用的名字+参数拼起来
    tokens: int           # 本步请求的 prompt token


def run(policy, steps: list[Step], max_steps: int = 6,
        max_tokens: int = 1000) -> tuple[str, int]:
    """按给定策略跑 steps，返回 (终止状态, 走了几步)。"""
    seen: set[str] = set()
    for i, s in enumerate(steps, 1):
        if s.finish_reason == "stop" and policy.get("stop"):
            return "done", i
        if i >= max_steps and policy.get("max_steps"):
            return "max_steps", i
        if s.tokens >= max_tokens and policy.get("max_tokens"):
            return "max_tokens", i
        if s.signature in seen and policy.get("dedup"):
            return "stalled", i
        seen.add(s.signature)
    return "ran_out_of_script", len(steps)


def main() -> None:
    # 三种形态：正常、参数递变（每步都不同）、原地重复
    normal = [
        Step("tool_calls", "get_order:A1001", 120),
        Step("stop", "", 180),
    ]
    sliding = [
        Step("tool_calls", f"get_order:A{1000 + i}", 120 + i * 200) for i in range(1, 9)
    ]
    repeated = [Step("tool_calls", "get_order:A1001", 120 + i * 20) for i in range(1, 9)]

    policies = {
        "只看 stop": {"stop": True},
        "stop + 步数": {"stop": True, "max_steps": True},
        "stop + 步数 + token": {"stop": True, "max_steps": True, "max_tokens": True},
        "四态齐全": {"stop": True, "max_steps": True, "max_tokens": True, "dedup": True},
    }
    shapes = {"正常": normal, "步数递增": sliding, "原地重复": repeated}

    def pad(s: str, width: int) -> str:
        """按显示宽度对齐（汉字算两格）。"""
        w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)
        return s + " " * max(0, width - w)

    print(pad("策略", 24) + pad("正常", 22) + pad("步数递增", 22) + "原地重复")
    for pname, policy in policies.items():
        cells = []
        for sname in shapes:
            status, n = run(policy, shapes[sname])
            cells.append(f"{status}({n})")
        print(pad(pname, 24) + pad(cells[0], 22) + pad(cells[1], 22) + cells[2])

    print()
    print("最后一行的 6 与 8 是上限截断：步数递增的形态里，脚本给了 8 步，")
    print("但 max_steps=6，所以在第 6 步停。")


if __name__ == "__main__":
    main()
