"""
api.user.models
~~~~~~~~~~~~~~~
RBAC ORM 模型:User / Role / Permission / 关联表。

复用项目级 Base(见 api.database),保持单一 metadata,
这样 `Base.metadata.create_all` 可同时建出知识库与用户表。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    func,
)
from sqlalchemy.orm import relationship

from api.database import Base

# ------------------------------------------------------------
# 关联表(多对多)
# ------------------------------------------------------------
user_role = Table(
    "user_role",
    Base.metadata,
    Column(
        "user_id",
        BigInteger,
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        BigInteger,
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column(
        "role_id",
        BigInteger,
        ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        BigInteger,
        ForeignKey("permission.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(Base):
    """用户(登录账号)。"""

    __tablename__ = "user"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True, comment="登录名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    email = Column(String(128), nullable=False, default="", server_default="")
    status = Column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
        comment="状态: active/disabled",
    )
    remark = Column(String(255), nullable=False, default="", server_default="")
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        server_default=func.now(),
    )

    roles = relationship(
        "Role",
        secondary=user_role,
        lazy="selectin",
        back_populates="users",
    )


class Role(Base):
    """角色(权限集合的载体)。"""

    __tablename__ = "role"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, comment="角色名称")
    code = Column(String(64), nullable=False, unique=True, comment="角色编码")
    description = Column(
        String(255), nullable=False, default="", server_default=""
    )
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        server_default=func.now(),
    )

    users = relationship(
        "User",
        secondary=user_role,
        back_populates="roles",
    )
    permissions = relationship(
        "Permission",
        secondary=role_permission,
        lazy="selectin",
        back_populates="roles",
    )


class Permission(Base):
    """权限(原子操作许可,以 code 标识)。"""

    __tablename__ = "permission"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, comment="权限名称")
    code = Column(String(128), nullable=False, unique=True, comment="权限编码")
    description = Column(
        String(255), nullable=False, default="", server_default=""
    )
    created_at = Column(DateTime, default=datetime.now, server_default=func.now())

    roles = relationship(
        "Role",
        secondary=role_permission,
        back_populates="permissions",
    )
