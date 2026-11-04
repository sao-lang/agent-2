"""FP 组合形态样张：把 v2 的插点 / 挂载用函数组合表达。

运行：
    python code/harness/examples/fp_composition.py

这不是框架实现，是一份"可运行的形态样张"：证明同样的能力用函数组合
表达时，开发体验（写、换、测）是什么样。核心只有三条：

    1. 程序 = Aspect；Aspect 是 Handler -> Handler 的纯函数
    2. 组合 = 函数复合（`>>` 左为外层，`|` 回退），无类、无装饰器、无容器
    3. 后端 = env 里的能力记录；换后端不改程序一个字

为什么有两个组合层：一次运行有四个拦截点，`step` 与 `tool_call` 不是同一层。
把准入（approval）挂到 step 外层，工具就会先执行、后被审批——本文件第一版
就犯了这个错，运行结果是 `状态=refused 但 refund 已执行`。这个洞只能在
"两层组合"里堵上，正好说明为什么要分插点而不是只用一条洋葱。

对照 v1 的等价写法（同样六个关注点）：

    agent = build(AgentConfig(
        model=model, tools=[fetch, refund], mode="react", max_steps=6,
        guard=FunctionGuard(policy), budget=Budget(tokens=2000),
        durability=MemoryDurability(), tracer=MemoryTracer(),
    ))

两者都能跑；差别在于：v1 的六个关注点是**构造参数**，加一个要改签名、
换一个要改实现；这里的六个是**可组合的值**，加一个只是多一次 `>>`。
"""

from __future__ import annotations

import asyncio
import operator
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any, Awaitable, Callable

State = dict[str, Any]
Env = dict[str, Any]
Handler = Callable[[State], Awaitable[State]]


# ══════════════════════════════════════════════════════════ 组合子
@dataclass(frozen=True)
class Aspect:
    """一个可组合的程序片：包裹一个 Handler，返回一个新 Handler。

    `build` 是纯函数——它只决定"怎么包"，不决定"包什么"。所以任意两个
    Aspect 都能组合，且组合结果仍是 Aspect（闭合性）。
    """

    parts: tuple[str, ...]
    build: Callable[[Handler], Handler]

    @property
    def name(self) -> str:
        return " > ".join(self.parts)

    def __call__(self, h: Handler) -> Handler:
        return self.build(h)

    def __rshift__(self, other: "Aspect") -> "Aspect":
        """顺序复合：self 在外、other 在内（与中间件直觉一致）。"""
        return Aspect(
            self.parts + other.parts,
            lambda nxt: self.build(other.build(nxt)),
        )

    def __or__(self, other: "Aspect") -> "Aspect":
        """回退复合：前者抛错则整体改用后者，二者共享同一个内层。"""

        def build(nxt: Handler) -> Handler:
            left, right = self.build(nxt), other.build(nxt)

            async def handler(state: State) -> State:
                try:
                    return await left(state)
                except Exception:  # noqa: BLE001 - 回退边界
                    state.setdefault("trace", []).append(f"fallback:{self.name}")
                    return await right(state)

            return handler

        return Aspect(self.parts + ("|",) + other.parts, build)


def compose(*aspects: Aspect) -> Aspect:
    """把若干 Aspect 复合成一个。reduce 而不是构造函数——这就是全部机制。"""
    return reduce(operator.rshift, aspects)


def describe(program: Aspect) -> str:
    """组合的代价是"看不见最终顺序"，所以必须能打印出来。"""
    return " > ".join(program.parts)


# ══════════════════════════════════════════════════════════ 内核：决策与执行
async def decide(state: State) -> State:
    """问模型要下一步。不执行任何副作用。"""
    env = state["env"]
    reply = await env["model"](state)
    state["usage"] += reply.get("tokens", 0)
    call = reply.get("call")

    if call is None:
        state["done"] = True
        state["answer"] = reply["content"]
        return state

    state["pending"] = {"tool": call, "args": reply["args"]}
    return state


