"""
api.user.auth
~~~~~~~~~~~~~
认证组件:密码哈希 / Token 签发 / FastAPI 鉴权依赖。

设计原则:仅使用 Python 标准库(hashlib / hmac / base64 / json / time),
不引入 PyJWT / passlib 等第三方依赖,部署零成本。

- 密码哈希:pbkdf2_hmac(sha256),200k 轮,格式 `pbkdf2_sha256$iter$salt$b64hash`
- Token:轻量 HS256 风格签名 JWT(header.payload.sig),
          payload 含 sub(user_id) / username / perms / exp
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.database import SessionLocal, get_db
from api.user.models import User

# ------------------------------------------------------------
# 配置(可通过环境变量覆盖)
# ------------------------------------------------------------
#: HS256 签名密钥,缺省从环境变量取,没有则用机器级随机量(进程重启即失效,
#: 仅用于本地开发)。生产请显式设置 AUTH_JWT_SECRET。
_JWT_SECRET: str = os.environ.get(
    "AUTH_JWT_SECRET", "kb-rag-default-secret-change-me-in-production"
)
#: Token 有效期(秒),默认 12 小时。
_JWT_EXPIRES: int = int(os.environ.get("AUTH_JWT_EXPIRES", str(12 * 3600)))
#: pbkdf2 迭代轮数
_PBKDF2_ITER: int = 200000

_bearer = HTTPBearer(auto_error=False)


# ============================================================
# 密码哈希
# ============================================================
def _b64encode(b: bytes) -> str:
    """URL-safe base64 编码(去掉填充的 =)。"""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    """URL-safe base64 解码(自动补齐填充)。"""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_password(raw: str) -> str:
    """
    生成密码哈希(每次随机盐)。

    Args:
        raw: 明文密码。

    Returns:
        形如 ``pbkdf2_sha256$200000$<salt>$<hash>`` 的字符串。
    """
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", raw.encode("utf-8"), salt, _PBKDF2_ITER
    )
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITER,
        _b64encode(salt),
        _b64encode(digest),
    )


def verify_password(raw: str, hashed: str) -> bool:
    """校验明文密码是否与哈希匹配。"""
    try:
        algo, iter_str, salt_b64, hash_b64 = hashed.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac(
            "sha256", raw.encode("utf-8"), salt, iterations
        )
        # 常量时间比较,防侧信道
        return hmac.compare_digest(digest, expected)
    except (ValueError, AttributeError, TypeError):
        return False


# ============================================================
# Token(HS256 风格自实现 JWT)
# ============================================================
def _sign(payload_b64: str) -> str:
    """对 payload 的 base64 串做 HMAC-SHA256 签名。"""
    sig = hmac.new(
        _JWT_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).digest()
    return _b64encode(sig)


def create_access_token(user: User, permissions: List[str]) -> str:
    """
    生成 access token。

    Args:
        user: 用户 ORM 实例。
        permissions: 该用户扁平后的权限码列表。

    Returns:
        签名后的 JWT 字符串。
    """
    payload = {
        "sub": user.id,
        "username": user.username,
        "perms": permissions,
        "exp": int(time.time()) + _JWT_EXPIRES,
    }
    payload_b64 = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    header_b64 = _b64encode(
        json.dumps(
            {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    sig = _sign(payload_b64)
    return f"{header_b64}.{payload_b64}.{sig}"


def decode_token(token: str) -> dict:
    """
    解码并验证 token。

    Raises:
        HTTPException(401): token 格式错误、签名不符或已过期。
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="token 格式错误")
    header_b64, payload_b64, sig = parts
    expected_sig = _sign(payload_b64)
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=401, detail="token 签名无效")
    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"token 解析失败: {exc}")
    exp = payload.get("exp")
    if exp is not None and int(time.time()) > int(exp):
        raise HTTPException(status_code=401, detail="token 已过期,请重新登录")
    return payload


# ============================================================
# FastAPI 依赖
# ============================================================
def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    解析当前请求的用户,token 缺失/无效则 401。

    用法:
        @router.get(...)
        def handler(user: User = Depends(get_current_user)):
            ...
    """
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="token 无 sub")
    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def require_permission(code: str):
    """
    生成一个 FastAPI 依赖:要求当前用户拥有指定权限码。

    超级管理员(其角色中含 code=admin)直接放行,无需逐权限检查。

    用法:
        @router.get("/users", dependencies=[Depends(require_permission("user:read"))])
        def list_users(...): ...
    """

    def _checker(user: User = Depends(get_current_user)) -> User:
        codes: set = set()
        for r in user.roles:
            # admin 角色直接全权
            if r.code == "admin":
                return user
            for p in r.permissions:
                codes.add(p.code)
        if code not in codes:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足,缺少权限: {code}",
            )
        return user

    return _checker


def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    可选鉴权:有合法 token 则返回用户,否则返回 None。

    用于聊天等接口:登录与否都可访问,登录后历史会按用户归属。
    """
    if creds is None or not creds.credentials:
        return None
    try:
        payload = decode_token(creds.credentials)
    except HTTPException:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    user = db.get(User, int(user_id))
    if user is None or user.status != "active":
        return None
    return user


def collect_permission_codes(user: User) -> List[str]:
    """收集用户扁平后的所有权限码(admin 视为拥有全部)。"""
    codes: set = set()
    for r in user.roles:
        if r.code == "admin":
            # admin 视为通配权限(返回特殊标记,前端可隐藏/禁用鉴权)
            return ["*"]
        for p in r.permissions:
            codes.add(p.code)
    return sorted(codes)
