"""第 28 章 step0：从零生成一份评测集骨架，并告诉你"怎么填"。

运行：
    python code/ch14_rag_eval/step0_make_eval_set.py      # 预览
    python code/ch14_rag_eval/step0_make_eval_set.py --write   # 写到 evals/rag_cases.new.json

为什么需要这一步？
  大多数人说"我要做评测"，然后就卡住了——因为不知道 30 条样本从哪来。

这条脚本给出的是"生成器 + 校验器"，不是"答案"：
  1. 先从语料里切出所有小节（每个小节就是一个可被问到的知识点）
  2. 按三类比例生成待填模板：正例 / 边界 / 对抗
  3. 自带一个「填完之后自己检查」的函数

[!] 模板里的 ground_truth 是空的 —— 必须人工填。
   谁填？懂业务的人。模型生成的只能当草稿，必须人工筛（见本章 N.2）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "data" / "售后政策手册.md").read_text(encoding="utf-8")
OUT = ROOT / "evals" / "rag_cases.new.json"

# 三类样本的配比（合计 30 条）：正例 50% / 边界 35% / 对抗 15%
PLAN = [("正例", 15), ("边界", 10), ("对抗", 5)]


def sections() -> list[tuple[str, str, str]]:
    """把语料切成 (锚点, 标题, 正文) 三元组。

    锚点 = "1.1" 这种章节号。它是评测集能跨分块策略复用的关键（见 N.8）。
    """
    out: list[tuple[str, str, str]] = []
    cur_id, cur_title, buf = "", "", []
    for line in DOC.splitlines():
        m = re.match(r"^###\s*(\d+)\.(\d+)\s*(.*)$", line)
        if m:
            if cur_id:
                out.append((cur_id, cur_title, "\n".join(buf).strip()))
            cur_id, cur_title, buf = f"{m.group(1)}.{m.group(2)}", m.group(3).strip(), []
        elif cur_id and not line.startswith("#"):
            buf.append(line)
    if cur_id:
        out.append((cur_id, cur_title, "\n".join(buf).strip()))
    return out


def make() -> list[dict]:
    secs = sections()
    rows: list[dict] = []
    n = 0
    for kind, count in PLAN:
        for i in range(count):
            sec = secs[n % len(secs)]
            n += 1
            rows.append(
                {
                    "id": f"n{len(rows) + 1:02d}",
                    "question": "",
                    "ground_truth": "",
                    "must_contain": [],
                    "tags": [kind],
                    "anchor": "" if kind == "对抗" else sec[0],
                    "source": "待填",
                    "_hint": f"{kind}样本｜建议参考小节 {sec[0]} {sec[1]}",
                }
            )
    return rows


def self_check(rows: list[dict]) -> list[str]:
    """填完之后自己检查：这一步不做，等于白填。"""
    errs = []
    for r in rows:
        rid = r["id"]
        if not r["question"].strip():
            errs.append(f"{rid}: question 为空")
        if not r["ground_truth"].strip():
            errs.append(f"{rid}: ground_truth 为空")
        if not r["must_contain"]:
            errs.append(f"{rid}: must_contain 为空（没有判分标准）")
        if "对抗" in r["tags"] and "未提及" not in r["ground_truth"]:
            errs.append(f"{rid}: 对抗样本的 ground_truth 应该明确写『资料中未提及』")
        if "对抗" not in r["tags"] and not r["anchor"]:
            errs.append(f"{rid}: 非对抗样本必须填 anchor")
    return errs


def main() -> None:
    rows = make()
    print("=" * 74)
    print("评测集模板生成器")
    print("=" * 74)
    print(f"语料里能识别出 {len(sections())} 个小节（= {len(sections())} 个可被问到的知识点）")
    print(f"按 {PLAN} 的比例生成 {len(rows)} 条模板\n")

    for r in rows[:6]:
        print(f"  {r['id']:<5}{r['tags'][0]:<4}{r['_hint']}")
    print(f"  ... 共 {len(rows)} 条")

    print("\n" + "=" * 74)
    print("填完之后必须先跑一次自检")
    print("=" * 74)
    errs = self_check(rows)
    print(f"  当前有 {len(errs)} 条不合格（这是正常的——模板还没填）")
    for e in errs[:5]:
        print(f"    [x] {e}")
    print("  ...")

    if "--write" in sys.argv:
        OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已写入 {OUT.relative_to(ROOT)}（记得把 _hint 字段删掉再提交）")
    else:
        print("\n（这是预览。加 --write 才会写文件）")

    print("\n" + "=" * 74)
    print("三条提醒")
    print("=" * 74)
    print("  1. question 要写「用户真的会怎么问」，不要写「文档里那句话怎么还原」")
    print("  2. must_contain 写 1~3 个必须出现的词，不要写整句话（否则一个标点不同就判错）")
    print("  3. 对抗样本最难写：它必须是**语料里真的没有**的问题，而不是你觉得难的")


if __name__ == "__main__":
    main()
