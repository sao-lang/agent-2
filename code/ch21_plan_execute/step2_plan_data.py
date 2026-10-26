"""第 20 章 · 第 2 级：把路径写成数据（Plan），而不是让它涌现。

运行：
    python code/ch21_plan_execute/step2_plan_data.py

新增的一个概念：**计划是一个数据结构，不是一段叙述。**

写成一个 dataclass 之后，你能做三件 ReAct 做不到的事：
  ① 执行前就打印出来给人看（可预审）
  ② 知道谁依赖谁（可并行）
  ③ 某步失败只重跑它（可重试，第 22 章）

这一级不调模型：计划是手写的，先把数据流跑通。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Step:
    id: str
    goal: str
    action: str
    args: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    result: str = ""
    status: str = "pending"      # pending / done / failed


@dataclass
class Plan:
    goal: str
    steps: list[Step]

    def by_id(self, sid: str) -> Step | None:
        return next((s for s in self.steps if s.id == sid), None)

    def ready(self) -> list[Step]:
        """前置都完成了、自己还没跑的步骤 —— 这一批可以并发。"""
        done = {s.id for s in self.steps if s.status == "done"}
        return [s for s in self.steps
                if s.status == "pending" and all(d in done for d in s.depends_on)]

    def show(self) -> None:
        for s in self.steps:
            deps = f"  依赖 {s.depends_on}" if s.depends_on else ""
            print(f"  [{s.id}] {s.goal:<14} action={s.action:<8}{deps}")


# ---------------------------------------------------------------- 工具

DB = {
    "竞品A": "¥99/月，按席位计费",
    "竞品B": "¥129/月，按调用量计费",
    "竞品C": "¥79/月，含 10 万 token 免费额度",
}


def search(args: dict) -> str:
    time.sleep(0.4)                      # 假装在查网络
    return DB.get(args.get("q", ""), "未找到")


def compare(args: dict) -> str:
    return f"三家价格区间：{args['a'][:5]} ~ {args['b'][:6]}，计费方式各不相同"


def answer(args: dict) -> str:
    return f"建议：{args['summary']}"


TOOLS = {"search": search, "compare": compare, "answer": answer}


# ---------------------------------------------------------------- 执行

def resolve(args: dict, plan: Plan) -> dict:
    """把 {"q": "{s1.result}"} 换成上一步的真实结果。

    这就是 P&E 和 ReAct 最本质的差别：数据依赖是**写出来的**，不是"模型记得就有"。
    """
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("{") and v.endswith(".result}"):
            prev = plan.by_id(v[1:-8])
            out[k] = prev.result if prev else ""
        else:
            out[k] = v
    return out


def run(plan: Plan, parallel: bool = False) -> Plan:
    while any(s.status == "pending" for s in plan.steps):
        batch = plan.ready()
        if not batch:
            print("  ⚠️ 没有任何步骤可执行（依赖永远不满足）—— 计划卡住了")
            break

        if parallel and len(batch) > 1:
            # 真实系统里这里是 asyncio.gather；这里用顺序执行证明"依赖允许并行"
            print(f"  ▶ 这一批可以并发：{[s.id for s in batch]}")

        for s in batch:
            s.result = str(TOOLS[s.action](resolve(s.args, plan)))
            s.status = "done"
            print(f"  ✔ [{s.id}] {s.goal} → {s.result}")
    return plan


def build_plan() -> Plan:
    return Plan(
        goal="对比三家竞品定价并给出建议",
        steps=[
            Step("s0", "定口径", "answer", {"summary": "统一按「月费 + 计费方式」比"}, []),
            Step("s1", "查竞品A", "search", {"q": "竞品A"}, []),
            Step("s2", "查竞品B", "search", {"q": "竞品B"}, []),
            Step("s3", "查竞品C", "search", {"q": "竞品C"}, []),
            Step("s4", "横向对比", "compare", {"a": "{s1.result}", "b": "{s2.result}"},
                 ["s1", "s2", "s3"]),
            Step("s5", "给出建议", "answer", {"summary": "{s4.result}"}, ["s4"]),
        ],
    )


def main() -> None:
    plan = build_plan()

    print("=" * 72)
    print("第 2 级：计划是一个数据结构")
    print("=" * 72)
    print("\n【执行前就能打印出来（可预审）】")
    plan.show()

    print("\n【执行】")
    t0 = time.perf_counter()
    run(plan)
    elapsed = time.perf_counter() - t0

    print(f"\n最终结果：{plan.steps[-1].result}")
    print(f"总耗时：{elapsed:.2f}s（三次串行搜索，每次 0.4s）")

    print("\n" + "=" * 72)
    print("这个数据结构白送了你三样东西")
    print("=" * 72)
    print("  ① 可预审：s0「先定口径」写进了计划，所以不会出现第 3 步才发现口径不对")
    print("  ② 可并行：s1/s2/s3 的 depends_on 都是空的 —— 一眼看出它们能同时跑")
    print("  ③ 可重试：如果 s3 失败，只有依赖 s3 的 s4 需要重排，s1/s2 不用重查（第 22 章）")
    print("\n  👉 下一级：让模型生成这个数据结构（而不是人写）。")


if __name__ == "__main__":
    main()
