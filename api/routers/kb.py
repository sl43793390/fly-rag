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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.api_config import UPLOAD_DIR
from api.database import get_db
from api.models import ChatSession, KbDocument, KnowledgeBase
from api.schemas import (
    HYBRID_RANKERS,
    RETRIEVAL_MODES,
    SPLITTERS,
    KbCreate,
    KbOut,
    KbUpdate,
)
from api.services import (
    collection_name_for,
    delete_docstore,
    drop_kb_collection,
    get_store,
    invalidate_store,
)
from api.services.chat_service import chat_service
from api.user.auth import get_current_user, require_permission

#: 全组路由强制登录:未登录/token 失效(如服务重启)一律 401,
#: 前端据此跳转登录页;create/delete 再叠加细粒度权限校验。
router = APIRouter(
    prefix="/api/kb",
    tags=["知识库"],
    dependencies=[Depends(get_current_user)],
)


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


def _validate_retrieval_config(
    retrieval_mode: Optional[str] = None, hybrid_ranker: Optional[str] = None
) -> None:
    """校验检索方式与融合排序器的合法值(均大小写敏感)。"""
    if retrieval_mode is not None and retrieval_mode not in RETRIEVAL_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"不支持的检索方式: {retrieval_mode},"
                f"可选: {', '.join(RETRIEVAL_MODES)}"
            ),
        )
    if hybrid_ranker is not None and hybrid_ranker not in HYBRID_RANKERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"不支持的融合排序器: {hybrid_ranker},"
                f"可选: {', '.join(HYBRID_RANKERS)}"
            ),
        )


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
    _validate_retrieval_config(
        retrieval_mode=payload.retrieval_mode, hybrid_ranker=payload.hybrid_ranker
    )
    if db.query(KnowledgeBase).filter(KnowledgeBase.name == payload.name).first():
        raise HTTPException(status_code=400, detail=f"知识库名称已存在: {payload.name}")

    kb = KnowledgeBase(
        name=payload.name,
        description=payload.description or "",
        collection_name="",  # 先落库拿 id,再分配 collection 名
        splitter=payload.splitter,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        retrieval_mode=payload.retrieval_mode,
        hybrid_ranker=payload.hybrid_ranker,
        hybrid_ranker_params=payload.hybrid_ranker_params,
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
    if "retrieval_mode" in data or "hybrid_ranker" in data:
        _validate_retrieval_config(
            retrieval_mode=data.get("retrieval_mode"),
            hybrid_ranker=data.get("hybrid_ranker"),
        )
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
    # 检索配置(retrieval_mode / hybrid_ranker / hybrid_ranker_params)变更时:
    # 1) 丢弃缓存的 store,下次按新配置重建(融合排序器是 store 级参数);
    # 2) 使该知识库所有会话的 RAG 引擎失效(检索方式是检索器级参数)。
    # 注意:dense -> sparse/hybrid 只对新建 collection 生效(稀疏字段无法
    # 追加到已有 schema),已有数据的知识库需重建后才能用全文检索。
    if {"retrieval_mode", "hybrid_ranker", "hybrid_ranker_params"} & data.keys():
        invalidate_store(kb_id)
        chat_service.invalidate_kb(kb_id)
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

    # 1) 删 Milvus collection + 父子检索 Docstore(父/中块节点)
    drop_kb_collection(kb_id)
    delete_docstore(kb_id)
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
