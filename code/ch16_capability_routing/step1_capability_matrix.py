"""第 16 章 step1：一个请求进来，四种能力该用哪个（离线可跑）。

运行：
    python code/ch16_capability_routing/step1_capability_matrix.py

第 12–15 章分别讲了四类能力：
    11 Agent 整体      12 工具（tool）
    13 MCP（工具的治理） 14 Skill（流程）

但没有一章回答这个问题：

    用户说「退款 399 元多久到账」—— 这一句该用哪个能力？

这一级做五件事：
    ① 四种编排策略在 60 条真实说法上的实测对比
    ② 为什么必须分能力看精确率/召回率
    ③ 能力冲突：两个能力都能答时怎么办
    ④ 依赖补齐：能力之间不是并列的
    ⑤ 兜底：四类都不合适时说什么

所有数字都是脚本真实算出来的。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 78


CAPABILITIES = {
    "answer": {"name": "直接回答", "cost": "1 次调用", "risk": "低（但会瞎编事实）"},
    "rag": {"name": "RAG（检索）", "cost": "1 检索 + 1 生成", "risk": "中（检索错也答得像真的）"},
    "tool": {"name": "工具（含 MCP）", "cost": "1~N 次调用", "risk": "高（写操作不可撤销）"},
    "skill": {"name": "Skill（流程）", "cost": "多轮 + 多工具", "risk": "高（漏一步就出事）"},
}


# ================================================================ 金标
# 标注规则（必须写清楚，否则无法复核）：
#   · 需要读具体订单号/金额/实时数据 -> tool
#   · 问的是"政策怎么规定" -> rag
#   · 要求"走一遍流程"（多步、有顺序）-> skill
#   · 闲聊/格式转换/常识 -> answer


@dataclass
class Case:
    text: str
    want: str
    note: str = ""


def build_cases() -> list[Case]:
    return [
        # ---- RAG（15 条）
        Case("退款政策是怎么规定的", "rag"),
        Case("无理由退货要几天内申请", "rag"),
        Case("质量问题退货运费谁承担", "rag"),
        Case("价保期是多久", "rag"),
        Case("会员有哪些权益", "rag"),
        Case("发票开具有什么要求", "rag"),
        Case("拆封了还能退吗，政策上怎么说", "rag"),
        Case("换新的条件是什么", "rag"),
        Case("一般多久能到账，按规定", "rag"),
        Case("有哪些情况不支持退货", "rag"),
        Case("企业版和普通版的售后差异", "rag"),
        Case("退货流程一般是几步", "rag"),
        Case("保修期内坏了怎么处理，规则上", "rag"),
        Case("运费险怎么用", "rag"),
        Case("什么算质量问题", "rag"),
        # ---- tool（15 条）
        Case("订单 A8821 到哪了", "tool"),
        Case("帮我查一下我的快递", "tool"),
        Case("A8821 这单能退多少钱", "tool"),
        Case("我的退款到账了吗", "tool"),
        Case("帮我把 A8821 退掉", "tool"),
        Case("A8821 什么时候发货", "tool"),
        Case("查一下 13800138000 绑定的订单", "tool"),
        Case("帮我改一下收货地址", "tool"),
        Case("A8821 的物流轨迹", "tool"),
        Case("我要取消 A8821 这个订单", "tool"),
        Case("帮我开一张发票，订单 A8821", "tool"),
        Case("我账户里还有多少余额", "tool"),
        Case("查一下我的优惠券", "tool"),
        Case("把 A8821 的退款进度告诉我", "tool"),
        Case("昨天那个单子签收了没", "tool"),
        # ---- skill（15 条）
        Case("帮我走一遍退款流程", "skill"),
        Case("我要申请售后，从检查到换新", "skill"),
        Case("帮我处理这个纠纷，该退就退", "skill"),
        Case("按流程帮我做一次退款审核", "skill"),
        Case("我的耳机坏了，帮我走完整流程", "skill"),
        Case("帮我投诉，要走完整个流程", "skill"),
        Case("帮我做一次完整的退货申请", "skill"),
        Case("这个订单有问题，帮我按流程处理", "skill"),
        Case("帮我把退款申请提交上去，该填的都填好", "skill"),
        Case("帮我处理一下这个售后单", "skill"),
        Case("走一下价保流程", "skill"),
        Case("帮我做一个退款前检查", "skill"),
        Case("帮我退掉这个订单并开好凭证", "skill"),
        Case("帮我处理这台机器的换新，从检测开始", "skill"),
        Case("帮我把整个退货流程跑完", "skill"),
        # ---- answer（15 条）
        Case("你好", "answer"),
        Case("你是谁", "answer"),
        Case("把这段话翻译成英文：退款已处理", "answer"),
        Case("帮我把「7 个工作日」改成阿拉伯数字", "answer"),
        Case("退货英语怎么说", "answer"),
        Case("谢谢", "answer"),
        Case("今天心情不好", "answer"),
        Case("帮我写一句道歉的话", "answer"),
        Case("你们几点下班", "answer"),
        Case("把上面的回答缩短到 20 字", "answer"),
        Case("解释一下什么叫「无理由退货」这个词", "answer"),
        Case("我该怎么办", "answer"),
        Case("帮我起个标题", "answer"),
        Case("你是机器人吗", "answer"),
        Case("再见", "answer"),
    ]


# ================================================================ 四种策略
def strategy_all_rag(c: Case) -> str:  # noqa: ARG001
    """错误策略 A：什么请求都先检索（最常见的偷懒做法）。"""
    return "rag"


def strategy_keyword(c: Case) -> str:
    """错误策略 B：关键词匹配（大部分人的第一版）。"""
    t = c.text
    if re.search(r"订单|快递|物流|发货|轨迹|余额|优惠券", t):
        return "tool"
    if re.search(r"退|换|售后|发票|价保", t):
        return "rag"
    return "answer"


def strategy_llm_guess(c: Case) -> str:
    """错误策略 C：让模型自由判断（用启发式模拟）。"""
    t = c.text
    if re.search(r"帮我(?!写|起)|查|改|取消|退掉|提交|处理|开一张|走", t):
        return "tool"
    if re.search(r"政策|规定|条件|多久|是什么|怎么算|哪些情况|差异|规则", t):
        return "rag"
    return "answer"


def strategy_matrix(c: Case) -> str:
    """正确策略：按五个判据顺序问，第一个命中的就是答案。

    顺序有讲究，见本章 15.3。
    """
    t = c.text

    # ① 要求「走流程 / 完整 / 从A到B / 做一次…检查」-> skill
    if re.search(r"(走一遍|走完|走一下|完整流程|整个流程|从.+开始|按流程|"
                 r"帮我处理|跑完|做一次完整|并开好|该退就退|该填的都填好|"
                 r"做一个.+检查|申请售后)", t):
        return "skill"

    # ② 有实体标识 -> tool
    if re.search(r"[A-Z]\d{3,}|\d{11}", t):
        return "tool"

    # ③ 明确的查询/执行动作 -> tool
    if re.search(r"(帮我退掉|退货申请提交|帮我改|帮我开|取消|帮我查|"
                 r"查一下|到账了吗|签收了没|多少余额|我的优惠券|我的退款)", t):
        return "tool"

    # ④ 问规则/政策/条件/谁承担 -> rag
    if re.search(r"(政策|规定|条件|规则|要求|条款|哪些情况|差异|算不算|"
                 r"什么算|怎么用|怎么算|权益|要几天|多久能|多久是|几步|"
                 r"谁承担|多久|几天|多长时间)", t):
        return "rag"

    return "answer"


STRATEGIES = [
    ("A 一律 RAG（偷懒）", strategy_all_rag, "看起来最安全，实际 3/4 都错"),
    ("B 关键词匹配（第一版）", strategy_keyword, "分不清「问政策」和「办业务」"),
    ("C 模型自由判断", strategy_llm_guess, "不知道你的系统有什么能力"),
    ("D 判据矩阵（本章）", strategy_matrix, "按顺序问五个问题"),
]


# ================================================================ 评测
def evaluate(fn) -> dict:
    cases = build_cases()
    correct = sum(1 for c in cases if fn(c) == c.want)
    wrong: dict[tuple[str, str], int] = {}
    for c in cases:
        got = fn(c)
        if got != c.want:
            wrong[(c.want, got)] = wrong.get((c.want, got), 0) + 1

    per = {}
    for cap in CAPABILITIES:
        tp = sum(1 for c in cases if c.want == cap and fn(c) == cap)
        fp = sum(1 for c in cases if c.want != cap and fn(c) == cap)
        fn_ = sum(1 for c in cases if c.want == cap and fn(c) != cap)
        per[cap] = (tp, fp, fn_)

    f1s = []
    for cap in CAPABILITIES:
        tp, fp, fn_ = per[cap]
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn_) if tp + fn_ else 0.0
        f1s.append(2 * p * r / (p + r) if p + r else 0.0)

    return {"acc": correct / len(cases), "macro_f1": sum(f1s) / len(f1s),
            "wrong": wrong, "per": per}


def demo_compare() -> None:
    print(DPRINT)
    print("① 四种策略在同一批 60 条请求上的表现")
    print(DPRINT)

    n = len(build_cases())
    print(f"  评测集：{n} 条，四类能力各 {n // 4} 条")
    print()
    print(f"  {'策略':<26} {'准确率':<10} {'宏F1':<9} 说明")
    print(f"  {'-' * 26} {'-' * 10} {'-' * 9} {'-' * 26}")

    results = {}
    for name, fn, note in STRATEGIES:
        r = evaluate(fn)
        results[name] = r
        print(f"  {name:<26} {r['acc']:<10.1%} {r['macro_f1']:<9.3f} {note}")

    print()
    print("  ⚠️ **注意 D 的 100% —— 这不是好消息，是过拟合。**")
    print("     D 的判据词是我**照着这 60 条写出来的**，所以必然满分。")
    print("     真实项目里你不知道用户会怎么说。下一节用留出集揭穿它。")
    print()

    for name in ("B 关键词匹配（第一版）", "C 模型自由判断"):
        r = results[name]
        print(f"  【{name}】主要错在哪：")
        for (want, got), cnt in sorted(r["wrong"].items(), key=lambda kv: -kv[1])[:3]:
            print(f"     {cnt} 条：该用 {CAPABILITIES[want]['name']} -> "
                  f"判成了 {CAPABILITIES[got]['name']}")
        print()

    print("  ---- 两个最有价值的错误模式：")
    print("     · 关键词法把「退款政策怎么规定」判成 RAG ✓，")
    print("       但把「帮我走一遍退款流程」也判成 RAG ✗ —— 因为都有「退」字。")
    print("     · 模型自由判断会系统性偏向 tool（因为有「帮我」），")
    print("       于是「帮我写一句道歉的话」被当成需要调工具。")
    print()
    print("     **共同根因：它们都在「看字面」，没有在「问能力」。**")


# ================================================================ 留出集
#
# 这一批句子是「换一种说法」，模拟线上真实分布。
# 关键：**我写 D 的规则时没有看这一批。**

HOLDOUT: list[Case] = [
    # rag（换说法）
    Case("退货规则里怎么写的", "rag"),
    Case("补差价有时间限制吗", "rag"),
    Case("开专票需要什么材料", "rag"),
    Case("哪些退不了", "rag"),
    Case("VIP 待遇包括啥", "rag"),
    Case("包邮门槛是多少", "rag"),
    Case("运费怎么算的，规定上", "rag"),
    Case("售后一般走几步", "rag"),
    # tool（换说法）
    Case("A4411 现在什么状态", "tool"),
    Case("我这单去哪了", "tool"),
    Case("把我那笔退款进度发我", "tool"),
    Case("帮我把 A4411 取消", "tool"),
    Case("我卡里还剩多少", "tool"),
    Case("查下我的券", "tool"),
    Case("A4411 寄出了吗", "tool"),
    Case("上次那单签收了没", "tool"),
    # skill（换说法）
    Case("帮我从头到尾办一次退货", "skill"),
    Case("走个完整售后", "skill"),
    Case("帮我把这个退款跑完整", "skill"),
    Case("按步骤帮我处理掉这张售后单", "skill"),
    Case("帮我做完整套换新", "skill"),
    Case("帮我把退款申请一次性弄好", "skill"),
    Case("帮我把这台机器退了，该走的都走", "skill"),
    Case("从检测开始帮我把换新办完", "skill"),
    # answer（换说法）
    Case("嗨", "answer"),
    Case("你能做什么", "answer"),
    Case("把这句话译成日文", "answer"),
    Case("缩成一句话", "answer"),
    Case("帮我改个措辞", "answer"),
    Case("没事了", "answer"),
    Case("帮我起个名", "answer"),
    Case("在吗", "answer"),
]


def evaluate_set(fn, cases: list[Case]) -> dict:
    correct = sum(1 for c in cases if fn(c) == c.want)
    wrong = [(c.want, fn(c), c.text) for c in cases if fn(c) != c.want]
    return {"acc": correct / len(cases), "wrong": wrong}


def demo_holdout() -> None:
    print()
    print(DPRINT)
    print("② 留出集：换一批说法，D 还站得住吗")
    print(DPRINT)

    train = build_cases()
    print(f"  训练集（写规则时看的）：{len(train)} 条")
    print(f"  留出集（写规则时**没看的**）：{len(HOLDOUT)} 条")
    print()
    print(f"  {'策略':<26} {'训练集':<10} {'留出集':<10} {'差':<8}")
    print(f"  {'-' * 26} {'-' * 10} {'-' * 10} {'-' * 8}")

    for name, fn, _note in STRATEGIES:
        a = evaluate_set(fn, train)["acc"]
        b = evaluate_set(fn, HOLDOUT)["acc"]
        print(f"  {name:<26} {a:<10.1%} {b:<10.1%} {a - b:+.1%}")

    print()
    d_wrong = evaluate_set(strategy_matrix, HOLDOUT)["wrong"]
    print(f"  D 在留出集上错 {len(d_wrong)} 条：")
    for want, got, text in d_wrong:
        print(f"     {CAPABILITIES[want]['name']:<10} -> {CAPABILITIES[got]['name']:<10} {text}")

    print()
    print("  ---- 这张表才是真实情况，而且比预期更糟：")
    print("     · D 从训练集 100% 掉到留出集 53%，掉了近一半。")
    print("       **因为它本质上是关键词法，只是关键词多写了 20 个。**")
    print("     · 掉到 53% 后，D 只比 B/C 的 34% 好 19 个点。")
    print("       换句话说：**精心设计的判据表，换个说法就塌了一半。**")
    print()
    print("  ---- 这 15 条错误的共同点（看上面明细就明白）：")
    print("     **全都是「换了个词」** —— 「包邮门槛」「哪些退不了」「我卡里还剩多少」")
    print("     「走个完整售后」。我的规则里一个词都没收录。")
    print()
    print("  ---- 所以真正的结论不是「再补 50 个词」，而是：")
    print("     1. **词表法只能当第一版**，它到 50 条规则左右就饱和了")
    print("     2. 想继续提升，必须换成**语义判断**（第 26 章 25.8「表示工程」）")
    print("     3. 判据结构（问哪五个问题）是有价值的 —— 它让语义判断有了输出格式；")
    print("        但**判据的词表不该是最终实现**")
    print()
    print("  一条实用的演进路径：")
    print("     第一版：判据矩阵（本章），能到 50~60%")
    print("     第二版：判据矩阵兜底 + 小模型分类器（第 26 章）")
    print("     第三版：分类器 + 置信度阈值，低置信度走兜底（本章 15.6）")


def demo_per_capability() -> None:
    print()
    print(DPRINT)
    print("② 分能力的精确率/召回率（为什么不能只看总准确率）")
    print(DPRINT)

    r = evaluate(strategy_matrix)
    print(f"  {'能力':<20} {'TP':<6} {'FP':<6} {'FN':<6} {'精确':<9} {'召回':<9}")
    print(f"  {'-' * 20} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 9} {'-' * 9}")
    for cap, (tp, fp, fn_) in r["per"].items():
        p = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn_) if tp + fn_ else 0.0
        print(f"  {CAPABILITIES[cap]['name']:<20} {tp:<6} {fp:<6} {fn_:<6} "
              f"{p:<9.2f} {rec:<9.2f}")

    print()
    print(f"  总准确率 {r['acc']:.1%}，宏 F1 {r['macro_f1']:.3f}")
    print()
    print("  ---- 为什么必须分能力看：")
    print("     同样的总准确率，可能意味着完全不同的风险。")
    rows = [
        ("tool 召回低", "用户要办的事没办", "体验差，但**安全**"),
        ("tool 精确低", "**不该调的时候调了**", "可能产生副作用，**危险**"),
        ("rag 召回低", "该查文档的没查", "模型瞎编，答案看着像真的"),
        ("skill 漏判成 tool", "该走 5 步的只做了 1 步", "**半成品交付**，最坑"),
    ]
    print(f"  {'情况':<22} {'后果':<26} 严重性")
    print(f"  {'-' * 22} {'-' * 26} {'-' * 26}")
    for a, b, c in rows:
        print(f"  {a:<22} {b:<26} {c}")


def demo_conflict() -> None:
    print()
    print(DPRINT)
    print("③ 能力冲突：两个能力都能答时怎么办")
    print(DPRINT)

    print("  真实冲突样本：「退款要多久到账」")
    print()
    print("  · RAG 能答：政策写着「7 个工作日」")
    print("  · tool 能答：这个订单的退款状态是「已退款，预计 3 天」")
    print("  · **两者答案不一样，用户问的是哪个？**")
    print()

    rows = [
        ("1. 有具体实体吗？", "有订单号/手机号 -> tool", "「A8821 退款要多久」-> tool"),
        ("2. 要「我的」还是「一般的」？", "「我的」-> tool；「一般/通常」-> rag", "「一般多久」-> rag"),
        ("3. 都不确定？", "先 tool 再 rag（查自己的更具体）", "且能顺便引用政策"),
    ]
    print(f"  {'规则':<26} {'判据':<34} 例子")
    print(f"  {'-' * 26} {'-' * 34} {'-' * 26}")
    for a, b, c in rows:
        print(f"  {a:<26} {b:<34} {c}")

    print()
    print("  ---- 第三条是本章最实用的取舍：")
    print("     **能查具体数据时优先查数据，把政策当补充。**")
    print("     反过来（先答政策再查数据）会出现「政策说 7 天，实际你的单子 3 天就到了」，")
    print("     用户会觉得你答非所问。")


def demo_dependency() -> None:
    print()
    print(DPRINT)
    print("④ 依赖补齐：能力之间不是并列的")
    print(DPRINT)

    print("  真实请求：「帮我退掉这个订单」")
    print("  ---- 只说了「退」，没说「哪个订单」。")
    print()

    rows = [
        ("直接调 apply_refund(订单号=?)", "❌ 参数缺失，模型可能瞎编订单号",
         "**最危险**：编对了是运气，编错了是事故"),
        ("反问用户「请提供订单号」", "🟡 能继续，多一轮交互", "简单可靠，但打断流程"),
        ("自动补齐：用手机号/会话上下文查", "✅ 体验最好",
         "需要「当前用户绑定的订单」这个能力"),
    ]
    print(f"  {'做法':<34} {'结果':<34} 说明")
    print(f"  {'-' * 34} {'-' * 34} {'-' * 26}")
    for a, b, c in rows:
        print(f"  {a:<34} {b:<34} {c}")

    print()
    print("  判据：**这个能力需要的每一个参数，有没有来源？**")
    print()
    deps = [
        ("apply_refund", ["order_id", "amount"], "order_id <- 上下文；amount <- query_order"),
        ("query_order", ["order_id"], "order_id <- 上下文/反问"),
        ("request_invoice", ["order_id", "title", "tax_no"], "order_id <- 上下文；其余 <- 用户"),
        ("transfer_to_human", [], "无参数"),
    ]
    print(f"  {'能力':<20} {'必需参数':<30} 来源")
    print(f"  {'-' * 20} {'-' * 30} {'-' * 36}")
    for a, b, c in deps:
        print(f"  {a:<20} {(', '.join(b) or '（无）'):<30} {c}")

    print()
    print("  一条硬规则：**参数没有来源时，唯一正确的做法是反问，不是猜。**")


def demo_fallback() -> None:
    print()
    print(DPRINT)
    print("⑤ 兜底：四类都不合适时说什么")
    print(DPRINT)

    print("  大部分人只写了四个分支，没写「以上都不是」：")
    print()
    print("    if 是政策问题:  rag(...)")
    print("    elif 是查订单:  tool(...)")
    print("    elif 要走流程:  skill(...)")
    print("    else:          answer(...)      # <- 问题就在这个 else")
    print()

    rows = [
        ("超出能力的请求（「帮我报警」）", "模型硬答", "**给出不该给的承诺**"),
        ("超出政策范围（「必须赔我 10 倍」）", "模型硬答", "承诺赔偿，法律风险"),
        ("系统故障（工具全挂）", "模型硬答", "编造数据"),
    ]
    print(f"  {'情况':<34} {'走 else 的结果':<20} 风险")
    print(f"  {'-' * 34} {'-' * 20} {'-' * 26}")
    for a, b, c in rows:
        print(f"  {a:<34} {b:<20} {c}")

    print()
    print("  正确做法：**兜底不是第五个能力，是第五个决策**")
    print()
    print("    else:")
    print("        if 明显超出业务范围:      礼貌拒绝 + 说明能做什么")
    print("        elif 涉及金额/法律/安全:  转人工（第 32 章）")
    print("        else:                    澄清式反问")
    print()
    print("  ---- 反问是最高性价比的兜底：")
    print("       它把「猜错」变成「多一轮」，而多一轮的代价远小于答错。")


if __name__ == "__main__":
    demo_compare()
    demo_holdout()
    demo_per_capability()
    demo_conflict()
    demo_dependency()
    demo_fallback()
    print()
    print(DPRINT)
    print("step1 完成。五句话带走：")
    print("  1. 「一律 RAG」准确率只有 25% —— 但它是最常见的实际做法。")
    print("  2. 关键词法和模型自由判断都栽在同一件事：分不清「问政策」和「办业务」。")
    print("  3. 判据矩阵在训练集上 100%，**留出集只有 53%** —— 词表法换个说法就塌。")
    print("     它的价值在「结构」，不在「词表」；想继续提升必须上语义判断。")
    print("  4. 冲突时优先查具体数据（tool），把政策（rag）当补充。")
    print("  5. 兜底不是 answer，是「拒绝 / 转人工 / 反问」三分支。")
    print(DPRINT)
