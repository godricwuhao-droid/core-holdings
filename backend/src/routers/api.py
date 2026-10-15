"""REST API 路由（前缀 /api），字段契约对齐前端 src/api/index.ts

权限管控（2026-10-15）：
- 除 POST /auth/login、GET /health、GET /files/{filename} 外，所有端点均需
  `Authorization: Bearer <jwt>`（依赖逐个明确挂载，不用 router 级全挂）。
- 读接口三角色均可（get_current_user）；业务写接口 admin+editor（require_editor）；
  账号管理/审计查询仅 admin（require_admin）。
- 审计在 router 层统一 record_audit（业务 services 不动，降低回归风险）。
"""
import mimetypes
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas, security, services
from ..database import get_db

router = APIRouter(prefix="/api")

# ============================================================
# 文件上传 / 访问（合同文件等）
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
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
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if user is not None and not user.enabled:
        security.record_audit(db, None, "auth", "登录失败", "auth", data.username, "账号已被禁用")
        raise HTTPException(401, "账号已被禁用")
    if user is None or not security.verify_password(data.password, user.passwordHash):
        security.record_audit(db, None, "auth", "登录失败", "auth", data.username, "用户名或密码错误")
        raise HTTPException(401, "用户名或密码错误")
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
def bootstrap(db: Session = Depends(get_db), _: models.User = Depends(security.get_current_user)):
    return services.bootstrap(db)


# ============================================================
# 资产（写：admin+editor）
# ============================================================
@router.post("/assets", response_model=schemas.AssetOut)
def create_asset(data: schemas.AssetInput, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_editor)):
    asset = services.create_asset(db, data)
    security.record_audit(db, user, "asset_change", "新增资产", "asset", asset.name, asset.code)
    return asset


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, request: dict, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_editor)):
    services.update_asset(db, asset_id, request)
    a = db.get(models.Asset, asset_id)
    security.record_audit(db, user, "asset_change", "编辑资产", "asset", a.name if a else str(asset_id))
    return {"ok": True}


# 注：已移除 PATCH /assets/{asset_id}/status（M6）——资产状态改为纯 2 态自动判定，
# 前端从不调用该端点（已确认），保留会与自动判定逻辑冲突。


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(security.require_editor)):
    a = db.get(models.Asset, asset_id)
    name = a.name if a else str(asset_id)
    services.delete_asset(db, asset_id)
    security.record_audit(db, user, "asset_change", "删除资产", "asset", name)
    return {"ok": True}


# ============================================================
# 销售项目（写：admin+editor）
# ============================================================
@router.post("/projects", response_model=schemas.ProjectOut)
def create_project(data: schemas.ProjectInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    project = services.create_project(db, data)
    security.record_audit(db, user, "sale", "新建销售项目", "project", project.name, project.code)
    return project


@router.put("/projects/{project_id}")
def update_project(project_id: int, data: schemas.ProjectInput, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    services.update_project(db, project_id, data)
    p = db.get(models.Project, project_id)
    security.record_audit(db, user, "sale", "编辑销售项目", "project", p.name if p else str(project_id))
    return {"ok": True}


@router.patch("/projects/{project_id}/status")
def change_project_status(project_id: int, data: schemas.StatusInput, db: Session = Depends(get_db),
                          user: models.User = Depends(security.require_editor)):
    services.change_project_status(db, project_id, data)
    p = db.get(models.Project, project_id)
    security.record_audit(db, user, "sale", "变更项目状态", "project",
                          p.name if p else str(project_id), f"status={data.status}")
    return {"ok": True}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(security.require_editor)):
    p = db.get(models.Project, project_id)
    name = p.name if p else str(project_id)
    services.delete_project(db, project_id)
    security.record_audit(db, user, "sale", "删除销售项目", "project", name)
    return {"ok": True}


# ============================================================
# 出库（写：admin+editor）
# ============================================================
@router.post("/outbounds", response_model=schemas.OutboundOut)
def create_outbound(data: schemas.OutboundInput, db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_editor)):
    ob = services.create_outbound(db, data)
    security.record_audit(db, user, "outbound", "新出库", "outbound", ob.assetName, ob.code)
    return ob


@router.post("/outbounds/{outbound_id}/revert")
def revert_outbound(outbound_id: int, request: dict, db: Session = Depends(get_db),
                    user: models.User = Depends(security.require_editor)):
    ob = db.get(models.Outbound, outbound_id)
    name = ob.assetName if ob else str(outbound_id)
    services.revert_outbound(db, outbound_id, request.get("reason", ""))
    security.record_audit(db, user, "outbound", "撤销出库", "outbound", name)
    return {"ok": True}


# ============================================================
# 购物车（user_id 保持 DEFAULT_USER="admin"，本轮不按登录用户隔离）
# ============================================================
@router.post("/cart", response_model=schemas.CartItemOut)
def add_to_cart(data: schemas.CartItemInput, db: Session = Depends(get_db),
                _: models.User = Depends(security.require_editor)):
    return services.add_to_cart(db, data)


@router.post("/cart/batch", response_model=schemas.CartBatchResult)
def add_to_cart_batch(data: schemas.CartBatchInput, db: Session = Depends(get_db),
                      _: models.User = Depends(security.require_editor)):
    return services.add_to_cart_batch(db, data)


@router.put("/cart/{cart_id}")
def set_cart_qty(cart_id: int, request: dict, db: Session = Depends(get_db),
                 _: models.User = Depends(security.require_editor)):
    services.set_cart_qty(db, cart_id, int(request.get("qty", 0)))
    return {"ok": True}


@router.delete("/cart/{cart_id}")
def remove_cart_item(cart_id: int, db: Session = Depends(get_db),
                     _: models.User = Depends(security.require_editor)):
    services.remove_cart_item(db, cart_id)
    return {"ok": True}


@router.delete("/cart")
def clear_cart(db: Session = Depends(get_db), _: models.User = Depends(security.require_editor)):
    services.clear_cart(db)


@router.post("/cart/checkout", response_model=schemas.ProjectOut)
def checkout(data: schemas.CheckoutInput, db: Session = Depends(get_db),
             user: models.User = Depends(security.require_editor)):
    project = services.checkout(db, data)
    security.record_audit(db, user, "sale", "购物车结算", "project", project.name, project.code)
    return project


@router.post("/sales/order", response_model=schemas.ProjectOut)
def create_sale_order(data: schemas.SaleOrderInput, db: Session = Depends(get_db),
                      user: models.User = Depends(security.require_editor)):
    project = services.create_sale_order(db, data)
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
# 交付物模板（type 为中文资产类型，走 query 避免 path 编码问题）
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
# 资产交付物
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
async def upload_file(file: UploadFile = File(...), _: models.User = Depends(security.require_editor)):
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
    return {"filename": fname, "name": orig, "size": len(content)}


def _resolve_upload(name: str) -> str:
    base = os.path.basename(name or "")
    if not base or base in (".", ".."):
        raise HTTPException(400, "非法文件名")
    path = os.path.join(UPLOAD_DIR, base)
    if not os.path.isfile(path):
        raise HTTPException(404, "文件不存在或已被删除")
    return path


@router.get("/files/{filename}")
def get_file(filename: str):
    path = _resolve_upload(filename)
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime)


@router.delete("/upload/{filename}")
def delete_file(filename: str, db: Session = Depends(get_db),
                user: models.User = Depends(security.require_editor)):
    path = _resolve_upload(filename)
    os.remove(path)
    security.record_audit(db, user, "user_mgmt", "删除上传文件", "file", filename)
    return {"ok": True}
