"""第 31 章示例：三种对外形态与一条可重连的 SSE。

不联网，只用标准库。SSE 服务起在 127.0.0.1 的临时端口（port=0），
跑完就关，不占固定端口。
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CHUNKS = [
    "根据政策，",
    "质量问题退货",
    "由商家承担运费，",
    "签收后 15 天内",
    "提交凭证即可。",
]
ANSWER = "".join(CHUNKS)
STEP_SECONDS = 0.06
SYNC_TIMEOUT = 0.2
HEARTBEAT_SECONDS = 0.45


class Timeline:
    """记录客户端视角的时间点，统一用相对毫秒打印。"""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.rows: list[tuple[int, str]] = []

    def mark(self, text: str) -> None:
        ms = int((time.monotonic() - self.started) * 1000)
        self.rows.append((ms, text))

    def dump(self) -> None:
        for ms, text in self.rows:
            print(f"  t+{ms:>4}ms  {text}")


# --------------------------------------------------------------- 同步

def call_sync(timeout: float = SYNC_TIMEOUT) -> tuple[Timeline, str | None]:
    """同步：客户端守一个上限，超时就放弃；服务端不知道，继续跑。"""
    tl = Timeline()
    tl.mark("客户端发出请求")
    aborted = False
    for i, _chunk in enumerate(CHUNKS, 1):
        time.sleep(STEP_SECONDS)
        waited = time.monotonic() - tl.started
        if not aborted and waited >= timeout:
            tl.mark(f"客户端超时放弃（上限 {int(timeout * 1000)}ms）")
            aborted = True
        if i == len(CHUNKS):
            tl.mark("服务端生成完毕，结果留在服务端")
    return tl, None if aborted else ANSWER


# --------------------------------------------------------------- 异步

class JobStore:
    """任务表：内存 dict + 一把锁。生产里换成数据库或 Redis。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}

    def submit(self, key: str) -> tuple[str, bool]:
        """同一个 Idempotency-Key 只建一个任务；返回（任务号，是否新建）。"""
        with self.lock:
            if key in self.by_key:
                return self.by_key[key], False
            job_id = f"job-{len(self.jobs) + 1}"
            self.jobs[job_id] = {"status": "pending", "result": None}
            self.by_key[key] = job_id
            return job_id, True

    def run(self, job_id: str) -> None:
        with self.lock:
            self.jobs[job_id]["status"] = "running"
        for _chunk in CHUNKS:
            time.sleep(STEP_SECONDS)
        with self.lock:
            self.jobs[job_id]["status"] = "done"
            self.jobs[job_id]["result"] = ANSWER

    def get(self, job_id: str) -> dict:
        with self.lock:
            return dict(self.jobs[job_id])


def call_async() -> None:
    store = JobStore()
    tl = Timeline()
    key = "order-A1001"
    job_id, created = store.submit(key)
    tl.mark(f"提交（Idempotency-Key: {key}）→ {job_id}，新建={created}")
    duplicate, created_again = store.submit(key)
    tl.mark(f"同一键重复提交 → {duplicate}，新建={created_again}")

    worker = threading.Thread(target=store.run, args=(job_id,), daemon=True)
    worker.start()

    last_status = ""
    deadline = time.monotonic() + 2
    result = None
    while time.monotonic() < deadline:
        snap = store.get(job_id)
        if snap["status"] != last_status:
            last_status = snap["status"]
            tl.mark(f"轮询：{last_status}")
        if snap["status"] == "done":
            result = snap["result"]
            break
        time.sleep(0.03)
    tl.dump()
    print(f"  调用方拿到：{result}")


# --------------------------------------------------------------- 流式

def call_stream() -> Timeline:
    tl = Timeline()
    tl.mark("客户端建立连接")
    got: list[str] = []
    for chunk in CHUNKS:
        time.sleep(STEP_SECONDS)
        got.append(chunk)
        tl.mark(f"收到第 {len(got)} 段：{chunk}")
    assert "".join(got) == ANSWER
    return tl


# --------------------------------------------------------------- SSE

