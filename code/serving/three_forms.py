"""三种对外形态的最小实现：同步、异步、流式。

不联网，不开端口。三种形态都在一个进程里跑，用一个模拟的慢模型（每步 sleep）
来产生时序差异，客户端侧记录"它什么时候看到了什么"。

  同步  调用方一直等到结果
  异步  提交后立刻拿到任务号，之后轮询
  流式  边生成边返回，首字节远早于最后一段
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field

CHUNKS = ["根据政策，", "质量问题退货", "由商家承担运费，", "签收后 15 天内", "提交凭证即可。"]
STEP_SECONDS = 0.06          # 模拟每一步生成耗时


@dataclass
class Timeline:
    events: list[tuple[float, str]] = field(default_factory=list)
    t0: float = field(default_factory=time.perf_counter)

    def mark(self, what: str) -> None:
        self.events.append((time.perf_counter() - self.t0, what))

    def show(self, title: str) -> None:
        print(f"  {title}")
        for t, what in self.events:
            print(f"    t+{t * 1000:6.0f}ms  {what}")


def slow_generate() -> list[str]:
    out = []
    for c in CHUNKS:
        time.sleep(STEP_SECONDS)
        out.append(c)
    return out


def call_sync(timeout_s: float) -> dict:
    """同步：调用方等到完整结果，超时就放弃。"""
    tl = Timeline()
    tl.mark("客户端发出请求")
    t_start = time.perf_counter()
    try:
        for _ in CHUNKS:
            time.sleep(STEP_SECONDS)
            if time.perf_counter() - t_start > timeout_s:
                raise TimeoutError
    except TimeoutError:
        tl.mark(f"超过 {timeout_s * 1000:.0f}ms 客户端放弃，服务端仍在跑")
        return {"ok": False, "timeline": tl, "result": None}
    tl.mark("客户端收到完整结果")
    return {"ok": True, "timeline": tl, "result": "".join(CHUNKS)}


class JobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.q: queue.Queue[str] = queue.Queue()
        self._seq = 0

    def submit(self) -> str:
        self._seq += 1
        job_id = f"job-{self._seq}"
        self.jobs[job_id] = {"status": "pending", "result": None}
        self.q.put(job_id)
        return job_id


def worker(store: JobStore, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            job_id = store.q.get(timeout=0.05)
        except queue.Empty:
            continue
        store.jobs[job_id]["status"] = "running"
        store.jobs[job_id]["result"] = "".join(slow_generate())
        store.jobs[job_id]["status"] = "done"


def call_async(store: JobStore) -> dict:
    """异步：提交后立刻返回任务号，调用方轮询。"""
    tl = Timeline()
    tl.mark("客户端提交任务")
    job_id = store.submit()
    tl.mark(f"拿到任务号 {job_id}")

    seen: list[str] = []
    deadline = time.perf_counter() + 3.0
    while time.perf_counter() < deadline:
        status = store.jobs[job_id]["status"]
        if status not in seen:
            seen.append(status)
            tl.mark(f"轮询到 {status}")
        if status == "done":
            tl.mark("取回结果")
            return {"ok": True, "timeline": tl, "result": store.jobs[job_id]["result"]}
        time.sleep(0.05)
    return {"ok": False, "timeline": tl, "result": None}


def call_stream() -> dict:
    """流式：第一段一生成就返回，调用方逐步拼接。"""
    tl = Timeline()
    tl.mark("客户端建立连接")
    got: list[str] = []
    for c in CHUNKS:
        time.sleep(STEP_SECONDS)
        got.append(c)
        tl.mark(f"收到第 {len(got)} 段：{c}")
    return {"ok": True, "timeline": tl, "result": "".join(got)}


def main() -> None:
    print("=== 1. 同步：调用方一直等到最后 ===")
    r = call_sync(timeout_s=0.2)
    r["timeline"].show("超时上限 200ms")
    print(f"    结果：{r['result']}")
    print("    <- 服务端其实生成完了，但客户端已经走了")

    print()
    print("=== 2. 异步：先拿号，再轮询 ===")
    store = JobStore()
    stop = threading.Event()
    t = threading.Thread(target=worker, args=(store, stop), daemon=True)
    t.start()
    r = call_async(store)
    r["timeline"].show("提交后立刻返回")
    print(f"    结果：{r['result']}")
    stop.set()

    print()
    print("=== 3. 流式：首段与末段间隔 ===")
    r = call_stream()
    r["timeline"].show("逐段返回")
    first = r["timeline"].events[1][0]
    last = r["timeline"].events[-1][0]
    print(f"    首段 {first * 1000:.0f}ms，末段 {last * 1000:.0f}ms，"
          f"用户看到第一句话等了 {first * 1000:.0f}ms")
    print(f"    结果：{r['result']}")

    print()
    print("=== 4. 三种形态的对照 ===")
    print(f"  同步  客户端阻塞 {sum(STEP_SECONDS for _ in CHUNKS) * 1000:.0f}ms，失败时什么也没拿到")
    print(f"  异步  提交耗时 ~0ms，完成需要轮询 {sum(STEP_SECONDS for _ in CHUNKS) * 1000:.0f}ms")
    print(f"  流式  首段 {STEP_SECONDS * 1000:.0f}ms 可见，总时长与同步相同")
    print(f"  三种形态的总耗时相同，差的是'什么时候给用户看第一段'")


if __name__ == "__main__":
    main()
