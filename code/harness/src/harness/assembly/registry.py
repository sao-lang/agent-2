"""配置解析与注册表（SPEC M15.7）：`name[:arg]` 或 dict 两种形态。

未知名一律 `ConfigError` 并列出可用名字——排查成本从这里省。
需要第三方适配器的条目在未安装时给出明确的安装提示，不静默降级。
"""

from __future__ import annotations

import re
from typing import Any, Callable

from harness.contracts.errors import ConfigError

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def parse_spec(spec: Any, *, kind: str) -> tuple[str, str, dict[str, Any]]:
    """拆解配置项 → (name, arg, 额外参数)。

    形态：
        "memory"                  → ("memory", "", {})
        "sqlite:runs.db"          → ("sqlite", "runs.db", {})
        {"kind": "postgres", "dsn": "..."}  → ("postgres", "", {"dsn": "..."})
    """
    if isinstance(spec, dict):
        data = dict(spec)
        if "kind" not in data:
            raise ConfigError(f"{kind} 的 dict 形态必须含 'kind'：{spec!r}")
        name = str(data.pop("kind"))
        arg = str(data.pop("arg", "") or data.pop("dsn", "") or data.pop("path", "") or "")
        if not _NAME_RE.match(name):
            raise ConfigError(f"{kind} 名字非法：{name!r}（应为 [a-z][a-z0-9_]*）")
        return name, arg, data

    if isinstance(spec, str):
        if not spec:
            raise ConfigError(f"{kind} 不能为空字符串")
        name, _, arg = spec.partition(":")
        if not _NAME_RE.match(name):
            raise ConfigError(f"{kind} 名字非法：{name!r}（应为 [a-z][a-z0-9_]*）")
        return name, arg, {}

    raise ConfigError(f"{kind} 只能是字符串或 dict，收到：{type(spec).__name__}")


def resolve(kind: str, spec: Any, table: dict[str, Callable[..., Any]]) -> Any:
    """查表构造；未知 name → ConfigError 并列出可用名字。"""
    name, arg, extra = parse_spec(spec, kind=kind)
    factory = table.get(name)
    if factory is None:
        raise ConfigError(f"未知 {kind}：{name!r}；可用：{sorted(table)}")
    return factory(arg, **extra)


def _adapter(name: str, extra: str) -> Callable[..., Any]:
    def factory(arg: str = "", **kwargs: Any) -> Any:
        raise ConfigError(f"{name} 需要安装适配器：pip install agent-harness[{extra}]")

    return factory


# ------------------------------------------------------------------ 注册表


