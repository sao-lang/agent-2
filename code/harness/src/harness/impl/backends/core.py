"""沙箱与其余后端的内存实现（SPEC M12）。

沙箱只提供两种：`FakeSandbox`（剧本，测试用）与 `LocalSandbox`（argv 白名单，
默认关闭网络）。**`exec` 只收 argv 列表**，不给 shell 解析留口子。
"""

from __future__ import annotations

import asyncio
import hashlib
import shlex
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from harness.contracts.types import (
    ApprovalRequest,
    ArtifactMeta,
    ArtifactRef,
    Decision,
    Document,
    ExecResult,
    Limits,
    Namespace,
    Recalled,
    Stat,
)


# ------------------------------------------------------------------ 沙箱


class FakeSandbox:
    """剧本沙箱：记录每次 argv，按预设返回。用于离线测试与干跑。"""

    def __init__(self, script: dict[str, ExecResult] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, ...]] = []
        self.killed: list[str] = []

    async def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str = "/work",
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        limits: Limits | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult:
        key = " ".join(argv)
        self.calls.append(tuple(argv))
        return self.script.get(key, ExecResult(exit=0, stdout=f"fake:{key}"))

    async def kill(self, exec_id: str) -> None:
        self.killed.append(exec_id)


class LocalSandbox:
    """本地进程沙箱：只允许白名单可执行文件，禁网络（尽力而为），有超时与输出上限。"""

    def __init__(self, *, allow: Sequence[str] = (), default_limits: Limits | None = None) -> None:
        self.allow = set(allow)
        self.default_limits = default_limits or Limits()
        self._running: dict[str, asyncio.subprocess.Process] = {}

    def _check(self, argv: Sequence[str], limits: Limits) -> None:
        if not argv:
            raise PermissionError("argv 不能为空")
        if self.allow and argv[0] not in self.allow:
            raise PermissionError(f"可执行文件不在白名单：{argv[0]}")
        if limits.network:
            raise PermissionError("本地沙箱不支持网络访问")

    async def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str = "/work",
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        limits: Limits | None = None,
        timeout_s: float | None = None,
    ) -> ExecResult:
        limits = limits or self.default_limits
        self._check(argv, limits)
        timeout = timeout_s or limits.wall_s
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=dict(env or {}),
            stdin=asyncio.subprocess.PIPE if stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._running[str(proc.pid)] = proc
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
            truncated = len(out) > limits.output_bytes
            return ExecResult(
                exit=proc.returncode or 0,
                stdout=out[: limits.output_bytes].decode("utf-8", "replace"),
                stderr=err[: limits.output_bytes].decode("utf-8", "replace"),
                truncated=truncated,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ExecResult(exit=-1, timed_out=True, stderr="timeout")
        finally:
            self._running.pop(str(proc.pid), None)

    async def kill(self, exec_id: str) -> None:
        proc = self._running.pop(exec_id, None)
        if proc is not None and proc.returncode is None:
            proc.kill()

    @staticmethod
    def split(command: str) -> list[str]:
        """把字符串命令拆成 argv（**调用方不得把结果再交给 shell**）。"""
        return shlex.split(command)


# ------------------------------------------------------------------ 工件


class MemoryArtifactStore:
    """只存引用、内容不进 State（SPEC M7.4）。"""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._meta: dict[str, ArtifactMeta] = {}

    async def put(self, name: str, data: Any) -> ArtifactRef:
        if hasattr(data, "__aiter__"):
            chunks = [chunk async for chunk in data]
            raw = b"".join(chunks)
        else:
            raw = data if isinstance(data, bytes) else bytes(data)
        digest = hashlib.sha256(raw).hexdigest()[:16]
        uri = f"artifact://{digest}/{name}"
        ref = ArtifactRef(uri=uri, bytes=len(raw), sha256=digest, content_type="application/octet-stream")
        self._blobs[uri] = raw
        self._meta[uri] = ArtifactMeta(ref=ref, created_at=time.time())
        return ref

    async def get(self, ref: ArtifactRef) -> bytes:
        if ref.uri not in self._blobs:
            raise FileNotFoundError(ref.uri)
        return self._blobs[ref.uri]

    async def stat(self, ref: ArtifactRef) -> ArtifactMeta:
        if ref.uri not in self._meta:
            raise FileNotFoundError(ref.uri)
        return self._meta[ref.uri]


# ------------------------------------------------------------------ 密钥


class EnvSecretBroker:
    """从环境变量取；**不回显值**（只暴露名字）。"""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        import os

        self._env = dict(env if env is not None else os.environ)

    async def get(self, name: str) -> str:
        if name not in self._env:
            raise KeyError(f"缺少密钥：{name}")
        return self._env[name]

    async def list(self) -> list[str]:
        return sorted(k for k in self._env if k.isupper())


class MemorySecretBroker:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})

    async def get(self, name: str) -> str:
        if name not in self._values:
            raise KeyError(f"缺少密钥：{name}")
        return self._values[name]

    async def list(self) -> list[str]:
        return sorted(self._values)


# ------------------------------------------------------------------ 索引


