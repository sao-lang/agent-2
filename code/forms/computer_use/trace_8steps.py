"""八步操作轨迹：登录 -> 搜索 -> 填表 -> 提交，成功由外部状态判定。

不联网。每一步记：页面、动作、结果、帧哈希、是否命中控件。
最后不采信模型自报的 Done，而是读 orders 里的收件人。

运行：python code/forms/computer_use/trace_8steps.py
"""

from __future__ import annotations

from dataclasses import dataclass

from action_schema import image_tokens, to_css
from ui_env import LOGIN, SEARCH, DETAIL, FORM, App, Element

TASK = "把订单 O2024 的收件人改成张三并提交"


@dataclass
class Step:
    n: int
    action: str
    page_before: str
    result: str
    page_after: str
    frame_hash: str
    hit: bool
    tokens: int


def act(app: App, action: dict) -> tuple[str, bool]:
    if action["kind"] == "click":
        x, y = to_css(action["x"], action["y"])
        before = app.page
        result = app.click(x, y)
        return result, app.page != before or "聚焦" in result
    if action["kind"] == "type":
        return app.type(action["text"]), app.focus != ""
    raise ValueError(action["kind"])


def run() -> tuple[App, list[Step]]:
    app = App({"O2024": {"recipient": "李四"}})
    actions = [
        {"kind": "click", "x": 0.3125, "y": 0.475},   # 已保存账号登录
        {"kind": "click", "x": 0.2109, "y": 0.25},    # 订单号输入框
        {"kind": "type", "text": "O2024"},
        {"kind": "click", "x": 0.3906, "y": 0.253},   # 查询
        {"kind": "click", "x": 0.1406, "y": 0.475},   # 编辑
        {"kind": "click", "x": 0.2109, "y": 0.333},   # 收件人输入
        {"kind": "type", "text": "张三"},
        {"kind": "click", "x": 0.1406, "y": 0.531},   # 提交
    ]
    steps: list[Step] = []
    tokens = 0
    for i, a in enumerate(actions, 1):
        tokens += image_tokens(1280, 720) + len(app.frame().text())
        before = app.page
        result, hit = act(app, a)
        label = a["kind"] if a["kind"] == "type" else \
            f"click({to_css(a['x'], a['y'])[0]},{to_css(a['x'], a['y'])[1]})"
        steps.append(Step(i, label, before, result, app.page, app.frame().digest(), hit, tokens))
    return app, steps


def main() -> None:
    app, steps = run()

    print(f"任务：{TASK}")
    print("=== 1. 八步轨迹 ===")
    print(f"    {'步':<3}{'页面':<8}{'动作':<18}{'结果':<22}{'帧哈希':<12}{'命中'}")
    for s in steps:
        print(f"    {s.n:<3}{s.page_before:<8}{s.action:<18}{s.result:<22}{s.frame_hash:<12}"
              f"{'是' if s.hit else '否'}")

    print()
    print("=== 2. 外部状态（不读模型的 Done，读这里） ===")
    print(f"    页面序列={app.pages_seen}")
    print(f"    orders={app.orders}")
    print(f"    空点次数={app.empty_clicks}")

    ok = app.orders["O2024"]["recipient"] == "张三" and app.submitted
    print()
    print("=== 3. 判定 ===")
    print(f"    模型自报：done(answer='O2024 已改为张三')")
    print(f"    外部核对：收件人={app.orders['O2024']['recipient']} 已提交={app.submitted} -> "
          f"{'通过' if ok else '不通过'}")
    print("    <- 只有外部核对能判断成功；模型自报与外部状态不一致时，以外部为准")

    print()
    print("=== 4. 成本 ===")
    print(f"    八步共约 {steps[-1].tokens} tokens（每步一帧 {image_tokens(1280, 720)} + 文本观测）")
    print("    这里的帧是坐标文本的价格；换成真截图，一帧就要按图像计费")


if __name__ == "__main__":
    main()
