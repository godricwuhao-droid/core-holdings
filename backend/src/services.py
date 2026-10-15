"""业务服务层：复刻前端 mock/store.ts 的全部业务规则

- 可售数量 = 入库 - 锁定 - 已出库；可重复售卖资产不扣减
- 状态仅 2 种（库存可售 / 全部出售），由数量自动判定
- 项目关联资产→锁定；合同签订→确认销售；交付完成→出库+累计销售；终止→释放锁定
- 出库撤销→反向流水；历史补录不扣库存
"""
import uuid
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas


# ============================================================
# 常量与工具
# ============================================================
BOARD_CODE = {
    "embodied": "EMB",
    "satellite": "SAT",
    "software": "SW",
    "hardware": "HW",
    "compute": "CMP",
}

PROJECT_FLOW = ["active", "delivered"]


def today() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _flush_with_code(db: Session, obj, code_fmt) -> None:
    """插入对象 → flush 由 DB 分配自增主键 → 再用生成的 id 拼写唯一编号 code。

    WHY：原实现用 next_id()（max(id)+1）手工指定主键，而 session 为 autoflush=False，
    循环内多次 db.add 不 flush 会拿到相同 id / code，commit 时唯一约束冲突（D1）。
    改为不手写主键、交由 DB 自增，flush 后取 obj.id 生成 code（flush 前先放一个唯一占位符，
    以免 code NOT NULL 约束报错；占位符不会提交，仅在事务内短暂存在）。
    """
    obj.code = uuid.uuid4().hex  # 唯一占位（不会提交）
    db.add(obj)
    db.flush()                  # DB 生成自增 id
    obj.code = code_fmt(obj.id)  # 用真实 id 拼写正式编号；UPDATE 在本次 flush/commit 落库


def get_asset(db: Session, asset_id: int | None) -> models.Asset | None:
    if not asset_id:
        return None
    return db.get(models.Asset, asset_id)


def get_project(db: Session, project_id: int | None) -> models.Project | None:
    if not project_id:
        return None
    return db.get(models.Project, project_id)


def add_flow(db: Session, asset_id: int, type: str, qty: int, unit: str,
             amount: float, date: str, ref: str, note: str) -> None:
    db.add(models.AssetFlow(
        assetId=asset_id, type=type, qty=qty, unit=unit,
        amount=amount, date=date, ref=ref, note=note,
    ))


def add_log(db: Session, target: str, target_name: str, action: str, detail: str,
            asset_id: int | None = None) -> None:
    db.add(models.OpLog(
        target=target, targetName=target_name, action=action,
        detail=detail, operator="admin", time=now_str(),
        assetId=asset_id if target == "asset" else None,
    ))


def auto_status(a: models.Asset) -> str:
    # 与前端 types.ts noSellableStock 完全一致：非可重复售卖且（库存-锁定-已出库）<=0 → 全部出售
    no_sellable = (not a.repeatSale) and (a.quantity - a.lockedQty - a.shippedQty) <= 0
    return "all_sold" if no_sellable else "in_stock"


def refresh_status(a: models.Asset) -> None:
    a.status = auto_status(a)
    a.updatedAt = today()


def item_status_of_input(it: schemas.ProjectItemInput) -> str:
    # H4：不再以金额是否为 0 判定。已关联资产即可锁定（含零价明细，交付时正常扣库存/出库）。
    # 注：pending_amount（待确认金额）自此不再产生，前端 ITEM_STATUS 中该项成为未使用枚举（预期）。
    if not it.assetId:
        return "pending_asset"
    return "locked"


def _validate_item_stock(a: models.Asset, qty: int) -> None:
    """H1：加锁前校验可售库存，避免超卖；负数量/零数量直接拒绝。

    可重复售卖资产不占用库存，跳过上限校验。
    """
    if qty <= 0:
        raise HTTPException(400, f"数量必须大于 0（{a.name}）")
    if a.repeatSale:
        return
    available = a.quantity - a.lockedQty - a.shippedQty
    if qty > available:
        raise HTTPException(400, f"库存不足：{a.name} 可售 {available}{a.unit}，本单需 {qty}")


def apply_item_lock(db: Session, asset_id: int | None, qty: int, add: bool, ref: str) -> None:
    a = get_asset(db, asset_id)
    if not a or a.repeatSale or qty <= 0:
        return
    a.lockedQty = max(0, a.lockedQty + (qty if add else -qty))
    add_flow(
        db, a.id,
        "project_lock" if add else "cancel_release",
        qty, a.unit, 0, today(), ref,
        "销售项目锁定" if add else "项目释放锁定",
    )
    refresh_status(a)


def _default_outbound_type(board: str) -> str:
    if board == "satellite":
        return "data_auth"
    if board == "software":
        return "software_auth"
    if board == "compute":
        return "service"
    return "physical"


