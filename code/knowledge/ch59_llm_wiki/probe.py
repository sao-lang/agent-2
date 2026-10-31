"""诊断探针：先发现缺事实，再改编译参数，再复测。"""

from __future__ import annotations

from wiki_core import compile_all, probe


def show(title: str, entries: dict) -> None:
    print(f"--- {title} ---")
    for question, passed, answer in probe(entries):
        print(f"{'PASS' if passed else 'FAIL'}  {question} -> {answer}")


def main() -> None:
    show("默认编译（丢例外）", compile_all(include_exceptions=False))
    print("\n发现：定制商品的例外句没有进条目。")
    show("重编译（保留例外）", compile_all(include_exceptions=True))


if __name__ == "__main__":
    main()
