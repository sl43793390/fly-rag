"""
config
~~~~~~~
集中管理项目配置(Embedding、LLM、Milvus、Chat)。

覆盖优先级:
    1. 函数调用时显式传入的参数
    2. 环境变量
    3. 代码中的默认值
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, List


def _env(key: str, default: str) -> str:
    """
    读取环境变量,缺失时返回默认值。

    Args:
        key: 环境变量名。
        default: 默认值。

    Returns:
        环境变量值或默认值。
    """
    return os.environ.get(key, default)


def _env_json(key: str, default) -> dict:
    """
    读取 JSON 格式的环境变量(用于 dict / list 类配置),缺失或非法时返回默认值。

    Args:
        key: 环境变量名。
        default: 默认值(dict)。

    Returns:
        解析后的 dict,解析失败时回落默认值。
    """
    import json

    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else default
    except (ValueError, TypeError):
        return default


@dataclass
class EmbeddingConfig:
    """Embedding 模型配置(OpenAI 兼容)。"""

    #: Embedding 模型名,如 ``text-embedding-3-small`` 或各厂商自带。
    model: str = field(default_factory=lambda: _env("EMBED_MODEL", "text-embedding-3-small"))
    #: API Key。
    api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", "sk-xxxxxx"))
    #: API Base URL(支持任意 OpenAI 兼容服务,如 dmxapi / DeepSeek / 通义等)。
    api_base: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://www.dmxapi.cn/v1"))
    #: Embedding 维度(Milvus 建表需要,需与所选模型匹配)。
    dim: int = field(default_factory=lambda: int(_env("EMBED_DIM", "1536")))


@dataclass
class LLMConfig:
    """LLM 配置(OpenAI 兼容,可以是 DeepSeek / 通义千问 / Ollama / vLLM 等)。"""

    #: 模型名。
    model: str = field(default_factory=lambda: _env("LLM_MODEL", "deepseek-v4-flash-0731"))
    #: API Key。
    api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", "sk-xxxxxx"))
    #: API Base URL。
    api_base: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "https://www.dmxapi.cn/v1"))
    #: 采样温度,越低越确定。
    temperature: float = 0.2
    #: 单次生成最大 token 数。
    max_tokens: int = 8192
    #: 请求超时秒数。
    timeout: float = 60.0


@dataclass
class MilvusConfig:
    """Milvus 向量库配置。

    分为四组:
    1. 连接: uri / token / collection_name / overwrite;
    2. Schema 字段名: 向量字段 / 稀疏字段 / 文本字段 / doc_id 字段;
    3. 索引与度量: 密集索引类型 / 参数 / 相似度度量 / 稀疏索引;
    4. 混合检索(BM25 全文检索,需 Milvus 2.5+ 服务端):
       enable_hybrid / 分词器 / 融合排序器及参数 / 一致性级别。
    """

    # ---------- 1. 连接 ----------
    #: Milvus 连接字符串。
    #: 嵌入式模式:本地文件路径,如 ``./milvus.db``。
    #: 集群/单机模式:服务器地址,如 ``http://localhost:19530``。
    uri: str = field(default_factory=lambda: _env("MILVUS_URI", "./milvus_llamaindex.db"))
    #: Milvus 集群访问 token(嵌入式不需要)。
    token: Optional[str] = field(default_factory=lambda: _env("MILVUS_TOKEN", None))
    #: 集合(表)名。
    collection_name: str = field(default_factory=lambda: _env("MILVUS_COLLECTION", "llamaindex_rag"))
    #: 是否每次启动覆盖已有 collection。
    overwrite: bool = field(default_factory=lambda: _env("MILVUS_OVERWRITE", "true").lower() == "true")
    #: 一致性级别(Bounded / Session / Strong / Eventually)。
    #: 写入后立即检索的场景建议 Strong 或 Bounded,避免新文档查不到。
    consistency_level: str = field(default_factory=lambda: _env("MILVUS_CONSISTENCY_LEVEL", "Session"))

    # ---------- 2. Schema 字段名 ----------
    #: 稠密向量字段名。
    vector_field: str = field(default_factory=lambda: _env("MILVUS_VECTOR_FIELD", "embedding"))
    #: 稀疏向量字段名(BM25 Function 的输出字段)。
    sparse_vector_field: str = field(default_factory=lambda: _env("MILVUS_SPARSE_VECTOR_FIELD", "sparse_embedding"))
    #: 原文文本字段名(节点正文存放字段,同时也是 BM25 的输入字段)。
    text_field: str = field(default_factory=lambda: _env("MILVUS_TEXT_FIELD", "text"))
    #: 文档 id 字段名(llama-index 用于按 ref_doc_id 删除节点)。
    doc_id_field: str = field(default_factory=lambda: _env("MILVUS_DOC_ID_FIELD", "doc_id"))
    #: 是否允许动态字段(未在 schema 中声明的 metadata 键自动建列)。
    #: 注意:当前 llama-index-vector-stores-milvus 1.1.0 建表固定 enable_dynamic_field=True,
    #: 该配置用于显式表达意图,自建 schema / 升级库版本时生效。
    enable_dynamic_field: bool = field(
        default_factory=lambda: _env("MILVUS_ENABLE_DYNAMIC_FIELD", "true").lower() == "true"
    )

    # ---------- 3. 索引与度量 ----------
    #: 稠密向量相似度度量类型: IP(内积) / COSINE(余弦) / L2(欧氏)。
    #: 使用 OpenAI 兼容 embedding 时 COSINE 更通用;为兼容历史 collection 默认 IP。
    similarity_metric: str = field(default_factory=lambda: _env("MILVUS_SIMILARITY_METRIC", "IP"))
    #: 稠密向量索引类型: FLAT / AUTOINDEX / HNSW / IVF_FLAT / DISKANN 等。
    index_type: str = field(default_factory=lambda: _env("MILVUS_INDEX_TYPE", "FLAT"))
    #: 稠密索引构建参数(随 index_type 变化):
    #:   HNSW -> {"M": 24, "efConstruction": 360};IVF_FLAT -> {"nlist": 1024}。
    index_params: Dict[str, float] = field(default_factory=lambda: _env_json("MILVUS_INDEX_PARAMS", {}))
    #: 稠密检索参数(随 index_type 变化): HNSW -> {"ef": 128};IVF -> {"nprobe": 16}。
    search_params: Dict[str, float] = field(default_factory=lambda: _env_json("MILVUS_SEARCH_PARAMS", {}))
    #: 稀疏向量索引类型(BM25 稀疏向量固定用 SPARSE_INVERTED_INDEX / SPARSE_WAND)。
    sparse_index_type: str = field(default_factory=lambda: _env("MILVUS_SPARSE_INDEX_TYPE", "SPARSE_INVERTED_INDEX"))
    #: 稀疏索引构建参数,如 {"drop_ratio_build": 0.2}(构建时丢弃最小权重,省内存)。
    sparse_index_params: Dict[str, float] = field(
        default_factory=lambda: _env_json("MILVUS_SPARSE_INDEX_PARAMS", {})
    )

    # ---------- 4. 混合检索(BM25 全文检索) ----------
    #: 是否启用混合检索:True 时 collection 建表带稀疏向量字段 + BM25 Function,
    #: Milvus 2.5+ 在写入时自动把文本转稀疏向量、查询时自动分词,无需自备稀疏模型。
    #: 关闭后仅稠密检索(旧 collection / 低版本服务端兼容)。
    enable_hybrid: bool = field(default_factory=lambda: _env("MILVUS_ENABLE_HYBRID", "true").lower() == "true")
    #: BM25 分词器类型: jieba(中文词典分词,Milvus 全版本支持,推荐) / standard(标准分词)。
    #: 注意:milvus-lite / 部分版本服务端不支持 "chinese" 类型,
    #: 支持集以服务端为准(报错 unknown tokenizer type 时按提示调整)。
    analyzer_type: str = field(default_factory=lambda: _env("MILVUS_ANALYZER_TYPE", "jieba"))
    #: 默认融合排序器: RRFRanker(对量纲不敏感,推荐) / WeightedRanker(需归一化)。
    hybrid_ranker: str = field(default_factory=lambda: _env("MILVUS_HYBRID_RANKER", "RRFRanker"))
    #: 融合排序器参数:
    #:   RRFRanker -> {"k": 60};WeightedRanker -> {"weights": [0.7, 0.3]}(稠密, 稀疏)。
    hybrid_ranker_params: Dict[str, object] = field(
        default_factory=lambda: _env_json("MILVUS_HYBRID_RANKER_PARAMS", {"k": 60})
    )
    #: 稀疏检索参数,如 {"drop_ratio_search": 0.2}(查询时丢弃最小权重,提效)。
    sparse_search_params: Dict[str, float] = field(
        default_factory=lambda: _env_json("MILVUS_SPARSE_SEARCH_PARAMS", {})
    )


@dataclass
class ChatConfig:
    """对话引擎配置。"""

    #: 是否对多轮问题进行改写(CondenseQuestionChatEngine)。
    #: True  = 改写(适合口语化、上下文依赖问题)
    #: False = 不改写(CustomRAGChatEngine,保留原问题直接检索)
    enable_question_rewriting: bool = field(
        default_factory=lambda: _env("ENABLE_QUESTION_REWRITING", "true").lower() == "true"
    )
    #: 检索返回的最相关节点数。
    similarity_top_k: int = field(default_factory=lambda: int(_env("SIMILARITY_TOP_K", "5")))
    #: RAG 检索节点相似度下限(0~1):低于该分数的节点视为不相关,直接丢弃,
    #: 防止知识库外的问题把不相关内容当"参考资料"喂给 LLM 导致自由发挥。
    #: 设为 0 表示不过滤。
    min_score: float = field(default_factory=lambda: float(_env("RAG_MIN_SCORE", "0.35")))
    #: 对话历史 token 上限(超过会被裁剪)。
    memory_token_limit: int = field(default_factory=lambda: int(_env("MEMORY_TOKEN_LIMIT", "3000")))
    #: 是否开启 RAG 全链路调试日志(打印检索节点、提示词、模型响应)。
    debug: bool = field(default_factory=lambda: _env("RAG_DEBUG", "false").lower() == "true")
    #: 调试打印时,单段文本的截断长度(字符数)。
    debug_text_limit: int = field(default_factory=lambda: int(_env("RAG_DEBUG_TEXT_LIMIT", "800")))
    #: 对话明细日志开关:按阶段打印 ①前端用户消息 ②Milvus 检索结果
    #: ③RAG 系统提示词 ④最终发送给大模型的完整消息 ⑤大模型回复,
    #: 各阶段以横线分隔,便于排查"提示词是否生效 / 检索是否命中"等问题。
    #: 环境变量 CHAT_LOG_DETAIL=false 可关闭。
    log_chat_detail: bool = field(
        default_factory=lambda: _env("CHAT_LOG_DETAIL", "true").lower() == "false"
    )


# ============================================================
# 默认配置实例(可直接 import 使用)
# ============================================================
EMBED = EmbeddingConfig()
LLM = LLMConfig()
MILVUS = MilvusConfig()
CHAT = ChatConfig()
