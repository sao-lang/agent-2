"""上线前四件套：队列、幂等、限流、鉴权。

不联网。四件都做成最小可运行的小对象，然后用同一批请求打过去，看各自拦下
哪些、放过哪些。顺序有讲究：先鉴权（最便宜），再限流，再幂等，最后入队。
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class Request:
    api_key: str
    user_id: str
    body: str
    idem_key: str | None = None


# ---------------------------------------------------------------- 鉴权
API_KEYS = {"sk-a": "tenant-1", "sk-b": "tenant-2"}


def auth(req: Request) -> tuple[bool, str]:
    tenant = API_KEYS.get(req.api_key)
    if tenant is None:
        return False, "未知 API key"
    if tenant != req.user_id.split(":")[0]:
        return False, "key 与租户不匹配"
    return True, tenant


# ---------------------------------------------------------------- 限流
class RateLimiter:
    """滑动窗口：每个租户每分钟 N 次。"""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, tenant: str, now: float) -> bool:
        q = self.hits[tenant]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


# ---------------------------------------------------------------- 幂等
class Idempotency:
    def __init__(self) -> None:
        self.seen: dict[str, str] = {}     # key -> job_id

    def lookup(self, key: str | None) -> str | None:
        """只查不登记：重复请求不该消耗配额，也不该占队列。"""
        return self.seen.get(key) if key else None

    def claim(self, key: str | None, make_job) -> str:
        job = make_job()
        if key:
            self.seen[key] = job
        return job


# ---------------------------------------------------------------- 队列
class Queue:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.items: list[str] = []

    def put(self, job_id: str) -> bool:
        if len(self.items) >= self.capacity:
            return False
        self.items.append(job_id)
        return True

    def take(self) -> str | None:
        return self.items.pop(0) if self.items else None


def fingerprint(body: str) -> str:
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]


def main() -> None:
    limiter = RateLimiter(limit=3, window_s=60)
    idem = Idempotency()
    q = Queue(capacity=3)
    job_seq = 0

    def make_job() -> str:
        nonlocal job_seq
        job_seq += 1
        return f"job-{job_seq}"

    reqs = [
        Request("sk-a", "tenant-1:u1", "查订单 A1001"),
        Request("bad", "tenant-1:u1", "查订单 A1001"),
        Request("sk-a", "tenant-1:u1", "查订单 A1002", idem_key="k-1"),
        Request("sk-a", "tenant-1:u1", "查订单 A1002", idem_key="k-1"),
        None,                                   # 占位：worker 取走一个任务
        Request("sk-a", "tenant-1:u1", "查订单 A1003"),
        Request("sk-a", "tenant-1:u1", "查订单 A1004"),
        Request("sk-b", "tenant-2:u9", "查订单 B2001"),
        Request("sk-a", "tenant-1:u1", "再查 A1001", idem_key="k-1"),
    ]

    now = time.monotonic()
    print("=== 1. 九步：七次请求 + 一次出队 + 一次重放 ===")
    for i, r in enumerate(reqs, 1):
        if r is None:
            job = q.take()
            print(f"  #{i} worker 取走 {job}（队列剩 {len(q.items)}）")
            continue
        ok, info = auth(r)
        if not ok:
            print(f"  #{i} 拒绝[auth]   {info}")
            continue
        known = idem.lookup(r.idem_key)
        if known:
            print(f"  #{i} 幂等命中      返回已有 {known}（不消耗配额）")
            continue
        if not limiter.allow(info, now + i * 0.01):
            print(f"  #{i} 拒绝[rate]   {info} 超过每分钟 3 次")
            continue
        job = idem.claim(r.idem_key, make_job)
        if not q.put(job):
            print(f"  #{i} 拒绝[queue]  队列满（容量 3）")
            continue
        print(f"  #{i} 入队           {job}  fingerprint={fingerprint(r.body)}")

    print()
    print("=== 2. 四件套各拦下什么 ===")
    print("  auth   未知 key 与跨租户：最便宜，先做")
    print("  rate   单租户高频：保护自己的下游")
    print("  idem   重复提交：同一 key 返回同一任务号")
    print("  queue  突发流量：满了就快速失败，而不是拖垮进程")

    print()
    print("=== 3. 顺序换一下会怎样 ===")
    print("  先限流后鉴权：攻击者用无效 key 就能把配额打满，正常租户被限")
    print("  登记幂等放在限流之前：被限流的请求留下一个永远不会执行的任务号")
    print("  先入队后鉴权：无效请求占满队列，正常请求全部被拒")
    print("  示例的顺序是：鉴权 -> 查幂等 -> 限流 -> 登记幂等 + 入队")


if __name__ == "__main__":
    main()
