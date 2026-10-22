"""第 41 章 step1：把一个 Agent 暴露成 API —— 同步 / 异步 / 流式，以及四种"看起来能用"的错误写法。

运行：
    python code/ch41_integration/step1_api.py

不依赖网络、不依赖真实模型：用一个「假模型」按块吐字，
这样你看到的所有数字（TTFT、状态码、取消行为）都是真实测出来的。
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

app = FastAPI(title="agent-api-demo")


# ---------------------------------------------------------------- 假模型
def fake_llm(prompt: str, chunks: int = 6, delay: float = 0.02) -> Iterator[str]:
    """模拟流式模型：每 delay 秒吐一块。块数固定，方便对比。"""
    text = "退款需要审核，7 个工作日内到账。" * 3
    step = max(1, len(text) // chunks)
    for i in range(0, len(text), step):
        time.sleep(delay)
        yield text[i : i + step]


# ---------------------------------------------------------------- 请求/响应模型
class ChatIn(BaseModel):
    q: str = Field(min_length=1, max_length=2000)
    user_id: str = "u-1"


class ChatOut(BaseModel):
    answer: str
    run_id: str
    latency_ms: float


# ---------------------------------------------------------------- ① 同步接口
@app.post("/chat", response_model=ChatOut)
def chat(req: ChatIn) -> ChatOut:
    t0 = time.perf_counter()
    answer = "".join(fake_llm(req.q, chunks=3))
    return ChatOut(
        answer=answer,
        run_id=f"run-{int(t0 * 1000)}",
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
    )


# ---------------------------------------------------------------- ② 流式接口（SSE）
def sse(event: str, data: dict[str, Any]) -> str:
    """SSE 的一帧：event 行 + data 行 + 空行。

    data 必须是**单行**——换行会让客户端把后半截当成新字段。
    含换行的内容要 json.dumps 成一行（ensure_ascii=False 保留中文）。
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class GuardedStream(StreamingResponse):
    """关键补丁：流式生成器里抛异常时，Starlette 会**原样向上抛**。

    在真实 uvicorn 下表现是"连接被掐断、客户端只收到半个响应"；
    在 TestClient 里直接变成整个请求失败（连测试都跑不过）。

    所以流式接口必须自己兜住异常，转成一帧 error 事件——这是**业务语义**，
    不是框架能替你决定的（HTTP 状态码早就 200 发出去了）。
    """

    async def stream_response(self, send: Any) -> None:
        try:
            await super().stream_response(send)
        except Exception as e:  # noqa: BLE001
            await send(
                {
                    "type": "http.response.body",
                    "body": sse("error", {"msg": f"{type(e).__name__}: {e}"}).encode(),
                    "more_body": False,
                }
            )


