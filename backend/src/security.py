"""认证与权限（JWT Bearer + PBKDF2 密码哈希 + 固定三角色 + 审计记录）

实现约束（架构决策，禁止偏离）：
- JWT HS256 自实现，仅用标准库 hmac/hashlib/base64/json，不引入新依赖；
  exp 7 天；secret 取环境变量 JWT_SECRET，默认值仅用于本地开发，
  **生产环境必须通过环境变量更换 JWT_SECRET**。
- 密码：hashlib.pbkdf2_hmac('sha256', pwd, salt, 100_000) + 16 字节随机 salt，
  存储格式 `pbkdf2$<salt_hex>$<hash_hex>`；明文密码不出现在任何响应体/日志中。
- 固定三角色：admin（管理）/ editor（可编辑）/ viewer（只读），不做动态权限表。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db

# 默认值仅供本地开发；生产必须设置环境变量 JWT_SECRET 更换
JWT_SECRET = os.getenv("JWT_SECRET", "core-holdings-local-dev-secret-change-in-production")
JWT_EXPIRE_DAYS = 7

ROLES = ("admin", "editor", "viewer")
EDITOR_ROLES = ("admin", "editor")

bearer = HTTPBearer(auto_error=False)


# ============================================================
# 密码哈希（PBKDF2-SHA256, 100_000 轮, 16 字节随机 salt）
# ============================================================
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 100_000)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


# ============================================================
# JWT（HS256，标准库实现）
# ============================================================
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(signing_input: str) -> str:
    sig = hmac.new(JWT_SECRET.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(sig)


def jwt_encode(user: models.User) -> str:
    now = int(time.time())
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url_encode(json.dumps({
        "sub": str(user.id),
        "username": user.username,
        "iat": now,
        "exp": now + JWT_EXPIRE_DAYS * 86400,
    }, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_sign(signing_input)}"


def jwt_decode(token: str) -> dict:
    """解析并校验 JWT；格式错误/签名不符/过期均抛 401「未登录或登录已过期」"""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected = _sign(signing_input)
        if not hmac.compare_digest(expected, sig_b64):
            raise ValueError("bad signature")
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        if header.get("alg") != "HS256":
            raise ValueError("bad alg")
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "未登录或登录已过期")


# ============================================================
# 认证 / 角色依赖
# ============================================================
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    """所有受保护端点的认证依赖：解析 JWT → 查用户（不存在/禁用 → 401）"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(401, "未登录或登录已过期")
    payload = jwt_decode(credentials.credentials)
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        raise HTTPException(401, "未登录或登录已过期")
    user = db.get(models.User, user_id)
    if user is None or not user.enabled:
        raise HTTPException(401, "未登录或登录已过期")
    return user


def require_editor(user: models.User = Depends(get_current_user)) -> models.User:
    """业务写操作：admin + editor 可执行，viewer 403
    （ADR-014：文案统一由后端给出，前端拦截器对 403 直接 toast detail）"""
    if user.role not in EDITOR_ROLES:
        raise HTTPException(403, "只读账号不可执行该操作")
    return user


def require_order(user: models.User = Depends(get_current_user)) -> models.User:
    """下单链路（购物车 + 直接下单）：已认证即可，admin/editor/viewer 均放行"""
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    """账号管理 / 审计查询：仅 admin"""
    if user.role != "admin":
        raise HTTPException(403, "无权限执行此操作")
    return user


# ============================================================
# 审计记录（router 层统一调用；业务 services 不动）
# ============================================================
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def record_audit(db: Session, user: models.User | None, action_type: str, action: str,
                 target: str, target_name: str = "", detail: str | None = None) -> None:
    """写一条审计日志并立即提交（业务服务已各自提交，审计独立落库，失败不影响业务响应）"""
    try:
        db.add(models.AuditLog(
            userId=user.id if user else None,
            username=(user.username if user else "")[:50],
            actionType=action_type,
            action=action[:50],
            target=target[:50],
            targetName=(target_name or "")[:120],
            detail=(detail or "")[:255] if detail else None,
            time=now_str(),
        ))
        db.commit()
    except Exception:
        db.rollback()


def user_out(user: models.User) -> dict:
    """User 序列化（不含 passwordHash）"""
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "enabled": user.enabled,
    }


# ============================================================
# 登录失败限流（进程内计数，标准库实现，无新依赖）
# 同一用户名 15 分钟内连续失败 ≥ 10 次 → 锁定 15 分钟（防撞库；
# 单实例部署够用；多 worker 部署下为每进程独立计数，保守但仍有效）。
# ============================================================
_LOGIN_FAIL_WINDOW = 15 * 60   # 秒
_LOGIN_FAIL_LIMIT = 10
_login_fails: dict[str, list[float]] = {}


def login_locked(username: str) -> bool:
    """该用户名当前是否处于登录失败锁定中"""
    now = time.time()
    fails = [t for t in _login_fails.get(username, []) if now - t < _LOGIN_FAIL_WINDOW]
    _login_fails[username] = fails
    return len(fails) >= _LOGIN_FAIL_LIMIT


def login_failed(username: str) -> None:
    now = time.time()
    fails = [t for t in _login_fails.get(username, []) if now - t < _LOGIN_FAIL_WINDOW]
    fails.append(now)
    _login_fails[username] = fails


def login_succeeded(username: str) -> None:
    _login_fails.pop(username, None)
