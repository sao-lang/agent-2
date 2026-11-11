"""虚拟路径与挂载表（SPEC M12.3）。

**唯一的 jail 点**：所有 `FileSystem` 实现都必须经过 `resolve()`，禁止各自拼路径。
越界、只读写入、符号链接逃逸都在这里收口。
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from harness.contracts.types import Mount


class PathDenied(PermissionError):
    """越界或只读违规。拒绝即拒绝，不做"尽量满足"。"""


@dataclass(frozen=True)
class Resolved:
    """解析结果：虚拟路径 + 命中的挂载 + 宿主路径（内存实现时为 None）。"""

    virtual: str
    mount: Mount
    real: Path | None = None
    relative: str = ""

    @property
    def writable(self) -> bool:
        return self.mount.mode == "rw"


def _normalize(path: str) -> str:
    if not path.startswith("/"):
        raise PathDenied(f"必须是绝对虚拟路径：{path!r}")
    # posixpath.normpath 会把 ".." 折掉；折完之后仍以 "/" 开头说明没逃出去
    norm = posixpath.normpath(path)
    if not norm.startswith("/"):
        raise PathDenied(f"路径越界：{path!r}")
    return norm


def resolve(mounts: Sequence[Mount], path: str) -> Resolved:
    """规范化 → 最长匹配挂载 → 校验越界与只读。"""
    virtual = _normalize(path)

    best: Mount | None = None
    for mount in mounts:
        target = _normalize(mount.target).rstrip("/") or "/"
        if virtual == target or virtual.startswith(target + "/"):
            if best is None or len(target) > len(best.target.rstrip("/")):
                best = mount
    if best is None:
        raise PathDenied(f"没有挂载点覆盖：{virtual}")

    target = _normalize(best.target).rstrip("/") or "/"
    relative = virtual[len(target) :].lstrip("/")

    real: Path | None = None
    if best.source:
        root = Path(best.source).resolve()
        candidate = (root / relative).resolve() if relative else root
        # 符号链接逃逸检查：真实路径必须仍在挂载根之内
        try:
            candidate.relative_to(root)
        except ValueError as exc:  # pragma: no cover - 平台相关
            raise PathDenied(f"符号链接逃逸：{virtual} -> {candidate}") from exc
        real = candidate

    return Resolved(virtual=virtual, mount=best, real=real, relative=relative)


def require_writable(resolved: Resolved) -> None:
    if not resolved.writable:
        raise PathDenied(f"挂载点为只读：{resolved.mount.target}")


__all__ = ["PathDenied", "Resolved", "resolve", "require_writable"]
