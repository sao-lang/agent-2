import re
import sys
from pathlib import Path

sys.path.insert(0, "docs")
from lint_prose import prose_only, paragraphs, zh, measure


def main() -> None:
    p = Path(sys.argv[1])
    text = p.read_text(encoding="utf-8")
    body = prose_only(text)
    paras = paragraphs(body)
    total = 0
    for i, para in enumerate(paras):
        n = zh(para)
        total += n
        head = para.replace("\n", " ")[:46]
        print(f"{i:3d} {n:5d}  {head}")
    m = measure(text)
    print(f"\nTOTAL prose_zh={m['prose_zh']} paras={m['paras']} avg={m['avg_para']}")


main()
