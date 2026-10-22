"""第 5 章 step3：流式输出——为什么"等 4 秒出全文"和"0.3 秒开始出字"感受完全不同（离线）。

运行：
    python code/ch05_calling/step3_streaming.py

上一级的痛点（step2）：调用稳了、成本降了，但用户抱怨"点了发送之后一直在转圈"。
                     实测总耗时 4.2 秒——可人眼在 1 秒没反应时就开始怀疑系统坏了。

这一级做什么：用同一份"回答"跑三种交付方式，量化用户**感知**的差异：
  A. 一次性返回（非流式）
  B. 流式但只在最后才渲染（前端写法不对，等于没流式）
  C. 真流式（逐 token 渲染）

关键指标不是"总耗时"，而是 **TTFT（首字延迟）**——第 37 章会把它拆到每个环节。

本脚本用假的时间线模拟（真实 token 间隔取决于模型与网络），
这样你在没有 API key 时也能看清"流式到底改变了什么"。
"""
from __future__ import annotations

from dataclasses import dataclass


# 一段真实长度的客服回答，切成 24 个"token"
TOKENS = [
    "签收", "后", " 7 ", "天", "内", "，", "商品", "未", "拆封", "且", "不影响",
    "二次", "销售", "的", "，", "可", "申请", "无理由", "退货", "。", "您", "的",
    "订单", "符合",
]

# 时间模型：首 token 之前是"思考+网络"时间，之后每个 token 有间隔
THINK_MS = 1800.0   # 模型开始输出前的固定等待（prefill + 排队）
PER_TOKEN_MS = 45.0  # 每个 token 的输出间隔
NETWORK_MS = 120.0   # 首字节网络往返


@dataclass
class Delivery:
    name: str
    ttft_ms: float       # 用户看到第一个字的时间
    full_ms: float       # 用户看到完整答案的时间
    updates: int         # 界面上"内容发生了变化"的次数
    notes: str


def no_stream() -> Delivery:
    """一次性返回：用户必须等到全部生成完。"""
    total = NETWORK_MS + THINK_MS + len(TOKENS) * PER_TOKEN_MS + NETWORK_MS
    return Delivery("A 一次性返回", total, total, 1, "全程空白，一次出现")


def stream_but_buffer() -> Delivery:
    """流式接收，但前端等收完再渲染——最常见的错误写法。"""
    total = NETWORK_MS + THINK_MS + len(TOKENS) * PER_TOKEN_MS
    return Delivery("B 流式但不渲染", total, total, 1, "省了带宽，用户感受没变")


def stream_render() -> Delivery:
    """真流式：收到第一个 token 就渲染。"""
    ttft = NETWORK_MS + THINK_MS + PER_TOKEN_MS
    full = NETWORK_MS + THINK_MS + len(TOKENS) * PER_TOKEN_MS
    return Delivery("C 真流式", ttft, full, len(TOKENS), "首字即渲染，逐字出现")


def perceive(d: Delivery) -> float:
    """用户感知等待分 = 首字延迟 + 剩余时间的 30%（人读字是跟得上的）。

    这是一个粗略模型，但它解释了为什么"流式"感觉快得多：
    剩下的时间用户在**读**，而不是在**等**。
    """
    return d.ttft_ms + (d.full_ms - d.ttft_ms) * 0.3


