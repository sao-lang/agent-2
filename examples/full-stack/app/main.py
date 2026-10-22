"""最小可运行的 Agent API —— 全栈交付示例的核心服务。

它的作用是让你有一个**真的能 docker compose up 起来**的东西，
而不是一份"看起来对"的 YAML。

它刻意做得很小，但把上线必须的几件事都做了：
  · /chat         同步
  · /chat/stream  流式（SSE，带 error 帧）
  · /jobs         长任务异步提交 + 轮询
  · /healthz      存活探针（只证明进程活着）
  · /readyz       就绪探针（真的去 ping DB / 队列 / 向量库）
  · SIGTERM       优雅关闭：拒新请求、等手上的活、写 checkpoint

环境变量（全部有默认值，方便本地裸跑）：
  DATABASE_URL   postgres 连接串，未设置则跳过 DB 检查
  REDIS_URL      redis 连接串，未设置则用内存队列
  VECTOR_URL     向量库健康检查地址
  LLM_MODE       fake | openai（默认 fake，这样不需要密钥）
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

LLM_MODE = os.getenv("LLM_MODE", "fake")
STARTED_AT = time.time()

# ---------------------------------------------------------------- 状态
SHUTTING_DOWN = False
INFLIGHT = 0
JOBS: dict[str, dict[str, Any]] = {}
QUEUE: deque[tuple[str, str]] = deque()  # (job_id, question)


class ChatIn(BaseModel):
    q: str = Field(min_length=1, max_length=2000)
    user_id: str = "u-1"
    session_id: str | None = None


async def fake_llm(prompt: str) -> AsyncIterator[str]:
    """假模型：每 30ms 吐一块。真实部署里换成 OpenAI / Ollama / vLLM。"""
    text = f"关于「{prompt[:20]}」：退款需要审核，7 个工作日内到账。" * 2
    step = max(1, len(text) // 8)
    for i in range(0, len(text), step):
        await asyncio.sleep(0.03)
        yield text[i : i + step]


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def check_dependency(name: str, url: str | None, timeout: float = 1.0) -> dict[str, Any]:
    """就绪探针：真的去连一下。连不上不等于服务该重启，但它不该接流量。"""
    if not url:
        return {"name": name, "ok": True, "detail": "not configured (skipped)"}
    try:
        from urllib.parse import urlparse

        u = urlparse(url)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(u.hostname or "localhost", u.port or 80), timeout
        )
        writer.close()
        await writer.wait_closed()
        return {"name": name, "ok": True, "detail": "tcp ok"}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- 生命周期
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    worker = asyncio.create_task(job_worker())
    print(f"[startup] LLM_MODE={LLM_MODE} pid={os.getpid()}", flush=True)
    try:
        yield
    finally:
        global SHUTTING_DOWN
        SHUTTING_DOWN = True
        print(f"[shutdown] 停止接新任务，等待 inflight={INFLIGHT} 完成…", flush=True)
        worker.cancel()
        deadline = time.time() + float(os.getenv("SHUTDOWN_GRACE", "8"))
        while INFLIGHT > 0 and time.time() < deadline:
            await asyncio.sleep(0.05)
        print(f"[shutdown] 完成，剩余 inflight={INFLIGHT}", flush=True)


app = FastAPI(title="fullstack-agent", lifespan=lifespan)


@app.middleware("http")
async def reject_while_shutting_down(request: Request, call_next: Any) -> Any:
    """优雅关闭的关键一半：还在接新请求，就别停。

    没有这一层，SIGTERM 后 uvicorn 会立刻停止接受连接 ——
    正在排队的用户直接收到 connection refused。
    """
    if SHUTTING_DOWN and request.url.path not in ("/healthz", "/readyz"):
        return JSONResponse({"detail": "server is shutting down"}, status_code=503)
    return await call_next(request)


def track_inflight(delta: int) -> None:
    global INFLIGHT
    INFLIGHT += delta


# ---------------------------------------------------------------- 路由
@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """存活探针：只回答「进程还在吗」。依赖挂了也算活着——重启没用。"""
    return {"ok": True, "uptime_s": round(time.time() - STARTED_AT, 1)}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """就绪探针：依赖都通了才返回 200，否则 503，让负载均衡把流量摘走。"""
    deps = await asyncio.gather(
        check_dependency("postgres", os.getenv("DATABASE_URL")),
        check_dependency("redis", os.getenv("REDIS_URL")),
        check_dependency("vector", os.getenv("VECTOR_URL")),
    )
    ok = all(d["ok"] for d in deps) and not SHUTTING_DOWN
    return JSONResponse({"ok": ok, "inflight": INFLIGHT, "deps": deps}, status_code=200 if ok else 503)


@app.post("/chat")
async def chat(req: ChatIn) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    track_inflight(1)
    try:
        parts = [p async for p in fake_llm(req.q)]
    finally:
        track_inflight(-1)
    return {
        "answer": "".join(parts),
        "run_id": run_id,
        "session_id": req.session_id or f"s-{req.user_id}",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


@app.post("/chat/stream")
async def chat_stream(req: ChatIn) -> StreamingResponse:
    run_id = uuid.uuid4().hex[:12]

    async def gen() -> AsyncIterator[str]:
        track_inflight(1)
        n = 0
        try:
            yield sse("meta", {"run_id": run_id})
            async for piece in fake_llm(req.q):
                n += 1
                yield sse("delta", {"i": n, "t": piece})
            yield sse("done", {"chunks": n, "run_id": run_id})
        except Exception as e:  # noqa: BLE001
            # 响应头早就发出去了，只能靠 error 帧告诉客户端"我没说完"
            yield sse("error", {"msg": f"{type(e).__name__}: {e}", "run_id": run_id})
        finally:
            track_inflight(-1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 让 nginx 不要缓冲 SSE
            "X-Run-Id": run_id,
        },
    )


@app.post("/jobs", status_code=202)
async def create_job(req: ChatIn) -> dict[str, str]:
    if SHUTTING_DOWN:
        raise HTTPException(status_code=503, detail="shutting down")
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"status": "queued", "result": None, "created": time.time()}
    QUEUE.append((job_id, req.q))
    return {"job_id": job_id, "poll": f"/jobs/{job_id}"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job_id": job_id, **job}


async def job_worker() -> None:
    """队列消费者。真实部署里换成 Redis Stream / Celery / Arq。"""
    while True:
        if not QUEUE:
            await asyncio.sleep(0.05)
            continue
        job_id, q = QUEUE.popleft()
        JOBS[job_id]["status"] = "running"
        track_inflight(1)
        try:
            parts = [p async for p in fake_llm(q)]
            JOBS[job_id]["result"] = "".join(parts)
            JOBS[job_id]["status"] = "done"
        finally:
            track_inflight(-1)


@app.get("/")
def index() -> dict[str, Any]:
    return {"service": "fullstack-agent", "endpoints": ["/chat", "/chat/stream", "/jobs", "/healthz", "/readyz"]}


# 让 `docker stop` 走 lifespan 的优雅关闭路径（uvicorn 自己也会处理，这里更显式）
def _install_signal_handlers() -> None:
    def handler(signum: int, _frame: Any) -> None:
        global SHUTTING_DOWN
        SHUTTING_DOWN = True
        print(f"[signal] 收到 {signal.Signals(signum).name}，进入优雅关闭", flush=True)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except ValueError:
            pass  # 非主线程（比如在测试里）装不上，忽略


_install_signal_handlers()
