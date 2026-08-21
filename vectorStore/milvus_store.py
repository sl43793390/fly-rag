"""
vectorStore.milvus_store
~~~~~~~~~~~~~~~~~~~~~~~~~~
将切分后的节点写入 Milvus,并提供索引/检索封装。

主要能力
--------
- ``get_embed_model``      : 获取 OpenAI 兼容的 Embedding 模型
- ``get_llm``              : 获取 OpenAI 兼容的 LLM
- ``configure_settings``   : 把 Embedding / LLM 注册到全局 ``Settings``
- ``build_milvus_store``   : 构造 Milvus 向量库客户端
- ``create_index``         : 把节点写入 Milvus 并构建可查询索引
- ``load_existing_index``  : 加载已存在的 Milvus 集合(不重新写入)
- ``inspect_milvus``       : 自检工具 —— 打印 schema、样本数据
"""
from typing import List, Optional

from llama_index.core import StorageContext, VectorStoreIndex, Settings
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.llms import LLM
from llama_index.core.schema import BaseNode
from llama_index.vector_stores.milvus import MilvusVectorStore

from config import MILVUS, EMBED, LLM as LLM_CFG


# ============================================================
# 模型构造
# ============================================================
def get_embed_model() -> BaseEmbedding:
    """
    获取 OpenAI 兼容的 Embedding 模型。

    Returns:
        配置好 model / api_key / api_base 的 ``OpenAIEmbedding`` 实例。
    """
    from llama_index.embeddings.openai import OpenAIEmbedding
    return OpenAIEmbedding(
        model=EMBED.model,
        api_key=EMBED.api_key,
        api_base=EMBED.api_base,
        embed_batch_size=64,
    )


def _patch_openai_model_registry():
    """
    修补 LlamaIndex 的 OpenAI 模型注册表，使非 OpenAI 模型名（如 deepseek-v4-flash）
    不会触发 ``openai_modelname_to_contextsize`` 的 ValueError，
    同时确保使用 chat completions 端点而非 text completions 端点。

    LlamaIndex 的 ``OpenAI`` LLM 在访问 ``metadata`` 属性时会调用
    ``openai_modelname_to_contextsize(model_name)``，该函数仅识别 OpenAI 官方模型名，
    对第三方兼容 API 的模型名会直接抛异常。此外，``is_chat_model`` 函数会检查模型
    是否在 ``CHAT_MODELS`` 集合中，不在其中的模型会走 text completions 端点，
    而大多数第三方 API 仅支持 chat completions 端点。

    此函数将当前配置的模型名注册到 ``ALL_AVAILABLE_MODELS`` 和 ``CHAT_MODELS`` 中。
    """
    from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS, CHAT_MODELS
    model_name = LLM_CFG.model
    if model_name not in ALL_AVAILABLE_MODELS:
        ALL_AVAILABLE_MODELS[model_name] = 256000  # 默认上下文窗口大小
    if model_name not in CHAT_MODELS:
        CHAT_MODELS[model_name] = True


def get_llm() -> LLM:
    """
    获取 OpenAI 兼容的 LLM(可用于生成 / 对话)。

    Returns:
        配置好 model / api_key / api_base / temperature 等的 ``OpenAI`` 实例。
    """
    _patch_openai_model_registry()
    from llama_index.llms.openai import OpenAI
    return OpenAI(
        model=LLM_CFG.model,
        api_key=LLM_CFG.api_key,
        api_base=LLM_CFG.api_base,
        temperature=LLM_CFG.temperature,
        max_tokens=LLM_CFG.max_tokens,
        timeout=LLM_CFG.timeout,
    )