# ============================================================
# 资产
# ============================================================
def create_asset(db: Session, data: schemas.AssetInput) -> models.Asset:
    asset = models.Asset(
        lockedQty=0, shippedQty=0, soldAmount=0, soldCount=0,
        name=data.name, board=data.board, type=data.type, subject=data.subject,
        unit=data.unit, quantity=data.quantity, repeatSale=data.repeatSale,
        salePrice=data.salePrice, status=data.status,
        inboundDate=data.inboundDate, expiryDate=data.expiryDate,
        perpetual=data.perpetual, spec=data.spec, saleDetail=data.saleDetail,
        contractFile=data.contractFile,
        remark=data.remark, updatedAt=today(),
    )
    # 不手写主键：flush 由 DB 生成 id，再据此拼写编号，编号格式保持 CH-{板块}-{3位序号}
    _flush_with_code(db, asset, lambda aid: f"CH-{BOARD_CODE.get(data.board, 'GEN')}-{str(aid).zfill(3)}")
    # 新登记资产即已入库（库存可售口径）
    add_flow(db, asset.id, "purchase_in", asset.quantity, asset.unit, 0,
             data.inboundDate or today(), asset.code, "入库")
    add_log(db, "asset", asset.name, "新增资产",
            f"新建资产 {asset.code}，状态：{'库存可售' if asset.status == 'in_stock' else '全部出售'}",
            asset_id=asset.id)
    db.commit()
    db.refresh(asset)
    return asset


def update_asset(db: Session, asset_id: int, patch: dict) -> None:
    a = get_asset(db, asset_id)
    if not a:
        raise HTTPException(404, "资产不存在")
    allowed = {"name", "board", "type", "subject", "unit", "quantity", "repeatSale",
               "salePrice", "status", "inboundDate", "expiryDate", "perpetual",
               "spec", "saleDetail", "contractFile", "remark"}
    old_repeat = a.repeatSale
    for k, v in patch.items():
        if k in allowed:
            setattr(a, k, v)
    # BUG1 修复：repeatSale false→true 时，存量 lockedQty 残留会成为"幽灵锁定"
    # （apply_item_lock 对 repeatSale 资产直接 return，交付/终止都无法释放）。
    # 故切换瞬间清零 lockedQty 并留痕；lockedQty=0 时无事发生不打日志。
    # true→false 不做任何库存动作（历史未锁明细由 item.locked 标记区分）。
    if (not old_repeat) and a.repeatSale and a.lockedQty > 0:
        old_locked = a.lockedQty
        a.lockedQty = 0
        add_log(db, "asset", a.name, "清零锁定",
                f"repeatSale 切换为 true，清零存量锁定 {old_locked}{a.unit}（可重复售卖不再占用库存）",
                asset_id=a.id)
    refresh_status(a)
    add_log(db, "asset", a.name, "编辑", "更新资产信息", asset_id=a.id)
    db.commit()


def delete_asset(db: Session, asset_id: int) -> None:
    a = get_asset(db, asset_id)
    if not a:
        return
    # H7：引用完整性校验（SQLite 不加外键——迁移风险高；改用服务层校验实现同等约束）
    # 1) 被任何非 terminated 项目的明细引用 → 拒绝
    ref_item = db.execute(
        select(models.ProjectItem)
        .join(models.Project, models.Project.id == models.ProjectItem.project_id)
        .where(models.ProjectItem.assetId == asset_id, models.Project.status != "terminated")
        .limit(1)
    ).scalars().first()
    # 2) 存在 status='done' 的出库记录引用 → 拒绝
    ref_ob = db.execute(
        select(models.Outbound)
        .where(models.Outbound.assetId == asset_id, models.Outbound.status == "done")
        .limit(1)
    ).scalars().first()
    if ref_item or ref_ob:
        raise HTTPException(400, "该资产仍被销售项目或出库记录引用，请先终止相关项目/撤销出库后再删除")
    # 3) 清理引用了该资产的购物车项
    for c in db.execute(select(models.CartItem).where(models.CartItem.assetId == asset_id)).scalars():
        db.delete(c)
    # 4) 级联删除该资产的交付物 + 流水
    for d in list(a.deliverables):
        db.delete(d)
    for f in db.execute(select(models.AssetFlow).where(models.AssetFlow.assetId == asset_id)).scalars():
        db.delete(f)
    name, code = a.name, a.code
    db.delete(a)
    add_log(db, "asset", name, "删除", f"删除资产 {code}", asset_id=asset_id)
    db.commit()


# ============================================================
# 销售项目
# ============================================================
def create_project(db: Session, data: schemas.ProjectInput) -> models.Project:
    project = _create_project_core(db, data)
    db.commit()
    db.refresh(project)
    return project


