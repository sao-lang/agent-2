"""第 39 章共用：离线语料、确定性嵌入、脚本化 LLM。

全部不联网。嵌入是字符二元组的哈希投影（原理演示，不是真实模型）；
LLM 是固定回答的脚本，用来观察 QueryEngine 把哪些节点放进了提示词，
而不是用来比较回答质量。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from llama_index.core import Document, Settings
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.ingestion import IngestionPipeline, DocstoreStrategy
from llama_index.core.llms import CompletionResponse, CustomLLM, LLMMetadata
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, TransformComponent
from llama_index.core.storage.docstore import SimpleDocumentStore

CHUNK_SIZE = 64

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
    """字符二元组哈希投影。确定性、无依赖，只用来让向量索引跑起来。

    它不是嵌入模型：既不理解同义，也没有语义相似度。本章检查的是摄取与
    索引的接口行为；换成真实模型只需替换 Settings.embed_model。
    """

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
    """固定回答的 LLM。把收到的提示词原文留在 `prompts` 里供检查。"""

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
        return CompletionResponse(text="根据资料，质量问题的退货运费由商家承担。")

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        text = self.complete(prompt).text
        yield CompletionResponse(text=text, delta=text)


class EmbedNodes(TransformComponent):
    """给节点算向量。它是变换链上的一环，不是索引的事。

    IngestionPipeline 只把“已经有 embedding 的节点”写进向量库，
    所以想让向量库在摄取阶段就填满，就需要这一步。
    """

    def __call__(self, nodes: list[BaseNode], **kwargs: Any) -> list[BaseNode]:
        embed_model: BaseEmbedding = Settings.embed_model
        for node in nodes:
            node.embedding = embed_model.get_text_embedding(node.get_content())
        return nodes


def make_docs() -> list[Document]:
    """三份文档，doc_id 用文件名：同一个文件第二次进来仍是同一个 id。"""
    return [
        Document(text=text, doc_id=name, metadata={"file": name})
        for name, text in DOCS.items()
    ]


def build_pipeline(
    chunk_size: int = CHUNK_SIZE,
    docstore: SimpleDocumentStore | None = None,
    vector_store: Any = None,
) -> IngestionPipeline:
    return IngestionPipeline(
        transformations=[
            SentenceSplitter(chunk_size=chunk_size, chunk_overlap=0),
            EmbedNodes(),
        ],
        docstore=docstore if docstore is not None else SimpleDocumentStore(),
        vector_store=vector_store,
        docstore_strategy=(
            DocstoreStrategy.UPSERTS
            if vector_store is not None
            else DocstoreStrategy.DUPLICATES_ONLY
        ),
    )


def setup() -> ScriptedLLM:
    """把全局 Settings 指到离线实现，返回脚本化 LLM 以便检查提示词。"""
    llm = ScriptedLLM()
    Settings.llm = llm
    Settings.embed_model = HashEmbedding()
    return llm
