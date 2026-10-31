"""定位失败 vs 规划失败：两种长得都像"没做对"，修法完全不同。

不联网。
  A 定位失败：按钮就在那儿，点击纵向偏 40px，没命中，页面不变，它重复同一次点击。
  B 规划失败：它以为已经在表单页，继续按表单的坐标操作，一路推进到 Done。
              每一步都"执行成功"，但页面身份是错的。

分类器读轨迹里的两个信号：命中与否、当前页与计划页是否一致。

运行：python code/forms/computer_use/failure_split.py
"""

from __future__ import annotations

from dataclasses import dataclass

from action_schema import to_css
from ui_env import DETAIL, FORM, LOGIN, SEARCH, App


@dataclass
class Rec:
    n: int
    expected: str
    page: str
    action: str
    result: str
    hit: bool
    page_after: str


def goto_detail(app: App) -> None:
    app.click(*LOGIN[3].center)
    app.click(*SEARCH[0].center)
    app.type("O2024")
    app.click(*SEARCH[1].center)


def run_miss() -> tuple[App, list[Rec]]:
    app = App({"O2024": {"recipient": "李四"}})
    goto_detail(app)
    x, y = DETAIL[2].center
    recs: list[Rec] = []
    for i in range(1, 3):
        before = app.page
        result = app.click(x, y + 40)
        recs.append(Rec(i, "detail", before, f"click({x},{y + 40})", result,
                        app.page != before or "聚焦" in result, app.page))
    app.click(x, y)                                     # 第三次点对了，但策略没有第三次
    return app, recs


def run_wrong_plan() -> tuple[App, list[Rec]]:
    app = App({"O2024": {"recipient": "李四"}})
    goto_detail(app)
    plan = [
        ("form", {"kind": "click", "at": FORM[0].center}),
        ("form", {"kind": "type", "text": "张三"}),
        ("form", {"kind": "click", "at": FORM[2].center}),
    ]
    recs: list[Rec] = []
    for i, (expected, a) in enumerate(plan, 1):
        before = app.page
        if a["kind"] == "click":
            result = app.click(*a["at"])
            label = f"click{a['at']}"
            hit = app.page != before or "聚焦" in result
        else:
            result = app.type(a["text"])
            label = "type"
            hit = app.focus != ""
        recs.append(Rec(i, expected, before, label, result, hit, app.page))
    return app, recs


def classify(app: App, recs: list[Rec]) -> tuple[str, list[str]]:
    evidence = []
    same_action = len({r.action for r in recs}) == 1 and len(recs) >= 2
    unchanged = all(r.page == r.page_after for r in recs)
    if same_action and unchanged and app.empty_clicks >= 2:
        evidence.append(f"同一动作重复 {len(recs)} 次，页面始终为 {recs[0].page}")
        evidence.append(f"空点计数={app.empty_clicks}（坐标未命中任何控件）")
        return "定位失败", evidence
    off_plan = [r for r in recs if r.page != r.expected]
    if off_plan:
        evidence.append(f"{len(off_plan)} 步的当前页与计划页不一致："
                        f"计划 {off_plan[0].expected}，实际 {off_plan[0].page}")
        evidence.append("每一个动作都合法执行了（点击落在文本区、输入进了有焦点的框），"
                        "但动作的前提是错的")
        if app.orders["O2024"]["recipient"] != "张三" or not app.submitted:
            evidence.append("外部状态未变：收件人仍是 " + app.orders["O2024"]["recipient"])
        return "规划失败", evidence
    return "未分类", ["信号不足以判断"]


def show(title: str, app: App, recs: list[Rec]) -> None:
    print(f"=== {title} ===")
    print(f"    {'步':<3}{'计划页':<8}{'当前页':<8}{'动作':<22}{'结果':<24}{'命中'}")
    for r in recs:
        print(f"    {r.n:<3}{r.expected:<8}{r.page:<8}{r.action:<22}{r.result:<24}"
              f"{'是' if r.hit else '否'}")
    kind, evidence = classify(app, recs)
    print(f"    分类：{kind}")
    for e in evidence:
        print(f"      - {e}")
    print(f"    外部状态：收件人={app.orders['O2024']['recipient']} 已提交={app.submitted}")
    print()


def main() -> None:
    app_a, recs_a = run_miss()
    show("A 定位失败（点偏 40px）", app_a, recs_a)
    app_b, recs_b = run_wrong_plan()
    show("B 规划失败（停错页仍继续）", app_b, recs_b)

    print("=== C 两种失败的修法不同 ===")
    print("    定位失败 -> 换定位方式：给控件稳定 ID / 用文本锚点 / 点击后校验焦点或变化")
    print("    规划失败 -> 每步先校验页面身份：当前页不是计划页就重新规划，而不是继续执行")
    print("    把两者混成一个'失败率'，会让修复方向随机：定位问题去改提示词，改不好")

    print()
    print("=== D 两者的共同点：都要外部判定 ===")
    print("    A 的模型可能自报'已点击编辑'，B 的模型可能自报'已提交'")
    print("    只有空点计数、页面序列与外部状态能区分它们")


if __name__ == "__main__":
    main()