EVENTS = {
    1: "根据政策，",
    2: "质量问题退货",
    3: "由商家承担运费，",
    4: "签收后 15 天内提交凭证即可。",
}


class SSEHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def write_frame(self, frame: str) -> None:
        self.wfile.write((frame + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/stream":
            self.send_error(404)
            return
        fail = parse_qs(parsed.query).get("fail", ["0"])[0] == "1"
        last = self.headers.get("Last-Event-ID", "")
        start = int(last) + 1 if last.isdigit() else 1

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()

            for i in range(start, 5):
                time.sleep(HEARTBEAT_SECONDS)
                self.write_frame(": ping")  # 心跳：注释帧，客户端会忽略
                body = json.dumps({"text": EVENTS[i]}, ensure_ascii=False)
                self.write_frame(f"id: {i}\nevent: delta\ndata: {body}")
                if fail and i == 2:
                    payload = {
                        "code": "model_overloaded",
                        "retry_after_ms": 2000,
                        "partial_chars": len(EVENTS[1]) + len(EVENTS[2]),
                    }
                    body = json.dumps(payload, ensure_ascii=False)
                    self.write_frame(f"event: error\ndata: {body}")
                    return

            body = json.dumps(
                {"finish_reason": "stop", "chars": len(ANSWER)}, ensure_ascii=False
            )
            self.write_frame(f"id: 5\nevent: done\ndata: {body}")
        except OSError:
            # 客户端在这一帧之前断开了，这一路就不再有接收方。
            pass


def read_stream(
    port: int,
    last_id: int | None = None,
    stop_after_id: int | None = None,
    fail: bool = False,
) -> tuple[list[list[str]], list[str]]:
    """用裸 http.client 读原始帧，不经过任何会攒包的封装。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Last-Event-ID": str(last_id)} if last_id is not None else {}
    path = "/stream" + ("?fail=1" if fail else "")
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()

    frames: list[list[str]] = []
    ids: list[str] = []
    try:
        while True:
            block: list[str] = []
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8").rstrip("\r\n")
                if text == "":
                    break
                block.append(text)
            if not block:
                break
            frames.append(block)
            for line in block:
                if line.startswith("id: "):
                    ids.append(line[4:])
            if stop_after_id is not None and ids and int(ids[-1]) >= stop_after_id:
                break
    finally:
        resp.close()
        conn.close()
    return frames, ids


def show_frames(frames: list[list[str]]) -> None:
    for block in frames:
        for line in block:
            print(f"    {line}")


def main() -> None:
    print("=== 1. 同步：调用方一直等到超时 ===")
    tl, result = call_sync()
    tl.dump()
    print(f"  调用方拿到：{result!r}")

    print("\n=== 2. 异步：先拿任务号，再轮询 ===")
    call_async()

    print("\n=== 3. 流式：首段与末段 ===")
    tl = call_stream()
    tl.dump()
    print(f"  调用方拿到：{ANSWER}")
    print("  总耗时相同，差的是用户多早看到第一段")

    server = ThreadingHTTPServer(("127.0.0.1", 0), SSEHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        print(f"\n=== 4. SSE：服务起在 127.0.0.1:{port}，收到 id 2 后断开 ===")
        frames, ids = read_stream(port, stop_after_id=2)
        show_frames(frames)
        print(f"  客户端断开，记下 Last-Event-ID = {ids[-1]}")

        print("\n=== 5. 带 Last-Event-ID: 2 重连：只补后面的 ===")
        frames, ids = read_stream(port, last_id=2)
        show_frames(frames)
        print(f"  重连收到的 id：{ids}")

        print("\n=== 6. 对照：不带 Last-Event-ID 会从头重放 ===")
        _, replay_ids = read_stream(port)
        print(f"  收到 id 序列：{replay_ids}")
        print(f"  带 id 只补 {len(ids)} 条，不带 id 从头来 {len(replay_ids)} 条")

        print("\n=== 7. 生成中途失败：错误帧发在断开之前 ===")
        frames, _ = read_stream(port, fail=True)
        show_frames(frames)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
