"""第 2 章 step3：窗口装不下时会发生什么——三种失败形态（离线）。

运行：
    python code/ch02_token/step3_budget.py

上一级的痛点（step2）：知道钱和 token 的关系了，但还没处理"装不下"这件事——
                     对话越聊越长，某一天它突然答非所问，或者直接报 400。

这一级做什么：把"超窗口"的三种真实失败形态摆出来，并给出一个可用的预算分配器。

  形态 1  静默截断：SDK 或你的代码把早期消息砍掉 → 模型不知道自己被砍了 → 硬答
  形态 2  硬报错    ：超出硬上限 → 直接 400 / context_length_exceeded
  形态 3  阴阳怪气  ：勉强塞进去，但留给输出的空间不足 → 答案被腰斩（finish_reason=length）

然后给一个两层防线：
  ① 事前：预算分配（system / history / retrieval / output_reserve 各占多少）
  ② 事中：超了就压缩历史，而不是砍检索结果
"""
from __future__ import annotations

from dataclasses import dataclass

from common.context import ContextBudget, est_tokens

SYSTEM = (
    "你是某电商平台的售后客服。只根据提供的政策条款回答，"
    "条款里没有的内容必须回答「这条我需要为您转人工确认」。"
    "回答控制在三句话以内。"
)

POLICIES = [
    "第一章 总则：本章适用于平台自营及第三方商家销售的全部实物商品，虚拟商品、服务类商品另有单独规则。"
    "本规则所称「签收」，以物流系统记录的签收时间为准；若为代收点代签，代签时间视为签收时间。"
    "用户对签收时间有异议的，应在发现后 48 小时内提出，逾期视为认可。",
    "第二章 无理由退货：签收后 7 天内，商品未拆封且不影响二次销售的，可申请无理由退货。"
    "「不影响二次销售」是指商品本体、包装、配件、赠品、说明书、保修卡均完整齐备，"
    "且不存在使用痕迹、划痕、水渍、异味、激活记录。外包装轻微挤压不影响判定。",
    "第三章 例外情形：定制类商品、生鲜类商品、已激活的数码产品不适用无理由退货。"
    "已激活是指设备完成开机引导流程并登录账号，或已产生联网记录。"
    "已拆封但未激活的数码产品，仍可申请无理由退货，退回时需保持包装完整。",
    "第四章 质量问题：签收后 15 天内出现非人为损坏的质量问题，可申请换新或退货。"
    "是否属于质量问题，以平台指定检测机构的检测结论为准；检测周期一般为 5 至 7 个工作日。"
    "检测确认为人为损坏的，检测费用由用户承担，且不支持退换。",
    "第五章 运费：退货运费在质量问题情形下由平台承担，在非质量问题情形下由买家承担。"
    "买家承担运费时，若订单享受过满减或包邮优惠，需在退款金额中扣除相应运费。",
    "第六章 优惠券：使用优惠券的订单退款时，已使用的优惠券不返还，且不补发等价积分。"
    "若整单退款且订单未发货，优惠券可原路返还，有效期不变。",
]

HISTORY = [
    ("user", "你好"),
    ("assistant", "您好，请问有什么可以帮您？"),
    ("user", "我上周买了个蓝牙耳机，订单号 A12345，价格 299，用了满 300 减 30 的券"),
    ("assistant", "好的，已记录订单 A12345，实付 269 元。请问有什么问题？"),
    ("user", "右耳一直有滋滋声，安静的时候特别明显，我换了手机连也一样"),
    ("assistant", "了解了。请问是签收后多久发现的？另外耳机是否已经拆封激活？"),
    ("user", "大概第 3 天发现的，拆了，也连过手机登录过小米账号"),
    ("assistant", "明白了。已激活的数码产品无法直接走无理由退货，需要先做质量检测。"),
    ("user", "那我能不能直接退了重新买一个，我不想等检测"),
    ("assistant", "直接退货需要满足无理由条件，已激活的数码产品不适用。"),
    ("user", "可是我这个确实是坏的啊，不是我不想要"),
    ("assistant", "如果确认为质量问题，可以走质量问题退换流程，检测费用由平台承担。"),
    ("user", "检测要多久？这期间我还能用吗"),
    ("assistant", "检测周期一般 5 到 7 个工作日。检测期间商品需寄回，无法使用。"),
    ("user", "那券还会退给我吗？我当时凑单凑到 300 的"),
    ("assistant", "已使用的优惠券在退款时不返还，这一点在规则里有说明。"),
    ("user", "好吧，那我再想想，先不寄了"),
    ("assistant", "好的，您随时可以回来继续处理，订单 A12345 的售后入口一直开着。"),
]

QUESTION = "那我现在到底能不能退？能退多少钱？"


@dataclass
class Attempt:
    """一次装配上下文的结果。"""

    kept_history: int
    kept_policies: int
    input_tokens: int
    output_room: int
    verdict: str


