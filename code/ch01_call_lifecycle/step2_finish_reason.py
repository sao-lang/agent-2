"""第 1 章 step2：finish_reason 决定后续逻辑（离线可运行）。

运行：
    python code/ch01_call_lifecycle/step2_finish_reason.py

本文件展示同一次调用在不同 finish_reason 下应当如何处理。
错误示范是不判断 finish_reason 就直接使用 content。
"""

from __future__ import annotations

import sys


def handle(content: str, finish_reason: str) -> tuple[str, str]:
    """返回 (处理结果, 说明)。"""
    if finish_reason == "stop":
        return "使用 content", "正常结束"
    if finish_reason == "length":
        return "继续生成或调大 max_tokens", "内容被截断，当前 content 不完整"
    if finish_reason == "tool_calls":
        return "执行工具后再次调用", "本轮不产出正文"
    if finish_reason == "content_filter":
        return "改换表述或转人工", "内容被拦截"
    return "记录并上报", f"未知取值：{finish_reason}"


CASES = [
    ("签收后 7 天内可以申请无理由退货。", "stop",
     "这是最常见的情况，可以直接使用"),
    ("签收后 7 天内可以申请无理由退", "length",
     "max_tokens 设小了，句子被切断"),
    ("", "tool_calls",
     "模型想先查订单，正文为空但请求体中带 tool_calls"),
    ("", "content_filter",
     "输出被策略拦截"),
    ("...", "some_new_reason",
     "厂商新增取值，旧代码没有分支"),
]


def main() -> None:
    print("=" * 96)
    print("① 不判断 finish_reason，直接用 content")
    print("=" * 96)
    for content, reason, note in CASES:
        if not content:
            outcome = "返回空字符串给用户"
        elif reason == "some_new_reason":
            outcome = "返回不完整内容，无法察觉"
        else:
            outcome = f"返回：{content}"
        print(f"  finish_reason={reason:<18}{outcome}")
        print(f"  {'':<16}{note}")

    print()
    print("=" * 96)
    print("② 判断 finish_reason 后分流处理")
    print("=" * 96)
    print(f"  {'finish_reason':<18}{'处理方式':<28}{'原因'}")
    print("  " + "-" * 88)
    for _, reason, _ in CASES:
        action, why = handle("", reason)
        print(f"  {reason:<18}{action:<28}{why}")

    print()
    print("=" * 96)
    print("③ 第一版与第二版的差异")
    print("=" * 96)
    rows = [
        ("正常输出", "可用", "可用", "无差异"),
        ("输出被截断", "静默返回半句", "触发续写", "关键差异"),
        ("需要调工具", "返回空字符串", "进入工具流程", "关键差异"),
        ("内容被拦截", "返回空字符串", "转人工或改写", "关键差异"),
        ("厂商新增取值", "按正常处理", "记录并上报", "防御性差异"),
    ]
    print(f"  {'情况':<16}{'不判断':<18}{'判断后':<18}{'结论'}")
    print("  " + "-" * 88)
    for a, b, c, d in rows:
        print(f"  {a:<16}{b:<18}{c:<18}{d}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
