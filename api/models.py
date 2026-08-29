"""
api.models
~~~~~~~~~~
ORM 模型:知识库 / 文档 / 对话会话 / 对话消息。

对应建表脚本见 ``sql/init.sql``(应用启动时也会按此处定义自动建表)。
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from api.database import Base


class KnowledgeBase(Base):
    """知识库(每个知识库对应一个 Milvus collection: kb_{id})。"""

    __tablename__ = "knowledge_base"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, comment="知识库名称")
    description = Column(String(512), default="", server_default="", comment="描述")
    collection_name = Column(String(128), nullable=False, comment="Milvus collection 名")
    #: 切分器: auto(按后缀自动) / sentence / token / simple / markdown / html / json
    splitter = Column(String(32), nullable=False, default="auto", server_default="auto")
    chunk_size = Column(Integer, nullable=False, default=1024, server_default="1024")
    chunk_overlap = Column(Integer, nullable=False, default=200, server_default="200")
    #: 检索方式: dense(仅向量) / sparse(仅 BM25 全文) / hybrid(稠密+BM25 融合)
    #: / parent_child(父子检索:层级切分,叶子入 Milvus,父块入 Docstore 自动合并)
    retrieval_mode = Column(
        String(16),
        nullable=False,
        default="dense",
        server_default="dense",
        comment="检索方式: dense/sparse/hybrid/parent_child",
    )
    #: 融合排序器(retrieval_mode=hybrid 时生效): RRFRanker / WeightedRanker
    hybrid_ranker = Column(
        String(16), nullable=True, comment="混合检索融合排序: RRFRanker/WeightedRanker"
    )
    #: 融合排序参数: RRFRanker -> {"k": 60}; WeightedRanker -> {"weights": [1.0, 1.0]}
    hybrid_ranker_params = Column(JSON, nullable=True, comment="融合排序参数")
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, server_default=func.now()
    )

    documents = relationship(
        "KbDocument", back_populates="kb", cascade="all, delete-orphan", passive_deletes=True
    )
    sessions = relationship(
        "ChatSession", back_populates="kb", cascade="all, delete-orphan", passive_deletes=True
    )


class KbDocument(Base):
    """知识库下的文档(上传记录 + 解析状态机)。"""

    __tablename__ = "kb_document"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kb_id = Column(
        BigInteger,
        ForeignKey("knowledge_base.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    file_path = Column(String(512), nullable=False, comment="落盘路径")
    file_ext = Column(String(16), default="", server_default="", comment="小写后缀")
    file_size = Column(BigInteger, default=0, server_default="0", comment="字节")
    #: pending -> processing -> done / failed
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    node_count = Column(Integer, default=0, server_default="0", comment="切分出的节点数")
    error_msg = Column(String(1024), default="", server_default="", comment="失败原因")
    #: 该文档入库时实际使用的切分参数(便于追溯)
    splitter = Column(String(32), default="auto", server_default="auto")
    chunk_size = Column(Integer, default=1024, server_default="1024")
    chunk_overlap = Column(Integer, default=200, server_default="200")
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, server_default=func.now()
    )

    kb = relationship("KnowledgeBase", back_populates="documents")


class ChatSession(Base):
    """对话会话。

    - ``kb_id`` 可空:为 None 时表示纯 LLM 对话(不挂知识库,不检索);
    - ``owner_id`` 可空:归属的用户 id,None 表示匿名会话(未登录用户共享)。
    """

    __tablename__ = "chat_session"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kb_id = Column(
        BigInteger,
        ForeignKey("knowledge_base.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联知识库(可空,纯 LLM 对话)",
    )
    owner_id = Column(
        BigInteger,
        nullable=True,
        index=True,
        comment="会话所有者(用户 id,可空为匿名会话)",
    )
    title = Column(String(255), nullable=False, default="新会话", server_default="新会话")
    #: 会话模式:rag(知识库对话) / chat(纯 LLM 对话)
    mode = Column(
        String(16), nullable=False, default="rag", server_default="rag"
    )
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, server_default=func.now()
    )

    kb = relationship("KnowledgeBase", back_populates="sessions")
    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class ChatMessage(Base):
    """对话消息(role: user / assistant),assistant 消息可携带引用来源。"""

    __tablename__ = "chat_message"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        BigInteger,
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(16), nullable=False, comment="user / assistant")
    content = Column(Text, nullable=False, default="", server_default="")
    #: RAG 引用来源(JSON 数组): [{text, score, file_name}]
    sources = Column(JSON, nullable=True)
    #: 是否为压缩摘要消息(超出保留窗口的旧对话会被 LLM 总结为一条 assistant 消息)
    is_summary = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class PromptTemplate(Base):
    """提示词模版(用户沉淀的常用提问模版,按 owner 隔离)。"""

    __tablename__ = "prompt_template"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_id = Column(
        BigInteger, nullable=False, index=True, comment="所属用户 id"
    )
    title = Column(String(128), nullable=False, comment="提示词标题")
    content = Column(Text, nullable=False, comment="提示词内容")
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, server_default=func.now()
    )
