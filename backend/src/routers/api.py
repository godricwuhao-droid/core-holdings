"""REST API 路由（前缀 /api），字段契约对齐前端 src/api/index.ts

权限管控（2026-10-15；2026-10-16 文件端点补鉴权；FIX-20261022 收口）：
- 除 POST /auth/login、GET /health 外，所有端点均需
  `Authorization: Bearer <jwt>`（依赖逐个明确挂载，不用 router 级全挂）。
- GET /files/{filename} 走双通道认证（get_file_user）：优先 Bearer 头，
  无头时接受 `?token=<jwt>` 查询参数（iframe/img 无法带请求头）；
  **对象级 ACL**（BUG-02/ADR-030 §3）：不可见一律 404（不返回 403，避免探测文件名）。
- 读接口三角色均可（get_current_user）；业务写接口 admin+editor（require_editor）；
  账号管理/审计查询仅 admin（require_admin）；`GET /users/options` 自 FIX-20261022 起
  为 require_editor（内部人员清单不对 viewer 暴露，BUG-32/ADR-030 §5）。
- 下单链路：购物车全部端点 require_order（已认证即可，viewer/生态人员放行）；
  `POST /sales/order`、`POST /projects/{id}/resubmit` 已下线（**410 Gone**，ADR-029 §3）。
- 审计在 router 层统一 record_audit（业务 services 不动，降低回归风险）。
"""
import mimetypes
import os
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .. import models, schemas, security, services
from ..database import get_db

router = APIRouter(prefix="/api")

# ============================================================
# 文件上传 / 访问（合同文件等）
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# UPLOAD_DIR 可用环境变量覆盖（本地验收用临时目录）；默认 backend/uploads
UPLOAD_DIR = os.getenv("UPLOAD_DIR") or os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
# `.doc` 已从白名单移除（BUG-31 / api-contracts §7：与 ADR-024 前端 accept 一致，禁上传 .doc）
ALLOWED_EXT = {"pdf", "docx", "png", "jpg", "jpeg", "gif", "webp", "xlsx"}
MAX_SIZE = 20 * 1024 * 1024  # 20MB
_CHUNK = 1024 * 1024  # 流式写入块大小（1MB）


@router.get("/health")
def health():
    return {"status": "ok", "service": "core-holdings"}


# ============================================================
# 认证
# ============================================================
_LOGIN_FAIL_MSG = "用户名或密码错误"
_LOGIN_TOO_MANY_MSG = "登录尝试过于频繁，请稍后再试"


@router.post("/auth/login")
def login(data: schemas.LoginInput, request: Request, db: Session = Depends(get_db)):
    """登录（BUG-12 / ADR-034 §4 加固）。

    - 失败文案**统一**「用户名或密码错误」（不再区分「账号已被禁用」，避免账号枚举）；
    - 用户不存在时仍执行一次 PBKDF2（恒定时间，抹平响应时间差）；
    - 失败计数双维度：`(ip, username)` 10/15min + 纯 IP 30/15min，超限 **429**；
      不再因单账号计数全局封号（避免定向锁死管理员）。
    """
    ip = (request.client.host if request.client else "") or ""
    username = (data.username or "").strip()
    if security.login_blocked(ip, username):
        security.record_audit(db, None, "auth", "登录拦截", "auth", username, "失败次数过多，来源限流")
        raise HTTPException(429, _LOGIN_TOO_MANY_MSG)
    user = db.query(models.User).filter(models.User.username == data.username).first()
    ok = security.verify_password_or_dummy(data.password, user.passwordHash if user is not None else None)
    if user is None or not ok or not user.enabled:
        security.login_failed(ip, username)
        reason = "用户名或密码错误" if user is None or not ok else "账号已被禁用"
        security.record_audit(db, None, "auth", "登录失败", "auth", username, reason)
        raise HTTPException(401, _LOGIN_FAIL_MSG)
    security.login_succeeded(ip, username)
    security.record_audit(db, user, "auth", "登录成功", "auth", user.username)
    return {"token": security.jwt_encode(user), "user": security.user_out(user)}


@router.get("/auth/me")
def me(user: models.User = Depends(security.get_current_user)):
    return security.user_out(user)


# ============================================================
# 用户管理（仅 admin）
# ============================================================
@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: models.User = Depends(security.require_admin)):
    return db.query(models.User).order_by(models.User.id.asc()).all()


@router.get("/users/options", response_model=list[schemas.UserOut])
def user_options(db: Session = Depends(get_db), _: models.User = Depends(security.require_editor)):
    """商务账号选项（ADR-012 §5.1）：editor + admin 有效账号，
    供「商务负责人」筛选/接手转交下拉与商务 username→姓名 展示映射（商务负责人与角色账号的关联查询）。

    BUG-32 / ADR-030 §5（FIX-20261022）：权限由「任意登录」提升为 **require_editor**——
    内部商务/管理员名单不再对 viewer 暴露（同口径的 /users/options/all 早已收敛）；
    前端「商务负责人」筛选对 viewer 不渲染。"""
    return (
        db.query(models.User)
        .where(models.User.role.in_(("editor", "admin")), models.User.enabled == True)  # noqa: E712
        .order_by(models.User.id.asc())
        .all()
    )


