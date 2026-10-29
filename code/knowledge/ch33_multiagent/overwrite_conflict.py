"""两个 agent 并发写同一份状态：覆盖、丢更新、合并。

不联网。三个 reducer 跑同一组输入，比较最后状态：
  overwrite  后写覆盖前写（整个字段替换）
  snapshot   两个分支各自读到旧快照再写回（丢更新：计数少一次）
  merge      写回前重读最新值，列表去重、计数累加
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field


@dataclass
class State:
    findings: list[str] = field(default_factory=list)
    votes: dict[str, int] = field(default_factory=dict)   # 发现 -> 几个分支独立报到


BRANCHES = [
    ("分支 A", ["缓存未命中", "连接池用到上限"]),
    ("分支 B", ["索引未更新", "连接池用到上限"]),
]
SHARED = "连接池用到上限"


def run_overwrite() -> State:
    st = State()
    for _, items in BRANCHES:
        st.findings = list(items)                  # 整个字段覆盖
        st.votes = {SHARED: 1}
    return st


def run_snapshot() -> State:
    st = State()
    base = deepcopy(st)                            # 两个分支同时读到同一份旧状态
    a = deepcopy(base)
    for it in BRANCHES[0][1]:
        a.findings.append(it)
    a.votes[SHARED] = a.votes.get(SHARED, 0) + 1
    b = deepcopy(base)
    for it in BRANCHES[1][1]:
        b.findings.append(it)
    b.votes[SHARED] = b.votes.get(SHARED, 0) + 1
    st = b                                         # 后写的那份留下来
    return st


def run_merge() -> State:
    st = State()
    for _, items in BRANCHES:
        for it in items:                           # 写回前基于最新值
            if it not in st.findings:
                st.findings.append(it)
            st.votes[it] = st.votes.get(it, 0) + 1
    return st


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 两个分支各报两条，其中一条相同 ===")
    for name, items in BRANCHES:
        print(f"  {name}: {items}")
    print(f"  期望：3 条不同的发现，'{SHARED}' 被 2 个分支报到")

    print()
    print("=== 2. 三种 reducer 的结果 ===")
    for label, fn in [("覆盖写", run_overwrite), ("旧快照写回", run_snapshot), ("合并", run_merge)]:
        st = fn()
        print(f"  {pad(label, 12)}{len(st.findings)} 条 {st.findings}")
        print(f"  {pad('', 12)}'{SHARED}' 计数 {st.votes.get(SHARED, 0)}")

    print()
    print("=== 3. 各丢了什么 ===")
    merged = run_merge()
    for label, fn in [("覆盖写", run_overwrite), ("旧快照写回", run_snapshot)]:
        st = fn()
        lost = sorted(set(merged.findings) - set(st.findings))
        print(f"  {pad(label, 12)}丢发现 {lost or '无'}，"
              f"丢计数 {merged.votes[SHARED] - st.votes.get(SHARED, 0)}")

    print()
    print("=== 4. '两个分支都看到了'与'看到一个'的区别 ===")
    print(f"  合并后计数：'{SHARED}' = {merged.votes[SHARED]}")
    print("  <- 计数让'独立证据数'保留下来；只做列表去重会把这个信息丢掉")


if __name__ == "__main__":
    main()