def _create_project_core(db: Session, data: schemas.ProjectInput) -> models.Project:
    """建项目核心（不提交）：校验库存 → 生成项目（状态强制 active）→ 锁定明细。

    抽成 core 供 create_project / checkout / sales order 复用，以收敛为单一事务（H8）。
    """
    project = models.Project(
        name=data.name, customer=data.customer, industry=data.industry, rep=data.rep,
        subject=data.subject, status="active",  # 契约 3：不采信请求体 status，后端强制 active
        expectedAmount=data.expectedAmount, quoteAmount=data.quoteAmount,
        contractAmount=data.contractAmount, paidAmount=data.paidAmount,
        expectedSignDate=data.expectedSignDate, lastFollowDate=data.lastFollowDate,
        remark=data.remark, createdAt=today(), updatedAt=today(),
    )
    # D1：不手写主键，flush 生成 id 后拼 SP-{3位} 编号
    _flush_with_code(db, project, lambda pid: f"SP-{str(pid).zfill(3)}")
    # H1：先整体校验库存，再统一加锁，避免部分加锁后中途失败
    # 超卖修复（H10）：校验必须**按 assetId 聚合**本单需求量后再比较可售。
    # WHY：同一项目可能含多条引用同一 assetId 的明细（如 qty 各 1、可售仅 1），
    # 逐条按"全量可售"校验会全部通过，合计却超卖/超锁；故先汇总该资产在本单的 qty 合计。
    validated: list[tuple[schemas.ProjectItemInput, models.Asset | None]] = []
    demand: dict[int, int] = {}
    for it in data.items:
        asset = get_asset(db, it.assetId)
        validated.append((it, asset))
        if it.assetId:
            demand[it.assetId] = demand.get(it.assetId, 0) + it.qty
    for aid, total_qty in demand.items():
        asset = get_asset(db, aid)
        if asset is not None:
            _validate_item_stock(asset, total_qty)
    for it, asset in validated:
        status = item_status_of_input(it)
        if status == "locked":
            apply_item_lock(db, it.assetId, it.qty, True, project.code)
        project.items.append(models.ProjectItem(
            assetId=it.assetId, qty=it.qty, unit=asset.unit if asset else "",
            price=it.price, amount=round(it.price * it.qty, 4),  # 契约 5：后端权威重算，忽略前端 amount
            status=status, deliveryReq=it.deliveryReq,
            # 契约 2：落「下单时刻是否真实加锁」事实（repeatSale 资产下单不加锁）
            locked=bool(asset is not None and not asset.repeatSale),
            lockedDate=today() if status == "locked" else "",
            confirmedDate="", shippedDate="",
        ))
    add_log(db, "project", project.name, "新增项目",
            f"创建销售项目 {project.code}，关联资产 {len(data.items)} 项")
    db.flush()
    return project


def update_project(db: Session, project_id: int, data: schemas.ProjectInput) -> None:
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    # 契约 4 / H2 / H3：仅进行中项目可编辑；忽略传入 status（不写入 p.status）
    if p.status != "active":
        raise HTTPException(400, "已完成/已终止项目不可编辑")
    # 1. 释放旧明细中的锁定（仅已锁定/已确认）；仅 it.locked（下单时真实加锁）才释放，
    # 与交付/终止分支同一根因：repeatSale 期间下单的明细从未加锁，不可写幽灵 cancel_release
    for it in list(p.items):
        if it.status in ("locked", "confirmed") and it.locked:
            apply_item_lock(db, it.assetId, it.qty, False, p.code)
    # 2. 覆盖基础字段（不含 status）
    for k in ("name", "customer", "industry", "rep", "subject",
              "expectedAmount", "quoteAmount", "contractAmount", "paidAmount",
              "expectedSignDate", "lastFollowDate", "remark"):
        setattr(p, k, getattr(data, k))
    p.updatedAt = today()
    # 3. 重建明细：H2 保留已出库(shipped)明细不被误删/误改 shippedQty，仅删除其余明细
    for it in list(p.items):
        if it.status != "shipped":
            db.delete(it)
    db.flush()
    # 4. H1：释放旧锁定之后再校验新明细库存（避免把本单自身占用算进可售）
    # 超卖修复（H10）：同样按 assetId 聚合新明细需求量后校验；旧明细已在上方释放锁定并删除，
    # 故只需按新明细聚合即可，不会把本单旧占用重复计入。
    validated: list[tuple[schemas.ProjectItemInput, models.Asset | None]] = []
    demand: dict[int, int] = {}
    for it in data.items:
        asset = get_asset(db, it.assetId)
        validated.append((it, asset))
        if it.assetId:
            demand[it.assetId] = demand.get(it.assetId, 0) + it.qty
    for aid, total_qty in demand.items():
        asset = get_asset(db, aid)
        if asset is not None:
            _validate_item_stock(asset, total_qty)
    for it, asset in validated:
        status = item_status_of_input(it)
        if status == "locked":
            apply_item_lock(db, it.assetId, it.qty, True, p.code)
        p.items.append(models.ProjectItem(
            assetId=it.assetId, qty=it.qty, unit=asset.unit if asset else "",
            price=it.price, amount=round(it.price * it.qty, 4),  # 契约 5：后端权威重算
            status=status, deliveryReq=it.deliveryReq,
            # 契约 2：重建明细同样落「下单时刻是否真实加锁」事实
            locked=bool(asset is not None and not asset.repeatSale),
            lockedDate=today() if status == "locked" else "",
            confirmedDate="", shippedDate="",
        ))
    add_log(db, "project", p.name, "编辑", "更新销售项目")
    db.commit()


