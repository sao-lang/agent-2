"""第 6 轮 S2：把已完成章节的编号统一迁到终版编号（只改号，不改内容）。

运行（项目根目录）：
    python tools/renumber_v6.py            # 预演：只打印将要改什么
    python tools/renumber_v6.py --apply    # 真正写回

为什么需要这个脚本：
    第 6 轮把全书结构改成"总览 → 概念 → LLM/RAG → Agent → Harness"，
    已有 29 章的编号全部变了（例如 01-从能调通到可计量 → 39-从能调通到可计量）。
    文件已经重命名好，但正文里的 `## 1.3`、`第 58 章`、`code/ch01_xxx/` 等引用还是旧号。

它按"旧号 → 新号"映射统一替换，所以：
  · **幂等**：跑两次结果一样（内部按占位符替换，不做链式替换）
  · **只认三种形式**：`## N.M` 标题 / `第 N 章` 引用 / `code/chNN_xxx` 路径
  · 其它数字（"第 3 步""3 个要点"）不动，避免误伤

映射表（旧号 → 新号）写死在 MAPPING 里，与 `整合映射表.md` 第三节一致。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 旧章号 → 新章号（旧号指"第 5 轮结束时的编号"）
MAPPING: dict[int, int] = {
    1: 39, 2: 40,
    3: 16, 4: 17, 5: 18, 6: 19, 7: 20, 8: 21, 9: 22, 10: 23,
    11: 24, 12: 29, 13: 30, 14: 25, 15: 28, 16: 42,
    17: 26, 18: 27,
    19: 33, 20: 34, 21: 35, 22: 36, 23: 37,
    24: 31, 25: 32, 26: 38,
    37: 43, 38: 57, 42: 58,
}

# 代码目录：旧名 → 新名
DIR_MAPPING: dict[str, str] = {
    "ch01_measuring": "ch39_measuring",
    "ch02_trace": "ch40_trace",
    "ch03_loop": "ch16_loop",
    "ch04_react": "ch17_react",
    "ch05_workflow": "ch18_workflow",
    "ch06_plan_execute": "ch19_plan_execute",
    "ch07_reflection": "ch20_reflection",
    "ch08_replan": "ch21_replan",
    "ch09_durable": "ch22_durable",
    "ch10_state": "ch23_state",
    "ch11_context": "ch24_context",
    "ch12_chunking": "ch29_chunking",
    "ch13_retrieval": "ch30_retrieval",
    "ch14_intent": "ch25_intent",
    "ch15_graphrag": "ch28_graphrag",
    "ch16_rag_eval": "ch42_rag_eval",
    "ch17_short_memory": "ch26_short_memory",
    "ch18_long_memory": "ch27_long_memory",
    "ch19_guardrails": "ch33_guardrails",
    "ch20_hitl": "ch34_hitl",
    "ch21_sandbox": "ch35_sandbox",
    "ch22_cost": "ch36_cost",
    "ch23_latency": "ch37_latency",
    "ch24_wiki": "ch31_wiki",
    "ch25_wiki_ops": "ch32_wiki_ops",
    "ch26_multi_agent": "ch38_multi_agent",
    "ch37_eval": "ch43_eval",
    "ch38_postmortem": "ch57_postmortem",
    "ch42_harness": "ch58_harness",
}


def chapter_no(path: Path) -> int | None:
    head = path.name[:2]
    return int(head) if head.isdigit() and path.name[2:3] == "-" else None


def renumber_headings(text: str, old: int, new: int) -> str:
    if old == new:
        return text
    return re.sub(rf"(?m)^## {old}\.(\d+)", rf"## {new}.\1", text)


def renumber_refs(text: str, mapping: dict[int, int]) -> str:
    """`第 N 章` / `N.M 节` / `见 N.M` 里的章号 → 新号。

    先换成占位符 `~n~`，最后统一落成新号，避免 14→25 之后又被 25→xx 再换一次。
    """
    def repl_chapter(m: re.Match[str]) -> str:
        nums = re.findall(r"\d+", m.group(1))
        return "第 " + "/".join(f"~{n}~" for n in nums) + " 章"

    text = re.sub(r"第\s*(\d+(?:\s*[/、,]\s*\d+)*)\s*章", repl_chapter, text)
    text = re.sub(r"(\d+)\.(\d+)\s*节", lambda m: f"~{m.group(1)}~.{m.group(2)} 节", text)
    text = re.sub(r"(见|参考|详见|参见)\s*(\d+)\.(\d+)",
                  lambda m: f"{m.group(1)} ~{m.group(2)}~.{m.group(3)}", text)

    return re.sub(r"~(\d+)~", lambda m: str(mapping.get(int(m.group(1)), int(m.group(1)))), text)


def fix_dirs(text: str) -> str:
    for old, new in DIR_MAPPING.items():
        text = text.replace(f"code/{old}/", f"code/{new}/").replace(f"code\\{old}\\", f"code\\{new}\\")
    return text


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv[1:])

    files = sorted(p for p in ROOT.glob("[0-9][0-9]-*.md"))
    new_to_old: dict[int, list[int]] = {}
    for old, new in MAPPING.items():
        new_to_old.setdefault(new, []).append(old)

    total = 0
    touched = 0
    for path in files:
        new = chapter_no(path)
        if new is None:
            continue
        text = orig = path.read_text(encoding="utf-8")
        for old in new_to_old.get(new, []):
            text = renumber_headings(text, old, new)
        text = renumber_refs(text, MAPPING)
        text = fix_dirs(text)
        if text != orig:
            touched += 1
            diff = sum(1 for a, b in zip(orig.split("\n"), text.split("\n")) if a != b)
            total += diff
            print(f"  {path.name:<38} {diff} 行")
            if args.apply:
                path.write_text(text, encoding="utf-8")

    for base in ("code", "tests", "tools"):
        for path in (ROOT / base).rglob("*.py"):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            text = orig = path.read_text(encoding="utf-8", errors="ignore")
            text = fix_dirs(text)
            text = renumber_refs(text, MAPPING)
            if text != orig:
                touched += 1
                if args.apply:
                    path.write_text(text, encoding="utf-8")

    print(f"\n{'已写入' if args.apply else '预演（加 --apply 才写）'}：{touched} 个文件，正文约 {total} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
