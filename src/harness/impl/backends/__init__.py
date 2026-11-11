"""后端实现集合（SPEC M12）：真实实现与内存/本地实现；测试替身在 tests/support.py。"""

from harness.impl.backends.core import (
    CallbackApprovalChannel,
    EnvSecretBroker,
    LocalSandbox,
    LocalArtifactStore,
    MemoryApprovalChannel,
    MemoryArtifactStore,
    MemoryIndex,
    MemoryQueue,
    MemorySecretBroker,
    SystemClock,
)
from harness.impl.backends.fs import LocalFileSystem, MemoryFileSystem
from harness.impl.backends.paths import PathDenied, Resolved, require_writable, resolve

__all__ = [
    "PathDenied",
    "Resolved",
    "resolve",
    "require_writable",
    "MemoryFileSystem",
    "LocalFileSystem",
    "LocalSandbox",
    "MemoryArtifactStore",
    "LocalArtifactStore",
    "EnvSecretBroker",
    "MemorySecretBroker",
    "MemoryIndex",
    "MemoryQueue",
    "MemoryApprovalChannel",
    "CallbackApprovalChannel",
    "SystemClock",
]