def configure_settings(
    embed_model: Optional[BaseEmbedding] = None,
    llm: Optional[LLM] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> None:
    """
    全局注册 Embedding / LLM / 切分参数,供 ``Index`` / ``QueryEngine`` 使用。

    Args:
        embed_model: 自定义 Embedding;为 None 时使用 :func:`get_embed_model`。
        llm: 自定义 LLM;为 None 时使用 :func:`get_llm`。
        chunk_size: 全局切分块大小;为 None 时保持默认 1024。
        chunk_overlap: 全局切分重叠大小;为 None 时保持默认 200。
    """
    Settings.embed_model = embed_model or get_embed_model()
    Settings.llm = llm or get_llm()
    Settings.chunk_size = chunk_size if chunk_size is not None else 1024
    Settings.chunk_overlap = chunk_overlap if chunk_overlap is not None else 200


# ============================================================
# Milvus 客户端
# ============================================================
def build_milvus_store(
    uri: Optional[str] = None,
    token: Optional[str] = None,
    collection_name: Optional[str] = None,
    dim: Optional[int] = None,
    overwrite: Optional[bool] = None,
) -> MilvusVectorStore:
    """
    构造 Milvus 向量库客户端。

    Args:
        uri:
            - 嵌入式模式:本地文件路径,如 ``./milvus.db``
            - 集群/单机模式:服务器地址,如 ``http://localhost:19530``
        token: Milvus 集群的访问 token(嵌入式不需要)。
        collection_name: 集合(表)名。
        dim: 向量维度,需与 Embedding 模型一致。
        overwrite: True 时会清空已存在集合;为 None 时从 ``config.MILVUS.overwrite`` 读取。

    Returns:
        配置好的 ``MilvusVectorStore`` 实例。

    Note:
        必须显式传 ``output_fields=["text", "_node_content", "_node_type"]``。
        - ``text``: 保证检索出来的节点 text 不为空;
        - ``_node_content`` / ``_node_type``: 让 llama-index 检索时能
          ``metadata_dict_to_node`` 还原完整节点(含 file_name / section 等
          入库时写入的元数据),否则前端引用与发给 LLM 的来源信息会丢失。
    """
    return MilvusVectorStore(
        uri=uri if uri is not None else MILVUS.uri,
        token=token if token is not None else MILVUS.token,
        collection_name=collection_name if collection_name is not None else MILVUS.collection_name,
        dim=dim if dim is not None else EMBED.dim,
        overwrite=overwrite if overwrite is not None else MILVUS.overwrite,
        # 关键:text + 节点序列化字段,保证检索能拿到内容与完整元数据
        output_fields=["text", "_node_content", "_node_type"],
    )


# ============================================================
# 索引构建 / 加载
# ============================================================
def create_index(
    nodes: List[BaseNode],
    milvus_store: Optional[MilvusVectorStore] = None,
) -> VectorStoreIndex:
    """
    将节点写入 Milvus 并构建可查询的索引。

    Args:
        nodes: 切分后的 BaseNode 列表。
        milvus_store: 已构造好的 Milvus 客户端;为 None 时使用 :func:`build_milvus_store`。

    Returns:
        可用于检索 / 对话构造的 ``VectorStoreIndex``。
    """
    store = milvus_store or build_milvus_store()
    storage_context = StorageContext.from_defaults(vector_store=store)

    if nodes:
        index = VectorStoreIndex(
            nodes=nodes,
            storage_context=storage_context,
            show_progress=True,
        )
    else:
        index = VectorStoreIndex.from_vector_store(
            vector_store=store,
            storage_context=storage_context,
        )
    return index


def load_existing_index(
    milvus_store: Optional[MilvusVectorStore] = None,
) -> VectorStoreIndex:
    """
    加载已存在的 Milvus 集合(不重新写入)。

    Args:
        milvus_store: 已构造好的 Milvus 客户端;为 None 时构造一个 ``overwrite=False`` 的实例。

    Returns:
        ``VectorStoreIndex``。
    """
    store = milvus_store or build_milvus_store(overwrite=False)
    store.client.load_collection(store.collection_name)
    return VectorStoreIndex.from_vector_store(vector_store=store)


# ============================================================
# 自检工具
# ============================================================
def inspect_milvus(
    collection_name: Optional[str] = None,
    uri: Optional[str] = None,
    limit: int = 3,
) -> None:
    """
    直接查 Milvus collection 的 schema 和样本数据,用于排查:
        - 节点 text 是否真的写入了 Milvus
        - 字段名 / 类型是否符合预期

    Args:
        collection_name: 集合名;为 None 时从 ``config.MILVUS`` 读取。
        uri: Milvus uri;为 None 时从 ``config.MILVUS`` 读取。
        limit: 抽样条数。
    """
    from pymilvus import MilvusClient
    client = MilvusClient(uri=uri or MILVUS.uri)
    cname = collection_name or MILVUS.collection_name

    print("=" * 70)
    print(f"【Milvus 自检】collection: {cname}")
    print("=" * 70)

    if not client.has_collection(cname):
        print(f"❌ collection '{cname}' 不存在")
        return

    # 1. schema
    schema = client.describe_collection(cname)
    print("\n--- Schema ---")
    for f in schema.get("fields", []):
        print(
            f"  - {f.get('name')}  type={f.get('type')}  "
            f"is_primary={f.get('is_primary', False)}  "
            f"dim={f.get('dim', '-')}"
        )

    # 2. 统计
    stats = client.get_collection_stats(cname)
    print("\n--- Stats ---")
    print(f"  row_count: {stats.get('row_count', '?')}")

    # 3. 抽样
    print(f"\n--- Sample (limit={limit}) ---")
    rows = client.query(cname, output_fields=["*"], limit=limit)
    for i, row in enumerate(rows, 1):
        text = row.get("text", "")
        print(f"\n  Row {i}:")
        print(f"    id   : {row.get('id', '')}")
        print(
            f"    text : {repr(text[:120] + ('...' if len(text) > 120 else ''))}"
        )
        meta_keys = [k for k in row.keys() if k not in ("id", "vector", "text")]
        if meta_keys:
            print(f"    meta : {meta_keys}")
