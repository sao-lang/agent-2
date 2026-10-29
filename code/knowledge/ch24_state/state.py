"""第 24 章示例：State 的三个演进版本，以及两个并行分支写同一字段的丢与不丢。

只用标准库，不联网。输出是真实运行结果，正文逐字粘贴。

运行：
    $env:PYTHONIOENCODING='utf-8'; python code/knowledge/ch24_state/state.py
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------- 版本 1：等于聊天记录

@dataclass
class V1:
    """把整段对话当状态，放什么全靠 messages。"""
    messages: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 版本 2：抽出任务字段

@dataclass
class V2:
    """把任务状态从 messages 里抽出来，字段固定。"""
    messages: list[dict] = field(default_factory=list)
    order_id: str | None = None
    eligible: bool | None = None
    reason: str | None = None


# ---------------------------------------------------------------- 版本 3：字段按生命周期分类

@dataclass
class V3:
    """输入只写一次，事实只增，结论可覆盖，计数只增。"""
    messages: list[dict] = field(default_factory=list)
    user_intent: str = ""                       # 输入
    facts: list[tuple[str, Any, str]] = field(default_factory=list)   # 事实：内容 + 来源
    eligible: bool | None = None                # 结论
    overwrites: int = 0                         # 计数

    def add_fact(self, key: str, value: Any, source: str) -> None:
        self.facts.append((key, value, source))

    def fact(self, key: str, default: Any = None) -> Any:
        """同名事实取最新一条。"""
        for k, v, _ in reversed(self.facts):
            if k == key:
                return v
        return default

    def set_conclusion(self, value: bool) -> None:
        if self.eligible is not None and value != self.eligible:
            self.overwrites += 1
        self.eligible = value

    def version(self) -> int:
        """事实只增，条数天然是一个单调版本号。"""
        return len(self.facts)


# ---------------------------------------------------------------- 同一问题，三个版本的代价

def sample_messages() -> list[dict]:
    """一段六条消息的历史：两次调用 get_order，参数完全相同。"""
    call = {"id": "c1", "type": "function",
            "function": {"name": "get_order", "arguments": '{"order_id": "A1001"}'}}
    call2 = {"id": "c2", "type": "function",
             "function": {"name": "get_order", "arguments": '{"order_id": "A1001"}'}}
    return [
        {"role": "user", "content": "订单 A1001 还能退吗"},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"status": "已签收", "signed_days_ago": 3}'},
        {"role": "assistant", "content": None, "tool_calls": [call2]},
        {"role": "tool", "tool_call_id": "c2", "content": '{"status": "已签收", "signed_days_ago": 3}'},
        {"role": "assistant", "content": "可以退"},
    ]


def scanned_order_ids(messages: list[dict]) -> tuple[list[str], int]:
    """V1 的做法：扫全量历史，解析每个工具调用的参数，再去重。"""
    seen: list[str] = []
    parsed = 0
    for m in messages:
        for call in m.get("tool_calls") or []:
            if call["function"]["name"] != "get_order":
                continue
            args = json.loads(call["function"]["arguments"])
            parsed += 1
            if args["order_id"] not in seen:
                seen.append(args["order_id"])
    return seen, parsed


# ---------------------------------------------------------------- 并发写对照

def run_two(branch) -> None:
    """两个线程在同一道 barrier 上同时起跑。"""
    barrier = threading.Barrier(2)
    ts = [threading.Thread(target=branch, args=(barrier, i)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def overwrite_trial() -> tuple[int, int]:
    """读-改-写：两个分支各读一次旧值，再写回，必然丢一次。"""
    state = {"count": 0}

    def branch(barrier: threading.Barrier, i: int) -> None:
        barrier.wait()                      # 两个分支都先读到 0
        current = state["count"]
        time.sleep(0.005)                   # 放大读写之间的窗口
        state["count"] = current + 1

    run_two(branch)
    return state["count"], 2


def concat_trial() -> tuple[int, int]:
    """拼接后重新赋值：看着像追加，实际是整体换掉引用。"""
    state: dict[str, list[str]] = {"facts": []}

    def branch(barrier: threading.Barrier, i: int) -> None:
        barrier.wait()
        current = state["facts"]            # 读出整个列表
        time.sleep(0.005)
        state["facts"] = current + [f"fact_{i}"]   # 写回整个列表

    run_two(branch)
    return len(state["facts"]), 2


def locked_trial() -> tuple[int, int]:
    """加锁的读-改-写：不丢，但两个分支被串行化。"""
    state = {"count": 0}
    lock = threading.Lock()

    def branch(barrier: threading.Barrier, i: int) -> None:
        barrier.wait()
        with lock:
            current = state["count"]
            time.sleep(0.005)
            state["count"] = current + 1

    run_two(branch)
    return state["count"], 2


def append_trial() -> tuple[int, int]:
    """累加（reducer）：不读旧值，只把新元素并进去。"""
    state: dict[str, list[str]] = {"facts": []}

    def branch(barrier: threading.Barrier, i: int) -> None:
        barrier.wait()
        time.sleep(0.005)
        state["facts"].append(f"fact_{i}")

    run_two(branch)
    return len(state["facts"]), 2


def repeat(trial, rounds: int = 20) -> tuple[int, int]:
    """跑多轮，返回 (丢的轮数, 总轮数)。"""
    lost = 0
    for _ in range(rounds):
        got, expect = trial()
        if got < expect:
            lost += 1
    return lost, rounds


# ---------------------------------------------------------------- 生命周期：版本号与 schema

@dataclass
class TaskState:
    """带版本的结论：事实条数一变，旧结论自动读不到。"""
    intent: str
    facts: list[tuple[str, Any, str]] = field(default_factory=list)
    conclusions: dict[str, tuple[Any, int]] = field(default_factory=dict)
    overwrites: dict[str, int] = field(default_factory=dict)

    def add_fact(self, key: str, value: Any, source: str) -> None:
        self.facts.append((key, value, source))

    def version(self) -> int:
        return len(self.facts)

    def set_conclusion(self, key: str, value: Any) -> None:
        if key in self.conclusions:
            self.overwrites[key] = self.overwrites.get(key, 0) + 1
        self.conclusions[key] = (value, self.version())

    def get_conclusion(self, key: str) -> Any:
        entry = self.conclusions.get(key)
        if entry is None:
            return None
        value, version = entry
        if version < self.version():
            return None                     # 过期视同没有，调用方必须重算
        return value


SCHEMA_V1 = {"intent": "A1001 能退吗", "facts": ["签收 3 天"], "schema_version": 1}


def migrate(raw: dict) -> dict:
    """读旧检查点：补默认值、换名字，不猜语义。"""
    if raw.get("schema_version") == 1:
        raw = dict(raw)
        raw["facts"] = [{"key": f"fact_{i}", "value": v, "source": "v1"}
                        for i, v in enumerate(raw["facts"])]
        raw["conclusions"] = {}
        raw["schema_version"] = 2
    return raw


ORDERS = {"A1001": {"status": "已签收", "signed_days_ago": 3, "channel": "app"}}


def store_raw(state: dict, key: str, payload: dict) -> None:
    """反例：把整份工具返回塞进状态。"""
    state.setdefault("data", {})[key] = payload


@dataclass
class V3b:
    """结构化状态：只放需要跨步骤保持一致的内容。"""
    user_intent: str = ""
    facts: list[str] = field(default_factory=list)
    eligible: bool | None = None


@dataclass
class Run:
    state: V3b = field(default_factory=V3b)              # 结构化，几 KB
    messages: list[dict] = field(default_factory=list)   # 历史，可能几百 KB
    trace: list[str] = field(default_factory=list)       # 轨迹，用于归因


def pad(text: str, width: int) -> str:
    """按显示宽度补空格：一个中文字符占两列。"""
    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - shown)


# ---------------------------------------------------------------- 打印

def main() -> None:
    print("=== 1. State 的三个演进版本 ===")
    titles = {V1: "V1 等于聊天记录", V2: "V2 抽出任务字段", V3: "V3 按生命周期分类"}
    categories = {"user_intent": "输入", "facts": "事实", "eligible": "结论",
                  "overwrites": "计数", "messages": "历史"}
    for cls in (V1, V2, V3):
        print(f"  {titles[cls]}")
        for f in dataclasses.fields(cls):
            note = categories.get(f.name, "") if cls is V3 else ""
            print(f"    {pad(f.name, 12)} {pad(f.type, 26)} {note}".rstrip())
    print()

    print("=== 2. 从历史推断状态：全量与裁剪后 ===")
    msgs = sample_messages()
    ids, parsed = scanned_order_ids(msgs)
    print(f"  全量：扫 {len(msgs)} 条消息，解析 {parsed} 次工具调用，去重后 {ids}")
    tail = msgs[-1:]
    tail_ids, tail_parsed = scanned_order_ids(tail)
    print(f"  裁剪到最近 1 条：扫 {len(tail)} 条消息，解析 {tail_parsed} 次工具调用，得到 {tail_ids}")
    print("  同一个任务，历史一裁，答案就变了")
    print()

    print("=== 3. 三个版本回答「查过订单 A1001 吗」 ===")
    print(f"  V1: 扫 {len(msgs)} 条消息，解析 {parsed} 次工具调用，去重后 {ids}")

    v2 = V2(messages=msgs, order_id="A1001")
    print(f"  V2: 判空一次，order_id={v2.order_id!r}")

    v3 = V3(messages=msgs, user_intent="A1001 能退吗")
    v3.add_fact("signed_days", 3, "get_order")
    v3.add_fact("window_days", 7, "get_policy")
    print(f"  V3: 读 facts，得到 {v3.facts}")
    print(f"      fact('signed_days')={v3.fact('signed_days')}，版本={v3.version()}")
    print()

    print("=== 4. State、messages、trace 三份并列 ===")
    r = Run()
    r.state.user_intent = "A1001 能退吗"
    r.state.facts.append("签收 3 天")
    r.messages = sample_messages()
    r.trace = ["router:refund", "tool:get_order ok"]
    print(f"  state 字段 {list(dataclasses.asdict(r.state))}")
    print(f"  state 事实 {len(r.state.facts)} 条，messages {len(r.messages)} 条，trace {len(r.trace)} 条")
    state_bytes = len(json.dumps(dataclasses.asdict(r.state), ensure_ascii=False).encode("utf-8"))
    msg_bytes = len(json.dumps(r.messages, ensure_ascii=False).encode("utf-8"))
    print(f"  序列化后 state {state_bytes} 字节，messages {msg_bytes} 字节")
    print()

    print("=== 5. 反例：整份工具返回塞进状态 ===")
    raw: dict = {}
    store_raw(raw, "order", ORDERS["A1001"])
    print(f"  存进去的键: {sorted(raw['data']['order'])}")
    order = raw["data"]["order"]
    print(f"  投影时会带上: status={order['status']}, "
          f"signed_days_ago={order['signed_days_ago']}, channel={order['channel']}")
    print("  channel 对判定没用，但它已经成了状态的一个字段")
    print()

    print("=== 6. 结论的生命周期：事实一变，旧结论失效 ===")
    s = TaskState(intent="A1001 能退吗")
    print(f"  步骤 0  版本 {s.version()}  eligible={s.get_conclusion('eligible')}")
    s.add_fact("signed_days", 3, "get_order")
    print(f"  步骤 1  版本 {s.version()}  eligible={s.get_conclusion('eligible')}")
    s.add_fact("window_days", 7, "get_policy")
    s.set_conclusion("eligible", True)
    print(f"  步骤 2  版本 {s.version()}  eligible={s.get_conclusion('eligible')}")
    s.set_conclusion("eligible", False)
    s.set_conclusion("eligible", True)
    print(f"  步骤 3  版本 {s.version()}  eligible={s.get_conclusion('eligible')}，"
          f"改主意 {s.overwrites['eligible']} 次")
    s.add_fact("signed_days", 4, "get_order")   # 订单刚签收，旧的 3 天不再准确
    print(f"  步骤 4  版本 {s.version()}  eligible={s.get_conclusion('eligible')}（过期）")
    print()

    print("=== 7. schema 演进：旧检查点用新代码读 ===")
    print(f"  旧检查点: {json.dumps(SCHEMA_V1, ensure_ascii=False)}")
    upgraded = migrate(SCHEMA_V1)
    print(f"  升级之后: {json.dumps(upgraded, ensure_ascii=False)}")
    print(f"  旧值仍在: facts[0]['value']={upgraded['facts'][0]['value']!r}，"
          f"schema_version={upgraded['schema_version']}")
    print()

    print("=== 8. 两个并行分支写同一字段：丢与不丢 ===")
    for label, trial in (("覆盖写（读-改-写）", overwrite_trial),
                         ("拼接后整体赋值", concat_trial),
                         ("加锁的读-改-写", locked_trial),
                         ("累加写 append", append_trial)):
        lost, rounds = repeat(trial)
        got, expect = trial()
        verdict = "丢" if lost else "不丢"
        print(f"  {pad(label, 18)} {rounds} 次里 {lost:>2} 次丢  "
              f"期望 {expect} 实际 {got}  [{verdict}]")


if __name__ == "__main__":
    main()
