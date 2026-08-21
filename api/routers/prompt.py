"""
api.routers.prompt
~~~~~~~~~~~~~~~~~~
提示词模版 API:用户保存的常用提问模版(按 owner 隔离)。

- 列表支持按标题关键字搜索(``?keyword=``);
- 创建/编辑/删除仅作用于当前登录用户自己的模版;
- 聊天页「保存为提示词模版」与提示词管理页共用本组接口。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import PromptTemplate
from api.schemas import PromptCreate, PromptOut, PromptUpdate
from api.user.auth import get_current_user
from api.user.models import User

router = APIRouter(prefix="/api/prompts", tags=["提示词"])


def _get_owned_or_404(db: Session, prompt_id: int, user: User) -> PromptTemplate:
    p = db.get(PromptTemplate, prompt_id)
    if p is None or p.owner_id != user.id:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return p


@router.get("", response_model=list[PromptOut], summary="提示词列表(按标题搜索)")
def list_prompts(
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(PromptTemplate).filter(PromptTemplate.owner_id == user.id)
    if keyword:
        q = q.filter(PromptTemplate.title.contains(keyword))
    return q.order_by(PromptTemplate.updated_at.desc()).all()


@router.post("", response_model=PromptOut, status_code=201, summary="新建提示词")
def create_prompt(
    payload: PromptCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = PromptTemplate(owner_id=user.id, title=payload.title, content=payload.content)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.put("/{prompt_id}", response_model=PromptOut, summary="编辑提示词")
def update_prompt(
    prompt_id: int,
    payload: PromptUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = _get_owned_or_404(db, prompt_id, user)
    if payload.title is not None:
        p.title = payload.title
    if payload.content is not None:
        p.content = payload.content
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{prompt_id}", summary="删除提示词")
def delete_prompt(
    prompt_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = _get_owned_or_404(db, prompt_id, user)
    db.delete(p)
    db.commit()
    return {"detail": "提示词已删除"}
