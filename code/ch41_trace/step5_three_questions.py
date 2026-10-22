"""第 39 章 · 第 5 级：用 trace 回答三个问题（排障实战）。

运行：
    python code/ch39_trace/step5_three_questions.py

这一级串联前四级，模拟一次"部分失败"的 Agent 运行，
然后用同一个 trace 回答三个问题：
  ① 这次运行多久？哪一步占了一半以上？
  ② 错在哪一步？
  ③ 模型当时看到了什么？

如果你能答出这三个问题，你就掌握了可观测性的全部实用价值。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch02_trace.step3_auto_trace import Tracer  # noqa: E402  复用第 3 级的实现

SINK = Path(__file__).resolve().parents[2] / ".traces" / "ch02_step5.jsonl"


# ---------------------------------------------------------------- 模拟一次真实运行

def fake_search(q: str) -> str:
    time.sleep(0.30)
    return "检索到 3 条退款政策"


def fake_db(q: str) -> str:
    time.sleep(0.80)              # ← 故意很慢
    return "订单 A12345，已签收 3 天"


def fake_mail(q: str) -> str:
    time.sleep(0.05)
    raise RuntimeError("SMTP 连接超时")


def run_agent(tracer: Tracer) -> None:
    with tracer.span("用户请求", user_question="我的耳机能退吗？") as root:
        with tracer.span("步骤1 规划") as s:
            s.attributes["plan"] = ["检索政策", "查订单", "发通知"]
            time.sleep(0.05)

        with tracer.span("步骤2 执行") as s:
            for name, fn in [("工具 search", fake_search), ("工具 db", fake_db), ("工具 mail", fake_mail)]:
                with tracer.span(name) as t:
                    t.attributes["tool"] = name
                    try:
                        t.attributes["result"] = fn("退款")
                    except Exception as e:  # noqa: BLE001
                        t.error = f"{type(e).__name__}: {e}"

        with tracer.span("步骤3 生成") as s:
            # ← 关键：记录"模型看到了什么"
            s.attributes["model"] = "mock-model"
            s.attributes["input_messages"] = [
                {"role": "system", "content": "你是客服助手"},
                {"role": "user", "content": "我的耳机能退吗？"},
                {"role": "tool", "content": "检索到 3 条退款政策 / 订单 A12345，已签收 3 天 / TOOL_FAILED:mail"},
            ]
            time.sleep(0.20)
            s.attributes["output"] = "可以退货，7 天内无理由。"
        root.attributes["status"] = "partial_failure"


# ---------------------------------------------------------------- 从 trace 回答三个问题

def main() -> None:
    if SINK.exists():
        SINK.unlink()
    tracer = Tracer(sink=SINK)

    run_agent(tracer)
    tracer.flush()                    # 写入 JSONL 并释放内存

    # ---- 模拟"排障时"：从磁盘读回（真实流程就是这样） ----
    spans = tracer.load_run()
    print(f"从磁盘读回 {len(spans)} 个 span\n")

    print("=" * 70)
    print("完整调用树")
    print("=" * 70)
    children: dict = {}
    for s in spans:
        children.setdefault(s.parent_id, []).append(s)

    def walk(pid, depth=0):
        for s in sorted(children.get(pid, []), key=lambda x: x.start):
            flag = f"   ❌ {s.error}" if s.error else ""
            print(f"  {'  ' * depth}{s.name:<18}{s.duration_ms:>8.1f}ms{flag}")
            walk(s.span_id, depth + 1)

    walk(None)

    # ---- 问题 ① ----
    print("\n" + "=" * 70)
    print("① 这次运行多久？哪一步占了一半以上？")
    print("=" * 70)
    root = next(s for s in spans if s.parent_id is None)
    total = root.duration_ms
    print(f"  总耗时：{total:.0f}ms")
    steps = [s for s in spans if s.parent_id == root.span_id]
    for s in sorted(steps, key=lambda x: -x.duration_ms):
        print(f"    {s.name:<16}{s.duration_ms:>8.0f}ms  占 {s.duration_ms / total:>5.0%}")
    slow = max(steps, key=lambda x: x.duration_ms)
    print(f"\n  → 结论：{slow.name} 占了 {slow.duration_ms / total:.0%}，它是主要瓶颈。")

    # ---- 问题 ② ----
    print("\n" + "=" * 70)
    print("② 错在哪一步？")
    print("=" * 70)
    errors = [s for s in spans if s.error]
    for s in errors:
        parent = next((p for p in spans if p.span_id == s.parent_id), None)
        print(f"  ❌ {s.name}")
        print(f"     父步骤：{parent.name if parent else '-'}")
        print(f"     错误  ：{s.error}")
    print(f"\n  → 结论：错误发生在「{errors[0].name}」，属于外部依赖问题，不是模型问题。")
    print("     如果没有 trace，你很可能会去改 prompt —— 方向完全错了。")

    # ---- 问题 ③ ----
    print("\n" + "=" * 70)
    print("③ 模型当时看到了什么？")
    print("=" * 70)
    gen = next(s for s in spans if s.name == "步骤3 生成")
    print(f"  模型：{gen.attributes.get('model')}")
    print("  输入消息：")
    for m in gen.attributes.get("input_messages", []):
        print(f"    [{m['role']:<9}] {m['content'][:60]}")
    print(f"  输出：{gen.attributes.get('output')}")
    print("\n  → 结论：模型看到的消息里，'mail' 工具是失败的（TOOL_FAILED:mail），")
    print("     但它仍然回答了'可以退货' —— 说明它没被失败影响，这次回答是对的。")
    print("     **如果不记录 input，你永远无法确认这一点。**")

    print("\n" + "=" * 70)
    print("回顾：你刚才用到的四个能力")
    print("=" * 70)
    print("  1. span 记录每一步（第 1 级）")
    print("  2. parent_id 串成树（第 2 级）")
    print("  3. with 自动维护 + 错误记录（第 3 级）")
    print("  4. 落盘 + 回读（第 3 级）")
    print("\n  这四个能力，就是'可观测性'的全部内容。")
    print("  剩下的（接 Langfuse、OTel 语义约定）只是'把这些数据送到更好的界面'。")

    print(f"\n原始数据：{SINK}")
    print("你可以直接打开它，看看 JSONL 长什么样：")


if __name__ == "__main__":
    main()
