"""
api.user.services
~~~~~~~~~~~~~~~~~
用户/角色/权限业务逻辑 + 默认数据初始化。

公开函数:
- ensure_default_admin():        首次启动时自动创建 admin / admin123 与内置角色/权限
- authenticate(username, pwd):   登录校验,返回 User 或 None
- assign_user_roles(db, uid, ids):重置用户的角色
- assign_role_permissions(db, rid, ids):重置角色的权限
"""
import logging
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.user.auth import make_password, verify_password
from api.user.models import Permission, Role, User

logger = logging.getLogger("api.user")

#: 内置权限清单(code, name, description),与 sql/init.sql 对齐
DEFAULT_PERMISSIONS: list[tuple[str, str, str]] = [
    ("user:read", "用户查看", "查看用户列表"),
    ("user:create", "用户创建", "创建用户"),
    ("user:update", "用户更新", "更新用户/分配角色"),
    ("user:delete", "用户删除", "删除用户"),
    ("role:read", "角色查看", "查看角色列表"),
    ("role:create", "角色创建", "创建角色"),
    ("role:update", "角色更新", "更新角色/分配权限"),
    ("role:delete", "角色删除", "删除角色"),
    ("perm:read", "权限查看", "查看权限列表"),
    ("kb:create", "知识库创建", "创建知识库"),
    ("kb:delete", "知识库删除", "删除知识库"),
]

#: 内置角色清单(code, name, description)
DEFAULT_ROLES: list[tuple[str, str, str]] = [
    ("admin", "超级管理员", "拥有全部权限"),
    ("kb_manager", "知识库管理员", "知识库/文档管理权限"),
    ("chat_user", "对话用户", "可使用 RAG 与纯 LLM 对话"),
]

#: 内置角色 -> 权限码映射
DEFAULT_ROLE_PERMS: dict[str, list[str]] = {
    "admin": [c for c, _, _ in DEFAULT_PERMISSIONS],
    "kb_manager": ["role:read", "perm:read", "kb:create", "kb:delete"],
    "chat_user": [],
}


# ============================================================
# 默认数据初始化
# ============================================================
def ensure_default_admin() -> None:
    """
    首次启动时自动初始化内置角色/权限/超级管理员。

    幂等:已存在则跳过。在 api.main lifespan 中调用。
    """
    from api.database import SessionLocal

    db = SessionLocal()
    try:
        # 1) 权限
        for code, name, desc in DEFAULT_PERMISSIONS:
            if db.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none() is None:
                db.add(Permission(name=name, code=code, description=desc))
        db.flush()

        # 2) 角色
        for code, name, desc in DEFAULT_ROLES:
            if db.execute(select(Role).where(Role.code == code)).scalar_one_or_none() is None:
                db.add(Role(name=name, code=code, description=desc))
        db.flush()

        # 3) 角色-权限
        for role_code, perm_codes in DEFAULT_ROLE_PERMS.items():
            role = db.execute(select(Role).where(Role.code == role_code)).scalar_one()
            wanted_perm_ids = {
                p.id
                for p in db.execute(
                    select(Permission).where(Permission.code.in_(perm_codes))
                ).scalars().all()
            } if perm_codes else set()
            # 替换式赋值
            existing = {p.id for p in role.permissions}
            to_add = wanted_perm_ids - existing
            if to_add:
                perms = db.execute(
                    select(Permission).where(Permission.id.in_(to_add))
                ).scalars().all()
                role.permissions.extend(perms)
        db.flush()

        # 4) 超级管理员账号
        admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
        if admin is None:
            admin = User(
                username="admin",
                password_hash=make_password("admin123"),
                email="",
                status="active",
                remark="内置超级管理员,初始密码 admin123,登录后请立即修改",
            )
            db.add(admin)
            db.flush()
            admin_role = db.execute(select(Role).where(Role.code == "admin")).scalar_one()
            admin.roles.append(admin_role)
            logger.warning("已创建内置管理员:admin / admin123(请尽快修改密码)")
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


# ============================================================
# 鉴权 / 业务
# ============================================================
def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """
    登录校验。

    Returns:
        用户实例;用户名/密码错误或账号禁用时返回 None。
    """
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if user.status != "active":
        return None
    return user


def assign_user_roles(db: Session, user: User, role_ids: List[int]) -> None:
    """替换式重置用户角色(以 role_id 列表为准)。"""
    roles: List[Role] = (
        db.execute(select(Role).where(Role.id.in_(role_ids))).scalars().all()
        if role_ids else []
    )
    user.roles = roles
    db.flush()


def assign_role_permissions(db: Session, role: Role, perm_ids: List[int]) -> None:
    """替换式重置角色权限。"""
    perms: List[Permission] = (
        db.execute(select(Permission).where(Permission.id.in_(perm_ids))).scalars().all()
        if perm_ids else []
    )
    role.permissions = perms
    db.flush()


def count_role_users(db: Session, role_id: int) -> int:
    """统计角色下的用户数。"""
    role = db.get(Role, role_id)
    if role is None:
        return 0
    return len(role.users) if role.users else 0
