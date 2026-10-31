"""同一任务在五种拓扑下的成本账。

不联网。agent 是脚本化替身，按固定剧本返回文本；耗时是虚拟时钟，不是实测。
目的只有一个：把"几个 agent、几条消息、多少上下文、多长时间"数出来，
而不是证明哪种拓扑答得更好。

任务：读三份日志，找出错误，写一份结论。
  - 每份日志 3000 字符
  - 每个 worker 的结论 300 字符
  - 最终报告 500 字符
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOG_CHARS = 3000
BRIEF_CHARS = 300
REPORT_CHARS = 500
CALL_MS = 1000          # 一次模型调用 1.0s
HANDOFF_MS = 200        # 一次交接 0.2s
TOKENS_PER_CHAR = 0.6   # 粗略换算，只用来看相对大小


@dataclass
class Reply:
    text: str
    chars: int


@dataclass
class Call:
    agent: str
    purpose: str
    prompt_chars: int
    at_ms: int


@dataclass
class World:
    """虚拟时钟 + 调用记录。所有 agent 共用一个世界。"""

    now_ms: int = 0
    calls: list[Call] = field(default_factory=list)
    handoffs: int = 0

    def advance(self, ms: int) -> None:
        self.now_ms += ms

    def call(self, agent: str, purpose: str, prompt: str, reply_chars: int) -> Reply:
        self.calls.append(Call(agent, purpose, len(prompt), self.now_ms))
        self.advance(CALL_MS)
        return Reply(f"[{agent}:{purpose}]" + "x" * reply_chars, reply_chars)

    def handoff(self) -> None:
        self.handoffs += 1
        self.advance(HANDOFF_MS)

    def total_prompt_chars(self) -> int:
        return sum(c.prompt_chars for c in self.calls)

    def tokens(self) -> int:
        return int(self.total_prompt_chars() * TOKENS_PER_CHAR)


LOGS = [f"<log {i}>" + "x" * (LOG_CHARS - 8) for i in range(1, 4)]
FINDINGS = ["连接池在第 42 行耗尽", "重试没有上限", "超时设成 0 等于不超时"]
SYSTEM = 200


def single_agent(w: World) -> str:
    """一个 agent 从头做到尾：三份日志都留在同一个上下文里。"""
    prompt = f"{'x' * SYSTEM}\n任务：读日志找错误并写结论\n" + "\n".join(LOGS)
    w.call("main", "读完三份日志", prompt, 600)
    prompt2 = prompt + "\n上面是全部日志，请写结论"
    return w.call("main", "写结论", prompt2, REPORT_CHARS).text


def supervisor(w: World) -> str:
    """中心调度：worker 各读一份日志，只把 300 字摘要交回。"""
    briefs = []
    for i, log in enumerate(LOGS, 1):
        w.handoff()
        r = w.call(f"worker{i}", f"读第 {i} 份日志", f"{'x' * SYSTEM}\n{log}", BRIEF_CHARS)
        briefs.append(r.text)
    w.handoff()
    prompt = f"{'x' * SYSTEM}\n三份结论：\n" + "\n".join(briefs)
    return w.call("supervisor", "合并成报告", prompt, REPORT_CHARS).text


def handoff(w: World) -> str:
    """控制权转移：第一个人读完后把上下文交给第二个人，自己退出。"""
    ctx = f"{'x' * SYSTEM}\n任务：读日志找错误并写结论\n"
    for i, log in enumerate(LOGS, 1):
        if i > 1:
            w.handoff()
        prompt = ctx + log + f"\n你是第 {i} 棒，读完把结论写进上下文"
        r = w.call(f"agent{i}", f"第 {i} 棒", prompt, BRIEF_CHARS)
        ctx = f"{'x' * SYSTEM}\n已知结论：{r.text}\n"
    w.handoff()
    return w.call("writer", "收尾写报告", ctx + "请写报告", REPORT_CHARS).text


def blackboard(w: World) -> str:
    """共享工作区：worker 只读任务，写完把发现贴到板上；写者最后读板。"""
    board: list[str] = []
    for i, log in enumerate(LOGS, 1):
        w.handoff()
        prompt = f"{'x' * SYSTEM}\n任务：读日志找错误\n板上已有：{board}\n{log}"
        r = w.call(f"worker{i}", f"读第 {i} 份日志", prompt, BRIEF_CHARS)
        board.append(r.text)
    w.handoff()
    prompt = f"{'x' * SYSTEM}\n任务：写报告\n板上发现：\n" + "\n".join(board)
    return w.call("writer", "读板写报告", prompt, REPORT_CHARS).text


def pipeline(w: World) -> str:
    """流水线：阶段固定，上一阶段的输出就是下一阶段的全部输入。"""
    merged = "\n".join(LOGS)
    r1 = w.call("reader", "合并日志", f"{'x' * SYSTEM}\n{merged}", 900)
    w.handoff()
    r2 = w.call("finder", "找错误", f"{'x' * SYSTEM}\n{r1.text}", 600)
    w.handoff()
    return w.call("writer", "写报告", f"{'x' * SYSTEM}\n{r2.text}", REPORT_CHARS).text


TOPOLOGIES = [
    ("单 agent", single_agent),
    ("supervisor", supervisor),
    ("handoff", handoff),
    ("blackboard", blackboard),
    ("流水线", pipeline),
]


def pad(text: str, width: int) -> str:
    """按显示宽度补齐（一个汉字算两格）。"""
    w = sum(2 if ord(c) > 127 else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    print("=== 1. 同一任务在五种拓扑下 ===")
    print("  " + pad("拓扑", 12) + pad("agent 数", 10) + pad("消息", 6)
          + pad("峰值(字符)", 12) + pad("总上下文", 12) + pad("token 估", 10) + "耗时(ms, 串行)")
    results = []
    for name, fn in TOPOLOGIES:
        w = World()
        fn(w)
        agents = len({c.agent for c in w.calls})
        results.append((name, w, agents))
        print("  " + pad(name, 12) + pad(str(agents), 10) + pad(str(w.handoffs), 6)
              + pad(str(max(c.prompt_chars for c in w.calls)), 12)
              + pad(str(w.total_prompt_chars()), 12) + pad(str(w.tokens()), 10)
              + str(w.now_ms))

    print()
    print("=== 2. 每一次调用看到多少上下文 ===")
    for name, w, _ in results:
        per_call = [c.prompt_chars for c in w.calls]
        print(f"  {pad(name, 12)}{per_call}")

    print()
    print("=== 3. 相对单 agent 的上下文倍数 ===")
    base = results[0][1].total_prompt_chars()
    for name, w, _ in results:
        print(f"  {pad(name, 12)}{w.total_prompt_chars() / base:.2f}x")

    print()
    print("=== 4. 交接次数与串行链路 ===")
    for name, w, _ in results:
        waiters = list(dict.fromkeys(c.agent for c in w.calls))
        print(f"  {pad(name, 12)}交接 {w.handoffs} 次，串行经过：{' -> '.join(waiters)}")
    print("  <- 这里的耗时按全部串行计；能并行的分支见正文 6.3 的加速比公式")


if __name__ == "__main__":
    main()
