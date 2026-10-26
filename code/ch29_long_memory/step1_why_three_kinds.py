"""第 28 章 step1：三种记忆混在一起，会发生什么（离线）。

运行：
    python code/ch29_long_memory/step1_why_three_kinds.py

上一级的痛点：无（这是起点）。
这一级做什么：把"偏好""事件""流程"三种东西塞进同一张表，
             让你看见它们被同一套规则处理时，各自怎么坏掉。

三种记忆：
  语义（semantic）   ：稳定事实。用户说"我对芒果过敏"，三个月后依然成立
  情景（episodic）   ：发生过什么。用户昨天投诉过运费，一周后就不该再提
  程序（procedural） ：怎么做。处理换新的 5 个步骤，只有成功过才值得记

它们坏的方式完全不同，所以必须分开。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class FlatMemory:
    """把所有东西塞进一张表的朴素实现。"""

    rows: list[dict] = field(default_factory=list)

    def write(self, content: str, kind: str, key: str = "") -> None:
        self.rows.append({"content": content, "kind": kind, "key": key, "created_at": time.time()})

    def all(self) -> list[dict]:
        return list(self.rows)


# 三个真实场景（同一用户，同一个租户）
SEED = [
    ("用户对芒果过敏，禁止推荐含芒果的商品", "fact", "pref.mango"),
    ("用户对芒果过敏，禁止推荐含芒果的商品", "fact", "pref.mango"),   # 用户又说了一遍
    ("今天帮用户处理了换新申请", "event", ""),
    ("一周前咨询过运费规则", "event", ""),
    ("换新的标准流程：查订单 → 验时效 → 传视频", "flow", "换新处理"),
    ("换新的标准流程（试跑失败版，多了一步重复上传）", "flow", "换新处理"),
]


def main() -> None:
    mem = FlatMemory()
    for content, kind, key in SEED:
        mem.write(content, kind, key)

    print("=" * 78)
    print("把三种记忆塞进一张表，会同时踩四个坑")
    print("=" * 78)
    print(f"写入 {len(SEED)} 条，表里实实在在存了 {len(mem.all())} 条：\n")
    for i, r in enumerate(mem.all(), 1):
        print(f"  {i}. [{r['kind']:<5}] {r['content'][:44]}")

    print("\n" + "=" * 78)
    print("坑 1 · 重复：同一件事存了两份")
    print("=" * 78)
    dup = [r for r in mem.all() if r["content"] == "用户对芒果过敏，禁止推荐含芒果的商品"]
    print(f"  「对芒果过敏」存了 {len(dup)} 份。")
    print("  检索时它会被算两次分，挤掉别的内容。")
    print("  → 语义记忆需要**去重键**（pref.mango），同一 key 只保留一条。")

    print("\n" + "=" * 78)
    print("坑 2 · 冲突：新旧说法相反，但系统不知道该信谁")
    print("=" * 78)
    print("  用户后来说「可以吃芒果了」，朴素实现只是又加了一条。")
    print("  两条都还在表里，检索时先命中谁全看运气。")
    print("  → 语义记忆需要**取代 + 软删除 + 高冲突人工确认**。")

    print("\n" + "=" * 78)
    print("坑 3 · 时间：三个月前的事件和昨天的事件等价")
    print("=" * 78)
    print("  朴素实现没有时间因素，检索「用户提到运费」时，")
    print("  「一周前咨询过运费」和「今天投诉了运费」得分相同。")
    print("  → 情景记忆需要**时间衰减**。")

    print("\n" + "=" * 78)
    print("坑 4 · 失败流程：不能照着做的步骤也被记下来了")
    print("=" * 78)
    flows = [r for r in mem.all() if r["kind"] == "flow"]
    print(f"  「换新处理」存了 {len(flows)} 个版本，其中一个是失败的试跑。")
    print("  下次检索到它，Agent 会照着失败流程做一遍。")
    print("  → 程序记忆必须**验证成功才写入 + 版本化**。")

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  四个坑的修法互不兼容：")
    print("    去重/冲突 → 需要 key + 取代语义")
    print("    时间衰减 → 需要时间因子，并且不能乱改内容")
    print("    成功验证 → 需要写入前的校验和版本号")
    print()
    print("  想把它们塞进一套规则，你最后会写出一个「if kind == ...」的巨型分支。")
    print("  **正确做法是分成三张表（或三个命名空间），各自一套写入策略。**")
    print("  这就是下一级的「三层长期记忆」。")


if __name__ == "__main__":
    main()