def assemble(window: int, history_limit: int, policy_limit: int, out_need: int) -> Attempt:
    """按"保最新历史 + 保前 N 条政策"装配，返回装进去之后的状况。"""
    hist = HISTORY[-history_limit:] if history_limit else []
    pol = POLICIES[:policy_limit]
    parts = [SYSTEM, *[p for p in pol], *[t for _, t in hist], QUESTION]
    used = sum(est_tokens(p) for p in parts) + 4 * len(parts)
    room = window - used
    if used > window:
        verdict = "形态 2：硬报错（400 context_length_exceeded）"
    elif room < out_need:
        verdict = f"形态 3：输出被腰斩（只有 {room} token 余量，需要 {out_need}）"
    else:
        verdict = "正常"
    return Attempt(len(hist), len(pol), used, room, verdict)


def main() -> None:
    window = 800
    out_need = 300

    print("=" * 88)
    print(f"场景：窗口 {window} token，输出至少需要 {out_need} token")
    print("=" * 88)
    print(f"系统提示   {est_tokens(SYSTEM):>5} token")
    print(f"政策条款   {sum(est_tokens(p) for p in POLICIES):>5} token（共 {len(POLICIES)} 条）")
    print(f"对话历史   {sum(est_tokens(t) for _, t in HISTORY):>5} token（共 {len(HISTORY)} 条）")
    print(f"本轮问题   {est_tokens(QUESTION):>5} token")
    print()

    print("=" * 88)
    print("不加任何预算控制：全塞进去")
    print("=" * 88)
    naive = sum(est_tokens(p) for p in [SYSTEM, *POLICIES, *[t for _, t in HISTORY], QUESTION])
    naive += 4 * (1 + len(POLICIES) + len(HISTORY) + 1)
    print(f"  需要 {naive} token，窗口只有 {window} token")
    print(f"  → 超出 {naive - window} token（{(naive / window - 1):.0%}）")
    print("  → 客户端行为取决于 SDK：")
    print("      · 有的直接报 400，你看到 context_length_exceeded")
    print("      · 有的**默默砍掉最早的消息**，你什么都看不到 ← 更危险")

    print("\n" + "=" * 88)
    print("形态 1/2/3：只保留最新 N 条历史，政策全留")
    print("=" * 88)
    print(f"{'保留历史':>8}{'保留政策':>9}{'输入token':>11}{'输出余量':>10}   判定")
    print("-" * 88)
    for h in (18, 14, 10, 6, 2, 0):
        a = assemble(window, h, len(POLICIES), out_need)
        print(f"{a.kept_history:>8}{a.kept_policies:>9}{a.input_tokens:>11}{a.output_room:>10}   {a.verdict}")

    print("-" * 88)
    print("  看懂这张表的三个要点：")
    print("    ① 保留 18 条 → 输入就爆了，直接报错（形态 2）")
    print("    ② 保留 10~2 条 → 不报错，但输出只剩 128~289 token，答案被腰斩（形态 3）")
    print("    ③ 保留 0 条 → 「正常」了，**但它连用户问过什么都看不见了**")
    print("       → 「不报错」和「答得对」是两件不同的事")

    print("\n" + "=" * 88)
    print("形态 3 的代价：输出余量不足")
    print("=" * 88)
    for room in (400, 300, 150, 50):
        ok = "完整回答" if room >= 250 else ("答案被截断" if room >= 50 else "几乎只能回一个字")
        print(f"  余量 {room:>4} token → {ok}")

    print("\n" + "=" * 88)
    print("两层防线：预算分配器（来自 code/common/context.py）")
    print("=" * 88)
    b = ContextBudget(total=window, system_ratio=0.10, history_ratio=0.25,
                      retrieval_ratio=0.45, output_reserve_ratio=0.20)
    actual = {
        "system": est_tokens(SYSTEM),
        "history": est_tokens("".join(t for _, t in HISTORY[-4:])),
        "retrieval": est_tokens("".join(POLICIES)),
        "output_reserve": out_need,
    }
    print(b.report(actual))

    print("  「预算」= 这个槽位最多能用多少；「实际」= 现在用了多少。")
    print("  超过 100% 的槽位会打 ⚠️——这就是下一步要压缩的地方。")

    print("\n" + "=" * 88)
    print("结论")
    print("=" * 88)
    print("  · 三种失败形态里，**静默截断最危险**：它不报错，只是悄悄答错。")
    print("  · 所以必须在**发请求之前**自己算一遍 token，而不是等模型告诉你。")
    print("  · 预算分配的原则：")
    print("      ① 先扣掉 output_reserve —— 输出空间不够，答案必被腰斩")
    print("      ② 再扣掉 system —— 它一般固定，且不能砍")
    print("      ③ retrieval 和 history 争剩下的空间，**优先保 retrieval**")
    print("         （你需要知道用户问什么，不需要知道上个月聊了什么）")
    print()
    print("  这一章给了「怎么算」，第 24 章给「怎么压」——")
    print("  历史压缩、检索去重、摘要替换，都在那一章。")

    assert assemble(window, 10, len(POLICIES), out_need).input_tokens > 0


if __name__ == "__main__":
    main()
