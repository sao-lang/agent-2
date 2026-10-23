"""第 41 章 step2：任务队列 / 幂等键 / 限流 / 鉴权 —— 四件"上线前必须做，做完看不见"的事。

运行：
    python code/ch42_integration/step2_queue.py

全部离线、纯标准库。队列用"内存版"模拟，但语义（可见性超时、重投、死信、幂等）
和真实 SQS / Redis Stream / Celery 完全一致——换成真队列只是把三行代码换掉。
"""
from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


# ================================================================ ① 带可见性超时的队列
@dataclass
class Message:
    msg_id: str
    body: dict[str, Any]
    attempts: int = 0
    visible_at: float = 0.0


class InMemoryQueue:
    """最小队列：ack / nack / 可见性超时 / 死信。

    为什么要"可见性超时"而不是"出队即删"？
    因为消费者可能在中途崩掉。出队即删 = 这条消息永久消失。
    真实实现（SQS visibility timeout / Redis Stream XCLAIM）都是同一个思路。
    """

    def __init__(self, visibility_timeout: float = 0.0, max_attempts: int = 3) -> None:
        self.ready: deque[Message] = deque()
        self.inflight: dict[str, Message] = {}
        self.dead: list[Message] = []
        self.visibility_timeout = visibility_timeout
        self.max_attempts = max_attempts
        self._seq = 0

    def send(self, body: dict[str, Any]) -> str:
        self._seq += 1
        mid = f"m-{self._seq}"
        self.ready.append(Message(mid, body))
        return mid

    def receive(self) -> Message | None:
        now = time.monotonic()
        # 先把可见性超时到期的消息放回 ready（这叫"重投"）
        for mid, m in list(self.inflight.items()):
            if m.visible_at <= now:
                del self.inflight[mid]
                self.ready.appendleft(m)
        if not self.ready:
            return None
        m = self.ready.popleft()
        m.attempts += 1
        m.visible_at = now + self.visibility_timeout
        self.inflight[m.msg_id] = m
        return m

    def ack(self, m: Message) -> None:
        self.inflight.pop(m.msg_id, None)

    def nack(self, m: Message) -> None:
        self.inflight.pop(m.msg_id, None)
        if m.attempts >= self.max_attempts:
            self.dead.append(m)
        else:
            self.ready.appendleft(m)


def demo_at_least_once() -> None:
    print("① 「出队即删」 vs 「可见性超时」")
    body = {"task": "index_doc", "doc_id": 7}

    naive = deque([body])
    got = naive.popleft()  # 消费者取走
    del got  # 消费者崩了
    print(f"   出队即删：剩余 {len(naive)} 条 → 这个任务永久丢失")

    q = InMemoryQueue(visibility_timeout=0.0, max_attempts=3)
    q.send(body)
    m1 = q.receive()
    print(f"   可见性超时：第一次取到 {m1.msg_id if m1 else None}，未 ack，消费者崩了")
    m2 = q.receive()
    print(f"               重新投递 → 又取到 {m2.msg_id if m2 else None}，attempts={m2.attempts if m2 else 0}")
    assert m2 is not None
    q.ack(m2)
    print(f"               ack 之后剩余 ready={len(q.ready)} inflight={len(q.inflight)}")
    print("   代价：任务可能被执行两次 → 所以必须有幂等键（见 ②）")
    print()


def demo_dead_letter() -> None:
    print("② 死信队列：一条永远失败的消息会怎样")
    q = InMemoryQueue(visibility_timeout=0.0, max_attempts=3)
    q.send({"task": "bad"})
    while True:
        m = q.receive()
        if m is None:
            break
        q.nack(m)
    print(f"   ready={len(q.ready)}  inflight={len(q.inflight)}  dead={len(q.dead)}")
    print(f"   死信里的消息 attempts={q.dead[0].attempts if q.dead else 0}")
    print("   注意：如果没有 max_attempts，这条消息会无限重投，把 worker 全部占死")
    print()


# ================================================================ ③ 幂等键
class IdempotentStore:
    """幂等表：key → 第一次的结果。第二次相同 key 直接返回缓存。

    三个必须想清楚的细节：
      1. key 从哪来——**客户端生成**（服务端生成就不是幂等了）
      2. key 存多久——至少覆盖"最大可能重试窗口"，常见 24h
      3. 并发下两个人同时用同一 key——需要 setnx，"先查再写"有竞态
    """

    def __init__(self) -> None:
        self.done: dict[str, Any] = {}
        self.calls = 0

    def run_once(self, key: str, fn: Callable[[], Any]) -> tuple[Any, bool]:
        if key in self.done:
            return self.done[key], True
        self.calls += 1
        result = fn()
        self.done[key] = result
        return result, False


def demo_idempotency() -> None:
    print("③ 幂等键：重投的消息真的只算一次钱")
    store = IdempotentStore()
    sent: list[str] = []

    def send_email() -> str:
        sent.append("email")
        return f"sent#{len(sent)}"

    key = hashlib.sha256(b"order-8831-refund-notice").hexdigest()[:12]
    for _ in range(3):
        result, cached = store.run_once(key, send_email)
        print(f"   调用 → {result:<8} cached={cached}")
    print(f"   实际执行业务函数 {store.calls} 次，发出邮件 {len(sent)} 封")
    print()

    print("   💥 失败实验：key 由服务端生成会怎样")
    calls = {"n": 0}

    def server_key() -> str:
        calls["n"] += 1
        return f"srv-{calls['n']}"

    store2 = IdempotentStore()
    for _ in range(3):
        store2.run_once(server_key(), send_email)
    print(f"   服务端每次生成新 key → 执行了 {store2.calls} 次，幂等完全失效")
    print()


