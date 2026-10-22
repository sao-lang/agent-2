"""S6-b：修正代码 docstring 里的 `code/chNN_xxx/` 路径（目录已改名）。

为什么单独写一个：
    章节重排时，md 正文里的路径由 renumber_s6.py 统一处理；
    但每个 .py 文件 docstring 里的"运行："示例也写着旧目录名，
    如果不改，读者照抄命令会找不到文件。

规则与 renumber_s6.py 一致：章号 >= 31 → -2。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIFT_FROM = 31
SHIFT_BY = 2

# 目录名 旧 → 新（只列真正改了的；同时兼容旧旧名）
DIR_MAP = {
    # 第 5 轮旧名（部分文件没跟上）→ 现名
    "ch19_guardrails": "ch31_guardrails",
    "ch20_hitl": "ch32_hitl",
    "ch21_sandbox": "ch33_sandbox",
    "ch22_cost": "ch34_cost",
    "ch23_latency": "ch35_latency",
    "ch24_wiki": "ch29_wiki",
    "ch25_wiki_ops": "ch30_wiki_ops",
    "ch26_multi_agent": "ch36_multi_agent",
    "ch01_measuring": "ch37_measuring",
    "ch02_trace": "ch38_trace",
    "ch03_loop": "ch16_loop",
    "ch04_react": "ch17_react",
    "ch05_workflow": "ch18_workflow",
    "ch06_plan_execute": "ch19_plan_execute",
    "ch07_reflection": "ch20_reflection",
    "ch08_replan": "ch21_replan",
    "ch09_durable": "ch22_durable",
    "ch10_state": "ch23_state",
    "ch11_context": "ch24_context",
    "ch12_chunking": "ch09_chunking",
    "ch13_retrieval": "ch10_retrieval_opt",
    "ch14_intent": "ch25_intent",
    "ch15_graphrag": "ch28_graphrag",
    "ch16_rag_eval": "ch40_rag_eval",
    "ch17_short_memory": "ch26_short_memory",
    "ch18_long_memory": "ch27_long_memory",
    "ch37_eval": "ch41_eval",
    "ch38_postmortem": "ch55_postmortem",
    "ch42_harness": "ch56_harness",
    # 本次 S6 位移
    "ch31_wiki": "ch29_wiki",
    "ch32_wiki_ops": "ch30_wiki_ops",
    "ch33_guardrails": "ch31_guardrails",
    "ch34_hitl": "ch32_hitl",
    "ch35_sandbox": "ch33_sandbox",
    "ch36_cost": "ch34_cost",
    "ch37_latency": "ch35_latency",
    "ch38_multi_agent": "ch36_multi_agent",
    "ch39_measuring": "ch37_measuring",
    "ch40_trace": "ch38_trace",
    "ch40_eval": "ch38_eval",
    "ch42_rag_eval": "ch40_rag_eval",
    "ch43_eval": "ch41_eval",
    "ch57_postmortem": "ch55_postmortem",
    "ch58_harness": "ch56_harness",
}


def fix_paths(text: str) -> str:
    # 反复替换直到稳定（处理链式改名）
    for _ in range(5):
        before = text
        for old, new in DIR_MAP.items():
            text = text.replace(f"code/{old}/", f"code/{new}/")
            text = text.replace(f"code\\{old}\\", f"code\\{new}\\")
        # 兜底：`code/chNN_xxx/` 里 NN >= 31 且不在上面表的，按 -2 改
        def _shift(m: re.Match[str]) -> str:
            n = int(m.group(1))
            return f"code/ch{n - SHIFT_BY:02d}_{m.group(2)}/" if n >= SHIFT_FROM else m.group(0)

        text = re.sub(r"code/ch(\d\d)_(\w+)/", _shift, text)
        if text == before:
            break
    return text


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    changed = []
    for p in sorted(ROOT.glob("code/**/*.py")):
        original = p.read_text(encoding="utf-8")
        final = fix_paths(original)
        if final != original:
            changed.append(p.relative_to(ROOT).as_posix())
            if args.apply:
                p.write_text(final, encoding="utf-8")

    print(f"{'将修正' if not args.apply else '已修正'} {len(changed)} 个 py 文件里的目录路径")
    for c in changed[:25]:
        print(f"  {c}")
    if len(changed) > 25:
        print(f"  …… 还有 {len(changed) - 25} 个")
    if not args.apply:
        print("\n（预演模式，加 --apply 生效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
