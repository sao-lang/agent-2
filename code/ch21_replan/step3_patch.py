"""第 21 章 · 第 3 级：真正做一次 PATCH —— 只换失败那一步，别的都不动。

运行：
    python code/ch21_replan/step3_patch.py

新增的一个概念：**只替换失效的部分（PATCH）**。

这一级要演示两个坑（本书作者都踩过）：
  坑 1：替换步骤换了 id → 下游的 {s2.result} 引用失效 → 静默拿到空字符串
  坑 2：把「已完成的下游」也删了 → 计划"提前完成"，但根本没给出结论
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass
class Step:
    id: str
    goal: str
    action: str
    args: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    result: str = ""
    error: str = ""


@dataclass
class Plan:
    goal: str
    steps: list[Step]
    version: int = 1

    def by_id(self, sid: str) -> Step | None:
        return next((s for s in self.steps if s.id == sid), None)

    def ready(self) -> list[Step]:
        done = {s.id for s in self.steps if s.status == "done"}
        return [s for s in self.steps
                if s.status == "pending" and all(d in done for d in s.depends_on)]

    def complete(self) -> bool:
        return all(s.status in ("done", "skipped") for s in self.steps)


TOOLS = {"search": lambda a: f"{a.get('q')}：¥99/月", "compare": lambda a: "价差 30%",
         "answer": lambda a: f"建议：{a.get('summary')}"}


def resolve(args: dict, plan: Plan) -> dict:
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("{") and v.endswith(".result}"):
            prev = plan.by_id(v[1:-8])
            out[k] = prev.result if prev else ""
        else:
            out[k] = v
    return out


def run(plan: Plan) -> Plan:
    while (batch := plan.ready()):
        for s in batch:
            fn = TOOLS.get(s.action)
            if fn is None:
                s.status, s.error = "failed", f"未知动作：{s.action}"
            else:
                s.result, s.status = str(fn(resolve(s.args, plan))), "done"
    return plan


# ---------------------------------------------------------------- PATCH 的三种写法

def patch_wrong_1(plan: Plan, failed: Step) -> Plan:
    """❌ 坑 1：换了 id。下游 {s2.result} 就找不到东西了（s3/s4 永远等不到）。"""
    new = copy.deepcopy(plan)
    new.steps = [s for s in new.steps if s.id != failed.id]
    new.steps.insert(1, Step(id=failed.id + "_new", goal=failed.goal, action="search",
                             args=failed.args, depends_on=failed.depends_on))
    new.version += 1
    return new


def patch_wrong_2(plan: Plan, failed: Step) -> Plan:
    """❌ 坑 2：把失败的步骤和它**全部下游**都删了（包括已完成的）。"""
    new = copy.deepcopy(plan)
    replace = {failed.id}
    changed = True
    while changed:
        changed = False
        for s in new.steps:
            if s.id not in replace and any(d in replace for d in s.depends_on):
                replace.add(s.id)
                changed = True
    new.steps = [s for s in new.steps if s.id not in replace]
    new.steps.append(Step(id=failed.id, goal=failed.goal, action="search",
                          args=failed.args, depends_on=failed.depends_on))
    new.version += 1
    return new


def patch_right(plan: Plan, failed: Step) -> Plan:
    """✅ 只替换失败的步骤，保留 id，保留已完成的下游。"""
    new = copy.deepcopy(plan)
    for s in new.steps:
        if s.id == failed.id:
            s.action = "search"
            s.args = failed.args
            s.status = "pending"
            s.error = ""
            s.goal = failed.goal + "（已修正工具名）"
    new.version += 1
    return new


def build() -> Plan:
    return Plan("对比竞品并给建议", [
        Step("s1", "查A", "search", {"q": "A"}),
        Step("s2", "查B", "search_B", {"q": "B"}),
        Step("s3", "对比", "compare", {"a": "{s1.result}", "b": "{s2.result}"}, ["s1", "s2"]),
        Step("s4", "给建议", "answer", {"summary": "{s3.result}"}, ["s3"]),
    ])


def show(title: str, plan: Plan) -> None:
    print(f"\n{title}")
    for s in plan.steps:
        mark = {"done": "✔", "failed": "✘", "pending": "·"}[s.status]
        print(f"  {mark} [{s.id}] {s.goal:<22} {s.result or s.error or '(未执行)'}")
    print(f"  计划完成？{plan.complete()}   版本 v{plan.version}")
    print(f"  最终输出：{plan.steps[-1].result or '（空）'}")


def main() -> None:
    print("=" * 78)
    print("第 3 级：PATCH —— 只换失败那一步")
    print("=" * 78)

    # 先跑一遍，让 s2 失败
    p = run(build())
    failed = next(s for s in p.steps if s.status == "failed")
    print(f"\n原始运行：s2 失败（{failed.error}），s3/s4 卡住")

    show("❌ 坑 1：替换步骤换了 id（s2 → s2_new）", run(patch_wrong_1(p, failed)))
    print("     ↑ s3 的 depends_on 还是 's2'，但计划里已经没有 s2 —— 永远等不到")

    show("❌ 坑 2：连已完成的下游一起删", run(patch_wrong_2(p, failed)))
    print("     ↑ 计划「完成」了，但最终输出是「查B」的结果，不是「给建议」")

    show("✅ 正确做法：保留 id + 只重置失败步骤", run(patch_right(p, failed)))

    print("\n" + "=" * 78)
    print("为什么这两个坑特别危险")
    print("=" * 78)
    print("  坑 1：程序不报错，s3 拿着空字符串算出了一个「看起来正常」的结论")
    print("  坑 2：is_complete() 返回 True，监控显示「任务成功」，但业务上什么都没产出")
    print()
    print("  👉 共同点：**修复引入了更隐蔽的 bug。**")
    print("     「明显错了」不可怕，「看起来对了」才可怕。")
    print("     所以每次改计划，都要重新检查「完成」的定义是否还成立。")


if __name__ == "__main__":
    main()
