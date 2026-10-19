"""REST API 路由（前缀 /api），字段契约对齐前端 src/api/index.ts

权限管控（2026-10-15；2026-10-16 文件端点补鉴权）：
- 除 POST /auth/login、GET /health 外，所有端点均需
  `Authorization: Bearer <jwt>`（依赖逐个明确挂载，不用 router 级全挂）。
- GET /files/{filename} 走双通道认证（get_file_user）：优先 Bearer 头，
  无头时接受 `?token=<jwt>` 查询参数（iframe/img 无法带请求头）。
- 读接口三角色均可（get_current_user）；业务写接口 admin+editor（require_editor）；
  账号管理/审计查询仅 admin（require_admin）。
- 下单链路（2026-10-16 权限矩阵调整）：购物车全部 7 端点 + POST /sales/order 用
  require_order（已认证即可，viewer/生态人员放行）。
- 审计在 router 层统一 record_audit（业务 services 不动，降低回归风险）。
"""
import mimetypes
import os
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
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
ALLOWED_EXT = {"pdf", "doc", "docx", "png", "jpg", "jpeg", "gif", "webp", "xlsx"}
MAX_SIZE = 20 * 1024 * 1024  # 20MB


@router.get("/health")
def health():
    return {"status": "ok", "service": "core-holdings"}


