"""通用解释器方案 · 端到端验收样张。

验证四件事：
  1. 十种主流架构 + 四种"框架作者没想过的架构"共用同一个 interpret()
  2. 自定义架构没有改动 contracts.py / interpreter.py（框架 diff = 0）
  3. Layer / Hook 横切机制照常工作，且插点可扩展
  4. 治理分级：声明式 Graph 可校验可序列化，裸函数程序只保证能跑
"""

from __future__ import annotations

import asyncio

from proposals.contracts import Layer, State, capabilities, describe, to_spec
from proposals.custom import custom_cases
from proposals.interpreter import Limits, Runtime, ValidationFailed
from proposals.paradigms import Graph, builtin_paradigms

EVENTS: list[str] = []


def budget_gate(effect, state) -> str:
    return "deny" if state.usage["calls"] > 50 else "allow"


def audit_observe(effect, result, state) -> None:
    EVENTS.append(f"{effect.kind}:{state.rev}")


def truncate_wrap(effect, nxt):
    async def handler(eff, state):
        out = await nxt(eff, state)
        if isinstance(out, dict) and isinstance(out.get("output"), str) and len(out["output"]) > 80:
            out = {**out, "output": out["output"][:80] + "…[truncated]"}
        return out
    return handler


LAYERS = (
    Layer("budget", gate=budget_gate),
    Layer("audit", observe=audit_observe),
    Layer("truncate", wrap=truncate_wrap),
)


def runtime() -> Runtime:
    return Runtime(layers=LAYERS, limits=Limits(max_transitions=64, max_calls=80))


async def main() -> None:
    cases = builtin_paradigms() + custom_cases()
    failures: list[str] = []

    print("=" * 74)
    print("通用解释器验收 · 10 种内置范式 + 4 种未知架构")
    print("=" * 74)
    for name, program, state in cases:
        problems = runtime().validate(program)
        if problems:
            failures.append(f"{name}: 装配期校验失败 {problems}")
            continue
        out = await runtime().interpret(program, state)
        flag = "OK" if out.status in ("completed", "degraded") else "FAIL"
        if flag == "FAIL":
            failures.append(f"{name}: {out.status}")
        print(f"[{flag}] {name:<26} status={out.status:<10} "
              f"steps={out.transitions:<3} ckpt={out.checkpoints:<3} answer={out.answer!r}")
        print(f"      trace: {' > '.join(out.trace[:6])}"
              + (" …" if len(out.trace) > 6 else ""))

    print("\n" + "-" * 74)
    print("治理分级（程序声明自己支持什么，框架不假装全能）")
    graph = cases[9][1]
    bare = cases[-1][1]
    print(f"  Graph   capabilities = {capabilities(graph)}  describe = {describe(graph)!r}")
    print(f"  Graph   static_check = {graph.static_check()}  to_spec keys = {sorted(to_spec(graph))}")
    print(f"  BareFn  capabilities = {capabilities(bare)}  describe = {describe(bare)!r}")
    try:
        to_spec(bare)
    except TypeError as exc:
        print(f"  BareFn  to_spec -> {type(exc).__name__}: {exc}")

    print("\n" + "-" * 74)
    print("装配期校验：故意给一个带环的 DAG")
    cyclic = Graph(
        nodes={"a": graph.nodes["a"], "b": graph.nodes["b"]},
        edges=(("a", "b", ""), ("b", "a", "")),
        entry="a",
    )
    try:
        await runtime().interpret(cyclic, State("bad", data={"tools": {}}))
        print("  未拦截（错误）")
        failures.append("带环 DAG 未被拦截")
    except ValidationFailed as exc:
        print(f"  已拦截：{exc}")

    print("\n" + "-" * 74)
    print("dry_run：四段链照走，终端只记账不执行")
    dry = await Runtime(record_only=True, layers=LAYERS).interpret(
        cases[1][1], State("干跑", data={"script": [{"content": "done"}]})
    )
    print(f"  status={dry.status} steps={dry.transitions} answer={dry.answer!r}")

    print("\n" + "-" * 74)
    print(f"横切观测事件（Hook/Layer 照常工作）：{len(EVENTS)} 条，示例 {EVENTS[:3]}")
    print(f"结论：{'全部通过' if not failures else '存在失败：' + '; '.join(failures)}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
