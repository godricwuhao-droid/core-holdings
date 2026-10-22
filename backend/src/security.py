"""认证与权限（JWT Bearer + PBKDF2 密码哈希 + 固定三角色 + 审计记录）

实现约束（架构决策，禁止偏离）：
- JWT HS256 自实现，仅用标准库 hmac/hashlib/base64/json，不引入新依赖；
  exp 7 天。**JWT_SECRET 缺失/等于内置开发值时（BUG-11 / ADR-034 §1）**：
  `APP_ENV != "dev"` → 启动 fail-fast（RuntimeError，进程不启动）；
  dev → **持久化开发密钥文件**（`backend/.jwt_secret`，0600，内容 64 字节 urlsafe
  随机串）：文件存在即复用 → `--reload` 热重载/重启不再使全部 token 失效
  （FIX-20261022-FOLLOWUP；此前为进程内随机密钥，每次重启集体掉登录）。
  该文件被 `.gitignore` 忽略，禁止提交；生产必须走环境变量 `JWT_SECRET`。
- JWT 携带 `ver`（users.tokenVersion）；`get_current_user` 每请求比对，不一致 → 401。
  改密/禁用/改角色时 tokenVersion += 1（旧 token 立即失效）。**不提供 /auth/logout**（ADR-034 §3）。
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
from collections import OrderedDict
from datetime import datetime

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db

# ---- JWT 密钥（BUG-11 / ADR-034 §1；FIX-20261022-FOLLOWUP 起 dev 持久化）----
DEV_DEFAULT_SECRET = "core-holdings-local-dev-secret-change-in-production"
APP_ENV = (os.getenv("APP_ENV") or "dev").strip().lower()
JWT_EXPIRE_DAYS = 7

# backend/ 目录（与默认 SQLite `backend/core_holdings.db` 同级）——不存在则自动创建
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 开发密钥文件：内容 = 64 字节 urlsafe 随机串，权限 0600，已在 .gitignore 中忽略
DEV_SECRET_FILE = os.path.join(BACKEND_DIR, ".jwt_secret")


def _read_dev_secret(path: str) -> str:
    """读开发密钥文件；不存在 / 不可读 / 空内容一律返回 ""（由调用方重新生成）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _chmod_private(path: str) -> None:
    """尽力把密钥文件收敛到 0600（仅属主可读写）；失败不阻塞启动。"""
    try:
        if os.stat(path).st_mode & 0o077:
            os.chmod(path, 0o600)
    except OSError:
        pass


def _atomic_write_secret(path: str, secret: str) -> None:
    """原子落盘：同目录临时文件（0600 创建）→ os.replace，避免并发读到半截内容。"""
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secret)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _chmod_private(path)


def _load_or_create_dev_secret(path: str) -> tuple[str, str]:
    """返回 (secret, 来源)；来源 ∈ reuse / create / regenerate / ephemeral。

    - 文件存在且非空 → **复用**（重复启动 / `--reload` 热重载不换密钥 → token 不再集体失效）
    - 文件不存在 → `O_CREAT|O_EXCL` 原子创建（0600），写入 64 字节 urlsafe 随机串
    - 已存在但为空 / 不可读 → 原子覆盖重新生成（不让空文件把服务钉死在随机密钥上）
    - 目录不可写（只读 FS / 权限不足）→ 退回进程内随机密钥（等价旧行为，仅 dev）
    """
    existing = _read_dev_secret(path)
    if existing:
        _chmod_private(path)
        return existing, "reuse"
    fresh = secrets.token_urlsafe(48)  # 48 字节 → 64 字节 urlsafe 串（无填充）
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # 并发启动（另一进程刚创建）或「存在但为空」：复读一次，仍空才覆盖
        again = _read_dev_secret(path)
        if again:
            _chmod_private(path)
            return again, "reuse"
        try:
            _atomic_write_secret(path, fresh)
            return fresh, "regenerate"
        except OSError:
            return fresh, "ephemeral"
    except OSError:
        return fresh, "ephemeral"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(fresh)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        try:
            os.remove(path)  # 清掉可能写了一半的文件
        except OSError:
            pass
        return fresh, "ephemeral"
    _chmod_private(path)
    return fresh, "create"


_SECRET_SOURCE_TEXT = {
    "reuse": "读取已有密钥文件，重启/热重载不换密钥",
    "create": "首次生成并落盘",
    "regenerate": "文件为空/不可读，已重新生成",
    "ephemeral": "密钥文件不可写，退回进程内随机密钥",
}


