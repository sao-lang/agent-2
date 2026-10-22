"""第 55 章 step3：把装配验收做成可进 CI 的自动检查（离线）。

运行：
    python code/ch55_assembly/step3_acceptance.py

上一级的痛点（step2）：四种装配故障都不会崩溃，只能靠人看。

这一级做什么：把上一级的四种故障变成五条可自动跑的断言 + 一份体检报告。

  · 每条检查都**显式传入被测配置**，不靠全局默认值
  · 判据是差分：正确配置必须全过，错误配置必须失败
  · 全部离线、纯逻辑，不调模型 → 可以进 CI
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ============================================================ 被测对象
@dataclass
class Tool:
    name: str
    source: str
    dangerous: bool = False


ALL_TOOLS: list[Tool] = [
    Tool("git_diff", "local"),
    Tool("read_file", "local"),
    Tool("run_test", "local"),
    Tool("deploy_instance", "local"),
    Tool("delete_user", "local", dangerous=True),
    Tool("mcp__query_order", "mcp:order"),
    Tool("mcp__delete_account", "mcp:user", dangerous=True),
]

CODE_REVIEW_ALLOWED = {"git_diff", "read_file"}
L1_TOKENS = 137
L2_TOKENS = 516


@dataclass
class Harness:
    narrow_tools: bool = True
    guard_in_loop: bool = True
    trace_with_source: bool = True
    unload_l2: bool = True
    max_steps: int = 5


@dataclass
class Turn:
    visible: list[str] = field(default_factory=list)
    called: list[tuple[str, str]] = field(default_factory=list)  # (name, source)
    blocked: list[str] = field(default_factory=list)
    context_tokens: int = 0


def visible_of(h: Harness, explicit: set[str] | None) -> set[str]:
    if explicit is not None:
        return set(explicit)
    return CODE_REVIEW_ALLOWED if h.narrow_tools else {t.name for t in ALL_TOOLS}


def run_one(h: Harness, steps: list[str], explicit_visible: set[str] | None = None,
            carry: int = 0) -> Turn:
    """跑一轮。

    carry = 此前轮次**遗留下来**的 token（不含本轮 L1）。
    本轮实际上下文 = carry + L1 常驻 + 本轮命中的 L2 正文。
    """
    vis = visible_of(h, explicit_visible)
    t = Turn(visible=sorted(vis))
    t.context_tokens = carry + L1_TOKENS + L2_TOKENS

    for i, name in enumerate(steps, 1):
        if i > h.max_steps:
            break
        tool = next((x for x in ALL_TOOLS if x.name == name), None)
        if tool is None:
            continue
        must_check = h.guard_in_loop or i == 1
        if must_check and tool.dangerous:
            t.blocked.append(name)
            continue
        if name not in vis:
            continue
        t.called.append((name, tool.source if h.trace_with_source else ""))
    return t


# ============================================================ 检查项
@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def check_tool_narrowing(h: Harness) -> Check:
    """有 skill 时，可见工具数必须小于全量。"""
    full = len(ALL_TOOLS)
    narrow = len(CODE_REVIEW_ALLOWED) if h.narrow_tools else full
    return Check("① 工具收窄", narrow < full, f"全量 {full} → 可见 {narrow}")


def check_guard_in_loop(h: Harness) -> Check:
    """第 2 步起的危险工具必须也被拦。"""
    steps = ["git_diff", "delete_user", "mcp__delete_account"]
    t = run_one(h, steps, explicit_visible=set(steps))
    return Check("② Guard 在循环内", len(t.blocked) == 2, f"拦截 {len(t.blocked)}/2 个危险调用")


def check_trace_source(h: Harness) -> Check:
    """每条工具调用都必须带来源。"""
    steps = ["git_diff", "mcp__query_order"]
    t = run_one(h, steps, explicit_visible=set(steps))
    missing = [n for n, src in t.called if not src]
    return Check("③ trace 带来源", bool(t.called) and not missing,
                 f"{len(t.called)} 次调用，缺来源 {len(missing)} 条")


def check_context_stable(h: Harness) -> Check:
    """检查「上下文是否恒定」这个性质本身是否成立。

    正确配置 → 恒定（PASS）；L2 跨轮保留 → 单调增长（FAIL）。
    """
    leaked = 0  # 此前轮次遗留的 L2 正文
    first = run_one(h, ["git_diff"], carry=0).context_tokens
    last = first
    for _ in range(5):
        last = run_one(h, ["git_diff"], carry=leaked).context_tokens
        if not h.unload_l2:
            leaked += L2_TOKENS  # 本轮 L2 正文留在上下文里，累加到下一轮
    stable = last == first
    return Check("④ 上下文恒定", stable, f"第1轮 {first} → 第6轮 {last}")


def check_step_limit(h: Harness) -> Check:
    """步数上限必须存在、有限，且真的能截断过多步骤。"""
    steps = ["git_diff", "read_file", "run_test", "deploy_instance", "mcp__query_order"]
    t = run_one(h, steps, explicit_visible=set(steps))
    # 判据一：上限必须是有限小值（99 这种等于没有）
    bounded = 0 < h.max_steps <= 10
    # 判据二：计划 5 步时，若上限 < 5 必须被截断
    truncated = len(t.called) <= h.max_steps
    ok = bounded and truncated
    return Check("⑤ 步数上限", ok,
                 f"max_steps={h.max_steps}，计划 5 步实际执行 {len(t.called)} 步"
                 + ("" if bounded else "（上限过大，等于没限）"))


CHECKS = [
    ("① 工具收窄", check_tool_narrowing),
    ("② Guard 在循环内", check_guard_in_loop),
    ("③ trace 带来源", check_trace_source),
    ("④ 上下文恒定", check_context_stable),
    ("⑤ 步数上限", check_step_limit),
]


def evaluate(h: Harness, label: str) -> int:
    print(f"\n  {label}")
    print(f"  {'检查项':<20}{'结果':<8}详情")
    print("  " + "-" * 86)
    n_pass = 0
    for name, fn in CHECKS:
        c = fn(h)
        n_pass += c.passed
        print(f"  {name:<20}{'PASS' if c.passed else 'FAIL':<8}{c.detail}")
    print(f"\n  {n_pass} / {len(CHECKS)} 通过")
    return n_pass


def main() -> None:
    print("=" * 90)
    print("Harness 装配验收（离线，可进 CI）")
    print("=" * 90)
    print("  被测的是一份 Harness 配置，不是模型表现。")
    print("  所以不需要 API Key、不需要网络，毫秒级跑完。")

    n_good = evaluate(Harness(), "A. 正确装配")

    print("\n" + "=" * 90)
    print("B. 逐个装错，看检查能不能抓到")
    print("=" * 90)
    faults = [
        ("工具不分组", Harness(narrow_tools=False)),
        ("Guard 在循环外", Harness(guard_in_loop=False)),
        ("trace 无来源", Harness(trace_with_source=False)),
        ("L2 跨轮保留", Harness(unload_l2=False)),
        ("无步数上限", Harness(max_steps=99)),
    ]
    caught = 0
    print(f"  {'装错方式':<18}{'失败的检查项':<30}结果")
    print("  " + "-" * 86)
    for label, h in faults:
        failed = [name for name, fn in CHECKS if not fn(h).passed]
        if failed:
            caught += 1
        print(f"  {label:<18}{'、'.join(failed) if failed else '（没抓到）':<30}"
              f"{'✓ 抓到' if failed else '✗ 漏掉'}")

    print()
    print(f"  5 种装错，抓到 {caught} 种。正确装配 {n_good}/{len(CHECKS)} 通过。")

    print("\n" + "=" * 90)
    print("C. 为什么这套检查值得进 CI")
    print("=" * 90)
    for a, b in [
        ("不需要模型", "纯逻辑断言，不花 token，不引入随机性"),
        ("毫秒级", "每次提交都能跑，不拖慢流水线"),
        ("差分判据", "正确必须全过、错误必须失败，两条都验证"),
        ("防回归", "新人改 Harness 时误删 Guard，CI 立刻红"),
    ]:
        print(f"  · {a:<12}{b}")

    print("\n" + "=" * 90)
    print("D. 装配验收清单（抄进你的项目）")
    print("=" * 90)
    for item in [
        "有 skill 时工具数必须收窄，并在日志里打印实际可见数",
        "Guard 在每一次工具调用前执行，不是每轮一次",
        "每条工具调用日志都带 source（local / mcp:服务名）",
        "每轮上下文 token 数应恒定，不能单调增长",
        "max_steps 有上限，且超限时记录停止原因",
        "工具重名时直接报错，不要静默覆盖",
    ]:
        print(f"  [ ] {item}")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · 装配验收不是「跑个 demo 看看」，是**可自动化的断言**。")
    print("  · 差分判据：正确必须全过 + 错误必须失败，缺一不可。")
    print("  · 全部离线，能进 CI —— 这才是 Harness 能长期维护的前提。")
    print("  · 到这里你有了一个能跑、能测、能定位问题的 Harness。")
    print()
    print("  下一章（55）：故障复盘方法论 —— 把一次事故变成一条用例。")

    assert n_good == len(CHECKS), f"正确装配应全部通过，实际 {n_good}/{len(CHECKS)}"
    assert caught == len(faults), f"应抓到全部 {len(faults)} 种装错，实际 {caught}"


if __name__ == "__main__":
    main()
