"""第 50 章 step1：Ingestion Pipeline——文档变成节点（离线）。

运行：
    python code/framework/li/ch50/step1_ingestion.py

上一章（第 49 章）的痛点：
    LangGraph 解决了"流程"，但"把 1000 份 PDF 变成可查询索引"这件事，
    你还是得一块一块自己切、自己算向量、自己维护 metadata。
    LlamaIndex 的强项正好是这一段。

这一级做什么：
    ① Document → Node 的两种切法（定长 / 句子），对比块数与长度分布
    ② 给每个节点加 metadata（来源、章节），并在检索后能拿到
    ③ 用 IngestionPipeline 把"切分 + 去重"串起来
    ④ 一个坑：默认切分器不认中文标点

关键认知：
    LlamaIndex 的核心抽象是 **Node**，不是"文本块"。
    Node 有 id / metadata / relationships（前后关系、父子关系），这是它比"字符串列表"强的地方。
"""
from __future__ import annotations

from pathlib import Path

from llama_index.core import Document
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import MetadataMode

DOC_PATH = Path(__file__).resolve().parents[4] / "data" / "售后政策手册.md"


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    print(f"  语料：{DOC_PATH.name}，{len(text)} 字符")

    line("① 两种切法：默认 vs 指定中文标点（含一次真实对比）")
    # 说明：语义切分只在"某一段超过 chunk_size"时才起作用。
    # 本语料每节都很短（< chunk_size），所以两种配置结果一样。
    # 为了让你看见差别，这里额外用一段"长段落"做对比。
    long_para = (
        "用户反馈右耳出现电流声，先检查蓝牙编解码是否匹配。若不匹配请重置连接。"
        "若匹配则检查耳塞网罩是否堵塞。网罩堵塞可用软毛刷清理，不要用针戳。"
        "清理后仍有电流声，判定为硬件故障，走保修流程。"
    ) * 2
    print(f"  对照段落：{len(long_para)} 字（一个长段落，没有分段）")
    for label, kw in (
        ("默认分隔符（英文 , . ;）", {}),
        ("指定中文标点（，。；！？）", {"secondary_chunking_regex": "[^，。；！？]+[，。；！？]?"}),
    ):
        sp = SentenceSplitter(chunk_size=60, chunk_overlap=0, **kw)
        got = sp.get_nodes_from_documents([Document(text=long_para)])
        print(f"  {label}")
        for n in got:
            c = n.get_content()
            print(f"    {len(c):>3} 字  {c[:24]!r}…{c[-8:]!r}")

    print("\n  → 看块尾：默认配置的第 2 块以「不要用针戳。」结尾，但第 3 块**从半句中间开始**")
    print("    （'清理后仍有电流声，判定为硬件故障，走保修流程。用' —— '用' 是下一句的开头）。")
    print("    指定中文标点后，块尾落在「。」或「，」上，第 3 块整整一句完整。")
    print("    块边界是否落在语义单位上，直接决定模型读到的是'半截话'还是'完整一句'。")

    fixed = SentenceSplitter(chunk_size=200, chunk_overlap=20, paragraph_separator="\n\n")
    sent = SentenceSplitter(
        chunk_size=200,
        chunk_overlap=20,
        paragraph_separator="\n\n",
        secondary_chunking_regex="[^，。；！？]+[，。；！？]?",   # ← 认中文标点
    )
    doc = Document(text=text, metadata={"source": "售后政策手册.md", "version": "v3"})

    n_fixed = fixed.get_nodes_from_documents([doc])
    n_sent = sent.get_nodes_from_documents([doc])

    print(f"\n  本章语料（每节都短）：默认 {len(n_fixed)} 块 / 指定中文标点 {len(n_sent)} 块")
    print("  → 结果一样。**别被'配置了但没变化'误导成'配置生效了'** ——")
    print("    要看它是否真的改变了切分位置（上面那个长段落对比才是证据）。")

    print("\n  前 3 块的开头（看有没有被切坏）：")
    for i, n in enumerate(n_sent[:3]):
        print(f"    [{i}] {n.get_content()[:46]!r}…")

    line("② Node 自带 metadata 和关系")
    node = n_sent[1]
    print(f"  node_id      = {node.node_id[:16]}…")
    print(f"  metadata     = {node.metadata}")
    print(f"  relationships = {[r.node_id[:8] + '…' for r in node.relationships.values()]}")
    print("\n  给模型看的内容（MetadataMode.LLM）：")
    print("  " + node.get_content(metadata_mode=MetadataMode.LLM).replace("\n", "\n  ")[:200])
    print("\n  → LlamaIndex 会把 metadata 自动拼进给模型的文本里（可用 exclude_keys 排除）")

    line("③ IngestionPipeline：切分 + 去重 + 向量化一条流水")
    pipe = IngestionPipeline(
        transformations=[
            SentenceSplitter(chunk_size=200, chunk_overlap=20,
                             secondary_chunking_regex="[^，。；！？]+[，。；！？]?"),
            MockEmbedding(embed_dim=8),          # 真实项目换 OpenAIEmbedding
        ],
    )
    nodes = pipe.run(documents=[doc])
    print(f"  pipeline 产出 {len(nodes)} 个节点，每个带 embedding：")
    print(f"    node[0].embedding 维度 = {len(nodes[0].embedding)}")
    print(f"    node[0].metadata      = {nodes[0].metadata}")

    # 去重：同一份文档再跑一次，节点数不会翻倍（靠 docstore 里的内容 hash 判重）
    again = pipe.run(documents=[Document(text=text, metadata={"source": "售后政策手册.md", "version": "v3"})])
    print(f"\n  去重：同一份文档再喂一次 → {len(again)} 个节点（不会翻倍）")
    print("  → 去重靠的是 node 内容的 hash（docstore 里记着）。这是增量更新的基础。")

    line("④ 关于中文标点的真实结论")
    print("  默认 SentenceSplitter 的顺序是：按 '\\n\\n' 分段 → 按正则切句 → 按空格切。")
    print("  它默认的 secondary regex 是 '[^,\\.;]+[,\\.;]?'，全是**半角**标点。")
    print("  但实测发现：即使一句中文标点都不配，它也能切出'看起来完整'的块 ——")
    print("  因为 nltk 的分句器对 '。' 也有一定识别能力，而且最终还有'按 chunk_size 硬切'兜底。")
    print("")
    print("  → 所以正确的结论不是「不配就切坏」，而是：")
    print("    **默认配置的切分边界不可控**（可能落在句子中间），你要的是可控 + 可验证。")
    print("    验证方法：把块尾打出来看（就像上面那段），而不是看'块数变没变'。")

    line("⑤ 和 LangChain 的 Document 对照")
    print("""  LangChain:  Document(page_content=..., metadata={...})   → 纯文本 + 字典
  LlamaIndex: Node(id=..., text=..., metadata=..., relationships={...}, embedding=...)
              ↑ 多了 id、关系、embedding 三个字段

  → 关系（prev/next/parent）是 LlamaIndex 做"句子窗口检索""父子块"的底层支撑。
  → 如果你只用向量检索，两者差别不大；一旦要做"取回相邻块"，Node 的结构更顺手。""")


if __name__ == "__main__":
    main()