@app.post("/chat/stream")
def chat_stream(req: ChatIn) -> StreamingResponse:
    def gen() -> Iterator[str]:
        t0 = time.perf_counter()
        n = 0
        try:
            for piece in fake_llm(req.q):
                n += 1
                yield sse("delta", {"i": n, "t": piece})
        except Exception as e:  # noqa: BLE001
            yield sse("error", {"msg": f"{type(e).__name__}: {e}", "after_chunks": n})
            return
        yield sse("done", {"chunks": n, "total_ms": round((time.perf_counter() - t0) * 1000, 1)})

    return GuardedStream(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- ③ 异步任务接口（202 + 轮询）
JOBS: dict[str, dict[str, Any]] = {}


def run_job(job_id: str, q: str) -> None:
    JOBS[job_id]["status"] = "running"
    try:
        JOBS[job_id]["result"] = "".join(fake_llm(q, chunks=4))
        JOBS[job_id]["status"] = "done"
    except Exception as e:  # noqa: BLE001
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = f"{type(e).__name__}: {e}"


@app.post("/jobs", status_code=202)
def create_job(req: ChatIn, bg: BackgroundTasks) -> dict[str, str]:
    job_id = f"job-{len(JOBS) + 1}"
    JOBS[job_id] = {"status": "queued", "result": None}
    bg.add_task(run_job, job_id, req.q)
    return {"job_id": job_id, "poll": f"/jobs/{job_id}"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job_id": job_id, **job}


# ---------------------------------------------------------------- 演示
def demo_sync(c: TestClient) -> None:
    print("① 同步接口 /chat")
    r = c.post("/chat", json={"q": "退款多久到账"})
    print(f"   状态码 {r.status_code}")
    body = r.json()
    print(f"   返回字段 {sorted(body)}")
    print(f"   端到端 {body['latency_ms']} ms —— 用户在这段时间里屏幕是空白的")
    print()


def demo_stream(c: TestClient) -> None:
    print("② 流式接口 /chat/stream（SSE）")
    t0 = time.perf_counter()
    ttft: float | None = None
    chunks = 0
    with c.stream("POST", "/chat/stream", json={"q": "退款多久到账"}) as r:
        print(f"   状态码 {r.status_code}  content-type {r.headers['content-type']}")
        for line in r.iter_lines():
            if not line:
                continue
            if line.startswith("event: delta"):
                if ttft is None:
                    ttft = (time.perf_counter() - t0) * 1000
                chunks += 1
            elif line.startswith("event: done"):
                total = (time.perf_counter() - t0) * 1000
                assert ttft is not None
                print(f"   收到 {chunks} 个 delta 块")
                print(f"   TTFT（首字）{ttft:.0f} ms  vs  总耗时 {total:.0f} ms")
                print(f"   用户感知提升 {(1 - ttft / total) * 100:.0f}%，但机器总工作量一模一样")
    print()


def demo_async_job(c: TestClient) -> None:
    print("③ 异步任务接口 /jobs（长任务用这个，不是流式）")
    r = c.post("/jobs", json={"q": "把 200 篇文档建成索引"})
    print(f"   POST /jobs → {r.status_code}（202 Accepted 而不是 200）")
    job_id = r.json()["job_id"]
    print(f"   job_id = {job_id}")
    j: dict[str, Any] = {}
    for _ in range(20):
        j = c.get(f"/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    print(f"   轮询后状态 = {j['status']}，结果长度 = {len(j['result'] or '')}")
    print()


def demo_failures(c: TestClient) -> None:
    print("④ 四种「看起来能用」的错误写法")

    r = c.post("/chat", json={"q": ""})
    print(f"   a) 空 q → 状态码 {r.status_code}（这是 pydantic 拦下来的，不是你的代码拦的）")
    r = c.get("/jobs/not-exist")
    print(f"      查不存在的 job → {r.status_code}，body 里有 detail 字段")

    def broken() -> Iterator[str]:
        yield sse("delta", {"t": "前半句"})
        raise RuntimeError("模型中途 500")

    @app.post("/chat/stream-broken")
    def broken_stream() -> StreamingResponse:
        # 故意用原生 StreamingResponse：这就是"没兜住"的版本
        return StreamingResponse(broken(), media_type="text/event-stream")

    @app.post("/chat/stream-guarded")
    def guarded_stream() -> StreamingResponse:
        return GuardedStream(broken(), media_type="text/event-stream")

    with c.stream("POST", "/chat/stream-guarded") as r:
        print(f"   b) 流式中途抛异常 → 状态码仍然是 {r.status_code}（响应头早发出去了，改不了！）")
        frames = [ln for ln in r.iter_lines() if ln.startswith("event:")]
    print(f"      有 GuardedStream：客户端收到 {frames} —— 明确知道「后半截没了」")

    try:
        with c.stream("POST", "/chat/stream-broken") as r:
            frames2 = [ln for ln in r.iter_lines() if ln.startswith("event:")]
        print(f"      没有 GuardedStream：只在 TestClient 里会炸（{len(frames2)} 帧）")
    except RuntimeError as e:
        print(f"      没有 GuardedStream：客户端只看到半截，然后连接断掉 —— {e}")

    print("   c) data 里直接放换行：")
    bad = "event: delta\ndata: 第一行\n第二行\n\n"
    for ln in bad.split("\n\n")[0].split("\n"):
        print(f"      | {ln}")
    print("      → 客户端认为「第二行」是一个新字段名，直接解析失败或静默丢弃")

    print("   d) 同步接口在 async def 里 time.sleep()：整个进程被独占，")
    print("      并发 10 个请求耗时 ≈ 串行 10 次（见 step3 的并发压测）")
    print()


def demo_contract(c: TestClient) -> None:
    print("⑤ 契约检查：把「接口必须满足什么」写成断言")
    r = c.post("/chat", json={"q": "x"})
    checks = [
        ("状态码 200", r.status_code == 200),
        ("含 answer 字段", "answer" in r.json()),
        ("含 run_id（能拿它去查 trace）", "run_id" in r.json()),
        ("响应体是 JSON 而不是纯文本", r.headers["content-type"].startswith("application/json")),
    ]
    for name, ok in checks:
        print(f"   {'OK ' if ok else 'BAD'} {name}")
    r2 = c.post("/chat", json={"q": ""})
    print(f"   {'OK ' if r2.status_code == 422 else 'BAD'} 空输入被拦成 422（不是 500）")
    print()


def main() -> None:
    c = TestClient(app)
    demo_sync(c)
    demo_stream(c)
    demo_async_job(c)
    demo_failures(c)
    demo_contract(c)


if __name__ == "__main__":
    main()