@router.get("/users/options/all", response_model=list[schemas.UserOut])
def user_options_all(db: Session = Depends(get_db), user: models.User = Depends(security.get_current_user)):
    """全部启用账号（2026-10-20：含生态 viewer）——供项目页「账号 → 姓名」显示映射
    （生态人员列 rep 存生态账号，/users/options 只有商务查不到 → 裸账号外露）。
    仅展示用途；商务接手/转交下拉仍用 /users/options（不得转给生态）。
    FIX-20261020-#6：viewer 仅返回本人 + 其可见项目中 rep/creator/businessOwner
    出现过的账号（此前全量返回会暴露其他客户相关账号）；admin/editor 全量（现状）。"""
    all_enabled = (
        db.query(models.User)
        .where(models.User.enabled == True)  # noqa: E712
        .order_by(models.User.id.asc())
        .all()
    )
    if user.role != "viewer":
        return all_enabled
    visible_projects = [p for p in db.query(models.Project).all()
                        if services.user_sees_project(user, p)]
    known = {user.username}
    for p in visible_projects:
        for v in (p.rep, p.creator, p.businessOwner):
            if v:
                known.add(v)
    return [u for u in all_enabled if u.username in known]


@router.post("/users", response_model=schemas.UserOut)
def create_user(data: schemas.UserCreate, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_admin)):
    if data.role not in security.ROLES:
        raise HTTPException(400, f"非法角色：role 仅支持 {'/'.join(security.ROLES)}")
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(400, "用户名已存在")
    u = models.User(
        username=data.username, passwordHash=security.hash_password(data.password),
        name=data.name, role=data.role, enabled=True, createdAt=security.now_str(),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    security.record_audit(db, user, "user_mgmt", "新增用户", "user", u.username, f"role={u.role}")
    return u


@router.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, data: schemas.UserUpdate, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_admin)):
    u = db.get(models.User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    if user_id == user.id and (data.role is not None or data.enabled is not None):
        raise HTTPException(400, "不能修改自己的角色或启用状态")
    changes = []
    if data.role is not None:
        if data.role not in security.ROLES:
            raise HTTPException(400, f"非法角色：role 仅支持 {'/'.join(security.ROLES)}")
        u.role = data.role
        changes.append(f"role→{data.role}")
    if data.name is not None:
        u.name = data.name
        changes.append("name")
    if data.enabled is not None:
        u.enabled = data.enabled
        changes.append(f"enabled→{data.enabled}")
    if data.password is not None:
        u.passwordHash = security.hash_password(data.password)
        changes.append("password")
    # BUG-11 / ADR-034 §2：改密 / 禁用 / 改角色 → tokenVersion+1，旧 token 立即失效
    #（登出仍为前端清 token，不新增 /auth/logout 端点，ADR-034 §3）
    if data.password is not None or data.role is not None or data.enabled is not None:
        u.tokenVersion = int(u.tokenVersion or 0) + 1
    db.commit()
    db.refresh(u)
    security.record_audit(db, user, "user_mgmt", "编辑用户", "user", u.username,
                          "，".join(changes) if changes else "无变更")
    return u


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_admin)):
    if user_id == user.id:
        raise HTTPException(400, "不能删除自己的账号")
    u = db.get(models.User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    name = u.username
    # 清理该用户的购物车行（cart_items.userId 存 users.id 字符串），避免删除后留下永久孤儿数据
    db.query(models.CartItem).filter(models.CartItem.userId == str(user_id)).delete(
        synchronize_session=False)
    db.delete(u)
    db.commit()
    security.record_audit(db, user, "user_mgmt", "删除用户", "user", name)
    return {"ok": True}


# ============================================================
# 审计日志（仅 admin）
# ============================================================
@router.get("/audit-logs")
def list_audit_logs(
    actionType: str | None = None,
    username: str | None = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: models.User = Depends(security.require_admin),
):
    q = db.query(models.AuditLog)
    if actionType:
        q = q.filter(models.AuditLog.actionType == actionType)
    if username:
        q = q.filter(models.AuditLog.username == username)
    total = q.count()
    # 时间倒序：time 为分钟级字符串，按自增 id 倒序等价且更精确
    items = q.order_by(models.AuditLog.id.desc()).offset((page - 1) * pageSize).limit(pageSize).all()
    return {"total": total, "items": [schemas.AuditLogOut.model_validate(i).model_dump() for i in items]}


# ============================================================
# Bootstrap（读，三角色均可）
# ============================================================
@router.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db), user: models.User = Depends(security.get_current_user)):
    # ADR-009：cart 仅返回当前登录用户的行；viewer（生态人员）projects/contracts 按「自己下单」过滤
    return services.bootstrap(db, str(user.id), user)


# ============================================================
# 产品（写：admin+editor）
# ============================================================
@router.post("/assets", response_model=schemas.AssetOut)
def create_asset(data: schemas.AssetInput, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_editor)):
    asset = services.create_asset(db, data, operator=user.username)
    security.record_audit(db, user, "asset_change", "新增产品", "asset", asset.name, asset.code)
    return asset


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, data: schemas.AssetUpdate, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_editor)):
    # 修复裸 dict 无校验：Pydantic 拦截非法类型/负数（422）；
    # exclude_unset——仅采信客户端实际传了的字段（未传字段不覆盖）
    services.update_asset(db, asset_id, data.model_dump(exclude_unset=True), operator=user.username)
    a = db.get(models.Asset, asset_id)
    security.record_audit(db, user, "asset_change", "编辑产品", "asset", a.name if a else str(asset_id))
    return {"ok": True}


# 注：已移除 PATCH /assets/{asset_id}/status（M6）——产品状态改为纯 2 态自动判定，
# 前端从不调用该端点（已确认），保留会与自动判定逻辑冲突。


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_editor)):
    a = db.get(models.Asset, asset_id)
    name = a.name if a else str(asset_id)
    services.delete_asset(db, asset_id, operator=user.username)
    security.record_audit(db, user, "asset_change", "删除产品", "asset", name)
    return {"ok": True}


