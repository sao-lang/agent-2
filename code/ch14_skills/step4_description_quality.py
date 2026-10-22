"""第 14 章 step4：description 的触发质量 —— 用打分代替「感觉还行」。

运行：
    python code/ch14_skills/step4_description_quality.py

step2 演示了「坏 description 永远不加载」，但只有 5 句话，结论很粗。
生产里你需要一个**可重复的评测**：

    准备 20 句真实用户会说的话（10 句该触发、10 句不该触发）
    跑一遍，算 精确 / 召回 / F1
    改一版 description，再跑一遍，看是不是真的变好了

这一级做什么：
    ① 一个**不调模型**的触发判定器（动作 + 对象 + 排除），让评测可以离线跑
    ② 4 版 description 的对比（含 2 版「看起来更好」但实际更差的）
    ③ 一版「过度拟合评测集」的 description，用留出集揭穿它
    ④ 只靠动作 vs 动作+对象 的取舍扫描

> ⚠️ **关于诚实性的重要说明**
> 这个判定器是「真模型判断该不该用这个技能」的**近似**，不是等价。
> 真实的模型读语义，本脚本读「动作词 + 对象词 + 排除词」。
> 所以它**不能**告诉你「你的 description 在某个模型上会怎样」，
> 但它**能**定量回答一个真问题：
>     「你的 description 里，有没有覆盖到用户真正会说的那些词？」
> 后者恰恰是 description 写不好时的主要原因。

所有数字都是脚本真实算出来的。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DPRINT = "=" * 72


# ================================================================ 评测集
#
# 这是本章最重要的"资产"。生产里这些句子应该从真实日志里采样。
# 这里按"该触发（正例）/ 不该触发（负例）"各 10 条硬编码。


@dataclass
class Sample:
    text: str
    should_trigger: bool
    why: str = ""


def build_eval() -> list[Sample]:
    return [
        # ---- 该触发：都是"审查代码"这件事的不同说法
        Sample("帮我 review 一下这个 PR", True),
        Sample("这段 diff 有什么风险吗", True),
        Sample("看看这个改动有没有问题", True),
        Sample("审查一下我提交的代码", True),
        Sample("这个改动会不会引入 bug", True),
        Sample("帮我检查一下代码质量", True),
        Sample("这个 MR 能合吗", True),
        Sample("审一下这段逻辑", True),
        Sample("这段改动安全吗", True),
        Sample("帮我看下这个 pull request", True),
        # ---- 不该触发：主题相近但意图不同
        Sample("帮我写一个快速排序", False, "是写，不是审"),
        Sample("这个函数怎么用", False, "问 API"),
        Sample("帮我改一下这个 bug", False, "是改，不是审"),
        Sample("解释一下这段代码在干什么", False, "是解释"),
        Sample("帮我优化一下这段代码的性能", False, "是优化"),
        Sample("格式化一下这个文件", False, "是格式化"),
        Sample("生成一个单元测试", False, "是生成"),
        Sample("这个报错怎么解决", False, "是排错"),
        Sample("怎么配置 lint 规则", False, "是配置工具"),
        Sample("帮我起一个分支", False, "是 git 操作"),
    ]


# ================================================================ 触发判定器
#
# 设计思路：模型判断"该不该用这个技能"，实际在做三件事
#   ① 用户想**干什么**（动作）        —— "审查" vs "写" vs "改"
#   ② 用户针对**什么**（对象）        —— "代码/PR/diff" vs "文件/分支"
#   ③ description 里有没有**排除**它  —— "不适用于写新代码"
#
# 这三个恰好也是 description 三段式要写的东西。
# 所以我们把 description 解析成这三类，再看它覆盖了 query 的多少。

# 动作词表：**只在判定器内部使用**，不是 description 的一部分。
# 它的作用是让判定器知道"审查/检查/看"和"写/改/优化"是不同意图。
ACTIONS = {
    "审查": ["审查", "审阅", "审一下", "审 ", "review", "检查", "查看", "看看", "看下",
             "看一下", "把关", "评估", "扫描", "找出", "定位", "排查", "有什么风险",
             "有问题吗", "安全吗", "能合吗", "引入 bug", "有没有问题", "靠谱吗",
             "有隐患吗", "什么意思"],
    "写": ["写", "生成", "创建", "新建", "实现", "加一个", "加个"],
    "改": ["改", "修", "修复", "重构", "调整", "优化", "格式化"],
    "解释": ["解释", "说明", "怎么用", "干什么", "是什么意思"],
    "配置": ["配置", "设置", "安装", "怎么装", "起一个", "建一个"],
    "排错": ["报错", "错误", "怎么解决", "为什么失败", "跑不起来"],
}

# 对象词表：注意包含口语说法
OBJECTS = ["代码", "changes", "diff", "pr", "mr", "pull request", "patch",
           "改动", "变更", "提交", "逻辑", "实现", "影响面",
           "文件", "分支", "函数", "测试", "规则", "报错", "性能", "类",
           "版本", "这版", "这个"]

# 真正能代表"代码产物"的对象（用于动作段判定时收紧）
CODE_OBJECTS = ["代码", "changes", "diff", "pr", "mr", "pull request", "patch",
                "改动", "变更", "提交", "逻辑", "实现", "影响面", "性能"]


def _norm(s: str) -> str:
    return s.lower()


def detect_actions(text: str) -> set[str]:
    t = _norm(text)
    return {name for name, words in ACTIONS.items() if any(w in t for w in words)}


def detect_objects(text: str) -> set[str]:
    t = _norm(text)
    return {o for o in OBJECTS if o in t}


def parse_description(desc: str) -> dict[str, str]:
    """把 description 拆成三段：动作句 / 触发条件句 / 排除条件句。"""
    trigger = ""
    exclude = ""
    m = re.search(r"(?:当|如果|若)(.+?)(?:时|的话)", desc)
    if m:
        trigger = m.group(1)
    m = re.search(r"(?:不适用于|不要用于|不处理|不包括)(.+?)(?:[。；]|$)", desc)
    if m:
        exclude = m.group(1)
    action_text = re.split(r"[。；]", desc)[0]
    return {"action": action_text, "trigger": trigger, "exclude": exclude}


def triggers(desc: str, query: str, require_object: bool = True) -> bool:
    """判定 desc 是否会在 query 上触发。

    判定规则（按顺序）：
      ① 排除段命中 query 的动作意图 -> 不触发
      ② 触发段的动作意图命中：
           · 触发段自己写了对象词 -> 要求 query 的对象也与它相交
           · 触发段没写对象词   -> 只能靠动作，但**还要求 query 指向代码产物**
             （否则「代码审查技能。」会因为"审查"这两个字，在
               「审查一下我提交的代码」「审一下这段逻辑」上触发，
               这会让 V1 看起来和 V2 一样好，掩盖真正的问题）
      ③ 没有触发段时退到动作段，同样要求对象是代码产物
    """
    parts = parse_description(desc)
    q_actions = detect_actions(query)
    q_objects = detect_objects(query)
    q_code = set(q_objects) & set(CODE_OBJECTS)

    # ① 排除
    if parts["exclude"] and (q_actions & detect_actions(parts["exclude"])):
        return False

    # ② 动作
    scope = parts["trigger"] or parts["action"]
    if not (q_actions & detect_actions(scope)):
        return False

    # ③ 对象
    if not require_object:
        return True
    d_objects = detect_objects(scope)
    if not d_objects:
        # 触发段没写对象词 -> 只能退化成"query 必须指向代码产物"
        return bool(q_code)
    return bool(set(q_objects) & set(d_objects))


# ================================================================ 打分
def score(desc: str, samples: list[Sample], **kw) -> dict:
    tp = fp = fn = tn = 0
    wrong: list[tuple[Sample, bool]] = []
    for s in samples:
        got = triggers(desc, s.text, **kw)
        if got and s.should_trigger:
            tp += 1
        elif got and not s.should_trigger:
            fp += 1
            wrong.append((s, got))
        elif not got and s.should_trigger:
            fn += 1
            wrong.append((s, got))
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "recall": rec, "f1": f1, "wrong": wrong}


# ================================================================ 四版 description
DESCRIPTIONS: list[tuple[str, str, str]] = [
    (
        "V1 极简（很多人的第一版）",
        "代码审查技能。",
        "没有「何时用」，也没有任何用户会说的对象词（PR/diff/改动）。",
    ),
    (
        "V2 三段式（正确方向）",
        "审查代码改动，找出高风险问题。当用户要求 review、检查 diff、"
        "审查 PR 或 MR 时用。不适用于写新代码、修 bug、优化性能。",
        "做什么 / 何时用 / 何时不用，三段齐全。",
    ),
    (
        "V3 看起来最专业",
        "本技能提供业界领先的静态代码分析能力，覆盖安全漏洞、性能隐患、"
        "代码规范、架构合理性等多个维度，采用多层次检测策略与深度语义理解。",
        "全是名词和形容词，没有一个用户会说的动作词。看起来最专业，实际永远不触发。",
    ),
    (
        "V4 过度堆砌触发词（过拟合）",
        "审查代码改动，找出高风险问题。当用户要求 review、检查 diff、审查 PR、"
        "看看代码、看下代码、帮忙看看、分析代码、评估代码、扫描代码时用。"
        "不适用于写新代码。",
        "把评测集里出现过的说法都塞进去。但漏掉了「提交」「逻辑」这些同样常见的对象词。",
    ),
]


def demo_compare() -> None:
    print(DPRINT)
    print("演示 1：四版 description 的真实打分")
    print(DPRINT)

    samples = build_eval()
    print(f"  评测集：{len(samples)} 条（该触发 {sum(s.should_trigger for s in samples)} 条，"
          f"不该触发 {sum(not s.should_trigger for s in samples)} 条）")
    print()
    print(f"  {'版本':<28} {'TP':<4} {'FP':<4} {'FN':<4} {'精确':<7} {'召回':<7} {'F1':<7}")
    print(f"  {'-' * 28} {'-' * 4} {'-' * 4} {'-' * 4} {'-' * 7} {'-' * 7} {'-' * 7}")

    for name, desc, _note in DESCRIPTIONS:
        r = score(desc, samples)
        print(f"  {name:<28} {r['tp']:<4} {r['fp']:<4} {r['fn']:<4} "
              f"{r['precision']:<7.2f} {r['recall']:<7.2f} {r['f1']:<7.2f}")

    print()
    for name, desc, note in DESCRIPTIONS:
        r = score(desc, samples)
        print(f"  【{name}】{note}")
        for s, _got in r["wrong"][:3]:
            kind = "漏触发" if s.should_trigger else "误触发"
            extra = f"（{s.why}）" if s.why else ""
            print(f"     {kind}: {s.text}{extra}")
        if r["wrong"]:
            print(f"     共 {len(r['wrong'])} 条失败")
        print()

    print("  ---- 三条必须内化的结论：")
    print("   1. **V3「看起来最专业」，但 F1 = 0.00。** 这是最危险的一类错误：")
    print("      字最多、评审时感觉很到位，但没有一个用户会说的具体词。")
    print("      它一次都不会触发 —— 也就是说，这个技能等于不存在。")
    print("   2. V1（「代码审查技能。」）看着很简洁，F1 只有 0.33。")
    print("      它只在 query 里出现「代码」或「审查」字样时触发，")
    print("      用户说「看下这个 PR」「这段 diff 有风险吗」就漏了。")
    print("   3. V2/V4 在训练集上看着还行（0.46/0.57），但它们在留出集上会崩 ——")
    print("      见演示 2。这就是为什么「自己写的测试集」不能当验收标准。")


def demo_overfit() -> None:
    print()
    print(DPRINT)
    print("演示 2：过度拟合评测集 —— 留出集揭穿它")
    print(DPRINT)

    train = build_eval()
    # 留出集：换一批说法，模拟"上线后用户说的是别的词"
    holdout = [
        Sample("能帮我看一下这个变更吗", True),
        Sample("这个提交有问题吗", True),
        Sample("审阅一下这段实现", True),
        Sample("这版改动靠谱吗", True),
        Sample("帮我把关一下这段代码", True),
        Sample("这个 patch 有隐患吗", True),
        Sample("看一下这个改动的影响面", True),
        Sample("帮我写个正则", False),
        Sample("这段报错什么意思", False),
        Sample("帮我重构一下这个类", False),
        Sample("这个库怎么装", False),
        Sample("帮我加个日志", False),
    ]

    print(f"  训练集 {len(train)} 条，留出集 {len(holdout)} 条（说法完全不同）")
    print()
    print(f"  {'版本':<28} {'训练集 F1':<12} {'留出集 F1':<12} {'差':<8}")
    print(f"  {'-' * 28} {'-' * 12} {'-' * 12} {'-' * 8}")
    for name, desc, _ in DESCRIPTIONS:
        r1 = score(desc, train)
        r2 = score(desc, holdout)
        print(f"  {name:<28} {r1['f1']:<12.2f} {r2['f1']:<12.2f} {r1['f1'] - r2['f1']:+.2f}")

    print()
    for tag in ("V2", "V4"):
        desc = next(d for n, d, _ in DESCRIPTIONS if n.startswith(tag))
        r2 = score(desc, holdout)
        print(f"  {tag} 在留出集上的失败明细：")
        if not r2["wrong"]:
            print("    （无失败）")
        for s, _ in r2["wrong"]:
            kind = "漏触发" if s.should_trigger else "误触发"
            extra = f"（{s.why}）" if s.why else ""
            print(f"    {kind}: {s.text}{extra}")
        print()

    print("  ---- 这是本章最值钱的一条工程经验：")
    print("     **description 的触发质量，必须在「你没见过的说法」上测。**")
    print()
    print("     看 V2：训练集 0.46，留出集 **0.00**，掉了 0.46。")
    print("     看 V4：训练集 0.57，留出集 0.25，掉了 0.32。")
    print("     而且 V2/V4 在留出集上漏的是同一批：「变更」「提交」「实现」「patch」。")
    print()
    print("     原因很直接：它们的触发段只写了 review / diff / PR / MR，")
    print("     而用户会说 变更 / 提交 / 实现 / patch / 改动 / 影响面 ——")
    print("     **动作词只有那么几个，对象词是无穷的。**")
    print()
    print("     所以「多堆几个动作词」（V4）治不了根；真正有效的是")
    print("     把「对象」这件事想清楚，并持续从日志里补充新说法。")


def demo_threshold() -> None:
    print()
    print(DPRINT)
    print("演示 3：只靠动作 vs 动作 + 对象")
    print(DPRINT)

    desc = next(d for n, d, _ in DESCRIPTIONS if n.startswith("V2"))
    parts = parse_description(desc)
    samples = build_eval()

    print(f"  V2 的动作段：{parts['action']}")
    print(f"  V2 的触发段：{parts['trigger']}")
    print(f"  V2 的排除段：{parts['exclude']}")
    print()
    print(f"  {'判定策略':<28} {'精确':<8} {'召回':<8} {'F1':<8} 说明")
    print(f"  {'-' * 28} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 20}")

    for name, ro, note in [
        ("只靠动作", False, "动作对上就触发"),
        ("动作 + 对象（默认）", True, "还要对象也对上"),
    ]:
        r = score(desc, samples, require_object=ro)
        print(f"  {name:<28} {r['precision']:<8.2f} {r['recall']:<8.2f} "
              f"{r['f1']:<8.2f} {note}")

    print()
    print("  只靠动作时，被误触发的例子：")
    r = score(desc, samples, require_object=False)
    for s, _ in r["wrong"]:
        if not s.should_trigger:
            print(f"    误触发: {s.text}（{s.why}）")

    print()
    print("  ---- 这张表的读法很关键，别读反了：")
    print("     「只靠动作」召回高（0.70）是因为它几乎什么都触发，")
    print("     「动作 + 对象」召回低（0.30）是因为**触发段里只写了 3 个对象词**。")
    print()
    print("     所以正确的结论不是「别约束对象」，而是：")
    print("     **对象约束是对的，但你写进去的对象词太少了。**")
    print("     约束越精确 -> 越不会误触发，但也越容易漏；")
    print("     解决漏的办法是**补充对象词**，不是拆掉约束。")
    print()
    print("  两个方向的代价不对称，要按业务定：")
    print("   · 技能是「省钱/加速」类（如缓存查询）-> 宁可漏触发，别误触发")
    print("   · 技能是「防事故」类（如部署前检查）-> 宁可误触发，别漏触发")


def demo_new_skill_checklist() -> None:
    print()
    print(DPRINT)
    print("演示 4：新写一个 skill 时的检查清单")
    print(DPRINT)

    checks = [
        ("有「做什么」？", "一句话说清这个技能完成什么任务"),
        ("有「何时用」？", "列出 >= 3 个用户会说的具体说法，不是抽象描述"),
        ("有「何时不用」？", "至少写一条，防止和相近技能抢触发"),
        ("动作词具体吗？", "用「审查/检查」而不是「分析能力/检测策略」"),
        ("对象词覆盖了吗？", "代码/PR/diff/改动/提交/patch —— 用户会换着说"),
        ("有关键动作？", "一个不熟悉的人靠常识会做错的那一步，单独列出并加粗"),
        ("有输出格式？", "告诉模型该产出什么结构，别让它自由发挥"),
        ("有失败怎么办？", "比如「找不到测试文件就报告缺失，不要跳过」"),
        ("评测过触发吗？", ">= 20 条（10 正 10 负），算过精确和召回"),
        ("在留出集上测过吗？", "换一批没见过的说法，F1 没有明显下降"),
        ("token 算过吗？", "命中时消耗多少 token，值不值得"),
        ("和相似技能的边界清晰吗？", "两个技能都能触发同一句话时，谁优先"),
    ]
    print(f"  {'#':<4} {'检查项':<24} 具体怎么做")
    print(f"  {'-' * 4} {'-' * 24} {'-' * 40}")
    for i, (item, how) in enumerate(checks, 1):
        print(f"  {i:<4} {item:<24} {how}")

    print()
    print("  ---- 第 9 和第 12 条是最常被跳过的：")
    print("     不测触发 = 你不知道它会不会被用；")
    print("     不划边界 = 两个技能抢同一句话，触发哪个看运气。")


if __name__ == "__main__":
    demo_compare()
    demo_overfit()
    demo_threshold()
    demo_new_skill_checklist()
    print()
    print(DPRINT)
    print("step4 完成。四句话带走：")
    print("  1. description 的三段式里，「何时用」是唯一不能省的——缺了它永远不触发。")
    print("  2. 「看起来很专业」的 description F1 往往是 0（没有一个用户会说的词）。")
    print("  3. 触发质量必须在**没见过的说法**上测，否则你会把评测集塞进 description。")
    print("  4. 动作词有限、对象词无穷——「只写动作」的 description 更容易过拟合。")
    print(DPRINT)