def change_project_status(db: Session, project_id: int, data: schemas.StatusInput) -> None:
    _change_project_status_core(db, project_id, data)
    db.commit()


def _change_project_status_core(db: Session, project_id: int, data: schemas.StatusInput) -> None:
    """项目状态变更核心（不提交），供 API 与下单流程复用，便于收敛为单一事务（H8）。"""
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    status, reason = data.status, data.reason
    from_status = p.status
    if status != from_status:
        if from_status == "terminated":
            raise HTTPException(400, "项目已终止，不可再变更状态")
        if status not in ("active", "delivered", "terminated"):
            raise HTTPException(400, f"不支持的项目状态：{status}")
        # 已完成不可回退到进行中；进行中 / 已完成均可终止
        if from_status == "delivered" and status == "active":
            raise HTTPException(400, "已交付完成的项目不可回退到进行中")
    p.status = status
    p.updatedAt = today()

    if status == "delivered":
        for it in p.items:
            # H4：locked/confirmed 均处理（含零价 amount=0 明细），不再因金额为 0 被跳过
            if it.status in ("confirmed", "locked"):
                a = get_asset(db, it.assetId)
                if a:
                    if a.repeatSale:
                        a.soldCount += 1
                    else:
                        # BUG2 修复：仅当下单时真实加锁（it.locked）才释放锁定，
                        # 消灭 repeatSale 期间下单（从未加锁）→ 改回 false → 交付时的幽灵释放
                        if it.locked:
                            apply_item_lock(db, it.assetId, it.qty, False, p.code)
                        # 防御存量脏数据：shippedQty 不得超 quantity（正常路径 locked 守恒时 min 不生效）
                        a.shippedQty = min(a.quantity, a.shippedQty + it.qty)
                    a.soldAmount = round(a.soldAmount + it.amount, 4)  # 契约 5：万元 4 位小数，禁止夹零
                    refresh_status(a)
                    add_flow(db, a.id, "sale_out", it.qty, a.unit, it.amount,
                             today(), p.code, "项目交付完成出库")
                    # D1：不手写主键；flush 由 DB 生成 id 后再拼出库单号，循环内逐条唯一
                    ob = models.Outbound(
                        projectId=p.id, projectName=p.name, customer=p.customer,
                        assetId=a.id, assetName=a.name, qty=it.qty, unit=a.unit,
                        amount=it.amount, type=_default_outbound_type(a.board),
                        mode="new", date=today(), operator=p.rep or "admin",
                        status="done", remark=f"项目「{p.name}」交付完成自动生成",
                    )
                    _flush_with_code(db, ob, lambda oid: f"CK-{str(oid).zfill(4)}")
                it.status = "shipped"
                it.shippedDate = today()
        add_log(db, "project", p.name, "状态变更", "交付完成，已生成出库记录并累计销售金额")

    if status == "terminated":
        _terminate_project(db, p, reason)


def _terminate_project(db: Session, p: models.Project, reason: str) -> None:
    """项目终止：释放未出库的锁定 + 撤销该项目名下已完成的出库（回退 shippedQty/soldAmount/soldCount）。"""
    released = 0
    for it in p.items:
        if it.status in ("locked", "confirmed"):
            # BUG2 修复：仅当下单时真实加锁（it.locked）才释放，
            # 消灭 repeatSale 期间下单（从未加锁）→ 终止时的 cancel_release 幽灵流水
            if it.locked:
                apply_item_lock(db, it.assetId, it.qty, False, p.code)
            it.status = "released"
            released += 1
    # 撤销该项目名下所有已完成出库（含交付完成自动生成 + 手动登记）
    obs = db.execute(
        select(models.Outbound).where(
            models.Outbound.projectId == p.id,
            models.Outbound.status == "done",
        )
    ).scalars().all()
    for ob in obs:
        _revert_outbound_inner(db, ob.id, "项目终止")
    # 已出库明细标记为已释放
    for it in p.items:
        if it.status == "shipped":
            it.status = "released"
    add_log(db, "project", p.name, "状态变更",
            f"项目终止：释放锁定 {released} 项，撤销出库 {len(obs)} 条，回退对应数量与累计销售金额"
            + (f"，原因：{reason}" if reason else ""))


def delete_project(db: Session, project_id: int) -> None:
    """删除项目（D2）：先回滚（释放未出库锁定 + 撤销该项目名下所有 done 出库，
    回退 shippedQty/soldAmount/soldCount）→ 再硬删项目及其明细 → 写 OpLog。
    回滚直接复用 _terminate_project，不重复实现。单事务，任一步失败整体回滚（H8）。"""
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    name, code = p.name, p.code
    _terminate_project(db, p, "项目删除回滚")
    db.delete(p)  # 级联删除明细（Project.items: cascade delete-orphan）
    add_log(db, "project", name, "删除", f"删除项目 {code}（已回滚锁定与出库）")
    db.commit()


