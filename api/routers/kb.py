"""
api.routers.kb
~~~~~~~~~~~~~~
知识库管理 API。

- 每个知识库对应一个 Milvus collection(kb_{id}),创建时分配,删除时同步 drop;
- 切分参数(splitter / chunk_size / chunk_overlap)为知识库默认值,
  上传文档时可覆盖。
"""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.api_config import UPLOAD_DIR
from api.database import get_db
from api.models import ChatSession, KbDocument, KnowledgeBase
from api.schemas import SPLITTERS, KbCreate, KbOut, KbUpdate
from api.services import collection_name_for, drop_kb_collection, get_store
from api.services.chat_service import chat_service
from api.user.auth import require_permission

router = APIRouter(prefix="/api/kb", tags=["知识库"])


def _kb_stats(db: Session, kb_id: int) -> dict:
    """聚合知识库的文档统计(总数 / 完成数 / 节点数)。"""
    row = (
        db.query(
            func.count(KbDocument.id),
            func.sum(func.ifnull(KbDocument.node_count, 0)),
        )
        .filter(KbDocument.kb_id == kb_id)
        .one()
    )
    done = (
        db.query(func.count(KbDocument.id))
        .filter(KbDocument.kb_id == kb_id, KbDocument.status == "done")
        .scalar()
        or 0
    )
    return {
        "doc_count": int(row[0] or 0),
        "done_doc_count": int(done),
        "node_count": int(row[1] or 0),
    }


def _kb_to_out(db: Session, kb: KnowledgeBase) -> KbOut:
    out = KbOut.model_validate(kb)
    for k, v in _kb_stats(db, kb.id).items():
        setattr(out, k, v)
    return out


def _validate_splitter(splitter: str) -> str:
    if splitter not in SPLITTERS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的切分器: {splitter},可选: {', '.join(SPLITTERS)}",
        )
    return splitter


@router.get("", response_model=list[KbOut], summary="知识库列表")
def list_kbs(db: Session = Depends(get_db)):
    kbs = db.query(KnowledgeBase).order_by(KnowledgeBase.id.desc()).all()
    return [_kb_to_out(db, kb) for kb in kbs]


@router.post(
    "",
    response_model=KbOut,
    status_code=201,
    summary="创建知识库",
    dependencies=[Depends(require_permission("kb:create"))],
)
def create_kb(payload: KbCreate, db: Session = Depends(get_db)):
    _validate_splitter(payload.splitter)
    if db.query(KnowledgeBase).filter(KnowledgeBase.name == payload.name).first():
        raise HTTPException(status_code=400, detail=f"知识库名称已存在: {payload.name}")

    kb = KnowledgeBase(
        name=payload.name,
        description=payload.description or "",
        collection_name="",  # 先落库拿 id,再分配 collection 名
        splitter=payload.splitter,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    kb.collection_name = collection_name_for(kb.id)
    db.commit()
    db.refresh(kb)
    return _kb_to_out(db, kb)


@router.get("/{kb_id}", response_model=KbOut, summary="知识库详情")
def get_kb(kb_id: int, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return _kb_to_out(db, kb)


@router.put("/{kb_id}", response_model=KbOut, summary="更新知识库")
def update_kb(kb_id: int, payload: KbUpdate, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    data = payload.model_dump(exclude_unset=True)
    if "splitter" in data and data["splitter"] is not None:
        _validate_splitter(data["splitter"])
    if "name" in data and data["name"]:
        exists = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.name == data["name"], KnowledgeBase.id != kb_id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail=f"知识库名称已存在: {data['name']}")

    for k, v in data.items():
        if v is not None:
            setattr(kb, k, v)
    db.commit()
    db.refresh(kb)
    return _kb_to_out(db, kb)


@router.delete(
    "/{kb_id}",
    summary="删除知识库(连带 Milvus collection / 上传文件 / 会话)",
    dependencies=[Depends(require_permission("kb:delete"))],
)
def delete_kb(kb_id: int, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 1) 删 Milvus collection
    drop_kb_collection(kb_id)
    # 2) 使该知识库下所有会话的引擎缓存失效
    chat_service.invalidate_kb(kb_id)
    # 3) 删上传目录
    kb_upload_dir = Path(UPLOAD_DIR) / f"kb_{kb_id}"
    if kb_upload_dir.exists():
        shutil.rmtree(kb_upload_dir, ignore_errors=True)
    # 4) 删 DB(外键级联: kb_document / chat_session / chat_message)
    db.delete(kb)
    db.commit()
    return {"detail": f"知识库 '{kb.name}' 已删除"}


@router.get("/{kb_id}/sessions", summary="知识库下的会话列表(便捷接口)")
def kb_sessions(kb_id: int, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.kb_id == kb_id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "kb_id": s.kb_id,
            "title": s.title,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        }
        for s in rows
    ]
