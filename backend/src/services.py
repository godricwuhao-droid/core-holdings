"""业务服务层：复刻前端 mock/store.ts 的全部业务规则

- 可售数量 = 登记 - 锁定 - 已交付；可重复售卖产品不扣减
- 状态仅 2 种（可售 / 全部出售），由数量自动判定
- 项目关联产品→锁定；合同签订→确认销售；交付完成→交付+累计销售；终止→释放锁定
- 交付撤销→反向流水；历史补录不扣数量
"""
import re
import uuid
from datetime import date, datetime
from decimal import Decimal

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

# 金额精度（ADR-006）：单位=元，累加/重算/比较一律 decimal.Decimal，
# 落库前转 float（SQLite REAL）。禁止对金额使用 round(x, 4) 旧单位式写法。
CENT = Decimal("0.01")

# 编号格式（FIX-20261020-#6：bootstrap viewer 日志过滤按编号匹配可见范围）：
# 项目 SP-{14位时间戳+2位随机}（存量旧编号 SP-001 同为 SP- 前缀数字）、交付 CK-{4位}
_SP_CODE_RE = re.compile(r"SP-\d+")
_CK_CODE_RE = re.compile(r"CK-\d+")


def _dec(v) -> Decimal:
    """float/Decimal/str → Decimal（经 str 中转，避免 float 二进制误差进入十进制运算）"""
    return Decimal(str(v))


def today() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _ts_code(db: Session, prefix: str, model) -> str:
    """时间戳唯一编号（2026-10-19 起，替代旧「前缀+自增序号零填充」方案）。

    格式 = 前缀 + 14 位本地时间（yyyyMMddHHmmss）+ 2 位随机数，共 16 位，
    例如 SP-2026101915301207 / HT-2026101915301235。
    为什么是 16 位：
    - 14 位时间戳：编号可读且天然按创建时间排序（后建的编号大）；
    - 尾部 2 位随机数：防同秒碰撞——购物车结算一次请求会为多客户生成多份合同
      （必然同一秒），不同项目也可能同秒创建；
    - 随机数碰撞（概率 1/100）时最多换 10 次随机重试，仍碰撞则兜底 16 位 uuid 后缀
      （实际不可达），保证 code UNIQUE 约束不破坏。
    code 列为 VARCHAR(32) UNIQUE，前缀+16 位共 19 字符安全容纳；
    存量旧编号（SP-001 / HT-0001）保留不动。
    """
    import random as _random

    for _ in range(10):
        code = f"{prefix}-{datetime.now():%Y%m%d%H%M%S}{_random.randint(0, 99):02d}"
        if not db.execute(select(model).where(model.code == code).limit(1)).first():
            return code
    return f"{prefix}-{uuid.uuid4().hex}"


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


def get_contract(db: Session, contract_id: int | None) -> models.Contract | None:
    if not contract_id:
        return None
    return db.get(models.Contract, contract_id)


def user_sees_project(user: "models.User | None", p: models.Project) -> bool:
    """销售项目可见性口径（2026-10-16：销售项目对生态人员放开，仅可见自己下单的）：

    - admin / editor：全部可见；
    - viewer（生态人员）：仅「自己下单」的项目——实际下单账号（creator）是自己；
      存量项目 creator 为空时回退「生态人员（rep）是自己姓名」判定。
    """
    if user is None or user.role != "viewer":
        return True
    if p.creator:
        return p.creator == user.username
    return bool(p.rep) and p.rep in (user.name, user.username)


def _normalize_rep(db: Session, rep: str) -> str:
    """FIX-20261020-#10：rep（生态人员）口径归一为 username。

    历史入口混存账号与姓名（下单弹窗写姓名、建单页写账号），导致筛选重复、统计拆分。
    归一规则：值在用户表中匹配 name → 替换为对应用户 username；已是 username 或无匹配
    则原样保存（不 400——rep 允许填写非平台账号的生态人员姓名）。
    """
    name = (rep or "").strip()
    if not name:
        return rep or ""
    u = db.query(models.User).filter(models.User.name == name).first()
    if u is not None:
        return u.username
    return name


def add_flow(db: Session, asset_id: int, type: str, qty: int, unit: str,
             amount: float, date: str, ref: str, note: str, operator: str = "",
             contract_id: int | None = None) -> None:
    # operator：流水操作账号（登录 username；启动 seed 路径传 "system"）；存量流水保持空
    # contract_id（ADR-007）：合同级交付/终止产生的流水记录关联合同；非合同场景为 None
    db.add(models.AssetFlow(
        assetId=asset_id, type=type, qty=qty, unit=unit,
        amount=amount, date=date, ref=ref, note=note, operator=operator,
        contractId=contract_id,
    ))


def add_log(db: Session, target: str, target_name: str, action: str, detail: str,
            asset_id: int | None = None, changes: str = "",
            contract_id: int | None = None, operator: str = "admin") -> None:
    # FIX-5：operator 真实化——有当前用户上下文的路径由 router 透传登录用户名；
    # 无上下文的内部路径（seed/内部复用）保持默认 "admin"（兼容存量口径）。
    db.add(models.OpLog(
        target=target, targetName=target_name, action=action,
        detail=detail, operator=operator, time=now_str(),
        assetId=asset_id if target == "asset" else None,
        changes=changes,
        contractId=contract_id,
    ))


def auto_status(a: models.Asset) -> str:
    # 与前端 types.ts noSellableStock 完全一致：非可重复售卖且（数量-锁定-已交付）<=0 → 全部出售
    no_sellable = (not a.repeatSale) and (a.quantity - a.lockedQty - a.shippedQty) <= 0
    return "all_sold" if no_sellable else "in_stock"


def refresh_status(a: models.Asset) -> None:
    a.status = auto_status(a)
    a.updatedAt = today()


def item_status_of_input(it: schemas.ProjectItemInput) -> str:
    # H4：不再以金额是否为 0 判定。已关联产品即可锁定（含零价明细，交付时正常扣数量/交付）。
    # 注：pending_amount（待确认金额）自此不再产生，前端 ITEM_STATUS 中该项成为未使用枚举（预期）。
    if not it.assetId:
        return "pending_asset"
    return "locked"


def _is_amount_mode(a: models.Asset) -> bool:
    """ADR-008：是否包量计价（合同金额整数元权威，salePrice 仅参考值）"""
    return (a.pricingMode or "unit") == "amount"


def _validate_amount_yuan(amount) -> Decimal:
    """ADR-008：包量计价金额校验——整数元且 > 0，否则 400。返回 Decimal（元）。"""
    if amount is None:
        raise HTTPException(400, "包量计价产品的销售金额须为整数元")
    amt = _dec(amount)
    if amt <= 0 or amt != amt.to_integral_value():
        raise HTTPException(400, "包量计价产品的销售金额须为整数元")
    return amt


def _derived_price(amt: Decimal, qty: int) -> float:
    """ADR-008：amount 模式派生展示单价 price = round(amount / qty, 6)（不参与金额计算）"""
    return float((amt / qty).quantize(Decimal("0.000001")))


def _validate_price_range(price_min: float | None, price_max: float | None) -> None:
    """ADR-018 §1（PRICING-20261020）：产品参考区间校验——只填其一允许（单边边界）；
    两者都有时 min ≤ max，否则 400。"""
    if price_min is not None and price_max is not None and _dec(price_min) > _dec(price_max):
        raise HTTPException(400, "参考区间下限不能大于上限")


def _check_discount_range(asset: models.Asset | None, qty: int, amount,
                          unit: str = "",
                          rs: models.RsItem | None = None) -> Decimal | None:
    """ADR-018 §1/§3（PRICING-20261020）：折扣金额校验 + 参考区间校验。
    购物车行更新 / 加购 / checkout / 直接下单（sales/order）各入口共用，不信任前端。

    - amount 为 None → 原价成交，返回 None（unit 行 salePrice×qty / 遥感行明细 price）；
    - amount 须为非负整数元，否则 400；
    - 折扣单价 = amount ÷ qty（Decimal 保留 6 位）须落在参考区间 [priceMin, priceMax] 内：
      未设置区间 = 不限制；单边区间按单边校验；超限 400
      「折扣单价超出该产品参考区间（{min}~{max} 元/{unit}）」（契约 §3 文案）。
    - ADR-021（RSITEM-RANGE-20261020）：遥感明细行（rs 非空）区间取该 rs_item 自身的
      priceMin/priceMax（不再取父产品容器 assets 的区间）；普通产品行行为不变。
    返回 Decimal 金额（元）。"""
    if amount is None:
        return None
    amt = _dec(amount)
    if amt < 0 or amt != amt.to_integral_value():
        raise HTTPException(400, "销售金额须为非负整数元")
    if qty <= 0:
        return amt
    # ADR-021（RSITEM-RANGE-20261020）：区间来源按行类型区分——
    # 遥感明细行用明细自身区间；普通产品行用产品（assets）区间
    if rs is not None:
        lo, hi = rs.priceMin, rs.priceMax
    elif asset is not None:
        lo, hi = asset.priceMin, asset.priceMax
    else:
        return amt
    if lo is None and hi is None:
        return amt  # 未设置区间 = 不限制（ADR-018 §1 / ADR-021）
    unit_price = (amt / qty).quantize(Decimal("0.000001"))
    u = unit or (asset.unit if asset else "")
    if lo is not None and hi is not None:
        rng = f"{lo:g}~{hi:g} 元/{u}"
    elif lo is not None:
        rng = f"≥{lo:g} 元/{u}"
    else:
        rng = f"≤{hi:g} 元/{u}"
    if (lo is not None and unit_price < _dec(lo)) or (hi is not None and unit_price > _dec(hi)):
        raise HTTPException(400, f"折扣单价超出该产品参考区间（{rng}）")
    return amt


def _validate_date_str(v: str, label: str) -> str:
    """YYYY-MM-DD 格式校验（ADR-019/020，PRICING-20261020）：非法 400。"""
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise HTTPException(400, f"{label}格式须为 YYYY-MM-DD")
    return v