def _fake_model(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.fakes import FakeModel
    from harness.impl.fakes import answer

    return FakeModel([answer("fake")])


def _memory_checkpoint(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.stores import MemoryCheckpointStore

    return MemoryCheckpointStore()


def _sqlite_checkpoint(arg: str = "", **kwargs: Any) -> Any:
    from harness.parts.durability import SQLiteDurability

    return SQLiteDurability(arg or "harness-runs.db")


def _memory_session(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.stores import MemorySessionStore

    return MemorySessionStore()


def _memory_messages(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.stores import MemoryMessageLog

    return MemoryMessageLog()


def _memory_memory(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.stores import MemoryMemoryStore

    return MemoryMemoryStore()


def _memory_idem(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.stores import MemoryIdempotency

    return MemoryIdempotency()


MODELS: dict[str, Callable[..., Any]] = {
    "fake": _fake_model,
    "openai": _adapter("openai", "openai"),
    "anthropic": _adapter("anthropic", "anthropic"),
    "ollama": _adapter("ollama", "ollama"),
}

STORES: dict[str, Callable[..., Any]] = {
    "memory": _memory_checkpoint,          # 默认；具体用途由槽位决定
    "sqlite": _sqlite_checkpoint,
    "postgres": _adapter("postgres", "postgres"),
    "redis": _adapter("redis", "redis"),
}

STORE_SLOTS: dict[str, dict[str, Callable[..., Any]]] = {
    "durability": {"memory": _memory_checkpoint, "sqlite": _sqlite_checkpoint,
                   "postgres": _adapter("postgres", "postgres")},
    "session": {"memory": _memory_session, "postgres": _adapter("postgres", "postgres")},
    "messages": {"memory": _memory_messages},
    "memory": {"memory": _memory_memory, "postgres": _adapter("postgres", "postgres")},
    "idempotency": {"memory": _memory_idem, "postgres": _adapter("postgres", "postgres")},
}


def _memory_fs(arg: str = "", **kwargs: Any) -> Any:
    from harness.contracts.types import Mount
    from harness.impl.backends import MemoryFileSystem

    return MemoryFileSystem((Mount("/work", None, "rw"),))


def _local_fs(arg: str = "", **kwargs: Any) -> Any:
    from harness.contracts.types import Mount
    from harness.impl.backends import LocalFileSystem

    root = arg or "."
    return LocalFileSystem((Mount("/work", root, "rw"),))


def _fake_sandbox(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import FakeSandbox

    return FakeSandbox()


def _memory_artifacts(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import MemoryArtifactStore

    return MemoryArtifactStore()


def _env_secrets(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import EnvSecretBroker

    return EnvSecretBroker()


def _memory_index(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import MemoryIndex

    return MemoryIndex()


def _memory_queue(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import MemoryQueue

    return MemoryQueue()


def _memory_approval(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import MemoryApprovalChannel

    return MemoryApprovalChannel()


def _system_clock(arg: str = "", **kwargs: Any) -> Any:
    from harness.impl.backends import SystemClock

    return SystemClock()


BACKENDS: dict[str, dict[str, Callable[..., Any]]] = {
    "fs": {"memory": _memory_fs, "local": _local_fs, "s3": _adapter("s3", "s3")},
    "sandbox": {"fake": _fake_sandbox, "local": _fake_sandbox,
                "docker": _adapter("docker", "docker")},
    "artifacts": {"memory": _memory_artifacts, "local": _memory_artifacts,
                  "s3": _adapter("s3", "s3")},
    "secrets": {"env": _env_secrets, "memory": _env_secrets, "vault": _adapter("vault", "vault")},
    "index": {"memory": _memory_index, "qdrant": _adapter("qdrant", "qdrant"),
              "pgvector": _adapter("pgvector", "postgres")},
    "queue": {"memory": _memory_queue, "redis": _adapter("redis", "redis")},
    "approval": {"memory": _memory_approval, "callback": _memory_approval,
                 "http": _adapter("http", "http")},
    "clock": {"system": _system_clock, "fake": _system_clock},
}

GUARDRAILS: dict[str, Callable[..., Any]] = {
    "injection": lambda arg="", **kw: _detector("injection"),
    "pii": lambda arg="", **kw: _detector("pii"),
    "secret_leak": lambda arg="", **kw: _detector("secret_leak"),
}


def _detector(name: str) -> Any:
    from harness.parts.guardrail import builtin_detectors

    return builtin_detectors([name])[0]


# ------------------------------------------------------------------ v3 程序注册表


def _body_factory(name: str) -> Callable[..., Any]:
    """v2 body 策略（``fp.Program.from_spec`` 用）；局部 import 避免装配期成环。"""

    def factory(arg: str = "", **kwargs: Any) -> Any:
        from harness.parts.policy import ReactPolicy, WorkflowPolicy

        if name == "react":
            return ReactPolicy()
        return WorkflowPolicy(steps=list(kwargs.get("steps", ())))

    return factory


#: 具名注册的程序工厂（PROPOSAL §9.2）。``fp.from_spec`` 的白名单改走这里；
#: v3 内置范式由 ``fp.frontends`` 在模块加载时调 ``register_program`` 自注册，
#: 这样新增前端只加一行注册，且 assembly 不依赖 fp（层间不成环）。
PROGRAMS: dict[str, Callable[..., Any]] = {
    "react": _body_factory("react"),
    "workflow": _body_factory("workflow"),
}


def register_program(name: str, factory: Callable[..., Any]) -> None:
    """注册一个具名前端程序；重名直接报错，不静默覆盖。"""
    if name in PROGRAMS:
        raise ConfigError(f"程序名重复注册：{name}")
    PROGRAMS[name] = factory


__all__ = [
    "parse_spec",
    "resolve",
    "MODELS",
    "STORES",
    "STORE_SLOTS",
    "BACKENDS",
    "GUARDRAILS",
    "PROGRAMS",
    "register_program",
]