def _resolve_jwt_secret() -> str:
    """密钥优先级：`JWT_SECRET` 环境变量（非默认值）> 开发密钥文件 > 生成并落盘。"""
    env_secret = (os.getenv("JWT_SECRET") or "").strip()
    if env_secret and env_secret != DEV_DEFAULT_SECRET:
        return env_secret
    reason = "未设置 JWT_SECRET" if not env_secret else "JWT_SECRET 等于内置开发默认值"
    if APP_ENV != "dev":
        raise RuntimeError(
            f"[security] 启动中止：{reason}。生产环境（APP_ENV={APP_ENV}）必须通过环境变量 "
            "JWT_SECRET 指定强随机密钥（否则任何拿到源码的人都可离线签发管理员 token）。"
        )
    secret, source = _load_or_create_dev_secret(DEV_SECRET_FILE)
    print(
        f"[security] {reason}（APP_ENV=dev）：JWT 密钥使用持久化开发密钥文件 "
        f"{DEV_SECRET_FILE}（{_SECRET_SOURCE_TEXT[source]}，权限 0600）；"
        "生产部署必须改用环境变量 JWT_SECRET。"
    )
    if source == "ephemeral":
        print("[security] ⚠️  密钥文件无法落盘：重启后全部 token 失效、需重新登录。")
    return secret


JWT_SECRET = _resolve_jwt_secret()

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
        # 凭据版本（BUG-11 / ADR-034 §2）：改密/禁用/改角色时 +1，旧 token 立即失效
        "ver": int(user.tokenVersion or 0),
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
def user_from_token(db: Session, raw_token: str) -> models.User:
    """JWT → 用户（唯一解析实现，Bearer 头与 `?token=` 双通道共用）。

    校验链：签名/过期（jwt_decode）→ sub 查用户（不存在/禁用 401）→
    **tokenVersion 比对**（BUG-11：改密/禁用/改角色后旧 token 立即失效）。
    """
    payload = jwt_decode(raw_token)
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        raise HTTPException(401, "未登录或登录已过期")
    user = db.get(models.User, user_id)
    if user is None or not user.enabled:
        raise HTTPException(401, "未登录或登录已过期")
    if int(payload.get("ver", 0) or 0) != int(user.tokenVersion or 0):
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    """所有受保护端点的认证依赖：解析 JWT → 查用户（不存在/禁用/tokenVersion 不符 → 401）"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(401, "未登录或登录已过期")
    return user_from_token(db, credentials.credentials)


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
# 登录失败限流（BUG-12 / ADR-034 §4；进程内计数，标准库实现，无新依赖）
# 双维度，均 15 分钟滑动窗口：
# - `(ip, username)` 维度：10 次 → 拦截（防针对性撞库）；
# - 纯 IP 维度：30 次 → 拦截（防换用户名喷洒）。
# 超限返回 429「登录尝试过于频繁，请稍后再试」；**不做全局封账号**（不因单账号计数锁死他人）。
# 结构有界：最多 10k 键，LRU 淘汰最旧键（防内存无界增长）。
# 单实例部署够用；多 worker 部署下为每进程独立计数，保守但仍有效。
# ============================================================
_LOGIN_WINDOW = 15 * 60          # 秒
_LOGIN_PAIR_LIMIT = 10           # (ip, username) 维度阈值
_LOGIN_IP_LIMIT = 30             # 纯 IP 维度阈值
_LOGIN_MAX_KEYS = 10_000         # 计数结构上界（LRU）
_login_fails: "OrderedDict[str, list[float]]" = OrderedDict()


def _login_key(ip: str, username: str = "") -> str:
    return f"{ip}|{(username or '').strip().lower()}"


def _recent(key: str, now: float) -> list[float]:
    fails = [t for t in _login_fails.get(key, []) if now - t < _LOGIN_WINDOW]
    if fails:
        _login_fails[key] = fails
        _login_fails.move_to_end(key)
    else:
        _login_fails.pop(key, None)
    return fails


def _remember(key: str, now: float) -> None:
    fails = _recent(key, now)
    fails.append(now)
    _login_fails[key] = fails
    _login_fails.move_to_end(key)
    while len(_login_fails) > _LOGIN_MAX_KEYS:
        _login_fails.popitem(last=False)  # LRU 淘汰最旧键


def login_blocked(ip: str, username: str) -> bool:
    """当前来源是否应被拦截（(ip, username) ≥10 或 纯 IP ≥30，15 分钟窗口）"""
    now = time.time()
    if len(_recent(_login_key(ip, username), now)) >= _LOGIN_PAIR_LIMIT:
        return True
    return len(_recent(_login_key(ip), now)) >= _LOGIN_IP_LIMIT


def login_failed(ip: str, username: str) -> None:
    now = time.time()
    _remember(_login_key(ip, username), now)
    _remember(_login_key(ip), now)


def login_succeeded(ip: str, username: str) -> None:
    # 成功只清 `(ip, username)` 计数；纯 IP 计数保留（避免用一次成功登录洗白喷洒计数）
    _login_fails.pop(_login_key(ip, username), None)


# 用户不存在时用于「恒定时间」的一次 PBKDF2（BUG-12：时间差不可用于枚举账号）
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password_or_dummy(password: str, stored: str | None) -> bool:
    """用户不存在（stored 为 None）时仍执行一次同参数 PBKDF2，抹平响应时间差。"""
    if not stored:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False
    return verify_password(password, stored)
