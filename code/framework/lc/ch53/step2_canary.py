"""第 53 章 step2：灰度与 A/B——用 tags 把指标切出来（离线）。

运行：
    python code/framework/lc/ch53/step2_canary.py

上一级的痛点：
    你能对比两个版本了，但**上线**怎么上？
    直接全量切过去，出问题再回滚——那叫"赌博 + 补救"，不叫发布。

这一级做什么：
    ① 按流量比例分流（同一用户始终进同一组，否则体验会跳变）
    ② 用 LangChain 的 `with_config(tags=[...])` 给每次调用打标
    ③ 把"分组 → 指标"的聚合写出来（这是灰度能成立的前提）
    ④ 一个坑：tag 打错了不会报错，只是指标对不上

关键认知：
    灰度的核心不是"分流"，是"**能按分组把指标切出来**"。
    切不出来，你就只是在随机让一部分用户更差。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def bucket(user_id: str, salt: str = "refund-promo") -> float:
    """稳定分桶：同一用户永远落在同一组（0~100）。"""
    h = hashlib.md5(f"{salt}:{user_id}".encode()).hexdigest()
    return int(h[:8], 16) % 100


@dataclass
class Call:
    user_id: str
    group: str
    tags: list[str]
    correct: bool
    latency_ms: int
    tokens: int


@dataclass
class GroupStats:
    name: str
    n: int = 0
    correct: int = 0
    latencies: list[int] = field(default_factory=list)
    tokens: int = 0

    def add(self, c: Call) -> None:
        self.n += 1
        self.correct += 1 if c.correct else 0
        self.latencies.append(c.latency_ms)
        self.tokens += c.tokens

    @property
    def acc(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def p95(self) -> int:
        if not self.latencies:
            return 0
        s = sorted(self.latencies)
        return s[min(len(s) - 1, int(len(s) * 0.95))]

    @property
    def avg_tokens(self) -> float:
        return self.tokens / self.n if self.n else 0.0


def main() -> None:
    print("=" * 78)
    print("① 分桶：为什么不能随机")
    print("=" * 78)
    for uid in ["u1001", "u1002", "u1003", "u1004", "u1005"]:
        b = bucket(uid)
        print(f"  {uid} → 桶 {b:>2} → {'v2（实验组）' if b < 20 else 'v1（对照组）'}")
    print("  同一个 uid 跑 5 次，桶永远一样（哈希，不是随机数）")
    print("  → 随机分流会让同一用户在两版之间跳变：昨天能退、今天不能退。")

    print("\n" + "=" * 78)
    print("② 打标：tags 是「按版本切指标」的唯一可靠办法")
    print("=" * 78)
    print("""  chain = prompt | model | parser

  # 对照组
  chain.with_config(tags=["exp:refund-v1", "group:control"], run_name="refund_qa")
  # 实验组
  chain.with_config(tags=["exp:refund-v2", "group:treat"], run_name="refund_qa")

  → tags 会随调用上报到 LangSmith / LangFuse（第 52 章）
  → 这两个 tag 是后续"按组聚合"的全部依据""")

    print("\n" + "=" * 78)
    print("③ 模拟一次 5% 灰度：跑 200 个用户，按组聚合指标")
    print("=" * 78)
    calls: list[Call] = []
    # v2 的真实行为：准确率略高、但更慢更贵（因为提示词变长了）
    for i in range(200):
        uid = f"u{1000 + i}"
        b = bucket(uid)
        treat = b < 5              # 5% 进实验组
        group = "treat" if treat else "control"
        version = "v2" if treat else "v1"

        # 用确定性"随机"模拟结果，保证可复现
        noise = int(hashlib.md5(f"r:{uid}".encode()).hexdigest()[:4], 16) % 100
        if treat:
            correct = noise < 92           # v2：92% 正确
            latency = 900 + (noise % 90)
            tokens = 470
        else:
            correct = noise < 85           # v1：85% 正确
            latency = 700 + (noise % 80)
            tokens = 320

        calls.append(Call(uid, group,
                          tags=[f"exp:refund-{version}", f"group:{group}"],
                          correct=correct, latency_ms=latency, tokens=tokens))

    stats: dict[str, GroupStats] = {}
    for c in calls:
        stats.setdefault(c.group, GroupStats(c.group)).add(c)

    print(f"  {'分组':<10}{'样本数':>8}{'准确率':>10}{'P95 延迟':>12}{'平均 token':>12}")
    print("  " + "-" * 56)
    for name in ("control", "treat"):
        s = stats[name]
        print(f"  {name:<10}{s.n:>8}{s.acc:>9.1%}{s.p95:>11}ms{s.avg_tokens:>12.0f}")

    ctrl, tr = stats["control"], stats["treat"]
    print(f"\n  准确率差：{tr.acc - ctrl.acc:+.1%}（样本 {tr.n}，5% 灰度）")
    print(f"  P95 延迟差：{tr.p95 - ctrl.p95:+d}ms")
    print(f"  token 差：{tr.avg_tokens - ctrl.avg_tokens:+.0f}/次")

    print("\n  ⚠️ 上面这组数字**不能**用来下结论 —— 实验组只有 8 个样本。")
    print("    这就是灰度最容易被误读的地方：5% 流量下，一天可能只有几十个样本，")
    print("    准确率差 ±11% 完全在噪声范围内。做个置信区间就知道：")
    n, p = tr.n, tr.acc
    se = (p * (1 - p) / n) ** 0.5 if n else 0
    print(f"    treat 准确率 {p:.1%}，n={n}，标准误 ≈ {se:.1%}，95% 区间 ≈ "
          f"{max(0, p - 1.96 * se):.1%} ~ {min(1, p + 1.96 * se):.1%}")
    print("    要证明 +7 点的提升，每组至少要几百个样本（可用样本量计算器估）。")
    print("    **所以灰度的第一件事是算样本量，不是开流量。**")

    print("\n  → 三个数字必须一起看：准确率、延迟、成本。")
    print("    只报'准确率 +7%'的 A/B，是在隐瞒另外两列。")

    print("\n" + "=" * 78)
    print("④ 一个坑：tag 打错了不会报错")
    print("=" * 78)
    bad = [Call("u1", "treat", ["exp:refund-v3", "group:treat"], True, 900, 470)]
    s = GroupStats("treat")
    s.add(bad[0])
    print(f"  tag 写成 exp:refund-v3（不存在的版本），调用依然成功：{s.n} 条")
    print("  → 后果：你在看板里过滤 exp:refund-v2，发现'实验组一条数据都没有'。")
    print("  → 防线：tag 用常量生成，并在启动时断言 tag 集合与版本注册表一致。")

    print("\n" + "=" * 78)
    print("⑤ 灰度决策表（抄进你的发布流程）")
    print("=" * 78)
    print("""  | 阶段 | 流量 | 看什么 | 通过条件 |
  |---|---|---|---|
  | 影子 | 0%（只记录不返回） | 报错率、延迟 | 报错率不高于基线 |
  | 内测 | 内部用户 | 人工体感 | 无 P0 问题 |
  | 灰度 | 1% → 5% → 20% | 准确率 / P95 / 成本 | 三项都不劣化，且至少一项变好 |
  | 全量 | 100% | 同上 + 投诉率 | 连续 3 天稳定 |
  | 回滚判据 | — | 准确率 −3 点 或 P95 ×1.5 或 报错率 ×2 | **立即回滚，不讨论** |
  """)


if __name__ == "__main__":
    main()
