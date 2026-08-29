"""
api.schemas
~~~~~~~~~~~
Pydantic 请求 / 响应模型。
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

#: 支持的切分器(spliter.auto_split 的 doc_type + auto)
SPLITTERS = [
    "auto", "sentence", "text", "paragraph", "token", "simple", "markdown", "html", "json",
]

#: 支持的检索方式
RETRIEVAL_MODES = ["dense", "sparse", "hybrid"]

#: 支持的混合检索融合排序器(Milvus hybrid search,大小写敏感)
HYBRID_RANKERS = ["RRFRanker", "WeightedRanker"]


# ------------------------------------------------------------
# 知识库
# ------------------------------------------------------------
class KbCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    description: str = Field("", max_length=512)
    splitter: str = Field("auto", description="切分器类型")
    chunk_size: int = Field(1024, ge=100, le=8192)
    chunk_overlap: int = Field(200, ge=0, le=2048)
    retrieval_mode: str = Field(
        "dense", description="检索方式: dense(向量)/sparse(BM25 全文)/hybrid(融合)"
    )
    hybrid_ranker: Optional[str] = Field(
        None, description="融合排序器: RRFRanker/WeightedRanker(仅 hybrid 生效,空则用全局默认)"
    )
    hybrid_ranker_params: Optional[dict] = Field(
        None, description="融合排序参数: RRF -> {k:60}; Weighted -> {weights:[1.0,1.0]}"
    )


class KbUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    splitter: Optional[str] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=8192)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=2048)
    retrieval_mode: Optional[str] = None
    hybrid_ranker: Optional[str] = None
    hybrid_ranker_params: Optional[dict] = None


class KbOut(BaseModel):
    id: int
    name: str
    description: str
    collection_name: str
    splitter: str
    chunk_size: int
    chunk_overlap: int
    retrieval_mode: str = "dense"
    hybrid_ranker: Optional[str] = None
    hybrid_ranker_params: Optional[dict] = None
    doc_count: int = 0
    done_doc_count: int = 0
    node_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ------------------------------------------------------------
# 文档
# ------------------------------------------------------------
class DocumentOut(BaseModel):
    id: int
    kb_id: int
    file_name: str
    file_path: str
    file_ext: str
    file_size: int
    status: str
    node_count: int
    error_msg: str
    splitter: str
    chunk_size: int
    chunk_overlap: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UploadResult(BaseModel):
    total: int
    accepted: int
    rejected: List[dict] = Field(default_factory=list, description="被拒绝的文件及原因")
    documents: List[DocumentOut] = []


# ------------------------------------------------------------
# 对话
# ------------------------------------------------------------
class SessionCreate(BaseModel):
    kb_id: Optional[int] = Field(
        None, description="知识库 id;为空表示纯 LLM 对话(不挂知识库)"
    )
    title: str = Field("新会话", max_length=255)
    mode: str = Field("rag", description="会话模式:rag/chat(纯 LLM)")


class SessionOut(BaseModel):
    id: int
    kb_id: Optional[int] = None
    owner_id: Optional[int] = None
    title: str
    mode: str = "rag"
    kb_name: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    sources: Optional[list] = None
    is_summary: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8192)


class SourceItem(BaseModel):
    text: str = ""
    score: Optional[float] = None
    file_name: str = ""
    section: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceItem] = []
    message_id: Optional[int] = None
    compressed: bool = Field(
        False, description="本次对话后是否触发了历史自动压缩"
    )


# ------------------------------------------------------------
# 提示词模版
# ------------------------------------------------------------
class PromptCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=128, description="提示词标题")
    content: str = Field(..., min_length=1, max_length=16384, description="提示词内容")


class PromptUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=128)
    content: Optional[str] = Field(None, min_length=1, max_length=16384)


class PromptOut(BaseModel):
    id: int
    title: str
    content: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