async def invoke(state: State) -> State:
    """执行 pending 的那一次工具调用。整条工具链的终端，唯一有副作用的原语。"""
    env, pending = state["env"], state.pop("pending")

    if env.get("mode") == "collect":  # 干跑：效果只入账，不执行
        state["effects"].append(pending)
        return state

    state["steps"].append(pending["tool"])
    out = await env["tools"][pending["tool"]](**pending["args"])
    state["messages"].append({"tool": pending["tool"], "out": out})
    state["last"] = out
    return state


def step(tool_chain: Aspect) -> Handler:
    """一次 step = 决策 + （若有）执行。工具链只在真正要调工具时走一遍。"""

    async def handler(state: State) -> State:
        state = await decide(state)
        if state.get("pending"):
            state = await tool_chain(invoke)(state)
        return state

    return handler


def react(*, max_steps: int = 6) -> Aspect:
    """主体策略作为包裹：只负责"重复调用内层，直到 done"。"""

    def build(nxt: Handler) -> Handler:
        async def loop(state: State) -> State:
            for i in range(max_steps):
                state["step"] = i + 1
                state = await nxt(state)
                if state.get("done"):
                    return state
            state["status"] = "max_steps"
            return state

        return loop

    return Aspect((f"react({max_steps})",), build)


# ══════════════════════════════════════════════════════════ 横切：全是包裹
def budget(tokens: int) -> Aspect:
    class Exceeded(Exception):
        pass

    def build(nxt: Handler) -> Handler:
        async def guard(state: State) -> State:
            if state["usage"] > tokens:
                raise Exceeded(f"预算耗尽：{state['usage']} > {tokens}")
            return await nxt(state)

        return guard

    return Aspect((f"budget({tokens})",), build)


def approval(policy: Callable[[str], bool]) -> Aspect:
    """Guard：动作准入。挂在**工具链**上——拒绝即短路，绝不进入 invoke。"""

    def build(nxt: Handler) -> Handler:
        async def check(state: State) -> State:
            tool = state["pending"]["tool"]
            if not policy(tool):
                state.pop("pending")
                state["status"] = "refused"
                state["done"] = True
                state["answer"] = f"拒绝执行 {tool}"
                return state
            return await nxt(state)

        return check

    return Aspect(("approval",), build)


def checkpoint(cap: str = "store") -> Aspect:
    """按能力名取后端：程序里不出现具体实现，换后端只换 env。"""

    def build(nxt: Handler) -> Handler:
        async def save(state: State) -> State:
            state = await nxt(state)
            if not state.get("done"):
                await state["env"][cap].put(state)
            return state

        return save

    return Aspect((f"checkpoint({cap})",), build)


def audit(cap: str = "sink") -> Aspect:
    """纯观察：拿不到返回值，改不了 state，异常必须吞掉。—— hook 的形态。"""

    def build(nxt: Handler) -> Handler:
        async def observe(state: State) -> State:
            out = await nxt(state)
            try:
                await state["env"][cap].emit(
                    {"step": state.get("step"), "tools": list(state["steps"])}
                )
            except Exception:  # noqa: BLE001 - 观察者不得影响运行
                pass
            return out

        return observe

    return Aspect((f"audit({cap})",), build)


# ══════════════════════════════════════════════════════════ 后端：可替换
class MemoryStore:
    name = "memory"

    def __init__(self) -> None:
        self.revs: list[dict] = []

    async def put(self, state: State) -> None:
        self.revs.append({k: v for k, v in state.items() if k != "env"})


class JsonlStore:
    name = "jsonl"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.revs: list[dict] = []

    async def put(self, state: State) -> None:
        import json

        row = {k: v for k, v in state.items() if k != "env"}
        self.revs.append(row)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


class MemorySink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)


# ══════════════════════════════════════════════════════════ 模型替身
class FakeModel:
    def __init__(self, *replies: dict) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def __call__(self, state: State) -> dict:
        self.calls += 1
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


def call(name: str, **args) -> dict:
    return {"call": name, "args": args, "tokens": 10}


def answer(text: str) -> dict:
    return {"content": text, "tokens": 10}


# ══════════════════════════════════════════════════════════ 运行入口
async def run(program: Aspect, tool_chain: Aspect, *, env: Env, goal: str) -> State:
    state: State = {
        "goal": goal, "env": env, "usage": 0, "step": 0,
        "steps": [], "messages": [], "effects": [], "trace": [],
        "answer": "", "status": "completed",
    }
    handler = program(step(tool_chain))
    try:
        return await handler(state)
    except Exception as exc:  # noqa: BLE001 - 出口唯一
        state["status"] = "degraded"
        state["answer"] = f"降级：{exc}"
        return state


