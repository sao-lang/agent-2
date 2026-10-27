"""上下文四槽位的装配，以及"任务状态"与"聊天记录"两种表示的差别。

不联网。token 用"非空白字符数"当估算口径（第 3 章讲过它只是估算，
这里比的是相对大小，不做绝对换算）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


def est(text: str) -> int:
    """估算 token：按非空白字符数计。三处用法一致，比较才成立。"""
    return sum(1 for c in text if not c.isspace())


# ---------------------------------------------------------------- 四槽位

@dataclass
class Slots:
    """四类内容的预算。总和不能超过窗口减去预留输出。"""
    window: int = 1200
    reserve_out: int = 200
    system_pct: float = 0.10
    task_pct: float = 0.15
    memory_pct: float = 0.25

    def budget(self) -> dict[str, int]:
        usable = self.window - self.reserve_out
        fixed = int(usable * (self.system_pct + self.task_pct + self.memory_pct))
        return {
            "system": int(usable * self.system_pct),
            "task": int(usable * self.task_pct),
            "memory": int(usable * self.memory_pct),
            "retrieval": usable - fixed,
        }


def shrink(text: str, budget: int, strategy: str) -> tuple[str, bool]:
    """把一段文字压到预算内。返回 (结果, 是否被压缩过)。"""
    if est(text) <= budget:
        return text, False

    if strategy == "tail":
        # 保尾部：最近几轮最重要
        out = ""
        for line in reversed(text.splitlines()):
            if est(out) + est(line) > budget:
                break
            out = line + "\n" + out
    elif strategy == "head":
        # 保头部：任务描述与开头最重要
        out = ""
        for line in text.splitlines():
            if est(out) + est(line) > budget:
                break
            out += line + "\n"
    elif strategy == "summary":
        # 摘要：只留每段的第一句
        out = ""
        for line in text.splitlines():
            head = line.split("。")[0]
            if est(out) + est(head) > budget:
                break
            out += head + "\n"
    else:
        raise ValueError(strategy)
    return (out.strip() or "（已省略）"), True


SYSTEM_TEXT = "你是电商客服，只处理退货问题。不要承诺政策以外的内容。"
TASK_TEXT = "判断 A1001 是否符合退货条件，并给出下一步。"
RETRIEVED = (
    "第3条 质量问题退货，运费由商家承担，7 天内提交凭证。\n"
    "第4条 非质量问题退货，商品需保持未拆封。\n"
    "第5条 生鲜类商品不支持无理由退货。\n"
    "第6条 发票可在订单页申请，开票时限为下单后 30 天。"
)


# ---------------------------------------------------------------- 装配

def assemble(system: str, task: str, memory: str, retrieved: str, s: Slots) -> dict:
    """四槽位装配。每个槽位独立压缩，不互相挤占。"""
    b = s.budget()
    parts, shrunk = {}, []
    for key, text, strategy in (
        ("system", system, "head"),
        ("task", task, "head"),
        ("memory", memory, "summary"),
        ("retrieval", retrieved, "tail"),
    ):
        out, was = shrink(text, b[key], strategy)
        parts[key] = out
        if was:
            shrunk.append(key)
    total = sum(est(v) for v in parts.values())
    return {"slots": b, "parts": parts, "used": total,
            "room": s.window - s.reserve_out - total, "shrunk": shrunk}


def assemble_uniform(system: str, task: str, memory: str, retrieved: str, s: Slots) -> dict:
    """反例：不做槽位，四段拼成一条再按行截断。排在前面的吃掉全部预算。"""
    joined = "\n".join([system, task, memory, retrieved])
    out, was = shrink(joined, s.window - s.reserve_out, "head")
    return {"used": est(out), "shrunk": was, "text": out}


# ---------------------------------------------------------------- 两种表示

@dataclass
class ChatMemory:
    """表示一：把整段对话当上下文。"""
    turns: list[str] = field(default_factory=list)

    def add(self, turn: str) -> None:
        self.turns.append(turn)

    def render(self) -> str:
        return "\n".join(self.turns)


@dataclass
class TaskState:
    """表示二：只留任务需要的事实字段。"""
    order_id: str | None = None
    signed_days: int | None = None
    window_days: int | None = None
    asked_shipping: bool = False

    def render(self) -> str:
        return (f"订单 {self.order_id}；已签收 {self.signed_days} 天；"
                f"政策窗口 {self.window_days} 天；已问过物流={self.asked_shipping}")


DIALOG = [
    "用户：你好，我想问一下退货的事",
    "助手：您好，请问是哪一笔订单？",
    "用户：A1001，上周三收到的",
    "助手：好的，A1001 已签收 3 天。您想退货是因为什么呢？",
    "用户：东西有点问题，不太满意",
    "助手：了解，可能是质量问题，我先看看政策窗口。",
    "用户：对了，物流怎么查",
    "助手：在订单页可以直接查看物流。",
    "用户：那我这个还能退吗",
]

FILLER = ["用户：好的，谢谢。", "助手：不客气，还有其他问题吗？"] * 40


def main() -> None:
    s = Slots()
    b = s.budget()
    print("=== 1. 四槽位的预算 ===")
    print(f"  窗口 {s.window}  预留输出 {s.reserve_out}  可用 {s.window - s.reserve_out}")
    print(f"  system={b['system']}  task={b['task']}  memory={b['memory']}  retrieval={b['retrieval']}")

    print()
    print("=== 2. 同一段对话，两种表示 ===")
    chat = ChatMemory()
    for t in DIALOG:
        chat.add(t)
    state = TaskState(order_id="A1001", signed_days=3, window_days=7, asked_shipping=True)
    print(f"  聊天记录 {est(chat.render())} 字符：")
    for line in chat.render().splitlines():
        print(f"    {line}")
    print(f"  任务状态 {est(state.render())} 字符：")
    print(f"    {state.render()}")

    print()
    print("=== 3. 对话变长之后，两种表示的增长 ===")
    for rounds in (0, 20, 40, 80):
        c = ChatMemory(turns=DIALOG + FILLER[:rounds])
        print(f"  第 {9 + rounds:>3} 轮：聊天记录 {est(c.render()):>4} 字符  "
              f"任务状态 {est(state.render()):>3} 字符")

    print()
    print("=== 4. 三种压缩策略，同一段历史（预算 60）===")
    long_hist = chat.render() + "\n" + "\n".join(FILLER)
    for text, label in ((chat.render(), "短对话"), (long_hist, "长对话（尾部全是寒暄）")):
        print(f"  {label}：原文 {est(text)} 字符")
        for st in ("head", "tail", "summary"):
            out, _ = shrink(text, 60, st)
            print(f"    {st:<8} {est(out):>3} 字符  {out.replace(chr(10), ' / ')[:56]}")

    print()
    print("=== 5. 四槽位装配一次（短对话）===")
    for label, mem in (("短对话", chat.render()), ("长对话", long_hist)):
        r = assemble(SYSTEM_TEXT, TASK_TEXT, mem, RETRIEVED, s)
        print(f"\n  [{label}] 记忆槽 {est(mem)} 字符")
        for k, v in r["parts"].items():
            print(f"    {k:<9} {est(v):>3} / {r['slots'][k]:>3}")
        print(f"    合计 {r['used']}  余量 {r['room']}  被压缩的槽位 {r['shrunk'] or '无'}")
        if "retrieval" in r["shrunk"]:
            print(f"    检索槽被压成：{r['parts']['retrieval'].replace(chr(10), ' / ')}")

    print()
    print("=== 6. 不做槽位的反例：四段拼成一条再截断 ===")
    big_system = "你是电商客服。可用工具：订单查询、政策查询、发票申请、物流查询、工单创建。" * 6
    big_retrieved = RETRIEVED * 3
    u = assemble_uniform(big_system, TASK_TEXT, long_hist, big_retrieved, s)
    total = est(big_system) + est(TASK_TEXT) + est(long_hist) + est(big_retrieved)
    print(f"  拼接总计 {total} 字符，截断后 {u['used']} 字符")
    tail = u["text"].replace("\n", " / ")[-64:]
    print(f"  截断后的尾部：...{tail}")
    print(f"  检索到的政策是否还在：{'在' if '第6条' in u['text'] else '不在了'}")

    r3 = assemble(big_system, TASK_TEXT, long_hist, big_retrieved, s)
    print(f"  按槽位装配后：retrieval {est(r3['parts']['retrieval'])} 字符"
          f"（{'含第6条' if '第6条' in r3['parts']['retrieval'] else '不含第6条'}）")


if __name__ == "__main__":
    main()
