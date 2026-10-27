"""逐片生成 + 遇到停止条件就收尾：四个取值是在哪里产生的。

同一段完整回答被切成片段，每片相当于一个或几个 token。生成过程从第一片
走到最后一片，中途遇到三种停止条件之一就收尾。`tool_calls` 是另一条路径：
它不生成正文，直接返回一个动作。

不联网。这里是过程模拟，不是模型实测；它演示的是收尾位置，不是模型行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 一段完整的回答，被切成若干片段
FULL_ANSWER = ["签收后", "7", "天内", "可退", "，", "条件", "是", "商品", "未", "拆封", "。"]

# 内容过滤的触发词
FILTER_WORDS = {"拆封"}


@dataclass
class Reply:
    content: str
    finish_reason: str
    produced: int = 0
    limit: int | None = None
    tool_calls: list[str] = field(default_factory=list)


def generate(max_tokens: int, want_tool: bool = False, filter_on: bool = False) -> Reply:
    """从片段序列逐片生成，遇到停止条件就收尾。

    filter_on 控制服务端是否启用内容过滤，用来分别演示四种收尾。
    """
    if want_tool:
        # 模型判断需要外部数据，于是不生成正文
        return Reply(content="", finish_reason="tool_calls", tool_calls=["get_order"])

    out: list[str] = []
    for i, piece in enumerate(FULL_ANSWER):
        # 条件一：达到输出上限，立刻截断
        if i >= max_tokens:
            return Reply("".join(out), "length", produced=i, limit=max_tokens)

        # 条件二：服务端在生成过程中做内容过滤
        if filter_on and piece in FILTER_WORDS:
            return Reply("".join(out), "content_filter", produced=i, limit=max_tokens)

        out.append(piece)

    # 条件三：模型生成完并输出结束标记（本例里就是片段走完）
    return Reply("".join(out), "stop", produced=len(out), limit=max_tokens)


def main() -> None:
    print("同一段回答，只改输出上限：")
    for limit in (64, 5, 6):
        r = generate(limit)
        print(f"  上限 {limit:<3} content={r.content!r}  ({r.finish_reason}, produced={r.produced})")
    print()

    print("另外两条路径：")
    tool = generate(64, want_tool=True)
    print(f"  要调工具  content={tool.content!r}  ({tool.finish_reason}, tool_calls={tool.tool_calls})")
    filtered = generate(64, filter_on=True)
    print(f"  被过滤    content={filtered.content!r}  ({filtered.finish_reason}, produced={filtered.produced})")
    print()

    print("收尾发生的位置：")
    print(f"  {'上限':<8}{'收尾原因':<16}{'已生成片段':<12}{'内容'}")
    for r in (generate(64), generate(5), generate(6), generate(64, want_tool=True),
              generate(64, filter_on=True)):
        print(f"  {str(r.limit):<8}{r.finish_reason:<16}{r.produced:<12}{r.content!r}")
    print()
    print("上限 5 与上限 6 都是 length，但截断的位置不同：一个停在逗号后，一个停在词中间。")
    print("服务端不判断内容是否完整，它只数到上限就停。")


if __name__ == "__main__":
    main()