# ================================================================ ④ 令牌桶限流
class TokenBucket:
    """令牌桶：允许突发（桶容量），长期速率受 rate 约束。

    和"固定窗口计数器"的区别：固定窗口在窗口边界会放过 2 倍流量
    （59 秒 100 次 + 61 秒 100 次 = 2 秒内 200 次）。令牌桶不会。
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last = time.monotonic()

    def allow(self, n: int = 1) -> tuple[bool, float]:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= n:
            self.tokens -= n
            return True, 0.0
        wait = (n - self.tokens) / self.rate
        return False, wait


class FixedWindow:
    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self.start = time.monotonic()
        self.count = 0

    def allow(self, n: int = 1) -> tuple[bool, float]:
        now = time.monotonic()
        if now - self.start >= self.window:
            self.start = now
            self.count = 0
        if self.count + n <= self.limit:
            self.count += n
            return True, 0.0
        return False, self.window - (now - self.start)


def demo_ratelimit() -> None:
    print("④ 限流：令牌桶 vs 固定窗口（同样 20 req/s 的额度）")
    bucket = TokenBucket(rate=20, capacity=20)
    passed = sum(1 for _ in range(60) if bucket.allow()[0])
    print(f"   令牌桶：瞬时打 60 个请求，放过 {passed} 个（桶容量 20，符合预期）")

    fw = FixedWindow(limit=20, window=1.0)
    passed_fw = 0
    for _ in range(60):
        if fw.allow()[0]:
            passed_fw += 1
        time.sleep(0.016)  # 60 个请求铺满约 1 秒
    print(f"   固定窗口：同样的 60 个请求，放过 {passed_fw} 个")

    b2 = TokenBucket(rate=1, capacity=1)
    ok, wait = b2.allow()
    b2.tokens = 0.0
    allowed, wait = b2.allow()
    print(f"   令牌桶用完 → allowed={allowed}，建议客户端等 {wait:.2f}s（可以写进 Retry-After 头）")
    print()


# ================================================================ ⑤ 鉴权
@dataclass
class Principal:
    user_id: str
    tenant: str
    scopes: set[str] = field(default_factory=set)


API_KEYS = {
    "sk-acme-read": Principal("u1", "acme", {"chat:read"}),
    "sk-acme-admin": Principal("u2", "acme", {"chat:read", "index:write"}),
}


def auth(api_key: str | None, need: str) -> tuple[Principal | None, int, str]:
    """返回 (principal, status, reason)。三种失败要区分开——

    这才是重点：401/403 混在一起，用户排查时会浪费几个小时。
    """
    if not api_key:
        return None, 401, "缺少 Authorization 头"
    p = API_KEYS.get(api_key)
    if p is None:
        return None, 401, "API key 无效"
    if need not in p.scopes:
        return None, 403, f"已认证但缺少 scope {need}（当前 {sorted(p.scopes)}）"
    return p, 200, "ok"


def demo_auth() -> None:
    print("⑤ 鉴权：401 和 403 必须分开")
    for key, need, label in [
        (None, "chat:read", "没带 key"),
        ("sk-wrong", "chat:read", "错 key"),
        ("sk-acme-read", "index:write", "key 对但没权限"),
        ("sk-acme-admin", "index:write", "key 对且有权限"),
    ]:
        p, status, reason = auth(key, need)
        tenant = p.tenant if p else "-"
        print(f"   {label:<18} → HTTP {status}  tenant={tenant:<6} {reason}")
    print()

    print("   💥 失败实验：tenant 从请求体里取")
    body = {"q": "上季度营收", "tenant": "globex"}  # 攻击者自己填了别家租户
    p = API_KEYS["sk-acme-read"]
    effective = body.get("tenant", p.tenant)
    print(f"   key 属于 {p.tenant}，但请求体声称 {body['tenant']} → 实际按 {effective} 查数据")
    print("   → 跨租户数据泄露。tenant 只能从凭证推导，永不接受客户端输入")
    print()


# ================================================================ 综合
def demo_end_to_end() -> None:
    print("⑥ 四件事串起来：一次「退款通知」任务的完整生命周期")
    q = InMemoryQueue(visibility_timeout=0.0, max_attempts=2)
    store = IdempotentStore()
    bucket = TokenBucket(rate=100, capacity=5)

    trace: list[str] = []
    for i in range(3):
        allowed, _ = bucket.allow()
        trace.append(f"请求{i + 1} 限流={'过' if allowed else '挡'}")
        if allowed:
            q.send({"idem_key": "refund-8831", "task": "notify"})

    while (m := q.receive()) is not None:
        result, cached = store.run_once(m.body["idem_key"], lambda: "notified")
        trace.append(f"消费 {m.msg_id} attempts={m.attempts} → {result} cached={cached}")
        q.ack(m)

    print("   " + "\n   ".join(trace))
    print(f"   最终：业务只执行 {store.calls} 次，3 条消息全部 ack")
    print()


def main() -> None:
    demo_at_least_once()
    demo_dead_letter()
    demo_idempotency()
    demo_ratelimit()
    demo_auth()
    demo_end_to_end()


if __name__ == "__main__":
    main()
