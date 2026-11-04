"""文件系统实现（SPEC M12.1 / M12.3）。

两个实现共用 `resolve()`：内存版用于测试与演示，本地版用于真实落地。
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from pathlib import Path
from typing import Sequence

from harness.contracts.types import Match, Mount, Stat
from harness.impl.backends.paths import PathDenied, require_writable, resolve


class MemoryFileSystem:
    """纯内存挂载：`source=None`，内容存在 dict 里。"""

    def __init__(self, mounts: Sequence[Mount] | None = None) -> None:
        self.mounts = tuple(mounts or (Mount("/work", None, "rw"),))
        self._files: dict[str, bytes] = {}
        self._mtime: dict[str, float] = {}

    # -- 内部 --
    def _get(self, path: str, *, write: bool = False) -> str:
        res = resolve(self.mounts, path)
        if write:
            require_writable(res)
        return res.virtual

    # -- 协议 --
    async def read(self, path: str) -> bytes:
        key = self._get(path)
        if key not in self._files:
            raise FileNotFoundError(key)
        return self._files[key]

    async def write(self, path: str, data: bytes) -> None:
        key = self._get(path, write=True)
        self._files[key] = data
        self._mtime[key] = float(len(self._files))

    async def edit(self, path: str, old: str, new: str, *, count: int = 1) -> int:
        key = self._get(path, write=True)
        text = self._files.get(key, b"").decode("utf-8", "replace")
        if old not in text:
            raise ValueError(f"未找到待替换文本：{old!r}")
        replaced = text.replace(old, new, count)
        hits = 1 if count == 1 else text.count(old)
        self._files[key] = replaced.encode("utf-8")
        return hits

    async def glob(self, pattern: str) -> list[str]:
        # pattern 相对某个挂载的根，例如 "/work/**/*.py"
        res = resolve(self.mounts, pattern)
        base = posixpath.dirname(pattern) if "*" in pattern else pattern
        name = posixpath.basename(pattern)
        out = []
        for key in self._files:
            if key.startswith(base.rsplit("/", 1)[0] or "/"):
                if fnmatch.fnmatch(posixpath.basename(key), name) or fnmatch.fnmatch(key, pattern):
                    out.append(key)
        _ = res
        return sorted(out)

    async def grep(
        self, pattern: str, *, glob: str = "**/*", max_hits: int = 200
    ) -> list[Match]:
        rx = re.compile(pattern)
        hits: list[Match] = []
        for path, raw in sorted(self._files.items()):
            if not fnmatch.fnmatch(path, glob) and glob != "**/*":
                continue
            for lineno, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(Match(path=path, line=lineno, text=line[:400]))
                    if len(hits) >= max_hits:
                        return hits
        return hits

    async def stat(self, path: str) -> Stat:
        key = self._get(path)
        if key not in self._files:
            raise FileNotFoundError(key)
        return Stat(path=key, size=len(self._files[key]), mtime=self._mtime.get(key, 0.0))


class LocalFileSystem:
    """挂载到宿主目录；`source` 必填。真实路径仍在挂载根内才放行。"""

    def __init__(self, mounts: Sequence[Mount]) -> None:
        for mount in mounts:
            if not mount.source:
                raise PathDenied(f"本地挂载必须给 source：{mount.target}")
        self.mounts = tuple(mounts)

    def _resolve(self, path: str, *, write: bool = False):
        res = resolve(self.mounts, path)
        if write:
            require_writable(res)
            res.real.parent.mkdir(parents=True, exist_ok=True)
        return res

    async def read(self, path: str) -> bytes:
        return self._resolve(path).real.read_bytes()

    async def write(self, path: str, data: bytes) -> None:
        self._resolve(path, write=True).real.write_bytes(data)

    async def edit(self, path: str, old: str, new: str, *, count: int = 1) -> int:
        target = self._resolve(path, write=True).real
        text = target.read_text(encoding="utf-8")
        if old not in text:
            raise ValueError(f"未找到待替换文本：{old!r}")
        target.write_text(text.replace(old, new, count), encoding="utf-8")
        return 1

    async def glob(self, pattern: str) -> list[str]:
        res = resolve(self.mounts, pattern)
        root = Path(res.mount.source).resolve()
        return [str(p) for p in sorted(root.glob(res.relative or "*"))]

    async def grep(
        self, pattern: str, *, glob: str = "**/*", max_hits: int = 200
    ) -> list[Match]:
        rx = re.compile(pattern)
        hits: list[Match] = []
        for mount in self.mounts:
            root = Path(mount.source).resolve()
            for path in sorted(root.glob(glob)):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        hits.append(Match(path=str(path), line=lineno, text=line[:400]))
                        if len(hits) >= max_hits:
                            return hits
        return hits

    async def stat(self, path: str) -> Stat:
        real = self._resolve(path).real
        st = real.stat()
        return Stat(path=str(real), size=st.st_size, mtime=st.st_mtime, mode=st.st_mode,
                    is_dir=real.is_dir())



__all__ = ["MemoryFileSystem", "LocalFileSystem"]
