"""失败处理：超时、重试预算、熔断三态、降级三档。

全部用模拟时钟（不真的 sleep），结果确定可复现。
只演示判定逻辑，不发真实请求。
"""

from __future__ import annotations

import random


class Clock:
    """模拟时钟：now() 返回秒，sleep 只推进时间。"""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class Breaker:
    """三态熔断：closed → open → half-open → closed/open。

    失败计数按"目标"分开：这里只演示单个 target。
    """

    def __init__(self, threshold: int = 3, cooldown: float = 10.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.rejected = 0

    def allow(self, now: float) -> bool:
        if self.state == "open":
            if now - self.opened_at >= self.cooldown:
                self.state = "half-open"
                return True          # 放一个探针
            self.rejected += 1
            return False
        if self.state == "half-open":
            return False             # 半开期间只允许一个探针
        return True

    def record(self, ok: bool, now: float) -> str:
        if self.state == "half-open":
            if ok:
                self.state, self.failures = "closed", 0
                return "closed"
            self.state, self.failures, self.opened_at = "open", 0, now
            return "open"
        if ok:
            self.failures = 0
            return self.state
        self.failures += 1
        if self.failures >= self.threshold:
            self.state, self.opened_at, self.failures = "open", now, 0
        return self.state


def degrade(primary_ok: bool, fallback_ok: bool, cache_hit: bool) -> dict:
    """降级三档：换模型 → 换路径（缓存）→ 兜底。每档都带正确性判据。"""
    if primary_ok:
        return {"tier": "primary", "answer": "正常答案",
                "criterion": "schema 通过"}
    if fallback_ok:
        return {"tier": "tier1 换模型", "answer": "备用模型答案",
                "criterion": "schema 仍通过 -> 可交付"}
    if cache_hit:
        return {"tier": "tier2 换路径", "answer": "缓存/关键词答案",
                "criterion": "引用可回指 -> 可交付"}
    return {"tier": "tier3 兜底", "answer": "明确拒绝 + 稍后重试",
            "criterion": "不产生错误答案"}


def retry_timeline(clock: Clock, attempts: int, duration: float,
                   timeout: float, backoff: float = 0.5) -> dict:
    """下游每次都会失败；比较"有超时"与"没有超时"的墙上时间与下游占用。"""
    wall0 = clock.now()
    downstream = 0.0
    for i in range(attempts):
        used = min(duration, timeout)
        downstream += used
        clock.sleep(used)
        clock.sleep(backoff * (i + 1))
    return {"wall": round(clock.now() - wall0, 1),
            "downstream": round(downstream, 1),
            "left_running": round(attempts * max(0.0, duration - timeout), 1)}


def main() -> None:
    print("=== 1. 没有超时的重试 = 放大器 ===")
    print("  下游每次 30s 才失败，重试 3 次，退避 0.5/1.0/1.5s")
    clock = Clock()
    a = retry_timeline(clock, 3, duration=30, timeout=999)
    print(f"  不设超时：墙上 {a['wall']:>5.1f}s，下游累计占用 {a['downstream']:>5.1f}s")
    clock2 = Clock()
    b = retry_timeline(clock2, 3, duration=30, timeout=5)
    print(f"  超时  5s：墙上 {b['wall']:>5.1f}s，下游累计占用 {b['downstream']:>5.1f}s，"
          f"另有 {b['left_running']:.1f}s 仍在跑")
    print(f"  -> 超时把等待从 {a['wall']}s 压到 {b['wall']}s；没有它，重试只是把等待乘 3")

    print()
    print("=== 2. 熔断三态：失败 3 次打开，冷却后放一个探针 ===")
    clock = Clock()
    b = Breaker(threshold=3, cooldown=10)
    plan = [("调用", False)] * 3 + [("调用", True)] * 4
    for i, (kind, ok) in enumerate(plan, 1):
        if not b.allow(clock.now()):
            print(f"  t={clock.now():>4.0f}s 第 {i:>2} 次 {kind}: 拒绝（open，快速失败）")
            continue
        clock.sleep(0.2)
        st = b.record(ok, clock.now())
        print(f"  t={clock.now():>4.0f}s 第 {i:>2} 次 {kind}: "
              f"{'成功' if ok else '失败'} -> {st}")
    clock.sleep(10)
    print(f"  t={clock.now():>4.0f}s 冷却结束，下一个请求："
          f"{'放行探针' if b.allow(clock.now()) else '仍拒绝'}")
    st = b.record(True, clock.now())
    print(f"  探针成功 -> {st}；累计快速失败 {b.rejected} 次（没有打到下游）")

    print()
    print("=== 3. 降级三档 ===")
    cases = [
        (True, True, True),
        (False, True, True),
        (False, False, True),
        (False, False, False),
    ]
    for primary, fallback, cache in cases:
        d = degrade(primary, fallback, cache)
        print(f"  主={int(primary)} 备={int(fallback)} 缓存={int(cache)} -> "
              f"{d['tier']:<10} {d['criterion']}")


if __name__ == "__main__":
    main()
