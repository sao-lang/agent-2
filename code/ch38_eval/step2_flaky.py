"""第 40 章 step2：同一问题跑 N 次，为什么 80% 比 0% 更危险（离线）。

运行：
    python code/ch38_eval/step2_flaky.py

上一级的痛点：一份报表只代表"这一次跑得怎么样"，代表不了"明天会怎么样"。

这一级做什么：让同一个问题跑 5 次，分三种情况各跑一遍：
  A. 稳定成功（5/5）
  B. 稳定失败（0/5）
  C. 时好时坏（4/5，即 flaky）
然后看三个指标：通过率、一致性、flaky 标记。

关键结论：**flaky 无法从单次评测里看出来**，所以必须"同一问题多跑几次"。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.agent_eval import AgentCase, AgentRun, TraceStep, stability  # noqa: E402

CASE = AgentCase("c-coupon", "会员退货优惠券返还吗？", ["不返还"], expected_tools=["search_policy"], max_steps=4)

ANSWERS = {
    "ok": "会员退货时，已使用的优惠券不返还。",
    "ok2": "已使用的优惠券不返还，其余按原路退回。",     # 同样正确，但措辞不同
    "bad": "可以返还，优惠券会原路退回到账户。",
}


def run(mode: str, variant: str = "ok") -> AgentRun:
    ans = ANSWERS[variant]
    steps = [TraceStep(0, "plan"), TraceStep(1, "tool", "search_policy", {"q": CASE.question}),
             TraceStep(2, "model", "answer")]
    err = "timeout" if mode == "fail" else None
    return AgentRun(case_id=CASE.id, question=CASE.question, answer=ans, steps=steps,
                    cost=0.006, latency_ms=1200, error=err)


def main() -> None:
    scenarios = {
        "A 稳定成功（5/5）": [run("ok")] * 5,
        "B 稳定失败（0/5）": [run("fail")] * 5,
        "C 时好时坏（4/5）": [run("ok"), run("ok", "ok2"), run("fail"), run("ok"), run("ok")],
        "D 全错但措辞不同": [run("ok", "bad")] * 5,
    }

    print("=" * 78)
    print("同一问题跑 5 次：四个场景")
    print("=" * 78)
    print(f"  {'场景':<20}{'通过率':>7}{'一致性':>8}{'flaky':>8}{'唯一答案数':>10}")
    print("  " + "-" * 55)
    for name, runs in scenarios.items():
        st = stability(runs, CASE)
        print(f"  {name:<20}{st['pass_rate']:>7.0%}{str(st['consistent']):>8}"
              f"{str(st['flaky']):>8}{st['unique_answers']:>10}")

    print("\n" + "=" * 78)
    print("为什么 C 最危险：三种状态的用户体验完全不同")
    print("=" * 78)
    print("  稳定成功  → 用户觉得'好用'，会推荐给别人")
    print("  稳定失败  → 用户觉得'这个功能不行'，但不会反复碰壁，会换别的办法")
    print("  时好时坏  → 用户觉得'这个系统不可信'，而且**每次都会再试**，每次都被伤一次")
    print("\n  → 所以 flaky 的严重性 > 稳定失败。")
    print("     而它偏偏是单次评测看不出来的：抽到哪一次，结论就是哪一个。")

    print("\n" + "=" * 78)
    print("再看一个更隐蔽的情况：D 全错但措辞一致")
    print("=" * 78)
    d = stability(scenarios["D 全错但措辞不同"], CASE)
    print(f"  通过率 {d['pass_rate']:.0%}  一致性 {d['consistent']}  flaky {d['flaky']}")
    print("  👉 '一致性 = True' 经常被误读成'稳定、可靠'。")
    print("     一致地错，也是一种一致。**必须同时看通过率。**")

    print("\n" + "=" * 78)
    print("结论与工程建议")
    print("=" * 78)
    print("  · 开发迭代：跑 1 次（快，但别据此下结论）")
    print("  · 上线前：跑 3~5 次（检测 flaky）")
    print("  · 线上：持续抽样，按天统计每个问题的通过率")
    print("\n  ⚠️ temperature=0 也不能保证完全确定：")
    print("     服务端并发、浮点累加顺序、缓存命中都会让输出不同。")
    print("     所以稳定性**必须实测**，不能假设。")
    print("\n  下一级：拿到这些数字之后，怎么判断'这次改动到底算好还是坏'。")


if __name__ == "__main__":
    main()
