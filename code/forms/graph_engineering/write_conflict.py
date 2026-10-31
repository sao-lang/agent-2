"""两个分支写同一个字段：三种"修法"为什么都不解决根因。

不联网。演示四件事：
  1 没有 owner：覆盖，最后写赢，且结果取决于调用顺序
  2 加锁：仍然覆盖，锁只保证原子性，不保证语义
  3 append reducer：两条都留下，多写安全
  4 owner 检查：写别人的字段直接抛错

运行：python code/forms/graph_engineering/write_conflict.py
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


def left(state: dict) -> dict:
    state["findings"] = ["左：鉴权失败"]
    return state


def right(state: dict) -> dict:
    state["findings"] = ["右：超时"]
    return state


def merge_without_owner(order: tuple) -> list[str]:
    state = {"findings": []}
    for fn in order:
        state = fn(state)
    return state["findings"]


LOCK = threading.Lock()


def left_locked(state: dict) -> dict:
    with LOCK:
        state["findings"] = ["左：鉴权失败"]
    return state


def right_locked(state: dict) -> dict:
    with LOCK:
        state["findings"] = ["右：超时"]
    return state


def merge_with_lock(order: tuple) -> list[str]:
    state = {"findings": []}
    for fn in order:
        state = fn(state)
    return state["findings"]


def append_reducer(old: list | None, new: list | None) -> list:
    return list(old or []) + list(new or [])


def left_append(state: dict) -> dict:
    state["findings"] = append_reducer(state["findings"], ["左：鉴权失败"])
    return state


def right_append(state: dict) -> dict:
    state["findings"] = append_reducer(state["findings"], ["右：超时"])
    return state


def merge_with_append(order: tuple) -> list[str]:
    state = {"findings": []}
    for fn in order:
        state = fn(state)
    return state["findings"]


@dataclass(frozen=True)
class Field:
    name: str
    owner: str


def check_owner(field: Field, writer: str) -> None:
    if field.owner != writer:
        raise PermissionError(f"{writer} 试图写 {field.name}，owner 是 {field.owner}")


def main() -> None:
    print("=== 1. 没有 owner：两种调用顺序 ===")
    print(f"    左先右后 -> {merge_without_owner((left, right))}")
    print(f"    右先左后 -> {merge_without_owner((right, left))}")
    print("    <- 同一个初始状态，两种结果；第一条发现总有一个会消失")

    print()
    print("=== 2. 加锁：结果仍然取决于顺序 ===")
    print(f"    左先右后 -> {merge_with_lock((left_locked, right_locked))}")
    print(f"    右先左后 -> {merge_with_lock((right_locked, left_locked))}")
    print("    <- 锁让赋值不交错，但两次都是覆盖，语义没变")

    print()
    print("=== 3. append reducer：两条都留下，且与顺序无关（集合意义下） ===")
    a = merge_with_append((left_append, right_append))
    b = merge_with_append((right_append, left_append))
    print(f"    左先右后 -> {a}")
    print(f"    右先左后 -> {b}")
    print(f"    集合相同 -> {set(a) == set(b)}；顺序不同 -> {a != b}")

    print()
    print("=== 4. owner 检查：写别人的字段直接报错 ===")
    f = Field("findings", owner="act")
    check_owner(f, "act")
    print("    act 写 findings：允许")
    try:
        check_owner(f, "verify")
    except PermissionError as e:
        print(f"    verify 写 findings：{e}")
    print("    <- owner 不是文档约定：写在文档里，第一次并行就会破")


if __name__ == "__main__":
    main()
