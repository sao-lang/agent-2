"""一个能跑、但没有工程结构的循环：先看它是怎么坏的。

不联网。call_model 是固定剧本（第 2 次就说"完成"），用来暴露三件事：
  1 完成由回复文本判定 -> 错的答案被当成完成交出去
  2 只有步数上限 -> 预算超了三倍也没有任何一处会停
  3 没有任何轨迹 -> 复盘时说不清它为什么停在第 2 步

运行：python code/forms/loop_engineering/symptom.py
"""

from __future__ import annotations

BUDGET = 100
COST_PER_CALL = 40


def call_model(messages: list[str]) -> str:
    """固定剧本：先给一个错答案，再自称完成。"""
    turn = sum(1 for m in messages if m.startswith("assistant"))
    if turn == 0:
        return "assistant: 答案是 42，已改好"
    return "assistant: 完成"


def naive_loop(task: str) -> tuple[str, int, int]:
    """8 行循环：只有步数上限与文本里出现"完成"两个出口。"""
    messages = [f"user: {task}"]
    spent = 0
    for _ in range(8):
        reply = call_model(messages)
        messages.append(reply)
        spent += COST_PER_CALL
        if "完成" in reply:
            return reply, len(messages) - 1, spent
    return messages[-1], len(messages) - 1, spent


def naive_loop_repeat(task: str) -> tuple[str, int, int]:
    """同一份循环，遇到重复动作时没有任何拦截，只能等步数用完。"""
    messages = [f"user: {task}"]
    spent = 0
    for _ in range(8):
        reply = "assistant: 调用 read_file(config.yaml)"
        messages.append(reply)
        spent += COST_PER_CALL
        if "完成" in reply:
            return reply, len(messages) - 1, spent
    return messages[-1], len(messages) - 1, spent


def main() -> None:
    print("=== 1. 自述完成：错答案被当成完成交出去 ===")
    reply, turns, spent = naive_loop("算出 6*7 并验证")
    truth = 42
    print(f"    循环交出的内容：{reply}")
    print(f"    外部真值：6*7={truth}  ->  {'通过' if str(truth) in reply else '不通过'}")
    print(f"    轮数={turns} 花费={spent}（预算 {BUDGET}）")

    print()
    print("=== 2. 只有步数上限：预算超三倍也不停 ===")
    _, turns2, spent2 = naive_loop_repeat("读出配置里的端口")
    print(f"    轮数={turns2} 花费={spent2} 预算={BUDGET} 超出={spent2 / BUDGET:.1f} 倍")
    print("    <- 循环里没有任何一行知道'钱'这回事")

    print()
    print("=== 3. 没有轨迹：只剩最后一句回复 ===")
    print("    复盘时能拿到的只有最后一条消息，没有每步的观测、动作、判定")
    print("    因此无法回答：它是第几步开始跑偏的、有没有重复动作、预算花在哪一步")

    print()
    print("=== 4. 三个病对应本章的三个补法 ===")
    print("    自述完成 -> verify 插点，用外部裁判判完成")
    print("    只有步数 -> 五种终止，预算与无进展、重复动作各有一条出口")
    print("    没有轨迹 -> 每步一行 JSONL，带观测哈希与动作哈希")


if __name__ == "__main__":
    main()

