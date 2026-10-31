"""一个可以"点"的假桌面：登录 -> 搜索 -> 详情 -> 表单 -> 提交。

不联网，没有浏览器。屏幕用文本框代渲染（每个控件一行坐标），点击按 bbox 命中，
未命中记一次"空点"且不改变状态——这是定位失败能被观察到的前提。
外部状态只有一处：orders 字典里那条订单的收件人。

运行：python code/forms/computer_use/ui_env.py
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

W, H = 1280, 720


@dataclass(frozen=True)
class Element:
    name: str
    kind: str                  # input / button / text
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


LOGIN = [
    Element("账号", "text", 120, 180, 300, 40),
    Element("密码", "input", 120, 240, 300, 40),
    Element("登录", "button", 120, 320, 160, 44),
    Element("已保存账号登录", "button", 300, 320, 200, 44),
]
SEARCH = [
    Element("订单号", "input", 120, 160, 300, 40),
    Element("查询", "button", 440, 160, 120, 44),
    Element("结果区", "text", 120, 240, 900, 320),
]
DETAIL = [
    Element("订单标题", "text", 120, 140, 600, 40),
    Element("收件人", "text", 120, 220, 400, 36),
    Element("编辑", "button", 120, 320, 120, 44),
]
FORM = [
    Element("收件人输入", "input", 120, 220, 300, 40),
    Element("电话输入", "input", 120, 280, 300, 40),
    Element("提交", "button", 120, 360, 120, 44),
]
DONE = [Element("结果", "text", 120, 200, 600, 40)]


@dataclass
class Frame:
    page: str
    elements: list[Element]
    values: dict[str, str] = field(default_factory=dict)
    focus: str = ""
    toast: str = ""

    def text(self) -> str:
        rows = [f"页面: {self.page}  屏幕 {W}x{H}"]
        for e in self.elements:
            rows.append(f"  [{e.kind}] {e.name} bbox=({e.x},{e.y},{e.w},{e.h})")
        for k, v in self.values.items():
            rows.append(f"  值 {k}={v!r}")
        if self.focus:
            rows.append(f"  焦点 {self.focus}")
        if self.toast:
            rows.append(f"  提示 {self.toast}")
        return "\n".join(rows)

    def digest(self) -> str:
        raw = json.dumps({"page": self.page, "values": self.values, "focus": self.focus,
                          "toast": self.toast}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


class App:
    def __init__(self, orders: dict[str, dict]) -> None:
        self.orders = orders
        self.page = "login"
        self.values: dict[str, str] = {}
        self.focus = ""
        self.toast = ""
        self.current = ""
        self.submitted = False
        self.empty_clicks = 0
        self.pages_seen = ["login"]

    def frame(self) -> Frame:
        table = {"login": LOGIN, "search": SEARCH, "detail": DETAIL,
                 "form": FORM, "done": DONE}
        return Frame(self.page, table[self.page], dict(self.values), self.focus, self.toast)

    def click(self, x: int, y: int) -> str:
        for e in reversed(self.frame().elements):
            if e.contains(x, y):
                return self._hit(e)
        self.empty_clicks += 1
        self.toast = f"该坐标没有控件（{x},{y}）"
        return self.toast

    def _hit(self, e: Element) -> str:
        self.toast = ""
        if e.kind == "input":
            self.focus = e.name
            return f"聚焦 {e.name}"
        if e.kind == "text":
            return f"点击了文本区 {e.name}（无动作）"
        if e.name == "已保存账号登录":
            self.page = "search"
            self.pages_seen.append("search")
            return "进入搜索页"
        if e.name == "查询":
            oid = self.values.get("订单号", "")
            if oid in self.orders:
                self.current = oid
                self.page = "detail"
                self.pages_seen.append("detail")
                return f"找到订单 {oid}"
            self.toast = "查无此单"
            return self.toast
        if e.name == "编辑":
            self.page = "form"
            self.pages_seen.append("form")
            self.values["收件人输入"] = self.orders[self.current]["recipient"]
            return "进入表单"
        if e.name == "提交":
            who = self.values.get("收件人输入", "").strip()
            if not who:
                self.toast = "收件人不能为空"
                return self.toast
            self.orders[self.current]["recipient"] = who
            self.submitted = True
            self.page = "done"
            self.pages_seen.append("done")
            return f"已提交 {self.current}"
        return f"点击 {e.name}"

    def type(self, text: str) -> str:
        if not self.focus:
            self.toast = "没有焦点，输入被丢弃"
            return self.toast
        self.values[self.focus] = text          # 填入，不是追加
        return f"{self.focus} <- {text!r}"


def demo() -> None:
    app = App({"O2024": {"recipient": "李四"}})
    print("=== 1. 第一屏（截图会被渲染成这样，或者交给人看） ===")
    print("    " + app.frame().text().replace("\n", "\n    "))

    print()
    print("=== 2. 点偏 40px 会怎样（详情页的'编辑'按钮 120x44） ===")
    app.click(*LOGIN[3].center)
    app.click(*SEARCH[0].center)
    app.type("O2024")
    app.click(*SEARCH[1].center)
    edit_btn = DETAIL[2]
    x, y = edit_btn.center
    print(f"    按钮 bbox=({edit_btn.x},{edit_btn.y},{edit_btn.w},{edit_btn.h}) 中心=({x},{y})")
    print(f"    正确点 ({x},{y}) -> 先不点，看偏的")
    print(f"    纵向偏 40px ({x},{y + 40}) -> {app.click(x, y + 40)}")
    print(f"    空点计数={app.empty_clicks} 页面仍={app.page}")
    print(f"    正确点 ({x},{y}) -> {app.click(x, y)}")

    print()
    print("=== 3. 走通一次（外部状态真的变了） ===")
    app2 = App({"O2024": {"recipient": "李四"}})
    print(f"    {app2.click(*LOGIN[3].center)}")
    print(f"    {app2.click(*SEARCH[0].center)}")
    print(f"    {app2.type('O2024')}")
    print(f"    {app2.click(*SEARCH[1].center)}")
    print(f"    {app2.click(*DETAIL[2].center)}")
    print(f"    {app2.click(*FORM[0].center)}")
    print(f"    {app2.type('张三')}")
    print(f"    {app2.click(*FORM[2].center)}")
    print(f"    页面序列={app2.pages_seen}")
    print(f"    外部状态：订单 O2024 收件人={app2.orders['O2024']['recipient']}")


if __name__ == "__main__":
    demo()
