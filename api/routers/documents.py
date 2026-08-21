"""
api.routers.documents
~~~~~~~~~~~~~~~~~~~~~
文档上传 / 状态查询 / 删除 / 失败重试 API。

上传流程:
    1) 校验扩展名与大小 -> 落盘 uploads/kb_{id}/ -> 写 MySQL(pending);
    2) 提交后台线程池(解析 -> 切分 -> 嵌入 -> 写 Milvus kb_{id});
    3) 前端轮询 GET /api/kb/{kb_id}/documents 展示 pending/processing/done/failed。

删除文档:
    按 Document.ref_doc_id(doc_{id})从 Milvus 删除对应节点,再删文件与记录。
"""
import logging
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.api_config import MAX_UPLOAD_SIZE, UPLOAD_DIR
from api.database import get_db
from api.models import KbDocument, KnowledgeBase
from api.schemas import SPLITTERS, DocumentOut, UploadResult
from api.services import submit_ingest
from dataLoader.loaders import SUPPORTED_EXTS

logger = logging.getLogger("api.documents")

router = APIRouter(prefix="/api/kb", tags=["文档"])


def _get_kb_or_404(db: Session, kb_id: int) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


@router.post(
    "/{kb_id}/documents",
    response_model=UploadResult,
    status_code=201,
    summary="批量上传文档(multipart,可指定切分参数)",
)
async def upload_documents(
    kb_id: int,
    files: List[UploadFile] = File(..., description="多个文件"),
    splitter: str = Form("auto", description="切分器:auto/sentence/token/simple/markdown/html/json"),
    chunk_size: int = Form(1024, ge=100, le=8192),
    chunk_overlap: int = Form(200, ge=0, le=2048),
    db: Session = Depends(get_db),
):
    kb = _get_kb_or_404(db, kb_id)
    if splitter not in SPLITTERS:
        raise HTTPException(status_code=400, detail=f"不支持的切分器: {splitter}")

    kb_dir = Path(UPLOAD_DIR) / f"kb_{kb_id}"
    kb_dir.mkdir(parents=True, exist_ok=True)

    accepted: List[KbDocument] = []
    rejected: List[dict] = []

    for f in files:
        name = f.filename or "unnamed"
        ext = Path(name).suffix.lower()

        # 校验扩展名
        if ext not in SUPPORTED_EXTS:
            rejected.append({"file_name": name, "reason": f"不支持的格式: {ext or '(无后缀)'}"})
            await f.close()
            continue

        # 读取并校验大小
        content = await f.read()
        await f.close()
        if len(content) > MAX_UPLOAD_SIZE:
            rejected.append(
                {
                    "file_name": name,
                    "reason": f"超过单文件上限 {MAX_UPLOAD_SIZE // 1024 // 1024}MB",
                }
            )
            continue
        if len(content) == 0:
            rejected.append({"file_name": name, "reason": "空文件"})
            continue

        # 落盘(uuid 文件名,避免中文 / 特殊字符 / 重名冲突)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        save_path = kb_dir / safe_name
        save_path.write_bytes(content)

        doc = KbDocument(
            kb_id=kb_id,
            file_name=name,
            file_path=str(save_path),
            file_ext=ext,
            file_size=len(content),
            status="pending",
            splitter=splitter,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        db.add(doc)
        accepted.append(doc)

    db.commit()
    for doc in accepted:
        db.refresh(doc)
        submit_ingest(doc.id)

    logger.info(
        "知识库 %s(%s)上传: 接收 %d, 拒绝 %d",
        kb_id, kb.name, len(accepted), len(rejected),
    )
    return UploadResult(
        total=len(files),
        accepted=len(accepted),
        rejected=rejected,
        documents=[DocumentOut.model_validate(d) for d in accepted],
    )


@router.get("/{kb_id}/documents", response_model=list[DocumentOut], summary="文档列表(含解析状态)")
def list_documents(kb_id: int, db: Session = Depends(get_db)):
    _get_kb_or_404(db, kb_id)
    docs = (
        db.query(KbDocument)
        .filter(KbDocument.kb_id == kb_id)
        .order_by(KbDocument.id.desc())
        .all()
    )
    return [DocumentOut.model_validate(d) for d in docs]


@router.delete("/documents/{doc_id}", summary="删除文档(Milvus 节点 + 文件 + 记录)")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    from api.services import get_store

    doc = db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 1) 从 Milvus 删除该文档的所有节点(按 ref_doc_id)
    store = get_store(doc.kb_id)
    try:
        store.delete(ref_doc_id=f"doc_{doc.id}")
    except Exception as e:  # noqa: BLE001 - collection 不存在等情况不阻断删除
        logger.warning("删除 Milvus 节点失败(可能集合为空): %s", e)

    # 2) 删落盘文件
    try:
        p = Path(doc.file_path)
        if p.exists():
            p.unlink()
    except OSError as e:
        logger.warning("删除文件失败: %s", e)

    # 3) 删 DB 记录
    db.delete(doc)
    db.commit()
    return {"detail": f"文档 '{doc.file_name}' 已删除"}


@router.post("/documents/{doc_id}/retry", response_model=DocumentOut, summary="重新解析失败文档")
def retry_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status == "processing":
        raise HTTPException(status_code=400, detail="该文档正在解析中")
    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=400, detail="源文件已不存在,请重新上传")

    doc.status = "pending"
    doc.error_msg = ""
    db.commit()
    submit_ingest(doc.id)
    db.refresh(doc)
    return DocumentOut.model_validate(doc)
