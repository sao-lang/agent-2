"""知识治理：版本共存、增量更新、过滤失效、缓存键与矛盾检测。

用真实组件：InMemoryVectorStore + Document.metadata + payload 过滤 + bge 嵌入。
首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings

MODEL = "BAAI/bge-small-zh-v1.5"

# (doc_id, version, active, 内容, 更新时间)
V1 = [
    ("p1", 1, True, "无理由退货时限为签收后 7 天，需保持未拆封。", "2026-01-10"),
    ("p2", 1, True, "发票开票时限为下单后 30 天。", "2026-01-10"),
    ("p3", 1, True, "生鲜类商品不支持无理由退货。", "2026-01-10"),
]

# 2026-10 改版：p1 的时限从 7 天改成 15 天，其余不变
V2 = [
    ("p1", 2, True, "无理由退货时限为签收后 15 天，需保持未拆封。", "2026-10-01"),
]


def docs_of(rows, index_version: str) -> list[Document]:
    out = []
    for doc_id, ver, active, text, updated in rows:
        out.append(Document(
            page_content=text,
            metadata={
                "doc_id": doc_id,
                "version": ver,
                "active": active,
                "source": f"policy/{doc_id}.md",
                "updated_at": updated,
                "index_version": index_version,
            },
        ))
    return out


def main() -> None:
    emb = HuggingFaceEmbeddings(model_name=MODEL,
                                encode_kwargs={"normalize_embeddings": True})
    store = InMemoryVectorStore(embedding=emb)

    store.add_documents(docs_of(V1, "idx-1"), ids=[f"{d}#v1" for d, *_ in V1])
    print(f"=== 1. 初始库（idx-1）{len(store.store)} 块 ===")
    for d in store.similarity_search("退货要几天内", k=3):
        m = d.metadata
        print(f"  {m['doc_id']} v{m['version']} active={m['active']}  {d.page_content[:26]}")

    print()
    print("=== 2. 改版：同 doc_id 写新版本，旧版标记失效 ===")
    store.add_documents([Document(
        page_content="无理由退货时限为签收后 7 天，需保持未拆封。",
        metadata={"doc_id": "p1", "version": 1, "active": False,
                  "source": "policy/p1.md", "updated_at": "2026-01-10",
                  "index_version": "idx-1"},
    )], ids=["p1#v1"])
    store.add_documents(docs_of(V2, "idx-1"), ids=["p1#v2"])
    for d in store.similarity_search("退货要几天内", k=5):
        m = d.metadata
        print(f"  {m['doc_id']} v{m['version']} active={m['active']}  {d.page_content[:26]}")

    print()
    print("=== 3. 查询不带 active 过滤：两个版本一起返回 ===")
    hits = store.similarity_search("退货要几天内", k=5)
    p1_versions = sorted(d.metadata["version"] for d in hits
                         if d.metadata["doc_id"] == "p1")
    print(f"  返回 {len(hits)} 条，p1 的版本 {p1_versions}（旧版仍可能被召回）")

    print()
    print("=== 4. 查询带 active 过滤：只剩现行版本 ===")
    live = store.similarity_search(
        "退货要几天内", k=5,
        filter=lambda d: d.metadata.get("active") is True,
    )
    for d in live:
        m = d.metadata
        print(f"  {m['doc_id']} v{m['version']}  {d.page_content[:26]}")

    print()
    print("=== 5. 按 doc_id 删旧插新（全量替换）===")
    before = len(store.store)
    store.delete(ids=["p1#v1"])
    after = len(store.store)
    print(f"  删掉 p1#v1：{before} -> {after}")

    print()
    print("=== 6. 缓存键不含索引版本，会返回旧答案 ===")
    cache: dict[str, list[str]] = {}
    fresh = InMemoryVectorStore(embedding=emb)
    fresh.add_documents(docs_of(V1, "idx-1"), ids=[f"{d}#v1" for d, *_ in V1])

    def ask(q: str, index_version: str, use_version_in_key: bool,
            vs: InMemoryVectorStore) -> list[str]:
        key = f"{q}|{index_version}" if use_version_in_key else q
        if key in cache:
            return cache[key]
        got = [d.page_content for d in vs.similarity_search(q, k=1)]
        cache[key] = got
        return got

    q = "退货要几天内"
    print(f"  改版前问（键不带版本）：{ask(q, 'idx-1', False, fresh)}")
    fresh.add_documents([Document(
        page_content="无理由退货时限为签收后 15 天，需保持未拆封。",
        metadata={"doc_id": "p1", "version": 2, "active": True,
                  "source": "policy/p1.md", "updated_at": "2026-10-01",
                  "index_version": "idx-2"},
    )], ids=["p1#v2b"])
    print(f"  改版后再问（键不带版本）：{ask(q, 'idx-2', False, fresh)}  <- 命中旧缓存")
    cache.clear()
    print(f"  清缓存后（键带版本）：{ask(q, 'idx-2', True, fresh)}")

    print()
    print("=== 7. 矛盾检测：两个 active 版本对同一 doc_id 给出不同结论 ===")
    con = InMemoryVectorStore(embedding=emb)
    con.add_documents([
        Document(page_content="无理由退货时限为 7 天。",
                 metadata={"doc_id": "p9", "version": 1, "active": True,
                           "updated_at": "2026-01-10"}),
        Document(page_content="无理由退货时限为 15 天。",
                 metadata={"doc_id": "p9", "version": 2, "active": True,
                           "updated_at": "2026-10-01"}),
    ], ids=["p9#v1", "p9#v2"])
    rows = con.similarity_search("无理由退货时限", k=5)
    active = [d for d in rows if d.metadata["active"]]
    seen: dict[str, set[int]] = {}
    for d in active:
        seen.setdefault(d.metadata["doc_id"], set()).add(d.metadata["version"])
    conflicts = {k: v for k, v in seen.items() if len(v) > 1}
    print(f"  同一 doc_id 有多个 active 版本：{conflicts}")
    for d in active:
        print(f"    v{d.metadata['version']} {d.page_content}")

    print()
    print("=== 8. 可溯源：每条结果带来源与版本 ===")
    for d in store.similarity_search("发票什么时候能开", k=1):
        m = d.metadata
        fp = hashlib.sha1(d.page_content.encode()).hexdigest()[:8]
        print(f"  {m['source']} v{m['version']} updated={m['updated_at']} "
              f"index={m['index_version']} 指纹={fp}")


if __name__ == "__main__":
    main()


