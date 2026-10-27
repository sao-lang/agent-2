"""概念覆盖率清查：RAG 基础概念在正文里出现过没有、在哪一章出现。

按"概念清单"逐条扫描所有章节正文，输出：命中章号 / 出现次数 / 判定。
"""

from __future__ import annotations

import re
from pathlib import Path

# 概念 -> 判定用的关键词（任一命中即算出现）
CONCEPTS: dict[str, list[str]] = {
    # A. 向量化
    "A1 嵌入的定义": ["映射到向量", "向量空间", "embedding", "嵌入"],
    "A2 嵌入模型与维度": ["bge", "sentence-transformers", "维度", "dim"],
    "A3 归一化与距离度量": ["归一化", "余弦", "cosine", "点积", "L2", "欧氏"],
    "A4 相似度的数值含义": ["相似度", "阈值", "0.8"],
    "A5 查询侧与文档侧": ["query instruction", "查询侧", "文档侧", "非对称"],
    "A6 截断与最大长度": ["max_seq", "截断长度", "最大长度", "512"],
    "A7 稀疏与稠密": ["稀疏", "稠密", "sparse", "dense", "BM25"],
    "A8 批量与缓存": ["批量", "batch", "缓存命中"],
    # B. 向量数据库
    "B1 向量库的职责": ["向量库", "vector store", "向量数据库"],
    "B2 索引类型 HNSW": ["HNSW", "hnsw"],
    "B3 索引类型 IVF/PQ": ["IVF", "PQ", "乘积量化", "nprobe", "nlist"],
    "B4 距离度量与索引匹配": ["IndexFlat", "距离度量", "metric"],
    "B5 元数据过滤": ["payload", "metadata", "过滤条件", "filter"],
    "B6 预过滤与后过滤": ["预过滤", "后过滤", "pre-filter", "post-filter"],
    "B7 多租户隔离": ["租户", "tenant", "命名空间", "namespace"],
    "B8 upsert 与删除语义": ["upsert", "软删除", "重建索引"],
    "B9 持久化与备份": ["持久化", "快照", "备份"],
    "B10 扩容与分片": ["分片", "shard", "副本", "replica"],
    "B11 量化与内存": ["量化", "int8", "binary", "内存占用"],
    "B12 检索参数调优": ["top_k", "top-k", "ef", "召回率与延迟"],
    "B13 选型": ["Qdrant", "Milvus", "pgvector", "Chroma", "FAISS", "faiss"],
    # C. 检索链路
    "C1 混合检索与 RRF": ["RRF", "混合检索", "倒数排名"],
    "C2 重排": ["重排", "rerank", "CrossEncoder"],
    "C3 查询改写": ["改写", "HyDE", "多查询"],
    "C4 MMR 多样性": ["MMR", "多样性", "去重"],
    "C5 MRR/nDCG": ["MRR", "nDCG", "首位命中"],
    # D. 切块
    "D1 token 切块": ["token 切", "TokenTextSplitter", "按 token 切"],
    "D2 语义切块": ["语义切块", "semantic chunk", "按语义边界"],
    "D3 表格与代码块": ["表格", "代码块", "结构化切块"],
}


def chapters() -> list[Path]:
    return sorted(p for p in Path(".").glob("*.md") if re.match(r"^\d\d-", p.name))


def main() -> None:
    files = chapters()
    print(f"扫描 {len(files)} 章正文\n")
    print(f"{'概念':<24}{'命中章':<22}{'次数':>4}  判定")
    print("-" * 74)
    for name, keys in CONCEPTS.items():
        hits: list[str] = []
        total = 0
        for f in files:
            t = f.read_text(encoding="utf-8")
            c = sum(t.count(k) for k in keys)
            if c:
                hits.append(f.name[:2])
                total += c
        verdict = "覆盖" if total >= 3 else ("提及" if total else "缺失")
        print(f"{name:<24}{','.join(hits) or '-':<22}{total:>4}  {verdict}")


if __name__ == "__main__":
    main()
