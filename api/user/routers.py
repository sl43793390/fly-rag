"""
api.user.routers
~~~~~~~~~~~~~~~~
认证 + 用户/角色/权限 CRUD 路由。

所有管理类接口都通过 `Depends(require_permission(...))` 强制 RBAC 校验。
登录接口 / 当前用户接口仅需合法 token(`Depends(get_current_user)`)。

统一前缀:`/api`
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.user import services
from api.user.auth import (
    collect_permission_codes,
    create_access_token,
    get_current_user,
    make_password,
    require_permission,
    verify_password,
)
from api.user.models import Permission, Role, User
from api.user.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    PermissionCreate,
    PermissionOut,
    ResetPasswordRequest,
    RoleAssignPermissions,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserAssignRoles,
    UserCreate,
    UserOut,
    UserUpdate,
    UserWithPermissions,
)

router = APIRouter(prefix="/api", tags=["用户与权限"])


# ============================================================
# 工具
# ============================================================
def _is_admin(user: User) -> bool:
    """是否为超级管理员(拥有 code=admin 角色,绕过所有权限校验)。"""
    return any(r.code == "admin" for r in user.roles)


def _user_to_out(user: User) -> UserOut:
    """User -> UserOut(含 roles + 各 role 的 permissions)。"""
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email or "",
        status=user.status,
        remark=user.remark or "",
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
        roles=[
            RoleOut(
                id=r.id,
                name=r.name,
                code=r.code,
                description=r.description or "",
                permissions=[
                    PermissionOut(
                        id=p.id, name=p.name, code=p.code, description=p.description
                    )
                    for p in r.permissions
                ],
            )
            for r in user.roles
        ],
    )


def _role_to_out(db: Session, role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        code=role.code,
        description=role.description or "",
        permissions=[
            PermissionOut(
                id=p.id, name=p.name, code=p.code, description=p.description
            )
            for p in role.permissions
        ],
        user_count=services.count_role_users(db, role.id),
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


# ============================================================
# 登录 / 当前用户 / 修改密码
# ============================================================
@router.post("/auth/login", response_model=LoginResponse, summary="用户登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = services.authenticate(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user.last_login_at = datetime.now()
    db.commit()
    db.refresh(user)
    perms = collect_permission_codes(user)
    token = create_access_token(user, perms)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserWithPermissions(
            id=user.id,
            username=user.username,
            email=user.email or "",
            status=user.status,
            roles=[
                RoleOut(
                    id=r.id,
                    name=r.name,
                    code=r.code,
                    description=r.description or "",
                    permissions=[
                        PermissionOut(
                            id=p.id, name=p.name, code=p.code, description=p.description
                        )
                        for p in r.permissions
                    ],
                )
                for r in user.roles
            ],
            permissions=perms,
        ),
    )


@router.get("/auth/me", response_model=UserWithPermissions, summary="当前登录用户")
def me(user: User = Depends(get_current_user)):
    return UserWithPermissions(
        id=user.id,
        username=user.username,
        email=user.email or "",
        status=user.status,
        roles=[
            RoleOut(
                id=r.id,
                name=r.name,
                code=r.code,
                description=r.description or "",
                permissions=[
                    PermissionOut(
                        id=p.id, name=p.name, code=p.code, description=p.description
                    )
                    for p in r.permissions
                ],
            )
            for r in user.roles
        ],
        permissions=collect_permission_codes(user),
    )


@router.post("/auth/change-password", summary="修改自己的密码")
def change_my_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = make_password(payload.new_password)
    db.commit()
    return {"detail": "密码已修改,请重新登录"}


# ============================================================
# 用户管理
# ============================================================
@router.get(
    "/users",
    response_model=list[UserOut],
    summary="用户列表",
    dependencies=[Depends(require_permission("user:read"))],
)
def list_users(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    用户列表。

    非超级管理员看不到拥有「超级管理员」角色的用户
    (避免普通管理员用户被查看 / 改密 / 删除)。
    """
    users = db.execute(select(User).order_by(User.id.asc())).scalars().all()
    if not _is_admin(user):
        users = [u for u in users if "admin" not in {r.code for r in u.roles}]
    return [_user_to_out(u) for u in users]


@router.post(
    "/users",
    response_model=UserOut,
    status_code=201,
    summary="创建用户",
    dependencies=[Depends(require_permission("user:create"))],
)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"用户名已存在: {payload.username}")
    user = User(
        username=payload.username,
        password_hash=make_password(payload.password),
        email=payload.email or "",
        status="active",
        remark=payload.remark or "",
    )
    db.add(user)
    db.flush()
    services.assign_user_roles(db, user, payload.role_ids)
    db.commit()
    db.refresh(user)
    return _user_to_out(user)


@router.get(
    "/users/{user_id}",
    response_model=UserOut,
    summary="用户详情",
    dependencies=[Depends(require_permission("user:read"))],
)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_to_out(user)


@router.put(
    "/users/{user_id}",
    response_model=UserOut,
    summary="更新用户",
    dependencies=[Depends(require_permission("user:update"))],
)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in ("active", "disabled"):
        raise HTTPException(status_code=400, detail="状态只能为 active/disabled")
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    db.refresh(user)
    return _user_to_out(user)


