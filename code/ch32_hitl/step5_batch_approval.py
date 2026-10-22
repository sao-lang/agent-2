"""第 33 章 step5：批量审批与审批体验（离线）。

运行：
    python code/ch32_hitl/step5_batch_approval.py

上一级的痛点：超时和升级都处理了，但人一天要看 94 个卡片（step1 算的），
             还是会疲劳。这一级解决"怎么让 94 个变成 3 个"。

三个手段：
  1. 批量：同类动作、同参数的请求合并成一条
  2. 摘要：卡片先给"一句话结论"，细节折叠
  3. 预置策略：把一类重复决策变成"一次性设定"（例如"100 元以下自动退"）
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

APPROVAL_SECONDS = 28  # 单张卡片的平均处理时间（来自 step1）


@dataclass
class Request:
    id: str
    action: str
    args: dict
    reason: str = ""


@dataclass
class Group:
    """一批可以一起批准的请求。"""

    action: str
    requests: list[Request] = field(default_factory=list)
    signature: str = ""

    @property
    def total_amount(self) -> float:
        return sum(float(r.args.get("amount", 0) or 0) for r in self.requests)


def group_requests(reqs: list[Request]) -> list[Group]:
    """按 (动作, 金额档) 合并；无金额参数的动作用自己的分组键。"""
    """把"同一个动作 + 同一类参数"的请求合并。

    合并键只取**决定风险的那几个参数**（这里是 action + amount 区间），
    而不是把整个 args 序列化 —— 否则订单号不同就合并不了。
    """
    buckets: dict[tuple[str, str], Group] = {}
    for r in reqs:
        if "amount" in r.args:
            amount = float(r.args.get("amount", 0) or 0)
            band = "0-100" if amount < 100 else ("100-500" if amount < 500 else "500+")
            band = f"{amount:.0f} 元档" if amount < 100 else band
        else:
            band = "无金额"
        key = (r.action, band)
        if key not in buckets:
            buckets[key] = Group(action=r.action, signature=f"{r.action}/{band}")
        buckets[key].requests.append(r)
    return list(buckets.values())


def main() -> None:
    # 一天里积压的请求（模拟）
    reqs: list[Request] = []
    for i in range(60):
        reqs.append(Request(f"r{i:02d}", "refund", {"order": f"A{1000 + i}", "amount": 59},
                            reason="7 天无理由退货"))
    for i in range(20):
        reqs.append(Request(f"s{i:02d}", "refund", {"order": f"B{2000 + i}", "amount": 299},
                            reason="质量问题"))
    for i in range(8):
        reqs.append(Request(f"t{i:02d}", "send_email", {"to": f"u{i}@example.com"},
                            reason="补发发票"))
    for i in range(6):
        reqs.append(Request(f"u{i:02d}", "modify_order", {"order": f"C{3000 + i}", "amount": 0},
                            reason="改收货地址"))

    print("=" * 80)
    print("① 逐条审批 vs 批量审批")
    print("=" * 80)
    print(f"  积压请求：{len(reqs)} 条")
    groups = group_requests(reqs)
    print(f"  合并后：{len(groups)} 组")
    print()
    print(f"  {'分组':<22}{'条数':>6}{'合计金额':>12}")
    print("  " + "-" * 44)
    for g in sorted(groups, key=lambda x: -len(x.requests)):
        print(f"  {g.signature:<22}{len(g.requests):>6}{g.total_amount:>12.0f}")

    once = len(reqs) * APPROVAL_SECONDS
    batched = len(groups) * APPROVAL_SECONDS
    print()
    print(f"  逐条：{len(reqs)} × {APPROVAL_SECONDS}s = {once / 60:.0f} 分钟")
    print(f"  批量：{len(groups)} × {APPROVAL_SECONDS}s = {batched / 60:.1f} 分钟"
          f"（省 {(1 - batched / once):.0%}）")

    print("\n" + "=" * 80)
    print("② 卡片信息的分层：一分钟能看完的版本")
    print("=" * 80)
    g = max(groups, key=lambda x: len(x.requests))
    print("  【折叠前 · 完整版】")
    for r in g.requests[:3]:
        print(f"    {r.id}  {r.action}  订单 {r.args['order']}  ¥{r.args['amount']}  （{r.reason}）")
    print(f"    ... 共 {len(g.requests)} 条")
    print()
    print("  【折叠后 · 一眼版】")
    print(f"    {g.action} · {len(g.requests)} 单 · 合计 ¥{g.total_amount:.0f}")
    print(f"    全部为『{g.requests[0].reason}』，单笔金额一致")
    print("    影响：资金不可撤回；可用财务冲正接口在 24h 内撤销")
    print()
    print("  → 人不是拒绝细节，是**需要先看到结论**。")
    print("    把『影响 + 数量 + 一致性』放在第一行，细节折叠在后面。")

    print("\n" + "=" * 80)
    print("③ 预置策略：把重复决策变成一次性设定")
    print("=" * 80)
    policy = [
        ("refund ≤ 100 元 且 7 天无理由", "AUTO", "每天约 60 单"),
        ("refund 100~500 元", "CONFIRM", "每天约 20 单"),
        ("refund > 500 元", "双人确认", "每天约 2 单"),
        ("send_email", "CONFIRM", "每天约 8 单"),
        ("modify_order", "CONFIRM", "每天约 6 单"),
    ]
    print(f"  {'规则':<30}{'级别':<10}{'量'}")
    print("  " + "-" * 58)
    for rule, level, vol in policy:
        print(f"  {rule:<30}{level:<10}{vol}")

    auto = sum(1 for r in reqs if r.action == "refund" and float(r.args["amount"]) <= 100)
    still_confirm = len(reqs) - auto
    print()
    print(f"  预置策略生效后，{auto} 单走自动，人只剩 {still_confirm} 单要处理 ——")
    print(f"  从 {len(reqs)} → {still_confirm}（再降 {(1 - still_confirm / len(reqs)):.0%}）。")

    print("\n" + "=" * 80)
    print("⚠️ 预置策略的三个风险")
    print("=" * 80)
    print("  1. 阈值被利用：坏人会故意拆单到 99 元（『小额拆分攻击』）")
    print("     → 对策：按用户/日累计金额判断，而不是只看单笔")
    print()
    print("  2. 策略过期：业务规则变了，策略没改")
    print("     → 对策：策略带有效期，到期强制复核")
    print()
    print("  3. 自动通过的部分没人抽查")
    print("     → 对策：自动通过的请求按 1%~5% 抽样人工复核，持续评估误判率")

    print("\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    print("  审批体验的三个层次：")
    print("    减少数量 → 分级（step2）+ 预置策略")
    print("    减少时长 → 批量 + 摘要")
    print("    保证质量 → 抽样复核 + 策略有效期")
    print()
    print("  只做前两个不做第三个，你会得到一个『很快』但『不可信』的审批系统。")


if __name__ == "__main__":
    main()
