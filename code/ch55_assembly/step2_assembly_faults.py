"""第 55 章 step2：装配错了会怎样——四种典型故障（离线）。

运行：
    python code/ch55_assembly/step2_assembly_faults.py

上一级的痛点（step1）：Harness 跑通了。但"能跑"和"跑对"是两件事。

这一级做什么：故意把 Harness 装错，看每种错误造成什么后果：

  ① 工具不分组（skill 不收窄工具集）→ 可见工具全量，选错率上升
  ② Guard 放在 Loop 外面（只检查第一次）→ 后续步骤裸奔
  ③ trace 不记工具来源 → 出问题不知道找谁
  ④ skill 常驻不卸载（L2 跨轮保留）→ 上下文越跑越胀

  · 四种都不会让程序崩溃，**这才是危险的地方**
  · 每个都对一个真实项目里的排查场景
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ============================================================ 基础零件
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
    Tool("rollback", "local"),
    Tool("delete_user", "local", dangerous=True),
    Tool("order-mcp__query_order_status", "mcp:order-mcp"),
    Tool("order-mcp__apply_refund", "mcp:order-mcp"),
    Tool("order-mcp__cancel_order", "mcp:order-mcp"),
    Tool("user-mcp__get_profile", "mcp:user-mcp"),
    Tool("user-mcp__update_address", "mcp:user-mcp"),
    Tool("user-mcp__delete_account", "mcp:user-mcp", dangerous=True),
]

CODE_REVIEW_ALLOWED = {"git_diff", "read_file"}


# ============================================================ 变体：装配方式
@dataclass
class Assembly:
    name: str
    narrow_tools: bool          # ① skill 是否收窄工具集
    guard_in_loop: bool         # ② Guard 是否在循环内
    trace_with_source: bool     # ③ trace 是否记来源
    unload_after_turn: bool     # ④ L2 是否每轮卸载


ASSEMBLIES = [
    Assembly("正确装配", True, True, True, True),
    Assembly("① 工具不分组", False, True, True, True),
    Assembly("② Guard 在循环外", True, False, True, True),
    Assembly("③ trace 无来源", True, True, False, True),
    Assembly("④ L2 跨轮保留", True, True, True, False),
]


# ============================================================ 模拟一轮请求
@dataclass
class TurnResult:
    visible_tools: int
    blocked: list[str] = field(default_factory=list)
    unblocked_dangerous: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    context_tokens: int = 0


def run_turn(a: Assembly, steps: list[str], carry_tokens: int = 0,
             force_visible: set[str] | None = None) -> TurnResult:
    """steps 是本轮模型想依次调用的工具名。

    force_visible：本场景只关心 Guard/trace，与工具可见性无关时，
                   用它临时放开可见范围（比如用户直接下危险指令，无 skill 收窄）。
    """
    if force_visible is not None:
        visible_names = set(force_visible)
    elif a.narrow_tools:
        visible_names = set(CODE_REVIEW_ALLOWED)
    else:
        visible_names = {t.name for t in ALL_TOOLS}
    r = TurnResult(visible_tools=len(visible_names))

    loaded_tokens = 516  # code-review 正文
    r.context_tokens = carry_tokens + loaded_tokens

    for i, name in enumerate(steps, 1):
        t = next((x for x in ALL_TOOLS if x.name == name), None)
        if t is None:
            continue

        # Guard：正确装配每次调用前都查；错误装配只在第 1 步查
        should_check = True if a.guard_in_loop else (i == 1)
        if should_check and t.dangerous:
            r.blocked.append(name)
            r.trace.append(f"[blocked] {name}({t.source})" if a.trace_with_source else "[blocked]")
            continue
        if t.dangerous and not should_check:
            r.unblocked_dangerous.append(name)
            r.trace.append(f"[call] {name}({t.source})" if a.trace_with_source else f"[call] {name}")
            continue

        if name not in visible_names:
            r.trace.append(f"[invisible] {name}" if a.trace_with_source else "[invisible]")
            continue
        r.trace.append(f"[call] {name}({t.source})" if a.trace_with_source else f"[call] {name}")
    return r


# ============================================================ 四个故障场景
def fault1_no_narrowing() -> None:
    print("=" * 90)
    print("① 工具不分组：skill 的 allowed-tools 没用上")
    print("=" * 90)
    steps = ["git_diff", "read_file"]
    for a in (ASSEMBLIES[0], ASSEMBLIES[1]):
        r = run_turn(a, steps)
        print(f"  {a.name:<14}可见工具 {r.visible_tools:>2} 个")
    print()
    print("  后果不会立刻显现：这两个请求都能跑对。")
    print("  但第 14 章实测过：工具数 12 → 40 时，选对率从 ~80% 掉到 ~67%。")
    print("  你会听到「明明有 git_diff，它却去读了别的文件」。")
    print()
    print("  排查方向：打印模型实际看到的 manifest 长度。超过 20 条就要警惕。")


def fault2_guard_outside() -> None:
    print("\n" + "=" * 90)
    print("② Guard 在循环外：只检查第一次决策")
    print("=" * 90)
    # 注意：这里故意让危险工具在可见范围内（比如没配 allowed-tools 的 skill，
    # 或用户直接说"删掉这个用户"走了无 skill 分支）
    steps = ["git_diff", "delete_user", "user-mcp__delete_account"]
    print(f"  模型想依次调用：{steps}")
    print()
    for a in (ASSEMBLIES[0], ASSEMBLIES[2]):
        r = run_turn(a, steps, force_visible=set(steps))
        print(f"  {a.name:<16}拦截 {len(r.blocked)} 个，"
              f"**放行危险 {len(r.unblocked_dangerous)} 个** {r.unblocked_dangerous}")
        for line in r.trace:
            print(f"        {line}")
    print()
    print("  这是最危险的一种：程序不崩，测试也过（因为第一次确实被拦了），")
    print("  但第 2、3 步的危险操作**完全没有检查**。")
    print("  真实项目里这等价于「用了几天才发现有张表被删了」。")
    print()
    print("  修法：Guard 必须在**每一次工具调用前**跑，不是每轮跑一次。")


def fault3_no_source() -> None:
    print("\n" + "=" * 90)
    print("③ trace 不记工具来源")
    print("=" * 90)
    steps = ["git_diff", "order-mcp__query_order_status", "user-mcp__get_profile"]
    for a in (ASSEMBLIES[0], ASSEMBLIES[3]):
        r = run_turn(a, steps, force_visible=set(steps))
        print(f"\n  {a.name}：")
        for line in r.trace:
            print(f"      {line}")
    print()
    print("  「③ trace 无来源」的日志里，你只看到工具名。")
    print("  当 order-mcp 返回了错误数据，你要先花时间**猜**是哪个服务。")
    print()
    print("  更糟的情况：两个服务都有 query_order，日志里名字完全一样，")
    print("  你甚至无法确定是谁被调用了。")
    print()
    print("  修法：工具名带命名空间前缀（order-mcp__xxx），trace 记 source 字段。")


def fault4_keep_l2() -> None:
    print("\n" + "=" * 90)
    print("④ L2 跨轮保留：渐进式加载失效")
    print("=" * 90)
    print(f"  {'轮次':<8}{'正确装配':>14}{'L2 跨轮保留':>16}")
    print("  " + "-" * 40)
    keep = 0
    for turn in range(1, 7):
        # 正确：每轮丢弃 L2，只保 L1
        if turn == 1:
            keep = 137 + 516
        else:
            keep += 516  # 每轮加载一个新技能且不卸载
        print(f"  第 {turn} 轮{137 + 516:>14,}{keep:>16,}")
    print()
    print("  正确装配：每轮都是 L1(137) + 当前技能正文(516) = 653，恒定。")
    print("  L2 跨轮保留：每轮 +516，6 轮后 3,233 —— 这就是回到「全塞」。")
    print()
    print("  这个 bug 最难发现，因为**前几轮完全正常**。")
    print("  等到上下文塞满，表现是「突然变笨」，而你还在改提示词。")


def main() -> None:
    print("=" * 90)
    print("四种装配错误，共同点：**都不会让程序崩溃**")
    print("=" * 90)
    print("  这四行对照很关键：")
    print("    错误装配 → 程序能跑 → 测试能过 → 上线几天后才发现")
    print("    正确装配 → 边界清晰 → 指标可测 → 出问题能定位")

    fault1_no_narrowing()
    fault2_guard_outside()
    fault3_no_source()
    fault4_keep_l2()

    print("\n" + "=" * 90)
    print("⑤ 怎么提前发现这四种")
    print("=" * 90)
    checks = [
        ("① 工具不分组", "每轮打印可见工具数", "> 20 就告警"),
        ("② Guard 在循环外", "构造一个「第 2 步调危险工具」的用例", "必须被拦"),
        ("③ trace 无来源", "检查日志里每条 call 有没有 source 字段", "缺就 fail"),
        ("④ L2 跨轮保留", "打印每轮上下文 token 数", "应是恒定的，不能单调涨"),
    ]
    print(f"  {'故障':<20}{'怎么测':<40}判据")
    print("  " + "-" * 86)
    for a, b, c in checks:
        print(f"  {a:<20}{b:<40}{c}")
    print()
    print("  这四条就是 Harness 的**最小回归测试集**。")
    print("  它们都不需要真实模型，纯逻辑就能测——所以应该进 CI。")

    print("\n" + "=" * 90)
    print("结论")
    print("=" * 90)
    print("  · 装配错误最危险的地方是**不报错**。")
    print("  · ① 工具不分组 → 选错率上升（第 14 章数据）")
    print("  · ② Guard 在循环外 → 第 2 步起裸奔（最危险）")
    print("  · ③ trace 无来源 → 出问题找不到人")
    print("  · ④ L2 跨轮保留 → 上下文单调涨，渐进式加载失效")
    print("  · 四条都能用纯逻辑测出来，应该进 CI。")
    print()
    print("  下一级（step3）：把这四种故障做成可自动跑的验收脚本。")


if __name__ == "__main__":
    main()
