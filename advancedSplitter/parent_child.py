"""
advancedSplitter.parent_child
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
父子切分 + 父块回查检索(Hierarchical Retrieval / Small-to-Big,Milvus 实现)。

原理:
    1. 用 HierarchicalNodeParser 把每个 Document 切成多层节点:
        - L0:父块(最大粒度,如 2048)
        - L1:中块(如 512)
        - L2:叶子块(最小粒度,如 128,用于向量检索)
    2. 入库(双存储):
        - 全部层级节点 -> Docstore(SimpleDocumentStore,JSON 落盘,按知识库隔离);
        - 仅叶子节点  -> Milvus(Embedding 后做稠密向量检索)。
    3. 检索(ParentLookupRetriever,小 -> 大):
        - 先在 Milvus 检索叶子块(小块语义聚焦,命中准);
        - 每个命中叶子沿 PARENT 关系从 Docstore 一路回查到顶层父块
          (L0,即知识库配置的"块大小"粒度,上下文最完整);
        - 同一顶层父块下的多个命中自动去重,按最高子块分数排序返回。

何时该用:
    - 文档有明显段落 / 章节结构(报告、论文、长文);
    - 小块检索能命中但上下文不足,整段作块又太大。

关键实现细节
------------
- SOURCE 关系统一改写为指向根 Document(ref_doc_id 传播到全部层级):
  HierarchicalNodeParser 逐层切分时,下层节点的 SOURCE 指向上一级节点
  (L2->L1->L0->Document)。Milvus 的 doc_id 列存的就是 ref_doc_id,
  不改写的话"按文档删除"会把 L1 节点 id 当 doc_id,漏删叶子节点。
- 为什么不用 AutoMergingRetriever(兄弟占比达标才合并):
  默认 top_k=5 且叶子=父块/16 时,命中分散在文档各处,任何父块的
  命中占比都到不了阈值,合并永远不会触发,父子检索退化为普通检索。
- 降级:Docstore 缺失父块时(如普通切分入库后切换为父子检索的旧数据),
  该命中保留叶子结果,检索不中断。

依赖:llama-index-core(HierarchicalNodeParser / BaseRetriever /
SimpleDocumentStore)+ llama-index-vector-stores-milvus(MilvusVectorStore)。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Tuple

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.node_parser import HierarchicalNodeParser, get_leaf_nodes
from llama_index.core.schema import (
    BaseNode,
    NodeRelationship,
    NodeWithScore,
    RelatedNodeInfo,
)
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.vector_stores.milvus import MilvusVectorStore

logger = logging.getLogger(__name__)


# 默认三层粒度:父块 2048、中块 512、叶子 128(比值 16:4:1)
DEFAULT_CHUNK_SIZES: Tuple[int, ...] = (2048, 512, 128)

#: 由知识库 chunk_size 推导层级粒度时,父块大小的下限
_MIN_PARENT_CHUNK: int = 512

#: 叶子块大小的下限(过小的叶子 Embedding 语义噪声大)
_MIN_LEAF_CHUNK: int = 64


# ============================================================
# 切分
# ============================================================
def hierarchical_chunk_sizes(
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> Tuple[List[int], int]:
    """
    由知识库的 chunk_size / chunk_overlap 推导三层切分粒度。

    规则(父:中:叶 = 16:4:1,与 LlamaIndex 默认 2048/512/128 同比例):
        - 父块 = max(chunk_size, 512)
        - 中块 = max(父块 / 4, 128)
        - 叶子 = max(父块 / 16, 64)
        - 重叠 = min(chunk_overlap, 叶子 / 4)(默认切分参数是为平铺块设计的,
          大重叠直接用于小叶子会导致句子乱拼,故按叶子大小封顶)

    Args:
        chunk_size: 知识库配置的块大小(即父块大小);None 时用默认 2048。
        chunk_overlap: 知识库配置的块重叠;None 时用 20。

    Returns:
        ``(chunk_sizes, chunk_overlap)``:从大到小的三层粒度与安全重叠值。

    Example:
        >>> hierarchical_chunk_sizes(2048, 200)
        ([2048, 512, 128], 32)
    """
    parent = max(int(chunk_size) if chunk_size else DEFAULT_CHUNK_SIZES[0], _MIN_PARENT_CHUNK)
    mid = max(parent // 4, _MIN_LEAF_CHUNK * 2)
    leaf = max(parent // 16, _MIN_LEAF_CHUNK)

    if chunk_overlap is None:
        overlap = 20
    else:
        overlap = max(0, min(int(chunk_overlap), leaf // 4))

    return [parent, mid, leaf], overlap


def split_parent_child(
    documents: List[Document],
    chunk_sizes: Optional[Sequence[int]] = None,
    chunk_overlap: int = 20,
) -> Tuple[List[BaseNode], List[BaseNode]]:
    """
    父子切分。

    Args:
        documents: 输入 Document 列表(Document.id_ 建议已设为 ``doc_{id}``,
            会作为全部节点的 ref_doc_id,支撑按文档粒度删除)。
        chunk_sizes: 从大到小的粒度序列;默认 ``(2048, 512, 128)``,
            也可用 :func:`hierarchical_chunk_sizes` 由知识库参数推导。
        chunk_overlap: 相邻块重叠(token 数)。

    Returns:
        ``(all_nodes, leaf_nodes)``:
            - ``all_nodes``  : 全部层级节点(整体入 Docstore);
            - ``leaf_nodes`` : 叶子节点(Embedding 后入 Milvus 检索)。

    Example:
        >>> all_nodes, leaves = split_parent_child(docs)
        >>> insert_parent_child_nodes(all_nodes, leaves, milvus_store, docstore)
    """
    sizes = tuple(sorted(chunk_sizes or DEFAULT_CHUNK_SIZES, reverse=True))

    parser = HierarchicalNodeParser.from_defaults(
        chunk_sizes=list(sizes),
        chunk_overlap=chunk_overlap,
    )

    all_nodes = parser.get_nodes_from_documents(documents)
    leaf_nodes = get_leaf_nodes(all_nodes)

    _unify_source_relationships(all_nodes)
    return all_nodes, leaf_nodes


def _unify_source_relationships(all_nodes: List[BaseNode]) -> None:
    """
    把全部层级节点的 SOURCE 关系统一改写为指向根 Document(原地修改)。

    背景:
        HierarchicalNodeParser 逐层下切时,每层新节点的 SOURCE 指向输入节点:
        L0 -> Document,L1 -> 所属 L0,L2 -> 所属 L1。而:
        - Milvus 的 ``doc_id`` 列 = node.ref_doc_id(即 SOURCE 的 node_id);
        - Docstore 按 ref_doc_id 聚合节点,``delete_ref_doc`` 依赖它。
        若不统一,叶子在 Milvus 中的 doc_id 是 L1 节点 id,
        ``store.delete(ref_doc_id="doc_x")`` 会漏删,Docstore 同理只删到 L0。

    处理:
        沿 PARENT 链爬到根(L0),取根的 SOURCE(即 Document id)作为
        所有层级节点的 SOURCE。PARENT / CHILD / PREV / NEXT 关系不受影响
        (父子检索只依赖 PARENT 关系回查父块)。
    """
    id_map = {n.node_id: n for n in all_nodes}
    for node in all_nodes:
        cur = node
        visited = set()
        while True:
            parent_info = cur.relationships.get(NodeRelationship.PARENT)
            if (
                parent_info is None
                or parent_info.node_id not in id_map
                or parent_info.node_id in visited
            ):
                break
            visited.add(parent_info.node_id)
            cur = id_map[parent_info.node_id]
        source_info = cur.relationships.get(NodeRelationship.SOURCE)
        root_id = source_info.node_id if source_info is not None else cur.node_id
        node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=root_id)


# ============================================================
# 入库(双存储:Docstore + Milvus)
# ============================================================
def insert_parent_child_nodes(
    all_nodes: List[BaseNode],
    leaf_nodes: List[BaseNode],
    milvus_store: MilvusVectorStore,
    docstore: SimpleDocumentStore,
) -> int:
    """
    父子检索入库:全量节点入 Docstore,叶子节点入 Milvus。

    Args:
        all_nodes: :func:`split_parent_child` 返回的全部层级节点
            (父块存这里,检索合并时按 id 回查)。
        leaf_nodes: 叶子节点(Embedding 后写入 Milvus 参与向量检索)。
        milvus_store: 该知识库的 MilvusVectorStore(collection: kb_{id})。
        docstore: 该知识库的 SimpleDocumentStore。

    Returns:
        实际写入 Milvus 的叶子节点数。

    Note:
        - 仅叶子节点 Embedding 并写入 Milvus,父块不产生 Embedding 开销,
          也不会污染向量检索结果;
        - Docstore 的落盘(persist)由调用方负责(见
          ``api.services.docstore_cache.persist_docstore``)。
    """
    if all_nodes:
        docstore.add_documents(list(all_nodes))

    index = VectorStoreIndex.from_vector_store(vector_store=milvus_store)
    if leaf_nodes:
        index.insert_nodes(list(leaf_nodes))
    return len(leaf_nodes)


def delete_parent_child_nodes(
    milvus_store: MilvusVectorStore,
    docstore: SimpleDocumentStore,
    ref_doc_id: str,
) -> None:
    """
    按文档删除父子检索的全部节点(Milvus 叶子 + Docstore 全层级,幂等)。

    Args:
        milvus_store: 该知识库的 MilvusVectorStore。
        docstore: 该知识库的 SimpleDocumentStore。
        ref_doc_id: 文档标识(``doc_{id}``,即入库时 Document.id_)。
    """
    try:
        milvus_store.delete(ref_doc_id=ref_doc_id)
    except Exception as exc:  # noqa: BLE001 - collection 不存在等不阻断
        logger.warning("Milvus 删除节点失败(ref_doc_id=%s): %s", ref_doc_id, exc)
    try:
        docstore.delete_ref_doc(ref_doc_id, raise_error=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Docstore 删除节点失败(ref_doc_id=%s): %s", ref_doc_id, exc)


# ============================================================
# 检索(Milvus 叶子检索 + 父块回查,小 -> 大)
# ============================================================
class ParentLookupRetriever(BaseRetriever):
    """
    父子检索器(小 -> 大):叶子精准命中,顶层父块完整上下文。

    流程:
        1. Milvus 稠密检索叶子块(向量库中只存叶子);
        2. 每个命中叶子沿 PARENT 关系从 Docstore 一路回查到顶层父块
           (L0,即知识库配置的"块大小"粒度),上下文完整、章节齐全;
        3. 同一顶层父块下的多个命中自动去重,父块分数取命中子块中的最高分;
        4. 按分数降序返回(去重后的父块 + 少数未能回查到父块的叶子)。

    为什么不用 AutoMergingRetriever(兄弟占比达标才合并):
        其合并依赖"命中聚集程度"——默认 top_k=5 且叶子=父块/16 时,
        命中分散在文档各处,任何父块的命中占比都到不了阈值(5/16 < 0.5),
        合并永远不会触发,父子检索退化成普通叶子检索。
        本检索器不依赖命中聚集:每个命中都确定性地回查完整父块,
        同一父块多次命中由去重兜底,不会撑大上下文。

    降级:Docstore 缺失父块时(如普通切分入库后切换为父子检索的旧数据),
    返回能回查到的最高层级节点,全部缺失则保留叶子,检索不中断。
    """

    def __init__(
        self,
        milvus_store: MilvusVectorStore,
        docstore: SimpleDocumentStore,
        similarity_top_k: int = 6,
        verbose: bool = False,
    ) -> None:
        index = VectorStoreIndex.from_vector_store(vector_store=milvus_store)
        self._leaf_retriever = index.as_retriever(similarity_top_k=similarity_top_k)
        self._docstore = docstore
        self._verbose = verbose
        super().__init__()

    def _resolve_top_parent(self, parent_info) -> Optional[BaseNode]:
        """
        从直接父块沿 PARENT 关系回查到顶层父块(L0)。

        Docstore 中存有全部层级节点,取到的节点自带 PARENT 关系,可继续
        向上爬;任何一环缺失时停在已取到的最高层级(全部缺失返回 None,
        由调用方降级保留叶子)。
        """
        node = self._docstore.get_document(parent_info.node_id, raise_error=False)
        visited = {parent_info.node_id}
        while node is not None:
            next_parent = node.parent_node
            if next_parent is None or next_parent.node_id in visited:
                break
            parent = self._docstore.get_document(next_parent.node_id, raise_error=False)
            if parent is None:
                logger.warning(
                    "Docstore 缺失父块 %s,停在其子节点 %s(层级回查中断)",
                    next_parent.node_id, node.node_id,
                )
                break
            visited.add(next_parent.node_id)
            node = parent
        return node

    def _retrieve(self, query_bundle) -> List[NodeWithScore]:
        leaves = self._leaf_retriever.retrieve(query_bundle)

        parent_nodes: Dict[str, NodeWithScore] = {}
        fallback: List[NodeWithScore] = []
        for nws in leaves:
            node = nws.node
            parent_info = node.parent_node if node is not None else None
            if parent_info is None:
                # 无父块关系(如旧数据),原样保留
                fallback.append(nws)
                continue
            parent = self._resolve_top_parent(parent_info)
            if parent is None:
                fallback.append(nws)
                continue
            cur = parent_nodes.get(parent.node_id)
            if cur is None or (nws.get_score() or 0.0) > (cur.get_score() or 0.0):
                # 父块分数取命中子块中的最高分,保证 min_score 过滤语义一致
                parent_nodes[parent.node_id] = NodeWithScore(
                    node=parent, score=nws.get_score()
                )

        if self._verbose:
            print(
                f"> ParentLookup: {len(leaves)} 个叶子命中 -> "
                f"{len(parent_nodes)} 个顶层父块(去重前 {len(leaves) - len(fallback)} 次), "
                f"{len(fallback)} 个叶子无父块按原样保留"
            )

        results = list(parent_nodes.values()) + fallback
        results.sort(key=lambda x: x.get_score() or 0.0, reverse=True)
        return results


def build_parent_child_retriever(
    milvus_store: MilvusVectorStore,
    docstore: SimpleDocumentStore,
    similarity_top_k: int = 6,
    verbose: bool = False,
) -> ParentLookupRetriever:
    """
    构建父子检索器:Milvus 叶子向量检索 + 父块回查(小 -> 大)。

    Args:
        milvus_store: 该知识库的 MilvusVectorStore(仅存叶子节点)。
        docstore: 该知识库的 SimpleDocumentStore(存全部层级节点)。
        similarity_top_k: 检索的叶子块数;同一顶层父块下的多个命中会被去重,
          最终返回的父块数 <= 该值,合理范围 4~10。
        verbose: 打印合并过程(调试用)。

    Returns:
        可直接传给对话引擎(CustomRAGChatEngine)的检索器。
    """
    return ParentLookupRetriever(
        milvus_store=milvus_store,
        docstore=docstore,
        similarity_top_k=similarity_top_k,
        verbose=verbose,
    )
