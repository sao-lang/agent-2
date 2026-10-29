"""上线四件套：鉴权、幂等、限流、队列。

不联网，不依赖第三方库。四件都做成最小对象，用同一批请求走一遍入口顺序：

    鉴权 -> 查幂等 -> 限流 -> 入队 + 登记幂等

每一件都至少拦下一次请求，输出里能看到它自己的状态码与理由。
运行：python code/knowledge/ch32_delivery/four_pieces.py
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class Request:
    api_key: str | None
    tenant: str
    body: str
    idem_key: str | None = None


class Auth:
    """静态 key 表。真实系统里换成数据库或签名校验，入口动作不变。"""

    KEYS = {"sk-t1": "tenant-1", "sk-t2": "tenant-2"}

    def check(self, req: Request) -> tuple[str | None, str | None]:
        tenant = self.KEYS.get(req.api_key or "")
        if tenant is None:
            return None, "未知 API key"
        if tenant != req.tenant:
            # 租户只从 key 推导，不信任请求体里声明的租户
            return None, f"key 属于 {tenant}，请求声明 {req.tenant}"
        return tenant, None


class Idem:
    """查询与登记分开：查询不产生副作用，登记才占一个任务号。"""

    def __init__(self) -> None:
        self.seen: dict[str, str] = {}

    def lookup(self, key: str | None) -> str | None:
        return self.seen.get(key) if key else None

    def remember(self, key: str | None, job: str) -> None:
        if key:
            self.seen[key] = job


class Limiter:
    """滑动窗口：每个租户在 window_s 秒内最多 limit 次。"""

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

    def retry_after(self, tenant: str, now: float) -> int:
        q = self.hits[tenant]
        if not q:
            return 0
        return max(0, math.ceil(self.window - (now - q[0])))


class Queue:
    """有容量上限的队列。put 失败就快速返回 503，不往进程内存里无限堆。"""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.items: list[str] = []

    def put(self, job: str) -> bool:
        if len(self.items) >= self.capacity:
            return False
        self.items.append(job)
        return True


def admit(
    req: Request,
    auth: Auth,
    idem: Idem,
    limiter: Limiter,
    queue: Queue,
    make_job,
    now: float,
) -> tuple[int, str]:
    """请求穿过四件套：鉴权 -> 查幂等 -> 限流 -> 入队 + 登记幂等。"""
    tenant, err = auth.check(req)
    if err:
        return 401, err

    known = idem.lookup(req.idem_key)
    if known:
        return 200, f"重复提交，返回已有 {known}，不占配额也不入队"

    if not limiter.allow(tenant, now):
        wait = limiter.retry_after(tenant, now)
        return 429, f"{tenant} 超过 2 次/60s，Retry-After: {wait}s"

    job = make_job()
    if not queue.put(job):
        return 503, "队列满（容量 3），快速失败"

    idem.remember(req.idem_key, job)
    return 202, f"入队 {job}，队列长度 {len(queue.items)}"


def main() -> None:
    auth = Auth()
    idem = Idem()
    limiter = Limiter(limit=2, window_s=60)   # 调小，便于在九次请求内看到 429
    queue = Queue(capacity=3)
    job_seq = 0

    def make_job() -> str:
        nonlocal job_seq
        job_seq += 1
        return f"job-{job_seq}"

    reqs = [
        ("#1", Request("sk-t1", "tenant-1", "查订单 A1001", "k-1")),
        ("#2", Request("bad", "tenant-1", "查订单 A1001")),
        ("#3", Request("sk-t1", "tenant-1", "查订单 A1002")),
        ("#4", Request("sk-t1", "tenant-1", "查订单 A1002", "k-1")),
        ("#5", Request("sk-t1", "tenant-1", "查订单 A1003")),
        ("#6", Request("sk-t2", "tenant-2", "查订单 B2001")),
        ("#7", Request("sk-t2", "tenant-2", "查订单 B2002")),
        ("#8", Request("sk-t2", "tenant-2", "查订单 B2003")),
        ("#9", Request("sk-t2", "tenant-2", "查订单 B2004")),
    ]

    now = time.monotonic()
    accepted = 0
    blocked = {"auth": 0, "idem": 0, "rate": 0, "queue": 0}
    tags = {202: "ok", 401: "auth", 200: "idem", 429: "rate", 503: "queue"}

    print("=== 1. 九次请求走一遍入口 ===")
    for i, (label, req) in enumerate(reqs, 1):
        code, msg = admit(req, auth, idem, limiter, queue, make_job, now + i * 0.01)
        tag = tags[code]
        if code == 202:
            accepted += 1
        else:
            blocked[tag] += 1
        head = f"  {label} {code}[{tag}]"
        print(head + " " * max(1, 15 - len(head)) + msg)

    print()
    print("=== 2. 四个中间件各自拦下的一次 ===")
    print("  auth   #2  401 未知 API key：一次字典查找，最便宜，放最前")
    print("  idem   #4  200 同一 Idempotency-Key：返回 job-1，不消耗限流配额")
    print("  rate   #5  429 tenant-1 已用满 2 次：保护下游，带 Retry-After")
    print("  queue  #7  503 队列容量 3 已满：快速失败，不把等待堆进内存")
    print(f"  合计：放行 {accepted} 条，拦下 {sum(blocked.values())} 条 "
          f"（auth={blocked['auth']} idem={blocked['idem']} "
          f"rate={blocked['rate']} queue={blocked['queue']}）")

    print()
    print("=== 3. 顺序换一下会怎样 ===")
    print("  限流放在鉴权前：无效 key 也能消耗配额，攻击者把正常租户挤掉")
    print("  登记幂等放在入队前且不回滚：队列满时留下永远不执行的任务号")
    print("  入队放在鉴权前：无效请求占满队列，正常请求全部 503")
    print("  本示例的顺序：鉴权 -> 查幂等 -> 限流 -> 入队 + 登记")


if __name__ == "__main__":
    main()
