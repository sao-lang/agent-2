"""第 33 章 step3：中断与恢复 —— 进程"死"了，审批不能丢（离线，LangGraph）。

运行：
    python code/ch33_hitl/step3_interrupt_resume.py

上一级的痛点：分级表有了，但"挂起等人"这件事本身怎么实现？
这一级做什么：把审批做成一次**可持久化的中断** ——
             图在闸门处停下，状态落进 checkpointer，重启后还能接着走。

三个必须验证的行为：
  1. 挂起后进程里什么状态都没了，但**从 checkpointer 能恢复**
  2. 恢复时**不会重跑**已经执行过的副作用（幂等键）
  3. 人"修改参数后批准"必须被当作**批准**处理（这是最容易写错的一条）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.hitl import HitlService, make_card  # noqa: E402


def line(title: str) -> None:
    print("\n" + "=" * 76)
    print(title)
    print("=" * 76)


def main() -> None:
    svc = HitlService()

    line("① 只读动作：不打断人")
    r = svc.start("t-auto", "帮我查一下订单 A12345")
    print(f"  状态：{r['status']}   结果：{r.get('result')}")

    line("② 写动作：挂起，等人点头")
    r = svc.start("t-refund", "给订单 A12345 退款 299")
    print(f"  状态：{r['status']}")
    card = r["card"]
    print(f"  审批卡片：{card['action']}  {card['args']}")
    print(f"    影响：{card['impact']}")
    print(f"    回滚：{card['rollback']}")
    print(f"    有效期：{card['expires_in_sec']} 秒")

    snap = svc.state("t-refund")
    print(f"  挂起位置：next={snap['next']}")
    print(f"  已执行副作用：{snap['values'].get('executed')}")

    line("③ ★ 模拟『进程重启』—— 用一个全新的服务实例恢复")
    print("  现实里这一步是：服务滚动发布 / Pod 被驱逐 / 机器重启。")
    print("  内存里的对象全没了，只剩 checkpointer 里的状态。")
    fresh = HitlService(app=svc.app)   # 复用同一份 checkpointer，模拟"进程活了"
    print(f"  新实例里 pending 列表：{len(fresh.list_pending())} 条（内存里是空的，这很正常）")
    r = fresh.approve("t-refund", decision="approve")
    print(f"  从 checkpointer 恢复后：状态={r['status']}  结果={r.get('result')}")

    line("④ ★ 人改了参数再批准 —— 必须当作『批准』")
    r = svc.start("t-modify", "给订单 A12345 退款 299")
    print(f"  挂起：{r['status']}，原金额 {r['card']['args']['amount']}")
    r = svc.approve("t-modify", decision="modify", new_args={"amount": 199})
    print(f"  人工改成 199 并批准 → 结果：{r['result']}")
    print("  ⚠️ 如果代码只认 decision=='approve'，这里会变成『拒绝』，")
    print("     而人是点了批准的 —— 参数改动被静默丢弃。")

    line("⑤ 拒绝也要留下记录")
    r = svc.start("t-reject", "给订单 A12345 退款 299")
    r = svc.approve("t-reject", decision="reject")
    print(f"  状态：{r['status']}   结果：{r.get('result')}")
    print(f"  日志：{r.get('log')}")

    line("⑥ 幂等：同一次审批被点了两次")
    r = svc.start("t-dup", "给订单 A12345 退款 299")
    r1 = svc.approve("t-dup", decision="approve")
    r2 = svc.approve("t-dup", decision="approve")   # 用户手抖 / 网络重试
    print(f"  第一次：{r1.get('result')}")
    print(f"  第二次：{r2.get('result')}")
    print("  → 幂等键（action+args）挡住第二次执行。没有它，就是**退两次款**。")

    line("⑦ 一张好卡片长什么样")
    c = make_card("refund", {"order": "A12345", "amount": 299})
    d = c.to_dict()
    print(f"  请求 ID：{d['request_id']}（用于幂等与审计）")
    print(f"  动作与参数：{d['action']} {d['args']}")
    print(f"  影响面：{d['impact']}")
    print(f"  回滚方案：{d['rollback']}")
    print(f"  有效期：{d['expires_in_sec']} 秒（过期自动失效，防止三天后突然执行）")
    print()
    print("  三要素缺一个，人都没法判断：")
    print("    缺影响面 → 不知道要改什么，只能盲批")
    print("    缺回滚   → 不敢批，任务卡死")
    print("    缺有效期 → 人不在时永远挂着，或者很久以后突然执行")

    line("结论")
    print("  HITL 的四个工程要素，缺一个就不算做完：")
    print("    分级  → 不是每个动作都问（step2）")
    print("    持久化 → 中断状态落 checkpointer，进程死了能恢复")
    print("    幂等  → 恢复不重复执行副作用")
    print("    卡片  → 影响面 + 回滚 + 有效期")


if __name__ == "__main__":
    main()