# ══════════════════════════════════════════════════════════ 业务工具
async def fetch_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "已签收"}


async def refund(order_id: str, amount: int) -> dict:
    return {"order_id": order_id, "refunded": amount}


TOOLS = {"fetch_order": fetch_order, "refund": refund}


# ══════════════════════════════════════════════════════════ 样张
async def main() -> None:
    # 工具点：准入 → 执行
    tool_chain = compose(approval(lambda t: t != "refund"), audit())
    # 运行 / 步点：预算 → 循环 → 每步落盘
    program = compose(budget(2_000), react(max_steps=6), checkpoint())

    print("① 程序文本（组合的代价是看不见顺序，所以必须能打印）")
    print(f"    运行链 = {describe(program)}")
    print(f"    工具链 = {describe(tool_chain)}")

    print("\n② 跑一次（内存后端）：refund 被准入拒绝，且没有真的执行")
    sink, store = MemorySink(), MemoryStore()
    model = FakeModel(
        call("fetch_order", order_id="A1001"),
        call("refund", order_id="A1001", amount=100),
        answer("不应到达这一步"),
    )
    result = await run(program, tool_chain,
                       env={"model": model, "tools": TOOLS, "store": store, "sink": sink},
                       goal="查 A1001 并退款")
    print(f"    状态={result['status']}  答案={result['answer']}")
    print(f"    已执行工具={result['steps']}  检查点={len(store.revs)} 个  审计={len(sink.events)} 条")

    print("\n③ 同一程序，换后端（jsonl）+ 干跑（效果只入账，不执行）")
    jstore = JsonlStore(Path(__file__).parent / "_fp_runs.jsonl")
    try:
        result2 = await run(program, tool_chain,
                            env={"model": FakeModel(call("fetch_order", order_id="A9"),
                                                    answer("done")),
                                 "tools": TOOLS, "store": jstore, "sink": MemorySink(),
                                 "mode": "collect"},
                            goal="干跑")
        print(f"    状态={result2['status']}  检查点={len(jstore.revs)} 个")
        print(f"    已执行={result2['steps']}  消息={result2['messages']}")
        print(f"    收集到的效果={result2['effects']}")
    finally:
        (Path(__file__).parent / "_fp_runs.jsonl").unlink(missing_ok=True)

    print("\n④ 回退：故意让预算断言炸掉，用 `|` 换整条链")
    def explode() -> Aspect:
        def build(nxt: Handler) -> Handler:
            async def boom(state: State) -> State:
                raise RuntimeError("后端不可用")
            return boom
        return Aspect(("explode",), build)

    safe = compose(explode(), react(max_steps=2)) | compose(react(max_steps=2))
    result3 = await run(safe, tool_chain,
                        env={"model": FakeModel(answer("兜底成功")), "tools": TOOLS,
                             "store": MemoryStore(), "sink": MemorySink()},
                        goal="回退演示")
    print(f"    程序={describe(safe)}")
    print(f"    状态={result3['status']}  答案={result3['answer']}  trace={result3['trace']}")

    print("\n⑤ 顺序无关性：交换 audit / checkpoint，结果必须一致")
    outs = []
    for prog in (compose(react(max_steps=6), checkpoint(), audit()),
                 compose(react(max_steps=6), audit(), checkpoint())):
        st = await run(prog, tool_chain,
                       env={"model": FakeModel(call("fetch_order", order_id="A1"), answer("ok")),
                            "tools": TOOLS, "store": MemoryStore(), "sink": MemorySink()},
                       goal="顺序")
        outs.append((st["status"], st["answer"], st["steps"]))
    print(f"    {describe(compose(react(max_steps=6), checkpoint(), audit()))} -> {outs[0]}")
    print(f"    {describe(compose(react(max_steps=6), audit(), checkpoint()))} -> {outs[1]}")
    print(f"    等价：{outs[0] == outs[1]}")


if __name__ == "__main__":
    asyncio.run(main())
