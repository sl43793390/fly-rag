"""
api.services.ingest_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~
后台文档解析入库服务(状态机: pending -> processing -> done / failed)。

流程(在独立线程池中执行,不阻塞 API 请求):
    1) 从 MySQL 读文档记录与所属知识库;
    2) auto_load 解析 -> 按 splitter/chunk 参数 auto_split 切分;
    3) 按知识库对应的 Milvus collection(kb_{id})流式 insert_nodes;
    4) 成功/失败状态回写 MySQL,前端通过轮询文档列表获取进度。

Document.id_ 统一设置为 ``doc_{doc_id}``,作为节点 ref_doc_id,
使得"删除文档"可以按该前缀一次性删除 Milvus 中对应的所有节点。
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from llama_index.core import VectorStoreIndex

from api.api_config import INGEST_WORKERS
from api.database import SessionLocal
from api.services.milvus_cache import get_store

logger = logging.getLogger("api.ingest")

#: 解析线程池(串行,避免 milvus-lite 并发写同一 db 文件)
ingest_executor = ThreadPoolExecutor(
    max_workers=INGEST_WORKERS, thread_name_prefix="ingest"
)

#: 正在处理的 doc_id 集合(防止重复提交)
_processing: set = set()
_processing_lock = threading.Lock()


def submit_ingest(doc_id: int) -> None:
    """
    提交一个文档的解析入库任务(幂等:同 id 重复提交会被忽略)。

    Args:
        doc_id: kb_document 表主键。
    """
    with _processing_lock:
        if doc_id in _processing:
            return
        _processing.add(doc_id)
    ingest_executor.submit(_run_ingest, doc_id)


def _run_ingest(doc_id: int) -> None:
    try:
        _ingest_document(doc_id)
    except Exception as e:  # noqa: BLE001 - 兜底,任何异常都要回写 failed
        logger.exception("文档 %s 入库异常", doc_id)
        _mark_failed(doc_id, f"未预期的异常: {e}")
    finally:
        with _processing_lock:
            _processing.discard(doc_id)


def _ingest_document(doc_id: int) -> None:
    """单个文档的完整入库流水线。"""
    # 延迟导入,避免 FastAPI 启动时就拉起重依赖
    from api.models import KbDocument
    from dataLoader import auto_load
    from dataLoader.loaders import get_doc_type, load_as_markdown
    from spliter import auto_split

    db = SessionLocal()
    try:
        doc = db.get(KbDocument, doc_id)
        if doc is None:
            logger.warning("文档 %s 不存在,跳过", doc_id)
            return
        kb = doc.kb
        if kb is None:
            _mark_failed(doc_id, "所属知识库不存在")
            return

        doc.status = "processing"
        doc.error_msg = ""
        db.commit()

        # 1) 确定实际切分器类型(splitter=auto 时按后缀自动选)
        if doc.splitter == "auto":
            doc_type = get_doc_type(doc.file_path)
        else:
            doc_type = doc.splitter

        # 2) 解析
        # 用户明确选择 markdown 标题切分时,非 markdown 格式先转成 markdown
        # (保留标题层级),再交给 MarkdownNodeParser 按标题切分;否则没有
        # 标题结构的文档(如 .docx/.pdf/.html)切分会退化成普通文本块。
        # 其余场景按后缀自动选 loader。
        if doc_type == "markdown":
            docs = load_as_markdown(doc.file_path)
        else:
            docs = auto_load(doc.file_path)
        if not docs:
            _mark_failed(doc_id, "解析结果为空(文件内容为空或格式不支持)")
            return

        # 统一 ref_doc_id,支持按文档粒度删除 Milvus 节点
        for d in docs:
            d.id_ = f"doc_{doc.id}"
            # 关键:file_name 必须强制写成源文件名(不能 setdefault)。
            # 解析器(SimpleDirectoryReader / MarkdownReader 等)会按落盘路径
            # 把 file_name 设成 uuid 文件名(如 '3bdb…a3.md'),setdefault 会
            # 保留这个无意义值,导致检索/大模型引用时看不到原始文件名。
            meta = dict(d.metadata or {})
            meta["file_name"] = doc.file_name or meta.get("file_name") or ""
            meta.setdefault("file_path", doc.file_path or "")
            d.metadata = meta

        # 3) 切分
        nodes = auto_split(
            docs,
            doc_type=doc_type,
            chunk_size=doc.chunk_size,
            chunk_overlap=doc.chunk_overlap,
        )
        if not nodes:
            _mark_failed(doc_id, "切分后无节点")
            return

        # 2.1) 为每个节点附加文档元数据(文件名 / 路径 / 章节),供检索引用
        _enrich_node_metadata(nodes, doc)

        # 3) 写入该知识库的 collection
        store = get_store(doc.kb_id)
        index = VectorStoreIndex.from_vector_store(vector_store=store)
        index.insert_nodes(nodes)

        # 4) 状态回写
        doc.status = "done"
        doc.node_count = len(nodes)
        db.commit()
        logger.info(
            "文档 %s(%s)入库完成: %d 节点 -> %s",
            doc.id, doc.file_name, len(nodes), kb.collection_name,
        )
    except Exception as e:  # noqa: BLE001
        db.rollback()
        _mark_failed(doc_id, str(e)[:1000])
    finally:
        db.close()


def _mark_failed(doc_id: int, error_msg: str) -> None:
    """把文档状态置为 failed(独立 session,保证一定写入)。"""
    from api.models import KbDocument

    db = SessionLocal()
    try:
        doc = db.get(KbDocument, doc_id)
        if doc is not None:
            doc.status = "failed"
            doc.error_msg = error_msg[:1000]
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("回写文档 %s 失败状态时出错", doc_id)
    finally:
        db.close()


def _enrich_node_metadata(nodes, doc) -> None:
    """
    给切分后的每个节点附加文档元数据,便于检索后引用来源。

    写入的元数据键:
    - ``file_name`` : 文档原始文件名
    - ``file_path`` : 文档落盘路径
    - ``section``   : 章节路径(取切分器已产出的 markdown 标题层级,
      如 ``"第二章 安装 > 2.2 安装步骤"``;无标题时留空)

    该函数只做原地修改,不改变节点内容与 embedding。
    """
    file_name = doc.file_name or ""
    file_path = doc.file_path or ""
    for node in nodes:
        meta = dict(node.metadata or {})
        # 文件名:强制覆盖为源文件名(切分器可能把 uuid 落盘名带进节点)
        meta["file_name"] = file_name or meta.get("file_name") or ""
        # 路径:保留已有(解析器已带 uuid 落盘路径)或补全
        meta.setdefault("file_path", file_path)
        # 章节:Markdown 等切分器会产出 header_path(如 '/第二章 安装/')
        section = _extract_section(meta)
        if section:
            meta["section"] = section
        node.metadata = meta


def _extract_section(meta: dict) -> str:
    """
    从节点元数据中提取可读的章节路径。

    兼容两种切分器的产出:
    - llama-index MarkdownNodeParser:``header_path``(形如 ``'/第二章 安装/'``)
    - 其它切分器:``Header 1`` / ``Header 2`` 等标题键

    Returns:
        形如 ``"第二章 安装 > 2.2 安装步骤"`` 的章节路径;提取不到返回空串。
    """
    header_path = str(meta.get("header_path") or "").strip()
    if header_path:
        parts = [p for p in header_path.strip("/").split("/") if p.strip()]
        return " > ".join(parts)

    # 兼容旧版/其它切分器:顺序收集 Header N
    headers = []
    for key, val in meta.items():
        if key.startswith("Header ") and val:
            headers.append((int(key.split()[-1]), str(val)))
    headers.sort()
    return " > ".join(v for _, v in headers) if headers else ""
