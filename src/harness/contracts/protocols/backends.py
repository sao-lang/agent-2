"""后端协议（SPEC M12.1）：所有「外部世界」的可替换边界。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Mapping, Protocol, Sequence, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from harness.contracts.events import RunEvent
    from harness.contracts.types import (
        ApprovalRequest,
        ArtifactMeta,
        ArtifactRef,
        Decision,
        Document,
        ExecResult,
        Goal,
        Limits,
        Match,
        Mount,
        Namespace,
        Recalled,
        Stat,
    )


@runtime_checkable
class FileSystem(Protocol):
    """虚拟路径 + 挂载表；`resolve()` 是唯一 jail 点（SPEC M12.3）。"""

    mounts: tuple["Mount", ...]

    async def read(self, path: str) -> bytes: ...

    async def write(self, path: str, data: bytes) -> None: ...

    async def edit(self, path: str, old: str, new: str, *, count: int = 1) -> int: ...

    async def glob(self, pattern: str) -> list[str]: ...

    async def grep(self, pattern: str, *, glob: str = "**/*", max_hits: int = 200) -> list["Match"]: ...

    async def stat(self, path: str) -> "Stat": ...


@runtime_checkable
class Sandbox(Protocol):
    """执行边界。`exec` 只收 argv 列表，不给 shell 解析留口子（SPEC M12.4）。"""

    async def exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str = "/work",
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        limits: "Limits | None" = None,
        timeout_s: float | None = None,
    ) -> "ExecResult": ...

    async def kill(self, exec_id: str) -> None: ...


@runtime_checkable
class ArtifactStore(Protocol):
    async def put(self, name: str, data: bytes | AsyncIterator[bytes]) -> "ArtifactRef": ...

    async def get(self, ref: "ArtifactRef") -> bytes: ...

    async def stat(self, ref: "ArtifactRef") -> "ArtifactMeta": ...


@runtime_checkable
class SecretBroker(Protocol):
    """只按名取；永不明文进 prompt（SPEC M12.2）。"""

    async def get(self, name: str) -> str: ...

    async def list(self) -> list[str]: ...


@runtime_checkable
class IndexBackend(Protocol):
    """过滤必须下推到后端，否则租户泄漏（SPEC M12.2）。"""

    async def search(
        self,
        ns: "Namespace",
        query: Any,
        *,
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list["Recalled"]: ...

    async def upsert(self, ns: "Namespace", docs: Sequence["Document"]) -> int: ...


@runtime_checkable
class Knowledge(Protocol):
    """既有形状，保留兼容。"""

    async def retrieve(
        self, query: str, *, k: int, filters: dict[str, Any] | None = None
    ) -> list["Recalled"]: ...


@runtime_checkable
class Skills(Protocol):
    """给流程不给能力；三段式渐进披露（SPEC M7.3）。"""

    def catalog(self) -> list[Any]: ...

    async def load(self, name: str) -> Any: ...

    async def resource(self, name: str, path: str) -> str: ...


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: "RunEvent") -> None: ...


@runtime_checkable
class Queue(Protocol):
    async def enqueue(self, job: Any, *, delay_s: float = 0) -> str: ...

    async def dequeue(self, *, timeout_s: float) -> Any: ...

    async def ack(self, job_id: str) -> None: ...


@runtime_checkable
class ApprovalChannel(Protocol):
    async def request(self, req: "ApprovalRequest") -> str: ...

    async def wait(self, approval_id: str, *, timeout_s: float) -> "Decision | None": ...

    async def respond(self, approval_id: str, decision: "Decision") -> None: ...


@runtime_checkable
class Clock(Protocol):
    """可注入时间，测试与回放必须能控制（SPEC M12.2）。"""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


__all__ = [
    "FileSystem",
    "Sandbox",
    "ArtifactStore",
    "SecretBroker",
    "IndexBackend",
    "Knowledge",
    "Skills",
    "EventSink",
    "Queue",
    "ApprovalChannel",
    "Clock",
]
