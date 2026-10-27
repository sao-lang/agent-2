"""max_tokens 与上下文窗口是两个不同的限制，触发哪一个取决于输入长度。

不联网。用固定数值演示两种上限的关系，以及它们各自触发的
finish_reason 或错误类型。数值是演示用的常量，不是某个模型的真实规格。
"""

from __future__ import annotations

from dataclasses import dataclass

# 演示用的常量
CONTEXT_WINDOW = 8192      # 上下文窗口：输入 + 输出 的总上限
DEFAULT_MAX_TOKENS = 256   # 很多接口在不指定时的默认值


@dataclass
class Case:
    prompt_tokens: int
    max_tokens: int

    @property
    def total_if_full(self) -> int:
        return self.prompt_tokens + self.max_tokens


def forecast(case: Case) -> tuple[str, str]:
    """返回 (结果, 说明)。"""
    if case.total_if_full > CONTEXT_WINDOW:
        return "请求被拒", (
            f"输入 {case.prompt_tokens} + 上限 {case.max_tokens} = "
            f"{case.total_if_full} > 窗口 {CONTEXT_WINDOW}"
        )
    if case.max_tokens < 32:
        return "length 风险高", "上限太小，长答案会被截断"
    return "正常", "输入与上限之和在窗口内"


def main() -> None:
    print(f"上下文窗口 = {CONTEXT_WINDOW}，输出上限是预留值，不是实际产出。")
    print()
    print(f"{'输入 token':>12}{'上限':>8}{'两者之和':>12}  {'结果':<12}{'说明'}")
    print("-" * 96)

    for prompt_tokens, max_tokens in (
        (100, DEFAULT_MAX_TOKENS),
        (4000, DEFAULT_MAX_TOKENS),
        (8000, DEFAULT_MAX_TOKENS),
        (4000, 2048),
        (4000, 12000),
        (200, 16),
    ):
        case = Case(prompt_tokens, max_tokens)
        verdict, why = forecast(case)
        print(f"{prompt_tokens:>12}{max_tokens:>8}{case.total_if_full:>12}  {verdict:<12}{why}")

    print()
    print("两件事要分开：")
    print("  1. max_tokens 是本次生成的允许上限，实际产出通常更少。")
    print("  2. 但它会连同输入一起占用窗口。设得太大，长输入会被直接拒绝。")
    print()
    print("第三种情况（输入 8000）：")
    c = Case(8000, DEFAULT_MAX_TOKENS)
    over = c.total_if_full - CONTEXT_WINDOW
    print(f"  输入 8000 已占掉窗口的 {8000 / CONTEXT_WINDOW:.1%}，")
    print(f"  只剩 {CONTEXT_WINDOW - 8000} 个 token 可给输出，")
    print(f"  默认上限 256 会超出 {over}，请求在生成开始前就被拒。")
    print()
    print("这不是 length：length 是生成中途被掐断，这里根本没有开始生成。")


if __name__ == "__main__":
    main()
