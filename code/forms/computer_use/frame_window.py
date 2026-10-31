"""最近 3 帧 vs 全历史：上下文里放多少帧。

不联网。帧数不变、动作不变，只改"带几帧进上下文"。
图像 token 按 512 一格估（数量级演示，不是厂商公式）；文本动作历史按字符估。

运行：python code/forms/computer_use/frame_window.py
"""

from __future__ import annotations

import math

STEPS = 8
CSS_W, CSS_H = 1280, 720
ACTION_CHARS = 42               # 每条动作历史的平均字符数（动作 + 结果摘要）


def image_tokens(w: int, h: int) -> int:
    return 85 + 170 * math.ceil(w / 512) * math.ceil(h / 512)


def cost(frames_kept: int) -> tuple[int, int]:
    """每步只带最近 k 帧（前几步不足 k 帧），文本历史累积带上。"""
    per_frame = image_tokens(CSS_W, CSS_H)
    image_part = sum(per_frame * min(frames_kept, i) for i in range(1, STEPS + 1))
    text_part = sum(int(ACTION_CHARS * i * 0.6) for i in range(1, STEPS + 1))
    return image_part, text_part


def main() -> None:
    print(f"=== 1. {STEPS} 步，每步带几帧 ===")
    print(f"    一帧 {CSS_W}x{CSS_H} 约 {image_tokens(CSS_W, CSS_H)} tokens")
    print(f"    {'保留帧数':<10}{'图像 tokens':>12}{'文本历史':>10}{'合计':>10}")
    for k in (1, 2, 3, 8):
        img, txt = cost(k)
        print(f"    {k:<10}{img:>12}{txt:>10}{img + txt:>10}")

    print()
    print("=== 2. 3 帧与全历史的差 ===")
    img3, txt3 = cost(3)
    img8, txt8 = cost(8)
    print(f"    3 帧：{img3 + txt3} tokens")
    print(f"    8 帧：{img8 + txt8} tokens")
    print(f"    差 {img8 + txt8 - (img3 + txt3)} tokens，是 3 帧方案的 "
          f"{(img8 + txt8) / (img3 + txt3):.2f} 倍")

    print()
    print("=== 3. 为什么是 3 帧而不是 1 帧 ===")
    print("    1 帧：只能看到当前画面，看不到'刚才那一下有没有生效'")
    print("    2 帧：能判断变化，但分不清'变化是这一步造成的还是上一步延迟生效'")
    print("    3 帧：能看到 前 -> 中 -> 后，够判断一次动作的效果与页面是否稳定")
    print("    再多的帧，信息增量主要来自很久以前，而那时页面已经变了")

    print()
    print("=== 4. 文本动作历史不能一起砍 ===")
    print("    全历史文本：" + f"{txt8} tokens" + "（8 步全部动作与结果）")
    print("    动作历史回答'我试过什么'，帧回答'现在是什么样'")
    print("    只留帧不留历史，会重复已经失败过的动作（第 47 章的重复动作）")


if __name__ == "__main__":
    main()
