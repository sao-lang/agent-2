"""第 39 章 · 摄取：doc_id、docstore、重复与失效。

运行：
    $env:PYTHONPATH="$PWD\\.libs"; $env:PYTHONIOENCODING='utf-8'
    python code/knowledge/ch39_llamaindex/ingest_pipeline.py

不联网。三份文档在 common.DOCS 里，切块用 SentenceSplitter，
docstore 用 SimpleDocumentStore，向量库用 SimpleVectorStore：
脱重与 upsert 要两者同时给，只给 docstore 时库会降级成 duplicates_only。
"""

from __future__ import annotations

import sys
import shutil
from pathlib import Path

from llama_index.core import Document
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.vector_stores import SimpleVectorStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHUNK_SIZE, DOCS, build_pipeline, make_docs, setup  # noqa: E402


def manual_chunks() -> list[dict]:
    """手写版：按空行切，存成一个 list。没有 doc_id，也没有已摄取记录。"""
    out: list[dict] = []
    for name, text in DOCS.items():
        for para in text.split("\n\n"):
            if para.strip():
                out.append({"file": name, "text": para.strip()})
    return out


def vectors(store: SimpleVectorStore) -> int:
    return len(store.data.embedding_dict)


def section_1_manual() -> None:
    print("=== 1. 手写切块：重跑一遍会怎样 ===")
    first = manual_chunks()
    second = manual_chunks()
    print(f"  第一次切出 {len(first)} 块，第二次切出 {len(second)} 块")
    print(f"  合并后 {len(first) + len(second)} 块，没有去重依据")
    print(f"  每块带的字段：{sorted(first[0])}")
    print("  没有字段能回答：这一块来自哪个文件的哪个版本")


def section_2_identity() -> None:
    print("=== 2. doc_id 决定“同一份文件” ===")
    vs = SimpleVectorStore()
    pipeline = build_pipeline(chunk_size=CHUNK_SIZE, vector_store=vs)
    docs = make_docs()
    nodes = pipeline.run(documents=docs)
    print(f"  第一次摄取：{len(nodes)} 个节点，docstore {len(pipeline.docstore.docs)} 份，向量库 {vectors(vs)} 条")
    print(f"  节点 id 是随机 UUID（第一个 {nodes[0].node_id[:8]}…），每次运行都不同")
    for n in nodes[:3]:
        print(f"    hash={n.hash[:8]}  ref={n.ref_doc_id}  {n.text[:16]!r}")

    again = pipeline.run(documents=docs)
    print(f"  原样重跑：新增 {len(again)} 个节点，向量库仍 {vectors(vs)} 条")

    fresh = [Document(text=t, metadata={"file": n, "batch": "2"}) for n, t in DOCS.items()]
    dup = pipeline.run(documents=fresh)
    print(f"  不带 doc_id 重跑：新增 {len(dup)} 个节点，docstore {len(pipeline.docstore.docs)} 份，向量库 {vectors(vs)} 条")
    print("  doc_id 缺省是随机 UUID，元数据里多了 batch：同一份文件被当成新文档")


def section_3_upsert() -> None:
    print("=== 3. 内容改了：UPSERTS 删旧块再写新块 ===")
    vs = SimpleVectorStore()
    docstore = SimpleDocumentStore()
    pipeline = build_pipeline(chunk_size=CHUNK_SIZE, docstore=docstore, vector_store=vs)
    nodes = pipeline.run(documents=make_docs())
    print(f"  首跑：{len(nodes)} 个节点，向量库 {vectors(vs)} 条")

    changed = DOCS["policy.md"] + "\n\n补充：生鲜类商品不支持无理由退货。"
    new_nodes = pipeline.run(
        documents=[Document(text=changed, doc_id="policy.md", metadata={"file": "policy.md"})]
    )
    print(f"  改政策后重跑：新增 {len(new_nodes)} 个节点，向量库 {vectors(vs)} 条")
    print(f"  新块里出现补充条款：{any('生鲜' in n.text for n in new_nodes)}")
    print(f"  向量库总数没涨：{vectors(vs)} == {len(nodes)}，旧块被按 ref_doc_id 删掉了")