def main() -> None:
    print("=" * 86)
    print("三种交付方式的时间线")
    print("=" * 86)
    print(f"回答长度：{len(TOKENS)} 个 token")
    print(f"模型第一字前等待：{THINK_MS:.0f}ms　每 token 间隔：{PER_TOKEN_MS:.0f}ms　网络往返：{NETWORK_MS:.0f}ms\n")

    rows = [no_stream(), stream_but_buffer(), stream_render()]

    print(f"{'方式':<18}{'TTFT':>10}{'完成':>10}{'刷新次数':>10}   用户看到")
    print("-" * 86)
    for d in rows:
        print(f"{d.name:<18}{d.ttft_ms:>9.0f}ms{d.full_ms:>9.0f}ms{d.updates:>10}   {d.notes}")
    print("-" * 86)

    print("\n" + "=" * 86)
    print("用户感知等待（首字 + 剩余 × 30%）")
    print("=" * 86)
    base = perceive(rows[0])
    print(f"{'方式':<18}{'感知等待':>12}{'相对 A':>10}   判定")
    print("-" * 86)
    for d in rows:
        p = perceive(d)
        verdict = "基线" if d is rows[0] else f"快 {(1 - p / base):.0%}"
        print(f"{d.name:<18}{p:>11.0f}ms{p / base:>10.0%}   {verdict}")
    print("-" * 86)

    print("\n" + "=" * 86)
    print("时间线上的差别（前 3 秒，每 500ms 一帧）")
    print("=" * 86)
    print(f"{'时刻':<9}{'A 一次性':<22}{'B 流式不渲染':<22}{'C 真流式'}")
    print("-" * 86)
    for ms in range(0, 3200, 500):
        a = "空白" if ms < rows[0].full_ms else "全文"
        b = "空白" if ms < rows[1].full_ms else "全文"
        if ms < rows[2].ttft_ms:
            c = "空白"
        else:
            shown = int((ms - rows[2].ttft_ms) / PER_TOKEN_MS) + 1
            c = f"已显示 {min(shown, len(TOKENS))}/{len(TOKENS)} token"
        print(f"{ms:>6}ms  {a:<22}{b:<22}{c}")
    print("-" * 86)

    print("\n" + "=" * 86)
    print("流式带来的三个新问题（不是免费的）")
    print("=" * 86)
    problems = [
        ("无法事后过滤", "内容已经开始显示了，护栏才发现有问题（第 33 章）",
         "流式护栏要逐块检查 + 可中断"),
        ("结构化输出变难", "JSON 是边生成边吐出的，中途不是合法 JSON",
         "用「流式 + 最后统一解析」或增量解析器（第 6 章）"),
        ("计费和计量时机", "usage 往往在**最后一个 chunk** 才给全",
         "必须在流结束后结算，不能边流边算（第 39 章）"),
    ]
    print(f"  {'问题':<16}{'为什么':<40}应对")
    print("  " + "-" * 82)
    for a, b, c in problems:
        print(f"  {a:<16}{b:<40}{c}")

    print("\n" + "=" * 86)
    print("什么时候**不该**用流式")
    print("=" * 86)
    print("  · 输出要被程序完整解析（抽字段、生成 SQL）→ 流式没有收益，反而增加复杂度")
    print("  · 输出很短（< 20 token）→ 首字和全文几乎同时到，流式只多了开销")
    print("  · 需要先过一遍完整护栏才敢给用户看（高风险场景）→ 先非流式，再整段展示")
    print()
    print("  判据很简单：**「用户是否需要边看边等？」**")
    print("    需要（聊天、长文生成、代码生成）→ 流式")
    print("    不需要（后台抽取、批处理、短答案）→ 非流式")

    print("\n" + "=" * 86)
    print("结论")
    print("=" * 86)
    print("  · 流式改变的不是总耗时，是 **TTFT**——而那才是用户真正感知的「慢」。")
    print("  · **流式接收 ≠ 流式渲染。** B 方案省了带宽，用户依然对着空白转圈。")
    print(f"  · 本例：感知等待从 {perceive(rows[0]):.0f}ms 降到 {perceive(rows[2]):.0f}ms"
          f"（快 {1 - perceive(rows[2]) / perceive(rows[0]):.0%}），**总耗时一点没变**。")
    print("  · 但流式会让护栏、结构化输出、计量三件事都变难——先想清楚再上。")

    assert rows[2].ttft_ms < rows[0].ttft_ms


if __name__ == "__main__":
    main()
