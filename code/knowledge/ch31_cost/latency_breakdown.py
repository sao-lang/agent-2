"""延迟分解：TTFT 与总延迟、并行化收益、降级链。

不联网。一次请求拆成五段，先算 TTFT（首字节）与总延迟，再看三种优化各省多少，
最后看降级链在主模型超时时怎么保住可用性。
"""

from __future__ import annotations

SEGMENTS = [
    ("排队", 120),
    ("检索", 400),
    ("模型首字节", 900),
    ("生成", 2400),
    ("工具调用", 600),
]


def waterfall() -> tuple[int, int]:
    print("=== 1. 一次请求的延迟分解 ===")
    print(f"  {'段':<12}{'耗时(ms)':>10}{'累计(ms)':>10}{'占总量':>8}")
    acc = 0
    for name, ms in SEGMENTS:
        acc += ms
        print(f"  {name:<12}{ms:>10}{acc:>10}{ms / total_ms():>8.1%}")
    ttft = sum(ms for name, ms in SEGMENTS if name in ("排队", "检索", "模型首字节"))
    print(f"  {'合计':<12}{total_ms():>10}{total_ms():>10}{1:>8.1%}")
    print(f"  TTFT = 排队 + 检索 + 首字节 = {ttft}ms")
    print(f"  总延迟 = {total_ms()}ms，TTFT 占 {ttft / total_ms():.1%}")
    return ttft, total_ms()


def total_ms() -> int:
    return sum(ms for _, ms in SEGMENTS)


def optimizations() -> None:
    print()
    print("=== 2. 三种优化各省多少 ===")
    base = total_ms()
    plans = [
        ("检索与工具并行", lambda: base - min(400, 600)),
        ("流式输出（首字节不变）", lambda: base),
        ("模型换小一档（首字节 900 -> 500）", lambda: base - 400),
        ("检索加缓存（400 -> 40）", lambda: base - 360),
    ]
    for name, fn in plans:
        v = fn()
        print(f"  {name:<32}{v:>6}ms  （省 {base - v:>4}ms，{(base - v) / base:>5.1%}）")

    print()
    print("  注意：流式不改总延迟，改的是 TTFT。")
    ttft = sum(ms for name, ms in SEGMENTS if name in ("排队", "检索", "模型首字节"))
    print(f"  流式之前 TTFT {ttft}ms，流式之后仍是 {ttft}ms，"
          f"但用户看到第一段的时间等于 TTFT 而不是总延迟")


def degradation() -> None:
    print()
    print("=== 3. 降级链：主模型超时时 ===")
    chain = [
        ("主模型", 2800, "正常", True),
        ("备用模型", 5200, "正常但慢", True),
        ("语义缓存", 80, "可能过期", True),
        ("模板兜底", 20, "只给政策原文", False),
    ]
    budget = 2000
    print(f"  单次等待预算 {budget}ms")
    for name, ms, quality, usable in chain:
        if ms <= budget:
            print(f"  {name:<10}{ms:>6}ms  质量：{quality:<10}采用，链在此停止")
            break
        print(f"  {name:<10}{ms:>6}ms  质量：{quality:<10}超预算，降下一级")
    print("  <- 降级不是'换一个更快的'，是'按预算逐级降质量'")


def main() -> None:
    waterfall()
    optimizations()
    degradation()


if __name__ == "__main__":
    main()