# ============================================================
# 遥感数据可售明细（ADR-011：父产品 + 明细两层模型；写 admin+editor，读随 bootstrap 放行）
# ============================================================
@router.post("/assets/{asset_id}/rs-items", response_model=schemas.RsItemOut)
def create_rs_item(asset_id: int, data: schemas.RsItemInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    a = db.get(models.Asset, asset_id)
    item = services.create_rs_item(db, asset_id, data, operator=user.username)
    security.record_audit(db, user, "asset_change", "新增可售明细", "asset",
                          a.name if a else str(asset_id), f"rsItemId={item.id}")
    return item


@router.put("/rs-items/{item_id}", response_model=schemas.RsItemOut)
def update_rs_item(item_id: int, data: schemas.RsItemInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    it = db.get(models.RsItem, item_id)
    a = db.get(models.Asset, it.assetId) if it else None
    item = services.update_rs_item(db, item_id, data, operator=user.username)
    security.record_audit(db, user, "asset_change", "编辑可售明细", "asset",
                          a.name if a else str(item_id), f"rsItemId={item.id}")
    return item


@router.delete("/rs-items/{item_id}")
def delete_rs_item(item_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    it = db.get(models.RsItem, item_id)
    a = db.get(models.Asset, it.assetId) if it else None
    services.delete_rs_item(db, item_id, operator=user.username)
    security.record_audit(db, user, "asset_change", "删除可售明细", "asset",
                          a.name if a else str(item_id), f"rsItemId={item_id}")
    return {"ok": True}


# ============================================================
# 产品相关列表服务端分页（PAGE-20261021，读：三角色放行，对齐 /audit-logs 先例）
# bootstrap 快照字段（rsItems/flows/logs）保留不动——RsItemPicker 树等消费方仍依赖全量镜像
# ============================================================
@router.get("/assets/{asset_id}/rs-items")
def list_rs_items(
    asset_id: int,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),  # PAGE-20261021：默认 10（单页 10 条）
    db: Session = Depends(get_db),
    _: models.User = Depends(security.get_current_user),
):
    """PAGE-20261021：可售明细分页（id ASC）。items = RsItemOut + 派生 soldCount。
    soldCount 口径：该明细被 delivered 状态合同的项目明细计数
    （project_items.itemId == rs_item.id 且所属合同 status='delivered'），
    一条聚合查询按当页 id 批量计算，避免逐行查。
    FIX-20261022-FOLLOWUP：聚合逻辑抽到 `services._rs_item_sold_counts`，
    与 `bootstrap.rsItems` 共用**同一实现**（不复制两份口径）。"""
    a = db.get(models.Asset, asset_id)
    if a is None:
        raise HTTPException(404, "产品不存在")
    q = db.query(models.RsItem).filter(models.RsItem.assetId == asset_id)
    total = q.count()
    items = q.order_by(models.RsItem.id.asc()).offset((page - 1) * pageSize).limit(pageSize).all()
    sold: dict[int, int] = services._rs_item_sold_counts(db, [i.id for i in items])
    out = []
    for i in items:
        d = schemas.RsItemOut.model_validate(i).model_dump()
        d["soldCount"] = sold.get(i.id, 0)
        out.append(schemas.RsItemOutWithSold.model_validate(d).model_dump())
    return {"total": total, "items": out}


@router.get("/assets/{asset_id}/flows")
def list_asset_flows(
    asset_id: int,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),  # PAGE-20261021：默认 10
    db: Session = Depends(get_db),
    user: models.User = Depends(security.get_current_user),
):
    """PAGE-20261021：产品级数量流水分页（id DESC，仅该 assetId）。

    BUG-13 / ADR-030 §4（FIX-20261022）：viewer **复用 `Visibility.flow_visible()`**，
    与 bootstrap 同一口径——此前该分页端点完全不过滤，可绕过 bootstrap 拿到他人
    销售记录编号/数量/金额。`total` 按过滤后的集合计算（对 viewer 先过滤再分页）。
    """
    a = db.get(models.Asset, asset_id)
    if a is None:
        raise HTTPException(404, "产品不存在")
    vis = services.build_visibility(db, user)
    q = db.query(models.AssetFlow).filter(models.AssetFlow.assetId == asset_id)
    if vis.restricted:
        rows = [f for f in q.order_by(models.AssetFlow.id.desc()).all() if vis.flow_visible(f)]
        total = len(rows)
        items = rows[(page - 1) * pageSize: (page - 1) * pageSize + pageSize]
    else:
        total = q.count()
        items = q.order_by(models.AssetFlow.id.desc()).offset(
            (page - 1) * pageSize).limit(pageSize).all()
    return {"total": total, "items": [schemas.FlowOut.model_validate(i).model_dump() for i in items]}


@router.get("/assets/{asset_id}/logs")
def list_asset_logs(
    asset_id: int,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),  # PAGE-20261021：默认 10
    db: Session = Depends(get_db),
    _: models.User = Depends(security.get_current_user),
):
    """PAGE-20261021：产品操作日志分页（target='asset' 且 assetId 过滤，id DESC）。
    抽屉「最近动态」由前端取两接口各一页后合并排序取 10 条（契约 PAGE-20261021 §3）。"""
    a = db.get(models.Asset, asset_id)
    if a is None:
        raise HTTPException(404, "产品不存在")
    q = db.query(models.OpLog).filter(
        models.OpLog.target == "asset", models.OpLog.assetId == asset_id)
    total = q.count()
    items = q.order_by(models.OpLog.id.desc()).offset((page - 1) * pageSize).limit(pageSize).all()
    return {"total": total, "items": [schemas.LogOut.model_validate(i).model_dump() for i in items]}


