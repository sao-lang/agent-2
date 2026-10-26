"""第 3 章 step4：token 计量器与窗口记账（离线可运行）。

运行：
    python code/ch03_tokens/step4_meter.py

演示三件事：
    1. 按真实词表计数，并计入消息结构开销
    2. 用一次真实调用的 usage 校准本地估算
    3. 窗口可用额度的计算与超出量判断
"""

from __future__ import annotations

import sys

import tiktoken


class TokenMeter:
    """优先使用服务端返回的 usage，缺失时才回落到本地估算。"""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        self.enc = tiktoken.get_encoding(encoding)
        self._calibration: float | None = None

    def count(self, text: str) -> int:
        return len(self.enc.encode(text))

    def count_messages(self, messages: list[dict], overhead: int = 4) -> int:
        """按消息计数，每条消息加固定结构开销，末尾加整体开销。"""
        return sum(self.count(m["content"]) + overhead for m in messages) + 2

    def calibrate(self, local: int, actual: int) -> None:
        if local > 0:
            self._calibration = actual / local

    @property
    def calibration(self) -> float | None:
        return self._calibration

    def estimate(self, text: str) -> int:
        raw = self.count(text)
        if self._calibration is None:
            return raw
        return round(raw * self._calibration)


class WindowBudget:
    def __init__(self, window: int, reserve_output: int,
                 system_tokens: int, tool_tokens: int = 0) -> None:
        self.window = window
        self.reserve_output = reserve_output
        self.system_tokens = system_tokens
        self.tool_tokens = tool_tokens

    @property
    def available(self) -> int:
        """可用于对话历史的 token 数。"""
        return self.window - self.reserve_output - self.system_tokens - self.tool_tokens

    def fits(self, history_tokens: int) -> bool:
        return history_tokens <= self.available

    def overflow(self, history_tokens: int) -> int:
        return max(0, history_tokens - self.available)


TEXTS = [
    ("中文", "签收后七天内可以申请无理由退货。"),
    ("英文", "Orders can be returned within seven days of delivery."),
]


def main() -> None:
    meter = TokenMeter()

    print("=" * 78)
    print("① 单条文本计数")
    print("=" * 78)
    for name, text in TEXTS:
        print(f"  {name:<6}{meter.count(text):>4} token   {text[:30]}")

    print()
    print("=" * 78)
    print("② 消息计数：正文 + 结构开销")
    print("=" * 78)
    msgs = [
        {"role": "system", "content": "你是售后助手。"},
        {"role": "user", "content": TEXTS[0][1]},
    ]
    raw = sum(meter.count(m["content"]) for m in msgs)
    print(f"  只算正文            {raw}")
    print(f"  计入结构开销        {meter.count_messages(msgs)}")
    print(f"  差值（结构开销）     {meter.count_messages(msgs) - raw}")

    print()
    print("=" * 78)
    print("③ 校准")
    print("=" * 78)
    local = meter.count_messages(msgs)
    actual = 60          # 假设服务端返回 60
    print(f"  本地估算            {local}")
    print(f"  服务端实际          {actual}")
    meter.calibrate(local=local, actual=actual)
    print(f"  校准系数            {meter.calibration:.3f}")
    print(f"  校准后估算          {meter.estimate(msgs[1]['content'])}")
    print(f"  未校准计数          {meter.count(msgs[1]['content'])}")

    print()
    print("=" * 78)
    print("④ 窗口记账")
    print("=" * 78)
    b = WindowBudget(window=1024, reserve_output=256, system_tokens=64, tool_tokens=128)
    print(f"  窗口上限            {b.window}")
    print(f"  输出预留            {b.reserve_output}")
    print(f"  系统消息            {b.system_tokens}")
    print(f"  工具定义            {b.tool_tokens}")
    print(f"  可用额度            {b.available}")
    for h in (500, 600, 700):
        print(f"  历史 {h:<4} fits={str(b.fits(h)):<6} overflow={b.overflow(h)}")

    print()
    print("=" * 78)
    print("⑤ 结论")
    print("=" * 78)
    print("  1. 只算正文会系统性低估，必须计入消息结构开销")
    print("  2. 校准系数让本地估算向服务端口径靠拢")
    print("  3. 可用额度必须预先扣除输出预留")
    print("  4. fits 与 overflow 分开，便于先判断再裁剪")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
