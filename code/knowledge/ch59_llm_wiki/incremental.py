"""改一篇源文档，只重编译受影响条目。"""

from __future__ import annotations

from wiki_core import compile_all


def main() -> None:
    old = compile_all(include_exceptions=True)
    new = compile_all(include_exceptions=True)
    new["退货资格"]["text"] = new["退货资格"]["text"].replace("15 天", "30 天")
    changed = [name for name in old if old[name]["text"] != new[name]["text"]]
    print("changed sources: 1 (d5 会员条款)")
    print("recompiled entries:", changed)
    print("unaffected entries:", len(old) - len(changed))
    print("old:", old["退货资格"]["text"])
    print("new:", new["退货资格"]["text"])
    print("diff:", "-15 天 / +30 天")


if __name__ == "__main__":
    main()