# ============================================================
# 销售项目（写：admin+editor）
# ============================================================
@router.post("/projects", response_model=schemas.ProjectOut)
def create_project(data: schemas.ProjectInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    """手动建单/保存草稿。
    【核心业务规则 ADR-012 修订 2026-10-19】所有角色（生态/商务/管理员）× 所有建单入口
    （手动建单/直接下单/购物车结算）统一建 **pending（待审核）**：
    商务「接手」绑定负责人 → 审核（改价确认/驳回）→ 生效 active。
    pending 期间：仅负责人（或 admin 越过）可编辑/审核，锁定照常。"""
    project = services.create_project(db, data, operator=user.username)
    security.record_audit(db, user, "sale", "新建销售项目", "project", project.name, project.code)
    return project


@router.put("/projects/{project_id}")
def update_project(project_id: int, data: schemas.ProjectInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_order)):
    # ADR-028 §1：viewer（生态人员）一律 403「订单已提交，不可编辑；如需修改请「撤销」后重新下单」
    #（订单提交即冻结，改单唯一路径 = 撤销 → 回填购物车 → 重下）；
    # 商务/管理员既有约束（pending 仅负责人或 admin、已交付/已终止不可编辑、名称非空）不变。
    # 权限判定一律在 services.update_project 内收口，路由层不重复判断。
    services.update_project(db, project_id, data, operator=user.username, user=user)
    p = db.get(models.Project, project_id)
    security.record_audit(db, user, "sale", "编辑销售项目", "project", p.name if p else str(project_id))
    return {"ok": True}


@router.patch("/projects/{project_id}/status")
def change_project_status(project_id: int, data: schemas.StatusInput, db: Session = Depends(get_db),
                          user: models.User = Depends(security.require_order)):
    # viewer（生态人员）仅可终止自己下单的项目——归属/动作约束在 services.change_project_status 内
    services.change_project_status(db, project_id, data, operator=user.username, user=user)
    p = db.get(models.Project, project_id)
    security.record_audit(db, user, "sale", "变更项目状态", "project",
                          p.name if p else str(project_id), f"status={data.status}")
    return {"ok": True}


