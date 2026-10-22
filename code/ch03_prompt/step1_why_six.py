"""第 3 章 step1：一句话 Prompt 的五个致命缺陷（离线）。

运行：
    python code/ch03_prompt/step1_why_six.py

上一级的痛点（第 2 章）：token 算清了、钱算清了，但你发现——
                         同样的 token 数，别人写出来的效果就是比你好。

这一级做什么：把"随便写一句"的 prompt 拆开，让它在**离线规则引擎**下暴露问题。
             这个引擎不是真的模型，它是一面镜子：只检查 prompt 里"有没有写清楚"。

要看的三件事：
  1. 一句"帮我分析一下"缺了 5 个要素，模型只能靠猜
  2. 每补一个要素，能消除一类"猜"（这正是六要素的来源）
  3. 六要素不是说六句话，而是六个**可检查的槽位**
"""
from __future__ import annotations

from dataclasses import dataclass


# ---- 六要素：(键, 中文名, 一个简单的存在性判据, 缺了会导致什么) ----------------
@dataclass
class Element:
    key: str
    name: str
    hint: str
    failure: str


ELEMENTS = [
    Element(
        "role", "角色",
        "说明你希望它用什么身份 / 视角 / 口吻",
        "口吻和专业深度不可控：同一份数据，有时像实习生，有时像老板",
    ),
    Element(
        "task", "任务",
        "明确要做的动作（分析 / 对比 / 抽取 / 改写）",
        "它不知道要干什么，只能挑最像的那件事做",
    ),
    Element(
        "context", "背景",
        "它需要知道的业务前提、历史、约束来源",
        "它用通用常识填空，而通用常识往往和你的业务相反",
    ),
    Element(
        "input", "输入数据",
        "本次要处理的具体内容，用分隔符包起来",
        "它分不清'要处理的'和'要参考的'，把指令当数据或反过来",
    ),
    Element(
        "format", "输出格式",
        "结果长什么样（表格 / JSON / 几段话 / 字数）",
        "每次格式都不一样，下游解析直接炸",
    ),
    Element(
        "constraint", "质量与约束",
        "哪些不能做、信息不足时怎么办",
        "它会编、会超范围、会为了'完整'而补充假设",
    ),
]

# ---- 三份 prompt 的演化：从一句话到六要素齐全 --------------------------------
V1 = """
帮我分析一下上周的退款情况。
"""

V2 = """
你是一名电商售后数据分析师。

帮我分析一下上周的退款情况。

按照以下格式输出：
1. 关键发现
2. 支撑数据
3. 建议
"""

V3 = """
# 角色
你是一名电商售后数据分析师，习惯用数字说话，不使用"较多""有所上升"这类模糊表述。

# 任务
分析上周（2026-10-13 至 2026-10-19）的退款数据，找出退款率异常升高的品类，并给出可能原因。

# 背景
我们是自营 3C 电商，退款率的历史基线是 2.1%。上周整体退款率 3.4%，超过 3% 就会触发运营预警。
业务方最关心的是"能不能立刻止损"，所以结论要能直接对应到动作。

# 输入数据
<<<
品类,订单数,退款数
蓝牙耳机,1240,89
充电宝,980,31
手机壳,2100,42
数据线,1560,28
>>>

# 输出格式
用 Markdown 表格输出，必须包含以下列：
| 品类 | 退款率 | 与基线差值 | 是否异常 |

表格下方给两段话：
- 第一段：一句话结论（不超过 40 字）
- 第二段：针对异常品类的止损动作（不超过 3 条）

# 质量与约束
- 只基于输入数据计算，不得引入外部信息
- 退款率 = 退款数 / 订单数，保留一位小数
- 若某品类订单数少于 100，必须在表格里标注"样本不足"
- 输入数据不足以支撑结论时，直接输出"信息不足"，不要推测
"""


def present(prompt: str) -> dict[str, bool]:
    """极简存在性判据——只看 prompt 里有没有对应槽位的关键词。

    真实模型当然不需要这些词，这里只是把"写没写清楚"变成可检查的东西。
    这也是本书全书的口径：**能被检查的才算约束，写在心里的是愿望。**
    """
    p = prompt
    return {
        "role": "你是一名" in p or "你是一位" in p,
        "task": ("任务" in p) or ("分析" in p and "找出" in p),
        "context": ("背景" in p) or ("基线" in p) or ("历史" in p),
        "input": "<<<" in p or "```" in p,
        "format": ("输出格式" in p) or ("表格" in p and "列" in p),
        "constraint": ("约束" in p) or ("不得" in p) or ("信息不足" in p),
    }


def score(prompt: str) -> tuple[int, list[Element]]:
    have = present(prompt)
    missing = [e for e in ELEMENTS if not have[e.key]]
    return len(ELEMENTS) - len(missing), missing


def main() -> None:
    versions = [
        ("v1 一句话版", V1),
        ("v2 加了角色与格式", V2),
        ("v3 六要素齐全", V3),
    ]

    print("=" * 84)
    print("同一件事的三份 prompt，六要素覆盖情况")
    print("=" * 84)

    header = f"{'版本':<20}" + "".join(f"{e.name:<7}" for e in ELEMENTS) + f"{'得分':>6}"
    print(header)
    print("-" * 84)
    for label, prompt in versions:
        have = present(prompt)
        marks = "".join(f"{'✅' if have[e.key] else '❌':<6}" for e in ELEMENTS)
        got, _ = score(prompt)
        print(f"{label:<20}{marks}{got:>4}/6")
    print("-" * 84)

    print("\n" + "=" * 84)
    print("每缺一个要素，模型要替你'猜'什么")
    print("=" * 84)
    print("v1 一句话版缺的：\n")
    _, missing = score(V1)
    for e in missing:
        print(f"  ❌ 缺【{e.name}】")
        print(f"     应该写：{e.hint}")
        print(f"     不写的后果：{e.failure}\n")

    print("=" * 84)
    print("v3 的六要素各对应哪一行")
    print("=" * 84)
    for e in ELEMENTS:
        marker = "✅" if present(V3)[e.key] else "❌"
        print(f"  {marker} {e.name:<8} → 写清了「{e.hint}」")

    print("\n" + "=" * 84)
    print("关键认知")
    print("=" * 84)
    print("  · 六要素不是'写六句话'，是六个**可检查的槽位**。")
    print("    写完之后你逐条打勾，缺哪条就是哪条要补——这是 prompt 工程和'感觉写得不错'的分界线。")
    print("  · 每补一个要素，就消灭一类'模型替你做主'的情况。")
    print("  · 但六要素**不能解决所有问题**——它只解决'我没说清楚'。")
    print("    如果问题出在'它没有资料'（第 8 章 RAG）或'它行为不稳'（第 56 章），六要素无能为力。")

    assert score(V1)[0] < score(V3)[0], "v3 必须比 v1 覆盖更多要素"


if __name__ == "__main__":
    main()