@router.delete(
    "/users/{user_id}",
    summary="删除用户",
    dependencies=[Depends(require_permission("user:delete"))],
)
def delete_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户自己")
    if "admin" in {r.code for r in target.roles}:
        # 防止误删最后一个管理员
        admin_users = [
            u for u in
            db.execute(select(User)).scalars().all()
            if any(r.code == "admin" for r in u.roles)
        ]
        if len(admin_users) <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个超级管理员")
    db.delete(target)
    db.commit()
    return {"detail": f"用户 '{target.username}' 已删除"}


@router.put(
    "/users/{user_id}/roles",
    response_model=UserOut,
    summary="分配用户角色(替换式)",
    dependencies=[Depends(require_permission("user:update"))],
)
def assign_user_roles_api(
    user_id: int,
    payload: UserAssignRoles,
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    services.assign_user_roles(db, user, payload.role_ids)
    db.commit()
    db.refresh(user)
    return _user_to_out(user)


@router.put(
    "/users/{user_id}/password",
    summary="管理员重置用户密码",
    dependencies=[Depends(require_permission("user:update"))],
)
def reset_user_password(
    user_id: int,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = make_password(payload.new_password)
    db.commit()
    return {"detail": f"用户 '{user.username}' 的密码已重置"}


# ============================================================
# 角色管理
# ============================================================
@router.get(
    "/roles",
    response_model=list[RoleOut],
    summary="角色列表",
    dependencies=[Depends(require_permission("role:read"))],
)
def list_roles(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    角色列表。

    非超级管理员看不到「超级管理员」(admin)内置角色,
    也就无法在分配角色 / 分配权限时触碰管理员角色。
    """
    roles = db.execute(select(Role).order_by(Role.id.asc())).scalars().all()
    if not _is_admin(user):
        roles = [r for r in roles if r.code != "admin"]
    return [_role_to_out(db, r) for r in roles]


@router.post(
    "/roles",
    response_model=RoleOut,
    status_code=201,
    summary="创建角色",
    dependencies=[Depends(require_permission("role:create"))],
)
def create_role(payload: RoleCreate, db: Session = Depends(get_db)):
    if db.execute(select(Role).where(Role.code == payload.code)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"角色编码已存在: {payload.code}")
    role = Role(
        name=payload.name,
        code=payload.code,
        description=payload.description or "",
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _role_to_out(db, role)


@router.get(
    "/roles/{role_id}",
    response_model=RoleOut,
    summary="角色详情",
    dependencies=[Depends(require_permission("role:read"))],
)
def get_role(role_id: int, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return _role_to_out(db, role)


@router.put(
    "/roles/{role_id}",
    response_model=RoleOut,
    summary="更新角色",
    dependencies=[Depends(require_permission("role:update"))],
)
def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(role, k, v)
    db.commit()
    db.refresh(role)
    return _role_to_out(db, role)


@router.delete(
    "/roles/{role_id}",
    summary="删除角色",
    dependencies=[Depends(require_permission("role:delete"))],
)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.code in ("admin", "kb_manager", "chat_user"):
        raise HTTPException(status_code=400, detail="内置角色不允许删除")
    if role.users:
        raise HTTPException(
            status_code=400,
            detail=f"该角色下仍有 {len(role.users)} 个用户,请先解绑",
        )
    db.delete(role)
    db.commit()
    return {"detail": f"角色 '{role.name}' 已删除"}


@router.put(
    "/roles/{role_id}/permissions",
    response_model=RoleOut,
    summary="分配角色权限(替换式)",
    dependencies=[Depends(require_permission("role:update"))],
)
def assign_role_permissions_api(
    role_id: int,
    payload: RoleAssignPermissions,
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    services.assign_role_permissions(db, role, payload.permission_ids)
    db.commit()
    db.refresh(role)
    return _role_to_out(db, role)


# ============================================================
# 权限管理
# ============================================================
@router.get(
    "/permissions",
    response_model=list[PermissionOut],
    summary="权限列表",
    dependencies=[Depends(require_permission("perm:read"))],
)
def list_permissions(db: Session = Depends(get_db)):
    perms = db.execute(select(Permission).order_by(Permission.id.asc())).scalars().all()
    return [
        PermissionOut(
            id=p.id, name=p.name, code=p.code, description=p.description
        )
        for p in perms
    ]


@router.post(
    "/permissions",
    response_model=PermissionOut,
    status_code=201,
    summary="创建权限",
    dependencies=[Depends(require_permission("role:update"))],
)
def create_permission(payload: PermissionCreate, db: Session = Depends(get_db)):
    if db.execute(select(Permission).where(Permission.code == payload.code)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"权限编码已存在: {payload.code}")
    perm = Permission(
        name=payload.name,
        code=payload.code,
        description=payload.description or "",
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return PermissionOut(
        id=perm.id, name=perm.name, code=perm.code, description=perm.description
    )


@router.delete(
    "/permissions/{perm_id}",
    summary="删除权限",
    dependencies=[Depends(require_permission("role:update"))],
)
def delete_permission(perm_id: int, db: Session = Depends(get_db)):
    perm = db.get(Permission, perm_id)
    if perm is None:
        raise HTTPException(status_code=404, detail="权限不存在")
    if perm.code in {
        c for c, _, _ in services.DEFAULT_PERMISSIONS
    }:
        raise HTTPException(status_code=400, detail="内置权限不允许删除")
    db.delete(perm)
    db.commit()
    return {"detail": f"权限 '{perm.name}' 已删除"}
