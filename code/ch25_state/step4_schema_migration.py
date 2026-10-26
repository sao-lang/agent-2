"""第 24 章 step4：State 结构变了，旧的检查点还能不能读（离线）。

运行：
    python code/ch25_state/step4_schema_migration.py

上一级的痛点：字段定好了、并发也安全了，但**上线之后你想加一个字段**。

这一级做什么：模拟三次发版，每次都改了 State 结构，然后从"旧检查点"恢复：
  v1 → v2：新增字段（带默认值）
  v2 → v3：字段改名（old_name → new_name）
  v3 → v4：字段删除 + 语义变化（cursor:int → progress:dict）

结论：**每一次改结构，都要写一段迁移代码——否则线上正在跑的长任务会全部崩在恢复那一刻。**
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CUR_VERSION = 4


@dataclass
class StateV1:
    goal: str
    step: int = 0                 # ← 当时叫 step


@dataclass
class StateV2:
    goal: str
    step: int = 0
    notes: list[str] = field(default_factory=list)      # ← 新增


@dataclass
class StateV3:
    goal: str
    cursor: int = 0                                     # ← step 改名成 cursor
    notes: list[str] = field(default_factory=list)


@dataclass
class StateV4:
    goal: str
    progress: dict = field(default_factory=lambda: {"cursor": 0, "total": 0})  # ← 结构变了
    notes: list[str] = field(default_factory=list)


def save(state) -> str:
    d = dict(state.__dict__)
    d["__version__"] = int(state.__class__.__name__[-1])
    return json.dumps(d, ensure_ascii=False)


def migrate(raw: dict) -> dict:
    """把任意版本的检查点，逐级升到当前版本。

    关键：**逐级迁移**，不是"直接映射到最新版"。
    因为每两级之间只差一个语义变化，逐级写能保证每一步都可测。
    """
    v = raw.get("__version__", 1)
    data = {k: val for k, val in raw.items() if k != "__version__"}

    if v == 1:
        data.setdefault("notes", [])          # v1 → v2：补默认值
        v = 2
    if v == 2:
        data["cursor"] = data.pop("step", 0)  # v2 → v3：改名
        v = 3
    if v == 3:
        cursor = data.pop("cursor", 0)
        data["progress"] = {"cursor": cursor, "total": 0}   # v3 → v4：改结构
        v = 4
    if v != CUR_VERSION:
        raise ValueError(f"检查点版本 {v} 不认识（当前支持到 v{CUR_VERSION}）")
    return data


def main() -> None:
    print("=" * 78)
    print("三个旧检查点，逐个恢复到当前版本")
    print("=" * 78)

    old_checkpoints = {
        "写于 v1": save(StateV1(goal="写竞品报告", step=2)),
        "写于 v2": save(StateV2(goal="写竞品报告", step=3, notes=["A 定价 99"])),
        "写于 v3": save(StateV3(goal="写竞品报告", cursor=4, notes=["A 定价 99", "B 定价 109"])),
    }

    for label, raw in old_checkpoints.items():
        print(f"\n  【{label}】原始：{raw}")
        try:
            data = migrate(json.loads(raw))
            st = StateV4(**data)
            print(f"    恢复成功 → cursor={st.progress['cursor']} notes={st.notes}")
        except Exception as exc:                      # noqa: BLE001
            print(f"    ❌ 恢复失败：{type(exc).__name__}: {exc}")

    print("\n" + "=" * 78)
    print("反例：不写迁移，直接按新结构恢复")
    print("=" * 78)
    raw_v1 = json.loads(old_checkpoints["写于 v1"])
    raw_v1.pop("__version__", None)
    try:
        StateV4(**raw_v1)
    except TypeError as exc:
        print(f"  ❌ TypeError: {exc}")
        print("  → 线上正在跑的长任务，会在**恢复那一刻**全部失败。")
        print("     而它们的数据还在，只是没人会读——这就是最难受的故障形态。")

    print("\n" + "=" * 78)
    print("三条迁移纪律")
    print("=" * 78)
    print("  1. **检查点里必须有版本号**。没有版本号，你不知道该按哪套规则解读它。")
    print("  2. **逐级迁移，每级一个函数**。不要写'从 v1 直接到 v4'的大映射，")
    print("     因为那会在 v5 出现时变成 4 条分支，没人测得完。")
    print("  3. **加字段给默认值，删字段先保留再废弃**（两个版本之后再删）。")
    print("     直接删 = 线上老数据全部读不出。")
    print()
    print("  ⚠️ 还有一条：**不要在 State 里存类实例 / 连接 / 锁**。")
    print("     检查点要能 json 序列化——不能序列化的东西，恢复时一定会出问题。")

    print("\n" + "=" * 78)
    print("下一级：最后回答一个问题——State 应该拆成一个大字典，还是分几个小对象？")
    print("=" * 78)


if __name__ == "__main__":
    main()