class MemoryIndex:
    """最小检索：字符二元组重合打分。**过滤下推**（先按 filters 筛，再打分）。"""

    def __init__(self) -> None:
        self._rows: dict[tuple, list[Document]] = {}

    @staticmethod
    def _key(ns: Namespace) -> tuple:
        return ns.as_tuple()

    async def upsert(self, ns: Namespace, docs: Sequence[Document]) -> int:
        bucket = self._rows.setdefault(self._key(ns), [])
        index = {d.id: i for i, d in enumerate(bucket)}
        for doc in docs:
            if doc.id in index:
                bucket[index[doc.id]] = doc
            else:
                bucket.append(doc)
        return len(docs)

    async def search(
        self,
        ns: Namespace,
        query: Any,
        *,
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[Recalled]:
        rows = self._rows.get(self._key(ns), [])
        if filters:
            rows = [
                d
                for d in rows
                if all(str(d.metadata.get(key)) == str(val) for key, val in filters.items())
            ]
        q = "".join(ch for ch in str(query).lower() if not ch.isspace())
        grams = {q[i : i + 2] for i in range(max(0, len(q) - 1))}
        scored: list[Recalled] = []
        for doc in rows:
            text = "".join(ch for ch in doc.text.lower() if not ch.isspace())
            dg = {text[i : i + 2] for i in range(max(0, len(text) - 1))}
            score = len(grams & dg) / len(grams) if grams else 0.0
            if score > 0:
                scored.append(
                    Recalled(text=doc.text, score=score, source=f"doc:{doc.id}", id=doc.id)
                )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]


# ------------------------------------------------------------------ 队列


class MemoryQueue:
    """至少一次投递；`dedup_key` 相同的入队只保留一条（SPEC M12.2）。"""

    def __init__(self) -> None:
        self._items: list[Any] = []
        self._seen: set[str] = set()
        self._inflight: dict[str, Any] = {}

    async def enqueue(self, job: Any, *, delay_s: float = 0) -> str:
        key = getattr(job, "dedup_key", "") or getattr(job, "id", "")
        if key and key in self._seen:
            return key
        if key:
            self._seen.add(key)
        self._items.append(job)
        return key or str(len(self._items))

    async def dequeue(self, *, timeout_s: float = 0) -> Any:
        if not self._items:
            if timeout_s:
                await asyncio.sleep(min(timeout_s, 0.01))
            return None
        job = self._items.pop(0)
        self._inflight[getattr(job, "id", "")] = job
        return job

    async def ack(self, job_id: str) -> None:
        self._inflight.pop(job_id, None)


# ------------------------------------------------------------------ 审批


class MemoryApprovalChannel:
    """进程内审批：request 返回 id，wait 阻塞直到 respond 或超时。"""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, Decision] = {}
        self._waiters: dict[str, asyncio.Event] = {}
        self._seq = 0

    async def request(self, req: ApprovalRequest) -> str:
        self._seq += 1
        approval_id = req.id or f"ap{self._seq}"
        self._pending[approval_id] = replace(req, id=approval_id)
        self._waiters[approval_id] = asyncio.Event()
        return approval_id

    async def wait(self, approval_id: str, *, timeout_s: float | None = None) -> Decision | None:
        event = self._waiters.get(approval_id)
        if event is None:
            return None
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        return self._decisions.get(approval_id)

    async def respond(self, approval_id: str, decision: Decision) -> None:
        if approval_id not in self._waiters:
            raise KeyError(f"未知审批：{approval_id}")
        self._decisions[approval_id] = decision
        self._waiters[approval_id].set()

    def pending(self) -> dict[str, ApprovalRequest]:
        return dict(self._pending)


class CallbackApprovalChannel:
    """把请求交给外部回调（UI / IM 卡片），决策由调用方回填。"""

    def __init__(self, on_request: Any) -> None:
        self._on_request = on_request
        self._decisions: dict[str, Decision] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._seq = 0

    async def request(self, req: ApprovalRequest) -> str:
        self._seq += 1
        approval_id = req.id or f"ap{self._seq}"
        self._events[approval_id] = asyncio.Event()
        result = self._on_request(replace(req, id=approval_id))
        if hasattr(result, "__await__"):
            await result
        return approval_id

    async def wait(self, approval_id: str, *, timeout_s: float | None = None) -> Decision | None:
        event = self._events.get(approval_id)
        if event is None:
            return None
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None
        return self._decisions.get(approval_id)

    async def respond(self, approval_id: str, decision: Decision) -> None:
        self._decisions[approval_id] = decision
        if approval_id in self._events:
            self._events[approval_id].set()


# ------------------------------------------------------------------ 时钟


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """可控时钟：回放与测试必须能钉死时间（SPEC M12.2）。"""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._mono = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now += timedelta(seconds=seconds)
        self._mono += seconds


__all__ = [
    "FakeSandbox",
    "LocalSandbox",
    "MemoryArtifactStore",
    "EnvSecretBroker",
    "MemorySecretBroker",
    "MemoryIndex",
    "MemoryQueue",
    "MemoryApprovalChannel",
    "CallbackApprovalChannel",
    "SystemClock",
    "FakeClock",
]
