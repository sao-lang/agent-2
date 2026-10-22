"""第 2 章示例：一个带完整 trace 的 mini Agent（3 步，不依赖真实工具）。

运行：
    python code/ch02_trace/demo_trace.py

它演示三件事：
  1. span 层级：run → step → tool_call / model_call
  2. 从 trace 还原调用树
  3. 从 trace 回答"最慢的是什么""错在哪一步"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import ROOT  # noqa: E402
from common.trace import Tracer  # noqa: E402


# ---------- 假工具：故意让第二个变慢、第三个失败 ----------

def fake_search(q: str) -> str:
    time.sleep(0.30)
    return f"[{q}] 检索到 3 条结果"


def fake_slow_db(q: str) -> str:
    time.sleep(0.80)
    return "500 条记录"


def fake_flaky_api(q: str) -> str:
    time.sleep(0.10)
    raise RuntimeError("上游服务 503")


TOOLS = {"search": fake_search, "db": fake_slow_db, "api": fake_flaky_api}


def run_agent(tracer: Tracer) -> None:
    with tracer.run("mini-agent", user_query="查一下上季度销量并给出建议") as run:
        # step 1：规划
        with tracer.step("plan") as s:
            s.input = "用户问题：查一下上季度销量并给出建议"
            s.output = ["search", "db", "api"]
            time.sleep(0.05)

        # step 2：调用工具（3 个，其中 1 个失败）
        with tracer.step("act") as s:
            results = []
            for name in ["search", "db", "api"]:
                with tracer.tool_call(name, tool=name) as t:
                    t.input = {"q": "上季度销量"}
                    try:
                        out = TOOLS[name]("上季度销量")
                        t.output = out
                        results.append(out)
                    except Exception as e:  # noqa: BLE001
                        # 关键：工具失败不该让整次运行崩掉，但要留下痕迹
                        t.error = f"{type(e).__name__}: {e}"
                        results.append(f"TOOL_FAILED:{name}")
            s.output = results

        # step 3：模型汇总（这里用 sleep 模拟，避免示例必须联网）
        with tracer.step("answer") as s:
            with tracer.model_call("summarize", model="mock-model") as m:
                time.sleep(0.20)
                m.attributes["tokens"] = {"in": 420, "out": 120}
                m.output = "建议：……"
            s.output = "建议：……"

        run.attributes["status"] = "partial_failure"


def main() -> None:
    sink = ROOT / ".traces" / "ch02_spans.jsonl"
    if sink.exists():
        sink.unlink()  # 示例每次从干净文件开始，避免读到上一次的旧 span
    tracer = Tracer(sink=sink)

    run_agent(tracer)  # run 结束时已自动 flush 到 JSONL

    spans = tracer.load_run()
    print("=== 调用树（从磁盘读回） ===")
    print(tracer.tree(spans=spans))

    print("\n=== 最慢的 3 个 span ===")
    for s in tracer.slowest(3, spans=spans):
        print(f"{s.kind:<11} {s.name:<12} {s.duration_ms:>8.1f}ms")

    print("\n=== 出错的 span ===")
    for s in spans:
        if s.error:
            print(f"{s.kind:<11} {s.name:<12} {s.error}")

    print(f"\nspan 已导出：{sink}")
    print("\n👉 现在试着回答：这次运行总共多久？哪一步占了一半以上？失败发生在第几步？")
    print("   如果这三个问题你答得出来，你就已经拥有可观测性了。")


if __name__ == "__main__":
    main()
