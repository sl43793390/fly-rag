"""
hybridRetriever.milvus_hybrid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Milvus 2.5 全文检索方案的原生混合检索(稠密 + BM25 稀疏在同一 collection 内融合)。

原理(路径 2:内置 BM25 Function,免训练稀疏模型):
    - Milvus 2.5+ 支持 Full-Text Search:建表时定义 BM25 Function,
      服务端在**写入时**自动把 text 字段转成稀疏向量(BM25 词频权重),
      **查询时**自动对原始 query 字符串分词,全程无需自备稀疏模型;
    - ``MilvusVectorStore``(llama-index-vector-stores-milvus >= 1.0)通过
      ``enable_sparse=True`` + ``sparse_embedding_function=BM25BuiltInFunction(...)``
      启用该能力;
    - 检索时 retriever 必须显式指定 ``vector_store_query_mode="hybrid"``,
      底层用一次 ``hybrid_search`` 完成 稠密 ANN + BM25 稀疏检索 + 库内融合
      (RRFRanker / WeightedRanker),不把候选集拉回应用层。

优势:
    - 零维护稀疏模型:不需要 BGE-M3 / SPLADE,分词器由 Milvus 内置(chinese 支持中文分词);
    - 一次 search 拿混合结果,延迟低于应用层多路召回 + RRF 融合;
    - 融合排序(RRF k / Weighted weights)可通过 config 或知识库级配置定制。

何时用:
    - Milvus 服务端 >= 2.5(嵌入式 milvus-lite 需确认支持 Function);
    - 不想引入/维护稀疏向量模型;
    - 数据量大、希望融合在库内完成。

分数语义(重要):
    - dense        : 相似度,可用绝对阈值(min_score)过滤;
    - hybrid+RRF   : RRF 融合分,量纲约 0~(路由数/k),不适用绝对阈值;
    - hybrid+Weighted: 加权相似度,权重和为 1 时量纲近似 [0, 1];
    - sparse(BM25) : BM25 相关性分,无上界,不适用绝对阈值。
"""
from __future__ import annotations

from typing import Any, List, Optional, Union

from llama_index.core.indices.vector_store import VectorStoreIndex
from llama_index.core.schema import NodeWithScore, QueryBundle

from .vector_retriever import score_normalize

#: 检索方式: 稠密 / 稀疏(BM25 全文) / 混合
MODE_DENSE = "dense"
MODE_SPARSE = "sparse"
MODE_HYBRID = "hybrid"
AVAILABLE_MODES = (MODE_DENSE, MODE_SPARSE, MODE_HYBRID)

#: 融合排序器(与 MilvusVectorStore.hybrid_ranker 对齐)
MILVUS_RRF = "RRFRanker"
MILVUS_WEIGHTED = "WeightedRanker"
AVAILABLE_RANKERS = (MILVUS_RRF, MILVUS_WEIGHTED)


def build_milvus_hybrid_store(
    collection_name: str,
    dim: Optional[int] = None,
    enable_hybrid: bool = True,
    hybrid_ranker: str = MILVUS_RRF,
    hybrid_ranker_params: Optional[dict] = None,
    uri: Optional[str] = None,
    token: Optional[str] = None,
    overwrite: Optional[bool] = None,
):
    """
    构造一个开启 BM25 全文混合检索的 MilvusVectorStore。

    稀疏向量化由 Milvus 2.5 内置 BM25 Function 在服务端完成:
    建表时 schema 自动附带 ``sparse_embedding`` 稀疏字段 + BM25 Function
    (输入 text 字段,中文分词),写入/查询均无需客户端编码。

    Args:
        collection_name: 集合名。
        dim: 稠密向量维度;None 时读 ``config.EMBED.dim``。
        enable_hybrid: True 启用稀疏字段 + BM25 Function;False 仅稠密。
        hybrid_ranker: ``"RRFRanker"``(推荐,对量纲不敏感)或 ``"WeightedRanker"``。
        hybrid_ranker_params: RRF ``{"k": 60}`` / Weighted ``{"weights": [0.7, 0.3]}``;
            None 时读 ``config.MILVUS.hybrid_ranker_params``。
        uri / token / overwrite: 同 ``MilvusVectorStore`` 构造参数;None 时读配置。

    Returns:
        :class:`MilvusVectorStore` 实例。
    """
    from vectorStore.milvus_store import build_milvus_store

    return build_milvus_store(
        uri=uri,
        token=token,
        collection_name=collection_name,
        dim=dim,
        overwrite=overwrite,
        enable_hybrid=enable_hybrid,
        hybrid_ranker=hybrid_ranker,
        hybrid_ranker_params=hybrid_ranker_params,
    )


class MilvusHybridRetriever:
    """
    在 :class:`MilvusVectorStore` 上做原生混合检索的薄包装。

    核心点:retriever 构造时必须传 ``vector_store_query_mode="hybrid"``,
    否则 llama-index 默认走 DEFAULT(纯稠密)检索,稀疏字段完全不参与。

    用法::

        store = build_milvus_hybrid_store(collection_name="rag", dim=1024)
        index = VectorStoreIndex.from_vector_store(vector_store=store)
        retriever = MilvusHybridRetriever(index, similarity_top_k=10, mode="hybrid")
        nodes = retriever.retrieve("什么是 UFX?")

    Args:
        index: 基于 hybrid store 构建的 ``VectorStoreIndex``。
        similarity_top_k: 召回条数。
        mode: ``"hybrid"``(稠密+BM25 融合,默认) / ``"sparse"``(纯 BM25 全文)
            / ``"dense"``(纯稠密)。
        normalize_score: 是否把分数 min-max 归一化到 [0, 1](相对分,
            仅影响展示/阈值,不改变排序)。RRF / BM25 原始分数量纲特殊,
            归一化后便于统一展示;设为 False 保留 Milvus 原始分数。
    """

    def __init__(
        self,
        index: VectorStoreIndex,
        similarity_top_k: int = 10,
        mode: str = MODE_HYBRID,
        normalize_score: bool = True,
    ) -> None:
        if mode not in AVAILABLE_MODES:
            raise ValueError(f"不支持的检索方式: {mode},可选: {', '.join(AVAILABLE_MODES)}")
        self.index = index
        self.similarity_top_k = similarity_top_k
        self.mode = mode
        self.normalize_score = normalize_score
        self._retriever = self._build_retriever(similarity_top_k)

    def _build_retriever(self, top_k: int):
        """构造底层 retriever:按 mode 注入 vector_store_query_mode。"""
        kwargs: dict[str, Any] = dict(similarity_top_k=top_k)
        if self.mode in (MODE_HYBRID, MODE_SPARSE):
            # 关键:hybrid/sparse 模式必须显式声明,否则走默认纯稠密检索
            kwargs["vector_store_query_mode"] = self.mode
        return self.index.as_retriever(**kwargs)

    def retrieve(
        self,
        query: str | QueryBundle,
        top_k: Optional[int] = None,
    ) -> List[NodeWithScore]:
        q = query if isinstance(query, QueryBundle) else QueryBundle(query_str=str(query))
        if top_k is not None and top_k != self.similarity_top_k:
            retriever = self._build_retriever(top_k)
        else:
            retriever = self._retriever
        try:
            result = retriever.retrieve(q)
        except TypeError:
            result = retriever.retrieve(q.query_str)
        if self.normalize_score:
            result = score_normalize(result)
        return result

    def __len__(self) -> int:
        try:
            return len(self.index.docstore.docs)
        except Exception:
            return 0
