"""忽略 finish_reason 会怎样：拿四种响应喂同一个"只看内容"的函数。

不联网。四种响应来自 finish_reason.py 的生成结果，这里固定写死，便于对照。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Response:
    case: str
    content: str | None
    finish_reason: str


RESPONSES = [
    Response("正常", "签收后7天内可退。", "stop"),
    Response("截断", "签收后7天内可退，条件是商品", "length"),
    Response("要调工具", None, "tool_calls"),
    Response("被过滤", "", "content_filter"),
]


def naive_take_content(response: Response) -> str:
    """只取 content 的写法。大多数第一版代码都是这样。"""
    return response.content or ""


def guarded_take_content(response: Response) -> tuple[str | None, str]:
    """先判断 finish_reason，再决定能不能用 content。"""
    if response.finish_reason == "stop":
        return response.content, "可用"
    if response.finish_reason == "length":
        return None, "不可用：被截断"
    if response.finish_reason == "tool_calls":
        return None, "不可用：不是答案，是待执行的动作"
    if response.finish_reason == "content_filter":
        return None, "不可用：生成被拦截"
    return None, f"不可用：未知取值 {response.finish_reason}"


def main() -> None:
    print("只用 content 的写法：")
    for r in RESPONSES:
        text = naive_take_content(r)
        printable = text if text else "（空字符串）"
        print(f"  {r.case:<6} -> {printable!r}")

    print()
    print("先判断 finish_reason 的写法：")
    for r in RESPONSES:
        text, verdict = guarded_take_content(r)
        shown = repr(text) if text is not None else "None"
        print(f"  {r.case:<6} -> {shown:<30} {verdict}")

    print()
    print("差别在哪里：")
    print("  '截断' 那条，两种写法都返回了非空字符串，但前者把半句话当成完整答案用了。")
    print("  '被过滤' 那条，前者返回空字符串，调用方会当成'模型没话说'，")
    print("  而不是'生成被拦截，重试无效'。这两种情况的处理方式正好相反。")


if __name__ == "__main__":
    main()