# ============================================================
# 出库
# ============================================================
def create_outbound(db: Session, data: schemas.OutboundInput) -> models.Outbound:
    a = get_asset(db, data.assetId)
    if not a:
        raise HTTPException(400, "资产不存在")
    p = get_project(db, data.projectId)
    # 防重复出库
    if p and data.mode == "new":
        items = [it for it in p.items if it.assetId == a.id]
        if items and all(it.status in ("shipped", "released") for it in items):
            raise HTTPException(400,
                f"项目「{p.name}」下该资产的明细已全部出库/释放，请勿重复登记；历史记录请改用「历史补录」")
    ob = models.Outbound(
        projectId=p.id if p else None,
        projectName=p.name if p else (f"补录-{data.customer}" if data.customer else "补录"),
        customer=p.customer if p else data.customer,
        assetId=a.id, assetName=a.name, qty=data.qty, unit=a.unit,
        amount=round(data.amount, 4), type=data.type, mode=data.mode, date=data.date,
        operator=data.operator or "admin", status="done", remark=data.remark,
    )
    # D1：flush 生成 id 后再拼 CK-{4位} 单号（不手写主键）
    _flush_with_code(db, ob, lambda oid: f"CK-{str(oid).zfill(4)}")
    if data.mode != "history":
        if a.repeatSale:
            a.soldCount += 1
        else:
            a.lockedQty = max(0, a.lockedQty - data.qty)
            a.shippedQty += data.qty
        a.soldAmount = round(a.soldAmount + ob.amount, 4)  # 契约 5：万元 4 位小数
        refresh_status(a)
    add_flow(
        db, a.id, "sale_out", data.qty, a.unit, ob.amount, data.date, ob.code,
        "历史出库补录（不扣减库存）" if data.mode == "history" else ("销售出库" if p else "出库补录"),
    )
    add_log(db, "outbound", a.name,
            "历史补录" if data.mode == "history" else "销售出库",
            f"{ob.code} 出库 {data.qty}{a.unit}，金额 {ob.amount} 万"
            + ("（不扣减库存）" if data.mode == "history" else ""))
    db.commit()
    db.refresh(ob)
    return ob


def _revert_outbound_inner(db: Session, outbound_id: int, reason: str) -> bool:
    """撤销出库（不提交事务，供批量回退复用）；返回是否实际撤销"""
    ob = db.get(models.Outbound, outbound_id)
    if not ob or ob.status == "reverted":
        return False
    a = get_asset(db, ob.assetId)
    ob.status = "reverted"
    if a and ob.mode != "history":
        if a.repeatSale:
            a.soldCount = max(0, a.soldCount - 1)
        else:
            a.shippedQty = max(0, a.shippedQty - ob.qty)
        # 契约 5：回退同样保留 4 位小数；不再用 max(0,...) 静默夹零（若为负将直接暴露）
        a.soldAmount = round(a.soldAmount - ob.amount, 4)
        refresh_status(a)
        add_flow(db, a.id, "manual_adjust", -ob.qty, a.unit, -ob.amount, today(), ob.code,
                 f"出库撤销：{reason}")
    elif a:
        add_flow(db, a.id, "manual_adjust", 0, a.unit, 0, today(), ob.code,
                 f"撤销历史补录（不调整库存）：{reason}")
    add_log(db, "outbound", ob.assetName, "出库撤销",
            f"{ob.code} 已撤销" + ("（历史补录，不调整库存）" if ob.mode == "history" else "") + f"，原因：{reason}")
    return True


def revert_outbound(db: Session, outbound_id: int, reason: str) -> None:
    _revert_outbound_inner(db, outbound_id, reason)
    db.commit()


# ============================================================
# 基础资料
# ============================================================
def add_base(db: Session, kind: str, data: schemas.BaseRecordInput) -> None:
    db.add(models.BaseRecord(kind=kind, name=data.name, contact=data.contact,
                             phone=data.phone, remark=data.remark))
    label = "供应商" if kind == "suppliers" else ("客户" if kind == "customers" else "生态人员")
    add_log(db, "setting", data.name, "新增", f"新增{label}")
    db.commit()


def update_base(db: Session, kind: str, rec_id: int, data: schemas.BaseRecordInput) -> None:
    r = db.get(models.BaseRecord, rec_id)
    if r and r.kind == kind:
        r.name, r.contact, r.phone, r.remark = data.name, data.contact, data.phone, data.remark
        db.commit()


def delete_base(db: Session, kind: str, rec_id: int) -> None:
    r = db.get(models.BaseRecord, rec_id)
    if r and r.kind == kind:
        db.delete(r)
        db.commit()


# ============================================================
# 交付物模板
# ============================================================
def add_template_item(db: Session, type: str, data: schemas.DeliverableTemplateInput) -> None:
    db.add(models.DeliverableTemplate(type=type, name=data.name, category=data.category,
                                      required=data.required, note=data.note))
    add_log(db, "setting", f"交付物模板 · {type}", "新增", f"新增交付物「{data.name}」")
    db.commit()


