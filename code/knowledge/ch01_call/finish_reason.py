"""同一个问题，两种收尾；以及按 finish_reason 分支的四条路径。

不联网。这段代码模拟"逐 token 生成 + 遇到停止条件就收尾"的过程，
用来演示 finish_reason 是生成过程怎么结束的记录，不是对结果质量的评价。

停止条件有三个来源，优先级不同：
  1. 模型输出了停止标记  -> stop
  2. 达到 max_tokens      -> length
  3. 服务端内容过滤       -> content_filter
另有第四种：模型要调用工具，生成就此中止 -> tool_calls
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 一段完整的回答，被切成若干片段（每片相当于一个 token 或几个 token）
FULL_ANSWER = [
    "签收后", "7", "天内", "可退", "，",
    "条件", "是", "商品", "未", "拆封", "。",
]

# 内容过滤的触发词
FILTER_WORDS = {"拆封"}


@dataclass
class Reply:
    content: str
    finish_reason: str
    produced: int = 0
    limit: int | None = None
    tool_calls: list[str] = field(default_factory=list)


def generate(max_tokens: int, want_tool: bool = False,
             filter_on: bool = False) -> Reply:
    """从片段序列逐片生成，遇到停止条件就收尾。

    filter_on 控制服务端是否启用内容过滤，用来分别演示四种收尾。
    """
    if want_tool:
        # 模型判断需要外部数据，于是不继续生成正文
        return Reply(content="", finish_reason="tool_calls", tool_calls=["get_order"])

    out: list[str] = []
    for i, piece in enumerate(FULL_ANSWER):
        # 条件 1：达到输出上限，立刻截断，最后一个片段之后不再生成
        if i >= max_tokens:
            return Reply("".join(out), "length", produced=i, limit=max_tokens)

        # 条件 3：服务端在生成过程中做内容过滤
        if filter_on and piece in FILTER_WORDS:
            return Reply("".join(out), "content_filter", produced=i, limit=max_tokens)

        out.append(piece)

    # 条件 2：模型生成了结束标记（本例里就是片段序列走完）
    return Reply("".join(out), "stop", produced=len(out), limit=max_tokens)


def dispatch(reply: Reply) -> tuple[str, str]:
    """调用方按 finish_reason 决定下一步。四种取值对应四种完全不同的处理。"""
    reason = reply.finish_reason

    if reason == "stop":
        return "接受", "文本已完整，直接使用"

    if reason == "length":
        # 不能直接使用：结尾被切断，可能是半句话
        return "续写或重来", "文本被截断，需要请求续写或放宽上限"

    if reason == "tool_calls":
        # 没有正文可读，等的是动作
        return "执行工具", f"需要执行 {reply.tool_calls}，再回灌结果"

    if reason == "content_filter":
        # 不是失败，是拒绝生成；重试通常也没用
        return "中止", "被内容过滤拦截，重试无效"

    return "未知", f"未处理的取值：{reason}"


def main() -> None:
    print("完整生成（上限 64）：")
    r = generate(64)
    print(f"  content={r.content!r}")
    print(f"  finish_reason={r.finish_reason}  produced={r.produced}")
    print(f"  -> {dispatch(r)}")

    print()
    print("同一问题，上限改为 5：")
    r = generate(5)
    print(f"  content={r.content!r}")
    print(f"  finish_reason={r.finish_reason}  produced={r.produced}/{r.limit}")
    print(f"  -> {dispatch(r)}")

    print()
    print("上限 5 与上限 6 的差别：")
    for limit in (5, 6):
        r = generate(limit)
        print(f"  上限 {limit}: {r.content!r}  ({r.finish_reason})")

    print()
    print("各 finish_reason 的处理分支：")
    for r in (
        generate(64),
        generate(5),
        generate(64, want_tool=True),
        generate(64, filter_on=True),
    ):
        action, why = dispatch(r)
        print(f"  {r.finish_reason:<15} -> {action:<8} {why}")

    print()
    print("未处理的取值：")
    action, why = dispatch(Reply("...", "unknown_value"))
    print(f"  unknown_value   -> {action:<8} {why}")


if __name__ == "__main__":
    main()
