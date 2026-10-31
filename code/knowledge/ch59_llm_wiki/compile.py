"""20 篇小文档 -> 条目目录（这里 8 篇，原理演示）。"""

from __future__ import annotations

from wiki_core import compile_all, render


def main() -> None:
    entries = compile_all()
    print("entries:", len(entries))
    print("catalog:", " / ".join(entries))
    print("---")
    print(render(entries))


if __name__ == "__main__":
    main()
