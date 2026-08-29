"""
advancedSplitter
~~~~~~~~~~~~~~~~
RAG 高级切分方法集合。

    - parent_child        : 父子切分 + 父块回查检索(HierarchicalNodeParser
                            + Milvus 叶子检索 + 小 -> 大父块回查)
    - semantic            : 语义切分(SemanticSplitterNodeParser)
    - llm_chunking        : LLM-based 切分(自实现 LLMSemanticChunker)
    - propositions        : 命题提取(Agentic Chunking 的原料步骤)
    - agentic_chunking    : Agentic Chunking(命题 → 主题聚类 → 合并)
    - utils               : 共享的 Embedding / LLM 客户端 & 文本工具

父子检索完整流程(Milvus 实现)::

    from advancedSplitter import (
        split_parent_child,
        insert_parent_child_nodes,
        build_parent_child_retriever,
        hierarchical_chunk_sizes,
    )
    from llama_index.core.storage.docstore import SimpleDocumentStore

    # 1) 切分:全部层级节点 + 叶子节点
    sizes, overlap = hierarchical_chunk_sizes(chunk_size=2048, chunk_overlap=200)
    all_nodes, leaves = split_parent_child(docs, chunk_sizes=sizes, chunk_overlap=overlap)

    # 2) 入库:全量节点 -> Docstore;叶子 -> Milvus(Embedding 后检索用)
    docstore = SimpleDocumentStore()
    insert_parent_child_nodes(all_nodes, leaves, milvus_store, docstore)

    # 3) 检索:叶子向量命中 -> 每个命中回查完整父块(小 -> 大,同父块去重)
    retriever = build_parent_child_retriever(milvus_store, docstore, similarity_top_k=6)
    nodes = retriever.retrieve("查询问题")

其它入口示例::

    docs = [Document(text=...)]
    nodes = split_semantic(docs, breakpoint_percentile_threshold=80)
"""
from .parent_child import (
    DEFAULT_CHUNK_SIZES,
    ParentLookupRetriever,
    build_parent_child_retriever,
    delete_parent_child_nodes,
    hierarchical_chunk_sizes,
    insert_parent_child_nodes,
    split_parent_child,
)
from .semantic import split_semantic, split_semantic_dual
from .llm_chunking import split_by_llm
from .propositions import extract_propositions, propositions_to_nodes
from .agentic_chunking import split_agentic

__all__ = [
    # parent_child
    "split_parent_child",
    "hierarchical_chunk_sizes",
    "insert_parent_child_nodes",
    "delete_parent_child_nodes",
    "build_parent_child_retriever",
    "ParentLookupRetriever",
    "DEFAULT_CHUNK_SIZES",
    # semantic
    "split_semantic",
    "split_semantic_dual",
    # llm_chunking
    "split_by_llm",
    # propositions
    "extract_propositions",
    "propositions_to_nodes",
    # agentic
    "split_agentic",
]
