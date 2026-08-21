"""
api.user.schemas
~~~~~~~~~~~~~~~~
用户/角色/权限的 Pydantic 请求与响应模型。
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------
# 通用
# ------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


# ------------------------------------------------------------
# 权限
# ------------------------------------------------------------
class PermissionOut(BaseModel):
    id: int
    name: str
    code: str
    description: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PermissionCreate(BaseModel):
    name: str = Field(..., max_length=64)
    code: str = Field(..., max_length=128)
    description: str = Field("", max_length=255)


# ------------------------------------------------------------
# 角色
# ------------------------------------------------------------
class RoleOut(BaseModel):
    id: int
    name: str
    code: str
    description: str
    permissions: List[PermissionOut] = []
    user_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoleCreate(BaseModel):
    name: str = Field(..., max_length=64)
    code: str = Field(..., max_length=64)
    description: str = Field("", max_length=255)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    description: Optional[str] = Field(None, max_length=255)


class RoleAssignPermissions(BaseModel):
    permission_ids: List[int] = Field(default_factory=list)


# ------------------------------------------------------------
# 用户
# ------------------------------------------------------------
class UserOut(BaseModel):
    id: int
    username: str
    email: str
    status: str
    remark: str
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    roles: List[RoleOut] = []

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    email: str = Field("", max_length=128)
    remark: str = Field("", max_length=255)
    role_ids: List[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    email: Optional[str] = Field(None, max_length=128)
    remark: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = None


class UserAssignRoles(BaseModel):
    role_ids: List[int] = Field(default_factory=list)


class UserWithPermissions(BaseModel):
    """登录响应:用户信息 + 扁平权限码列表。"""

    id: int
    username: str
    email: str
    status: str
    roles: List[RoleOut] = []
    permissions: List[str] = []

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserWithPermissions
