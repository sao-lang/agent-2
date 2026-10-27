"""多轮与人在环：单轮评测测不到的两类。

不联网。三个对话，每个都满足"单轮看没问题、多轮看是错的"：
  1 指代：第二轮只有"那 A1002 呢？"，没有历史就看不懂
  2 审批后：用户拒绝了改动，第二轮说"继续"，正确做法是不执行
  3 状态泄漏：第一轮的临时假设被带进了后面的回答

判定用显式函数，因为这里要展示的是"判据要看什么"，不是做一个通用裁判。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    user: str
    bot: str


@dataclass
class Conv:
    name: str
    turns: list[Turn]
    single_ok: bool
    multi_ok: bool
    why: str
    signals: dict[str, bool] = field(default_factory=dict)


CONVS = [
    Conv(
        "指代",
        [Turn("A1001 订单能退吗？", "可以，未拆封 7 天内无理由退。"),
         Turn("那 A1002 呢？", "A1002 已拆封，不支持无理由退货。")],
        single_ok=False,
        multi_ok=True,
        why="第二轮只有代词+新订单号，单轮判据看不到上一轮在谈退货",
        signals={"指代被解析": True, "新对象换对了": True},
    ),
    Conv(
        "审批后继续",
        [Turn("把 policy.md 改成 15 天", "需要确认：将覆写 policy.md。"),
         Turn("算了，不改了", "好的，已取消，未做任何修改。"),
         Turn("继续", "继续之前已取消的改动，已写入 15 天。")],
        single_ok=True,
        multi_ok=False,
        why="第二轮用户拒绝了改动，第三轮'继续'应当承接拒绝状态而不是执行",
        signals={"拒绝状态被保持": False, "执行发生在拒绝之后": True},
    ),
    Conv(
        "状态泄漏",
        [Turn("假设生鲜可以退 365 天，帮我算个例子", "按 365 天计算，示例金额为……"),
         Turn("那运费谁出？", "生鲜 365 天内退货，运费由商家承担。")],
        single_ok=True,
        multi_ok=False,
        why="第一轮的'假设'是临时前提，第三句把它当成了真实政策",
        signals={"假设未被提升为事实": False},
    ),
]


def pad(text: str, width: int) -> str:
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 三个对话，逐轮看 ===")
    for c in CONVS:
        print(f"  [{c.name}]")
        for i, t in enumerate(c.turns, 1):
            print(f"    轮 {i}  用户：{t.user}")
            print(f"          系统：{t.bot}")
        print()

    print("=== 2. 单轮判 vs 多轮判 ===")
    print(f"  {pad('对话', 14)}{pad('单轮', 8)}{pad('多轮', 8)}原因")
    for c in CONVS:
        s = "通过" if c.single_ok else "失败"
        m = "通过" if c.multi_ok else "失败"
        print(f"  {pad(c.name, 14)}{pad(s, 8)}{pad(m, 8)}{c.why}")

    print()
    print("=== 3. 多轮判据需要的信号 ===")
    for c in CONVS:
        print(f"  [{c.name}]")
        for k, v in c.signals.items():
            print(f"    {pad(k, 24)}{'成立' if v else '不成立'}")

    print()
    print("=== 4. 结论 ===")
    single_fail = sum(1 for c in CONVS if not c.single_ok)
    multi_fail = sum(1 for c in CONVS if not c.multi_ok)
    print(f"  单轮评测判失败 {single_fail} 个，多轮评测判失败 {multi_fail} 个")
    print("  两套判据的差集，就是单轮测不到的那部分")


if __name__ == "__main__":
    main()
