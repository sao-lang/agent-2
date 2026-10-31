"""动作 schema：一个判别联合，坐标用 0–1 相对值，Done 必须带答案。

不联网。校验是严格的：多一个字段就拒绝，少一个字段也拒绝。
坐标换算这一段演示了 devicePixelRatio 的坑：截图上的像素坐标要先除以 dpr 才能点。

运行：python code/forms/computer_use/action_schema.py
"""

from __future__ import annotations

import math

FIELDS = {
    "click": {"x": float, "y": float},
    "type": {"text": str},
    "scroll": {"dy": int},
    "wait": {"ms": int},
    "done": {"answer": str},
}
CSS_W, CSS_H = 1280, 720


def validate(action: dict) -> tuple[bool, str]:
    kind = action.get("kind")
    if kind not in FIELDS:
        return False, f"未知动作类型 {kind!r}，合法值 {sorted(FIELDS)}"
    allowed = {"kind", "reason"} | set(FIELDS[kind])
    extra = set(action) - allowed
    if extra:
        return False, f"多余的字段 {sorted(extra)}（schema 不允许自由文本）"
    missing = set(FIELDS[kind]) - set(action)
    if missing:
        return False, f"缺少字段 {sorted(missing)}"
    for key, typ in FIELDS[kind].items():
        value = action[key]
        if typ is float:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"{key} 必须是数字"
            if not 0.0 <= float(value) <= 1.0:
                return False, f"{key}={value} 超出 0–1 相对坐标"
        elif typ is int:
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"{key} 必须是整数"
        elif typ is str:
            if not isinstance(value, str) or not value.strip():
                return False, f"{key} 不能为空"
            if len(value) > 200:
                return False, f"{key} 超过 200 字符（打字不是贴文档）"
    if kind == "scroll" and not -10 <= action["dy"] <= 10:
        return False, "dy 超出 ±10 格"
    if kind == "wait" and not 0 <= action["ms"] <= 5000:
        return False, "ms 超出 0–5000"
    return True, "ok"


def to_css(x: float, y: float, dpr: float = 2.0) -> tuple[int, int]:
    """相对坐标 -> CSS 像素。截图坐标要除以 dpr 才是 CSS 像素。"""
    return int(x * CSS_W), int(y * CSS_H)


def from_screenshot(px: int, py: int, dpr: float = 2.0) -> tuple[int, int]:
    """截图像素 -> CSS 像素。"""
    return int(px / dpr), int(py / dpr)


def image_tokens(w: int, h: int) -> int:
    """按 512 一格估图像 token（数量级演示，不是厂商公式）。"""
    return 85 + 170 * math.ceil(w / 512) * math.ceil(h / 512)


def main() -> None:
    print("=== 1. 六个动作，逐个校验 ===")
    cases = [
        {"kind": "click", "x": 0.14, "y": 0.47},
        {"kind": "click", "x": 140, "y": 340},
        {"kind": "type", "text": "O2024"},
        {"kind": "type", "text": ""},
        {"kind": "click", "x": 0.14, "y": 0.47, "thought": "先点登录"},
        {"kind": "done", "answer": "O2024 的收件人已改为张三"},
        {"kind": "done"},
        {"kind": "press", "key": "Enter"},
    ]
    for a in cases:
        ok, why = validate(a)
        print(f"    {str(a):<62}{'通过' if ok else '拒绝'}  {why}")

    print()
    print("=== 2. 相对坐标 -> CSS 像素 ===")
    for nx, ny in ((0.14, 0.47), (0.5, 0.5), (0.984, 0.996)):
        print(f"    ({nx},{ny}) -> {to_css(nx, ny)}")

    print()
    print("=== 3. 截图像素与 CSS 像素的差（dpr=2） ===")
    shot_w, shot_h = CSS_W * 2, CSS_H * 2
    print(f"    截图 {shot_w}x{shot_h}，页面 {CSS_W}x{CSS_H}")
    for px, py in ((280, 680), (1280, 720)):
        print(f"    截图上读到的 ({px},{py}) -> 应点 {from_screenshot(px, py)}；"
              f"直接点 ({px},{py}) 会偏 {px - from_screenshot(px, py)[0]}px")

    print()
    print("=== 4. 一帧的 token 量级 ===")
    print(f"    {CSS_W}x{CSS_H} 一帧约 {image_tokens(CSS_W, CSS_H)} tokens")


if __name__ == "__main__":
    main()
