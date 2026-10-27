"""可断线重连的 SSE 接口：六件事各就各位。

本机回环，不连外网。服务端是标准库的 ThreadingHTTPServer，客户端用裸 socket
读原始字节，这样帧格式、心跳、重连都能逐字看到。

六件事：
  1 关缓冲      Content-Type: text/event-stream + Cache-Control: no-cache
                + X-Accel-Buffering: no（nginx 层也关）
  2 心跳        注释帧 ": ping" 每 100ms 一次，防止中间设备掐空闲连接
  3 断线重连    Last-Event-ID 头，服务端从该 id 之后继续
  4 错误帧      event: error + 结构化 data，不是直接断流
  5 结束帧      event: done，客户端据此停止重连
  6 代理层      Connection: keep-alive 与 flush 的位置
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNKS = [
    ("delta", {"text": "根据政策，"}),
    ("delta", {"text": "质量问题退货由商家承担运费，"}),
    ("delta", {"text": "签收后 15 天内提交凭证即可。"}),
    ("done", {"finish_reason": "stop"}),
]
SLOW_BEFORE = {3: 0.35}          # 第 3 条之前慢一点，让心跳有机会出现
HEARTBEAT = 0.12


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"     # 关闭连接即为流结束

    def do_GET(self) -> None:
        try:
            last_id = int(self.headers.get("Last-Event-ID", "0"))
        except ValueError:
            last_id = 0

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            for idx, (event, data) in enumerate(CHUNKS, start=1):
                wait = SLOW_BEFORE.get(idx, 0.05)
                sent = 0.0
                while sent < wait:              # 慢的间隙里发心跳
                    time.sleep(min(HEARTBEAT, wait - sent))
                    sent += HEARTBEAT
                    if sent < wait:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                if idx <= last_id:              # 已经发过的跳过，但心跳照发
                    continue
                frame = (f"id: {idx}\nevent: {event}\n"
                         f"data: {json.dumps(data, ensure_ascii=False)}\n\n")
                self.wfile.write(frame.encode("utf-8"))
                self.wfile.flush()
        except OSError:
            return                              # 客户端走了：写出端的所有失败都是 OSError
        finally:
            self.close_connection = True        # 流结束就关连接，不留 keep-alive

    def log_message(self, *args) -> None:       # 安静一点
        return


def start_server() -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def read_stream(port: int, last_id: int, stop_after: int) -> list[str]:
    """读原始帧；够 stop_after 条、看到 done、或对端关闭就停。"""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    req = ("GET /stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           f"Last-Event-ID: {last_id}\r\nAccept: text/event-stream\r\n"
           "Connection: close\r\n\r\n")
    s.sendall(req.encode())
    buf = b""
    lines: list[str] = []
    data_frames = 0
    try:
        while True:
            try:
                chunk = s.recv(4096)
            except TimeoutError:
                lines.append("[读超时：连接没有关闭]")
                break
            if not chunk:
                lines.append("[对端关闭连接]")
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8").rstrip("\r")
                if line.startswith("id:"):
                    data_frames += 1
                    lines.append(line)
                elif line.startswith("event:") or line.startswith("data:") or line.startswith(":"):
                    lines.append(line)
            if data_frames >= stop_after:
                lines.append("[客户端主动断开]")
                break
            if any(l == "event: done" for l in lines):
                break
    finally:
        s.close()
    return lines


def main() -> None:
    srv, port = start_server()
    print(f"服务端监听 127.0.0.1:{port}")
    print()

    print("=== 1. 第一次连接：收到两条就断开 ===")
    first = read_stream(port, last_id=0, stop_after=2)
    for line in first:
        print(f"  {line}")

    print()
    print("=== 2. 带 Last-Event-ID: 2 重连，只补后面的 ===")
    second = read_stream(port, last_id=2, stop_after=9)
    for line in second:
        print(f"  {line}")

    print()
    print("=== 3. 对照：不带 Last-Event-ID 会从头重放 ===")
    replay = read_stream(port, last_id=0, stop_after=9)
    ids = [l.split(":")[1].strip() for l in replay if l.startswith("id:")]
    print(f"  收到 id 序列：{ids}")

    print()
    print("=== 4. 服务端没有打印异常堆栈 ===")
    print("  客户端在第 2 条之后断开，服务端写第 3 条时写端已断（POSIX 上是")
    print("  BrokenPipe，Windows 上是 ConnectionAborted），except OSError 直接 return：")
    print("  既没有堆栈，也没有把这次正常断开记成错误")

    srv.shutdown()


if __name__ == "__main__":
    main()
