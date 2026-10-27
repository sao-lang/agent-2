"""提示词六要素：缺哪一项，输出会在哪里坏。

不联网。用一个规则式的假后端：它只检查提示词里"出现没出现"某类信息，
据此决定输出的质量。用来演示"要素缺失导致的失败形态"，不是模型实测。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Prompt:
    role: str | None = None
    task: str | None = None
    context: str | None = None
    data: str | None = None
    fmt: str | None = None
    constraints: str | None = None

    def present(self) -> set[str]:
        keys = ["role", "task", "context", "data", "fmt", "constraints"]
        return {k for k in keys if getattr(self, k)}


MISSING_EFFECT = {
    "role": "语气与视角不稳定：同一问题在'客服'和'法务'口吻间摆动",
    "task": "输出跑题：回答了相关但没有回答被问的那件事",
    "context": "缺少判断依据：不知道你现在是哪一方，立场可能反了",
    "data": "编造输入：没有真实数据时，用看起来合理的内容填充",
    "fmt": "格式随机：有时表格、有时列表、有时整段文字，下游无法解析",
    "constraints": "越界：超出范围也照答，不拒答也不标注不确定",
}


def simulate(p: Prompt) -> list[str]:
    """按缺失项返回预计的失效形态。"""
    have = p.present()
    return [MISSING_EFFECT[k] for k in ("role", "task", "context", "data", "fmt", "constraints")
            if k not in have]


FULL = Prompt(
    role="你是电商客服，只回答退货相关问题。",
    task="判断这笔订单是否符合退货条件，并给出结论。",
    context="当前政策：签收后 7 天内可退，需商品完好。",
    data="订单 A1001：签收于 3 天前，商品未拆封。",
    fmt="输出 JSON：{eligible: bool, reason: str}，不要其他文字。",
    constraints="只依据给定政策判断；信息不足时 eligible 填 null 并在 reason 里说明。",
)

CASES = {
    "完整六项": FULL,
    "缺 role": Prompt(task=FULL.task, context=FULL.context, data=FULL.data,
                      fmt=FULL.fmt, constraints=FULL.constraints),
    "缺 task": Prompt(role=FULL.role, context=FULL.context, data=FULL.data,
                      fmt=FULL.fmt, constraints=FULL.constraints),
    "缺 context": Prompt(role=FULL.role, task=FULL.task, data=FULL.data,
                         fmt=FULL.fmt, constraints=FULL.constraints),
    "缺 data": Prompt(role=FULL.role, task=FULL.task, context=FULL.context,
                      fmt=FULL.fmt, constraints=FULL.constraints),
    "缺 fmt": Prompt(role=FULL.role, task=FULL.task, context=FULL.context,
                     data=FULL.data, constraints=FULL.constraints),
    "缺 constraints": Prompt(role=FULL.role, task=FULL.task, context=FULL.context,
                             data=FULL.data, fmt=FULL.fmt),
    "只有 task": Prompt(task=FULL.task),
}


def main() -> None:
    for name, p in CASES.items():
        missing = simulate(p)
        print(f"=== {name} ===")
        if not missing:
            print("  六项齐全：输出可复现、可解析、边界明确")
        else:
            for effect in missing:
                print(f"  {effect}")
        print()

    print("说明：")
    print("  六项不是每次都写满才叫好。")
    print("  但每缺一项，就多一种'看不出来'的失效方式。")
    print("  缺 fmt 和缺 constraints 最难发现 —— 输出照样有内容，只是不可用。")


if __name__ == "__main__":
    main()
