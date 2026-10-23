"""第 57 章示例 1：给一次调用记账。

运行：
    python code/ch38_measuring/demo_measure.py

你会看到三件事：
  1. 同样的问题，输出长度不同，output_tokens 差多少
  2. 多轮对话里 input_tokens 是**累加**的——这是成本失控的头号原因
  3. 一个"看起来便宜"的调用，其实可能比你想的贵
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import Meter, get_settings, make_llm, usage_of  # noqa: E402


def one_shot(meter: Meter) -> None:
    """单轮调用：短回答 vs 长回答。"""
    s = get_settings()
    llm = make_llm()

    for ask, label in [("用一句话解释 token。", "短"), ("用 300 字解释 token。", "长")]:
        with meter.track(s.model, step=f"oneshot-{label}") as rec:
            resp = llm.invoke(ask)
            rec.input_tokens = usage_of(resp)["input_tokens"]
            rec.output_tokens = usage_of(resp)["output_tokens"]
        print(f"[{label}] out={rec.output_tokens:>4} tokens  cost=¥{rec.cost:.6f}")


def multi_turn(meter: Meter) -> None:
    """多轮调用：观察 input_tokens 的累加。

    这是新手最容易忽略的成本陷阱：
    第 5 轮请求的 input 里，包含前 4 轮的全部内容。
    """
    s = get_settings()
    llm = make_llm()
    history: list[tuple[str, str]] = []

    questions = ["我叫小林。", "我做什么工作的？", "我住在哪？", "我喜欢什么？", "总结一下我的信息。"]

    for i, q in enumerate(questions, 1):
        # 把历史拼进 prompt —— 先手写，理解成本从哪来
        prompt = "\n".join([f"用户：{u}\n助手：{a}" for u, a in history] + [f"用户：{q}"])
        with meter.track(s.model, step=f"turn-{i}") as rec:
            resp = llm.invoke(prompt)
            u = usage_of(resp)
            rec.input_tokens, rec.output_tokens = u["input_tokens"], u["output_tokens"]
        history.append((q, resp.content))
        print(f"第 {i} 轮  input={rec.input_tokens:>4}  output={rec.output_tokens:>3}  累计成本=¥{sum(r.cost for r in meter.records):.6f}")


def main() -> None:
    s = get_settings()
    if s.api_key in ("missing", ""):
        print("❌ 需要 API key。请复制 .env-example 为 .env 并填入配置。")
        print("   无 key 也能跑的可运行示例：python code/ch38_measuring/growth_curve.py")
        return

    meter = Meter()
    print("=== 1. 单轮：长度对输出的影响 ===")
    one_shot(meter)
    print("\n=== 2. 多轮：input token 的累加 ===")
    multi_turn(meter)

    print("\n=== 汇总 ===")
    for k, v in meter.summary().items():
        print(f"{k:<18}: {v}")

    out = Path(__file__).resolve().parents[2] / ".traces" / "ch01_ledger.json"
    meter.dump(out)
    print(f"\n账本已导出：{out}")
    print("\n👉 记住这个数字：多轮对话的成本是**超线性**增长的，不是线性的。")


if __name__ == "__main__":
    main()