# ============================================================
# 认证
# ============================================================
@router.post("/auth/login")
def login(data: schemas.LoginInput, db: Session = Depends(get_db)):
    # 登录失败限流：同一用户名 15 分钟内失败 ≥10 次锁定（防撞库）
    if security.login_locked(data.username):
        security.record_audit(db, None, "auth", "登录拦截", "auth", data.username, "失败次数过多，临时锁定")
        raise HTTPException(429, "登录失败次数过多，请 15 分钟后再试")
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if user is not None and not user.enabled:
        security.login_failed(data.username)
        security.record_audit(db, None, "auth", "登录失败", "auth", data.username, "账号已被禁用")
        raise HTTPException(401, "账号已被禁用")
    if user is None or not security.verify_password(data.password, user.passwordHash):
        security.login_failed(data.username)
        security.record_audit(db, None, "auth", "登录失败", "auth", data.username, "用户名或密码错误")
        raise HTTPException(401, "用户名或密码错误")
    security.login_succeeded(data.username)
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
def user_options(db: Session = Depends(get_db), _: models.User = Depends(security.get_current_user)):
    """商务账号选项（ADR-012 §5.1）：editor + admin 有效账号，
    供「商务负责人」筛选/接手转交下拉与商务 username→姓名 展示映射（商务负责人与角色账号的关联查询）"""
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
    # viewer（生态人员）可编辑自己下单的项目——归属/rep 不可改约束在 services.update_project 内
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
    """订单审核（ADR-012，仅商务/管理员）：确认下单（可带行级改价，实际价同步写回平台挂牌价）
    / 驳回（释放锁定 + 项目终止 + 原因留痕）。生态人员 403（require_editor 拦截）。
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


@router.post("/projects/{project_id}/resubmit", response_model=schemas.ProjectOut)
def resubmit_project(project_id: int, data: schemas.ProjectInput, db: Session = Depends(get_db),
                     user: models.User = Depends(security.require_order)):
    """重新提交（2026-10-20）：已终止项目（驳回/取消/终止）按（可修改的）明细新建 pending 订单，
    旧项目保留终止历史。viewer 仅自己下单的项目（后端 creator 守卫兜底）。"""
    p = services.resubmit_project(db, project_id, data, operator=user.username, user=user)
    security.record_audit(db, user, "sale", "重新提交销售项目", "project", p.name)
    return p


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
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
def revert_outbound(outbound_id: int, request: dict, db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_editor)):
    ob = db.get(models.Outbound, outbound_id)
    name = ob.assetName if ob else str(outbound_id)
    services.revert_outbound(db, outbound_id, request.get("reason", ""), operator=user.username)
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


@router.put("/cart/{cart_id}")
def set_cart_qty(cart_id: int, request: dict, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_order)):
    # ADR-008：可选携带 amount（包量计价合同金额，整数元；unit 模式忽略）
    services.set_cart_qty(db, cart_id, int(request.get("qty", 0)), user_id=str(user.id),
                          amount=request.get("amount"))
    return {"ok": True}


@router.patch("/cart/{cart_id}")
def patch_cart_item(cart_id: int, data: schemas.CartPatchInput, db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_order)):
    """修改购物车行级客户（ADR-007）；可选携带合同金额（ADR-008）"""
    services.patch_cart_item(db, cart_id, data.customer, user_id=str(user.id), amount=data.amount)
    security.record_audit(db, user, "sale", "修改购物车客户", "cart", str(cart_id), f"customer={data.customer}")
    return {"ok": True}


@router.delete("/cart/{cart_id}")
def remove_cart_item(cart_id: int, db: Session = Depends(get_db),
                     user: models.User = Depends(security.require_order)):
    services.remove_cart_item(db, cart_id, user_id=str(user.id))
    return {"ok": True}


@router.delete("/cart")
def clear_cart(db: Session = Depends(get_db), user: models.User = Depends(security.require_order)):
    services.clear_cart(db, user_id=str(user.id))


@router.post("/cart/checkout", response_model=schemas.ProjectOut)
def checkout(data: schemas.CheckoutInput, db: Session = Depends(get_db),
             user: models.User = Depends(security.require_order)):
    """购物车结算：按产品分组 → 每个产品一条销售记录（ADR-013）。
    【核心业务规则 ADR-012 修订 2026-10-19】所有角色结算统一建 **pending（待审核）**
    （数量锁定照常）→ 商务接手审核（改价确认/驳回）后生效；原「仅生态人员进 pending」的角色分叉已废除。
    is_viewer 现仅用于金额免填（生态人员 amount 模式行可留空回退挂牌价×数量）。"""
    is_viewer = user.role == "viewer"
    project = services.checkout(db, data, user_id=str(user.id), operator=user.username,
                                viewer=is_viewer)
    security.record_audit(db, user, "sale",
                          "购物车下单（待商务审核）" if is_viewer else "购物车结算",
                          "project", project.name, project.code)
    return project


@router.post("/sales/order", response_model=schemas.ProjectOut)
def create_sale_order(data: schemas.SaleOrderInput, db: Session = Depends(get_db),
                      user: models.User = Depends(security.require_order)):
    """产品直接下单（任意角色）。
    【核心业务规则 ADR-012 修订 2026-10-19】统一建 **pending（待审核）**（锁定照常），
    商务接手审核（改价确认/驳回）后生效 active——与手动建单/购物车结算同口径。"""
    project = services.create_sale_order(db, data, operator=user.username)
    security.record_audit(db, user, "sale", "下单", "project", project.name, project.code)
    return project


# ============================================================
# 基础资料（kind: suppliers / customers / reps）
# ============================================================
_BASE_LABEL = {"suppliers": "供应商", "customers": "客户", "reps": "生态人员"}


@router.post("/bases/{kind}")
def add_base(kind: str, data: schemas.BaseRecordInput, db: Session = Depends(get_db),
             user: models.User = Depends(security.require_editor)):
    services.add_base(db, kind, data)
    label = _BASE_LABEL.get(kind, kind)
    security.record_audit(db, user, "setting", f"新增{label}", "base", data.name, f"kind={kind}")
    return {"ok": True}


@router.put("/bases/{kind}/{rec_id}")
def update_base(kind: str, rec_id: int, data: schemas.BaseRecordInput, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_editor)):
    services.update_base(db, kind, rec_id, data)
    label = _BASE_LABEL.get(kind, kind)
    security.record_audit(db, user, "setting", f"编辑{label}", "base", data.name, f"kind={kind}")
    return {"ok": True}


@router.delete("/bases/{kind}/{rec_id}")
def delete_base(kind: str, rec_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_editor)):
    r = db.get(models.BaseRecord, rec_id)
    name = r.name if r else str(rec_id)
    services.delete_base(db, kind, rec_id)
    label = _BASE_LABEL.get(kind, kind)
    security.record_audit(db, user, "setting", f"删除{label}", "base", name, f"kind={kind}")
    return {"ok": True}


# ============================================================
# 交付物模板（type 为中文产品类型，走 query 避免 path 编码问题）
# ============================================================
@router.post("/deliverable-templates")
def add_template_item(atype: str = Query(..., alias="type"),
                      data: schemas.DeliverableTemplateInput = ..., db: Session = Depends(get_db),
                      user: models.User = Depends(security.require_editor)):
    services.add_template_item(db, atype, data)
    security.record_audit(db, user, "setting", "新增交付物模板", "template", data.name, f"type={atype}")
    return {"ok": True}


@router.put("/deliverable-templates/{item_id}")
def update_template_item(item_id: int, atype: str = Query(..., alias="type"),
                         data: schemas.DeliverableTemplateInput = ..., db: Session = Depends(get_db),
                         user: models.User = Depends(security.require_editor)):
    services.update_template_item(db, atype, item_id, data)
    security.record_audit(db, user, "setting", "编辑交付物模板", "template", data.name, f"type={atype}")
    return {"ok": True}


@router.delete("/deliverable-templates/{item_id}")
def delete_template_item(item_id: int, atype: str = Query(..., alias="type"), db: Session = Depends(get_db),
                         user: models.User = Depends(security.require_editor)):
    t = db.get(models.DeliverableTemplate, item_id)
    name = t.name if t else str(item_id)
    services.delete_template_item(db, atype, item_id)
    security.record_audit(db, user, "setting", "删除交付物模板", "template", name, f"type={atype}")
    return {"ok": True}


# ============================================================
# 产品交付物
# ============================================================
@router.post("/assets/{asset_id}/deliverables")
def add_asset_deliverable(asset_id: int, data: schemas.AssetDeliverableInput, db: Session = Depends(get_db),
                          user: models.User = Depends(security.require_editor)):
    services.add_asset_deliverable(db, asset_id, data)
    security.record_audit(db, user, "setting", "新增交付物", "deliverable", data.name, f"assetId={asset_id}")
    return {"ok": True}


@router.put("/assets/{asset_id}/deliverables/{item_id}")
def update_asset_deliverable(asset_id: int, item_id: int, request: dict, db: Session = Depends(get_db),
                             user: models.User = Depends(security.require_editor)):
    services.update_asset_deliverable(db, asset_id, item_id, request)
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
    orig = file.filename or ""
    ext = orig.rsplit(".", 1)[-1].lower() if "." in orig else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的文件格式：.{ext or '?'}（支持 pdf/doc/docx/图片/xlsx）")
    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容为空")
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "文件过大（上限 20MB）")
    fname = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
        f.write(content)
    # 落盘成功后写原名映射（上传不是产品操作，不写 OpLog）
    services.add_file_meta(db, fname, orig, len(content), user.username)
    return {"filename": fname, "name": orig, "size": len(content), "storedName": fname}


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
    复用 security.jwt_decode 校验（不改动其签名），失败一律 401。"""
    raw = (credentials.credentials if credentials is not None else "") or (token or "")
    if not raw:
        raise HTTPException(401, "未登录或登录已过期")
    payload = security.jwt_decode(raw)
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        raise HTTPException(401, "未登录或登录已过期")
    user = db.get(models.User, user_id)
    if user is None or not user.enabled:
        raise HTTPException(401, "未登录或登录已过期")
    return user


@router.get("/files/{filename}")
def get_file(filename: str, inline: bool = Query(False, description="true 时内联预览（Content-Disposition: inline），缺省下载"),
             db: Session = Depends(get_db),
             user: models.User = Depends(get_file_user)):
    path = _resolve_upload(filename)
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # 还原原始文件名：查 file_meta，无记录用散列名兜底；MIME 仍按扩展名
    m = db.get(models.FileMeta, filename)
    orig = (m.name if (m and m.name) else filename)
    quoted = urllib.parse.quote(orig)
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path, media_type=mime,
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quoted}"},
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
    path = _resolve_upload(filename)
    os.remove(path)
    # 同步清理 file_meta 原名映射（无行则忽略，幂等）
    m = db.get(models.FileMeta, filename)
    if m is not None:
        db.delete(m)
    security.record_audit(db, user, "user_mgmt", "删除上传文件", "file", filename)
    db.commit()
    return {"ok": True}
