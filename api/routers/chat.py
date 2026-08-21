"""
api.routers.chat
~~~~~~~~~~~~~~~~
对话 API:会话管理 + RAG / 纯 LLM 问答。

- 会话可归属某个知识库(mode=rag),也可不挂知识库(mode=chat,纯 LLM);
- 已登录用户(可选鉴权)的会话绑定到 ``owner_id``,下次登录仍可见;
- 历史消息持久化 MySQL,服务重启后自动恢复;
- RAG 回答附带引用来源(sources: text / score / file_name);
- 历史超过 30 轮自动压缩(详见 chat_service)。

注意:路由使用同步 def,FastAPI 自动放入线程池执行,
LLM 阻塞调用不会卡住事件循环。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import ChatMessage, ChatSession, KnowledgeBase
from api.schemas import (
    ChatRequest,
    ChatResponse,
    MessageOut,
    SessionCreate,
    SessionOut,
)
from api.services.chat_service import chat_service
from api.user.auth import get_optional_user
from api.user.models import User

router = APIRouter(prefix="/api/chat", tags=["对话"])


# ============================================================
# 工具
# ============================================================
def _get_session_or_404(db: Session, session_id: int) -> ChatSession:
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


def _resolve_owner(user: User | None) -> int | None:
    """登录用户的 owner_id;匿名为 None。"""
    return user.id if user is not None else None


def _touch_session(session_id: int) -> None:
    """刷新会话活跃时间(独立短 session,供 SSE 生成器收尾时调用)。"""
    from api.database import SessionLocal

    db = SessionLocal()
    try:
        s = db.get(ChatSession, session_id)
        if s is not None:
            s.updated_at = datetime.now()
            db.commit()
    finally:
        db.close()


# ============================================================
# 会话列表 / 创建 / 删除
# ============================================================
@router.get("/sessions", response_model=list[SessionOut], summary="会话列表(按所有者/知识库过滤)")
def list_sessions(
    kb_id: int | None = None,
    owner_id: int | None = None,
    include_anonymous: bool = True,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """
    - 未指定 owner_id 时,若已登录则按当前用户过滤;否则返回匿名会话;
    - ``include_anonymous=true`` 时,匿名会话也一并返回(默认 true)。
    """
    owner = owner_id if owner_id is not None else _resolve_owner(user)
    q = db.query(ChatSession, KnowledgeBase.name).outerjoin(
        KnowledgeBase, ChatSession.kb_id == KnowledgeBase.id
    )
    conditions = []
    if kb_id is not None:
        conditions.append(ChatSession.kb_id == kb_id)
    if owner is not None:
        if include_anonymous:
            conditions.append(
                or_(ChatSession.owner_id == owner, ChatSession.owner_id.is_(None))
            )
        else:
            conditions.append(ChatSession.owner_id == owner)
    if conditions:
        q = q.filter(*conditions)
    rows = q.order_by(ChatSession.updated_at.desc()).all()
    return [
        SessionOut(
            id=s.id,
            kb_id=s.kb_id,
            owner_id=s.owner_id,
            title=s.title,
            # 展示模式与运行时派生逻辑一致(kb_id 为准),避免标签与实际行为不符
            mode="rag" if s.kb_id is not None else "chat",
            kb_name=kb_name or "",
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s, kb_name in rows
    ]


@router.post("/sessions", response_model=SessionOut, status_code=201, summary="创建会话(RAG 或纯 LLM)")
def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    owner = _resolve_owner(user)

    # 模式校验:无 kb_id 视为 chat 模式(纯 LLM)
    mode = payload.mode or "rag"
    if payload.kb_id is None:
        mode = "chat"
    else:
        # 校验知识库存在
        kb = db.get(KnowledgeBase, payload.kb_id)
        if kb is None:
            raise HTTPException(status_code=404, detail="知识库不存在")
        mode = "rag"

    s = ChatSession(
        kb_id=payload.kb_id,
        owner_id=owner,
        title=payload.title or "新会话",
        mode=mode,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    kb_name = ""
    if s.kb_id is not None:
        kb = db.get(KnowledgeBase, s.kb_id)
        kb_name = kb.name if kb else ""
    return SessionOut(
        id=s.id,
        kb_id=s.kb_id,
        owner_id=s.owner_id,
        title=s.title,
        mode=s.mode,
        kb_name=kb_name,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.delete("/sessions/{session_id}", summary="删除会话(含消息)")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = _get_session_or_404(db, session_id)
    chat_service.invalidate_session(session_id)
    db.delete(s)
    db.commit()
    return {"detail": "会话已删除"}


@router.patch("/sessions/{session_id}", response_model=SessionOut, summary="重命名会话")
def rename_session(
    session_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    s = _get_session_or_404(db, session_id)
    title = (payload or {}).get("title")
    if title:
        s.title = title
        db.commit()
        db.refresh(s)
    kb_name = ""
    if s.kb_id is not None:
        kb = db.get(KnowledgeBase, s.kb_id)
        kb_name = kb.name if kb else ""
    return SessionOut(
        id=s.id,
        kb_id=s.kb_id,
        owner_id=s.owner_id,
        title=s.title,
        mode=s.mode,
        kb_name=kb_name,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


# ============================================================
# 消息
# ============================================================
@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageOut],
    summary="会话历史消息",
)
def list_messages(session_id: int, db: Session = Depends(get_db)):
    _get_session_or_404(db, session_id)
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return [MessageOut.model_validate(m) for m in msgs]


@router.post(
    "/sessions/{session_id}/chat",
    response_model=ChatResponse,
    summary="发送消息并获取回答(RAG 或纯 LLM)",
)
def chat(session_id: int, payload: ChatRequest, db: Session = Depends(get_db)):
    s = _get_session_or_404(db, session_id)

    # 模式与知识库校验
    # 关键:mode 以 kb_id 是否挂载为准派生,不信任可能过期/不一致的 s.mode 字符串。
    # 会话挂了知识库 → 强制 RAG(否则检索被跳过、知识库限制提示词失效);
    # 未挂知识库 → 纯 LLM 对话。
    kb_id = s.kb_id
    if kb_id is not None:
        mode = "rag"
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise HTTPException(status_code=404, detail="会话所属知识库不存在")
    else:
        mode = "chat"

    result = chat_service.chat(session_id, mode, kb_id, payload.message)

    # 刷新会话活跃时间(列表按 updated_at 排序)
    s.updated_at = datetime.now()
    db.commit()
    return ChatResponse(**result)


@router.post(
    "/sessions/{session_id}/chat/stream",
    summary="发送消息并流式获取回答(SSE,默认前端调用)",
)
def chat_stream(session_id: int, payload: ChatRequest, db: Session = Depends(get_db)):
    """
    流式对话接口(Server-Sent Events)。

    事件序列(每行 ``data: {json}\\n\\n``):
    1. ``{"event": "sources", "sources": [...]}`` 检索完成即推送(RAG);
    2. ``{"event": "delta", "text": "..."}`` 增量文本(多次);
    3. ``{"event": "done", "message_id", "compressed", "sources"}`` 结束;
    4. ``{"event": "error", "detail": "..."}`` 异常。

    注意:必须先完整校验会话再返回 StreamingResponse,
    保证 404 等错误仍走 JSON 错误协议而不是 SSE 流。
    """
    import json

    from fastapi.responses import StreamingResponse

    s = _get_session_or_404(db, session_id)

    # 模式与知识库校验(与 chat() 一致)
    # 以 kb_id 是否挂载为准派生 mode,不信任 s.mode 字符串,
    # 避免"挂了知识库的会话被当成纯 LLM 对话"导致检索被静默跳过。
    kb_id = s.kb_id
    if kb_id is not None:
        mode = "rag"
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise HTTPException(status_code=404, detail="会话所属知识库不存在")
    else:
        mode = "chat"

    def _sse():
        try:
            for event in chat_service.stream_chat(session_id, mode, kb_id, payload.message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            # 刷新会话活跃时间(独立 session,避免复用请求级 db)
            _touch_session(session_id)

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/clear", summary="清空会话消息")
def clear_session(session_id: int, db: Session = Depends(get_db)):
    _get_session_or_404(db, session_id)
    chat_service.clear_session(session_id)
    return {"detail": "会话已清空"}


@router.post("/sessions/{session_id}/compress", summary="手动触发历史压缩")
def compress_session(session_id: int, db: Session = Depends(get_db)):
    """便于运维手动触发压缩(参考 chat_service._maybe_compress_history)。"""
    _get_session_or_404(db, session_id)
    triggered = chat_service._maybe_compress_history(session_id, db)
    if triggered:
        chat_service.invalidate_session(session_id)
    return {"detail": "已触发压缩" if triggered else "未达到压缩阈值"}