@router.post("/projects/{project_id}/review")
def review_project(project_id: int, data: schemas.ReviewInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    """订单审核（ADR-012，仅商务/管理员）：确认下单（可带行级改价 + 服务期限；
    ADR-018 §4 起不再回写平台挂牌价）/ 驳回（释放锁定 + 项目终止 + 原因留痕）。
    生态人员 403（require_editor 拦截）。
    【核心业务规则 ADR-012 修订 2026-10-19】全部建单入口统一 pending 后，本接口是唯一
    pending→active 出口；仅**商务负责人**（businessOwner 绑定账号）可操作，admin 越过，
    非负责人 400（未接手 → 「该订单尚未被商务接手，请先接手后再操作」）。"""
    # ADR-012 §5.1：接手人守卫在 services.review_project 内（未接手/非接手人 400，admin 可越过）
    services.review_project(db, project_id, data, operator=user.username, user=user)
    p = db.get(models.Project, project_id)
    security.record_audit(db, user, "sale",
                          "确认下单" if data.action == "confirm" else "驳回订单",
                          "project", p.name if p else str(project_id))
    return {"ok": True}


@router.post("/projects/{project_id}/claim")
def claim_project(project_id: int, data: schemas.ClaimInput = schemas.ClaimInput(),
                  db: Session = Depends(get_db),
                  user: models.User = Depends(security.require_editor)):
    """商务接手/转交（ADR-012 §5.1 纯移交制）：无负责人→接手（绑定自己）；
    已有负责人→仅负责人可转交（body 传 newOwner=目标商务账号）或 admin 越过（接手/转交任意账号）。
    接手后 businessOwner 成为改价/确认/驳回的权限依据（admin 可越过）。"""
    action = services.claim_project(db, project_id, user=user, new_owner=data.newOwner)
    p = db.get(models.Project, project_id)
    security.record_audit(db, user, "sale", action, "project",
                          p.name if p else str(project_id))
    return {"ok": True}


@router.post("/projects/{project_id}/withdraw")
def withdraw_project(project_id: int, data: schemas.WithdrawInput, db: Session = Depends(get_db),
                     user: models.User = Depends(security.require_order)):
    """撤销待审核订单（ADR-026，下单生态人员本人或 admin）。

    语义 = 终止原单（释放锁定 + cancel_release 流水 + 合同 remark 留痕） **+ 全部明细
    自动回填下单人购物车**（保留客户/数量/金额/服务期限/折扣率/遥感明细 itemId），
    原单保留 terminated 历史（可查原因），不删除、不新增「草稿」状态。
    守卫：仅 pending 可撤销（否则 400）；非本人且非 admin → 403；reason 必填 1–200 字。
    回填容错：单行无法回填时降级「原价成交 / 跳过」，在响应 restored/amountFallback/
    skipped/skippedReasons 中返回，绝不中断整体撤销。
    不改现有终止/驳回/重新提交口径（PATCH status / review / resubmit 行为不变）。"""
    result = services.withdraw_project(db, project_id, data.reason, user)
    security.record_audit(db, user, "sale", "撤销订单", "project",
                          str(project_id), f"reason={data.reason}")
    return result


@router.post("/projects/{project_id}/refill-cart")
def refill_project_cart(project_id: int, db: Session = Depends(get_db),
                        user: models.User = Depends(security.require_order)):
    """「重新提交」收口购物车（ADR-027）：把已终止项目的明细回填**下单人**购物车，
    前端随后跳 `/cart` 改单再结算（不再走 create 页 copy 模式）。

    无 body；守卫：仅 `terminated` 项目（否则 400），viewer 仅自己下单的项目（403），
    admin/editor 放行（admin 代操作同样回填到**下单人**购物车）。
    幂等：`Project.cartRefilled` 为 True 时直接返回 `alreadyRefilled: true`，不重复回填
    （购物车行数不增加、不写日志）。回填容错口径与 withdraw 完全一致（共享实现）：
    单行失败降级「原价成交」重试，仍失败计入 skipped/skippedReasons，绝不中断。
    副作用：首次回填仅新增 cart_items 行（不锁量、不改项目/合同状态）+ 1 条 OpLog。"""
    result = services.refill_project_cart(db, project_id, user)
    if not result["alreadyRefilled"]:
        security.record_audit(db, user, "sale", "重新提交（回填购物车）", "project",
                              str(project_id), f"restored={result['restored']}")
    return result


@router.post("/projects/{project_id}/resubmit")
def resubmit_project(project_id: int):  # noqa: ARG001 - 下线端点，仅保留路径参数签名
    """⚠️ **已下线（BUG-08/ADR-029 §3，FIX-20261022）**：一律 410 Gone。

    原因：该入口对 viewer 开放且**完全不做**参考区间/服务期限校验（可绕过购物车直接建单）。
    「重新提交」唯一路径 = `POST /projects/{id}/refill-cart`（明细回填购物车 → `/cart` 改单 → 结算）。
    """
    raise HTTPException(410, "该接口已下线，请使用购物车结算")


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    # ADR-028 §3：撤销留痕护栏（terminated && cartRefilled → 403）在 services.delete_project 内收口，
    # 路由层不重复判断；其他终态（被驳回且从未回填）仍可删除
    p = db.get(models.Project, project_id)
    name = p.name if p else str(project_id)
    services.delete_project(db, project_id, operator=user.username)
    security.record_audit(db, user, "sale", "删除销售项目", "project", name)
    return {"ok": True}


# ============================================================
# 合同（ADR-007）：数量联动的最小单位
# 生命周期：POST /projects（contracts 入参）或 POST /cart/checkout 生成；
# 状态流转 PATCH /contracts/{id}/status；删除随项目删除级联（无独立删除端点）。
# ============================================================
@router.patch("/contracts/{contract_id}", response_model=schemas.ContractOut)
def patch_contract_fields(contract_id: int, data: schemas.ContractFieldPatch,
                          db: Session = Depends(get_db),
                          user: models.User = Depends(security.require_order)):
    """录入合同时间节点（ADR-019，PRICING-20261020）。

    - signedDate（合同签订时间）：editor/admin（接手人守卫，与审核同口径）；
      仅合同 active 可录入，录入后自动 active→delivering + 项目重算；录后可改、
      传 null 清空 → 400「签订时间录入后不可清空」；
    - scheduledDeliveryDate（预计交付时间）：仅 admin（非 admin 403）；
      仅合同 delivering 可录/改/清空（null 允许）。
    viewer 403「只读账号不可执行该操作」（该端点仅 editor/admin 使用）。"""
    c = services.patch_contract_fields(db, contract_id, data.model_dump(exclude_unset=True), user=user)
    security.record_audit(db, user, "sale", "录入合同时间节点", "contract", c.code,
                          f"signedDate={data.signedDate}, scheduledDeliveryDate={data.scheduledDeliveryDate}")
    return c


@router.patch("/contracts/{contract_id}/status")
def change_contract_status(contract_id: int, data: schemas.StatusInput, db: Session = Depends(get_db),
                           user: models.User = Depends(security.require_order)):
    # viewer（生态人员）仅可终止自己下单项目的合同（不可交付）——约束在 services.change_contract_status 内
    c = db.get(models.Contract, contract_id)
    code = c.code if c else str(contract_id)
    services.change_contract_status(db, contract_id, data.status, reason=data.reason,
                                    operator=user.username, user=user)
    security.record_audit(db, user, "sale", "变更销售记录状态", "contract", code, f"status={data.status}")
    return {"ok": True}


# ============================================================
# 交付（写：admin+editor）
# ============================================================
@router.post("/outbounds", response_model=schemas.OutboundOut)
def create_outbound(data: schemas.OutboundInput, db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_editor)):
    ob = services.create_outbound(db, data, operator=user.username)
    security.record_audit(db, user, "outbound", "新交付", "outbound", ob.assetName, ob.code)
    return ob


@router.post("/outbounds/{outbound_id}/revert")
def revert_outbound(outbound_id: int, data: schemas.OutboundRevertInput,
                    db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_editor)):
    """撤销交付（BUG-20：裸 dict → Pydantic；非法入参 422，不再 500）。
    BUG-14：产品/明细已不存在时 400（不允许「静默成功、零回滚」）。"""
    ob = db.get(models.Outbound, outbound_id)
    name = ob.assetName if ob else str(outbound_id)
    services.revert_outbound(db, outbound_id, data.reason, operator=user.username)
    security.record_audit(db, user, "outbound", "撤销交付", "outbound", name)
    return {"ok": True}


# ============================================================
# 购物车（ADR-009：按登录用户隔离——全部端点传 get_current_user 的 user.id）
# ============================================================
@router.post("/cart", response_model=schemas.CartItemOut)
def add_to_cart(data: schemas.CartItemInput, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_order)):
    return services.add_to_cart(db, data, user_id=str(user.id))


