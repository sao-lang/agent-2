"""第 17 章 · 第 3 级：给 ReAct 接上第 16 章的四道刹车。

运行：
    python code/ch17_react/step3_guarded_react.py

新增的一个概念：**把"重复的查询结果"变成显式信号，喂回给模型**。

第 2 级能跑通，但它不会保护你：
  · 模型可以一直调工具（没有预算）
  · 模型可以用同样的参数调 10 次（没有指纹）
  · 工具报错会直接崩掉整个循环（没有容错）

这一级把三件事都补上，并演示"工具报错转成观察结果"为什么能让模型自救。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 工具

def search(args: dict) -> str:
    q = args.get("q", "")
    if not q:
        raise ValueError("缺少必填参数 q")
    if q == "退款":
        return "退款政策：签收后 7 天内无理由退货，15 天内可换货。"
    return "未检索到相关内容"


def flaky(args: dict) -> str:
    """一个会抛错的工具，用来演示容错。"""
    raise RuntimeError("上游服务 503")


TOOLS = {"search": search, "flaky": flaky}


# ---------------------------------------------------------------- 刹车

@dataclass
class Budget:
    max_steps: int = 6
    steps_used: int = 0

    def exhausted(self) -> str | None:
        return f"steps({self.max_steps})" if self.steps_used >= self.max_steps else None


@dataclass
class LoopGuard:
    max_repeats: int = 2
    seen: dict[str, int] = field(default_factory=dict)

    def check(self, name: str, args: dict) -> str | None:
        raw = json.dumps({"t": name, "a": args}, sort_keys=True, ensure_ascii=False)
        fp = hashlib.md5(raw.encode()).hexdigest()[:8]
        self.seen[fp] = self.seen.get(fp, 0) + 1
        if self.seen[fp] > self.max_repeats:
            return f"重复调用 {name}({args}) 第 {self.seen[fp]} 次"
        return None


# ---------------------------------------------------------------- 模型与循环

@dataclass
class Reply:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class ScriptedModel:
    script: list[Reply]
    turn: int = 0

    def invoke(self, messages: list[dict]) -> Reply:
        out = self.script[min(self.turn, len(self.script) - 1)]
        self.turn += 1
        return out


def react(llm, tools: dict, question: str, budget: Budget, guard: LoopGuard) -> dict:
    messages: list[dict] = [{"role": "user", "content": question}]

    while True:
        hit = budget.exhausted()
        if hit:
            return {"ok": False, "steps": budget.steps_used, "answer": "", "stop": f"budget:{hit}"}

        ai = llm.invoke(messages)
        budget.steps_used += 1
        messages.append(ai)

        if not ai.tool_calls:
            return {"ok": True, "steps": budget.steps_used, "answer": ai.content, "stop": "answer"}

        for call in ai.tool_calls:
            why = guard.check(call["name"], call["args"])
            if why:
                # 不终止循环，而是把"别再试了"作为观察结果交回模型
                messages.append({"role": "tool", "content": f"BLOCKED: {why}",
                                 "tool_call_id": call["id"]})
                continue

            fn = tools.get(call["name"])
            if fn is None:
                out = f"TOOL_ERROR: 没有名为 {call['name']} 的工具"
            else:
                try:
                    out = str(fn(call["args"]))
                except Exception as e:  # noqa: BLE001
                    # 关键：工具异常不往上抛，而是变成一条"观察结果"
                    out = f"TOOL_ERROR: {type(e).__name__}: {e}"
            messages.append({"role": "tool", "content": out, "tool_call_id": call["id"]})


def main() -> None:
    print("=" * 70)
    print("场景 A：模型反复用同样的参数查询（thrash）")
    print("=" * 70)
    thrash = ScriptedModel([Reply(tool_calls=[{"name": "search", "args": {"q": "退款"}, "id": f"c{i}"}])
                            for i in range(6)])
    r = react(thrash, TOOLS, "能退吗？", Budget(max_steps=8), LoopGuard(max_repeats=2))
    print(f"stop={r['stop']}  steps={r['steps']}  answer={r['answer'] or '(无)'}")
    print("→ 每个相同调用都被拦（BLOCKED 交回模型），但脚本模型不会自己收手，")
    print("  所以最后还是被步数预算停掉 —— 这正是「刹车要四道都有」的原因。")
    print("\n" + "=" * 70)
    print("场景 B：工具抛异常，模型自己换成对的参数")
    print("=" * 70)
    self_heal = ScriptedModel([
        Reply(tool_calls=[{"name": "search", "args": {}, "id": "c1"}]),        # 缺参数 → 工具报错
        Reply(tool_calls=[{"name": "search", "args": {"q": "退款"}, "id": "c2"}]),  # 看到错误后修正
        Reply(content="签收后 7 天内无理由退货，15 天内可换货。"),
    ])
    r = react(self_heal, TOOLS, "能退吗？", Budget(max_steps=6), LoopGuard(max_repeats=2))
    print(f"stop={r['stop']}  steps={r['steps']}  answer={r['answer']}")

    print("\n" + "=" * 70)
    print("场景 C：工具报错如果直接 raise，会发生什么")
    print("=" * 70)
    try:
        search({})
    except ValueError as e:
        print(f"  直接调用 → 抛异常 {type(e).__name__}: {e}")
        print("  如果循环里不捕获，整次运行就死了，模型连补救的机会都没有。")
    print("\n  👉 Agent 的容错一半来自「让模型知道错了」。")

    print("\n" + "=" * 70)
    print("三级的差别")
    print("=" * 70)
    print("  step1 文本 ReAct：能跑，但失败是静默的，而且会白花一整轮")
    print("  step2 原生 tool_calls：失败会当场报错，但没有任何保护")
    print("  step3 带刹车：失败可控、重复可拦、错误可自救")


if __name__ == "__main__":
    main()