def update_template_item(db: Session, type: str, item_id: int, data: schemas.DeliverableTemplateInput) -> None:
    t = db.get(models.DeliverableTemplate, item_id)
    if t and t.type == type:
        t.name, t.category, t.required, t.note = data.name, data.category, data.required, data.note
        add_log(db, "setting", f"交付物模板 · {type}", "编辑", f"更新交付物「{data.name}」")
        db.commit()


def delete_template_item(db: Session, type: str, item_id: int) -> None:
    t = db.get(models.DeliverableTemplate, item_id)
    if t and t.type == type:
        name = t.name
        db.delete(t)
        add_log(db, "setting", f"交付物模板 · {type}", "删除", f"删除交付物「{name}」")
        db.commit()


# ============================================================
# 资产交付物（按模板惰性初始化）
# ============================================================
def _init_asset_deliverables(db: Session, a: models.Asset) -> list[models.AssetDeliverable]:
    if a.deliverables:
        return a.deliverables
    tpl = db.execute(select(models.DeliverableTemplate).where(models.DeliverableTemplate.type == a.type)).scalars().all()
    for t in tpl:
        a.deliverables.append(models.AssetDeliverable(
            asset_id=a.id, name=t.name, category=t.category, required=t.required,
            note=t.note, version="V1.0", meta=t.note,
            status="todo" if "验收" in t.name else "ready", updatedAt=a.updatedAt or today(),
        ))
    db.flush()
    return a.deliverables


def add_asset_deliverable(db: Session, asset_id: int, data: schemas.AssetDeliverableInput) -> None:
    a = get_asset(db, asset_id)
    _init_asset_deliverables(db, a) if a else None
    if a:
        a.deliverables.append(models.AssetDeliverable(
            asset_id=asset_id, name=data.name, category=data.category, required=data.required,
            note=data.note, version="V1.0", meta=data.note,
            status="todo" if "验收" in data.name else "ready", updatedAt=today(),
        ))
        # WHY：此前遗漏 asset_id，导致前端资产详情「操作记录」按 l.assetId === assetId 过滤时
        # 看不到这条「新增交付物」记录；与 update/remove_asset_deliverable 对齐补上 assetId。
        add_log(db, "asset", a.name, "新增交付物", f"新增交付物「{data.name}」", asset_id=a.id)
        db.commit()


def update_asset_deliverable(db: Session, asset_id: int, item_id: int, patch: dict) -> None:
    d = db.get(models.AssetDeliverable, item_id)
    a = get_asset(db, asset_id)
    if d and d.asset_id == asset_id:
        for k in ("name", "category", "required", "note", "version", "meta", "status"):
            if k in patch:
                setattr(d, k, patch[k])
        d.updatedAt = today()
        if a:
            add_log(db, "asset", a.name, "更新交付物", f"{d.name} 已更新（{d.version}）", asset_id=a.id)
        db.commit()


def remove_asset_deliverable(db: Session, asset_id: int, item_id: int) -> None:
    d = db.get(models.AssetDeliverable, item_id)
    a = get_asset(db, asset_id)
    if d and d.asset_id == asset_id:
        name = d.name
        db.delete(d)
        if a:
            add_log(db, "asset", a.name, "删除交付物", f"删除交付物「{name}」", asset_id=a.id)
        db.commit()


# ============================================================
# Bootstrap（一次性拉取全量，供前端填充响应式缓存）
# ============================================================
# ============================================================
# 购物车（预留 userId 维度，为后续账号权限管控做准备；当前默认 admin）
# ============================================================
DEFAULT_USER = "admin"


def _cart_list(db: Session, user_id: str) -> list[models.CartItem]:
    return db.execute(
        select(models.CartItem)
        .where(models.CartItem.userId == user_id)
        .order_by(models.CartItem.id.asc())
    ).scalars().all()


def _cart_qty_of(db: Session, user_id: str, asset_id: int) -> int:
    c = db.execute(
        select(models.CartItem).where(
            models.CartItem.userId == user_id,
            models.CartItem.assetId == asset_id,
        )
    ).scalar_one_or_none()
    return c.qty if c else 0


def _avail(a: models.Asset) -> int:
    """可售库存（可重复售卖资产由调用处先判 repeatSale，不参与上限校验）"""
    return max(0, a.quantity - a.lockedQty - a.shippedQty)


def _check_stock(db: Session, asset_id: int, target_qty: int) -> None:
    """校验目标数量不超过可售库存；可重复售卖资产不校验。超量抛 400。"""
    a = get_asset(db, asset_id)
    if a and not a.repeatSale and target_qty > _avail(a):
        raise HTTPException(
            400,
            f"「{a.name}」可售库存仅 {_avail(a)}{a.unit}，无法加入/设置为 {target_qty}{a.unit}，请调整数量",
        )


def _cart_subject(db: Session, user_id: str) -> str | None:
    """购物车当前主体（首个可解析资产的 subject）；购物车为空返回 None"""
    for c in _cart_list(db, user_id):
        a = get_asset(db, c.assetId)
        if a:
            return a.subject
    return None