@router.post("/cart/batch", response_model=schemas.CartBatchResult)
def add_to_cart_batch(data: schemas.CartBatchInput, db: Session = Depends(get_db),
                      user: models.User = Depends(security.require_order)):
    return services.add_to_cart_batch(db, data, user_id=str(user.id))


@router.put("/cart/{cart_id}", response_model=schemas.CartItemOut)
def set_cart_qty(cart_id: int, data: schemas.CartQtyUpdate, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_order)):
    """改数量（`qty` 必传）+ 可选金额/服务期限/折扣率（BUG-20：裸 dict → Pydantic，非法入参 422）。

    - ADR-008/ADR-018 §3：可选携带 amount（unit/遥感行=折扣金额过区间校验；amount 行=整数元权威）；
    - ADR-020：可选携带 serviceStart/serviceEnd（服务期限）；
    - ADR-023：可选携带 discountRate（0-1 小数，0 < rate ≤ 1 否则 400；null=清空）；
    - CART-PERF-20261021：响应为更新后的完整 CartItemOut（前端本地打补丁，免全量重拉）；
    - CART-PATCH-20261021：其余字段**未传 = 保持原值**（按 `model_fields_set` 判断），显式 null = 清空；
    - ADR-037 §3（FORMS-20261022）：区间校验分角色——viewer 只校验下限（上限放开），
      editor/admin 双向（角色取当前登录用户，与 checkout 同函数）。
    """
    provided = data.model_fields_set
    item = services.set_cart_qty(db, cart_id, data.qty, user_id=str(user.id),
                                 amount=data.amount if "amount" in provided else services.UNSET,
                                 service_start=(data.serviceStart if "serviceStart" in provided
                                                else services.UNSET),
                                 service_end=(data.serviceEnd if "serviceEnd" in provided
                                              else services.UNSET),
                                 discount_rate=(data.discountRate if "discountRate" in provided
                                                else services.UNSET),
                                 viewer=(user.role == "viewer"))
    return item


@router.patch("/cart/{cart_id}", response_model=schemas.CartItemOut)
def patch_cart_item(cart_id: int, data: schemas.CartPatchInput, db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_order)):
    """修改购物车行级客户（ADR-007）；可选携带合同金额（ADR-008/ADR-018 §3）、
    服务期限（ADR-020，PRICING-20261020）与折扣率（DISCOUNT-20261021/ADR-023，
    0 < rate ≤ 1 否则 400；null=清空）。
    CART-PERF-20261021：响应由 {"ok": true} 改为更新后的完整 CartItemOut（前端本地打补丁，免全量重拉）。
    ADR-037 §3（FORMS-20261022）：区间校验分角色——viewer 只校验下限（上限放开），
    editor/admin 双向（角色取当前登录用户，与 PUT /cart/{id} / checkout 同函数）。"""
    # CART-PATCH-20261021：按 Pydantic model_fields_set 判断字段是否真的传了——
    # 未传 = 保持原值（不改），显式 null = 清空（修复改客户时金额/服务期限/折扣被误清空）
    provided = data.model_fields_set
    item = services.patch_cart_item(
        db, cart_id, data.customer, user_id=str(user.id),
        amount=data.amount if "amount" in provided else services.UNSET,
        service_start=data.serviceStart if "serviceStart" in provided else services.UNSET,
        service_end=data.serviceEnd if "serviceEnd" in provided else services.UNSET,
        discount_rate=data.discountRate if "discountRate" in provided else services.UNSET,
        viewer=(user.role == "viewer"))
    security.record_audit(db, user, "sale", "修改购物车客户", "cart", str(cart_id), f"customer={data.customer}")
    return item


@router.delete("/cart/{cart_id}")
def remove_cart_item(cart_id: int, db: Session = Depends(get_db),
                     user: models.User = Depends(security.require_order)):
    services.remove_cart_item(db, cart_id, user_id=str(user.id))
    return {"ok": True}


@router.delete("/cart")
def clear_cart(db: Session = Depends(get_db), user: models.User = Depends(security.require_order)):
    """清空购物车（BUG-33：成功体统一为 `{"ok": true}`，此前返回空 body/null）。"""
    services.clear_cart(db, user_id=str(user.id))
    return {"ok": True}


@router.post("/cart/checkout")
def checkout(data: schemas.CheckoutInput, db: Session = Depends(get_db),
             user: models.User = Depends(security.require_order)):
    """购物车结算：按产品分组 → 每个产品一条销售记录（ADR-013）。
    【核心业务规则 ADR-012 修订 2026-10-19】所有角色结算统一建 **pending（待审核）**
    （数量锁定照常）→ 商务接手审核（改价确认/驳回）后生效。
    ADR-022（REQUIRED-20261024）：逐行必填校验（客户/销售金额>0整数元/普通行服务期限起止），
    缺项 400 一次报全（文案含行标识）；「留空=挂牌价」兜底与 viewer 金额免填口径已作废。

    BUG-10 / ADR-033 §1：可选 `requestId` 幂等——响应 = `ProjectOut` 全部字段 + `idempotent`
    （首次 false；同一 `(userId, requestId)` 24h 内重复请求返回首次项目、`idempotent: true`，
    不重复建单/锁量/清购物车）。故此处不用 response_model（需附加非 ORM 字段）。
    """
    is_viewer = user.role == "viewer"
    project, idempotent = services.checkout(db, data, user_id=str(user.id),
                                            operator=user.username, viewer=is_viewer)
    if not idempotent:
        security.record_audit(db, user, "sale",
                              "购物车下单（待商务审核）" if is_viewer else "购物车结算",
                              "project", project.name, project.code)
    body = schemas.ProjectOut.model_validate(project).model_dump()
    body["idempotent"] = idempotent
    return body


