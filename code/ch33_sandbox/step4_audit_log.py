"""第 34 章 step4：审计 —— 出了事能回答"是谁、在什么时候、做了什么"（离线）。

运行：
    python code/ch33_sandbox/step4_audit_log.py

上一级的痛点：四条边界都设好了，但**你怎么知道它们被触发过**？
这一级做什么：把每次判定都记下来，并回答三个问题：

  1. 今天有多少次越界尝试？
  2. 集中在哪个维度（文件 / 网络 / 执行）？
  3. 哪个工具最容易被模型用来越界？

没有审计的沙箱 = 一道你不知道有没有被撞过的门。
"""
from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.sandbox import Sandbox, SandboxPolicy  # noqa: E402

# 一段"看起来很正常"的 Agent 工作流，中间夹着三次越界
WORKFLOW = [
    ("read", "notes/order.md"),
    ("write", "output/summary.md"),
    ("read", "../../etc/passwd"),
    ("fetch", "https://docs.example.com/policy"),
    ("fetch", "http://169.254.169.254/latest/meta-data/"),
    ("write", "/etc/cron.d/backdoor"),
    ("read", "notes/order.md"),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "workspace"
        (work / "notes").mkdir(parents=True)
        (work / "notes" / "order.md").write_text("订单 A12345 已签收，7 天内可退。", encoding="utf-8")

        policy = SandboxPolicy(workdir=work, net_allow=["docs.example.com"])
        box = Sandbox(policy=policy)

        print("=" * 78)
        print("一段 Agent 工作流（第三次开始越界）")
        print("=" * 78)
        for kind, target in WORKFLOW:
            try:
                if kind == "read":
                    box.read_file(target)
                elif kind == "write":
                    box.write_file(target, "ok")
                else:
                    box.fetch(target)
                print(f"  ✓ {kind:<6}{target}")
            except PermissionError as e:
                print(f"  ✗ {kind:<6}{target}")
                print(f"        {str(e)[:66]}")

        print("\n" + "=" * 78)
        print("① 审计摘要")
        print("=" * 78)
        s = box.audit.summary()
        print(f"  总操作：{s['total']}")
        print(f"  被拒绝：{s['denied']}")
        print(f"  按维度：{s['denied_by_kind']}")

        print("\n" + "=" * 78)
        print("② 每一条拒绝都要能还原现场")
        print("=" * 78)
        print(f"  {'序号':<6}{'维度':<8}{'目标':<40}{'原因'}")
        print("  " + "-" * 92)
        for i, e in enumerate(box.audit.denied(), 1):
            reason = e["reason"][:38]
            print(f"  {i:<6}{e['kind']:<8}{e['target'][:38]:<40}{reason}")

        print("\n" + "=" * 78)
        print("★ 审计的三个价值（缺一个就白记）")
        print("=" * 78)
        print("  1. 事后追责")
        print("     「3 月 5 日 14:23，用户 A 的 Agent 试图写 /etc/cron.d/backdoor，被拒绝」")
        print("     → 没有这条记录，你连'有没有被攻击过'都不知道。")
        print()
        print("  2. 发现攻击面")
        counts = Counter(e["kind"] for e in box.audit.denied())
        dist = "，".join(f"{k} {v} 次" for k, v in counts.most_common())
        print(f"     本次按维度聚合结果：{dist}")
        print("     → 哪个维度最频繁，就说明模型最常往那个方向越界，")
        print("       你先在那条规则上补提示词 / 补样例，收益最大。")
        print()
        print("  3. 验证规则有效性")
        print("     如果某条规则一个月都没触发过，它可能是**多余的**；")
        print("     如果某条规则触发率突然涨了 10 倍，大概率是有人在攻击。")

        print("\n" + "=" * 78)
        print("③ 一条合格审计记录必须有的字段")
        print("=" * 78)
        print(f"  {'字段':<14}{'为什么必须有'}")
        print("  " + "-" * 66)
        print(f"  {'时间':<14}{'排序、还原时间线'}")
        print(f"  {'谁（user/tenant）':<14}{'追责、隔离。**不能只记 agent_id**'}")
        print(f"  {'维度':<14}{'文件 / 网络 / 执行，用于聚合分析'}")
        print(f"  {'目标':<14}{'具体访问了什么（路径 / URL / 命令）'}")
        print(f"  {'放行/拒绝':<14}{'放行的也要记 —— 否则无法区分『没做』和『做了但没记』'}")
        print(f"  {'原因':<14}{'命中了哪条规则，用于调参'}")
        print(f"  {'trace_id':<14}{'串起同一次请求里的所有动作（第 39 章）'}")

        print("\n" + "=" * 78)
        print("⚠️ 三个常见的审计错误")
        print("=" * 78)
        print("  1. 只记拒绝，不记放行")
        print("     → 出事时无法证明'这个动作到底有没有执行'。")
        print()
        print("  2. 记录里带敏感内容")
        print("     → 审计日志本身变成了泄露源（把 /etc/passwd 的内容原样存进去了）。")
        print("     正确做法：只记路径和判定结果，不记文件内容。")
        print()
        print("  3. 日志可被 Agent 修改")
        print("     → Agent 能写工作区，如果日志也在工作区里，它就能删掉证据。")
        print("     正确做法：日志写到独立的、只追加（append-only）的地方。")

        print("\n" + "=" * 78)
        print("结论")
        print("=" * 78)
        counts = Counter(e["kind"] for e in box.audit.denied())
        top = counts.most_common(1)[0] if counts else ("-", 0)
        print(f"  本次工作流：{len(box.audit.entries)} 次操作，"
              f"{len(box.audit.denied())} 次被拒，最高频维度是『{top[0]}』。")
        print()
        print("  这个数字就是你的『攻击面画像』——")
        print("  它告诉你该在哪里加强，而不是凭感觉加规则。")


if __name__ == "__main__":
    main()
