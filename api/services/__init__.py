"""api.services:业务逻辑层(文档入库 / 对话引擎管理)。"""
from api.services.chat_service import ChatService
from api.services.docstore_cache import (
    delete_docstore,
    docstore_exists,
    get_docstore,
    persist_docstore,
)
from api.services.ingest_service import ingest_executor, submit_ingest
from api.services.milvus_cache import (
    collection_name_for,
    drop_kb_collection,
    get_store,
    invalidate_store,
)

__all__ = [
    "ChatService",
    "ingest_executor",
    "submit_ingest",
    "collection_name_for",
    "drop_kb_collection",
    "get_store",
    "invalidate_store",
    # 父子检索 Docstore 管理
    "get_docstore",
    "persist_docstore",
    "docstore_exists",
    "delete_docstore",
]