@router.post("/sales/order")
def create_sale_order():
    """⚠️ **已下线（BUG-08/ADR-029 §3，FIX-20261022）**：一律 410 Gone。

    原因：该入口曾对 viewer 开放且只做「部分」校验（参考区间/服务期限缺失），
    与购物车链路形成第二套口径（同一业务不变量被复制到 4 处且无权威出口）。
    购物车结算 `POST /cart/checkout` 为唯一下单链路，新增入口自动继承全部校验。
    前端已无封装/入口；外部脚本直调需改造。
    """
    raise HTTPException(410, "该接口已下线，请使用购物车结算")


# ============================================================
# 基础资料（kind: suppliers / customers）
# CLEANUP-20261020：生态人员（kind='reps'）已由 users 表 + viewer 角色承载，该基础资料类型下线
# ============================================================
_BASE_LABEL = {"suppliers": "供应商", "customers": "客户"}


def _check_base_kind(kind: str) -> None:
    # CLEANUP-20261020：reps 类型已下线，统一返回 400
    if kind == "reps":
        raise HTTPException(400, "该基础资料类型已下线")


@router.post("/bases/{kind}")
def add_base(kind: str, data: schemas.BaseRecordInput, db: Session = Depends(get_db),
             user: models.User = Depends(security.require_editor)):
    _check_base_kind(kind)
    services.add_base(db, kind, data)
    label = _BASE_LABEL.get(kind, kind)
    security.record_audit(db, user, "setting", f"新增{label}", "base", data.name, f"kind={kind}")
    return {"ok": True}


@router.put("/bases/{kind}/{rec_id}")
def update_base(kind: str, rec_id: int, data: schemas.BaseRecordInput, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_editor)):
    _check_base_kind(kind)
    services.update_base(db, kind, rec_id, data)
    label = _BASE_LABEL.get(kind, kind)
    security.record_audit(db, user, "setting", f"编辑{label}", "base", data.name, f"kind={kind}")
    return {"ok": True}


@router.delete("/bases/{kind}/{rec_id}")
def delete_base(kind: str, rec_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_editor)):
    _check_base_kind(kind)
    r = db.get(models.BaseRecord, rec_id)
    name = r.name if r else str(rec_id)
    services.delete_base(db, kind, rec_id)
    label = _BASE_LABEL.get(kind, kind)
    security.record_audit(db, user, "setting", f"删除{label}", "base", name, f"kind={kind}")
    return {"ok": True}


# ============================================================
# 资产主体（ADR-035，ENTITIES-20261022）：主体清单单一事实来源
# 读登录即可（viewer 建产品页下拉也需读取）；写 admin+editor
# ============================================================
_ENTITY_LABEL = "资产主体"


@router.get("/entities", response_model=list[schemas.EntityOut])
def list_entities(db: Session = Depends(get_db),
                  _: models.User = Depends(security.get_current_user)):
    """全量返回，按 createdAt 正序、id 正序（存量展示顺序稳定）。"""
    return services.list_entities(db)


@router.post("/entities", response_model=schemas.EntityOut)
def add_entity(data: schemas.EntityInput, db: Session = Depends(get_db),
               user: models.User = Depends(security.require_editor)):
    e = services.add_entity(db, data, operator=user.username)
    security.record_audit(db, user, "setting", f"新增{_ENTITY_LABEL}", "entity",
                          e.name, f"short={e.short}")
    return e


@router.put("/entities/{entity_id}", response_model=schemas.EntityOut)
def update_entity(entity_id: int, data: schemas.EntityInput, db: Session = Depends(get_db),
                  user: models.User = Depends(security.require_editor)):
    old = db.get(models.Entity, entity_id)
    e = services.update_entity(db, entity_id, data, operator=user.username)
    detail = f"short={e.short}"
    if old and old.name != e.name:
        detail = f"名称 {old.name} → {e.name}；short={e.short}"
    security.record_audit(db, user, "setting", f"编辑{_ENTITY_LABEL}", "entity",
                          e.name, detail)
    return e


@router.delete("/entities/{entity_id}")
def delete_entity(entity_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(security.require_editor)):
    e = db.get(models.Entity, entity_id)
    name = e.name if e else str(entity_id)
    services.delete_entity(db, entity_id, operator=user.username)
    security.record_audit(db, user, "setting", f"删除{_ENTITY_LABEL}", "entity", name)
    return {"ok": True}


# ============================================================
# 产品交付物（ADR-024：模板端点已下线，实例完全手动维护）
# ============================================================
@router.post("/assets/{asset_id}/deliverables")
def add_asset_deliverable(asset_id: int, data: schemas.AssetDeliverableInput, db: Session = Depends(get_db),
                          user: models.User = Depends(security.require_editor)):
    services.add_asset_deliverable(db, asset_id, data)
    security.record_audit(db, user, "setting", "新增交付物", "deliverable", data.name, f"assetId={asset_id}")
    return {"ok": True}


