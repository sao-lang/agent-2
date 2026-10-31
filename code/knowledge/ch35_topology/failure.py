"""交接单校验与分支失败的处理。

不联网。两段：
  1. 一份缺字段的交接单被打回，而不是被接进上下文
  2. 三个分支里有一个超时：整轮失败，还是带着缺失继续

运行：python code/knowledge/ch35_topology/failure.py
"""

from __future__ import annotations

from actors import Brief, pad

REQUIRED = ("task", "result", "evidence", "confidence")


class Timeout(Exception):
    pass


def validate(brief: Brief) -> list[str]:
    """返回缺的字段；空列表表示可以接。"""
    return [name for name in REQUIRED if not getattr(brief, name, "")]


def run(policy: str) -> str:
    findings = ["连接池在 db.py:42 耗尽", "client.py:88 的重试没有 max_attempts"]
    missing: list[int] = []
    for i in (1, 2, 3):
        try:
            if i == 2:
                raise Timeout(f"worker{i} 超时")
            findings.append(f"日志 {i}：已定位")
        except Timeout:
            if policy == "fail_all":
                raise
            missing.append(i)
    tail = f"；缺第 {'、'.join(map(str, missing))} 份" if missing else ""
    return "初报：" + "；".join(findings) + tail


def main() -> None:
    good = Brief(task="日志 1", result="连接池耗尽", evidence="db.py:42",
                 confidence="high")
    bad = Brief(task="日志 2", result="可能有点问题", evidence="", confidence="")

    print("=== 1. 交接单校验 ===")
    for label, brief in (("完整", good), ("缺依据", bad)):
        missing = validate(brief)
        verdict = "接收" if not missing else f"打回，缺 {missing}"
        print(f"  {pad(label, 8)}{verdict}")
    print("  <- 缺 evidence 的结论不能进上下文；否则主 agent 只能选择相信或重读")
    print()

    print("=== 2. 一个分支超时，两种策略 ===")
    for policy in ("fail_all", "degrade"):
        try:
            report = run(policy)
            print(f"  {pad(policy, 10)}继续：{report}")
        except Timeout as e:
            print(f"  {pad(policy, 10)}整轮失败：{e}")
    print("  <- 缺的那一项不是后续步骤的前提时，降级比整轮重来便宜")


if __name__ == "__main__":
    main()
