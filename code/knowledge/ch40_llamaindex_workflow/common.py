"""第 40 章共用：离线语料、哈希嵌入、脚本化 LLM、索引构建。

不联网。嵌入是字符二元组哈希投影（原理演示）；LLM 是固定回答的脚本，
用来数调用次数、看提示词里放了哪些块，不代表回答质量。
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.vector_stores import SimpleVectorStore
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.llms import CompletionResponse, CustomLLM, LLMMetadata
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, TransformComponent

CHUNK_SIZE = 64
ANSWER = "根据资料，质量问题的退货运费由商家承担。"
REWRITE = "质量问题导致退货时退货运费由谁承担"

DOCS: dict[str, str] = {
    "policy.md": (
        "退货运费规则\n\n"
        "质量问题导致的退货，运费由商家承担。用户签收后十五天内提交照片凭证即可。\n\n"
        "非质量问题的退货，运费由用户承担。定制类商品不支持七天无理由退货。"
    ),
    "invoice.md": (
        "发票说明\n\n"
        "电子发票在订单完成后二十四小时内开具，可在订单详情页下载。\n\n"
        "需要专用发票的用户，请在提交订单时填写抬头与税号，开具后不可更改。"
    ),
    "logistics.md": (
        "物流时效\n\n"
        "现货商品在付款后四十八小时内发出，偏远地区额外增加两到三天。\n\n"
        "预售商品的发货时间以商品页标注为准，超时未发货可以申请补偿。"
    ),
}


class HashEmbedding(BaseEmbedding):
    """字符二元组哈希投影。确定性、无依赖，只让向量索引能跑起来。"""

    dim: int = 32

    def _bucket(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for i in range(len(text) - 1):
            gram = text[i : i + 2]
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:8], 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._bucket(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._bucket(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._bucket(query)


class ScriptedLLM(CustomLLM):
    """固定回答，记录每次收到的提示词。"""

    context_window: int = 8192
    num_output: int = 512
    prompts: list[str] = []

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self.context_window,
            num_output=self.num_output,
            is_chat_model=False,
            model_name="scripted-llm",
        )

    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        self.prompts.append(prompt)
        return CompletionResponse(text=ANSWER)

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        text = self.complete(prompt).text
        yield CompletionResponse(text=text, delta=text)


class EmbedNodes(TransformComponent):
    def __call__(self, nodes: list[BaseNode], **kwargs: Any) -> list[BaseNode]:
        embed_model: BaseEmbedding = Settings.embed_model
        for node in nodes:
            node.embedding = embed_model.get_text_embedding(node.get_content())
        return nodes


def setup() -> ScriptedLLM:
    llm = ScriptedLLM()
    Settings.llm = llm
    Settings.embed_model = HashEmbedding()
    return llm


def build_index() -> VectorStoreIndex:
    docs = [Document(text=t, doc_id=n, metadata={"file": n}) for n, t in DOCS.items()]
    nodes = IngestionPipeline(
        transformations=[SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=0), EmbedNodes()],
    ).run(documents=docs)
    ctx = StorageContext.from_defaults(vector_store=SimpleVectorStore())
    return VectorStoreIndex(nodes, storage_context=ctx)


def hit_line(hits: list) -> str:
    return ", ".join(f"{h.node.ref_doc_id}:{h.score:.3f}" for h in hits)


if __name__ == "__main__":
    setup()
    index = build_index()
    for q in ("退货邮费谁付", "如何申请专利"):
        hits = index.as_retriever(similarity_top_k=3).retrieve(q)
        print(q, "→", hit_line(hits))