@router.put("/assets/{asset_id}/deliverables/{item_id}")
def update_asset_deliverable(asset_id: int, item_id: int,
                             data: schemas.AssetDeliverableUpdate,
                             db: Session = Depends(get_db),
                             user: models.User = Depends(security.require_editor)):
    """更新交付物（BUG-20：裸 dict → Pydantic 部分更新，字段未传 = 保持原值，非法入参 422）。"""
    services.update_asset_deliverable(db, asset_id, item_id,
                                      data.model_dump(exclude_unset=True))
    d = db.get(models.AssetDeliverable, item_id)
    security.record_audit(db, user, "setting", "编辑交付物", "deliverable",
                          d.name if d else str(item_id), f"assetId={asset_id}")
    return {"ok": True}


@router.delete("/assets/{asset_id}/deliverables/{item_id}")
def remove_asset_deliverable(asset_id: int, item_id: int, db: Session = Depends(get_db),
                             user: models.User = Depends(security.require_editor)):
    d = db.get(models.AssetDeliverable, item_id)
    name = d.name if d else str(item_id)
    services.remove_asset_deliverable(db, asset_id, item_id)
    security.record_audit(db, user, "setting", "删除交付物", "deliverable", name, f"assetId={asset_id}")
    return {"ok": True}


# ============================================================
# 文件（合同等）上传 / 预览访问 / 删除
# ============================================================
@router.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: models.User = Depends(security.require_editor)):
    """上传附件（BUG-31 / api-contracts §7）：`.doc` 已从白名单移除；**流式写入**，
    累计超过 20MB 立即中断并删除半成品（不再先整体读入内存，避免 20MB×N 并发内存峰值）。"""
    orig = file.filename or ""
    ext = orig.rsplit(".", 1)[-1].lower() if "." in orig else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            400,
            f"不支持的文件格式：.{ext or '?'}（支持 pdf/docx/xlsx/图片；.doc 请先另存为 .docx）",
        )
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(UPLOAD_DIR, fname)
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SIZE:
                    raise HTTPException(400, "文件过大（上限 20MB）")
                out.write(chunk)
    except HTTPException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    if not size:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise HTTPException(400, "文件内容为空")
    # 落盘成功后写原名映射（上传不是产品操作，不写 OpLog）
    services.add_file_meta(db, fname, orig, size, user.username)
    return {"filename": fname, "name": orig, "size": size, "storedName": fname}


def _resolve_upload(name: str) -> str:
    base = os.path.basename(name or "")
    if not base or base in (".", ".."):
        raise HTTPException(400, "非法文件名")
    path = os.path.join(UPLOAD_DIR, base)
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在或已被删除")
    return path


async def get_file_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security.bearer),
    token: str | None = Query(None, description="JWT（iframe/img 无法带请求头时的查询参数通道）"),
    db: Session = Depends(get_db),
) -> models.User:
    """文件端点双通道认证：优先 Authorization: Bearer 头；无头时接受 ?token=<jwt>。
    复用 `security.user_from_token`（含 tokenVersion 比对），失败一律 401。"""
    raw = (credentials.credentials if credentials is not None else "") or (token or "")
    if not raw:
        raise HTTPException(401, "未登录或登录已过期")
    return security.user_from_token(db, raw)


@router.get("/files/{filename}")
def get_file(filename: str, inline: bool = Query(False, description="true 时内联预览（Content-Disposition: inline），缺省下载"),
             db: Session = Depends(get_db),
             user: models.User = Depends(get_file_user)):
    """下载/预览上传文件。

    BUG-02 / ADR-030 §3（FIX-20261022）：**对象级 ACL**——
    文件被任一产品引用（`assets.contractFile` / `featureDoc` / `asset_deliverables.file`）→ 所有
    登录用户可见；未被引用的孤儿文件 → 仅 `uploadedBy == 当前用户` 或 admin 可见。
    不可见返回 **404**（不返回 403，避免探测文件名是否存在）。
    响应头追加 `X-Content-Type-Options: nosniff`（禁止浏览器 MIME 嗅探）。
    """
    path = _resolve_upload(filename)
    visible = services.build_visibility(db, user).file_visible(os.path.basename(filename or ""))
    if not visible:
        raise HTTPException(404, "文件不存在或已被删除")
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # 还原原始文件名：查 file_meta，无记录用散列名兜底；MIME 仍按扩展名
    m = db.get(models.FileMeta, filename)
    orig = (m.name if (m and m.name) else filename)
    quoted = urllib.parse.quote(orig)
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path, media_type=mime,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quoted}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/upload/{filename}")
def delete_file(filename: str, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_editor)):
    # 引用完整性：仍被产品「产品清单/功能清单」引用的文件禁止删除（删后详情页预览/下载 404）
    ref = db.query(models.Asset).filter(
        (models.Asset.contractFile == filename) | (models.Asset.featureDoc == filename)
    ).first()
    if ref is not None:
        raise HTTPException(400, f"该文件仍被产品「{ref.name}」引用（产品清单/功能清单），请先修改产品附件后再删除")
    # ADR-024：仍被交付物附件（asset_deliverables.file）引用的文件禁止删除
    dref = db.query(models.AssetDeliverable).filter(models.AssetDeliverable.file == filename).first()
    if dref is not None:
        a = db.get(models.Asset, dref.asset_id)
        aname = a.name if a else str(dref.asset_id)
        raise HTTPException(400, f"该文件仍被产品「{aname}」的交付物「{dref.name}」引用（交付物附件），请先移除交付物附件后再删除")
    path = _resolve_upload(filename)
    os.remove(path)
    # 同步清理 file_meta 原名映射（无行则忽略，幂等）
    m = db.get(models.FileMeta, filename)
    if m is not None:
        db.delete(m)
    security.record_audit(db, user, "user_mgmt", "删除上传文件", "file", filename)
    db.commit()
    return {"ok": True}
