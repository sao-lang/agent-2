"""第 39 章 step1：文档生命周期——从"一个 md 文件"到"能追溯的条目"（离线）。

运行：
    python code/ch40_data/step1_lifecycle.py

上一级（第 38 章）的痛点：
    你能查到"这次调用为什么错"，但查不到"这条知识是什么时候进来的、谁改的、还作不作数"。
    文档一多，"知识库"就变成一个没人敢动的黑盒。

这一级做什么：
    ① 把文档过一遍完整生命周期：接入 → 解析 → 清洗 → 分块 → 索引 → 打版本
    ② 每个阶段都留"可追溯的痕迹"（document_id / version / content_hash / updated_at）
    ③ 演示"内容没变但文件重新上传"这种情况，看怎么避免重复入库
    ④ 演示"文档删了但索引还在"这个最经典的线上事故

关键认知：
    数据层的核心不是"存下来"，是**"能回答这三个问题"**：
      这条知识从哪来？现在还有效吗？删掉源头时索引跟着删了吗？
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "data" / "售后政策手册.md"


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------- 清洗规则
NOISE_PATTERNS = [
    (r"内部知识库[）)]", "内部知识库）"),      # 占位：保留（示例，不实际改）
    (r"\n{3,}", "\n\n"),                      # 连续空行
    (r"[ \t]+\n", "\n"),                      # 行尾空白
    (r"第\s*\d+\s*页", ""),                   # 页码
    (r"^\s*-\s*$", ""),                        # 空列表项
]


def clean(text: str) -> tuple[str, list[str]]:
    """清洗并返回"改了什么"（可审计）。"""
    applied = []
    for pat, repl in NOISE_PATTERNS:
        new = re.sub(pat, repl, text, flags=re.MULTILINE)
        if new != text:
            applied.append(f"{pat} → {repl!r}")
        text = new
    return text, applied


# ---------------------------------------------------------------- 条目模型
@dataclass
class Chunk:
    doc_id: str
    version: int
    chunk_id: str
    heading: str
    text: str
    content_hash: str
    source: str
    updated_at: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    doc_id: str
    source: str
    version: int
    content_hash: str
    updated_at: str
    chunks: list[Chunk] = field(default_factory=list)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 流水线
def ingest(path: Path, version: int, store: dict[str, Document]) -> Document | None:
    """接入一份文档。返回 None 表示"内容没变，跳过"。"""
    raw = path.read_text(encoding="utf-8")
    digest = sha(raw)

    existing = store.get(path.name)
    if existing and existing.content_hash == digest:
        print(f"  跳过：{path.name} 内容未变（hash {digest}）")
        return None

    text, applied = clean(raw)
    sections = re.split(r"\n(?=#{2,3} )", text)
    chunks = []
    for i, sec in enumerate(sections):
        sec = sec.strip()
        if not sec:
            continue
        heading = sec.splitlines()[0].lstrip("# ").strip()
        chunks.append(
            Chunk(
                doc_id=path.name,
                version=version,
                chunk_id=f"{path.stem}#v{version}#c{i:02d}",
                heading=heading,
                text=sec[:300],
                content_hash=sha(sec),
                source=str(path.name),
                updated_at=now(),
                tags=["售后"] if "售后" in heading or "退" in heading else [],
            )
        )

    doc = Document(path.name, str(path.name), version, digest, now(), chunks)
    store[path.name] = doc
    print(f"  入库：{path.name} v{version} → {len(chunks)} 块（清洗应用 {len(applied)} 条规则）")
    if not applied:
        print("      （本语料很干净，清洗规则一条都没触发 —— 真实文档里通常有页码/页眉）")
    for a in applied:
        print(f"      清洗：{a}")
    return doc


def main() -> None:
    store: dict[str, Document] = {}

    line("① 完整生命周期：接入 → 清洗 → 分块 → 打版本")
    d1 = ingest(DOC_PATH, 1, store)
    assert d1
    print(f"\n  document_id  = {d1.doc_id}")
    print(f"  version      = {d1.version}")
    print(f"  content_hash = {d1.content_hash}")
    print(f"  updated_at   = {d1.updated_at}")
    print("\n  前 3 块的追溯信息：")
    for c in d1.chunks[:3]:
        print(f"    {c.chunk_id:<28} {c.heading[:16]:<18} hash={c.content_hash} tags={c.tags}")

    line("② 内容没变时重新上传：不会重复入库")
    ingest(DOC_PATH, 2, store)
    print(f"  当前 store 里仍是 {len(store)} 份文档（版本还是 v1）")

    line("③ 内容变了：新版本 + 旧版本标记失效")
    new_text = DOC_PATH.read_text(encoding="utf-8").replace("签收后 7 天内", "签收后 30 天内")
    tmp = Path("_ch39_tmp.md")
    tmp.write_text(new_text, encoding="utf-8")
    d2 = ingest(tmp, 2, store)
    assert d2
    print(f"  新版本 v{d2.version}，hash {d2.content_hash}（与 v1 的 {d1.content_hash} 不同）")
    print("  → 旧块必须标记 invalid，否则检索会同时命中「7 天」和「30 天」两个答案")
    print(f"    本例：v1 的块 id 前缀 = {d1.chunks[0].chunk_id}")
    print(f"           v2 的块 id 前缀 = {d2.chunks[0].chunk_id}")
    print("    → **块 id 里带版本号**，是「能精确失效」的前提（第 31 章 LLMWiki 的同一招）")

    line("④ 最经典的线上事故：文档删了，索引还在")
    print("  场景：运营在后台删了《2024 旧政策.pdf》，但只删了文件，没删索引。")
    print("  后果：用户问到「能不能退」，检索命中旧政策，答出已经作废的条款。")
    print("  真实输出（模拟）：")
    all_chunks = [c for d in store.values() for c in d.chunks]
    print(f"    索引里现有 {len(all_chunks)} 块，来自 {len(store)} 份文档")
    print(f"    其中 v1 版本 {sum(1 for c in all_chunks if c.version == 1)} 块，"
          f"v2 版本 {sum(1 for c in all_chunks if c.version == 2)} 块")
    print("    → 如果检索不过滤 version，v1 和 v2 会被同时召回。")
    print("    → 修法：① 删除文档时同步删索引；② 检索时加 version 过滤；③ 定期对账。")

    line("⑤ 对账：三条必须能自动跑的检查")
    print("  检查 1｜孤儿块：索引里有、源文件没有")
    orphans = [c.chunk_id for d in store.values() for c in d.chunks
               if c.source == "_ch39_tmp.md"]
    print(f"    本例孤儿块 {len(orphans)} 个（来自临时文件，源已删）")
    print("  检查 2｜过期块：同一 heading 有多个版本同时有效")
    heads: dict[str, set[int]] = {}
    for d in store.values():
        for c in d.chunks:
            heads.setdefault(c.heading, set()).add(c.version)
    dup = {h: v for h, v in heads.items() if len(v) > 1}
    print(f"    同一标题多版本共存：{len(dup)} 处，例如 {list(dup)[:2]}")
    print("  检查 3｜空块：清洗后为空的块（切分 bug 的典型症状）")
    empties = [c.chunk_id for d in store.values() for c in d.chunks if len(c.text.strip()) < 10]
    print(f"    过短块：{len(empties)} 个")

    tmp.unlink(missing_ok=True)

    line("⑥ 落成「可查询的元数据表」（真实项目存数据库）")
    sample = [c.to_dict() for c in d2.chunks[:2]]
    print(json.dumps(sample, ensure_ascii=False, indent=2)[:600])

    line("⑦ 一条铁律")
    print("""  数据层的三个必答问题：
    1. 这条知识从哪来？   → source + doc_id + updated_at
    2. 现在还有效吗？     → version + valid_until（或 invalidated_at）
    3. 删源头时索引跟着删了吗？ → 删除必须"级联"，并且有对账脚本

  → 任何一条答不出来，知识库就会慢慢变成"没人敢动的黑盒"。""")


if __name__ == "__main__":
    main()

