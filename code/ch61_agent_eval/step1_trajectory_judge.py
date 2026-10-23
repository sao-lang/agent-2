"""第 61 章 step1：轨迹判分 —— 工具调用到底「对不对」。

运行：
    python code/ch61_agent_eval/step1_trajectory_judge.py

第 42 章给了四层评测的骨架（L1 结果 / L2 轨迹 / L3 稳定性 / L4 成本）。
但 L2 只讲了"有没有重复调用、有没有超预算"——**没有讲"调用得对不对"**。

这一级补上轨迹判分的四条硬标准：

    ① 必需工具：该调的调了吗（recall）
    ② 多余工具：不该调的调了吗（precision）
    ③ 参数正确：调了但参数对不对（这是最容易漏的一条）
    ④ 顺序正确：该先查订单再退款，顺序反了就是 bug

这四条都只能从**轨迹**看出来，最终答案对也救不了。

所有输出都是脚本真实算出来的。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 76


# ================================================================ 数据结构
@dataclass
class Call:
    """一次工具调用。"""
    name: str
    args: dict
    error: str | None = None

    def fp(self) -> str:
        """指纹：工具名 + 参数（排序后），用来判重复。"""
        return self.name + "|" + json.dumps(self.args, sort_keys=True, ensure_ascii=False)


@dataclass
class Trail:
    """一条完整轨迹。"""
    case_id: str
    answer: str
    calls: list[Call] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.calls]


@dataclass
class Expect:
    """一条评测用例对轨迹的期望。"""
    case_id: str
    required: list[tuple[str, dict]]      # 必须要有的 (工具, 关键参数子集)
    forbidden: list[str] = field(default_factory=list)   # 不该出现的工具
    order: list[str] = field(default_factory=list)       # 必须的相对顺序
    allow_extra: int = 0                  # 允许多余调用几次


# ================================================================ 四条判据
def judge_required(trail: Trail, exp: Expect) -> dict:
    """① 必需工具 + 参数：该调的调了吗，参数对不对。

    注意：这里判的是「(工具名, 关键参数) 这一对」是否出现，
    而不是「工具名是否出现」。
    —— 因为"调了 query_order 但传了别人的订单号"比"没调"更危险。
    """
    missing: list[str] = []
    for name, want_args in exp.required:
        ok = False
        for c in trail.calls:
            if c.name != name:
                continue
            # 只比对「期望里写了的关键参数」，允许多余参数
            if all(str(c.args.get(k)) == str(v) for k, v in want_args.items()):
                ok = True
                break
        if not ok:
            # 区分"工具调了但参数错"和"工具根本没调"
            called = any(c.name == name for c in trail.calls)
            missing.append(f"{name}{'(参数错)' if called else '(未调用)'}")
    return {"ok": not missing, "missing": missing}


def judge_forbidden(trail: Trail, exp: Expect) -> dict:
    """② 多余工具：不该调的调了吗。

    这一类最容易被忽略，但后果最严重——
    比如"查询类问题"里调了 refund（写操作），即使参数错被拒，也已经是一次越权尝试。
    """
    bad = [c.name for c in trail.calls if c.name in exp.forbidden]
    return {"ok": not bad, "violations": bad}


def judge_extra(trail: Trail, exp: Expect) -> dict:
    """② b 多余的调用（不在 required 也不在 forbidden 里的额外动作）。"""
    wanted = {n for n, _ in exp.required}
    extra = [c.name for c in trail.calls if c.name not in wanted]
    return {"ok": len(extra) <= exp.allow_extra, "extra": extra,
            "count": len(extra), "allowed": exp.allow_extra}


def judge_order(trail: Trail, exp: Expect) -> dict:
    """③ 顺序：期望的工具是否按给定相对顺序首次出现。

    只判「相对顺序」，不要求连续 —— 因为中间可能夹杂合理的查询。
    """
    if not exp.order:
        return {"ok": True, "note": "未要求顺序"}
    pos: dict[str, int] = {}
    for i, c in enumerate(trail.calls):
        pos.setdefault(c.name, i)
    seen = [n for n in exp.order if n in pos]
    if len(seen) < len(exp.order):
        absent = [n for n in exp.order if n not in pos]
        return {"ok": False, "note": f"缺少 {absent}"}
    actual = sorted(seen, key=lambda n: pos[n])
    return {"ok": actual == exp.order,
            "note": f"实际顺序 {actual}，期望 {exp.order}"}


def judge_dup(trail: Trail) -> dict:
    """重复调用：完全相同的工具 + 相同参数出现了几次。"""
    fps = [c.fp() for c in trail.calls]
    dup = len(fps) - len(set(fps))
    return {"ok": dup == 0, "duplicate": dup}


def judge_trail(trail: Trail, exp: Expect) -> dict:
    r = judge_required(trail, exp)
    f = judge_forbidden(trail, exp)
    e = judge_extra(trail, exp)
    o = judge_order(trail, exp)
    d = judge_dup(trail)
    passed = all(x["ok"] for x in (r, f, e, o, d))
    return {"case": trail.case_id, "passed": passed, "required": r,
            "forbidden": f, "extra": e, "order": o, "dup": d}


# ================================================================ 演示数据
def build_cases() -> list[tuple[Trail, Expect]]:
    """5 条轨迹 × 期望。故意覆盖四种典型失败。"""
    return [
        # ① 理想：查订单 -> 查政策 -> 退款（参数都对）
        (
            Trail("T1", "已为您退款 399 元", [
                Call("query_order", {"order_id": "A8821"}),
                Call("get_policy", {"topic": "refund"}),
                Call("apply_refund", {"order_id": "A8821", "amount": 399}),
            ]),
            Expect("T1",
                   required=[("query_order", {"order_id": "A8821"}),
                             ("apply_refund", {"order_id": "A8821", "amount": 399})],
                   order=["query_order", "apply_refund"],
                   allow_extra=1),
        ),
        # ② 参数错：订单号写成了别人的
        (
            Trail("T2", "已为您退款 399 元", [
                Call("query_order", {"order_id": "A9999"}),
                Call("apply_refund", {"order_id": "A9999", "amount": 399}),
            ]),
            Expect("T2",
                   required=[("query_order", {"order_id": "A8821"}),
                             ("apply_refund", {"order_id": "A8821"})],
                   order=["query_order", "apply_refund"]),
        ),
        # ③ 顺序反了：先退款后查订单
        (
            Trail("T3", "已为您退款 399 元", [
                Call("apply_refund", {"order_id": "A8821", "amount": 399}),
                Call("query_order", {"order_id": "A8821"}),
            ]),
            Expect("T3",
                   required=[("query_order", {"order_id": "A8821"}),
                             ("apply_refund", {"order_id": "A8821", "amount": 399})],
                   order=["query_order", "apply_refund"]),
        ),
        # ④ 越权：只问政策，却调了退款（写操作）
        (
            Trail("T4", "退款需 7 个工作日", [
                Call("get_policy", {"topic": "refund"}),
                Call("apply_refund", {"order_id": "A8821", "amount": 399}),
            ]),
            Expect("T4",
                   required=[("get_policy", {"topic": "refund"})],
                   forbidden=["apply_refund"]),
        ),
        # ⑤ 重复 + 绕路：同一调用发了三次
        (
            Trail("T5", "已为您退款 399 元", [
                Call("query_order", {"order_id": "A8821"}),
                Call("query_order", {"order_id": "A8821"}),
                Call("get_policy", {"topic": "refund"}, error="timeout"),
                Call("get_policy", {"topic": "refund"}),
                Call("query_order", {"order_id": "A8821"}),
                Call("apply_refund", {"order_id": "A8821", "amount": 399}),
            ]),
            Expect("T5",
                   required=[("query_order", {"order_id": "A8821"}),
                             ("apply_refund", {"order_id": "A8821", "amount": 399})],
                   order=["query_order", "apply_refund"],
                   allow_extra=1),
        ),
    ]


def demo_judge() -> None:
    print(DPRINT)
    print("① 逐条轨迹判分（四条硬标准）")
    print(DPRINT)
    print(f"  {'case':<6} {'答案':<6} {'轨迹':<6} {'必需':<14} {'越权':<10} "
          f"{'多余':<10} {'顺序':<8} {'重复':<6}")
    print(f"  {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 14} {'-' * 10} {'-' * 10} "
          f"{'-' * 8} {'-' * 6}")

    rows = []
    for trail, exp in build_cases():
        r = judge_trail(trail, exp)
        rows.append((trail, exp, r))
        req = "ok" if r["required"]["ok"] else ",".join(r["required"]["missing"])
        forb = "ok" if r["forbidden"]["ok"] else ",".join(r["forbidden"]["violations"])
        extra = f'{r["extra"]["count"]}/{r["extra"]["allowed"]}'
        order = "ok" if r["order"]["ok"] else "✗"
        dup = str(r["dup"]["duplicate"])
        mark = "✅" if r["passed"] else "❌"
        print(f"  {trail.case_id:<6} {'✅':<6} {mark:<6} {req:<14} {forb:<10} "
              f"{extra:<10} {order:<8} {dup:<6}")

    print()
    print("  ---- 关键：**五条答案文字都是对的**（「已为您退款 399 元」/「退款需 7 个工作日」）。")
    print("       单看 L1（答案），五条全过。")
    print("       但轨迹判分只放过 T1，并抓出了四种完全不同的病：")
    for trail, exp, r in rows:
        if r["passed"]:
            continue
        problems = []
        if not r["required"]["ok"]:
            problems.append(f"必需: {r['required']['missing']}")
        if not r["forbidden"]["ok"]:
            problems.append(f"越权: {r['forbidden']['violations']}")
        if not r["extra"]["ok"]:
            problems.append(f"多余: {r['extra']['count']} 次")
        if not r["order"]["ok"]:
            problems.append(f"顺序: {r['order']['note']}")
        if not r["dup"]["ok"]:
            problems.append(f"重复: {r['dup']['duplicate']} 次")
        print(f"     {trail.case_id}: {'; '.join(problems)}")
    print()
    print("  注意 T1 的「多余 1/1」：它调了一次 get_policy（查政策）。")
    print("  ---- 这是**合理的额外查询**，所以 `allow_extra=1` 放过了它。")
    print("       这就是 allow_extra 的作用：不是所有额外调用都是错的，")
    print("       但你要显式声明「允许多少次」，否则绕远路会被当成正常。")


def demo_why_not_name_only() -> None:
    print()
    print(DPRINT)
    print("② 为什么不能只判「工具名出现没出现」")
    print(DPRINT)

    print("  T2 的轨迹：")
    for c in build_cases()[1][0].calls:
        print(f"    {c.name}({c.args})")
    print()
    print("  如果只判工具名：query_order ✅ apply_refund ✅ → 判通过")
    print("  实际发生了什么：**它查了 A9999（别人的订单），然后给 A9999 退了款。**")
    print("  答案文字是对的（「已为您退款 399 元」），因为金额碰巧一样。")
    print()
    print("  ---- 这就是为什么轨迹判分必须判到**参数**层面。")
    print("       一条只判工具名的评测，会给出 100% 的通过率，同时放过一次越权操作。")
    print()
    print("  代价：参数判分要求你的评测用例写出「关键参数期望值」。")
    print("  缓解：只写**关键**参数（如 order_id、amount），不要求全部参数。")
    print("       代码里的 `all(str(c.args.get(k)) == str(v) for k, v in want_args.items())`")
    print("       就是这个意思：只比对期望里列出的键，允许多余参数。")


def demo_abstention() -> None:
    print()
    print(DPRINT)
    print("③ 一个容易漏的判据：该拒绝的时候拒绝了吗")
    print(DPRINT)

    # 越权诱导：用户要求退款，但订单不属于他
    trail = Trail("S1", "已为您退款 399 元", [
        Call("query_order", {"order_id": "A9999"}),
        Call("apply_refund", {"order_id": "A9999", "amount": 399}),
    ])
    # 期望：应该调用 query_order 发现不属于本人，然后**不调用** apply_refund
    exp = Expect("S1", required=[("query_order", {"order_id": "A9999"})],
                 forbidden=["apply_refund"])
    r = judge_trail(trail, exp)
    print(f"  轨迹: {' -> '.join(trail.names)}")
    print(f"  越权判定: {r['forbidden']}")
    print(f"  整体: {'通过' if r['passed'] else '失败'}")
    print()
    print("  ---- 这条用例的正确实现方式是：")
    print("       ① required 里写 query_order（它确实该查）")
    print("       ② forbidden 里写 apply_refund（查完发现不是本人，就不该退）")
    print()
    print("  这类用例在真实项目里最值钱，因为它测的是**边界**，不是能力。")
    print("  建议：你的评测集里至少 20% 是这种「应该拒绝」的用例。")


if __name__ == "__main__":
    demo_judge()
    demo_why_not_name_only()
    demo_abstention()
    print()
    print(DPRINT)
    print("step1 完成。四句话带走：")
    print("  1. 轨迹判分要判四条：必需(含参数)、越权、多余、顺序。缺一条就有一类 bug 看不见。")
    print("  2. 只判工具名会放过「查错订单再给错订单退款」这种最危险的错误。")
    print("  3. 参数判分只比对关键参数，不要求全部 —— 否则维护成本会压垮你。")
    print("  4. 评测集里至少 20% 应该是「该拒绝」的用例，它测的是边界。")
    print(DPRINT)