def section_4_persist() -> None:
    print("=== 4. 两份状态要一起备份 ===")
    vs = SimpleVectorStore()
    docstore = SimpleDocumentStore()
    pipeline = build_pipeline(chunk_size=CHUNK_SIZE, docstore=docstore, vector_store=vs)
    pipeline.run(documents=make_docs())
    tmp = Path(__file__).resolve().parent / "_store"
    tmp.mkdir(exist_ok=True)
    docstore.persist(str(tmp / "docstore.json"))
    vs.persist(str(tmp / "vectors.json"))
    print(f"  docstore.json {tmp.joinpath('docstore.json').stat().st_size} 字节，vectors.json {tmp.joinpath('vectors.json').stat().st_size} 字节")

    ds2 = SimpleDocumentStore.from_persist_path(str(tmp / "docstore.json"))
    vs2 = SimpleVectorStore.from_persist_path(str(tmp / "vectors.json"))
    repl = build_pipeline(chunk_size=CHUNK_SIZE, docstore=ds2, vector_store=vs2).run(documents=make_docs())
    print(f"  两份都读回：重跑新增 {len(repl)} 个节点，向量库 {vectors(vs2)} 条")

    vs_lost = SimpleVectorStore()
    only_doc = build_pipeline(chunk_size=CHUNK_SIZE, docstore=ds2, vector_store=vs_lost).run(documents=make_docs())
    print(f"  只读回 docstore、向量库丢了：重跑新增 {len(only_doc)} 个节点，向量库 {vectors(vs_lost)} 条")
    print("  结论：docstore 说“已摄取”，向量库却是空的，索引永远补不回来")
    shutil.rmtree(tmp)


def section_5_stale_chunk() -> None:
    print("=== 5. 改了 chunk_size，旧块原地不动 ===")
    vs = SimpleVectorStore()
    pipeline = build_pipeline(chunk_size=CHUNK_SIZE, docstore=SimpleDocumentStore(), vector_store=vs)
    first = pipeline.run(documents=make_docs())
    lens = [len(n.text) for n in first]
    print(f"  {CHUNK_SIZE} token 切块：{len(first)} 个节点，块长 {lens}")

    pipeline.transformations = build_pipeline(chunk_size=96).transformations
    smaller = pipeline.run(documents=make_docs())
    print(f"  同一 docstore 换成 96 token 重跑：新增 {len(smaller)} 个节点，向量库仍 {vectors(vs)} 条")
    print(f"  库里的块长仍然是：{lens}")
    print("  原因：文档 hash 没变 → 判定已摄取 → 变换链根本没跑")


def section_6_fix() -> None:
    print("=== 6. 两种修法：删掉旧文档，或把版本写进 doc_id ===")
    vs = SimpleVectorStore()
    docstore = SimpleDocumentStore()
    pipeline = build_pipeline(chunk_size=CHUNK_SIZE, docstore=docstore, vector_store=vs)
    pipeline.run(documents=make_docs())

    for name in list(docstore.docs):
        docstore.delete_ref_doc(name, raise_error=False)
        vs.delete(name)
    print(f"  先试 delete_ref_doc：docstore 剩 {len(docstore.docs)} 份，向量库剩 {vectors(vs)} 条")

    for name in list(docstore.docs):
        docstore.delete_document(name)
        vs.delete(name)
    print(f"  改用 delete_document：docstore 剩 {len(docstore.docs)} 份，向量库剩 {vectors(vs)} 条")
    pipeline.transformations = build_pipeline(chunk_size=96).transformations
    rebuilt = pipeline.run(documents=make_docs())
    print(f"  修法一 删 docstore 记录 + 删向量：重跑 {len(rebuilt)} 个节点，块长 {[len(n.text) for n in rebuilt[:3]]}")

    vs2 = SimpleVectorStore()
    ds2 = SimpleDocumentStore()
    v1 = [Document(text=t, doc_id=f"{n}@c64", metadata={"file": n}) for n, t in DOCS.items()]
    build_pipeline(chunk_size=CHUNK_SIZE, docstore=ds2, vector_store=vs2).run(documents=v1)
    v2 = [Document(text=t, doc_id=f"{n}@c96", metadata={"file": n}) for n, t in DOCS.items()]
    added = build_pipeline(chunk_size=96, docstore=ds2, vector_store=vs2).run(documents=v2)
    print(f"  修法二 doc_id 带版本：新增 {len(added)} 个节点，向量库 {vectors(vs2)} 条（旧版 5 条还在）")
    print("  代价：旧版本节点留在库里，检索会同时命中两个版本，要另外按 metadata 清理")


def main() -> None:
    setup()
    section_1_manual()
    section_2_identity()
    section_3_upsert()
    section_4_persist()
    section_5_stale_chunk()
    section_6_fix()


if __name__ == "__main__":
    main()

