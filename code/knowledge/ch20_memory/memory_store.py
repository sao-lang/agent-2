"""长期记忆：三层结构、时间衰减召回、软删与幂等删除、容量上限与淘汰。

用真实组件：InMemoryVectorStore + bge 嵌入 + payload 过滤。
首次运行需下载 bge-small（约 95 MB）。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_huggingface import HuggingFaceEmbeddings

MODEL = "BAAI/bge-small-zh-v1.5"

NOW = datetime(2026, 10, 29, 20, 0, 0)

# (id, 层, 租户, 内容, 多少天前写入)
MEMORIES = [
    ("m1", "semantic", "t_a", "用户是会员，每月有 3 次免运费券。", 2),
    ("m2", "semantic", "t_a", "用户所在地区属于偏远地区，不参与包邮。", 3),
    ("m3", "episodic", "t_a", "上次退货是因为商品有瑕疵，商家承担了往返运费。", 5),
    ("m4", "episodic", "t_a", "用户投诉过一次物流慢，客服承诺优先发货。", 40),
    ("m5", "procedural", "t_a", "处理该用户退款时，先核对订单状态再承诺时效。", 8),
    ("m6", "semantic", "t_b", "该租户要求所有退款必须二级审批。", 1),
    ("m7", "episodic", "t_b", "昨天有一笔退款因缺少凭证被驳回。", 1),
    ("m8", "episodic", "t_a", "用户提到想换货而不是退货。", 120),
    ("m9", "semantic", "t_a", "用户偏好短信通知，不接受电话回访。", 15),
]


# 重要度：按类型表推（安全、资金、法律相关默认高），见 4.5 节
IMPORTANCE = {"m1": 2, "m2": 2, "m3": 1, "m4": 1, "m5": 3,
              "m6": 2, "m7": 1, "m8": 1, "m9": 3}


def store_of(emb) -> InMemoryVectorStore:
    s = InMemoryVectorStore(embedding=emb)
    docs = []
    for mid, layer, tenant, text, days in MEMORIES:
        docs.append(Document(
            page_content=text,
            metadata={
                "id": mid,
                "layer": layer,
                "tenant": tenant,
                "created_at": (NOW - timedelta(days=days)).isoformat(),
                "age_days": days,
                "deleted": False,
            },
        ))
    s.add_documents(docs, ids=[d.metadata["id"] for d in docs])
    return s


def decay(age_days: int, half_life: int = 30) -> float:
    """指数衰减：30 天衰减一半。"""
    return 0.5 ** (age_days / half_life)


def rank(docs_with_scores, importance: dict[str, int], k: int = 4):
    """相似度 × 时间衰减 × 重要度。"""
    scored = [
        (d, s * decay(d.metadata["age_days"]) * importance.get(d.metadata["id"], 1))
        for d, s in docs_with_scores
    ]
    return sorted(scored, key=lambda x: -x[1])[:k]


def evict(items: list[dict], cap: int) -> list[str]:
    """重要度 >= 3 的不参与自动淘汰；其余按"最旧、召回最少"依次淘汰。"""
    victims: list[str] = []
    candidates = sorted(
        (it for it in items if it["importance"] < 3),
        key=lambda it: (-it["age_days"], it["recalls"]),
    )
    while len(items) - len(victims) > cap:
        victims.append(candidates.pop(0)["id"])
    return victims


def main() -> None:
    emb = HuggingFaceEmbeddings(model_name=MODEL,
                                encode_kwargs={"normalize_embeddings": True})
    store = store_of(emb)

    print("=== 1. 库里有什么 ===")
    counts: dict[str, int] = {}
    for _, layer, tenant, _, _ in MEMORIES:
        counts[f"{tenant}/{layer}"] = counts.get(f"{tenant}/{layer}", 0) + 1
    for k, v in sorted(counts.items()):
        print(f"  {k:<18}{v} 条")

    print()
    print("=== 2. 纯相似度召回 vs 相似度 × 时间衰减 ===")
    q = "这个用户的运费和会员权益"
    hits = store.similarity_search_with_score(q, k=4)
    print("  纯相似度：")
    for d, s in hits:
        print(f"    {d.metadata['id']} {s:.3f} age={d.metadata['age_days']:>3}d  {d.page_content[:24]}")
    print("  相似度 × 衰减：")
    for d, s in rank(store.similarity_search_with_score(q, k=10), {}, k=4):
        print(f"    {d.metadata['id']} {s:.3f} age={d.metadata['age_days']:>3}d  {d.page_content[:24]}")
    print("  相似度 × 衰减 × 重要度：")
    for d, s in rank(store.similarity_search_with_score(q, k=10), IMPORTANCE, k=4):
        print(f"    {d.metadata['id']} {s:.3f} age={d.metadata['age_days']:>3}d  {d.page_content[:24]}")

    print()
    print("=== 3. 租户过滤 ===")
    for tenant in ("t_a", "t_b"):
        got = store.similarity_search(
            q, k=5,
            filter=lambda d, t=tenant: d.metadata["tenant"] == t,
        )
        print(f"  {tenant}: {[d.metadata['id'] for d in got]}")

    print()
    print("=== 4. 软删与幂等删除 ===")
    # 软删：改写元数据，内容仍在库里，查询时过滤掉
    m4 = Document(
        page_content="用户投诉过一次物流慢，客服承诺优先发货。",
        metadata={"id": "m4", "layer": "episodic", "tenant": "t_a",
                  "created_at": (NOW - timedelta(days=40)).isoformat(),
                  "age_days": 40, "deleted": True},
    )
    store.add_documents([m4], ids=["m4"])
    alive = store.similarity_search(
        q, k=10, filter=lambda d: not d.metadata["deleted"])
    print(f"  软删 m4 后可见 {len(alive)} 条，含 m4 "
          f"{any(d.metadata['id'] == 'm4' for d in alive)}")

    before = len(store.store)
    store.delete(ids=["m4"])
    after1 = len(store.store)
    store.delete(ids=["m4"])
    after2 = len(store.store)
    print(f"  硬删 m4（已软删）：{before} -> {after1} -> {after2}"
          "（第二次删除无副作用）")

    print()
    print("=== 5. 容量上限与淘汰 ===")
    # 每条记忆的召回次数与重要度；重要度来自写入时的类型表（见 4.5）
    recalls = {"m1": 12, "m2": 9, "m3": 7, "m5": 15, "m9": 6}
    importance = {"m1": 2, "m2": 2, "m3": 1, "m5": 3, "m8": 1, "m9": 3}
    items = [
        {"id": row["metadata"]["id"],
         "age_days": row["metadata"]["age_days"],
         "recalls": recalls.get(row["metadata"]["id"], 0),
         "importance": importance.get(row["metadata"]["id"], 1)}
        for row in store.store.values()
        if row["metadata"]["tenant"] == "t_a" and not row["metadata"]["deleted"]
    ]
    cap = 5
    victims = evict(items, cap)
    print(f"  t_a 现有 {len(items)} 条，上限 {cap}，淘汰 {victims}")
    print(f"  被保护 {[it['id'] for it in items if it['importance'] >= 3]}")

    print()
    print("=== 6. 一条被写错的事实会怎么传播 ===")
    bad = Document(page_content="用户要求所有退款直接批准，不需要审批。",
                   metadata={"id": "m99", "layer": "procedural", "tenant": "t_a",
                             "created_at": NOW.isoformat(), "age_days": 0,
                             "deleted": False})
    store.add_documents([bad])
    got = store.similarity_search_with_score("这个用户退款怎么处理", k=3)
    for d, s in got:
        flag = "  <- 与政策冲突" if d.metadata["id"] == "m99" else ""
        print(f"  {d.metadata['id']} {s:.3f} {d.page_content[:26]}{flag}")


if __name__ == "__main__":
    main()