def _validate_service_period(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """ADR-020（PRICING-20261020）：服务期限校验——YYYY-MM-DD 格式 + start ≤ end，
    否则 400「服务开始日期不能晚于结束日期」。空串视为未填（None）。"""
    def _norm(v: str | None, label: str) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        return _validate_date_str(s, label)
    s = _norm(start, "服务开始日期")
    e = _norm(end, "服务结束日期")
    if s and e and s > e:
        raise HTTPException(400, "服务开始日期不能晚于结束日期")
    return s, e


def _validate_discount_rate(rate: float | None) -> float | None:
    """折扣率校验（DISCOUNT-20261021/ADR-023）：0 < rate ≤ 1（0.9=九折），
    违反 400「折扣率须为 0 到 1 之间的正数」；None 允许（=清空/无折扣）。
    后端只存不算——不做金额回填计算（金额权威原则，区间校验仍对 amount 生效）。"""
    if rate is None:
        return None
    if not (0 < rate <= 1):
        raise HTTPException(400, "折扣率须为 0 到 1 之间的正数")
    return float(rate)


def _item_pricing(a: models.Asset | None, it: schemas.ProjectItemInput) -> tuple[float, float]:
    """销售明细计价分支（ADR-008），返回 (price, amount)：
    - amount 模式：amount 为权威输入（整数元校验），跳过 price×qty 重算，price 为派生值；
    - unit 模式：price×qty Decimal 权威重算（行为完全不变）。"""
    if a is not None and _is_amount_mode(a):
        amt = _validate_amount_yuan(it.amount)
        return _derived_price(amt, it.qty), float(amt)
    return float(it.price), float((_dec(it.price) * it.qty).quantize(CENT))


def _validate_item_stock(a: models.Asset, qty: int) -> None:
    """H1：加锁前校验可用数量，避免超卖；负数量/零数量直接拒绝。

    可重复售卖产品不占用数量，跳过上限校验。
    """
    if qty <= 0:
        raise HTTPException(400, f"数量必须大于 0（{a.name}）")
    if a.repeatSale:
        return
    available = a.quantity - a.lockedQty - a.shippedQty
    if qty > available:
        raise HTTPException(400, f"可用数量不足：{a.name} 可售 {available}{a.unit}，本单需 {qty}")


def apply_item_lock(db: Session, asset_id: int | None, qty: int, add: bool, ref: str,
                    operator: str = "", contract_id: int | None = None,
                    repeat_override: bool | None = None) -> None:
    a = get_asset(db, asset_id)
    # repeat_override（ADR-011）：遥感明细行以 rs_items.repeatSale 为权威（父产品 repeatSale 无意义），
    # 非明细行保持产品口径（None → a.repeatSale）
    if not a or qty <= 0:
        return
    if a.repeatSale if repeat_override is None else repeat_override:
        return
    a.lockedQty = max(0, a.lockedQty + (qty if add else -qty))
    add_flow(
        db, a.id,
        "project_lock" if add else "cancel_release",
        qty, a.unit, 0, today(), ref,
        "销售项目锁定" if add else "项目释放锁定",
        operator=operator, contract_id=contract_id,
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
# 产品
# ============================================================
def create_asset(db: Session, data: schemas.AssetInput, operator: str = "") -> models.Asset:
    # ADR-011：遥感数据按普通父产品登记（容器，本身不可直接加购/下单），
    # 售卖粒度走 rs_items 明细表（POST /assets/{id}/rs-items）；
    # ADR-010 的三维必填/判重逻辑已移除，服务层不再读写 assets 的 4 个废弃列。
    # ADR-018 §1（PRICING-20261020）：参考区间校验（两者都有时 min ≤ max，否则 400）
    _validate_price_range(data.priceMin, data.priceMax)
    asset = models.Asset(
        lockedQty=0, shippedQty=0, soldAmount=0, soldCount=0,
        name=data.name, board=data.board, type=data.type, subject=data.subject,
        unit=data.unit, quantity=data.quantity, repeatSale=data.repeatSale,
        salePrice=data.salePrice,
        priceMin=data.priceMin, priceMax=data.priceMax,  # ADR-018 §1：参考区间（可空=不限制）
        status=data.status,  # 占位，下方按数量自动判定覆盖
        inboundDate=data.inboundDate, expiryDate=data.expiryDate,
        perpetual=data.perpetual, spec=data.spec, saleDetail=data.saleDetail,
        featureDoc=data.featureDoc,
        contractFile=data.contractFile,
        remark=data.remark, updatedAt=today(),
        # ADR-008：计价模式由后端按类型权威决定（卫星Token → 'amount'，其余恒 'unit'），
        # 不接受前端传 pricingMode 篡改类型映射
        pricingMode="amount" if data.type == "卫星Token" else "unit",
    )
    # 状态两态规则：由数量自动判定，不采信前端 status（与 update_asset/refresh_status 口径一致）
    # ——修复：此前直接信任 data.status（前端恒传 in_stock），quantity=0 的非重复售卖产品会被误存为「可售」
    asset.status = auto_status(asset)
    # 不手写主键：flush 由 DB 生成 id，再据此拼写编号，编号格式保持 CH-{板块}-{3位序号}
    _flush_with_code(db, asset, lambda aid: f"CH-{BOARD_CODE.get(data.board, 'GEN')}-{str(aid).zfill(3)}")
    # 新登记产品即已登记（可售口径）
    add_flow(db, asset.id, "purchase_in", asset.quantity, asset.unit, 0,
             data.inboundDate or today(), asset.code, "登记", operator=operator)
    add_log(db, "asset", asset.name, "新增产品",
            f"新建产品 {asset.code}，状态：{'可售' if asset.status == 'in_stock' else '全部出售'}",
            asset_id=asset.id, operator=operator)
    db.commit()
    db.refresh(asset)
    return asset


# update_asset 字段级 diff 的中文映射（未映射字段用原名）
ASSET_FIELD_LABELS = {
    "name": "产品名称", "board": "所属板块", "type": "产品类型", "subject": "所属主体",
    "unit": "单位", "quantity": "产品总数", "repeatSale": "可重复售卖",
    "salePrice": "销售单价", "priceMin": "参考区间下限", "priceMax": "参考区间上限",
    "status": "产品状态", "inboundDate": "登记日期",
    "expiryDate": "到期日期", "perpetual": "永久授权", "spec": "规格描述",
    "saleDetail": "销售明细", "featureDoc": "功能清单", "contractFile": "产品清单",
    "remark": "备注",
}
# 长文本字段变化时只记「已变更」，不贴全文
ASSET_LONG_TEXT_FIELDS = {"spec", "saleDetail", "remark"}
# 文件类字段（存散列落盘名）：diff 展示时还原为原始文件名（查 file_meta，无记录用散列名兜底）
ASSET_FILE_FIELDS = {"featureDoc", "contractFile"}
# 金额类字段（存「元」口径，ADR-006）：diff 展示直接按元值千分位（平台口径禁止「万」字）
# ADR-018 §1（PRICING-20261020）：参考区间 priceMin/priceMax 同为元口径
ASSET_AMOUNT_FIELDS = {"salePrice", "priceMin", "priceMax"}


def _fmt_amount_yuan(v) -> str:
    """元值千分位展示（ADR-006 后库内即元值，直接格式化，不再 ×10000）。
    空值/0 显示「0 元」，平台口径禁止「万」字。"""
    try:
        yuan = float(v)
    except (TypeError, ValueError):
        yuan = 0.0
    if yuan == 0:
        return "0 元"
    if abs(yuan - round(yuan)) < 1e-6:
        return f"{int(round(yuan)):,} 元"
    return f"{yuan:,.2f} 元"


def _file_display_name(db: Session, stored: str) -> str:
    """散列落盘名 → 原始文件名（查 file_meta，无记录用散列名兜底；空值返回空串）。"""
    if not stored:
        return ""
    m = db.get(models.FileMeta, stored)
    return m.name if (m and m.name) else stored


def _arrow(old: str, new: str) -> str:
    """diff 值连接（空值不留多余空格）：如「→ 产品说明书.pdf」/「A → B」。"""
    if old == "" and new == "":
        return "→"
    if old == "":
        return f"→ {new}"
    if new == "":
        return f"{old} →"
    return f"{old} → {new}"


def update_asset(db: Session, asset_id: int, patch: dict, operator: str = "admin") -> None:
    a = get_asset(db, asset_id)
    if not a:
        raise HTTPException(404, "产品不存在")
    allowed = {"name", "board", "type", "subject", "unit", "quantity", "repeatSale",
               "salePrice", "priceMin", "priceMax",  # ADR-018 §1（PRICING-20261020）：参考区间
               "status", "inboundDate", "expiryDate", "perpetual",
               "spec", "saleDetail", "featureDoc", "contractFile", "remark"}
    # ADR-011：ADR-010 的 4 个废弃列（province/city/resolution/imageDate）不再接受修改
    old_repeat = a.repeatSale
    old_type = a.type
    # 字段级 diff：仅对本次实际变更的字段生成中文描述（金额类展示原值不换算）
    changes: list[str] = []
    for k, v in patch.items():
        if k not in allowed:
            continue
        old = getattr(a, k)
        if old == v:
            continue
        setattr(a, k, v)
        label = ASSET_FIELD_LABELS.get(k, k)
        if k in ASSET_LONG_TEXT_FIELDS:
            changes.append(f"{label}: 已变更")
        elif k in ASSET_FILE_FIELDS:
            # 文件字段：散列名 → 原始名（如「功能清单: → 产品说明书.pdf」）
            changes.append(f"{label}: {_arrow(_file_display_name(db, old), _file_display_name(db, v))}")
        elif k in ASSET_AMOUNT_FIELDS:
            # 金额字段：元值直显千分位（如「销售单价: 330,000 元 → 3,200,000 元」）
            changes.append(f"{label}: {_fmt_amount_yuan(old)} → {_fmt_amount_yuan(v)}")
        else:
            unit = {"quantity": a.unit}.get(k, "")
            changes.append(f"{label}: {old} → {v}" + (f" {unit}" if unit else ""))
    # FIX-20261020-#8：type 变更时重算 pricingMode（卫星Token → amount，其余 → unit），
    # 与新建逻辑（create_asset）一致——pricingMode 不在可更新白名单内，只能由类型权威推导
    if "type" in patch and patch["type"] != old_type:
        new_mode = "amount" if patch["type"] == "卫星Token" else "unit"
        if a.pricingMode != new_mode:
            changes.append(f"计价模式: {a.pricingMode} → {new_mode}")
            a.pricingMode = new_mode
    # ADR-018 §1（PRICING-20261020）：参考区间组合校验——按「存量值 + 本次 patch」的
    # 最终落库值校验（防分两次编辑分别改 min/max 造成 min > max）
    _validate_price_range(a.priceMin, a.priceMax)
    # BUG1 修复：repeatSale false→true 时，存量 lockedQty 残留会成为"幽灵锁定"
    # （apply_item_lock 对 repeatSale 产品直接 return，交付/终止都无法释放）。
    # 故切换瞬间清零 lockedQty 并留痕；lockedQty=0 时无事发生不打日志。
    # true→false 不做任何数量动作（历史未锁明细由 item.locked 标记区分）。
    if (not old_repeat) and a.repeatSale and a.lockedQty > 0:
        old_locked = a.lockedQty
        a.lockedQty = 0
        add_log(db, "asset", a.name, "清零锁定",
                f"repeatSale 切换为 true，清零存量锁定 {old_locked}{a.unit}（可重复售卖不再占用数量）",
                asset_id=a.id, operator=operator)
    # 数量不变量守卫：产品总数不得低于「锁定 + 已交付」（否则可售变负，破坏可售=总数−锁定−交付口径）。
    # 校验放在锁定清零之后——repeatSale 切换释放的锁定不应阻塞数量下调。
    # 入参类型/范围（quantity≥0 整数、salePrice≥0）由路由层 Pydantic（schemas.AssetUpdate）拦截。
    if a.quantity < a.lockedQty + a.shippedQty:
        raise HTTPException(
            400,
            f"产品总数不能低于已锁定 {a.lockedQty}{a.unit} + 已交付 {a.shippedQty}{a.unit}"
            f"（合计 {a.lockedQty + a.shippedQty}{a.unit}），请先处理相关销售项目/交付记录",
        )
    refresh_status(a)
    # 仅当有实际变更时打编辑日志（无变更不打日志）
    if changes:
        add_log(db, "asset", a.name, "编辑", "更新产品信息", asset_id=a.id,
                changes="；".join(changes), operator=operator)
    db.commit()


def delete_asset(db: Session, asset_id: int, operator: str = "admin") -> None:
    a = get_asset(db, asset_id)
    if not a:
        return
    # H7：引用完整性校验（SQLite 不加外键——迁移风险高；改用服务层校验实现同等约束）
    # 1a) FIX-4（合同感知）：合同明细（contractId 非空）——仅当存在 active/pending 合同引用时拒绝；
    #     delivered/terminated 合同的引用放行（前端已有「未关联产品」兜底，交付分支已有 if a: 防御）。
    #     ADR-012：pending（待审核）合同与 active 同语义——锁定未释放，产品不可删除。
    # ADR-019（PRICING-20261020）：delivering（交付中）合同与 active 同语义——锁定未释放，不可删
    ref_contract = db.execute(
        select(models.Contract)
        .join(models.ProjectItem, models.ProjectItem.contractId == models.Contract.id)
        .where(models.ProjectItem.assetId == asset_id,
               models.Contract.status.in_(("active", "pending", "delivering")))
        .limit(1)
    ).scalars().first()
    if ref_contract:
        raise HTTPException(400,
            f"该产品仍被进行中/待审核的销售记录 {ref_contract.code}（客户 {ref_contract.customer}）引用，请先终止该销售记录后再删除")
    # 1b) 无合同 legacy 项目明细引用：保持原规则（项目 status != terminated → 拒绝）
    ref_item = db.execute(
        select(models.ProjectItem)
        .join(models.Project, models.Project.id == models.ProjectItem.project_id)
        .where(models.ProjectItem.assetId == asset_id,
               models.ProjectItem.contractId.is_(None),
               models.Project.status != "terminated")
        .limit(1)
    ).scalars().first()
    # 2) 存在 status='done' 的交付记录引用 → 拒绝
    ref_ob = db.execute(
        select(models.Outbound)
        .where(models.Outbound.assetId == asset_id, models.Outbound.status == "done")
        .limit(1)
    ).scalars().first()
    if ref_item or ref_ob:
        raise HTTPException(400, "该产品仍被销售项目或交付记录引用，请先终止相关项目/撤销交付后再删除")
    # 3) 清理引用了该产品的购物车项（含 ADR-011 遥感明细行）
    for c in db.execute(select(models.CartItem).where(models.CartItem.assetId == asset_id)).scalars():
        db.delete(c)
    # 4) 级联删除该产品的交付物 + 流水 + 遥感数据明细（ADR-011：父产品删除，明细随之删除；
    #    走到这里说明无 active 合同/非 terminated 项目引用，其明细行也不可能有销售关联）
    for d in list(a.deliverables):
        db.delete(d)
    for f in db.execute(select(models.AssetFlow).where(models.AssetFlow.assetId == asset_id)).scalars():
        db.delete(f)
    for r in db.execute(select(models.RsItem).where(models.RsItem.assetId == asset_id)).scalars():
        db.delete(r)
    name, code = a.name, a.code
    db.delete(a)
    add_log(db, "asset", name, "删除", f"删除产品 {code}", asset_id=asset_id, operator=operator)
    db.commit()


# ============================================================
# 遥感数据可售明细（ADR-011：父产品 + 明细两层模型）
# ============================================================
def _rs_item_desc(it: models.RsItem) -> str:
    """明细可读描述：省/市 · 精度 · 月份（市为空时省略）"""
    loc = f"{it.province}/{it.city}" if it.city else it.province
    return f"{loc} {it.resolution:g}m {it.saleMonth}"


def _rs_item_dup(db: Session, asset_id: int, province: str, city: str,
                 resolution: float, sale_month: str,
                 exclude_id: int | None = None) -> models.RsItem | None:
    """(assetId, province, city, resolution, saleMonth) 组合判重（Python 层，与全库风格一致）。

    resolution 为 FLOAT 列，比较用容差（1e-9）避免二进制浮点误差误判。
    """
    q = select(models.RsItem).where(
        models.RsItem.assetId == asset_id,
        models.RsItem.province == province,
        models.RsItem.city == city,
        models.RsItem.saleMonth == sale_month,
    )
    if exclude_id is not None:
        q = q.where(models.RsItem.id != exclude_id)
    for r in db.execute(q).scalars().all():
        if abs(float(r.resolution) - float(resolution)) < 1e-9:
            return r
    return None


def _rs_item_fields(data: schemas.RsItemInput) -> tuple[str, str, float, str, float]:
    """明细字段归一化 + 校验：省必填、price 整数元 > 0（saleMonth 格式/resolution>0 由 Pydantic 422）。"""
    province = (data.province or "").strip()
    if not province:
        raise HTTPException(400, "遥感数据明细必须填写省份")
    price = _dec(data.price)
    if price <= 0 or price != price.to_integral_value():
        raise HTTPException(400, "遥感数据明细单价须为整数元且大于 0")
    return province, (data.city or "").strip(), float(data.resolution), data.saleMonth, float(price)


def _get_rs_item_or_404(db: Session, item_id: int) -> models.RsItem:
    it = db.get(models.RsItem, item_id)
    if not it:
        raise HTTPException(404, "遥感数据明细不存在")
    return it


def create_rs_item(db: Session, asset_id: int, data: schemas.RsItemInput,
                   operator: str = "") -> models.RsItem:
    a = get_asset(db, asset_id)
    if not a:
        raise HTTPException(404, "产品不存在")
    if a.type != "遥感数据":
        raise HTTPException(400, "仅遥感数据产品可维护可售明细")
    province, city, resolution, sale_month, price = _rs_item_fields(data)
    # ADR-021（RSITEM-RANGE-20261020）：参考区间校验（与产品区间同口径，两者都有时 min ≤ max）
    _validate_price_range(data.priceMin, data.priceMax)
    if _rs_item_dup(db, asset_id, province, city, resolution, sale_month):
        raise HTTPException(400, "该父产品下已存在相同 省/市 + 精度 + 月份 的明细")
    it = models.RsItem(
        assetId=asset_id, province=province, city=city, resolution=resolution,
        saleMonth=sale_month, price=price, repeatSale=data.repeatSale,
        priceMin=data.priceMin, priceMax=data.priceMax,  # ADR-021：参考区间（可空=不限制）
        createdAt=now_str(), updatedAt=now_str(),
    )
    db.add(it)
    db.flush()
    add_log(db, "asset", a.name, "新增可售明细",
            f"新增明细 #{it.id}：{_rs_item_desc(it)}，单价 {_fmt_amount_yuan(price)}",
            asset_id=a.id, operator=operator)
    db.commit()
    db.refresh(it)
    return it


def update_rs_item(db: Session, item_id: int, data: schemas.RsItemInput,
                   operator: str = "") -> models.RsItem:
    it = _get_rs_item_or_404(db, item_id)
    a = get_asset(db, it.assetId)
    if not a:
        raise HTTPException(404, "明细所属父产品不存在")
    province, city, resolution, sale_month, price = _rs_item_fields(data)
    if _rs_item_dup(db, it.assetId, province, city, resolution, sale_month, exclude_id=it.id):
        raise HTTPException(400, "该父产品下已存在相同 省/市 + 精度 + 月份 的明细")
    it.province, it.city, it.resolution = province, city, resolution
    it.saleMonth, it.price, it.repeatSale = sale_month, price, data.repeatSale
    # ADR-021（RSITEM-RANGE-20261020）：参考区间（与产品区间同口径；传 null 清空=不限制）
    _validate_price_range(data.priceMin, data.priceMax)
    it.priceMin, it.priceMax = data.priceMin, data.priceMax
    it.updatedAt = now_str()
    add_log(db, "asset", a.name, "编辑可售明细",
            f"明细 #{it.id} 更新为：{_rs_item_desc(it)}，单价 {_fmt_amount_yuan(price)}",
            asset_id=a.id, operator=operator)
    db.commit()
    db.refresh(it)
    return it


def delete_rs_item(db: Session, item_id: int, operator: str = "") -> None:
    it = _get_rs_item_or_404(db, item_id)
    a = get_asset(db, it.assetId)
    # 引用完整性（服务层校验，同 delete_asset 风格）：任一销售关联（项目明细/购物车行）→ 400
    ref_cnt = db.execute(
        select(models.ProjectItem).where(models.ProjectItem.itemId == item_id).limit(1)
    ).scalars().first()
    if ref_cnt is None:
        ref_cnt = db.execute(
            select(models.CartItem).where(models.CartItem.itemId == item_id).limit(1)
        ).scalars().first()
    if ref_cnt is not None:
        raise HTTPException(400, "该明细存在销售关联，无法删除")
    desc = _rs_item_desc(it)
    db.delete(it)
    add_log(db, "asset", a.name if a else f"产品 #{it.assetId}", "删除可售明细",
            f"删除明细 #{item_id}：{desc}",
            asset_id=it.assetId if a else None, operator=operator)
    db.commit()


# ============================================================
# 销售项目
# ============================================================
def create_project(db: Session, data: schemas.ProjectInput, operator: str = "") -> models.Project:
    """手动建单/保存草稿（任意商务/管理员角色）。
    【核心业务规则 ADR-012 修订 2026-10-19】统一建 **pending（待审核）**（core 默认值）：
    商务接手 → 审核（改价确认/驳回）→ active。pending 期间仅负责人（或 admin）可编辑/审核。"""
    project = _create_project_core(db, data, operator=operator)
    db.commit()
    db.refresh(project)
    return project


def resubmit_project(db: Session, project_id: int, data: schemas.ProjectInput,
                     operator: str = "", user: models.User | None = None) -> models.Project:
    """重新提交（2026-10-20）：已终止项目（被驳回/取消/终止）的**下单账号**（或商务/管理员）
    把原单明细（可修改产品/数量/客户）重新下单——**新建 pending 项目（新编号）**走完整
    待审核流程（重新锁量、商务接手审核）；旧项目保留 terminated 历史（驳回原因可查）。
    守卫：源项目必须 terminated；viewer 仅自己下单的项目（creator 口径）。"""
    old = get_project(db, project_id)
    if not old:
        raise HTTPException(404, "原项目不存在")
    if old.status != "terminated":
        raise HTTPException(400, "仅已终止的项目可重新提交（进行中/待审核请走取消或终止）")
    if user is not None and user.role == "viewer" and not user_sees_project(user, old):
        raise HTTPException(403, "生态人员仅可重新提交自己下单的项目")
    project = _create_project_core(db, data, operator=operator)
    # 双向留痕：新项目备注标注来源；旧项目备注标注续单去向（不覆盖合同级驳回原因）
    if project.remark:
        project.remark = f"重新提交自 {old.code}（{old.name}）；{project.remark}"
    else:
        project.remark = f"重新提交自 {old.code}（{old.name}）"
    old.remark = (old.remark + " " if old.remark else "") + f"已重新提交为 {project.code}（{project.name}）"
    old.updatedAt = today()
    add_log(db, "project", project.name, "重新提交",
            f"由 {old.code}（{old.name}）重新提交为新订单，进入待审核", operator=operator,
            contract_id=None)
    db.commit()
    db.refresh(project)
    return project


def _normalize_contracts(db: Session, data: schemas.ProjectInput) -> list[tuple[str, list[schemas.ProjectItemInput], Decimal, str]]:
    """归一化合同结构（ADR-007）→ [(customer, items, contractAmount, remark), ...]。

    两种入参都支持（向后兼容）：
    - 传 contracts：按合同建项目（每客户一个合同）；
    - 不传（仅 items）：按**单合同**自动包装，customer 取项目 customer 字段，
      contractAmount 缺省=该组明细 amount 合计。
    返回的 contractAmount 为 Decimal（元口径，ADR-006），缺省时按明细计价合计：
    amount 模式=Σ 权威 amount（整数元，ADR-008），unit 模式=Σ price×qty。
    """
    def _item_total(it: schemas.ProjectItemInput) -> Decimal:
        a = get_asset(db, it.assetId)
        if a is not None and _is_amount_mode(a):
            return _validate_amount_yuan(it.amount)
        return (_dec(it.price) * it.qty).quantize(CENT)

    if data.contracts:
        out = []
        for c in data.contracts:
            total = sum((_item_total(it) for it in c.items), Decimal("0"))
            amt = _dec(c.contractAmount).quantize(CENT) if c.contractAmount is not None else total.quantize(CENT)
            out.append((c.customer, c.items, amt, c.remark))
        return out
    # 兼容路径：items 自动包装为单合同
    total = sum((_item_total(it) for it in data.items), Decimal("0"))
    return [(data.customer, data.items, total.quantize(CENT), "")]


def _item_repeat(db: Session, asset: models.Asset | None,
                 item_id: int | None) -> bool:
    """ADR-011：明细行（itemId 非空）以 rs_items.repeatSale 为权威（父产品 repeatSale 无意义）；
    非明细行用产品 repeatSale。"""
    if item_id:
        rs = db.get(models.RsItem, item_id)
        if rs is not None:
            return rs.repeatSale
    return asset.repeatSale if asset else True


def _validate_rs_item_ref(db: Session, it: schemas.ProjectItemInput) -> models.RsItem | None:
    """ADR-011：含 itemId 的明细行统一校验（三个下单入口共用）：
    明细存在且归属 assetId；qty 强制 1。返回 RsItem（无 itemId 返回 None）。"""
    if not it.itemId:
        return None
    rs = db.get(models.RsItem, it.itemId)
    if rs is None or rs.assetId != it.assetId:
        raise HTTPException(400, "遥感数据明细不存在或不属于该产品")
    if it.qty != 1:
        raise HTTPException(400, "遥感数据明细行数量固定为 1")
    return rs


def _create_project_core(db: Session, data: schemas.ProjectInput,
                         operator: str = "", initial_status: str = "pending") -> models.Project:
    """建项目核心（不提交）：归一化合同 → 逐合同校验同主体 → 按 assetId 聚合校验数量
    → 生成项目（状态 = initial_status）+ 合同（HT-xxxx）+ 明细（挂 contractId）→ 锁定。

    initial_status（ADR-012 修订 2026-10-19）：**所有角色/入口统一 "pending"（待审核）**——
    生态/商务/管理员 的购物车结算、直接下单、手动建单均进「待审核」流程：
    商务接手 → 审核（改价确认/驳回）→ active（确认时实际价写回挂牌价）。锁定照常。

    抽成 core 供 create_project / checkout / sales order 复用，以收敛为单一事务（H8）。
    项目 subject/customer/expectedAmount 均由合同派生（_recompute_project），
    请求体中的 subject/expectedAmount/contractAmount 不再采信（派生口径，ADR-007）。
    ADR-011：含 itemId 的明细行——明细存在/归属/qty=1 校验、金额=明细 price 权威、
    锁定按明细 repeatSale（true 不锁，false 锁父产品 qty=1）。
    """
    # 项目名非空（后端权威校验；Pydantic 无 min_length，前端直调 API 可传空串）
    if not (data.name or "").strip():
        raise HTTPException(400, "项目名称不能为空")
    data.name = data.name.strip()
    # FIX-20261020-#10：rep 归一为 username（前端已统一传 username，此处为后端兜底）
    data.rep = _normalize_rep(db, data.rep)
    # ADR-012 §5.1：建单入口指定的商务负责人必须通过账号校验（存在/启用/editor+admin），
    # 与 claim 转交同口径——防止脏负责人导致单据永久卡在 pending
    _validate_business_owner(db, data.businessOwner)
    contracts_in = _normalize_contracts(db, data)
    # FIX-20261020-#13b：任一合同 customer 为空 → 400（前端有校验，API 直调兜底）
    for customer, _items, _amt, _remark in contracts_in:
        if not (customer or "").strip():
            raise HTTPException(400, "请为每份销售记录填写客户")
    # ADR-011：明细行前置校验（存在/归属/qty=1），并缓存 RsItem 供计价/锁定复用
    rs_map: dict[int, models.RsItem] = {}
    for _customer, items, _amt, _remark in contracts_in:
        for it in items:
            # FIX-20261020-#13c：遥感父产品（容器）不可直接购买——
            # 容器明细行（itemId 非空，指向 rs_items）放行，只拦父产品本身
            if not it.itemId and it.assetId:
                a = get_asset(db, it.assetId)
                if a is not None and a.type == "遥感数据":
                    raise HTTPException(400, "遥感数据容器不可直接购买，请购买其数据明细")
            rs = _validate_rs_item_ref(db, it)
            if rs is not None:
                rs_map[it.itemId] = rs
            # DISCOUNT-20261021/ADR-023：折扣率统一校验（0 < rate ≤ 1 否则 400；null=无折扣）——
            # 覆盖购物车结算 / 手动建单 / 直接下单 / 重新提交全部入口（快照只写不改，
            # 后端只存不算，amount 校验完全不变）
            _validate_discount_rate(it.discountRate)
    # ADR-013：移除「记录内同主体」校验（一资产一记录天然单主体；手动建单可混合主体成一条记录）
    # H1：先整体校验数量，再统一加锁，避免部分加锁后中途失败
    # 超卖修复（H10）：校验必须**按 assetId 聚合**全项目（跨合同）需求量后再比较可售。
    # WHY：同一项目可能含多条引用同一 assetId 的明细（如 qty 各 1、可售仅 1），
    # 逐条按"全量可售"校验会全部通过，合计却超卖/超锁；故先汇总该产品在本单的 qty 合计。
    demand: dict[int, int] = {}
    for _customer, items, _amt, _remark in contracts_in:
        for it in items:
            if not it.assetId:
                continue
            # ADR-011：明细行仅当明细 repeatSale=false 才计入父产品锁定需求（true 只计次不占数量）
            if it.itemId and rs_map.get(it.itemId) is not None and rs_map[it.itemId].repeatSale:
                continue
            demand[it.assetId] = demand.get(it.assetId, 0) + it.qty
    for aid, total_qty in demand.items():
        asset = get_asset(db, aid)
        if asset is not None:
            _validate_item_stock(asset, total_qty)
    # 建项目（customer/subject/expectedAmount 建完合同后由 _recompute_project 派生落库）
    project = models.Project(
        name=data.name, customer=data.customer, industry=data.industry, rep=data.rep,
        # 下单账号（登录 username）：生态人员「仅可见自己下单的项目」的可见性判定依据
        creator=operator,
        businessOwner=data.businessOwner,  # 商务负责人（可选，默认 ""）
        subject="", status=initial_status,  # 契约 3：不采信请求体 status；ADR-012 修订：所有入口默认 pending（待审核）
        expectedAmount=0, quoteAmount=data.quoteAmount,
        contractAmount=0, paidAmount=data.paidAmount,
        expectedSignDate=data.expectedSignDate, lastFollowDate=data.lastFollowDate,
        remark=data.remark, createdAt=today(), updatedAt=today(),
    )
    # D1：不手写主键，flush 后拼编号；编号为时间戳 16 位方案（见 _ts_code 注释）
    _flush_with_code(db, project, lambda pid: _ts_code(db, "SP", models.Project))
    # 建合同 + 明细（合同 code 同为时间戳 16 位，HT- 前缀）
    total_item_count = 0
    for customer, items, amt, remark in contracts_in:
        # ADR-013：签约主体派生 = 各行主体全一致 → 该值；混合 → 空串（语义=多主体记录，前端显示「多主体」）
        subjects = {a.subject for a in (get_asset(db, it.assetId) for it in items) if a is not None and a.subject}
        subject = subjects.pop() if len(subjects) == 1 else ""
        contract = models.Contract(
            projectId=project.id, customer=customer, subject=subject,
            contractAmount=float(amt), status=initial_status, remark=remark,
            createdAt=today(), updatedAt=today(),
        )
        _flush_with_code(db, contract, lambda cid: _ts_code(db, "HT", models.Contract))
        for it in items:
            asset = get_asset(db, it.assetId)
            rs = rs_map.get(it.itemId) if it.itemId else None
            eff_repeat = rs.repeatSale if rs is not None else (asset.repeatSale if asset else True)
            status = item_status_of_input(it)
            if status == "locked" and not eff_repeat:
                apply_item_lock(db, it.assetId, it.qty, True, project.code, operator=operator,
                                repeat_override=eff_repeat)
            # 计价分支：
            # - ADR-011 明细行：amount 权威 = 明细 price × 1（Decimal 重算，忽略前端传值）
            # - ADR-008 amount 模式：amount 权威（整数元）+ price 派生
            # - unit 模式：price×qty 后端权威重算（契约 5，Decimal 精确到分，元口径 ADR-006）
            if rs is not None:
                price = float(_dec(rs.price))
                amount = float((_dec(rs.price) * 1).quantize(CENT))
            else:
                price, amount = _item_pricing(asset, it)
            # ADR-018 §2（PRICING-20261020）：原价快照——下单时刻的**原始挂牌价**
            # （在改价/折扣之前取，永不覆盖）：遥感行 = rs_items.price / 同值；
            # 普通行（unit/amount 模式）= asset.salePrice / salePrice×qty
            if rs is not None:
                orig_price = float(_dec(rs.price))
                orig_amount = float(_dec(rs.price).quantize(CENT))
            elif asset is not None:
                orig_price = float(asset.salePrice)
                orig_amount = float((_dec(asset.salePrice) * it.qty).quantize(CENT))
            else:
                orig_price, orig_amount = None, None  # 未关联产品行（pending_asset）无原价
            # ADR-020（PRICING-20261020）：服务期限校验（YYYY-MM-DD + start ≤ end，否则 400）
            service_start, service_end = _validate_service_period(it.serviceStart, it.serviceEnd)
            project.items.append(models.ProjectItem(
                contractId=contract.id,
                assetId=it.assetId, qty=it.qty, unit=asset.unit if asset else "",
                price=price, amount=amount,
                origPrice=orig_price, origAmount=orig_amount,  # ADR-018 §2：原价快照
                serviceStart=service_start, serviceEnd=service_end,  # ADR-020：服务期限
                discountRate=it.discountRate,  # DISCOUNT-20261021/ADR-023：折扣率快照（只写不改）
                status=status, deliveryReq=it.deliveryReq,
                itemId=it.itemId,  # ADR-011：遥感明细行落库（非明细行 NULL）
                # 契约 2：落「下单时刻是否真实加锁」事实（repeatSale/明细 repeatSale 下单不加锁）
                locked=bool(asset is not None and not eff_repeat),
                lockedDate=today() if status == "locked" else "",
                confirmedDate="", shippedDate="",
            ))
            total_item_count += 1
    # 项目派生字段落库：status/customer/subject/expectedAmount=Σ合同（ADR-007）
    _recompute_project(project)
    add_log(db, "project", project.name, "新增项目",
            f"创建销售项目 {project.code}，销售记录 {len(contracts_in)} 条，关联产品 {total_item_count} 项",
            operator=operator)
    db.flush()
    return project


# ============================================================
# 合同（ADR-007）：数量联动的最小单位
# ============================================================
def _apply_item_delivery(db: Session, it: models.ProjectItem, operator: str = "",
                         ref: str = "", remark: str = "",
                         customer: str = "", contract_id: int | None = None,
                         project: models.Project | None = None) -> None:
    """单明细交付（项目级/合同级共用，避免两套逻辑漂移）：
    释放锁定（仅 it.locked）→ 非 repeatSale 扣 shippedQty → 累计 soldCount/soldAmount
    → 写 sale_out 流水 → 生成交付记录（精确关联合同）。
    ADR-011：明细行（it.itemId）以 rs_items.repeatSale 为权威（父产品 repeatSale 无意义）。"""
    a = get_asset(db, it.assetId)
    eff_repeat = _item_repeat(db, a, it.itemId)
    if a:
        if not eff_repeat:
            # BUG2 修复：仅当下单时真实加锁（it.locked）才释放锁定，
            # 消灭 repeatSale 期间下单（从未加锁）→ 改回 false → 交付时的幽灵释放
            # ADR-011：明细行传 repeat_override（父产品 repeatSale 无意义，不传会误跳过释放）
            if it.locked:
                apply_item_lock(db, it.assetId, it.qty, False, ref, operator=operator,
                                contract_id=contract_id, repeat_override=eff_repeat)
            # 防御存量脏数据：shippedQty 不得超 quantity（正常路径 locked 守恒时 min 不生效）
            a.shippedQty = min(a.quantity, a.shippedQty + it.qty)
        # ADR-007：repeatSale 与非 repeatSale 交付均累计 soldCount/soldAmount（交付=一次销售）
        a.soldCount += 1
        # 契约 5：Decimal 累加（元口径，ADR-006），禁止夹零；落库前转 float
        a.soldAmount = float(_dec(a.soldAmount) + _dec(it.amount))
        refresh_status(a)
        add_flow(db, a.id, "sale_out", it.qty, a.unit, it.amount,
                 today(), ref, "交付完成交付", operator=operator, contract_id=contract_id)
        # D1：不手写主键；flush 由 DB 生成 id 后再拼交付单号，循环内逐条唯一
        ob = models.Outbound(
            projectId=project.id if project else None,
            contractId=contract_id,
            # FIX-20261020-#7：精确关联本次交付的项目明细——撤销交付按 id 定位，
            # 同合同同产品多明细不再 limit(1) 猜行（存量/手动补录为 NULL）
            projectItemId=it.id,
            projectName=project.name if project else "",
            customer=customer,
            assetId=a.id, assetName=a.name, qty=it.qty, unit=a.unit,
            amount=it.amount, type=_default_outbound_type(a.board),
            mode="new", date=today(),
            # FIX-20261020-#5：经办人取实际触发交付的登录账号（调用方透传 user.username），
            # 不再取 project.rep（生态人员/下单人，与审计日志操作人不一致）
            operator=operator or "admin",
            status="done", remark=remark,
        )
        _flush_with_code(db, ob, lambda oid: f"CK-{str(oid).zfill(4)}")
    it.status = "shipped"
    it.shippedDate = today()


def _apply_item_release(db: Session, it: models.ProjectItem, operator: str = "",
                        ref: str = "", contract_id: int | None = None) -> bool:
    """单明细释放（项目级/合同级共用）：仅 locked/confirmed 且 it.locked（下单时真实加锁）
    才写 cancel_release 流水释放锁定；标记 released。返回是否实际释放。
    ADR-011：明细行以 rs_items.repeatSale 判定（repeat_override，父产品口径无意义）。"""
    if it.status in ("locked", "confirmed"):
        if it.locked:
            a = get_asset(db, it.assetId)
            apply_item_lock(db, it.assetId, it.qty, False, ref, operator=operator,
                            contract_id=contract_id,
                            repeat_override=_item_repeat(db, a, it.itemId))
        it.status = "released"
        return True
    return False


def _derive_project_status(p: models.Project) -> str:
    """项目状态派生（ADR-007；ADR-019 §3 扩展，PRICING-20261020 新增 delivering）：

    | 合同状态集合 | 项目状态 |
    |---|---|
    | 全 pending | pending（待审核） |
    | 全 delivered | delivered（已完成） |
    | 含 terminated 且其余全 pending/terminated | terminated |
    | 全部合同 status ∈ {delivering, delivered}（即全部已签，含已交付） | delivering（交付中） |
    | 其余（含 active 未签完） | active（进行中） |

    无合同→active（存量兼容）。"""
    contracts = p.contracts
    if not contracts:
        return "active"
    statuses = {c.status for c in contracts}
    if statuses == {"pending"}:
        return "pending"
    if statuses == {"delivered"}:
        return "delivered"
    if "terminated" in statuses and statuses <= {"pending", "terminated"}:
        return "terminated"
    # ADR-019 §3：全部已签（delivering/delivered 混合）→ 交付中
    if statuses <= {"delivering", "delivered"}:
        return "delivering"
    return "active"


def _recompute_project(p: models.Project) -> None:
    """合同变更后重算项目派生字段（ADR-007）：
    status（派生）+ expectedAmount=Σ合同 contractAmount（Decimal）+ customer/subject
    （多合同=空字符串，前端显示「N 位客户」；单合同=该合同值；无合同=保持存量值不动）。"""
    contracts = p.contracts
    p.status = _derive_project_status(p)
    total = sum((_dec(c.contractAmount) for c in contracts), Decimal("0"))
    p.expectedAmount = float(total.quantize(CENT))
    p.contractAmount = float(total.quantize(CENT))  # 项目级 contractAmount 兼容口径同 expectedAmount
    if contracts:
        # ADR-013：多记录（一资产一记录）但客户/主体全一致时仍取该值，避免误显「N 位客户」
        customers = {c.customer for c in contracts if c.customer}
        subjects = {c.subject for c in contracts if c.subject}
        p.customer = customers.pop() if len(customers) == 1 else ""
        p.subject = subjects.pop() if len(subjects) == 1 else ""
    p.updatedAt = today()


def change_contract_status(db: Session, contract_id: int, status: str,
                           reason: str = "", operator: str = "",
                           user: "models.User | None" = None) -> None:
    """合同状态变更（ADR-007，数量联动的最小单位）：
    - delivered：逐明细交付（释放锁定+扣 shippedQty+累计销售+生成交付，精确关联合同）；
    - terminated：active 合同→释放锁定；delivered 合同→撤销该合同名下 done 交付并回退；
    - 每次动作后重算项目派生字段（status/expectedAmount/customer/subject）。
    单事务，任一步失败整体回滚（H8）。
    生态人员（viewer）：仅可终止**自己下单项目**的合同（含 delivered 撤销交付），不可交付。"""
    c = get_contract(db, contract_id)
    if not c:
        raise HTTPException(404, "销售记录不存在")
    if c.status == "pending":
        # ADR-012：待审核合同唯一状态出口是订单审核接口（确认下单/驳回）
        raise HTTPException(400, "待审核销售记录不可直接变更状态，请通过订单审核（确认下单/驳回）操作")
    p = get_project(db, c.projectId)
    if not p:
        raise HTTPException(404, "销售记录所属项目不存在")
    if user is not None and user.role == "viewer":
        if not user_sees_project(user, p):
            raise HTTPException(403, "生态人员仅可操作自己下单的项目")
        if status != "terminated":
            raise HTTPException(400, "生态人员仅可终止销售记录（交付需商务人员/管理员操作）")
    # ADR-019（PRICING-20261020）：状态白名单加 delivering；
    # delivering 只能由录入签订时间（PATCH /contracts/{id}）自动触发，不可直接变更
    if status not in ("active", "delivering", "delivered", "terminated"):
        raise HTTPException(400, f"不支持的销售记录状态：{status}")
    if status == "delivering":
        raise HTTPException(400, "「交付中」状态由录入合同签订时间自动触发，不可直接变更")
    if c.status == "terminated":
        raise HTTPException(400, "销售记录已终止，不可再变更状态")
    if c.status == "delivered" and status == "active":
        raise HTTPException(400, "已交付完成的销售记录不可回退到进行中")
    # ADR-019：active→delivered 守卫——合同必须先 delivering（signedDate 非空）才可交付，
    # 否则 400（存量 active 合同需商务先补录签订时间）
    if status == "delivered" and (c.status != "delivering" or not c.signedDate):
        raise HTTPException(400, "合同尚未录入签订时间，不可交付")
    _change_contract_status_core(db, c, status, reason, operator=operator)
    db.commit()


def patch_contract_fields(db: Session, contract_id: int, patch: dict,
                          user: "models.User") -> models.Contract:
    """PATCH /contracts/{id}（ADR-019，PRICING-20261020）：录入合同时间节点。

    patch 为 exclude_unset dict（仅采信客户端实际传了的字段，区分「未传」与「传 null」）：
    - signedDate（合同签订时间）：editor/admin（接手人守卫，与审核同口径：仅该单
      businessOwner 或 admin）；仅合同 active 可录入（录入即 active→delivering +
      项目重算）；录后可改（delivering 状态改值）、**传 null/空清空 → 400**
      「签订时间录入后不可清空」；
    - scheduledDeliveryDate（预计交付时间）：**仅 admin**（非 admin 403）；
      仅合同 delivering 可录/改/清空（null 允许，可纠正）。
    viewer 直接 403「只读账号不可执行该操作」（该端点仅 editor/admin 使用）。
    返回更新后的合同。"""
    c = get_contract(db, contract_id)
    if not c:
        raise HTTPException(404, "销售记录不存在")
    p = get_project(db, c.projectId)
    if not p:
        raise HTTPException(404, "销售记录所属项目不存在")
    # 契约 §5：该端点仅 editor/admin 使用，viewer 直接 403
    if user.role == "viewer":
        raise HTTPException(403, "只读账号不可执行该操作")
    is_admin = user.role == "admin"

    if "signedDate" in patch:
        # 接手人守卫（与 review 同口径）：仅该单商务负责人可录，admin 越过
        if not is_admin and (p.businessOwner or "").strip() != user.username:
            raise HTTPException(403,
                f"仅接手的商务负责人（{p.businessOwner}）可录入合同签订时间，如需处理请先转交")
        val = (patch.get("signedDate") or "").strip()
        if not val:
            # 传 null/空 = 清空：已有签订时间则拒绝（录后不可清空回退）
            if c.signedDate:
                raise HTTPException(400, "签订时间录入后不可清空")
        else:
            _validate_date_str(val, "合同签订时间")
            if c.status not in ("active", "delivering"):
                # 录入/修改仅合同签订中（active）与交付中（delivering，录后改值）允许
                raise HTTPException(400, "仅「合同签订中」状态的合同可录入/修改签订时间")
            c.signedDate = val
            if c.status == "active":
                # ADR-019：录 signedDate 即 active → delivering（不扣量，交付时才扣）
                c.status = "delivering"
                _recompute_project(p)
            c.updatedAt = today()
            add_log(db, "contract", c.code, "录入合同签订时间",
                    f"销售记录 {c.code}（客户 {c.customer}）签订时间 {val}，状态 → 交付中",
                    contract_id=c.id, operator=user.username)

    if "scheduledDeliveryDate" in patch:
        # ADR-019：预计交付时间仅 admin（系统「管理人员账号」= admin 角色）
        if not is_admin:
            raise HTTPException(403, "仅管理员可录入预计交付时间")
        val = (patch.get("scheduledDeliveryDate") or "").strip()
        if val:
            _validate_date_str(val, "预计交付时间")
        if c.status != "delivering":
            raise HTTPException(400, "仅「交付中」状态的合同可录入/修改/清空预计交付时间")
        c.scheduledDeliveryDate = val or None  # null 允许（可纠正）
        c.updatedAt = today()
        add_log(db, "contract", c.code, "录入预计交付时间",
                f"销售记录 {c.code}（客户 {c.customer}）预计交付时间 {val or '（已清空）'}",
                contract_id=c.id, operator=user.username)

    db.commit()
    db.refresh(c)
    return c


def _validate_business_owner(db: Session, username: str) -> None:
    """商务负责人账号校验（claim 转交 + 建单入口指定负责人共用）。
    【核心业务规则 ADR-012 §5.1】businessOwner 只允许绑定真实可用的商务/管理员账号
    （存在 + 启用 + editor/admin 角色）——防止脏负责人导致单据永久卡死在 pending
    （任何商务都不满足「仅负责人可转交」、review 守卫也放行不了）。"""
    name = (username or "").strip()
    if not name:
        return
    tgt = db.query(models.User).filter(models.User.username == name).first()
    if tgt is None or not tgt.enabled or tgt.role not in ("editor", "admin"):
        raise HTTPException(400, f"「{name}」不是可用的商务账号，请重新选择")


def claim_project(db: Session, project_id: int, user: models.User,
                  new_owner: str = "") -> str:
    """商务接手/转交（ADR-012 §5.1，纯移交制）：

    - 无负责人（pending/active 均可）：任意商务/管理员 → **接手**（绑定自己）；
    - 已有负责人（**移交**）：仅**当前负责人**可转交——必须传 `new_owner`（启用的商务/管理员账号）；
      admin 越过：可接手（绑自己）或转交给任意账号；
      非负责人的普通商务 → 400（不可抢单，权责清晰）；
    - delivered/terminated 终态 → 400。
    返回动作标识（"接手订单" / "转交订单"，路由层写审计）。"""
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    if p.status in ("delivered", "terminated"):
        raise HTTPException(400, "该订单已完成/已终止，不可接手或转交")
    old = (p.businessOwner or "").strip()
    is_admin = user.role == "admin"
    if not old:
        target = user.username  # 无主 → 接手（绑定操作人）
    elif old == user.username:
        # 负责人移交：必须指定新负责人
        new_owner = (new_owner or "").strip()
        if not new_owner:
            raise HTTPException(400, "请指定转交的目标商务账号")
        if new_owner == user.username:
            raise HTTPException(400, "转交目标不能是自己")
        target = new_owner
    else:
        if not is_admin:
            raise HTTPException(400, f"该订单由商务负责人「{old}」负责，仅其本人可转交（如需介入请联系 admin 处理）")
        target = (new_owner or "").strip() or user.username  # admin：指定则转交，未指定接手给自己
    _validate_business_owner(db, target)
    p.businessOwner = target
    if old:
        add_log(db, "project", p.name, "转交订单",
                f"商务负责人 {old} → {target}", operator=user.username)
        db.commit()
        return "转交订单"
    add_log(db, "project", p.name, "接手订单",
            f"商务负责人绑定为 {target}", operator=user.username)
    db.commit()
    return "接手订单"


def review_project(db: Session, project_id: int, data: schemas.ReviewInput,
                   operator: str = "", user: models.User | None = None) -> None:
    """订单审核（ADR-012，仅商务/管理员，路由层 require_editor）：pending 项目
    确认下单（可带改价 + 服务期限）或驳回（释放锁定 + 留痕）。

    confirm：改价只改合同行——unit 行传实际单价（amount = price×qty 重算）、
    amount 行传实际合同金额（整数元，price 派生反算）；遥感明细行仅可改本行销售金额
    （2026-10-20 放开，不回写 rs_items 明细单价）；
    ADR-018 §4（PRICING-20261020）：**删除**终审改价回写 assets.salePrice 的逻辑——
    挂牌价与参考区间仅由产品管理维护，改价只写 ProjectItem.price/amount（orig 快照不动）；
    ADR-020：行级入参可改服务期限（serviceStart/serviceEnd，格式/顺序校验）；
    数量审核时不可改（需改数量 → 驳回重下）；确认后存在 amount<=0 行 → 400；
    合同 pending→active、项目派生 → active。
    reject：reason 必填；逐明细释放锁定（仅 it.locked）；合同 pending→terminated
    （remark 留痕「驳回：{reason}」）、项目 terminated。单事务（H8）。"""
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    if p.status != "pending":
        raise HTTPException(400, "仅待审核项目可审核（确认下单/驳回）")
    # ADR-012 §5.1 接手人守卫：未接手 400；非接手人仅 admin 可越过（日志留痕实际操作人由路由层审计覆盖）
    if user is not None:
        if not (p.businessOwner or "").strip():
            raise HTTPException(400, "该订单尚未被商务接手，请先接手后再操作")
        if p.businessOwner != user.username and user.role != "admin":
            raise HTTPException(400,
                f"仅接手的商务负责人（{p.businessOwner}）可调整该订单价格，如需处理请先转交")
    contracts = list(p.contracts)

    if data.action == "reject":
        if not (data.reason or "").strip():
            raise HTTPException(400, "驳回原因不能为空")
        reason = data.reason.strip()
        for c in contracts:
            for it in c.items:
                _apply_item_release(db, it, operator=operator, ref=c.code, contract_id=c.id)
            c.status = "terminated"
            # 留痕：生态人员经 bootstrap 仍可见驳回原因
            # FIX-20261020-#11：追加而非覆盖——原合同备注（下单时的说明）必须保留
            if (c.remark or "").strip():
                c.remark = f"{c.remark}｜驳回：{reason}"
            else:
                c.remark = f"驳回：{reason}"
            c.updatedAt = today()
        _recompute_project(p)
        add_log(db, "project", p.name, "驳回订单",
                f"项目 {p.code} 订单已驳回：{reason}（锁定已释放）", operator=operator)
        db.commit()
        return

    if data.action != "confirm":
        raise HTTPException(400, f"不支持的审核动作：{data.action}")

    # confirm：应用行级改价（只改合同行，未传改价的行保持原值）
    # ADR-018 §4（PRICING-20261020）：不再装配 price_changes_by_asset、不再回写挂牌价
    by_id = {i.itemId: i for i in data.items}
    diffs: list[str] = []
    for c in contracts:
        for it in c.items:
            ri = by_id.get(it.id)
            if ri is None:
                continue
            if it.itemId is not None:
                # 2026-10-20：遥感明细行放开审核改价——仅改**本行**销售金额（整数元，price 派生反算）；
                # 不回写 rs_items.price（明细单价属产品「可售明细」主数据）也不进 price_changes_by_asset
                #（不污染平台挂牌价）——订单级一次性价调整，其他订单不受影响
                if ri.amount is None:
                    continue
                amt = _validate_amount_yuan(ri.amount)
                old_amount = it.amount
                it.amount = float(amt)
                it.price = _derived_price(amt, it.qty)  # 派生参考单价（元/个）展示
                rs = db.get(models.RsItem, it.itemId)
                a = get_asset(db, it.assetId)
                name = f"{a.name}·{_rs_item_desc(rs)}" if (a and rs) else f"遥感明细 #{it.itemId}"
                diffs.append(f"{name} 销售金额 {old_amount:g} → {it.amount:g} 元")
                continue
            a = get_asset(db, it.assetId)
            old_price, old_amount = it.price, it.amount
            if a is not None and _is_amount_mode(a):
                if ri.amount is None:
                    continue
                amt = _validate_amount_yuan(ri.amount)
                it.amount = float(amt)
                it.price = _derived_price(amt, it.qty)  # 派生参考单价（元/个）反算展示
                # ADR-018 §4：不再回写 assets.salePrice（orig 快照永不触碰）
                name = a.name
                diffs.append(f"{name} 销售金额 {old_amount:g} → {it.amount:g} 元")
            else:
                if ri.price is None:
                    continue
                if ri.price <= 0:
                    raise HTTPException(400, "单价须大于 0")
                it.price = float(ri.price)
                it.amount = float((_dec(ri.price) * it.qty).quantize(CENT))
                # ADR-018 §4：不再回写 assets.salePrice（orig 快照永不触碰）
                name = a.name if a else f"产品 #{it.assetId}"
                diffs.append(f"{name} 单价 {old_price:g} → {it.price:g} 元")
    # 合同合计重算（派生 = Σ 行 amount）
    for c in contracts:
        c.contractAmount = float(
            sum((_dec(it.amount) for it in c.items), Decimal("0")).quantize(CENT))
    # 确认守卫：防 0 元单生效（覆盖参考价未设的极端路径）
    all_items = [it for c in contracts for it in c.items]
    # 2026-10-19 排查修复（S1）：空草稿项目（0 明细）不可 confirm——否则产生 0 元 0 明细的
    # 「已生效」项目且可被批量「交付」，唯一出口只剩终止
    if not all_items:
        raise HTTPException(400, "该订单没有销售明细，请补充明细后再确认（或删除该草稿订单）")
    for it in all_items:
        # 2026-10-19 排查修复（S2）：未关联产品的明细行（pending_asset）不可 confirm——
        # 确认后再交付恒 400，只能终止；与交付口径对齐提前拦截
        if it.status == "pending_asset" or it.assetId is None:
            raise HTTPException(400, "存在未关联产品的明细行，请先关联产品或删除该行再确认")
        if _dec(it.amount) <= 0:
            raise HTTPException(400, "存在未定价明细，请先填写单价/销售金额")
    # ADR-018 §4（PRICING-20261020）：原「写回平台挂牌价」逻辑整体删除——
    # 挂牌价/参考区间仅由产品管理维护，终审改价只定本单价格（ProjectItem.price/amount）
    # ADR-020（PRICING-20261020）：confirm 可改服务期限（只写 ProjectItem，格式/顺序校验）
    for c in contracts:
        for it in c.items:
            ri = by_id.get(it.id)
            if ri is None or (ri.serviceStart is None and ri.serviceEnd is None):
                continue
            # 只传一边时与存量另一边组合校验（防改一边造成 start > end）
            new_start, new_end = _validate_service_period(
                ri.serviceStart if ri.serviceStart is not None else it.serviceStart,
                ri.serviceEnd if ri.serviceEnd is not None else it.serviceEnd)
            it.serviceStart, it.serviceEnd = new_start, new_end
    for c in contracts:
        c.status = "active"
        c.updatedAt = today()
    _recompute_project(p)
    add_log(db, "project", p.name, "确认下单",
            f"项目 {p.code} 订单已确认" + (f"，改价：{'；'.join(diffs)}" if diffs else ""),
            operator=operator)
    db.commit()


def _release_contract_items(db: Session, c: models.Contract, operator: str = "") -> int:
    """合同级联释放（项目删除用）：active 合同释放全部 locked/confirmed 明细锁定。"""
    released = 0
    for it in c.items:
        if _apply_item_release(db, it, operator=operator, ref=c.code, contract_id=c.id):
            released += 1
    return released


def _revert_contract_outbounds(db: Session, c: models.Contract, operator: str = "") -> int:
    """合同级联撤销（项目删除用）：delivered 合同撤销名下全部 done 交付并回退数量/金额。"""
    obs = db.execute(
        select(models.Outbound).where(
            models.Outbound.contractId == c.id,
            models.Outbound.status == "done",
        )
    ).scalars().all()
    for ob in obs:
        # 批量级联撤销：不回滚合同状态（合同已随项目删除，释放由调用方统一决定）
        _revert_outbound_inner(db, ob.id, "项目删除回滚", operator=operator, restore_contract=False)
    for it in c.items:
        if it.status == "shipped":
            it.status = "released"
    return len(obs)


def update_project(db: Session, project_id: int, data: schemas.ProjectInput,
                   operator: str = "", user: "models.User | None" = None) -> None:
    """编辑项目（ADR-007 起）：仅保留**项目基本信息**编辑
    （name/industry/rep/remark/日期；quoteAmount/paidAmount 2026-10-19 废弃不再写入）。

    - 合同与明细的结构编辑本次不做：合同一经生成不可增删改明细（终止再重下），
      故入参中的 items / contracts / customer / subject / expectedAmount / contractAmount
      **一律忽略**（customer/subject/expectedAmount 为合同派生字段，见 _recompute_project）。
    - 编辑约束（判断改为合同口径）：存在 delivered 合同则不可编辑；
      存量无合同项目沿用旧规则（status != active 不可编辑）。
    - 生态人员（viewer）：可编辑**自己下单**的项目基本信息（2026-10-16），
      但 rep（生态人员）字段不可改——防止把项目转给他人后越权。
    """
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    if user is not None and user.role == "viewer" and not user_sees_project(user, p):
        raise HTTPException(403, "生态人员仅可编辑自己下单的项目")
    # ADR-012 §5.1：pending 项目基本信息仅负责人（或 admin 越过）可编辑
    #（viewer 为下单人本身，上面已限定仅自己项目，保留可编辑）
    if p.status == "pending" and user is not None and user.role not in ("viewer", "admin"):
        if (p.businessOwner or "").strip() != user.username:
            raise HTTPException(400, "待审核项目仅商务负责人（或管理员）可编辑基本信息")
    # 项目名非空（防止被清空；与 _create_project_core 口径一致）
    if not (data.name or "").strip():
        raise HTTPException(400, "项目名称不能为空")
    data.name = data.name.strip()
    if p.contracts:
        # FIX-6a：与前端 canEditProject 对齐——派生状态 terminated（全合同终止/混合 delivered+terminated）不可编辑
        if _derive_project_status(p) == "terminated":
            raise HTTPException(400, "项目已终止，不可编辑")
        if any(c.status == "delivered" for c in p.contracts):
            raise HTTPException(400, "已交付完成的项目不可编辑")
    else:
        # 存量兼容：无合同项目沿用旧规则（terminated 单列新文案，与合同口径一致）
        if p.status == "terminated":
            raise HTTPException(400, "项目已终止，不可编辑")
        if p.status != "active":
            raise HTTPException(400, "已完成/已终止项目不可编辑")
    # 仅覆盖项目基本信息（不含 status/customer/subject/expectedAmount/contractAmount——派生字段）。
    # ADR-012 §5.1：businessOwner **不在可写字段**——唯一写入口是 claim（接手/转交）接口，
    # 防止任意商务通过编辑表单越权重设负责人（入参同名值一律忽略）
    # 2026-10-19：quoteAmount/paidAmount 已废弃移出白名单（不再写入；存量值保留在库中不覆盖）
    for k in ("name", "industry", "rep",
              "expectedSignDate", "lastFollowDate", "remark"):
        # 生态人员（viewer）不可修改 rep（生态人员）字段：改了即「项目不属于自己」，越权转移
        if k == "rep" and user is not None and user.role == "viewer":
            continue
        setattr(p, k, getattr(data, k))
    p.updatedAt = today()
    add_log(db, "project", p.name, "编辑", "更新销售项目", operator=operator)
    db.commit()


def change_project_status(db: Session, project_id: int, data: schemas.StatusInput,
                          operator: str = "", user: "models.User | None" = None) -> None:
    """项目级状态变更（ADR-007 起，批量快捷语义）：

    项目 status 为合同派生字段，本接口保留为**批量快捷入口**——
    对名下全部 active 合同批量执行该状态动作（delivered=全部交付、terminated=全部终止），
    前端主入口用合同级 PATCH /contracts/{id}/status。
    存量无合同项目走旧的项目级明细逻辑（兼容路径）。
    生态人员（viewer）：仅可终止**自己下单**的项目（含**待审核订单的取消**；交付需商务/管理员）。
    商务/管理员对 pending 项目仍只能走订单审核接口（确认下单/驳回），不可绕过审核直接改状态。
    """
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    is_viewer_own = (
        user is not None
        and user.role == "viewer"
        and user_sees_project(user, p)
    )
    if p.status == "pending":
        # ADR-012：待审核项目状态出口是订单审核接口（确认下单/驳回）；
        # 2026-10-19 新增：下单生态人员可终止（取消）自己的待审核订单——释放锁定、记录留存、不可再编辑
        if not (is_viewer_own and data.status == "terminated"):
            raise HTTPException(
                400, "待审核项目不可直接变更状态，请通过订单审核（确认下单/驳回）操作")
    if user is not None and user.role == "viewer":
        if not is_viewer_own:
            raise HTTPException(403, "生态人员仅可操作自己下单的项目")
        if data.status != "terminated":
            raise HTTPException(400, "生态人员仅可终止项目（交付需商务人员/管理员操作）")
    status, reason = data.status, data.reason
    if p.contracts:
        # 批量语义：仅 delivered / terminated 是合同动作；active 由合同派生，不可直接设置
        if status not in ("delivered", "terminated"):
            raise HTTPException(400, "项目状态由销售记录状态派生，仅支持批量 delivered/terminated（active 请直接变更销售记录状态）")
        if p.status == "terminated" and status == "delivered":
            raise HTTPException(400, "项目已终止，不可再变更状态")
        # 2026-10-19：pending 项目（生态取消自己的待审核单）目标为 pending 记录；
        # 其余场景（批量交付 / 终止进行中）为 active 记录；
        # ADR-019（PRICING-20261020）：批量交付同样覆盖 delivering 记录（已签待交付）
        target_states = ("pending",) if p.status == "pending" else ("active", "delivering")
        targets = [c for c in p.contracts if c.status in target_states]
        if not targets:
            raise HTTPException(400, "项目下没有可执行的销售记录（进行中/待审核），无可批量执行")
        for c in targets:
            # 复用合同级核心（不提交），单事务收敛（H8）
            _change_contract_status_core(db, c, status, reason, operator=operator)
        add_log(db, "project", p.name, "状态变更",
                f"项目批量{('交付' if status == 'delivered' else '终止')}：名下 {len(targets)} 条销售记录已执行",
                operator=operator)
        db.commit()
        return
    # 存量兼容：无合同项目走旧的项目级明细逻辑
    _legacy_change_project_status(db, p, status, reason, operator=operator)
    db.commit()


def _change_contract_status_core(db: Session, c: models.Contract, status: str,
                                 reason: str = "", operator: str = "") -> None:
    """合同状态变更核心（不提交）：供 change_contract_status / 项目级批量复用（H8）。"""
    p = get_project(db, c.projectId)
    from_status = c.status
    if status == from_status:
        return
    if status == "delivered":
        # 待关联产品明细（assetId=null，仅手动建项目 API 可产生）无法交付——
        # 若放行，合同会被置 delivered、项目派生「已完成」，明细永久悬挂。
        pending = [it for it in c.items if it.status == "pending_asset"]
        if pending:
            raise HTTPException(400,
                f"合同 {c.code} 尚有 {len(pending)} 项明细未关联产品，无法交付完成（请先终止该销售记录）")
        for it in c.items:
            # H4：locked/confirmed 均处理（含零价 amount=0 明细），不再因金额为 0 被跳过
            if it.status in ("confirmed", "locked"):
                _apply_item_delivery(
                    db, it, operator=operator, ref=c.code,
                    remark=f"销售记录「{c.code}」交付完成自动生成",
                    customer=c.customer, contract_id=c.id, project=p,
                )
        c.status = "delivered"
        c.updatedAt = today()
        _recompute_project(p)
        add_log(db, "project", p.name, "销售记录状态变更",
                f"销售记录 {c.code}（客户 {c.customer}）交付完成，已生成交付记录并累计销售金额",
                contract_id=c.id, operator=operator)
    elif status == "terminated":
        released = 0
        reverted = 0
        # 2026-10-19：pending 合同终止同样释放锁定（原仅 active 分支，pending 终止会漏释放）——
        # 支撑「生态人员终止自己待审核订单」场景（项目级批量终止，见 change_project_status）
        # ADR-019（PRICING-20261020）：delivering 合同终止同样释放锁定（交付前锁定未释放）
        if from_status in ("active", "pending", "delivering"):
            # active/pending/delivering 合同终止：释放锁定（仅 it.locked，沿用 ADR 修复机制）
            for it in c.items:
                if _apply_item_release(db, it, operator=operator, ref=c.code,
                                       contract_id=c.id):
                    released += 1
        else:  # delivered 合同终止：撤销该合同名下 done 交付 + 回退 shippedQty/soldCount/soldAmount
            obs = db.execute(
                select(models.Outbound).where(
                    models.Outbound.contractId == c.id,
                    models.Outbound.status == "done",
                )
            ).scalars().all()
            for ob in obs:
                _revert_outbound_inner(db, ob.id, f"销售记录终止（{c.code}）", operator=operator, restore_contract=False)
                reverted += 1
            for it in c.items:
                if it.status == "shipped":
                    it.status = "released"
        c.status = "terminated"
        c.updatedAt = today()
        _recompute_project(p)
        add_log(db, "project", p.name, "销售记录状态变更",
                f"销售记录 {c.code}（客户 {c.customer}）终止：释放锁定 {released} 项，撤销交付 {reverted} 条"
                + (f"，原因：{reason}" if reason else ""),
                contract_id=c.id, operator=operator)


def _legacy_change_project_status(db: Session, p: models.Project, status: str,
                                  reason: str = "", operator: str = "") -> None:
    """存量兼容（无合同项目）：旧的项目级明细状态逻辑，行为与 ADR-007 前一致。"""
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
        # 与合同口径一致：待关联产品明细无法交付，放行会留下「已完成项目悬挂 pending 明细」
        pending = [it for it in p.items if it.status == "pending_asset"]
        if pending:
            raise HTTPException(400,
                f"项目 {p.code} 尚有 {len(pending)} 项明细未关联产品，无法交付完成（请先终止该项目）")
        for it in p.items:
            if it.status in ("confirmed", "locked"):
                _apply_item_delivery(
                    db, it, operator=operator, ref=p.code,
                    remark=f"项目「{p.name}」交付完成自动生成",
                    customer=p.customer, project=p,
                )
        add_log(db, "project", p.name, "状态变更", "交付完成，已生成交付记录并累计销售金额",
                operator=operator)

    if status == "terminated":
        _terminate_project(db, p, reason, operator=operator)


def _terminate_project(db: Session, p: models.Project, reason: str,
                       operator: str = "") -> None:
    """项目终止：释放未交付的锁定 + 撤销该项目名下已完成的交付（回退 shippedQty/soldAmount/soldCount）。

    FIX-2 说明（终止≠删除）：合同口径下项目终止**不做**「挂项目手动交付（contractId == null）」
    的回滚——手动交付是独立动作，终止只影响合同名下交付（见 _change_contract_status_core）；
    手动交付的撤销仅在「删除项目」时发生（delete_project）。本函数仅服务于**存量无合同**
    legacy 路径（终止/删除共用旧的全量撤销语义），不新增合同口径逻辑。"""
    released = 0
    for it in p.items:
        if it.status in ("locked", "confirmed"):
            # BUG2 修复：仅当下单时真实加锁（it.locked）才释放，
            # 消灭 repeatSale 期间下单（从未加锁）→ 终止时的 cancel_release 幽灵流水
            if it.locked:
                apply_item_lock(db, it.assetId, it.qty, False, p.code, operator=operator)
            it.status = "released"
            released += 1
    # 撤销该项目名下所有已完成交付（含交付完成自动生成 + 手动登记）
    obs = db.execute(
        select(models.Outbound).where(
            models.Outbound.projectId == p.id,
            models.Outbound.status == "done",
        )
    ).scalars().all()
    for ob in obs:
        _revert_outbound_inner(db, ob.id, "项目终止", operator=operator, restore_contract=False)
    # 已交付明细标记为已释放
    for it in p.items:
        if it.status == "shipped":
            it.status = "released"
    add_log(db, "project", p.name, "状态变更",
            f"项目终止：释放锁定 {released} 项，撤销交付 {len(obs)} 条，回退对应数量与累计销售金额"
            + (f"，原因：{reason}" if reason else ""), operator=operator)


def delete_project(db: Session, project_id: int, operator: str = "") -> None:
    """删除项目（ADR-007 起，合同级联）：先按合同回滚——
    active 合同释放锁定、delivered 合同撤销名下 done 交付（回退 shippedQty/soldCount/soldAmount）
    → FIX-2：再撤销挂项目的手动交付（contractId == null 的 done 交付）
    → 再硬删项目及其合同、明细（cascade）→ 写 OpLog。
    存量无合同项目沿用旧逻辑（_terminate_project，其全量撤销已含手动交付）。
    单事务，任一步失败整体回滚（H8）。"""
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    name, code = p.name, p.code
    if p.contracts:
        for c in list(p.contracts):
            # ADR-012：pending（待审核）合同与 active 同语义——锁定需释放；
            # ADR-019（PRICING-20261020）：delivering 合同锁定同样未释放，需一并释放
            if c.status in ("active", "pending", "delivering"):
                _release_contract_items(db, c, operator=operator)
            elif c.status == "delivered":
                _revert_contract_outbounds(db, c, operator=operator)
        # FIX-2：同时撤销挂项目的手动交付（contractId == null 的 done 交付）——
        # 合同交付已在 _revert_contract_outbounds 按 contractId 撤销，此处补齐手动登记部分，
        # 与前端删除确认文案「撤销该项目已生成的交付记录」对齐（复用 _revert_outbound_inner：
        # 写「交付撤销」日志 + 回退流水 + 回退 shippedQty/soldCount/soldAmount）。
        manual_obs = db.execute(
            select(models.Outbound).where(
                models.Outbound.projectId == p.id,
                models.Outbound.contractId.is_(None),
                models.Outbound.status == "done",
            )
        ).scalars().all()
        for ob in manual_obs:
            _revert_outbound_inner(db, ob.id, "项目删除回滚", operator=operator, restore_contract=False)
    else:
        # 存量兼容：无合同项目走旧的项目级回滚
        _terminate_project(db, p, "项目删除回滚", operator=operator)
    db.delete(p)  # 级联删除合同 + 明细（cascade delete-orphan）
    add_log(db, "project", name, "删除", f"删除项目 {code}（已回滚锁定与交付）", operator=operator)
    db.commit()


# ============================================================
# 交付
# ============================================================
def create_outbound(db: Session, data: schemas.OutboundInput, operator: str = "") -> models.Outbound:
    # FIX-20261020-#13a：qty=0 不再放行（此前 ge=0 可建 0 数量交付记录且仍 soldCount+1）
    if data.qty <= 0:
        raise HTTPException(400, "交付数量必须大于 0")
    a = get_asset(db, data.assetId)
    if not a:
        raise HTTPException(400, "产品不存在")
    # FIX-20261020-#9：遥感父产品（容器）不可直接交付——只能对其数据明细交付
    #（OutboundInput 无 itemId，任何挂容器的交付都属父产品交付）
    if a.type == "遥感数据":
        raise HTTPException(400, "遥感容器不可直接交付，请交付其数据明细")
    p = get_project(db, data.projectId)
    # FIX-20261020-#9：项目归属校验——待审核（审核前不可产生交付）/已终止项目不可登记交付
    if p is not None and p.status in ("pending", "terminated"):
        raise HTTPException(400, "该项目当前状态不可登记交付")
    # FIX-20261020-#9：产品必须属于所选项目明细（任意产品挂任意项目会绕过审核产生销售额）
    if p is not None and not any(it.assetId == a.id for it in p.items):
        raise HTTPException(400, "该产品不属于所选项目")
    # 防重复交付
    if p and data.mode == "new":
        items = [it for it in p.items if it.assetId == a.id]
        if items and all(it.status in ("shipped", "released") for it in items):
            raise HTTPException(400,
                f"项目「{p.name}」下该产品的明细已全部交付/释放，请勿重复登记；历史记录请改用「历史补录」")
    # FIX-1：手动交付补可售校验——mode != "history"（补录不扣数量）且产品非 repeatSale（可重复售卖
    # 不占数量，跳过）时，按当前库值校验 qty <= quantity - lockedQty - shippedQty，超量 400。
    # 交付是独立动作，仅按当前库值校验（本单其它明细/合同锁定不在其范围）。
    # ADR-015：校验基于**未改动**的 lockedQty（下方库存变更不再触碰 lockedQty）。
    if data.mode != "history" and not a.repeatSale:
        avail = a.quantity - a.lockedQty - a.shippedQty
        if data.qty > avail:
            raise HTTPException(400,
                f"交付数量超出可用数量：{a.name} 可售 {avail}{a.unit}，本次交付 {data.qty}{a.unit}")
    ob = models.Outbound(
        projectId=p.id if p else None,
        projectName=p.name if p else (f"补录-{data.customer}" if data.customer else "补录"),
        customer=p.customer if p else data.customer,
        assetId=a.id, assetName=a.name, qty=data.qty, unit=a.unit,
        amount=float(_dec(data.amount).quantize(CENT)),  # 元口径，精确到分（ADR-006）
        type=data.type, mode=data.mode, date=data.date,
        # 操作人取路由层真实登录账号（require_editor 已保证非空），
        # 不再采信前端入参 data.operator（可伪造，导致业务表与审计表操作人不一致）
        operator=operator or "admin", status="done", remark=data.remark,
    )
    # D1：flush 生成 id 后再拼 CK-{4位} 单号（不手写主键）
    _flush_with_code(db, ob, lambda oid: f"CK-{str(oid).zfill(4)}")
    if data.mode != "history":
        # 口径统一（与 _apply_item_delivery 对齐）：交付即一次销售，soldCount 一律 +1
        # （修复：此前仅 repeatSale 分支 +1，与合同交付路径「交付=计次」口径不一致）
        a.soldCount += 1
        if not a.repeatSale:
            # ADR-015（FIX-20261020-#2）：手动补录交付**不触碰 lockedQty**——补录不对应任何
            # 订单明细、也未释放过对应锁，偷减会侵占其他订单的锁定并造成超卖/撤销后凭空增可售。
            # 仅 shippedQty += qty（min 夹零防御：shippedQty 不超 quantity）
            a.shippedQty = min(a.quantity, a.shippedQty + data.qty)
        # 契约 5：Decimal 累加（元口径，ADR-006），禁止夹零
        a.soldAmount = float(_dec(a.soldAmount) + _dec(ob.amount))
        refresh_status(a)
    add_flow(
        db, a.id, "sale_out", data.qty, a.unit, ob.amount, data.date, ob.code,
        "历史交付补录（不扣减数量）" if data.mode == "history" else ("销售交付" if p else "交付补录"),
        operator=operator,
    )
    add_log(db, "outbound", a.name,
            "历史补录" if data.mode == "history" else "销售交付",
            f"{ob.code} 交付 {data.qty}{a.unit}，金额 {_fmt_amount_yuan(ob.amount)}"
            + ("（不扣减数量）" if data.mode == "history" else ""), operator=operator)
    db.commit()
    db.refresh(ob)
    return ob


def _revert_outbound_inner(db: Session, outbound_id: int, reason: str,
                           operator: str = "", restore_contract: bool = True) -> bool:
    """撤销交付（不提交事务，供批量回退复用）；返回是否实际撤销

    restore_contract（2026-10-19）：单条撤销（交付记录页「撤销」）时，把关联合同回滚到
    「进行中」（明细重新锁定 + 项目状态重算）。合同终止 / 项目删除的**批量级联撤销**
    必须传 False——终止/删除的最终状态由调用方统一决定（released/terminated），
    若逐条回滚时先回滚合同再释放，会把本应释放的数量错误地重新加锁。"""
    ob = db.get(models.Outbound, outbound_id)
    if not ob or ob.status == "reverted":
        return False
    a = get_asset(db, ob.assetId)
    ob.status = "reverted"
    contract_restored = False
    it = None
    if a and ob.mode != "history":
        # ADR-011：合同交付的 shippedQty 回退按明细行权威——按 contractId+assetId 查明细取 itemId，
        # 明细行以 rs_items.repeatSale 判定（父产品 repeatSale 无意义）；手动交付保持产品口径
        eff_repeat = a.repeatSale
        if ob.projectItemId is not None:
            # FIX-20261020-#7：交付记录已精确关联明细（合同交付写入 it.id）→ 按 id 定位，
            # 同合同同产品多明细不再取错行（明细已随项目删除时回退下方 limit(1) 兼容逻辑）
            it = db.get(models.ProjectItem, ob.projectItemId)
        if it is None and ob.contractId is not None:
            # 存量记录（projectItemId 为 NULL）：回退 contractId+assetId limit(1) 兼容逻辑
            it = db.execute(
                select(models.ProjectItem).where(
                    models.ProjectItem.contractId == ob.contractId,
                    models.ProjectItem.assetId == ob.assetId,
                ).limit(1)
            ).scalars().first()
            if it is not None and it.itemId:
                rs = db.get(models.RsItem, it.itemId)
                if rs is not None:
                    eff_repeat = rs.repeatSale
        if not eff_repeat:
            a.shippedQty = max(0, a.shippedQty - ob.qty)
        # FIX-3 + 口径统一：创建侧（合同交付 _apply_item_delivery / 手动交付 create_outbound）
        # 现均一律 soldCount+1（交付=一次销售，历史补录除外）→ 撤销一律 -1。
        # 注意：口径统一前创建的非 repeatSale 手动交付当时未 +1，其撤销会 -1，
        # max(0, …) 夹零保证不为负（存量数据最多少计一次，可接受）。
        a.soldCount = max(0, a.soldCount - 1)
        # 契约 5：Decimal 回退（元口径，ADR-006）；不再用 max(0,...) 静默夹零（若为负将直接暴露）
        a.soldAmount = float(_dec(a.soldAmount) - _dec(ob.amount))
        refresh_status(a)
        add_flow(db, a.id, "manual_adjust", -ob.qty, a.unit, -ob.amount, today(), ob.code,
                 f"交付撤销：{reason}", operator=operator)
        # 2026-10-19 修复：撤销「合同交付」生成的交付记录后，把合同回滚到「进行中」——
        # 明细重新锁定（交付释放的锁反向恢复）+ 清除交付日期 + 项目状态重算。
        # 此前仅回退产品数量，合同仍停留 delivered，项目详情页状态不随撤销变化。
        # 再交付安全性：合同交付分支只处理 locked/confirmed 明细（跳过 shipped），
        # 故重新「交付」合同时只会补交被撤销的这条明细，不会重复扣量。
        if restore_contract and it is not None and it.status == "shipped":
            if it.locked and not eff_repeat:
                # 交付时释放过锁定（仅 it.locked 为真才释放过）→ 反向重新加锁
                apply_item_lock(db, it.assetId, it.qty, True, ob.code,
                                operator=operator, contract_id=ob.contractId,
                                repeat_override=eff_repeat)
            it.status = "locked"
            it.shippedDate = ""
            c = db.get(models.Contract, ob.contractId)
            if c is not None and c.status == "delivered":
                # ADR-019（PRICING-20261020）：撤销交付回退目标从 active 改为 delivering——
                # signedDate 仍在（录后不可清空），不能回「合同签订中」
                c.status = "delivering"
                c.updatedAt = today()
                p = get_project(db, c.projectId)
                if p is not None:
                    _recompute_project(p)
                contract_restored = True
    elif a:
        add_flow(db, a.id, "manual_adjust", 0, a.unit, 0, today(), ob.code,
                 f"撤销历史补录（不调整数量）：{reason}", operator=operator)
    add_log(db, "outbound", ob.assetName, "交付撤销",
            f"{ob.code} 已撤销" + ("（历史补录，不调整数量）" if ob.mode == "history" else "")
            + ("，关联销售记录已回退「进行中」并重新锁定明细" if contract_restored else "")
            + f"，原因：{reason}",
            operator=operator)
    return True


def revert_outbound(db: Session, outbound_id: int, reason: str, operator: str = "") -> None:
    _revert_outbound_inner(db, outbound_id, reason, operator=operator)
    db.commit()


# ============================================================
# 基础资料
# ============================================================
def add_base(db: Session, kind: str, data: schemas.BaseRecordInput) -> None:
    db.add(models.BaseRecord(kind=kind, name=data.name, contact=data.contact,
                             phone=data.phone, remark=data.remark))
    # CLEANUP-20261020：reps 类型已下线，仅保留 suppliers / customers
    label = "供应商" if kind == "suppliers" else "客户"
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
# 产品交付物（按模板惰性初始化）
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
        # WHY：此前遗漏 asset_id，导致前端产品详情「操作记录」按 l.assetId === assetId 过滤时
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
# 购物车（ADR-009：按登录用户隔离——router 层传 get_current_user 的 user.id）
# ============================================================
# DEFAULT_USER 常量保留（seed/兼容），router 不再使用
DEFAULT_USER = "admin"


def _cart_amount(a: models.Asset | None, amount: float | None) -> float | None:
    """购物车行级合同金额（ADR-008）：amount 模式产品校验整数元后返回；
    未传返回 None（结算时再强制必填）；unit 模式忽略（不采信、不落库）。"""
    if amount is None:
        return None
    if a is not None and _is_amount_mode(a):
        return float(_validate_amount_yuan(amount))
    return None


def _cart_list(db: Session, user_id: str) -> list[models.CartItem]:
    return db.execute(
        select(models.CartItem)
        .where(models.CartItem.userId == user_id)
        .order_by(models.CartItem.id.asc())
    ).scalars().all()


def _cart_qty_of(db: Session, user_id: str, asset_id: int, customer: str = "",
                 item_id: int | None = None) -> int:
    """唯一键语义：(userId, assetId, customer) 相同才合并（ADR-007）；
    ADR-011 升级为 (userId, assetId, itemId, customer)——item_id=None 匹配无明细行（itemId IS NULL），
    非空匹配对应明细行（无 itemId 行口径不变）。"""
    q = select(models.CartItem).where(
        models.CartItem.userId == user_id,
        models.CartItem.assetId == asset_id,
        models.CartItem.customer == (customer or ""),
    )
    if item_id is None:
        q = q.where(models.CartItem.itemId.is_(None))
    else:
        q = q.where(models.CartItem.itemId == item_id)
    c = db.execute(q).scalar_one_or_none()
    return c.qty if c else 0


def _avail(a: models.Asset) -> int:
    """可用数量（可重复售卖产品由调用处先判 repeatSale，不参与上限校验）"""
    return max(0, a.quantity - a.lockedQty - a.shippedQty)


def _check_stock(db: Session, asset_id: int, target_qty: int) -> None:
    """校验目标数量不超过可用数量；可重复售卖产品不校验。超量抛 400。"""
    a = get_asset(db, asset_id)
    if a and not a.repeatSale and target_qty > _avail(a):
        raise HTTPException(
            400,
            f"「{a.name}」可用数量仅 {_avail(a)}{a.unit}，无法加入/设置为 {target_qty}{a.unit}，请调整数量",
        )


# ADR-007：删除购物车同主体限制（_cart_subject/_check_entity 已移除）——
# 购物车支持跨主体加购，结算时按行级 customer 分组，每客户一个合同（合同内再校验同主体）。


def _resolve_cart_rs_item(db: Session, asset: models.Asset, item_id: int | None) -> models.RsItem | None:
    """ADR-011：购物车明细行解析——itemId 非空时校验明细存在且归属该产品，返回 RsItem。"""
    if item_id is None:
        return None
    rs = db.get(models.RsItem, item_id)
    if rs is None or rs.assetId != asset.id:
        raise HTTPException(400, "遥感数据明细不存在或不属于该产品")
    return rs


def _resolve_cart_rs_item_soft(db: Session, asset: models.Asset, item_id: int | None) -> models.RsItem | None:
    """批量加购用：同 _resolve_cart_rs_item 但校验失败返回 None（批量语义=跳过该行，不整单 400）。"""
    if item_id is None:
        return None
    rs = db.get(models.RsItem, item_id)
    return rs if (rs is not None and rs.assetId == asset.id) else None


def _cart_add_inner(db: Session, data: schemas.CartItemInput, user_id: str = DEFAULT_USER) -> models.CartItem:
    """加购核心（**不提交**，供 add_to_cart / add_to_cart_batch 复用，批量可收敛为单一事务）"""
    a = get_asset(db, data.assetId)
    if not a:
        raise HTTPException(404, "产品不存在")
    # FIX-20261020-#13c：遥感父产品（容器）不可直接加购——容器明细行（itemId 非空）放行
    if a.type == "遥感数据" and not data.itemId:
        raise HTTPException(400, "遥感数据容器不可直接购买，请购买其数据明细")
    customer = (data.customer or "").strip()
    # ADR-011：明细行——校验归属 + qty 恒 1（≠1 → 400）
    rs = _resolve_cart_rs_item(db, a, data.itemId)
    if rs is not None and data.qty != 1:
        raise HTTPException(400, "遥感数据明细行数量固定为 1")
    qty = 1 if rs is not None else max(1, int(data.qty or 1))
    # 判重口径按 (userId, assetId, itemId, customer)（无 itemId 行 = itemId IS NULL，口径不变）
    cur = _cart_qty_of(db, user_id, data.assetId, customer, data.itemId)
    # 数量上限按该产品**全部行**（跨 customer）合计 + 本次**净增**校验；
    # 明细行按**明细** repeatSale 判定（true 不占数量；false 按父产品可售校验）。
    # 净增口径修复：total_in_cart 已含目标行存量 cur——
    #  - 普通行合并后为 cur+qty，净增 = qty（原 total+qty 口径正确）；
    #  - 明细行重复加购幂等合并（恒 1，不累加），净增 = 0（原口径 double-count，
    #    可售恰为 1 时重复加购同一明细会被误判「可用数量不足」）。
    delta = 0 if (rs is not None and cur > 0) else qty
    if rs is None or not rs.repeatSale:
        total_in_cart = sum(c.qty for c in _cart_list(db, user_id) if c.assetId == data.assetId)
        if not a.repeatSale and total_in_cart + delta > _avail(a):
            raise HTTPException(
                400,
                f"「{a.name}」可用数量仅 {_avail(a)}{a.unit}，无法加入/设置为 {total_in_cart + delta}{a.unit}，请调整数量",
            )
    # 行级金额（ADR-008 / ADR-018 §3，PRICING-20261020）：
    # - amount 模式：整数元权威（_cart_amount）；
    # - unit / 遥感明细行：折扣金额传入即采信（过参考区间校验，超限 400），不传 = 原价成交
    if _is_amount_mode(a):
        amount = _cart_amount(a, data.amount)
    else:
        # ADR-021（RSITEM-RANGE-20261020）：遥感明细行传 rs，区间取明细自身 priceMin/priceMax
        amt = _check_discount_range(a, qty, data.amount, unit=a.unit, rs=rs)
        amount = float(amt) if amt is not None else None
    # ADR-020（PRICING-20261020）：服务期限校验（YYYY-MM-DD + start ≤ end，否则 400）
    service_start, service_end = _validate_service_period(data.serviceStart, data.serviceEnd)
    # DISCOUNT-20261021/ADR-023：折扣率校验（0 < rate ≤ 1 否则 400；null=清空/无折扣）。
    # 后端只存不算：不做金额回填（前端回填 amount 后一起提交，金额权威原则）
    discount_rate = _validate_discount_rate(data.discountRate)
    q = select(models.CartItem).where(
        models.CartItem.userId == user_id,
        models.CartItem.assetId == data.assetId,
        models.CartItem.customer == customer,
    )
    if data.itemId is None:
        q = q.where(models.CartItem.itemId.is_(None))
    else:
        q = q.where(models.CartItem.itemId == data.itemId)
    existing = db.execute(q).scalar_one_or_none()
    if existing:
        # 明细行 qty 恒 1：重复加购幂等合并（不累加）；普通行累加
        existing.qty = 1 if rs is not None else cur + qty
        if amount is not None:
            existing.amount = amount
        # ADR-020：服务期限（本次传了才覆盖，未传保持原值）
        if service_start is not None or service_end is not None:
            existing.serviceStart, existing.serviceEnd = service_start, service_end
        # DISCOUNT-20261021/ADR-023：折扣率（null=清空，与契约「null 允许=清空」同口径）
        existing.discountRate = discount_rate
        existing.updatedAt = now_str()
    else:
        existing = models.CartItem(
            userId=user_id, assetId=data.assetId, customer=customer, qty=qty,
            amount=amount, itemId=data.itemId,
            serviceStart=service_start, serviceEnd=service_end,  # ADR-020：服务期限
            discountRate=discount_rate,  # DISCOUNT-20261021/ADR-023：折扣率（null=无折扣）
            createdAt=now_str(), updatedAt=now_str(),
        )
        db.add(existing)
    # 批量路径必需：flush 让同批后续行的 SELECT（判重/合计）能看到本行——
    # session autoflush=False，不 flush 则同键第二行会判为「不存在」而重复插入；
    # flush 仍在同一事务内，任一步 400 时整体回滚，原子性不变
    db.flush()
    return existing


def add_to_cart(db: Session, data: schemas.CartItemInput, user_id: str = DEFAULT_USER) -> models.CartItem:
    existing = _cart_add_inner(db, data, user_id)
    db.commit()
    db.refresh(existing)
    return existing


def patch_cart_item(db: Session, cart_id: int, customer: str, user_id: str = DEFAULT_USER,
                    amount: float | None = None,
                    service_start: str | None = None, service_end: str | None = None,
                    discount_rate: float | None = None) -> models.CartItem:
    """修改购物车行级客户（ADR-007）；可选携带合同金额（ADR-008）、服务期限（ADR-020）
    与折扣率（DISCOUNT-20261021/ADR-023）。

    金额语义（ADR-018 §3，PRICING-20261020）：
    - unit / 遥感明细行：amount 传入即采信（过参考区间校验，超限 400），不传保持 NULL（原价成交）；
    - amount 模式行：整数元权威（不传保持原值，结算时必填兜底不变）。
    折扣率语义（ADR-023）：0 < rate ≤ 1 否则 400「折扣率须为 0 到 1 之间的正数」；
    null=清空（无折扣，与契约「null 允许=清空」同口径）。后端只存不算，amount 校验完全不变。
    目标 (userId, assetId, customer) 已存在其它行时 400（避免静默合并产生歧义，前端可先删除原行）。"""
    c = db.get(models.CartItem, cart_id)
    if not c or c.userId != user_id:
        raise HTTPException(404, "购物车项不存在")
    a = get_asset(db, c.assetId)
    is_discount_row = c.itemId is not None or (a is not None and not _is_amount_mode(a))
    # ADR-021（RSITEM-RANGE-20261020）：遥感明细行区间取该 rs_item 自身（不再取父产品容器区间）
    rs = db.get(models.RsItem, c.itemId) if c.itemId is not None else None
    # 行级金额（ADR-008 / ADR-018 §3）
    if amount is not None:
        if is_discount_row:
            amt = _check_discount_range(a, c.qty, amount, unit=a.unit if a else "", rs=rs)
            c.amount = float(amt)
        else:
            amt = _cart_amount(a, amount)
            if amt is not None:
                c.amount = amt
    elif is_discount_row:
        c.amount = None  # unit/遥感行不传 amount = 原价成交（保持 NULL）
    # ADR-020（PRICING-20261020）：服务期限（格式/顺序校验，start ≤ end 否则 400）
    if service_start is not None or service_end is not None:
        new_start, new_end = _validate_service_period(
            service_start if service_start is not None else c.serviceStart,
            service_end if service_end is not None else c.serviceEnd)
        c.serviceStart, c.serviceEnd = new_start, new_end
    # DISCOUNT-20261021/ADR-023：折扣率（0 < rate ≤ 1 否则 400；null=清空/无折扣）
    c.discountRate = _validate_discount_rate(discount_rate)
    if amount is not None or service_start is not None or service_end is not None \
            or discount_rate is not None:
        c.updatedAt = now_str()
    new_customer = (customer or "").strip()
    if new_customer != (c.customer or ""):
        dup_q = select(models.CartItem).where(
            models.CartItem.userId == user_id,
            models.CartItem.assetId == c.assetId,
            models.CartItem.customer == new_customer,
            models.CartItem.id != c.id,
        )
        # ADR-011：判重键含 itemId（明细行与无明细行互不冲突）
        if c.itemId is None:
            dup_q = dup_q.where(models.CartItem.itemId.is_(None))
        else:
            dup_q = dup_q.where(models.CartItem.itemId == c.itemId)
        dup = db.execute(dup_q).scalar_one_or_none()
        if dup:
            raise HTTPException(400, f"购物车中该产品在客户「{new_customer}」下已有行，无法修改客户（请先删除原行）")
        c.customer = new_customer
        c.updatedAt = now_str()
    db.commit()
    # CART-PERF-20261021：commit 后 refresh 并返回更新后的行对象（供路由序列化为 CartItemOut，前端本地打补丁）
    db.refresh(c)
    return c


def add_to_cart_batch(db: Session, data: schemas.CartBatchInput, user_id: str = DEFAULT_USER) -> dict:
    """批量加购：逐条校验可用数量（按产品全部行合计口径），超量的跳过并记录，其余正常加入。
    ADR-007：行级带 customer，跨主体加购不再拦截。"""
    skipped: list[dict] = []
    added = 0
    for it in data.items:
        a = get_asset(db, it.assetId)
        if not a:
            skipped.append({"assetId": it.assetId, "name": f"产品 #{it.assetId}", "available": 0, "reason": "产品不存在"})
            continue
        # ADR-011：明细行——归属校验失败跳过（批量语义不整单 400）；qty 恒 1
        rs = _resolve_cart_rs_item_soft(db, a, it.itemId)
        if it.itemId is not None and rs is None:
            skipped.append({"assetId": it.assetId, "name": a.name, "available": 0,
                            "reason": "遥感数据明细不存在或不属于该产品"})
            continue
        qty = 1 if rs is not None else max(1, int(it.qty or 1))
        customer = (it.customer or "").strip()
        cur = _cart_qty_of(db, user_id, it.assetId, customer, it.itemId)
        total_in_cart = sum(c.qty for c in _cart_list(db, user_id) if c.assetId == it.assetId)
        # 明细行按明细 repeatSale 判定（true 不占数量）；普通行按产品 repeatSale。
        # 净增口径与 _cart_add_inner 一致：明细行已在车（幂等合并恒 1）时净增 = 0
        delta = 0 if (rs is not None and cur > 0) else qty
        repeat = rs.repeatSale if rs is not None else a.repeatSale
        if not repeat and total_in_cart + delta > _avail(a):
            skipped.append({
                "assetId": it.assetId, "name": a.name, "available": _avail(a),
                "reason": f"可售仅 {_avail(a)}{a.unit}（购物车已有 {total_in_cart}{a.unit}）",
            })
            continue
        # 原子性修复：走不提交的 _cart_add_inner，整批末尾统一 commit——
        # 任一行硬 400（如 amount 模式金额校验）整体回滚，不再「加一半」
        _cart_add_inner(db, schemas.CartItemInput(assetId=it.assetId, qty=qty, customer=customer,
                                                  amount=it.amount, itemId=it.itemId,
                                                  discountRate=it.discountRate), user_id)  # DISCOUNT-20261021/ADR-023
        added += 1
    db.commit()
    return {
        "addedCount": added,
        "skipped": skipped,
        "cart": [schemas.CartItemOut.model_validate(c).model_dump() for c in _cart_list(db, user_id)],
    }


def set_cart_qty(db: Session, cart_id: int, qty: int, user_id: str = DEFAULT_USER,
                 amount: float | None = None,
                 service_start: str | None = None, service_end: str | None = None,
                 discount_rate: float | None = None) -> models.CartItem:
    """PUT /cart/{id}：改数量；可选携带合同金额（ADR-008）、服务期限（ADR-020）
    与折扣率（DISCOUNT-20261021/ADR-023）。

    金额语义（ADR-018 §3，PRICING-20261020）：
    - unit / 遥感明细行：amount 传入即采信（过参考区间校验，超限 400），不传保持 NULL（原价成交）；
    - amount 模式行：整数元权威（不传保持原值）。
    折扣率语义（ADR-023）：0 < rate ≤ 1 否则 400「折扣率须为 0 到 1 之间的正数」；
    null=清空（无折扣）。后端只存不算，amount 校验完全不变。
    删除行仅走 DELETE /cart/{id}——PUT 语义不再兼作删除（qty<=0 直接 400，
    修复：此前 PUT 漏传 qty 会默认 0 → 静默删行，调用方极易误触发）。"""
    c = db.get(models.CartItem, cart_id)
    if not c or c.userId != user_id:
        raise HTTPException(404, "购物车项不存在")
    if qty <= 0:
        raise HTTPException(400, "数量必须大于 0（移除行请使用删除操作）")
    # ADR-011：明细行 qty 恒 1（前端本就不允许改；删除走 DELETE /cart/{id}）
    if c.itemId is not None and qty != 1:
        raise HTTPException(400, "遥感数据明细行数量固定为 1")
    # FIX-6b：数量上限从「本行 qty ≤ 可售」升级为「该产品在购物车全部行合计（本次修改后）≤ 可售」
    # （与 add_to_cart / add_to_cart_batch 的行级合计口径对齐；repeatSale 产品跳过）
    a = get_asset(db, c.assetId)
    if a and not a.repeatSale:
        total_after = sum(x.qty for x in _cart_list(db, user_id) if x.assetId == c.assetId) \
            - c.qty + int(qty)
        if total_after > _avail(a):
            raise HTTPException(400, f"购物车中 {a.name} 合计 {total_after} 超出可售 {_avail(a)}")
    c.qty = int(qty)
    # 行级金额（ADR-008 / ADR-018 §3，PRICING-20261020）：改数量后按新 qty 重做区间校验
    is_discount_row = c.itemId is not None or (a is not None and not _is_amount_mode(a))
    # ADR-021（RSITEM-RANGE-20261020）：遥感明细行区间取该 rs_item 自身（不再取父产品容器区间）
    rs = db.get(models.RsItem, c.itemId) if c.itemId is not None else None
    if amount is not None:
        if is_discount_row:
            amt = _check_discount_range(a, c.qty, amount, unit=a.unit if a else "", rs=rs)
            c.amount = float(amt)
        else:
            amt = _cart_amount(a, amount)
            if amt is not None:
                c.amount = amt
    elif is_discount_row:
        c.amount = None  # unit/遥感行不传 amount = 原价成交（保持 NULL）
    # ADR-020（PRICING-20261020）：服务期限（格式/顺序校验，start ≤ end 否则 400）
    if service_start is not None or service_end is not None:
        new_start, new_end = _validate_service_period(
            service_start if service_start is not None else c.serviceStart,
            service_end if service_end is not None else c.serviceEnd)
        c.serviceStart, c.serviceEnd = new_start, new_end
    # DISCOUNT-20261021/ADR-023：折扣率（0 < rate ≤ 1 否则 400；null=清空/无折扣）
    c.discountRate = _validate_discount_rate(discount_rate)
    c.updatedAt = now_str()
    db.commit()
    # CART-PERF-20261021：commit 后 refresh 并返回更新后的行对象（供路由序列化为 CartItemOut，前端本地打补丁）
    db.refresh(c)
    return c


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
    db: Session, data, asset_qty: list[tuple[models.Asset, int, float | None, int | None]],
    operator: str = ""
) -> models.Project:
    """通用下单（直接下单，ADR-013 按产品拆记录）：校验可用数量，
    生成进行中销售项目（**每个产品一条销售记录**，遥感明细行归父产品）并锁定数量（交付由人工触发，不自动交付）。
    主体（subject）由产品自动带出，无需前端传入。
    ADR-013：不再强制同一主体（一资产一记录，各记录独立主体）。
    asset_qty 四元组 (产品, 数量, 前端传入 amount, itemId)：
    - amount 模式产品以第三元为权威输入（ADR-008）；
    - 明细行（第四元非空，ADR-011）：qty 恒 1（≠1 → 400），金额权威 = 明细 price × 1（忽略前端传值）。"""
    if not asset_qty:
        raise HTTPException(400, "没有可下单的产品")
    # ADR-013：按产品分组（保持行序，明细行归父产品）→ 每产品一条销售记录
    groups: dict[int, list[tuple[models.Asset, int, float | None, int | None]]] = {}
    for t in asset_qty:
        groups.setdefault(t[0].id, []).append(t)
    contracts_in: list[schemas.ContractInput] = []
    for _aid, rows in groups.items():
        items: list[schemas.ProjectItemInput] = []
        total = Decimal("0")
        for a, qty, in_amount, item_id in rows:
            # FIX-20261020-#13c：遥感父产品（容器）不可直接下单——容器明细行（item_id 非空）放行
            if a.type == "遥感数据" and item_id is None:
                raise HTTPException(400, "遥感数据容器不可直接购买，请购买其数据明细")
            rs = db.get(models.RsItem, item_id) if item_id else None
            if rs is not None and rs.assetId != a.id:
                raise HTTPException(400, "遥感数据明细不存在或不属于该产品")
            if rs is not None and qty != 1:
                raise HTTPException(400, "遥感数据明细行数量固定为 1")
            # 数量校验：明细行按明细 repeatSale（true 不占数量）；普通行按产品 repeatSale
            repeat = rs.repeatSale if rs is not None else a.repeatSale
            if not repeat and qty > _avail(a):
                raise HTTPException(400, f"「{a.name}」可用数量仅 {_avail(a)}{a.unit}，无法下单 {qty}{a.unit}")
            if rs is not None:
                if in_amount is not None:
                    # ADR-018 §5（PRICING-20261020）：遥感行折扣金额可输（过区间校验，
                    # 防直调绕过购物车校验）；不输 = 明细 price 原价
                    # ADR-021（RSITEM-RANGE-20261020）：区间取该 rs_item 自身（不再取父产品容器区间）
                    amt = _check_discount_range(a, 1, in_amount, unit=a.unit, rs=rs)
                    price = _derived_price(amt, 1)
                    amount = amt.quantize(CENT)
                else:
                    # ADR-011：明细行金额权威 = 明细 price × 1（Decimal 重算，整数元天然成立）
                    price = float(_dec(rs.price))
                    amount = _dec(rs.price).quantize(CENT)
            elif _is_amount_mode(a):
                # ADR-008：amount 权威（整数元校验），price 派生展示值
                amount = _validate_amount_yuan(in_amount)
                price = _derived_price(amount, qty)
            elif in_amount is not None:
                # ADR-018 §3（PRICING-20261020）：unit 行折扣金额采信（过区间校验）
                amt = _check_discount_range(a, qty, in_amount, unit=a.unit)
                price = _derived_price(amt, qty)
                amount = amt.quantize(CENT)
            else:
                # 契约 5：与项目创建路径完全一致，Decimal 精确到分（元口径，ADR-006）
                price = a.salePrice or 0
                amount = (_dec(price) * qty).quantize(CENT)
            total += amount
            items.append(
                schemas.ProjectItemInput(assetId=a.id, qty=qty, price=price, amount=float(amount),
                                         deliveryReq=data.deliveryReq, itemId=item_id)
            )
        contracts_in.append(schemas.ContractInput(
            customer=data.customer, items=items, contractAmount=float(total.quantize(CENT)), remark="", 
        ))
    project_input = schemas.ProjectInput(
        name=data.projectName,
        customer=data.customer,
        industry="",
        # FIX-20261020-#10：rep 归一为 username（_create_project_core 内同样兜底，幂等）
        rep=_normalize_rep(db, data.rep),
        businessOwner=data.businessOwner,  # 商务负责人（可选，默认 ""）
        subject="",  # ADR-007：主体由合同派生，不再采信
        expectedAmount=0,  # ADR-007/013：派生字段，_recompute_project 会重算落库
        quoteAmount=0,
        contractAmount=data.contractAmount,
        paidAmount=0,
        expectedSignDate=data.expectedSignDate or today(),
        lastFollowDate=today(),
        remark=data.remark,
        # ADR-013：按产品拆分为多条销售记录（customer 取项目 customer 字段）
        contracts=contracts_in,
    )
    # H8：建项目走 core（不提交），由调用方在一个事务内提交
    # WHY：销售与交付是两个独立动作——下单只锁定数量（active），交付（扣数量+交付）
    # 由人工把合同/项目置为"已完成"触发；分离便于纠错编辑与审计留痕各自独立。
    project = _create_project_core(db, project_input, operator=operator)
    return project


def checkout(db: Session, data: schemas.CheckoutInput, user_id: str = DEFAULT_USER,
             operator: str = "", viewer: bool = False) -> models.Project:
    """购物车结算（ADR-016）：按 (产品, 客户) 分组 → 每组合并数量/金额后一条销售记录
    （明细行按父产品归组；同产品多客户=多条记录，不再静默合并）
    → 建项目（pending + 锁定）→ 清空购物车。全部单事务，任一步失败整体回滚（H8）。
    不自动交付。customer 取分组键客户（同客户多产品=同项目多条记录）。
    ADR-012 修订（2026-10-19）：**所有角色**结算 → 项目/记录建 pending（待审核，锁定照常），
    商务接手后经审核（改价确认/驳回）生效。
    ADR-022（REQUIRED-20261024）：逐行必填校验——客户非空 / 销售金额 > 0 整数元（所有行类型）/
    普通产品行服务期限起止均必填且 start ≤ end；缺项 400 一次报全（文案含行标识：产品名/遥感明细名）。
    取代 ADR-018 §3「留空=挂牌价成交」兜底（viewer 免填金额口径同步作废）；
    遥感明细行（itemId 非空）服务期限仍豁免（ADR-020：期数即服务时间）。
    ADR-013：不再校验同主体（记录粒度=单资产，天然单主体；同客户多主体=多条记录并列）。"""
    cart = _cart_list(db, user_id)
    if not cart:
        raise HTTPException(400, "购物车为空，请先添加产品")
    # ADR-022（REQUIRED-20261024）：逐行必填校验——收集全部缺项一次报全（400），
    # 文案含行标识（产品名 / 遥感明细名），便于前端逐行标红定位：
    # - 客户非空（现状保留）；
    # - 销售金额 > 0 整数元（**所有行类型**：unit/amount/遥感明细行）——
    #   取代 ADR-018 §3「留空=原价成交」兜底（amount 为空回退 salePrice×qty 的分支已删除）；
    # - 普通产品行：serviceStart 与 serviceEnd 均必填，且 start ≤ end（格式校验现状保留）；
    # - 遥感明细行（itemId 非空）服务期限豁免（ADR-020）。
    missing: list[str] = []
    for c in cart:
        a = get_asset(db, c.assetId)
        if not a:
            raise HTTPException(400, f"购物车中的产品（#{c.assetId}）已删除，请先移除后再下单")
        label = a.name
        if c.itemId is not None:
            rs = db.get(models.RsItem, c.itemId)
            if rs is None or rs.assetId != c.assetId:
                raise HTTPException(400, "购物车中的遥感数据明细已删除或不属于该产品，请先移除后再下单")
            label = f"{a.name}·{_rs_item_desc(rs)}"
        if not (c.customer or "").strip():
            missing.append(f"{label}：客户")
        # 销售金额：所有行类型必填（ADR-022），> 0 整数元
        amt = _dec(c.amount) if c.amount is not None else None
        if amt is None or amt <= 0 or amt != amt.to_integral_value():
            missing.append(f"{label}：销售金额（整数元，大于 0）")
        if c.itemId is None:
            # 普通产品行：服务期限起止均必填（遥感明细行豁免）；
            # 均已填时按 ADR-020 口径校验格式与 start ≤ end
            if not (c.serviceStart or "").strip() or not (c.serviceEnd or "").strip():
                missing.append(f"{label}：服务期限（开始/结束日期均必填）")
            else:
                _validate_service_period(c.serviceStart, c.serviceEnd)
    if missing:
        raise HTTPException(400, "购物车存在必填缺项，请补齐后再结算：" + "；".join(missing))
    # 按 (产品, 客户) 分组（保持购物车行序）；八元组
    # (产品, 数量, 权威/折扣 amount, itemId, 行级客户, serviceStart, serviceEnd, discountRate)
    # 明细行 qty 恒 1（ADR-011）；ADR-022 后 amount 恒非空且为合法整数元（上方必填校验保证）
    # ADR-018 §3（PRICING-20261020）：unit/遥感行折扣金额 checkout 时再过一次区间校验
    #（行更新时已校验，此处防绕过行更新接口直接改库/旧客户端）
    # DISCOUNT-20261021/ADR-023：discountRate 原样透传落 project_items 快照（只写不改）
    # ADR-016（FIX-20261020-#3）：分组键由 assetId 单键升级为 (assetId, customer)——
    # 同产品多客户行不再被静默合并为一条记录（客户归属/金额串账），与前端预览口径一致
    groups: dict[tuple[int, str], list[tuple[models.Asset, int, Decimal, int | None, str,
                                            str | None, str | None, float | None]]] = {}
    for c in cart:
        a = get_asset(db, c.assetId)
        customer = (c.customer or "").strip()
        if c.itemId is not None:
            rs = db.get(models.RsItem, c.itemId)
            # ADR-018 §5：遥感明细行折扣金额采信（过区间校验）；
            # ADR-021（RSITEM-RANGE-20261020）：区间取该 rs_item 自身（不再取父产品容器区间）
            amt = _check_discount_range(a, 1, c.amount, unit=a.unit, rs=rs)
            groups.setdefault((c.assetId, customer), []).append(
                (a, 1, amt, c.itemId, customer, c.serviceStart, c.serviceEnd, c.discountRate))
            continue
        if _is_amount_mode(a):
            amt = _validate_amount_yuan(c.amount)  # 整数元校验（必填校验已过，幂等兜底）
        else:
            # ADR-018 §3：unit 行折扣金额采信（过区间校验）
            amt = _check_discount_range(a, c.qty, c.amount, unit=a.unit)
        groups.setdefault((c.assetId, customer), []).append(
            (a, c.qty, amt, None, customer, c.serviceStart, c.serviceEnd, c.discountRate))
    # 每组（产品×客户）→ 一条销售记录（ADR-016：一资产一客户一记录，customer 取分组键）
    # 计价（明细行=明细 price 权威 / amount 模式=权威金额 / unit 模式 price×qty）
    contracts_in: list[schemas.ContractInput] = []
    for (_asset_id, _customer), rows in groups.items():
        items: list[schemas.ProjectItemInput] = []
        total = Decimal("0")
        for a, qty, amt, item_id, _cust, s_start, s_end, d_rate in rows:
            # ADR-022（REQUIRED-20261024）：amt 经上方必填校验恒非空（> 0 整数元）——
            # 「留空=原价成交」兜底已删除（unit 行 salePrice×qty / 遥感行明细 price 分支作废）
            price = _derived_price(amt, qty)  # 派生展示值（遥感明细行 qty 恒 1）
            amount = amt.quantize(CENT)  # 元口径，Decimal 精确到分
            total += amount
            items.append(schemas.ProjectItemInput(
                assetId=a.id, qty=qty, price=price, amount=float(amount),
                deliveryReq=data.deliveryReq, itemId=item_id,
                serviceStart=s_start, serviceEnd=s_end,  # ADR-020：服务期限透传
                discountRate=d_rate,  # DISCOUNT-20261021/ADR-023：折扣率快照透传
            ))
        contracts_in.append(schemas.ContractInput(
            customer=_customer, items=items, contractAmount=float(total.quantize(CENT)), remark="",
        ))
    project_input = schemas.ProjectInput(
        name=data.projectName or f"销售项目-{today()}",
        customer="",  # 多客户派生为空（前端显示「N 位客户」）；单客户由 _recompute_project 回填
        industry="",
        rep=data.rep,
        businessOwner=data.businessOwner,  # 商务负责人（可选，默认 ""）
        subject="",
        expectedAmount=0,  # 派生 = Σ合同 contractAmount
        quoteAmount=0,
        contractAmount=0,
        paidAmount=0,
        expectedSignDate=data.expectedSignDate or today(),
        lastFollowDate=today(),
        remark=data.remark,
        contracts=contracts_in,
    )
    # H8：建项目（含合同/明细/锁定）→ 清空购物车 收敛为同一事务
    # ADR-012 修订（2026-10-19）：所有角色结算统一进「待审核」（pending），商务接手审核（改价/驳回）后生效
    project = _create_project_core(db, project_input, operator=operator,
                                   initial_status="pending")
    _clear_cart(db, user_id)
    db.commit()
    db.refresh(project)
    return project


def create_sale_order(db: Session, data: schemas.SaleOrderInput,
                      operator: str = "") -> models.Project:
    """产品直接下单：items 按产品分组拆销售记录（ADR-013，不再校验同主体），
    customer 必填 → 建项目 + 销售记录（pending 待审核 + 锁定数量，不自动交付；
    ADR-012 修订：所有角色直接下单均进待审核，商务接手审核后生效）"""
    asset_qty: list[tuple[models.Asset, int, float | None, int | None]] = []
    for it in data.items:
        a = get_asset(db, it.assetId)
        if not a:
            raise HTTPException(404, f"产品 #{it.assetId} 不存在")
        # ADR-011：明细行 qty 原样透传（_order_core 校验恒 1，≠1 → 400）
        qty = it.qty if it.itemId is not None else max(1, int(it.qty or 1))
        asset_qty.append((a, qty, it.amount, it.itemId))
    # H8：建项目 + 锁定同一事务
    project = _order_core(db, data, asset_qty, operator=operator)
    db.commit()
    db.refresh(project)
    return project


def add_file_meta(db: Session, stored_name: str, name: str, size: int,
                  uploaded_by: str = "") -> None:
    """写/更新上传文件原名映射（散列落盘名 → 原始文件名）。

    上传不是产品操作，故只写 file_meta、不写 OpLog。
    """
    m = db.get(models.FileMeta, stored_name)
    if m is None:
        m = models.FileMeta(storedName=stored_name)
        db.add(m)
    m.name = name or stored_name
    m.size = size
    m.uploadedBy = uploaded_by or ""
    m.createdAt = now_str()
    db.commit()


def bootstrap(db: Session, user_id: str, user: "models.User | None" = None) -> dict:
    """全量快照。cart 仅返回当前请求用户（ADR-009 按登录用户隔离）的行；
    生态人员（viewer）projects/contracts 按「自己下单」口径过滤（2026-10-16）。"""
    assets = db.execute(select(models.Asset).order_by(models.Asset.id.desc())).scalars().all()
    # 确保每个产品的交付物实例已初始化（惰性）。
    # 写副作用收敛：仅当确有产品尚未初始化时才进入写路径并提交；
    # 稳态（全部已初始化）下 bootstrap 保持纯读，读接口不再抢 SQLite 写锁。
    pending_assets = [a for a in assets if not a.deliverables]
    if pending_assets:
        for a in pending_assets:
            _init_asset_deliverables(db, a)
        db.commit()

    projects = db.execute(select(models.Project).order_by(models.Project.id.desc())).scalars().all()
    # ADR-007：合同全量（含 items，明细挂 contractId）
    contracts = db.execute(select(models.Contract).order_by(models.Contract.id.asc())).scalars().all()
    # 生态人员（viewer）销售项目可见性隔离：仅自己下单的项目（creator==自己 / 存量回退 rep==自己），
    # 合同跟随项目可见性一并过滤；admin/editor 全量。前端项目列表/详情/产品销售关联均消费此镜像。
    if user is not None and user.role == "viewer":
        projects = [p for p in projects if user_sees_project(user, p)]
        visible_project_ids = {p.id for p in projects}
        contracts = [c for c in contracts if c.projectId in visible_project_ids]
    outbounds = db.execute(select(models.Outbound).order_by(models.Outbound.id.desc())).scalars().all()
    flows = db.execute(select(models.AssetFlow).order_by(models.AssetFlow.id.asc())).scalars().all()
    logs = db.execute(select(models.OpLog).order_by(models.OpLog.id.asc())).scalars().all()
    # FIX-20261020-#6：viewer 的 outbounds/flows/logs 按引用关系过滤——
    # 此前全量返回会泄露其他客户的交付记录（客户名/数量/金额）、关联合同号的流水与操作日志。
    # 过滤口径（宁可保守过滤，不漏放跨客户信息）：
    # - outbounds：projectId ∈ 可见项目 或 contractId ∈ 可见合同；
    # - flows：contractId ∈ 可见合同，或 ref 指向可见项目/合同/交付编号；
    #   产品级流水（ref=产品编号，如登记 purchase_in）产品对 viewer 全量可见，放行；
    # - logs：project 日志按 detail 中 SP- 编号 / contractId / 项目名匹配可见范围；
    #   outbound 日志按 CK- 编号匹配；asset/setting 日志引用产品/基础资料（全量可见），放行。
    if user is not None and user.role == "viewer":
        visible_project_codes = {p.code for p in projects}
        visible_project_names = {p.name for p in projects}
        visible_contract_ids = {c.id for c in contracts}
        visible_contract_codes = {c.code for c in contracts}
        outbounds = [
            o for o in outbounds
            if (o.projectId is not None and o.projectId in visible_project_ids)
            or (o.contractId is not None and o.contractId in visible_contract_ids)
        ]
        visible_outbound_codes = {o.code for o in outbounds}

        def _keep_flow(f: models.AssetFlow) -> bool:
            if f.contractId is not None:
                return f.contractId in visible_contract_ids
            ref = f.ref or ""
            if ref.startswith("SP-"):
                return ref in visible_project_codes
            if ref.startswith("HT-"):
                return ref in visible_contract_codes
            if ref.startswith("CK-"):
                return ref in visible_outbound_codes
            return True  # 产品级流水（登记等，ref=产品编号/“-”）：产品全量可见

        def _keep_log(lg: models.OpLog) -> bool:
            if lg.target == "project":
                m = _SP_CODE_RE.search(lg.detail or "")
                if m:
                    return m.group(0) in visible_project_codes
                if lg.contractId is not None:
                    return lg.contractId in visible_contract_ids
                # detail 无编号（如「更新销售项目」）：按项目名匹配，匹配不到则保守过滤
                return lg.targetName in visible_project_names
            if lg.target == "outbound":
                m = _CK_CODE_RE.search(lg.detail or "")
                return bool(m and m.group(0) in visible_outbound_codes)
            # asset / setting：引用产品或基础资料（对 viewer 全量可见），无跨客户信息
            return True

        flows = [f for f in flows if _keep_flow(f)]
        logs = [lg for lg in logs if _keep_log(lg)]

    def _bases(kind: str):
        return db.execute(select(models.BaseRecord).where(models.BaseRecord.kind == kind)
                          .order_by(models.BaseRecord.id.asc())).scalars().all()

    # CLEANUP-20261020：移除 reps（生态人员）快照字段
    suppliers, customers = _bases("suppliers"), _bases("customers")

    templates = db.execute(select(models.DeliverableTemplate)).scalars().all()
    tpl_map: dict[str, list] = {}
    for t in templates:
        tpl_map.setdefault(t.type, []).append(schemas.DeliverableTemplateOut.model_validate(t).model_dump())

    deliv_map: dict[int, list] = {}
    for a in assets:
        if a.deliverables:
            deliv_map[str(a.id)] = [schemas.AssetDeliverableOut.model_validate(d).model_dump() for d in a.deliverables]

    category_units = db.execute(select(models.CategoryUnit).order_by(models.CategoryUnit.id.asc())).scalars().all()
    # ADR-009：购物车按登录用户隔离——仅返回当前请求用户的行（不再用 DEFAULT_USER）
    cart = _cart_list(db, user_id)
    # 上传文件原名映射全量返回（当前量级小，无分页问题）
    files = db.execute(select(models.FileMeta).order_by(models.FileMeta.storedName.asc())).scalars().all()
    # ADR-011：遥感数据可售明细全量（读随 bootstrap 放行，前端 RsItemPicker/明细页签消费）
    rs_items = db.execute(select(models.RsItem).order_by(models.RsItem.id.asc())).scalars().all()

    return {
        "assets": [schemas.AssetOut.model_validate(a).model_dump() for a in assets],
        "rsItems": [schemas.RsItemOut.model_validate(r).model_dump() for r in rs_items],
        "projects": [schemas.ProjectOut.model_validate(p).model_dump() for p in projects],
        "contracts": [schemas.ContractOut.model_validate(c).model_dump() for c in contracts],
        "outbounds": [schemas.OutboundOut.model_validate(o).model_dump() for o in outbounds],
        "suppliers": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in suppliers],
        "customers": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in customers],
        "flows": [schemas.FlowOut.model_validate(f).model_dump() for f in flows],
        "logs": [schemas.LogOut.model_validate(l).model_dump() for l in logs],
        "deliverableTemplates": tpl_map,
        "assetDeliverables": deliv_map,
        "categoryUnits": [schemas.CategoryUnitOut.model_validate(c).model_dump() for c in category_units],
        "cart": [schemas.CartItemOut.model_validate(c).model_dump() for c in cart],
        "files": [schemas.FileMetaOut.model_validate(f).model_dump() for f in files],
    }