def _check_entity(db: Session, user_id: str, a: models.Asset) -> None:
    """购物车仅允许同一主体资产；与现有主体不一致时抛 400"""
    cs = _cart_subject(db, user_id)
    if cs is not None and a.subject != cs:
        raise HTTPException(400, f"购物车内已有「{cs}」的资产，仅可添加同一主体；「{a.name}」属于「{a.subject}」")


def add_to_cart(db: Session, data: schemas.CartItemInput, user_id: str = DEFAULT_USER) -> models.CartItem:
    a = get_asset(db, data.assetId)
    if not a:
        raise HTTPException(404, "资产不存在")
    qty = max(1, int(data.qty or 1))
    cur = _cart_qty_of(db, user_id, data.assetId)
    _check_stock(db, data.assetId, cur + qty)
    _check_entity(db, user_id, a)
    existing = db.execute(
        select(models.CartItem).where(
            models.CartItem.userId == user_id,
            models.CartItem.assetId == data.assetId,
        )
    ).scalar_one_or_none()
    if existing:
        existing.qty = cur + qty
        existing.updatedAt = now_str()
    else:
        existing = models.CartItem(
            userId=user_id, assetId=data.assetId, qty=qty,
            createdAt=now_str(), updatedAt=now_str(),
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def add_to_cart_batch(db: Session, data: schemas.CartBatchInput, user_id: str = DEFAULT_USER) -> dict:
    """批量加购：逐条校验可售库存，超量的跳过并记录，其余正常加入"""
    skipped: list[dict] = []
    added = 0
    for it in data.items:
        a = get_asset(db, it.assetId)
        if not a:
            skipped.append({"assetId": it.assetId, "name": f"资产 #{it.assetId}", "available": 0, "reason": "资产不存在"})
            continue
        qty = max(1, int(it.qty or 1))
        cur = _cart_qty_of(db, user_id, it.assetId)
        if not a.repeatSale and cur + qty > _avail(a):
            skipped.append({
                "assetId": it.assetId, "name": a.name, "available": _avail(a),
                "reason": f"可售仅 {_avail(a)}{a.unit}（购物车已有 {cur}{a.unit}）",
            })
            continue
        cs = _cart_subject(db, user_id)
        if cs is not None and a.subject != cs:
            skipped.append({
                "assetId": it.assetId, "name": a.name, "available": _avail(a),
                "reason": f"主体不一致（购物车为「{cs}」，该项为「{a.subject}」）",
            })
            continue
        add_to_cart(db, schemas.CartItemInput(assetId=it.assetId, qty=qty), user_id)
        added += 1
    return {
        "addedCount": added,
        "skipped": skipped,
        "cart": [schemas.CartItemOut.model_validate(c).model_dump() for c in _cart_list(db, user_id)],
    }


def set_cart_qty(db: Session, cart_id: int, qty: int, user_id: str = DEFAULT_USER) -> None:
    c = db.get(models.CartItem, cart_id)
    if not c or c.userId != user_id:
        raise HTTPException(404, "购物车项不存在")
    if qty <= 0:
        db.delete(c)
    else:
        _check_stock(db, c.assetId, int(qty))
        c.qty = int(qty)
        c.updatedAt = now_str()
    db.commit()


def remove_cart_item(db: Session, cart_id: int, user_id: str = DEFAULT_USER) -> None:
    c = db.get(models.CartItem, cart_id)
    if not c or c.userId != user_id:
        raise HTTPException(404, "购物车项不存在")
    db.delete(c)
    db.commit()


def clear_cart(db: Session, user_id: str = DEFAULT_USER) -> None:
    _clear_cart(db, user_id)
    db.commit()


def _clear_cart(db: Session, user_id: str = DEFAULT_USER) -> None:
    """清空购物车（不提交），供 checkout 与其它流程在同一事务内复用（H8）。"""
    for c in _cart_list(db, user_id):
        db.delete(c)


def _order_core(
    db: Session, data, asset_qty: list[tuple[models.Asset, int]]
) -> models.Project:
    """通用下单：校验同一主体 + 可售库存，生成进行中销售项目并锁定库存
    （交付由人工置"已完成"触发）。主体（subject）由资产自动带出，无需前端传入。"""
    if not asset_qty:
        raise HTTPException(400, "没有可下单的资产")
    subjects = {a.subject for a, _ in asset_qty}
    if len(subjects) > 1:
        raise HTTPException(400, "下单资产必须属于同一主体，请清空购物车后重新选择")
    subject = next(iter(subjects))
    items: list[schemas.ProjectItemInput] = []
    total = 0.0
    for a, qty in asset_qty:
        if not a.repeatSale and qty > _avail(a):
            raise HTTPException(400, f"「{a.name}」可售库存仅 {_avail(a)}{a.unit}，无法下单 {qty}{a.unit}")
        price = a.salePrice or 0
        amount = round(price * qty, 4)  # 契约 5：与项目编辑路径完全一致，万元 4 位小数
        total += amount
        items.append(
            schemas.ProjectItemInput(assetId=a.id, qty=qty, price=price, amount=amount, deliveryReq=data.deliveryReq)
        )
    project_input = schemas.ProjectInput(
        name=data.projectName,
        customer=data.customer,
        industry="",
        rep=data.rep,
        subject=subject,
        expectedAmount=round(total, 4),
        quoteAmount=0,
        contractAmount=data.contractAmount,
        paidAmount=0,
        expectedSignDate=data.expectedSignDate or today(),
        lastFollowDate=today(),
        remark=data.remark,
        items=items,
    )
    # H8：建项目走 core（不提交），由调用方在一个事务内提交
    # WHY：销售与交付是两个独立动作——下单只锁定库存（active），交付（扣库存+出库）
    # 由人工把项目置为"已完成"触发；分离便于纠错编辑与审计留痕各自独立。
    project = _create_project_core(db, project_input)
    return project


def checkout(db: Session, data: schemas.CheckoutInput, user_id: str = DEFAULT_USER) -> models.Project:
    """购物车下单：用购物车资产生成进行中销售项目（锁定库存），随后清空购物车；
    交付由人工置"已完成"触发"""
    cart = _cart_list(db, user_id)
    if not cart:
        raise HTTPException(400, "购物车为空，请先添加资产")
    asset_qty: list[tuple[models.Asset, int]] = []
    for c in cart:
        a = get_asset(db, c.assetId)
        if not a:
            raise HTTPException(400, f"购物车中的资产（#{c.assetId}）已删除，请先移除后再下单")
        asset_qty.append((a, c.qty))
    # H8：建项目 → 交付出库 → 清空购物车 收敛为同一事务，任一步失败整体回滚
    project = _order_core(db, data, asset_qty)
    _clear_cart(db, user_id)
    db.commit()
    db.refresh(project)
    return project


def create_sale_order(db: Session, data: schemas.SaleOrderInput) -> models.Project:
    """资产直接下单：单/多资产生成进行中销售项目（锁定库存，与购物车下单同一流程）；
    交付由人工置"已完成"触发"""
    asset_qty: list[tuple[models.Asset, int]] = []
    for it in data.items:
        a = get_asset(db, it.assetId)
        if not a:
            raise HTTPException(404, f"资产 #{it.assetId} 不存在")
        asset_qty.append((a, max(1, int(it.qty or 1))))
    # H8：建项目 + 交付出库同一事务
    project = _order_core(db, data, asset_qty)
    db.commit()
    db.refresh(project)
    return project


def bootstrap(db: Session) -> dict:
    assets = db.execute(select(models.Asset).order_by(models.Asset.id.desc())).scalars().all()
    # 确保每个资产的交付物实例已初始化（惰性）
    for a in assets:
        _init_asset_deliverables(db, a)
    db.commit()

    projects = db.execute(select(models.Project).order_by(models.Project.id.desc())).scalars().all()
    outbounds = db.execute(select(models.Outbound).order_by(models.Outbound.id.desc())).scalars().all()
    flows = db.execute(select(models.AssetFlow).order_by(models.AssetFlow.id.asc())).scalars().all()
    logs = db.execute(select(models.OpLog).order_by(models.OpLog.id.asc())).scalars().all()

    def _bases(kind: str):
        return db.execute(select(models.BaseRecord).where(models.BaseRecord.kind == kind)
                          .order_by(models.BaseRecord.id.asc())).scalars().all()

    suppliers, customers, reps = _bases("suppliers"), _bases("customers"), _bases("reps")

    templates = db.execute(select(models.DeliverableTemplate)).scalars().all()
    tpl_map: dict[str, list] = {}
    for t in templates:
        tpl_map.setdefault(t.type, []).append(schemas.DeliverableTemplateOut.model_validate(t).model_dump())

    deliv_map: dict[int, list] = {}
    for a in assets:
        if a.deliverables:
            deliv_map[str(a.id)] = [schemas.AssetDeliverableOut.model_validate(d).model_dump() for d in a.deliverables]

    category_units = db.execute(select(models.CategoryUnit).order_by(models.CategoryUnit.id.asc())).scalars().all()
    cart = _cart_list(db, DEFAULT_USER)

    return {
        "assets": [schemas.AssetOut.model_validate(a).model_dump() for a in assets],
        "projects": [schemas.ProjectOut.model_validate(p).model_dump() for p in projects],
        "outbounds": [schemas.OutboundOut.model_validate(o).model_dump() for o in outbounds],
        "suppliers": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in suppliers],
        "customers": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in customers],
        "reps": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in reps],
        "flows": [schemas.FlowOut.model_validate(f).model_dump() for f in flows],
        "logs": [schemas.LogOut.model_validate(l).model_dump() for l in logs],
        "deliverableTemplates": tpl_map,
        "assetDeliverables": deliv_map,
        "categoryUnits": [schemas.CategoryUnitOut.model_validate(c).model_dump() for c in category_units],
        "cart": [schemas.CartItemOut.model_validate(c).model_dump() for c in cart],
    }
