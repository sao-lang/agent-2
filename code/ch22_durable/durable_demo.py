"""第 22 章示例：进程被杀 → 重启 → 继续跑完（不需要 API）。

运行：
    python code/ch22_durable/durable_demo.py simulate
    python code/ch22_durable/durable_demo.py resume

step 1（simulate）：跑三步，到"撰写结论"前触发人工确认 → 把进程"杀掉"
step 2（resume） ：新进程启动，从 SQLite 恢复状态 → 批准 → 跑完

为什么分两次运行而不是一个脚本里完成？
因为第 1 次运行结束后**内存里的对象全部销毁**，
第 2 次运行是真正的"新进程"——这才叫"重启可恢复"。

同一个脚本内 resume 只能证明"checkpointer 能读回状态"，
分两次运行才能证明"进程无关"。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.types import Command  # noqa: E402

from common.durable import ROOT_DB, build, make_saver  # noqa: E402

THREAD = "task-42"


def simulate() -> None:
    if ROOT_DB.exists():
        ROOT_DB.unlink()
    saver, conn = make_saver(ROOT_DB)
    app = build(saver)
    cfg = {"configurable": {"thread_id": THREAD}}

    print("=== 第一次运行（会停在人工确认前）===")
    out = app.invoke({"goal": "调研竞品定价", "findings": [], "executed": []}, cfg)
    print(f"  返回：{json.dumps(out, ensure_ascii=False, default=str)[:200]}")
    if "__interrupt__" in out:
        q = out["__interrupt__"][0].value
        print(f"  ⏸  已中断，等待确认：{q}")

    snap = app.get_state(cfg)
    print("\n=== 当前状态（存在 SQLite 里）===")
    print(f"  next:     {snap.next}")
    print(f"  cursor:   {snap.values.get('cursor')}")
    print(f"  findings: {snap.values.get('findings')}")
    print(f"  executed: {snap.values.get('executed')}")
    conn.close()
    print(f"\n  数据库：{ROOT_DB}")
    print("  现在假设进程被 kill -9（我们直接结束进程）。")
    print("  下一步执行：python code/ch22_durable/durable_demo.py resume")


def resume() -> None:
    if not ROOT_DB.exists():
        print("❌ 没有找到检查点，请先运行 simulate")
        return
    saver, conn = make_saver(ROOT_DB)
    app = build(saver)
    cfg = {"configurable": {"thread_id": THREAD}}

    snap = app.get_state(cfg)
    print("=== 第二次运行（新进程）===")
    print(f"  从检查点恢复：cursor={snap.values.get('cursor')} next={snap.next}")
    print(f"  已完成：{snap.values.get('executed')}")

    print("\n  批准确认 → 继续执行")
    out = app.invoke(Command(resume=True), cfg)
    print(f"\n  最终结果：{out.get('final')}")
    print(f"  执行记录：{out.get('executed')}")
    conn.close()

    print("\n👉 关键点：'检索'和'整理要点'**没有被重跑**——")
    print("   因为 executed 里记录了它们，execute_node 会跳过。")


def inspect() -> None:
    """查看所有检查点（这就是"时间旅行"的基础）。"""
    saver, conn = make_saver(ROOT_DB)
    app = build(saver)
    cfg = {"configurable": {"thread_id": THREAD}}
    print("=== 检查点历史 ===")
    for i, snap in enumerate(app.get_state_history(cfg)):
        print(f"  #{i}  next={snap.next}  cursor={snap.values.get('cursor')}")
    conn.close()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "simulate"
    {"simulate": simulate, "resume": resume, "inspect": inspect}[cmd]()


if __name__ == "__main__":
    main()
