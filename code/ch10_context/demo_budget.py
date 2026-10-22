"""第 10 章示例 1：token 预算分配与可视化（不需要 API）。

运行：
    python code/ch10_context/demo_budget.py

你会看到两件事：
  1. 一次典型的 RAG 请求里，各槽位到底占了多少钱
  2. 不分配预算时，历史会挤掉检索结果——而检索结果才是答案的来源
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.context import ContextAssembler, ContextBudget, est_tokens  # noqa: E402


SYSTEM = "你是电商客服助手。根据参考资料回答，资料里没有就说不知道。"

HISTORY = [
    {"role": "user", "content": "你好，我想问个事。"},
    {"role": "assistant", "content": "您好，请问有什么可以帮您？"},
    {"role": "user", "content": "我叫张伟，订单号 A12345，上周买的耳机有杂音。"},
    {"role": "assistant", "content": "抱歉给您带来不便，请问是哪种杂音？"},
    {"role": "user", "content": "就是有滋滋声，尤其右耳。"},
    {"role": "assistant", "content": "了解，可能是驱动或接触问题。"},
    {"role": "user", "content": "那我该怎么办？"},
    {"role": "assistant", "content": "建议您先换设备测试，如果仍有问题可以申请售后。"},
    {"role": "user", "content": "试过了，还是有。"},
    {"role": "assistant", "content": "好的，那可以走售后流程。"},
]

# 长参考资料（真实 RAG 一次召回 5 条就是这样）
RETRIEVAL = [
    "【售后政策】签收后 7 天内出现非人为损坏，可申请无理由退货；15 天内可换新。"
    "耳机类商品需保留包装与配件，缺少配件可能影响换新。",
    "【杂音排查】右耳电流声常见原因：1) 蓝牙编解码不匹配 2) 耳塞网罩堵塞 3) 电池老化。"
    "建议依次尝试：重置耳机、更换播放设备、清洁网罩。",
    "【换新流程】App - 我的订单 - 申请售后 - 选择换新 - 上传故障视频 - 寄回 - 检测 - 发货。"
    "整个流程通常 5-7 个工作日。",
    "【运费规则】非人为质量问题，往返运费由商家承担；人为损坏需买家承担检测费。",
    "【联系人工】售后问题超过 3 个工作日未处理，可在 App 内点击「转人工」，或拨打 400-xxx。",
]

QUESTION = "我的耳机右耳有滋滋声，能换新吗？"

# 真实场景里"不分配预算"= 把能带的历史全带上（上限只看模型窗口，比如 128k）
FULL_WINDOW = 128_000


def main() -> None:
    print("=" * 66)
    print("场景 A：不分配预算（历史能塞多少塞多少，只看模型窗口）")
    print("=" * 66)
    # 模拟"客服系统里这个用户的完整历史"：40 轮，每轮都比示例里更长
    long_history = HISTORY * 4
    hist_tokens = sum(est_tokens(m["content"]) for m in long_history)
    ret_tokens = sum(est_tokens(r) for r in RETRIEVAL)
    print(f"  系统提示: {est_tokens(SYSTEM):>6} token")
    print(f"  对话历史: {hist_tokens:>6} token  ({len(long_history)} 条)")
    print(f"  检索结果: {ret_tokens:>6} token  ({len(RETRIEVAL)} 条)")
    print(f"  问题    : {est_tokens(QUESTION):>6} token")
    print(f"  合计    : {hist_tokens + ret_tokens + est_tokens(QUESTION) + est_tokens(SYSTEM):>6} token")
    print(f"  → 历史占比 {hist_tokens / (hist_tokens + ret_tokens):.0%}")
    print("  → 这个示例还小。真实客服系统里历史是几千 token 级，检索只有几百")
    print("    ——不分配预算时，历史会稳定挤占检索的空间。")

    print("\n" + "=" * 66)
    print("场景 B：分配预算（8000 token，四槽位）")
    print("=" * 66)
    assembler = ContextAssembler(ContextBudget(total=8000))
    messages, actual = assembler.build(
        system=SYSTEM, question=QUESTION, history=long_history, retrieval=RETRIEVAL
    )
    print(assembler.budget.report(actual))

    print(f"\n  最终 messages：{len(messages)} 条")
    print(f"  实际总 token：{sum(est_tokens(m['content']) for m in messages):,}")

    print("\n" + "=" * 66)
    print("关键结论")
    print("=" * 66)
    print("  1. 有预算 ≠ 每类都塞满；预算是**在冲突时该牺牲谁**的决策。")
    print("  2. 这个示例的语料太小（288 token），所以看不出差异——")
    print("     真实场景请用你自己的数据跑，数字会立刻变得刺眼。")
    print("  3. 关键不是这套默认比例，而是**你要能说出自己系统的比例是多少**。")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
