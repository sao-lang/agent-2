"""全书代码示例清查：每章有什么代码、用了什么库、哪些是"代用品"。

输出一张表，供人工判定"这一章该不该用真实库、现在缺什么"。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(".").resolve()

FAKE_MARKERS = [
    "原理演示", "演示用", "代替真实", "字符 2-gram", "字符2-gram", "字面重合",
    "脚本化的假后端", "假后端", "模拟", "示意", "不是实测", "无依赖",
]

REAL_LIBS = {
    "langchain", "langchain_core", "langchain_text_splitters", "langchain_community",
    "langgraph", "langfuse", "pydantic_ai", "sentence_transformers", "qdrant_client",
    "faiss", "rank_bm25", "jieba", "numpy", "sklearn", "transformers", "torch",
    "llama_index", "ragas", "openai", "scipy",
}

STDLIB_OK_CHAPTERS = {"00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"}


def chapter_files() -> list[Path]:
    return sorted(p for p in ROOT.glob("*.md") if re.match(r"^\d\d-", p.name))


def code_fences(text: str) -> tuple[int, int]:
    py = len(re.findall(r"^```python", text, re.M))
    total = len(re.findall(r"^```", text, re.M)) // 2
    return py, total


def imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def main() -> None:
    print(f"{'章':<4}{'py块':>5}{'全部块':>7}{'示例文件':>9}{'行数':>7}  {'真实库':<28}{'代用品标记'}")
    print("-" * 110)
    for md in chapter_files():
        num = md.name[:2]
        text = md.read_text(encoding="utf-8")
        py, total = code_fences(text)
        m = re.search(r"示例目录\*\*：`([^`]+)`", text)
        example_dir = m.group(1) if m else ""
        files: list[Path] = []
        if example_dir and (ROOT / example_dir).exists():
            files = sorted((ROOT / example_dir).glob("*.py"))
        lines = sum(len(f.read_text(encoding="utf-8").splitlines()) for f in files)
        libs: set[str] = set()
        for f in files:
            libs |= (imports_of(f) & REAL_LIBS)
        markers = [w for w in FAKE_MARKERS if w in text]
        lib_txt = ",".join(sorted(libs))[:26] if libs else "-"
        print(f"{num:<4}{py:>5}{total:>7}{len(files):>9}{lines:>7}  {lib_txt:<28}{','.join(markers[:3])}")


if __name__ == "__main__":
    main()
