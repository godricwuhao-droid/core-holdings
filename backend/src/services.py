"""业务服务层：复刻前端 mock/store.ts 的全部业务规则

- 可售数量 = 登记 - 锁定 - 已交付；可重复售卖产品不扣减
- 状态仅 2 种（可售 / 全部出售），由数量自动判定
- 项目关联产品→锁定；合同签订→确认销售；交付完成→交付+累计销售；终止→释放锁定
- 交付撤销→反向流水；历史补录不扣数量
"""
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select, update
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

# 编号格式：项目 SP-{14位时间戳+2位随机}（存量旧编号 SP-001 同为 SP- 前缀数字）、
# 销售记录 HT-{...}、交付 CK-{4位}。
# ⚠️ FIX-20261022（ADR-030 §2）：可见性判定**禁止**再用 detail 文本正则 / 项目名匹配
# （文案一改即误判，且会漏放合同类日志）。原 _SP_CODE_RE/_CK_CODE_RE 已随 BUG-13 删除，
# 改为结构化外键（logs.projectId / contractId，flows.contractId / ref 编号归属）。


def _dec(v) -> Decimal:
    """float/Decimal/str → Decimal（经 str 中转，避免 float 二进制误差进入十进制运算）"""
    return Decimal(str(v))


# PUT/PATCH /cart/{id} 字段「未传」哨兵（CART-PATCH-20261021，2026-10-21）：
# 未传 = 保持原值（不改）；显式传 null = 清空。修复「填了销售金额后选服务期限/改数量/改客户 → 金额被清空」。
UNSET = object()


def _fmt_money(v) -> str:
    """金额文案（报错/日志展示）：千分位 + 两位小数，禁止科学计数法（如 7.58e+06）。"""
    if v is None:
        return "-"
    return f"{_dec(v):,.2f}"


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


# ============================================================
# 可见性判定（BUG-02 / BUG-13，ADR-030）：**单一判定实现**，bootstrap 与全部分页端点共用。
# 判定依据只用结构化外键（projectId / contractId / assetId / uploadedBy），
# 禁止再用 detail 文本正则或项目名匹配（文案一改即误判）。
# ============================================================
class Visibility:
    """请求级可见性上下文。

    - admin / editor：全部可见（`restricted=False`，各 visible_* 直接放行）；
    - viewer（生态人员）：仅自己下单的项目及其合同/交付/流水/日志 + 公开产品相关资源。
    """

    def __init__(self, user: "models.User | None", project_ids: set[int] | None = None,
                 contract_ids: set[int] | None = None, outbound_ids: set[int] | None = None,
                 referenced_files: set[str] | None = None,
                 own_files: set[str] | None = None):
        self.user = user
        self.username = (user.username if user is not None else "")
        self.restricted = bool(user is not None and user.role == "viewer")
        self.project_ids = project_ids or set()
        self.contract_ids = contract_ids or set()
        self.outbound_ids = outbound_ids or set()
        # 被任一产品引用的文件（assets.contractFile / featureDoc、asset_deliverables.file）
        self.referenced_files = referenced_files or set()
        # 本人上传的文件（孤儿文件仅上传人/管理员可见）
        self.own_files = own_files or set()
        # 编号集合（流水的 ref 是编号而非 id，需按编号归属判定）
        self.project_codes: set[str] = set()
        self.contract_codes: set[str] = set()
        self.outbound_codes: set[str] = set()

    # ---- 资源级判定 ----
    def project_visible(self, project_id: int | None) -> bool:
        if not self.restricted:
            return True
        return project_id is not None and project_id in self.project_ids

    def contract_visible(self, contract_id: int | None) -> bool:
        if not self.restricted:
            return True
        return contract_id is not None and contract_id in self.contract_ids

    def flow_visible(self, f: "models.AssetFlow") -> bool:
        """数量流水：合同流水按 contractId；项目/合同/交付编号流水按对应编号归属；
        产品级流水（ref=产品编号/“-”）放行（产品目录本身对所有角色可见）。"""
        if not self.restricted:
            return True
        if f.contractId is not None:
            return f.contractId in self.contract_ids
        ref = f.ref or ""
        if ref.startswith("HT-"):
            # ref 为销售记录编号：无法直接映射 id，按已可见合同 id 反查由调用方补齐（见 build_visibility）
            return ref in self.contract_codes
        if ref.startswith("SP-"):
            return ref in self.project_codes
        if ref.startswith("CK-"):
            return ref in self.outbound_codes
        return True  # 产品级流水（登记/补录等）

    def log_visible(self, lg: "models.OpLog") -> bool:
        """操作日志：**只看结构化外键**（ADR-030 §4）。

        - target='project'：projectId 可见 或 contractId 可见；两者皆空 → 对 viewer 过滤；
        - target='contract'：contractId ∈ 可见合同；为空 → 过滤；
        - target='outbound'：按 projectId / contractId 归属（交付单本身无外键时过滤）；
        - target='asset' / 'setting'：产品与基础资料对所有角色可见 → 放行。
        """
        if not self.restricted:
            return True
        target = lg.target or ""
        if target == "project":
            if lg.contractId is not None and lg.contractId in self.contract_ids:
                return True
            return lg.projectId is not None and lg.projectId in self.project_ids
        if target == "contract":
            return lg.contractId is not None and lg.contractId in self.contract_ids
        if target == "outbound":
            if lg.contractId is not None:
                return lg.contractId in self.contract_ids
            return lg.projectId is not None and lg.projectId in self.project_ids
        if target in ("asset", "setting"):
            return True
        # 无法归属的其他 target：对 viewer 一律过滤（宁可保守，不漏放）
        return False

    def file_visible(self, stored_name: str) -> bool:
        """文件可见性（ADR-030 §3）：被任一产品引用 → 所有登录用户可见；
        孤儿文件 → 仅上传人本人或 admin 可见。不可见时调用方返回 **404**（不暴露存在性）。"""
        if not self.restricted:
            return True
        if not stored_name:
            return False
        return stored_name in self.referenced_files or stored_name in self.own_files


def referenced_file_names(db: Session) -> set[str]:
    """被任一产品引用的文件散列名集合（assets.contractFile/featureDoc + asset_deliverables.file）。"""
    names: set[str] = set()
    rows = db.execute(
        select(models.Asset.contractFile, models.Asset.featureDoc)
    ).all()
    for contract_file, feature_doc in rows:
        if contract_file:
            names.add(contract_file)
        if feature_doc:
            names.add(feature_doc)
    for (f,) in db.execute(select(models.AssetDeliverable.file)).all():
        if f:
            names.add(f)
    return names


def build_visibility(db: Session, user: "models.User | None") -> Visibility:
    """构建请求级可见性上下文（viewer 才需要预计算集合；admin/editor 走放行分支）。"""
    vis = Visibility(user)
    vis.referenced_files = referenced_file_names(db)
    if not vis.restricted:
        return vis
    projects = db.execute(select(models.Project)).scalars().all()
    vis.project_ids = {p.id for p in projects if user_sees_project(user, p)}
    vis.project_codes = {p.code for p in projects if p.id in vis.project_ids}
    contracts = db.execute(select(models.Contract)).scalars().all()
    visible_contracts = [c for c in contracts if c.projectId in vis.project_ids]
    vis.contract_ids = {c.id for c in visible_contracts}
    vis.contract_codes = {c.code for c in visible_contracts}
    outbounds = db.execute(select(models.Outbound)).scalars().all()
    visible_ob = [
        o for o in outbounds
        if (o.projectId is not None and o.projectId in vis.project_ids)
        or (o.contractId is not None and o.contractId in vis.contract_ids)
    ]
    vis.outbound_ids = {o.id for o in visible_ob}
    vis.outbound_codes = {o.code for o in visible_ob}
    vis.own_files = {
        s for (s,) in db.execute(
            select(models.FileMeta.storedName).where(models.FileMeta.uploadedBy == vis.username)
        ).all()
    }
    return vis


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
            contract_id: int | None = None, operator: str = "admin",
            project_id: int | None = None) -> None:
    # FIX-5：operator 真实化——有当前用户上下文的路径由 router 透传登录用户名；
    # 无上下文的内部路径（seed/内部复用）保持默认 "admin"（兼容存量口径）。
    # project_id（BUG-13 / ADR-030 §4）：target='project' 的日志必须写结构化外键——
    # 生态人员（viewer）可见性判定只看外键，不再用 detail 文本里的 SP- 正则/项目名匹配。
    db.add(models.OpLog(
        target=target, targetName=target_name, action=action,
        detail=detail, operator=operator, time=now_str(),
        assetId=asset_id if target == "asset" else None,
        projectId=project_id if target in ("project", "outbound") else None,
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
                          rs: models.RsItem | None = None,
                          enforce_max: bool = True) -> Decimal | None:
    """ADR-018 §1/§3（PRICING-20261020）：金额（销售金额）参考区间校验。
    购物车行更新 / 加购 / checkout / 直接下单（sales/order）各入口共用，不信任前端。

    函数名中的 "discount" 为历史命名（ADR-018 当年叫「折扣金额」）——NO-DISCOUNT-20261022
    / ADR-039 后**折扣率已下线**：本函数只校验 `unit_price = amount ÷ qty` 的金额区间，
    内部**没有任何「用折扣率推算金额」的路径**（入参里也没有 rate）；ADR-018/021/037 口径不变。

    - amount 为 None → 原价成交，返回 None（unit 行 salePrice×qty / 遥感行明细 price）；
    - amount 须为非负整数元，否则 400；
    - 折扣单价 = amount ÷ qty（Decimal 保留 6 位）须落在参考区间 [priceMin, priceMax] 内：
      未设置区间 = 不限制；单边区间按单边校验；超限 400
      「单价超出该产品参考区间（{min}~{max} 元/{unit}）」（契约 §3 文案；NO-DISCOUNT-20261022
      文案收口：去「折扣」字样，与 ADR-039 折扣下线一致）。
    - ADR-021（RSITEM-RANGE-20261020）：遥感明细行（rs 非空）区间取该 rs_item 自身的
      priceMin/priceMax（不再取父产品容器 assets 的区间）；普通产品行行为不变。
    - ADR-037 §3（FORMS-20261022）：区间校验分角色——`enforce_max=False`（viewer/生态人员）
      只校验下限（amount < priceMin → 400 原文案），上限放开（加价成交允许）；
      editor/admin 维持双向（默认 True）。遥感明细行同口径分角色。
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
    # ADR-037 §3：enforce_max=False（viewer）只校验下限，上限放开
    if (lo is not None and unit_price < _dec(lo)) or (enforce_max and hi is not None and unit_price > _dec(hi)):
        raise HTTPException(400, f"单价超出该产品参考区间（{_range_label(lo, hi, u)}）")
    return amt


def _range_label(lo, hi, unit: str) -> str:
    """参考区间可读文案（单边/双边），用于 400 detail。"""
    u = unit or ""
    if lo is not None and hi is not None:
        return f"{_fmt_money(lo)}~{_fmt_money(hi)} 元/{u}"
    if lo is not None:
        return f"≥{_fmt_money(lo)} 元/{u}"
    return f"≤{_fmt_money(hi)} 元/{u}"


def _check_unit_price_range(asset: models.Asset | None, price, qty: int = 1,
                            enforce_max: bool = True) -> None:
    """unit 行单价参考区间校验（BUG-07/08，ADR-029 §1）：`_item_pricing` 不再无条件采信前端 price。

    单价 = price（元/{unit}）须落在 [priceMin, priceMax]；未设置区间 = 不限制，单边按单边校验。
    超限 400「销售单价超出该产品参考区间（…）」。
    ADR-037 §3（FORMS-20261022）：`enforce_max=False`（viewer）只校验下限，上限放开；
    editor/admin 维持双向（默认 True），与 `_check_discount_range` 同口径。
    """
    if asset is None or qty <= 0:
        return
    lo, hi = asset.priceMin, asset.priceMax
    if lo is None and hi is None:
        return
    unit_price = _dec(price)
    if (lo is not None and unit_price < _dec(lo)) or (enforce_max and hi is not None and unit_price > _dec(hi)):
        raise HTTPException(
            400,
            f"销售单价超出该产品参考区间（{_range_label(lo, hi, asset.unit)}）",
        )


def _validate_date_str(v: str, label: str, allow_empty: bool = False) -> str:
    """YYYY-MM-DD 格式校验（ADR-019/020；BUG-28 起覆盖全部日期入参）：非法 400。

    allow_empty=True：空串/None 视为「未填写」，归一为空串返回（用于选填日期：
    产品登记日期/到期日期、交付日期、项目预计签订日期/最后跟进日期）。
    只校验本次写入值，不做存量数据清洗。
    """
    s = "" if v is None else str(v).strip()
    if not s:
        if allow_empty:
            return ""
        raise HTTPException(400, f"{label}格式须为 YYYY-MM-DD")
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise HTTPException(400, f"{label}格式须为 YYYY-MM-DD")
    return s


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


# 注（NO-DISCOUNT-20261022 / ADR-039）：折扣率功能已下线，`_validate_discount_rate`
# 随全部调用点移除而删除（原 DISCOUNT-20261021 / ADR-023：0 < rate ≤ 1 否则 400）。
# 入参中的 `discountRate` 由 Pydantic 保留定义以兼容旧客户端（不 422），后端**不读不校验不写**。


def _item_pricing(a: models.Asset | None, it: schemas.ProjectItemInput,
                  enforce_max: bool = True) -> tuple[float, float]:
    """销售明细计价分支（ADR-008），返回 (price, amount)：
    - amount 模式：amount 为权威输入（整数元校验），跳过 price×qty 重算，price 为派生值；
    - unit 模式：price×qty Decimal 权威重算，且**单价必须落在产品参考区间内**
      （BUG-07/08，ADR-029 §1：不再无条件采信前端 price）。
    ADR-037 §3（FORMS-20261022）：`enforce_max` 透传给 `_check_unit_price_range`
    （viewer 只校验下限，上限放开；editor/admin 双向不变）。"""
    if a is not None and _is_amount_mode(a):
        amt = _validate_amount_yuan(it.amount)
        return _derived_price(amt, it.qty), float(amt)
    if it.qty > 0:
        _check_unit_price_range(a, it.price, it.qty, enforce_max=enforce_max)
    return float(it.price), float((_dec(it.price) * it.qty).quantize(CENT))


def _validate_item_stock(a: models.Asset, qty: int, repeat_override: bool | None = None) -> None:
    """H1：加锁前校验可用数量，避免超卖；负数量/零数量直接拒绝。

    repeat_override（BUG-05/ADR-011）：行级有效 repeatSale——遥感明细行以 rs_items.repeatSale
    为权威，**父产品 repeatSale 不参与明细行判定**（None → 取产品口径）。
    """
    if qty <= 0:
        raise HTTPException(400, f"数量必须大于 0（{a.name}）")
    if a.repeatSale if repeat_override is None else repeat_override:
        return
    available = a.quantity - a.lockedQty - a.shippedQty
    if qty > available:
        raise HTTPException(400, f"可用数量不足：{a.name} 可售 {available}{a.unit}，本单需 {qty}")


def _invariant_violation(db: Session, message: str, asset: models.Asset | None = None,
                         operator: str = "") -> None:
    """数量/金额不变量被破坏（BUG-10 / ADR-033 §3）：写审计告警 + 显式失败。

    取代 `max(0, ...)` / `min(quantity, ...)` 的静默夹断——夹断会把错误钉在边界上、
    事后无告警、无修出口。此处明确 500（视为数据不变量破缺，需人工介入），
    同时落一条 OpLog（target=asset，action=「数据不变量告警」）供排查。
    """
    try:
        add_log(db, "asset", (asset.name if asset is not None else "数量/金额不变量"),
                "数据不变量告警", message, asset_id=asset.id if asset is not None else None,
                operator=operator)
        db.flush()
    except Exception:  # 告警落库失败不掩盖原始错误
        pass
    raise HTTPException(500, f"数据不变量被破坏：{message}（请联系管理员核对台账）")


def apply_item_lock(db: Session, asset_id: int | None, qty: int, add: bool, ref: str,
                    operator: str = "", contract_id: int | None = None,
                    repeat_override: bool | None = None) -> None:
    """锁定/释放数量（BUG-10 / ADR-033 §3：**原子条件更新**，不再读-改-写）。

    - 加锁：`UPDATE assets SET lockedQty=lockedQty+:q WHERE id=:id AND quantity-lockedQty-shippedQty>=:q`，
      影响 0 行 → 400（可用数量不足）；
    - 释放：`... WHERE id=:id AND lockedQty>=:q`，影响 0 行 → 不变量告警（500），
      不再 `max(0, ...)` 静默夹断。
    repeat_override（ADR-011）：遥感明细行以 rs_items.repeatSale 为权威（父产品 repeatSale 无意义）。
    """
    a = get_asset(db, asset_id)
    if not a or qty <= 0:
        return
    if a.repeatSale if repeat_override is None else repeat_override:
        return
    from sqlalchemy import text as _sql
    if add:
        res = db.execute(
            _sql("UPDATE assets SET lockedQty = lockedQty + :q "
                 "WHERE id = :id AND quantity - lockedQty - shippedQty >= :q"),
            {"q": qty, "id": a.id},
        )
        if res.rowcount == 0:
            db.refresh(a)
            available = a.quantity - a.lockedQty - a.shippedQty
            raise HTTPException(
                400, f"可用数量不足：{a.name} 可售 {available}{a.unit}，本单需 {qty}")
    else:
        res = db.execute(
            _sql("UPDATE assets SET lockedQty = lockedQty - :q WHERE id = :id AND lockedQty >= :q"),
            {"q": qty, "id": a.id},
        )
        if res.rowcount == 0:
            db.refresh(a)
            _invariant_violation(
                db,
                f"释放锁定失败：{a.name} 当前锁定 {a.lockedQty}{a.unit}，需释放 {qty}{a.unit}（{ref}）",
                asset=a, operator=operator,
            )
    db.refresh(a)
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
# ADR-036 §4（FORMS-20261022）：遥感数据容器产品类型权威常量（新建/编辑的
# repeatSale 禁开校验统一引用，避免字符串两处硬编码漂移）
RS_DATA_TYPE = "遥感数据"


def create_asset(db: Session, data: schemas.AssetInput, operator: str = "") -> models.Asset:
    # ADR-011：遥感数据按普通父产品登记（容器，本身不可直接加购/下单），
    # 售卖粒度走 rs_items 明细表（POST /assets/{id}/rs-items）；
    # ADR-010 的三维必填/判重逻辑已移除，服务层不再读写 assets 的 4 个废弃列。
    # ADR-018 §1（PRICING-20261020）：参考区间校验（两者都有时 min ≤ max，否则 400）
    _validate_price_range(data.priceMin, data.priceMax)
    # ADR-036 §4（FORMS-20261022）：遥感数据容器按明细售卖，不支持重复售卖
    if data.type == RS_DATA_TYPE and data.repeatSale:
        raise HTTPException(400, "遥感数据容器按明细售卖，不支持重复售卖")
    # ADR-036 §1（FORMS-20261022）：登记时间不传/空 → 自动生成当天（传值仍校验格式）
    inbound_date = _validate_date_str(data.inboundDate, "登记日期", allow_empty=True) or today()
    # BUG-28：日期入参统一校验（YYYY-MM-DD，允许空串；只校验写入值）
    _validate_date_str(data.expiryDate, "到期日期", allow_empty=True)
    asset = models.Asset(
        lockedQty=0, shippedQty=0, soldAmount=0, soldCount=0,
        name=data.name, board=data.board, type=data.type, subject=data.subject,
        unit=data.unit, quantity=data.quantity, repeatSale=data.repeatSale,
        salePrice=data.salePrice,
        priceMin=data.priceMin, priceMax=data.priceMax,  # ADR-018 §1：参考区间（可空=不限制）
        status=data.status,  # 占位，下方按数量自动判定覆盖
        inboundDate=inbound_date, expiryDate=data.expiryDate,
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
             inbound_date, asset.code, "登记", operator=operator)
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
    # BUG-28：日期入参统一校验（YYYY-MM-DD，允许空串；只校验本次写入值，不清洗存量）
    # ADR-036 §1（FORMS-20261022）：inboundDate 不传 = 保持原值（exclude_unset），
    # 传值可改（只读展示是前端约束，后端不锁）
    if "inboundDate" in patch:
        _validate_date_str(patch["inboundDate"], "登记日期", allow_empty=True)
    if "expiryDate" in patch:
        _validate_date_str(patch["expiryDate"], "到期日期", allow_empty=True)
    # ADR-036 §4（FORMS-20261022）：遥感数据容器按明细售卖，不支持重复售卖——
    # 按「存量值 + 本次 patch」的最终落库值校验（覆盖 type 改为遥感数据 / repeatSale 改为 true 两种路径）
    if patch.get("type", a.type) == RS_DATA_TYPE and patch.get("repeatSale", a.repeatSale):
        raise HTTPException(400, "遥感数据容器按明细售卖，不支持重复售卖")
    # REVERT-FIX-20261022（DEFECT-2 方案 A）：遥感数据容器的 quantity 是**派生量**
    # （= 可售明细条数，见 `_sync_container_quantity`），不接受手改——
    # 手改小会让 apply_item_lock 的条件更新 `quantity-lockedQty-shippedQty>=q` 提前失败，
    # 明细明明还在却「可用数量不足」，售卖被卡住。
    # 处理：容器场景**忽略入参 quantity**（保留当前值，随后由 `_sync_container_quantity`
    # 规则决定），且不进入字段级 diff 日志；接口**不报错**——前端编辑表单可能回传表单里的
    # 旧 quantity，报错会打断整个编辑（保持幂等/兼容）。非容器产品行为完全不变。
    eff_type = patch.get("type") or a.type  # 与 repeatSale 校验同口径：按「存量值 + 本次 patch」
    if eff_type == RS_DATA_TYPE and "quantity" in patch:
        patch.pop("quantity")
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
    # REVERT-FIX-20261022（DEFECT-2）：容器 quantity 忽略入参后，按派生规则复核一次——
    # 无锁定/无交付时自愈为明细条数（顺手修掉历史被手改小的漂移值）；在售中不改数量，
    # 仅校验 quantity >= lockedQty + shippedQty（不满足 → 不变量告警，与明细维护路径同口径）。
    if a.type == RS_DATA_TYPE:
        _sync_container_quantity(db, a.id, operator=operator)
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
    # 1a) FIX-4（合同感知）：合同明细（contractId 非空）——仅当存在 active/pending/delivering
    #     合同引用时拒绝；terminated 合同的引用放行（前端已有「未关联产品」兜底）。
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
    # 1a-2) BUG-14：存在 **delivered** 合同引用 → 拒绝（此前放行，删除后撤销交付会「静默成功但零回滚」，
    #       合同永久卡 delivered）。已交付引用只能先撤销交付（合同回 delivering）再终止后删除。
    ref_delivered = db.execute(
        select(models.Contract)
        .join(models.ProjectItem, models.ProjectItem.contractId == models.Contract.id)
        .where(models.ProjectItem.assetId == asset_id,
               models.Contract.status == "delivered")
        .limit(1)
    ).scalars().first()
    if ref_delivered:
        raise HTTPException(400, "该产品存在已交付销售记录，不可删除")
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
    # 3) 清理引用了该产品的购物车项（含 ADR-011 遥感明细行；含**其他用户**的行）
    # BUG-42：清理行数写入 OpLog detail，便于事后追溯「谁的购物车被清了几行」
    cart_cleared = 0
    for c in db.execute(select(models.CartItem).where(models.CartItem.assetId == asset_id)).scalars():
        db.delete(c)
        cart_cleared += 1
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
    # BUG-42：清理他人购物车行数必须留痕（此前静默删除无提示无记录）
    detail = f"删除产品 {code}"
    if cart_cleared:
        detail += f"；已清理 {cart_cleared} 行购物车引用（含其他账号）"
    add_log(db, "asset", name, "删除", detail, asset_id=asset_id, operator=operator)
    db.commit()


# ============================================================
# 遥感数据可售明细（ADR-011：父产品 + 明细两层模型）
# ============================================================
def _rs_item_desc(it: models.RsItem) -> str:
    """明细可读描述：省/市 · 精度 · 月份（市为空时省略）"""
    loc = f"{it.province}/{it.city}" if it.city else it.province
    return f"{loc} {it.resolution:g}m {it.saleMonth}"


def _rs_repeat_desc(repeat_sale: bool) -> str:
    """明细售卖模式的可读描述（OpLog 用，ADR-038）。"""
    return "可重复售卖" if repeat_sale else "单次售卖"


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


def _rs_item_sold_counts(db: Session, item_ids: list[int] | None = None) -> dict[int, int]:
    """明细级「已售次数」（派生字段 `soldCount` 的**唯一实现**，bootstrap 与分页端点共用）。

    口径：该明细被 **delivered 状态合同**的项目明细计数
    （`project_items.itemId == rs_item.id` 且所属合同 `status='delivered'`）。
    **一条聚合查询**（`GROUP BY project_items.itemId`）覆盖全部入参 id，
    复杂度 O(log n + k)（k=命中明细数），不存在逐明细 N+1。

    - `item_ids=None` → 统计全表（bootstrap 全量快照；SQL 无 IN 条件）
    - `item_ids=[]` → 直接返回 `{}`（不发查询）
    - 返回 `{rsItemId: count}`；无交付计数的明细不在结果中（调用方按 0 兜底）
    """
    if item_ids is not None and not item_ids:
        return {}
    q = (
        db.query(models.ProjectItem.itemId, func.count(models.ProjectItem.id))
        .join(models.Contract, models.ProjectItem.contractId == models.Contract.id)
        .filter(
            models.Contract.status == "delivered",
            models.ProjectItem.itemId.isnot(None),  # 排除无明细行（存量/非遥感行）
        )
    )
    if item_ids is not None:
        q = q.filter(models.ProjectItem.itemId.in_(item_ids))
    return {item_id: cnt for item_id, cnt in q.group_by(models.ProjectItem.itemId).all()}


def _rs_item_occupied(db: Session, item_id: int) -> bool:
    """该明细当前是否**被有效合同占用**（真值查询，`_sync_rs_item_status` 的唯一占用判据）。

    占用 = `project_items.itemId == 明细 id` **且** 所属 `contracts.status != 'terminated'`
    （pending / active / delivering / delivered 全算占用；terminated 不占用）。
    与 `repeatSale` 无关——`repeatSale` 只在状态真值规则里作为「永不售罄」的短路条件。
    """
    return db.execute(
        select(models.ProjectItem.id)
        .join(models.Contract, models.Contract.id == models.ProjectItem.contractId)
        .where(
            models.ProjectItem.itemId == item_id,
            models.Contract.status != "terminated",
        )
        .limit(1)
    ).scalars().first() is not None


def _sync_rs_item_status(db: Session, item_id: int | None) -> str | None:
    """按真值重算**单条**明细状态并落库（明细 `status` 的**唯一写入实现**，RS-STATUS-20261022）。

    真值规则（业务方方案，ADR-038 Decision 3 修订；与外层产品状态同构）：
        repeatSale = true                  → in_stock（可重复售卖只计次，永不售罄）
        否则 被非 terminated 合同占用      → all_sold（已售罄，不可再选）
        否则 未被任何有效合同引用          → in_stock（可售）

    幂等 / 自愈：每次调用都**重新查真值**并与现值比较，无变化不写库、不写日志；
    因此允许在任意位置冗余调用（遗漏点也会在后续动作中被纠正）。
    WHY 不回写 OpLog：这是可重算的派生字段，一次结算含 N 条明细会产生 N 条噪声日志，
    而占用变化的业务动作本身已有流水（project_lock / cancel_release / sale_out）+ OpLog 覆盖。

    调用点（**所有占用状态变化点，禁止各处手写 `item.status = ...`**）：
    `_create_project_core`（下单锁定后）、`_apply_item_delivery`（交付）、
    `_apply_item_release`（释放）、`_revert_outbound_inner`（撤销交付回 locked）、
    `update_rs_item`（repeatSale 切换）、`review_project`（驳回批量）、
    `change_project_status`（批量终止/交付兜底）、`delete_project`（删除后兜底）。

    返回落库后的状态；明细不存在 / item_id 为空时返回 None（非遥感行直接跳过）。
    """
    if not item_id:
        return None
    rs = db.get(models.RsItem, item_id)
    if rs is None:
        return None
    if rs.repeatSale:
        new_status = "in_stock"
    else:
        new_status = "all_sold" if _rs_item_occupied(db, rs.id) else "in_stock"
    if rs.status != new_status:
        # session 为 autoflush=False：显式 flush，让同事务内后续按库值统计的调用方
        #（_rs_container_available_counts / _rs_container_item_count）读到最新状态
        rs.status = new_status
        db.flush()
    return rs.status


def _sync_rs_item_statuses(db: Session, item_ids: Iterable[int | None]) -> None:
    """批量版 `_sync_rs_item_status`（去重 + 跳过空值），供批量动作（驳回/批量状态/删项目）兜底自愈。

    WHY 需要批量兜底：批处理里「合同状态」与「明细释放」的写入顺序不保证先落库
    （如驳回是 `_apply_item_release` → `c.status = "terminated"`），单点重算此刻读到的
    仍是旧合同状态；调用方在批量结束后统一 flush + 重算一次，状态才等于真值。
    """
    for item_id in {i for i in item_ids if i}:
        _sync_rs_item_status(db, item_id)


def _rs_container_available_counts(
    db: Session, rs_items: list[models.RsItem]
) -> dict[int, int]:
    """容器「可售数量」= `status='in_stock'` 的明细条数（派生字段 `availableCount` 的唯一实现）。

    口径（RS-STATUS-20261022，ADR-038 Decision 3 修订；**替换**上一版
    「明细总数 − 被非 terminated 合同占用且 repeatSale=false 的明细数」的 join 推导）：
        `availableCount = COUNT(rs_items WHERE status = 'in_stock' GROUP BY assetId)`
    明细状态由 `_sync_rs_item_status` 在各占用状态变化点按真值维护，可售数直接数状态即可——
    与外层产品 `quantity − lockedQty − shippedQty` 完全同构（一个数数量、一个数状态）。

    **1 条聚合查询**（走 idx_rs_items_assetId / ix_rs_items_status；与产品数/明细数解耦，
    禁止按产品循环查询 → 无 N+1）；结果**不依赖**调用方传入的 `rs_items` 是否全量（防漏数）。

    **与调用者可见性无关**：查询是全量、不看 `Visibility`——viewer 的 bootstrap 只含
    自己下单的项目/合同，用它算会失真（同 `_rs_item_sold_counts` 的思路，避免重演 BUG-46）。

    返回 `{assetId: availableCount}`；无明细 / 明细全部售罄的容器不在结果中（调用方按 0 兜底）。

    参数 `rs_items`：保留入参以兼容既有唯一调用点（`bootstrap`，已整表加载明细）；
    本函数口径**不再依赖**它的内容。
    """
    return {
        asset_id: int(cnt)
        for asset_id, cnt in (
            db.query(models.RsItem.assetId, func.count(models.RsItem.id))
            .filter(models.RsItem.status == "in_stock")  # 已售罄明细不计入可售数
            .group_by(models.RsItem.assetId)
            .all()
        )
    }


def _rs_container_item_count(db: Session, asset_id: int) -> int:
    """容器**明细总条数**（含已售罄；`_sync_container_quantity` 的唯一计数口径 = 容器 quantity 语义）。

    注意与 `_rs_container_available_counts` 区分：本函数数的是「一共登记了多少期」，
    后者数的是「还有几期可售（status='in_stock'）」。
    """
    return int(
        db.query(func.count(models.RsItem.id))
        .filter(models.RsItem.assetId == asset_id)
        .scalar()
        or 0
    )


def _sync_container_quantity(db: Session, asset_id: int | None,
                             operator: str = "") -> int | None:
    """遥感容器 `quantity` 与可售明细条数同步（**唯一实现**，RS-REPEAT-20261022-FIX）。

    WHY（缺陷根因）：容器的「数量」语义 = 可售明细条数（一期明细 = 一期可售）。
    父产品 `quantity` 若停留在 1（登记时的占位值），则明细行下单时
    `apply_item_lock(asset_id=容器, qty=1)` 的条件更新
    `quantity - lockedQty - shippedQty >= 1` 只有第一条能成功，第二条起 rowcount=0 → 400
    「可用数量不足」；`_validate_item_stock` 的聚合校验、`_apply_item_delivery` 的
    `shippedQty + qty > quantity` 同样因此失真（后者表现为 500 不变量告警）。
    把 `quantity` 与明细条数对齐后，上述三处 `quantity - lockedQty - shippedQty`
    口径天然等于 `availableCount`（RS-STATUS-20261022 起 = `COUNT(status='in_stock')`）——
    锁一条明细 ⇒ lockedQty +1 且该明细置 all_sold（可售 −1），两个口径同涨同落。
    注：`quantity` 是**容器明细总条数**（含已售罄），手改一律被忽略（见 update_asset DEFECT-2）。

    规则：
    - 非遥感容器 / 产品不存在 → 不做任何事，返回 None；
    - `lockedQty == 0 and shippedQty == 0`（无任何真实锁定/已交付）→ `quantity = 明细条数`；
    - 否则（在售数据）→ **不改数量**（避免把进行中的锁定/交付统计冲掉），
      仅校验 `quantity >= lockedQty + shippedQty`，不满足 → `_invariant_violation`（500 + 审计告警）。

    调用点：`create_rs_item` / `delete_rs_item`（提交前同事务）；
    `scripts/import_rs_items.py` / `scripts/reset_rs_items.py` /
    `scripts/sync_container_quantity.py` 内以等价 SQL 实现（脚本不 import 业务包）。
    返回同步后的 quantity（未处理时返回 None）。
    """
    if not asset_id:
        return None
    a = get_asset(db, asset_id)
    if a is None or a.type != RS_DATA_TYPE:
        return None
    locked, shipped = int(a.lockedQty or 0), int(a.shippedQty or 0)
    if locked == 0 and shipped == 0:
        count = _rs_container_item_count(db, a.id)
        if a.quantity != count:
            old, a.quantity = a.quantity, count
            refresh_status(a)  # 数量变化会影响「可售 / 全部出售」两态判定
            add_log(db, "asset", a.name, "同步容器数量",
                    f"容器数量按可售明细条数同步：{old} → {count}（明细 {count} 条）",
                    asset_id=a.id, operator=operator)
        return a.quantity
    if a.quantity < locked + shipped:
        _invariant_violation(
            db,
            f"{a.name} 容器数量 {a.quantity} 小于已锁定 {locked} + 已交付 {shipped}"
            f"（明细 {_rs_container_item_count(db, a.id)} 条，已锁定/交付中不可自动同步数量）",
            asset=a,
        )
    return a.quantity


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
            f"新增明细 #{it.id}：{_rs_item_desc(it)}，单价 {_fmt_amount_yuan(price)}"
            f"，{_rs_repeat_desc(it.repeatSale)}",
            asset_id=a.id, operator=operator)
    # RS-REPEAT-20261022-FIX §1：容器 quantity = 可售明细条数（同事务提交前同步）
    _sync_container_quantity(db, a.id, operator=operator)
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
    old_repeat = bool(it.repeatSale)
    it.province, it.city, it.resolution = province, city, resolution
    it.saleMonth, it.price, it.repeatSale = sale_month, price, data.repeatSale
    # ADR-021（RSITEM-RANGE-20261020）：参考区间（与产品区间同口径；传 null 清空=不限制）
    _validate_price_range(data.priceMin, data.priceMax)
    it.priceMin, it.priceMax = data.priceMin, data.priceMax
    it.updatedAt = now_str()
    # RS-STATUS-20261022（§二.5）：repeatSale 切换会改变「是否计入可售」→ 立刻按真值重算状态：
    #   切到 true  → 永不售罄，回 in_stock（容器可售数 +1）；
    #   切回 false → 若仍被非 terminated 合同占用则回 all_sold（可售数 −1）。
    # 必须在 add_log / commit 之前调用（同一事务、日志描述里的状态才与落库一致）。
    old_status = it.status
    new_status = _sync_rs_item_status(db, it.id)
    # ADR-038：重复售卖开关变更对可售口径有直接影响 → OpLog 记录「是 → 否」变化，便于追溯
    repeat_change = ""
    if old_repeat != bool(it.repeatSale):
        repeat_change = (f"，可重复售卖：{'是' if old_repeat else '否'} → "
                         f"{'是' if it.repeatSale else '否'}")
    if old_status != new_status:
        repeat_change += f"，状态：{old_status} → {new_status}"
    add_log(db, "asset", a.name, "编辑可售明细",
            f"明细 #{it.id} 更新为：{_rs_item_desc(it)}，单价 {_fmt_amount_yuan(price)}"
            f"，{_rs_repeat_desc(it.repeatSale)}{repeat_change}",
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
    asset_id = it.assetId  # 先取，flush 后实例进入 deleted 态不可再读属性
    db.delete(it)
    add_log(db, "asset", a.name if a else f"产品 #{asset_id}", "删除可售明细",
            f"删除明细 #{item_id}：{desc}",
            asset_id=asset_id if a else None, operator=operator)
    # RS-REPEAT-20261022-FIX §1：容器 quantity = 可售明细条数。
    # session 为 autoflush=False，必须先显式 flush，否则 COUNT 仍统计到待删行。
    db.flush()
    _sync_container_quantity(db, asset_id, operator=operator)
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
    """⚠️ **已无调用方（FIX-20261022 / ADR-029 §3）**：`POST /projects/{id}/resubmit` 现直接
    返回 410 Gone，本函数仅作为历史实现保留，**新代码禁止调用**（唯一改单路径 =
    「撤销」→ 购物车重下；「重新提交」= `refill_project_cart` 回填购物车）。

    历史说明（2026-10-20；deprecated ADR-027）：前端入口已改为
    `POST /projects/{id}/refill-cart` 进购物车改单。

    已终止项目（被驳回/取消/终止）的**下单账号**（或商务/管理员）
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
            contract_id=None, project_id=project.id)
    db.commit()
    db.refresh(project)
    return project


# ============================================================
# 撤销待审核订单（ADR-026）：终止原单（释放锁定 + 留痕）+ 全部明细回填下单人购物车
# ============================================================
WITHDRAW_REASON_MAX = 200


def _can_withdraw(p: models.Project, user: models.User) -> bool:
    """撤销权限（ADR-026 §2）：admin 越过；否则仅下单人本人——
    creator（下单 username）匹配；存量 creator 为空时回退 rep（生态人员姓名/账号）匹配。"""
    if user.role == "admin":
        return True
    if (p.creator or "").strip():
        return p.creator.strip() == user.username
    return bool((p.rep or "").strip()) and p.rep.strip() in (user.username, user.name)


def _withdraw_owner(db: Session, p: models.Project) -> models.User | None:
    """回填购物车目标账号（下单人）：creator（username）优先；存量 creator 为空回退 rep
    （先按 username、再按姓名匹配）。admin 代撤销/代重新提交同样回填到**下单人**购物车。
    口径由 withdraw（ADR-026）与 refill-cart（ADR-027）共用，勿各写一套。"""
    keys = [k.strip() for k in (p.creator, p.rep) if (k or "").strip()]
    for key in keys:
        u = db.query(models.User).filter(models.User.username == key).first()
        if u is not None:
            return u
    rep = (p.rep or "").strip()
    if rep:
        return db.query(models.User).filter(models.User.name == rep).first()
    return None


# ADR-042 §2：回填模式白名单（merge=保留购物车现有商品，同键行被覆盖；
# replace=先清空目标用户购物车再回填，同一事务、不可撤销）
REFILL_MODES = ("merge", "replace")

# REFILL-20261022-B3：回填逐行结果 `rows[].code` 白名单——给前端**结构化**失败类别，
# 避免其用正则解析 `reason` 中文串（文案随时可能调整）。
# ok=成功 / insufficient=可售不足（含被占用）/ no_asset=明细未关联产品或产品已不存在 /
# other=其它（区间不符、金额校验失败等写阶段校验失败）。
REFILL_ROW_CODES = ("ok", "insufficient", "no_asset", "other")


def _refill_owner_brief(u: models.User | None) -> dict | None:
    """回填对象（下单人）摘要：供前端判断「回填对象是否当前登录者」（ADR-042 §5）。
    理论上回填目标必定存在；None 仅作防御（不让响应炸掉）。"""
    if u is None:
        return None
    return {"id": u.id, "username": u.username, "name": u.name}


def _refill_cart_from_project(db: Session, p: models.Project, target_user_id: str, *,
                              mode: str = "merge") -> dict:
    """把项目全部明细回填 `target_user_id` 的购物车（ADR-026 §4 口径，ADR-027 两处复用，
    ADR-042 增补「同键替换 / mode / 逐行结果」）。

    **唯一实现**：`withdraw_project`（撤销）与 `refill_project_cart`（重新提交）都调本函数，
    避免「客户/数量/金额/服务期限/折扣率/遥感明细 itemId」两套口径漂移。
    - 行级客户取**所属合同**的 customer（ADR-007 拆合同口径），存量无合同明细回退项目客户；
    - ADR-042 §1：判重键 (userId, assetId, itemId, customer) 命中已有行时**覆盖**
      qty/amount/serviceStart/serviceEnd（`existing_policy="replace"`），不新增行、不累加——
      重试天然幂等（修「重试翻倍」）；`POST /cart` 加购仍为累加（不在本函数内）。
    - ADR-042 §2：`mode="replace"` 先清空目标用户购物车（`_clear_cart`，**不提交**），
      记录 `cleared` 行数；`mode="merge"` 保留现有商品。非法 mode → 400。
    - ADR-042 补遗1：`mode="replace"` **先预检、后清空**（两阶段）——预检为纯计算、零写入；
      **可行行数 == 0 → 跳过清空**（`cleared=0`，全量 rows 计 skipped）直接返回，绝不出现
      「购物车被清空且回填全失败」的数据破坏。
    - ADR-042 补遗2：`mode="replace"` 仅允许清空**本人**购物车——守卫在 `refill_project_cart`
      的幂等短路与全部写操作之前（代操作 → 400，只能走 merge）。
    - ADR-042 §4：逐行**预检可售**（复用统一口径 `_avail`）——不足则直接计 skipped 并给出
      带库存数值的「已被其他订单占用」文案，不再透传 `_cart_add_inner` 的泛化报错；
      预检只判「可售是否够」，区间/金额校验仍在写阶段由 `_cart_add_inner` 单一来源负责；
    - 容错：单行因区间/数据缺失无法回填时**不中断**——先降级 `amount=None`（原价成交）
      重试，仍失败则跳过并计入 skipped/skippedReasons；
    - **不提交事务**（调用方单事务收口），**不加锁**（回填不占 lockedQty，与下单锁量无关）。

    返回 `{restored, amountFallback, skipped, skippedReasons, mode, cleared, rows}`，
    `rows = [{assetName, qty, ok, reason, assetId, code, need}]` 逐行结果（成功行
    `ok=True, reason=""`）。`assetId/code/need` 为 REFILL-20261022-B3 **加性**字段
    （旧 4 键全保留），`reason` 与 `skippedReasons` 的文案**逐字未变**——新增字段只为
    让前端做结构化渲染（产品名 + 数量 + 状态胶囊 + 库存/锁定/出库/需求），不解析中文文案。
    """
    if mode not in REFILL_MODES:
        # 内部函数同样防御（唯一合法值见 REFILL_MODES），校验置于任何写操作之前
        raise HTTPException(400, "非法的回填模式")

    def _label(it: models.ProjectItem) -> str:
        """行标签（产品名；产品已删/未关联时给兜底文案）。`db.get` 走 identity map，重复调用不再发 SQL。"""
        a = get_asset(db, it.assetId)
        return a.name if a is not None else f"产品 #{it.assetId}"

    def _row(it: models.ProjectItem, label: str, ok: bool, reason: str, code: str) -> dict:
        """逐行结果（键顺序即响应 JSON 顺序）。

        REFILL-20261022-B3 加性字段：
        - `assetId`：产品 id（未关联产品时为 `None`），前端按 id 从 bootstrap 镜像读库存；
        - `code`：失败类别，取值见 `REFILL_ROW_CODES`（成功行 `"ok"`）；
        - `need`：本次需要数量（= 行 qty，**成功行也填**），与 `qty` 同源。
        `reason` 保持既有完整文案（日志/旧消费方仍可用），本次一个字未改。
        """
        qty = int(it.qty or 0)
        return {
            "assetName": label,
            "qty": qty,
            "ok": ok,
            "reason": reason,
            "assetId": int(it.assetId) if it.assetId else None,
            "code": code,
            "need": qty,
        }

    # ---------- 阶段 1：预检（纯计算，零写入，ADR-042 补遗1） ----------
    # 只判「可售是否够」：可售口径复用唯一实现 `_avail`（= quantity - lockedQty - shippedQty，
    # clamp 0）+ repeatSale 豁免（与 `_check_stock` 同口径）。区间/金额/客户等校验属于写阶段，
    # 仍由 `_cart_add_inner` 单一来源负责——预检**不重复实现**，避免两套校验漂移。
    # planned = [(明细, 行级客户, 是否可行, 不可行原因, rows[].code)]，顺序 = p.items 顺序。
    # REFILL-20261022-B3：第 5 位 code 与第 4 位 reason 一一对应（reason 文案不动，只并出结构化类别）。
    planned: list[tuple[models.ProjectItem, str, bool, str, str]] = []
    for it in list(p.items):
        a = get_asset(db, it.assetId)
        if not it.assetId:
            planned.append((it, "", False, f"明细 #{it.id} 未关联产品，无法回填购物车",
                            "no_asset"))
            continue
        if a is None:
            planned.append((it, "", False, f"产品 #{it.assetId} 已不存在", "no_asset"))
            continue
        # ADR-042 §4 逐行预检（在 _cart_add_inner 之前）：可售口径复用唯一实现 `_avail`，
        # 不另起一套算法。可重复售卖（明细 repeatSale / 产品 repeatSale）不占数量，跳过预检。
        rs = db.get(models.RsItem, it.itemId) if it.itemId else None
        repeat = rs.repeatSale if rs is not None else a.repeatSale
        available_qty = _avail(a)
        if not repeat and available_qty < int(it.qty or 0):
            # 此处 product 已确认存在 → assetId 为真实产品 id，need = 本次需求数量
            planned.append((it, "", False,
                            f"「{a.name}」可售数量不足（库存 {a.quantity}，已锁定 {a.lockedQty}，"
                            f"已出库 {a.shippedQty}，本次需 {it.qty}），该产品已被其他订单占用，"
                            f"请等待释放或补货后再提交", "insufficient"))
            continue
        # 行级客户：所属合同的客户（ADR-007 拆合同口径）；存量无合同明细回退项目客户
        customer = (it.contract.customer if it.contract is not None else p.customer) or ""
        planned.append((it, customer, True, "", "ok"))

    restored = 0
    amount_fallback = 0
    skipped = 0
    skipped_reasons: list[str] = []
    rows: list[dict] = []
    cleared = 0
    feasible_count = sum(1 for _it, _c, ok, _r, _code in planned if ok)

    # ---------- 阶段 2a：仅 replace 才清空（且必须「有可行行」才清） ----------
    if mode == "replace":
        if feasible_count == 0:
            # ADR-042 补遗1：可行行为 0 → **跳过清空**（cleared=0），不写任何数据直接返回；
            # 用户原购物车一行不动，由前端弹「无法回填」列出逐行原因（修数据破坏级缺陷：
            # 原实现「先清空再回填」，全部行因可售不足被跳过时购物车被清空且不可回滚）。
            for it, _customer, _ok, reason, code in planned:
                skipped += 1
                skipped_reasons.append(reason)
                rows.append(_row(it, _label(it), False, reason, code))
            return {
                "restored": 0,
                "amountFallback": 0,
                "skipped": skipped,
                "skippedReasons": skipped_reasons,
                "mode": mode,
                "cleared": 0,
                "rows": rows,
            }
        # ADR-042 §2：清空后回填（同一事务，不 commit；flush 让后续判重/合计看到删除结果）
        cleared = len(_cart_list(db, target_user_id))
        _clear_cart(db, target_user_id)
        db.flush()

    # ---------- 阶段 2b：逐行写入（merge 不清空；replace 已在上一段清空） ----------
    for it, customer, ok, reason, code in planned:
        label = _label(it)
        if not ok:
            # 预检已判不可行（未关联产品 / 产品已删 / 可售不足）：零写入，直接计入 skipped
            # code 由预检给出（no_asset / insufficient），与 reason 一一对应
            skipped += 1
            skipped_reasons.append(reason)
            rows.append(_row(it, label, False, reason, code))
            continue
        # NO-DISCOUNT-20261022 / ADR-039：不再透传明细的 discountRate 快照（新购物车行恒 null；
        # 历史值留在 project_items 里可追溯，不回填购物车）
        base = dict(
            assetId=it.assetId, qty=it.qty, customer=customer, itemId=it.itemId,
            serviceStart=it.serviceStart, serviceEnd=it.serviceEnd,
        )
        first_err = ""
        try:
            # ADR-042 §1：回填走「同键替换」，不累加（重试不翻倍）
            _cart_add_inner(db, schemas.CartItemInput(amount=it.amount or None, **base),
                            user_id=target_user_id,  # type: ignore[arg-type]
                            existing_policy="replace")
            restored += 1
            rows.append(_row(it, label, True, "", "ok"))
            continue
        except HTTPException as exc:
            first_err = str(exc.detail)
        if not it.amount:
            # 订单行本就无折扣金额（原价成交口径），无降级空间 → 跳过
            # REFILL-20261022-B3：写阶段校验失败（区间不符 / 金额校验等）统一归 "other"
            skipped += 1
            reason = f"{label}：{first_err}"
            skipped_reasons.append(reason)
            rows.append(_row(it, label, False, reason, "other"))
            continue
        # 降级重试：amount=None（原价成交）——区间/金额口径失配时保证不被单行卡死
        try:
            _cart_add_inner(db, schemas.CartItemInput(amount=None, **base),
                            user_id=target_user_id,  # type: ignore[arg-type]
                            existing_policy="replace")
            restored += 1
            amount_fallback += 1
            rows.append(_row(it, label, True, "", "ok"))
        except HTTPException as exc:
            # 降级（amount=None）仍失败 → 写阶段校验问题，归 "other"
            skipped += 1
            reason = f"{label}：{exc.detail}"
            skipped_reasons.append(reason)
            rows.append(_row(it, label, False, reason, "other"))
    return {
        "restored": restored,
        "amountFallback": amount_fallback,
        "skipped": skipped,
        "skippedReasons": skipped_reasons,
        "mode": mode,
        "cleared": cleared,
        "rows": rows,
    }


def withdraw_project(db: Session, project_id: int, reason: str, user: models.User) -> dict:
    """POST /projects/{id}/withdraw（ADR-026）：生态人员「撤销」自己提交的待审核订单。

    语义 = **终止原单 + 全部明细自动回填下单人购物车**（原单保留 terminated 历史，不删除）：
    ① 逐合同 pending → terminated（复用 `_change_contract_status_core`：释放真实锁定 +
       `cancel_release` 流水 + OpLog），并在合同 remark 追加「撤销：{reason}」留痕
       （`_change_contract_status_core` 只把 reason 写进 OpLog，不写 remark，故此处补写；
       追加而非覆盖，且已含同文案时不重复追加）；
    ② 项目 status 置 terminated（含存量无合同项目）+ `_recompute_project` 保持
       金额/客户/主体派生口径一致；
    ③ 有商务负责人则解绑（置空）并留痕；
    ④ 逐明细调 `_refill_cart_from_project`（ADR-027 共享实现，ADR-042 传 `mode="merge"`）
       回填**下单人**购物车（保留客户/数量/金额/服务期限/遥感明细 itemId；判重键
       (userId, assetId, itemId, customer) 命中即**覆盖**，不累加——ADR-042 §1 顺带修掉
       「撤销后同键行翻倍」），并置 `p.cartRefilled = True`
       （幂等标记：之后点「重新提交」不再重复回填）；
       ⚠️ 撤销**不清空**购物车（`mode="merge"`），OpLog 文案与本函数返回结构一字未改；
    ⑤ OpLog（`撤销订单`）+ 路由层审计。

    回填容错（ADR-026 §4）：单行因区间/可售/数据缺失无法回填时**不中断撤销**——
    先降级 `amount=None`（原价成交）重试，仍失败则跳过并计入 `skipped/skippedReasons`。
    单事务（**校验全部前置**，进入写路径后不再抛 400，避免半途回滚）。
    """
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "销售项目不存在")
    if not _can_withdraw(p, user):
        raise HTTPException(403, "只能撤销自己提交的订单")
    if p.status != "pending":
        raise HTTPException(400, "仅待审核订单可撤销")
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "请填写撤销原因")
    if len(reason) > WITHDRAW_REASON_MAX:
        raise HTTPException(400, "撤销原因不能超过 200 字")
    owner = _withdraw_owner(db, p)
    if owner is None:
        raise HTTPException(400, "下单账号不存在，无法回填购物车")
    target_user_id = str(owner.id)  # cart_items.userId 存 users.id 字符串（ADR-009）
    note = f"撤销：{reason}"

    # ① 合同 pending → terminated（复用终止链路：释放真实锁定 + cancel_release 流水 + 留痕）
    if p.contracts:
        for c in list(p.contracts):
            _change_contract_status_core(db, c, "terminated", note, operator=user.username)
            # remark 留痕：追加而非覆盖（保留下单备注）；已含同文案则不重复追加
            if note not in (c.remark or ""):
                c.remark = f"{c.remark}｜{note}" if (c.remark or "").strip() else note
                c.updatedAt = today()
    else:
        # 存量兼容（无合同项目）：沿用旧的全量释放语义
        _terminate_project(db, p, note, operator=user.username)

    # ② 解绑商务负责人（留痕进下方 OpLog，避免额外日志噪声）
    old_owner = (p.businessOwner or "").strip()
    if old_owner:
        p.businessOwner = ""

    # ③ 项目终态 + 派生字段重算（金额/客户/主体随合同口径保持一致）
    _recompute_project(p)
    p.status = "terminated"  # 显式终态（无合同项目派生结果为 active，必须覆盖）
    p.updatedAt = today()

    # ④ 逐明细回填下单人购物车（共享实现：单行失败绝不中断整体撤销）
    # ADR-042 §2：撤销固定 `mode="merge"`（**不清空**购物车），但自动获得 replace 的
    # upsert 语义（同键覆盖不累加）；返回结构与 OpLog 文案保持原样，不携带 mode 字段
    refill = _refill_cart_from_project(db, p, target_user_id, mode="merge")
    restored = refill["restored"]
    amount_fallback = refill["amountFallback"]
    skipped = refill["skipped"]
    skipped_reasons = refill["skippedReasons"]
    # 幂等标记（ADR-027）+ BUG-15：**仅当全部明细都成功回填（skipped == 0）才置位**——
    # 有跳过行时保持 False，前端据 skippedReasons 提示并允许「重新提交」重试（原实现
    # 即使全部行回填失败也置 True，导致明细丢失且原单不可删不可重提）。
    # ⚠️ ADR-028 的撤销单删除护栏依赖该标记：存在跳过行时该单仍可被删除（预期，见 changelog）。
    p.cartRefilled = (skipped == 0)

    # ⑤ OpLog（详情尾注解绑信息，保持「1 次撤销 = 1 条撤销日志」）
    detail = (f"待审核订单已撤销，{restored} 行明细回填购物车"
              f"（原价回填 {amount_fallback} 行，跳过 {skipped} 行），原因：{reason}")
    if old_owner:
        detail += f"；原商务负责人 {old_owner} 已解绑"
    if skipped:
        detail += "；存在跳过行，未置「已回填」标记（可点「重新提交」重试）"
    add_log(db, "project", p.name, "撤销订单", detail, operator=user.username, project_id=p.id)
    db.commit()
    return {
        "ok": True,
        "restored": restored,
        "amountFallback": amount_fallback,
        "skipped": skipped,
        "skippedReasons": skipped_reasons,
    }


# ============================================================
# 「重新提交」收口购物车（ADR-027）：终止项目明细确保在**下单人**购物车，只回填一次
# ============================================================
def refill_project_cart(db: Session, project_id: int, user: models.User,
                        mode: str = "merge") -> dict:
    """POST /projects/{id}/refill-cart（ADR-027）：终止项目「重新提交」改为**进购物车改单**。

    语义 = 确保原单全部明细在**下单人**购物车 → 前端跳 `/cart` 结算（与撤销后的动线一致）；
    **不新建订单**、不改项目状态、不改合同、不锁量（回填不占 lockedQty）。

    - 守卫（顺序固定，全部在写操作之前，保持单事务）：项目存在（404）→ `status == 'terminated'`
      （否则 400）→ 权限：**viewer 仅本人项目（`user_sees_project`，creator 口径、存量回退 rep，
      否则 403）/ admin 放行 / editor → 403（ADR-043）** → 下单账号存在（400，无法确定回填目标）→
      **`mode == 'replace'` 仅限本人（400，ADR-042 补遗2）** → 幂等短路。
      `mode ∉ {merge, replace}` → 400（ADR-042 §2，同样前置）。
    - **ADR-043（REFILL-20261022-B4）：商务（editor）禁入「重新提交」**——回填目标**恒为下单人**
      （`_withdraw_owner`），editor 操作后自身购物车无变化，只会造成「提示成功但什么也没发生」的误解；
      合法路径 = 通知下单人本人重新提交，或由 admin 代操作。**部分取代 ADR-027 的「admin/editor 放行」**
      （editor 部分失效）；路由层 `require_order` 未改，三角色均可进端点，由本业务级守卫拒绝
      （错误信息比通用 403 更准确）。撤销（`withdraw_project`）权限未变，editor 仍可撤销。
    - **ADR-042 补遗2：`replace` 仅限本人购物车**——回填目标恒为下单人，若操作者不是下单人
      （admin/其他商务代操作）则 `replace` 会清空**他人**购物车（跨用户破坏）→ 400
      「只能对本人购物车执行『清空后回填』，他人项目请使用合并」；代操作场景只保留 `merge`。
    - **ADR-042 补遗1：`replace` 先预检、后清空**（见 `_refill_cart_from_project`）——可行行为 0
      时**不清空**（`cleared == 0` 且 `mode == "replace"` 是合法组合），用户原购物车不丢。
    - **幂等只回填一次（仅对 merge 生效，ADR-042 §2）**：`p.cartRefilled` 为 True 且
      `mode == 'merge'` → 直接返回 `alreadyRefilled: true`（不写库、不回填、不打日志）；
      `mode == 'replace'`（用户主动「清空重建」）**跳过幂等短路**，返回 `forced: true`。
      （owner 解析已提前到短路之前，短路分支直接复用该 owner，避免二次查询。）
    - 回填逻辑与 `withdraw_project` **共用** `_refill_cart_from_project`（口径不漂移），
      同键行**覆盖**而非累加（ADR-042 §1）。
    - 单事务：回填成功 → `p.cartRefilled = True` + OpLog（`重新提交（回填购物车）`）→ commit。

    返回 `{ok, alreadyRefilled, restored, amountFallback, skipped, skippedReasons,
    mode, forced, cleared, owner, rows}`（前 6 个字段为 ADR-027 原结构，ADR-042 加性扩展）。
    `owner = {id, username, name}` 供前端判断「回填对象是否当前登录者」。
    """
    # ADR-042 §2：mode 校验前置（写操作之前；缺省/空白按 merge 处理，保持旧调用兼容）
    mode = (mode or "").strip().lower() or "merge"
    if mode not in REFILL_MODES:
        raise HTTPException(400, "非法的回填模式")
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "销售项目不存在")
    if p.status != "terminated":
        raise HTTPException(400, "仅已终止的项目可重新提交")
    if user.role == "viewer" and not user_sees_project(user, p):
        raise HTTPException(403, "生态人员仅可重新提交自己下单的项目")
    # ADR-043（REFILL-20261022-B4）：商务（editor）禁用「重新提交」——回填目标恒为下单人，
    # 商务操作后自身购物车无变化，只会造成"提示成功但什么也没发生"的误解。
    # 合法路径：通知下单人本人重新提交，或由 admin 代操作。守卫置于任何写操作之前。
    if user.role == "editor":
        raise HTTPException(403, "商务人员不可使用「重新提交」，请通知下单人本人操作")
    # ADR-042 补遗2：owner 解析**提前**到幂等短路之前——`replace` 的「仅限本人」守卫必须先拿到
    # 目标账号才能判定；守卫顺序固定为：项目存在(404) → 已终止(400) → viewer 权限(403) →
    # **editor 业务级拒绝(403，ADR-043)** → 下单账号存在(400) → **replace 仅限本人(400)** →
    # 幂等短路（位置不得再调整）。
    owner = _withdraw_owner(db, p)
    if owner is None:
        raise HTTPException(400, "下单账号不存在，无法回填购物车")
    target_user_id = str(owner.id)  # cart_items.userId 存 users.id 字符串（ADR-009）
    if mode == "replace" and target_user_id != str(user.id):
        # ADR-042 补遗2：`replace` 会清空**回填目标**（下单人）购物车——代操作（admin/其他商务）
        # 时目标为他人 → 跨用户清空，不可接受。守卫置于任何写操作之前（此刻一行未删）。
        raise HTTPException(400, "只能对本人购物车执行『清空后回填』，他人项目请使用合并")
    if p.cartRefilled and mode == "merge":
        # 已回填过：直接告知前端「明细已在购物车」，绝不重复回填（避免行数翻倍）
        # ADR-042 §2：仅 merge 短路；replace 是用户显式「清空重建」，必须继续执行
        return {
            "ok": True,
            "alreadyRefilled": True,
            "restored": 0,
            "amountFallback": 0,
            "skipped": 0,
            "skippedReasons": [],
            "mode": mode,
            "forced": False,
            "cleared": 0,
            "owner": _refill_owner_brief(owner),
            "rows": [],
        }

    refill = _refill_cart_from_project(db, p, target_user_id, mode=mode)
    # BUG-15：仅全部成功才置幂等标记；有跳过行时保持 False，允许再次点「重新提交」重试
    # （ADR-042：replace 有跳过行时同样保持 False，允许重试）
    p.cartRefilled = (refill["skipped"] == 0)
    detail = (f"{refill['restored']} 行明细已回填购物车"
              f"（原价回填 {refill['amountFallback']} 行，跳过 {refill['skipped']} 行）")
    if mode == "replace":
        # ADR-042 §2：仅 replace 追加模式信息（merge 保持原文案，避免噪声）
        detail += f"（mode=replace，清空原有 {refill['cleared']} 行）"
    detail += f"，由下单人 {owner.username} 购物车改单后重新提交"
    add_log(db, "project", p.name, "重新提交（回填购物车）", detail, operator=user.username,
            project_id=p.id)
    db.commit()
    return {
        "ok": True,
        "alreadyRefilled": False,
        "restored": refill["restored"],
        "amountFallback": refill["amountFallback"],
        "skipped": refill["skipped"],
        "skippedReasons": refill["skippedReasons"],
        "mode": mode,
        "forced": (mode == "replace"),
        "cleared": refill["cleared"],
        "owner": _refill_owner_brief(owner),
        "rows": refill["rows"],
    }


def _normalize_contracts(db: Session, data: schemas.ProjectInput,
                         enforce_max: bool = True) -> list[tuple[str, list[schemas.ProjectItemInput], Decimal, str]]:
    """归一化合同结构（ADR-007）→ [(customer, items, contractAmount, remark), ...]。

    两种入参都支持（向后兼容）：
    - 传 contracts：按合同建项目（每客户一个合同）；
    - 不传（仅 items）：按**单合同**自动包装，customer 取项目 customer 字段，
      contractAmount 缺省=该组明细 amount 合计。
    返回的 contractAmount 为 Decimal（元口径，ADR-006），缺省时按明细计价合计：
    amount 模式=Σ 权威 amount（整数元，ADR-008），unit 模式=Σ price×qty。
    ADR-037 §3（FORMS-20261022）：`enforce_max` 透传给 `_rs_row_amount`
    （viewer 只校验下限，上限放开；editor/admin 双向不变）。
    """
    def _item_total(it: schemas.ProjectItemInput) -> Decimal:
        # ADR-011：遥感明细行金额与 _create_project_core 落库同源（_rs_row_amount），
        # 否则 Σ 明细与合同金额校验会与落库值不一致
        if it.itemId:
            rs = db.get(models.RsItem, it.itemId)
            if rs is not None:
                return _rs_row_amount(get_asset(db, it.assetId), rs, it.amount,
                                      enforce_max=enforce_max)
        a = get_asset(db, it.assetId)
        if a is not None and _is_amount_mode(a):
            return _validate_amount_yuan(it.amount)
        return (_dec(it.price) * it.qty).quantize(CENT)

    def _contract_total(items: list[schemas.ProjectItemInput]) -> Decimal:
        return sum((_item_total(it) for it in items), Decimal("0")).quantize(CENT)

    if data.contracts:
        out = []
        for c in data.contracts:
            total = _contract_total(c.items)
            # 0 / 未传 = 「未填写」，合同金额按 Σ 明细派生（沿用前端 contractAmount 只读展示口径）
            explicit = _dec(c.contractAmount) if c.contractAmount is not None else Decimal("0")
            if explicit > 0:
                # BUG-18 / ADR-029 §2：金额不变量——客户端显式传入的合同金额必须等于 Σ 明细金额，
                # 不一致直接 400（此前直接覆盖，pending 期报表与审批依据失真）
                amt = explicit.quantize(CENT)
                if amt != total:
                    raise HTTPException(400, "合同金额与明细合计不一致")
            else:
                amt = total
            out.append((c.customer, c.items, amt, c.remark))
        return out
    # 兼容路径：items 自动包装为单合同（合同金额 = Σ 明细，派生口径）
    return [(data.customer, data.items, _contract_total(data.items), "")]


def _rs_row_amount(asset: models.Asset | None, rs: models.RsItem, amount_in,
                   enforce_max: bool = True) -> Decimal:
    """遥感明细行**权威金额**（唯一实现，_create_project_core 与合同金额校验共用）：

    - 显式传入 > 0 的金额：采信并过该明细自身参考区间（ADR-018 §5 / ADR-021，超限 400）；
    - 未传 / 0 / 非法：按明细挂牌价 rs.price 成交（ADR-011）。
    WHY 需要「0 视为未传」：手动建单入参 `amount` 必填（前端未填时为 0），
    若把 0 当折扣金额会把明细行金额错误落成 0 元。
    ADR-037 §3（FORMS-20261022）：`enforce_max` 透传给 `_check_discount_range`
    （viewer 只校验下限，上限放开；editor/admin 双向不变）。
    """
    try:
        amt_in = _dec(amount_in) if amount_in is not None else None
    except (TypeError, ValueError):
        amt_in = None
    if amt_in is not None and amt_in > 0:
        amt = _check_discount_range(asset, 1, amount_in,
                                    unit=asset.unit if asset is not None else "", rs=rs,
                                    enforce_max=enforce_max)
        if amt is not None:
            return amt.quantize(CENT)
    return _dec(rs.price).quantize(CENT)


def _item_repeat(db: Session, asset: models.Asset | None,
                 item_id: int | None) -> bool:
    """ADR-011：明细行（itemId 非空）以 rs_items.repeatSale 为权威（父产品 repeatSale 无意义）；
    非明细行用产品 repeatSale。"""
    if item_id:
        rs = db.get(models.RsItem, item_id)
        if rs is not None:
            return rs.repeatSale
    return asset.repeatSale if asset else True


def _validate_rs_item_ref(db: Session, it: schemas.ProjectItemInput,
                          seen: set[int] | None = None) -> models.RsItem | None:
    """ADR-011：含 itemId 的明细行统一校验（三个下单入口共用）：
    明细存在且归属 assetId；qty 强制 1。返回 RsItem（无 itemId 返回 None）。

    RS-STATUS-20261022 §3.2：**售罄护栏改为读明细状态**（替换上一版基于 join 的占用检查）——
    `repeatSale == False` 且 `status == 'all_sold'` → 400「该可售明细已售罄，请选择其他明细」。
    状态由 `_sync_rs_item_status` 在占用变化点维护（下单锁定即置 all_sold），
    故「同一条单次售卖明细被卖第二次」在 SQL 层就被拦住。
    `repeatSale == True`（可重复售卖）永不售罄，不校验，只计次不扣量。

    同一请求内重复选同一条单次售卖明细：本请求的明细行尚未落库、状态检查看不见，
    由调用方传入本请求已选用的 id 集合 `seen` 拦截（否则跨销售记录选同一明细会被卖两次：
    `lockedQty` +2 而可售只减 1 条）。
    检查与调用方同处一个事务（checkout 已是单事务 + `apply_item_lock` 条件更新，
    SQLite 单写者），不引入新的读-改-写竞态。
    """
    if not it.itemId:
        return None
    rs = db.get(models.RsItem, it.itemId)
    if rs is None or rs.assetId != it.assetId:
        raise HTTPException(400, "遥感数据明细不存在或不属于该产品")
    if it.qty != 1:
        raise HTTPException(400, "遥感数据明细行数量固定为 1")
    if not rs.repeatSale:
        if rs.status == "all_sold":
            raise HTTPException(400, "该可售明细已售罄，请选择其他明细")
        if seen is not None:
            if rs.id in seen:
                raise HTTPException(400, "同一条单次售卖明细不可在同一订单中重复下单，请选择其他明细")
            seen.add(rs.id)
    return rs


def _create_project_core(db: Session, data: schemas.ProjectInput,
                         operator: str = "", initial_status: str = "pending",
                         enforce_max: bool = True) -> models.Project:
    """建项目核心（不提交）：归一化合同 → 逐合同校验同主体 → 按 assetId 聚合校验数量
    → 生成项目（状态 = initial_status）+ 合同（HT-xxxx）+ 明细（挂 contractId）→ 锁定。

    ADR-037 §3（FORMS-20261022）：`enforce_max` = 参考区间**上限是否生效**——
    viewer（生态人员）结算传 False（只校验下限，上限放开）；editor/admin 入口默认 True
    （双向校验不变）。透传至 `_normalize_contracts` / `_rs_row_amount` / `_item_pricing`，
    与改价入口（PUT/PATCH /cart/{id}）复用同一校验函数（`_check_discount_range` /
    `_check_unit_price_range`），禁止复制第二套规则。

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
    contracts_in = _normalize_contracts(db, data, enforce_max=enforce_max)
    # FIX-20261020-#13b：任一合同 customer 为空 → 400（前端有校验，API 直调兜底）
    for customer, _items, _amt, _remark in contracts_in:
        if not (customer or "").strip():
            raise HTTPException(400, "请为每份销售记录填写客户")
    # BUG-19 服务层兜底（contracts 的 UNIQUE(projectId, customer) 因 ADR-016 冲突不建，
    # 见 main._ensure_unique_indexes 与 database.md）：
    # ① 同一项目内「客户 + 明细集合」完全重复 → 400（防构造重复销售记录）；
    # ② 同一销售记录内 (assetId, itemId) 重复 → 400（DB 唯一索引 uq_project_items_key 的友好前置）。
    seen_contracts: set[tuple] = set()
    for customer, items, _amt, _remark in contracts_in:
        ckey = ((customer or "").strip(),
                tuple(sorted(((it.assetId or 0), (it.itemId or 0)) for it in items)))
        if ckey in seen_contracts:
            raise HTTPException(400, f"客户「{(customer or '').strip()}」下相同的销售明细不可重复建记录")
        seen_contracts.add(ckey)
        line_keys = [((it.assetId or 0), (it.itemId or 0)) for it in items]
        if len(set(line_keys)) != len(line_keys):
            raise HTTPException(400, "同一销售记录中同一产品（含明细）不可重复，请合并为一行")
    # ---------------- 唯一权威校验链（BUG-08 / BUG-16 / BUG-05，ADR-029 §1）----------------
    # 固定顺序：① 明细存在性 → ② 明细归属/qty → ③ 服务期限 → ④ 参考区间/金额
    #           → ⑤ 按 assetId 聚合数量。所有建单入口（购物车结算 / 手动建单 / 重新提交）
    # 必经此处，禁止在入口层重复实现（复制即漂移）。
    # （原「③ 折扣率」一步已随 NO-DISCOUNT-20261022 / ADR-039 删除：入参 discountRate 不校验）
    rs_map: dict[int, models.RsItem] = {}
    service_map: dict[int, tuple[str | None, str | None]] = {}
    # RS-STATUS-20261022：本请求内已选用的「单次售卖」明细 id（售罄护栏的第二道：同请求重复选）。
    # WHY 需要单独记：售罄检查读的是明细 `status`，而本请求的明细行尚未落库、状态也还没重算；
    # 同一条单次售卖明细若出现在两个销售记录里（同客户会被 ① 的 seen_contracts 拦下，
    # 不同客户则不拦），会绕过售罄护栏被卖两次（lockedQty +2 而可售只减 1 条 → 两个口径打架）。
    single_sale_seen: set[int] = set()
    for _customer, items, _amt, _remark in contracts_in:
        for it in items:
            # ① 明细存在性（BUG-16）：非空 assetId 必须指向真实产品——
            # 否则可造出「确认后能交付、但无交付单/无销量/无数量变动」的幽灵明细
            if it.assetId:
                a = get_asset(db, it.assetId)
                if a is None:
                    raise HTTPException(400, "所选产品不存在或已删除")
                # ② FIX-20261020-#13c：遥感父产品（容器）不可直接购买——
                # 容器明细行（itemId 非空，指向 rs_items）放行，只拦父产品本身
                if not it.itemId and a.type == "遥感数据":
                    raise HTTPException(400, "遥感数据容器不可直接购买，请购买其数据明细")
            # ② 明细归属 / qty=1（ADR-011）+ 售罄护栏（RS-STATUS-20261022）
            rs = _validate_rs_item_ref(db, it, seen=single_sale_seen)
            if rs is not None:
                rs_map[it.itemId] = rs
            # ③ 折扣率：**已下线**（NO-DISCOUNT-20261022 / ADR-039）——入参 `it.discountRate`
            # 容忍但忽略（不校验、不 400、不落库；旧客户端仍可传）
            # ④ 服务期限（ADR-020：YYYY-MM-DD 且 start ≤ end，否则 400）
            service_map[id(it)] = _validate_service_period(it.serviceStart, it.serviceEnd)
    # ADR-013：移除「记录内同主体」校验（一资产一记录天然单主体；手动建单可混合主体成一条记录）
    # ⑥ 数量：先整体校验、再统一加锁（H1），且必须**按 assetId 聚合**全项目（跨合同）需求（H10）
    # WHY：同一项目可能含多条引用同一 assetId 的明细（如 qty 各 1、可售仅 1），逐条按"全量可售"
    # 校验会全部通过，合计却超卖/超锁；故先汇总该产品在本单的 qty 合计再比较可售。
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
            # BUG-05：进入 demand 的行都是**占用数量**的行，故按 repeat_override=False 校验——
            # 父产品 repeatSale=true 不得短路明细行（明细 repeatSale=false 仍须受可售约束）
            _validate_item_stock(asset, total_qty, repeat_override=False)
    # BUG-28：项目日期入参统一校验（允许空串；只校验写入值）
    expected_sign = _validate_date_str(data.expectedSignDate, "预计签订日期", allow_empty=True)
    last_follow = _validate_date_str(data.lastFollowDate, "最后跟进日期", allow_empty=True)
    # 建项目（customer/subject/expectedAmount 建完合同后由 _recompute_project 派生落库）
    project = models.Project(
        name=data.name, customer=data.customer, industry=data.industry, rep=data.rep,
        # 下单账号（登录 username）：生态人员「仅可见自己下单的项目」的可见性判定依据
        creator=operator,
        businessOwner=data.businessOwner,  # 商务负责人（可选，默认 ""）
        subject="", status=initial_status,  # 契约 3：不采信请求体 status；ADR-012 修订：所有入口默认 pending（待审核）
        expectedAmount=0, quoteAmount=data.quoteAmount,
        contractAmount=0, paidAmount=data.paidAmount,
        expectedSignDate=expected_sign, lastFollowDate=last_follow,
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
            # ⑤ 计价分支（与 _normalize_contracts 的 Σ 口径同源，否则合同金额校验会误报）：
            # - ADR-011 明细行：金额 = 明细挂牌价（或显式>0 的折扣金额，过明细区间）→ _rs_row_amount
            # - ADR-008 amount 模式：amount 权威（整数元）+ price 派生
            # - unit 模式：price×qty 后端权威重算 + 单价过产品参考区间（_item_pricing）
            if rs is not None:
                amount_dec = _rs_row_amount(asset, rs, it.amount, enforce_max=enforce_max)
                price = _derived_price(amount_dec, 1)
                amount = float(amount_dec)
            else:
                price, amount = _item_pricing(asset, it, enforce_max=enforce_max)
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
            # ADR-020：服务期限取校验链④的结果（不重复校验，避免两套口径）
            service_start, service_end = service_map.get(
                id(it), (None, None))
            project.items.append(models.ProjectItem(
                contractId=contract.id,
                assetId=it.assetId, qty=it.qty, unit=asset.unit if asset else "",
                price=price, amount=amount,
                origPrice=orig_price, origAmount=orig_amount,  # ADR-018 §2：原价快照
                serviceStart=service_start, serviceEnd=service_end,  # ADR-020：服务期限
                # NO-DISCOUNT-20261022 / ADR-039：折扣率已下线——**一律写 null**（不读前端值，
                # 旧客户端传了也忽略）；列保留，历史单的历史值不动、可追溯
                discountRate=None,
                status=status, deliveryReq=it.deliveryReq,
                itemId=it.itemId,  # ADR-011：遥感明细行落库（非明细行 NULL）
                # 契约 2：落「下单时刻是否真实加锁」事实（repeatSale/明细 repeatSale 下单不加锁）
                locked=bool(asset is not None and not eff_repeat),
                lockedDate=today() if status == "locked" else "",
                confirmedDate="", shippedDate="",
            ))
            total_item_count += 1
            # RS-STATUS-20261022（ADR-038 Decision 3）：明细占用状态紧跟「下单锁定」按真值重算
            #（被占用 → all_sold；repeatSale=true → 永不售罄，保持 in_stock）。
            # WHY 必须在本行 append **且 flush 之后**：重算查的是库里的真值（project_items ⋈ contracts），
            # 明细行还没落库时会被判成「未被占用」→ 刚锁定的单次售卖明细被错误置回 in_stock
            #（表现为下单后 availableCount 不降、同一明细还能被再卖一次）。
            if rs is not None:
                db.flush()
                _sync_rs_item_status(db, rs.id)
    # 项目派生字段落库：status/customer/subject/expectedAmount=Σ合同（ADR-007）
    _recompute_project(project)
    add_log(db, "project", project.name, "新增项目",
            f"创建销售项目 {project.code}，销售记录 {len(contracts_in)} 条，关联产品 {total_item_count} 项",
            operator=operator, project_id=project.id)
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
            # BUG-10 / ADR-033 §3：取消 `min(quantity, ...)` 静默夹断——超卖属不变量破缺，
            # 显式失败并写审计告警（夹断会把错误钉在边界上、事后无告警）
            if a.shippedQty + it.qty > a.quantity:
                _invariant_violation(
                    db,
                    f"{a.name} 交付后已交付数量将超过产品总数"
                    f"（总数 {a.quantity}{a.unit}，已交付 {a.shippedQty}{a.unit}，本次 {it.qty}{a.unit}，"
                    f"合同明细 #{it.id}）",
                    asset=a, operator=operator,
                )
            a.shippedQty = a.shippedQty + it.qty
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
    # RS-STATUS-20261022：交付后明细仍被有效合同引用 → 状态保持 all_sold（幂等重算，
    # 兼作自愈：若上游漏调/历史数据把状态写歪，交付动作会把它纠回真值）
    _sync_rs_item_status(db, it.itemId)


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
        # RS-STATUS-20261022：释放后该明细不再被占用 → 重算状态（合同已 terminated 时回 in_stock）。
        # 注：驳回场景合同状态在本循环之后才写（c.status = "terminated"），故 review_project
        # 批量结束后还有一次 `_sync_rs_item_statuses` 兜底（见该处注释）。
        _sync_rs_item_status(db, it.itemId)
        return True
    return False


def _derive_project_status(p: models.Project) -> str:
    """项目状态派生（ADR-007；ADR-019 §3 扩展，PRICING-20261020 新增 delivering）：

    | 合同状态集合 | 项目状态 |
    |---|---|
    | 全 pending | pending（待审核） |
    | 全 delivered | delivered（已完成） |
    | ⊆ {delivered, terminated} 且含 delivered（BUG-17：已交付 + 剩余作废） | delivered（已完成） |
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
    # BUG-17 / ADR-032 §5：{delivered} 与 {delivered, terminated} 均判「已完成」
    # （已交付的部分作废，项目不再显示「进行中」，也不再让项目级接口永久 400）
    if statuses <= {"delivered", "terminated"} and "delivered" in statuses:
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


def _delivery_blocker(c: models.Contract) -> str | None:
    """交付前置条件（BUG-03 / ADR-032 §1）——**唯一判定**，合同级与项目级批量共用。

    返回不合规原因（None = 可交付）：
    - 合同必须已进入 delivering（即已录签订时间）：`signedDate` 非空；
    - 不得存在 `pending_asset` 明细（未关联产品的明细交付后永久悬挂）；
    - 已 delivered 的合同视为无阻断（幂等：core 对 from_status == status 直接返回）。
    """
    if c.status == "delivered":
        return None
    if c.status != "delivering" or not c.signedDate:
        return "尚未录入签订时间，不可交付"
    pending = [it for it in c.items if it.status == "pending_asset"]
    if pending:
        return f"尚有 {len(pending)} 项明细未关联产品，无法交付完成"
    return None


def _claim_contract_status(db: Session, c: models.Contract, from_status: str, to_status: str) -> None:
    """状态变更「认领」——条件更新（BUG-10 / ADR-033 §2）。

    `UPDATE contracts SET status=:new WHERE id=:id AND status=:old`：
    并发重复交付/终止时，后到者影响 0 行 → 400「状态已变更，请刷新后重试」，
    不会重复扣量、重复生成交付单、重复累计销售额。
    先认领再执行副作用：任一步失败整体回滚（单事务），不会留下半截状态。
    """
    from sqlalchemy import text as _sql
    res = db.execute(
        _sql("UPDATE contracts SET status = :new, updatedAt = :ts "
             "WHERE id = :id AND status = :old"),
        {"new": to_status, "old": from_status, "id": c.id, "ts": today()},
    )
    if res.rowcount == 0:
        raise HTTPException(400, "状态已变更，请刷新后重试")
    db.expire(c)  # 让会话中的合同对象重新读取（后续 _recompute_project 读 status）


def _outbound_of_item(db: Session, contract_id: int | None,
                      it: models.ProjectItem) -> models.Outbound | None:
    """定位某条已交付明细对应的 done 交付记录（BUG-04：终止时按明细逐个撤销交付）。

    优先 projectItemId 精确匹配（FIX-20261020-#7）；存量记录回退 contractId + assetId。
    """
    if it.id is not None:
        ob = db.execute(
            select(models.Outbound)
            .where(models.Outbound.projectItemId == it.id,
                   models.Outbound.status == "done")
            .order_by(models.Outbound.id.desc())
        ).scalars().first()
        if ob is not None:
            return ob
    if contract_id is not None and it.assetId is not None:
        return db.execute(
            select(models.Outbound)
            .where(models.Outbound.contractId == contract_id,
                   models.Outbound.assetId == it.assetId,
                   models.Outbound.status == "done")
            .order_by(models.Outbound.id.desc())
        ).scalars().first()
    return None


def _revert_item_quantities(db: Session, it: models.ProjectItem, reason: str,
                            operator: str = "") -> None:
    """明细级数量/金额回退（无交付单可撤销时的兜底，BUG-04）。

    仅用于「明细已 shipped 但找不到 done 交付记录」的存量不一致数据——
    按明细自身的 qty/amount 反向回退，并留一条告警日志（不允许静默跳过）。
    """
    a = get_asset(db, it.assetId)
    if a is None:
        return
    eff_repeat = _item_repeat(db, a, it.itemId)
    if not eff_repeat:
        if a.shippedQty < it.qty:
            _invariant_violation(
                db, f"{a.name} 已交付数量 {a.shippedQty}{a.unit} 不足以回退 {it.qty}{a.unit}"
                    f"（明细 #{it.id}）", asset=a, operator=operator)
        a.shippedQty = a.shippedQty - it.qty
    if a.soldCount < 1:
        _invariant_violation(
            db, f"{a.name} 累计售卖次数为 0，无法回退明细 #{it.id} 的售卖次数",
            asset=a, operator=operator)
    a.soldCount = a.soldCount - 1
    a.soldAmount = float(_dec(a.soldAmount) - _dec(it.amount))
    refresh_status(a)
    add_flow(db, a.id, "manual_adjust", -it.qty, a.unit, -it.amount, today(), f"ITEM-{it.id}",
             f"交付回退（缺交付单，按明细回退）：{reason}", operator=operator)
    add_log(db, "asset", a.name, "交付回退（缺交付单）",
            f"明细 #{it.id} 无对应交付记录，已按明细直接回退 {it.qty}{a.unit} / "
            f"{_fmt_amount_yuan(it.amount)}（原因：{reason}）", asset_id=a.id, operator=operator)


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
            # BUG-33 / api-contracts §1：权限类失败统一 403（此前 400）
            raise HTTPException(403, "生态人员仅可终止销售记录（交付需商务人员/管理员操作）")
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
    # ADR-019：active→delivered 守卫**已下沉到 `_change_contract_status_core`（BUG-03/ADR-032 §1）**，
    # 合同级与项目级批量共用同一道守卫，此处不再重复实现（避免两套口径）
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
                f"商务负责人 {old} → {target}", operator=user.username, project_id=p.id)
        db.commit()
        return "转交订单"
    add_log(db, "project", p.name, "接手订单",
            f"商务负责人绑定为 {target}", operator=user.username, project_id=p.id)
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
    NO-DISCOUNT-20261022 / ADR-039：**折扣率已下线**——审核改价只写 price/amount/service，
    既不读入参 discountRate、也**不回写** `ProjectItem.discountRate`（存量历史快照原值保留）；
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
            # BUG-33 / api-contracts §1：权限类失败统一 403（此前 400）
            raise HTTPException(403,
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
        # RS-STATUS-20261022：驳回 = 全部明细释放 → 状态必须回 in_stock。
        # 上面循环里 `_apply_item_release` 的重算读到的合同状态仍是 pending（本循环之后才置
        # terminated），故此处 flush 后再统一重算一次（冗余自愈，杜绝「驳回后明细仍售罄」）。
        db.flush()
        _sync_rs_item_statuses(
            db, [it.itemId for c in contracts for it in c.items])
        _recompute_project(p)
        add_log(db, "project", p.name, "驳回订单",
                f"项目 {p.code} 订单已驳回：{reason}（锁定已释放）", operator=operator,
                project_id=p.id)
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
                diffs.append(f"{name} 销售金额 {_fmt_money(old_amount)} → {_fmt_money(it.amount)} 元")
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
                diffs.append(f"{name} 销售金额 {_fmt_money(old_amount)} → {_fmt_money(it.amount)} 元")
            else:
                if ri.price is None:
                    continue
                if ri.price <= 0:
                    raise HTTPException(400, "单价须大于 0")
                it.price = float(ri.price)
                it.amount = float((_dec(ri.price) * it.qty).quantize(CENT))
                # ADR-018 §4：不再回写 assets.salePrice（orig 快照永不触碰）
                name = a.name if a else f"产品 #{it.assetId}"
                diffs.append(f"{name} 单价 {_fmt_money(old_price)} → {_fmt_money(it.price)} 元")
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
    # ADR-020：confirm 可改服务期限（只写 ProjectItem，格式/顺序校验）
    # FIX-20261022（api-contracts §3）：语义改为「**未传 = 保持原值；显式 null = 清空**」
    # （与 PUT /cart/{id} 的 UNSET 哨兵口径一致）——此前把 null 当"未传"，前端「清空日期」无效。
    for c in contracts:
        for it in c.items:
            ri = by_id.get(it.id)
            if ri is None:
                continue
            provided = ri.model_fields_set
            if "serviceStart" not in provided and "serviceEnd" not in provided:
                continue
            new_start = ri.serviceStart if "serviceStart" in provided else it.serviceStart
            new_end = ri.serviceEnd if "serviceEnd" in provided else it.serviceEnd
            # 只传一边时与存量另一边组合校验（防改一边造成 start > end）
            new_start, new_end = _validate_service_period(new_start, new_end)
            it.serviceStart, it.serviceEnd = new_start, new_end
    for c in contracts:
        c.status = "active"
        c.updatedAt = today()
    _recompute_project(p)
    add_log(db, "project", p.name, "确认下单",
            f"项目 {p.code} 订单已确认" + (f"，改价：{'；'.join(diffs)}" if diffs else ""),
            operator=operator, project_id=p.id)
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
    - 生态人员（viewer）：**一律 403**（ADR-028，2026-10-21）——订单提交即冻结，
      改单唯一路径是「撤销」（POST /projects/{id}/withdraw）→ 明细回填购物车 → 重新下单；
      系统无草稿态（POST /projects 直接生成 pending），故「提交后禁编辑」等价于「viewer 禁止编辑」，
      不按状态/归属做条件分支（原「viewer 可编辑自己下单项目」分支已收回）。
    - 商务/管理员规则**不变**：pending 仅商务负责人（或 admin 越过）可编辑基本信息；
      存在 delivered 合同 / 派生 terminated 不可编辑；项目名称非空。
    """
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    # ADR-028 §1：生态人员无编辑权（404 优先于 403；不看状态与归属，服务层一处收口）
    if user is not None and user.role == "viewer":
        raise HTTPException(403, "订单已提交，不可编辑；如需修改请「撤销」后重新下单")
    # ADR-012 §5.1：pending 项目基本信息仅负责人（或 admin 越过）可编辑
    #（ADR-028：viewer 已在上面一律 403，此处判定实际只对商务生效）
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
    # ADR-028 §1：原「rep 字段对 viewer 忽略」特判已删除——viewer 编辑权整体收回（上方一律 403），
    # 该特判作为编辑权的子约束成为死代码
    for k in ("name", "industry", "remark"):
        setattr(p, k, getattr(data, k))
    # BUG-43：编辑侧 rep 同样走 _normalize_rep（与建单侧一致，避免账号/姓名混存复发——
    # rep 还是存量单 viewer 可见性的回退依据）
    p.rep = _normalize_rep(db, data.rep)
    # BUG-28：日期入参统一校验（YYYY-MM-DD，允许空串；只校验写入值）
    p.expectedSignDate = _validate_date_str(data.expectedSignDate, "预计签订日期", allow_empty=True)
    p.lastFollowDate = _validate_date_str(data.lastFollowDate, "最后跟进日期", allow_empty=True)
    p.updatedAt = today()
    add_log(db, "project", p.name, "编辑", "更新销售项目", operator=operator, project_id=p.id)
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
        if status == "delivered":
            # BUG-03 / ADR-032 §2：**全量或全不**——先收集全部不合规合同，一次性 400 列出
            #（编号 + 原因），不做「能交付几条算几条」的部分执行。
            blockers = []
            for c in targets:
                why = _delivery_blocker(c)
                if why:
                    blockers.append(f"{c.code} {why}")
            if blockers:
                raise HTTPException(
                    400, "以下销售记录不满足交付条件，请先补齐后重试：" + "；".join(blockers))
        for c in targets:
            # 复用合同级核心（不提交），单事务收敛（H8）
            _change_contract_status_core(db, c, status, reason, operator=operator)
        # RS-STATUS-20261022：批量动作结束后对相关明细统一 flush + 重算（幂等冗余）——
        # 逐条路径已各自重算，这里兜底覆盖「合同状态由 ORM 属性延迟写入」等顺序差异，
        # 保证一次批量终止/交付后所有明细状态都等于真值（无遗漏点）。
        db.flush()
        _sync_rs_item_statuses(db, [it.itemId for c in targets for it in c.items])
        add_log(db, "project", p.name, "状态变更",
                f"项目批量{('交付' if status == 'delivered' else '终止')}：名下 {len(targets)} 条销售记录已执行",
                operator=operator, project_id=p.id)
        db.commit()
        return
    # 存量兼容：无合同项目走旧的项目级明细逻辑
    _legacy_change_project_status(db, p, status, reason, operator=operator)
    db.commit()


def _change_contract_status_core(db: Session, c: models.Contract, status: str,
                                 reason: str = "", operator: str = "") -> None:
    """合同状态变更核心（不提交）：**唯一变更入口**，合同级与项目级批量共用（H8 / ADR-032）。

    - delivered 前置条件（BUG-03）：`from_status == delivering` 且 `signedDate` 非空、
      无 `pending_asset` 明细——下沉到此处后**任何入口都绕不过**（此前守卫只写在
      `change_contract_status`，项目级批量直调 core 绕过了 ADR-019）；
    - terminated 回滚（BUG-04）：按**明细实际状态**处理，不再按合同 from_status 二选一——
      `shipped` → 撤销该明细对应交付（回退 shippedQty/soldCount/soldAmount、交付单置 reverted）；
      `locked/confirmed` → 释放锁定；产品已删 / 明细缺失 → **400**（不允许静默成功零回滚）；
    - 状态变更一律**条件更新**（BUG-10 / ADR-033 §2），并发冲突 → 400「状态已变更，请刷新后重试」。
    """
    p = get_project(db, c.projectId)
    from_status = c.status
    if status == from_status:
        return
    if status == "delivered":
        blocker = _delivery_blocker(c)
        if blocker:
            raise HTTPException(400, f"合同 {c.code} {blocker}")
        _claim_contract_status(db, c, from_status, status)
        for it in c.items:
            # H4：locked/confirmed 均处理（含零价 amount=0 明细），不再因金额为 0 被跳过
            if it.status in ("confirmed", "locked"):
                _apply_item_delivery(
                    db, it, operator=operator, ref=c.code,
                    remark=f"销售记录「{c.code}」交付完成自动生成",
                    customer=c.customer, contract_id=c.id, project=p,
                )
        _recompute_project(p)
        add_log(db, "project", p.name, "销售记录状态变更",
                f"销售记录 {c.code}（客户 {c.customer}）交付完成，已生成交付记录并累计销售金额",
                contract_id=c.id, operator=operator, project_id=p.id)
    elif status == "terminated":
        # ---- 前置校验（全量或全不，先校验后写）----
        # BUG-04：已交付明细的产品必须仍存在，否则无法回退数量（不允许「静默成功、零回滚」）
        shipped_items = [it for it in c.items if it.status == "shipped"]
        missing = [
            f"明细 #{it.id}" for it in shipped_items
            if it.assetId is None or get_asset(db, it.assetId) is None
        ]
        if missing:
            raise HTTPException(
                400,
                "该产品/明细已不存在，无法回滚交付，请先联系管理员（" + "；".join(missing) + "）",
            )
        _claim_contract_status(db, c, from_status, status)
        released = 0
        reverted = 0
        for it in c.items:
            if it.status == "shipped":
                # shipped → 撤销该明细对应交付（回退 shippedQty/soldCount/soldAmount，交付单置 reverted）
                ob = _outbound_of_item(db, c.id, it)
                if ob is not None:
                    _revert_outbound_inner(db, ob.id, f"销售记录终止（{c.code}）",
                                           operator=operator, restore_contract=False)
                    reverted += 1
                else:
                    # 存量数据不一致（明细已交付但无交付单）：按明细回退并留告警，不静默跳过
                    _revert_item_quantities(db, it, f"销售记录终止（{c.code}）", operator=operator)
                it.status = "released"
            elif it.status in ("locked", "confirmed"):
                # locked/confirmed → 释放锁定（仅 it.locked 真实加锁过才写 cancel_release）
                if _apply_item_release(db, it, operator=operator, ref=c.code,
                                       contract_id=c.id):
                    released += 1
        _recompute_project(p)
        add_log(db, "project", p.name, "销售记录状态变更",
                f"销售记录 {c.code}（客户 {c.customer}）终止：释放锁定 {released} 项，撤销交付 {reverted} 条"
                + (f"，原因：{reason}" if reason else ""),
                contract_id=c.id, operator=operator, project_id=p.id)


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
                operator=operator, project_id=p.id)

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
            + (f"，原因：{reason}" if reason else ""), operator=operator, project_id=p.id)


def delete_project(db: Session, project_id: int, operator: str = "") -> None:
    """删除项目（ADR-007 起，合同级联）：先按合同回滚——
    active 合同释放锁定、delivered 合同撤销名下 done 交付（回退 shippedQty/soldCount/soldAmount）
    → FIX-2：再撤销挂项目的手动交付（contractId == null 的 done 交付）
    → 再硬删项目及其合同、明细（cascade）→ 写 OpLog。
    存量无合同项目沿用旧逻辑（_terminate_project，其全量撤销已含手动交付）。
    单事务，任一步失败整体回滚（H8）。
    ADR-028 §3（2026-10-21）：**撤销单不可删除**——`status == "terminated" and cartRefilled`
    → 403，先校验后写（保持单事务语义，不产生半截回滚）。
    复用 cartRefilled 作为撤销留痕标记而不新增列：语义由「购物车已回填」扩为
    「该终止单已产生回填/撤销留痕」，恰好覆盖「已撤销单不得删除」；不新增列即无迁移，
    避免为一次权限收紧引入 schema 变更（ADR-028 Decision 3）。被驳回且从未回填的终态项目仍可清理。
    """
    p = get_project(db, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    # ADR-028 §3：撤销留痕硬护栏（校验置于任何写操作之前）
    if p.status == "terminated" and p.cartRefilled:
        raise HTTPException(403, "该订单已撤销（或已回填购物车）并将保留历史记录，不可删除")
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
    # RS-STATUS-20261022：项目删除 = 相关明细全部失去占用 → 状态必须回 in_stock。
    # 先取 itemId（删除后明细行进入 deleted 态不可再读属性），删除 + flush 后再重算，
    # 否则真值查询仍能看到「待删的 project_items/contracts」而把明细错误留在 all_sold。
    deleted_item_ids = [it.itemId for it in p.items if it.itemId]
    db.delete(p)  # 级联删除合同 + 明细（cascade delete-orphan）
    add_log(db, "project", name, "删除", f"删除项目 {code}（已回滚锁定与交付）",
            operator=operator, project_id=project_id)
    db.flush()
    _sync_rs_item_statuses(db, deleted_item_ids)
    # ADR-041 补遗1（FLOW-20261022-B2）：SQLite 无 AUTOINCREMENT，项目 id 会被复用——
    # 删除后把本项目全部日志的外键置空（日志文本/targetName 全部保留，审计不丢），
    # 否则旧日志会挂到未来复用同一 id 的新项目「流转过程」里（实测已发生）。
    # ⚠️ 执行时机：必须在本项目**所有**日志（含上面最后那条「删除」）写入之后——若把本 UPDATE
    # 放在 db.delete(p) 之前，那条「删除」日志是在 UPDATE 之后 INSERT 的，会保留旧 projectId，
    # 新项目复用同一 id 时仍会串台（本任务实测：置空 3 条、残留「删除」1 条，B 的流转过程里
    # 出现「删除项目 SP-…」）；放在 commit 前 + db.flush() 后 → 全部置空。
    # 副作用：这些日志对 viewer 变为不可见（Visibility.log_visible 遇 projectId IS NULL 过滤），
    # 但项目已删除、viewer 本就无法到达，可接受。
    # 事务性质（H8）不变：仍是同一事务，任一步失败整体回滚（UPDATE 与删除同事务）。
    db.execute(
        update(models.OpLog)
        .where(models.OpLog.projectId == project_id)
        .values(projectId=None)
    )
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
    # FIX-20261020-#9 / BUG-45：遥感父产品（容器）不可直接交付——只能对其数据明细交付
    #（OutboundInput 无 itemId，任何挂容器的交付都属「父产品交付」，一律 400 明确拒绝）
    if a.type == "遥感数据":
        raise HTTPException(400, "遥感容器不可直接交付，请交付其数据明细")
    # BUG-28：交付日期入参统一校验（YYYY-MM-DD，允许空串；只校验写入值）
    _validate_date_str(data.date, "交付日期", allow_empty=True)
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
            # BUG-10：取消 `min(quantity, ...)` 静默夹断——超卖属不变量破缺，显式失败并告警。
            if a.shippedQty + data.qty > a.quantity:
                _invariant_violation(
                    db,
                    f"{a.name} 本次交付后已交付数量将超过产品总数"
                    f"（总数 {a.quantity}{a.unit}，已交付 {a.shippedQty}{a.unit}，本次 {data.qty}{a.unit}）",
                    asset=a, operator=operator)
            a.shippedQty = a.shippedQty + data.qty
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
            + ("（不扣减数量）" if data.mode == "history" else ""), operator=operator,
            project_id=p.id if p is not None else None)
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
    # BUG-14 / ADR-032 §3：产品已删（或合同交付的明细已缺失）时**不允许静默成功**——
    # 此前 `if a:` 直接跳过整段回退、仅写一条「已撤销」日志并返回 200，
    # 合同永久卡在 delivered、销量残留且无修出口。
    if a is None:
        raise HTTPException(400, "该产品/明细已不存在，无法回滚交付，请先联系管理员")
    if ob.mode != "history" and ob.contractId is not None:
        item_ref = None
        if ob.projectItemId is not None:
            item_ref = db.get(models.ProjectItem, ob.projectItemId)
        if item_ref is None:
            item_ref = db.execute(
                select(models.ProjectItem).where(
                    models.ProjectItem.contractId == ob.contractId,
                    models.ProjectItem.assetId == ob.assetId,
                ).limit(1)
            ).scalars().first()
        if item_ref is None:
            raise HTTPException(400, "该产品/明细已不存在，无法回滚交付，请先联系管理员")
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
            # BUG-10 / ADR-033 §3：取消 max(0,...) 静默夹断——已交付数量不足以回退属不变量破缺
            if a.shippedQty < ob.qty:
                _invariant_violation(
                    db,
                    f"{a.name} 已交付数量 {a.shippedQty}{a.unit} 不足以撤销交付 {ob.code}"
                    f"（{ob.qty}{a.unit}）", asset=a, operator=operator)
            a.shippedQty = a.shippedQty - ob.qty
        # FIX-3 + 口径统一：创建侧（合同交付 _apply_item_delivery / 手动交付 create_outbound）
        # 现均一律 soldCount+1（交付=一次销售，历史补录除外）→ 撤销一律 -1。
        # BUG-10：取消 max(0, …) 夹断——累计售卖次数为 0 时回退属不变量破缺，显式告警。
        if a.soldCount < 1:
            _invariant_violation(
                db, f"{a.name} 累计售卖次数为 0，无法撤销交付 {ob.code} 的售卖次数",
                asset=a, operator=operator)
        a.soldCount = a.soldCount - 1
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
            # REVERT-FIX-20261022（DEFECT-1）：**必须先 flush 再调 apply_item_lock**。
            # WHY：上面刚刚改的 shippedQty / soldCount / soldAmount 还挂在 session 里没落库
            # （session 为 autoflush=False），而 apply_item_lock 内部会 `db.refresh(a)`——
            # refresh 会 expire 实例并重新读库，把「未 flush 的待写值」直接丢弃（不是延迟，
            # 而是永久丢失），表现为撤销交付后 shippedQty 残留、销量/销售额不回退；
            # 同时它的条件更新 `quantity-lockedQty-shippedQty>=q` 读到的也是库里的旧
            # shippedQty（数量=1 的产品甚至会误判 400「可用数量不足」）。
            # 因此先落库（同一事务内，不改变原子性），再做条件加锁，两处口径才一致。
            db.flush()
            if it.locked and not eff_repeat:
                # 交付时释放过锁定（仅 it.locked 为真才释放过）→ 反向重新加锁
                apply_item_lock(db, it.assetId, it.qty, True, ob.code,
                                operator=operator, contract_id=ob.contractId,
                                repeat_override=eff_repeat)
            it.status = "locked"
            it.shippedDate = ""
            # RS-STATUS-20261022：明细回到 locked（仍被该合同占用）→ 状态重算后仍是 all_sold；
            # 冗余重算的意义是把「撤销交付不会让明细变回可售」写成显式事实（防后续改动误置 in_stock）
            _sync_rs_item_status(db, it.itemId)
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
            operator=operator, contract_id=ob.contractId, project_id=ob.projectId)
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
# 资产主体（ADR-035，ENTITIES-20261022）
# ============================================================
def _validate_entity_fields(name: str, short: str) -> tuple[str, str]:
    """trim 后校验：name 2–64 字、short 1–32 字（400）。返回 (name, short)。"""
    name = (name or "").strip()
    short = (short or "").strip()
    if not (2 <= len(name) <= 64):
        raise HTTPException(400, "主体名称须为 2–64 个字符")
    if not (1 <= len(short) <= 32):
        raise HTTPException(400, "主体简称须为 1–32 个字符")
    return name, short


def list_entities(db: Session) -> list[models.Entity]:
    return db.execute(
        select(models.Entity).order_by(models.Entity.createdAt.asc(), models.Entity.id.asc())
    ).scalars().all()


def add_entity(db: Session, data: schemas.EntityInput, operator: str = "") -> models.Entity:
    name, short = _validate_entity_fields(data.name, data.short)
    dup = db.execute(select(models.Entity).where(models.Entity.name == name)).scalars().first()
    if dup:
        raise HTTPException(400, "主体已存在")
    now = now_str()
    e = models.Entity(name=name, short=short, createdAt=now, updatedAt=now)
    db.add(e)
    add_log(db, "setting", name, "新增主体", f"新增资产主体「{name}」（简称 {short}）",
            operator=operator)
    db.commit()
    return e


def update_entity(db: Session, entity_id: int, data: schemas.EntityInput,
                  operator: str = "") -> models.Entity:
    e = db.get(models.Entity, entity_id)
    if not e:
        raise HTTPException(404, "主体不存在")
    name, short = _validate_entity_fields(data.name, data.short)
    old_name = e.name
    if name != old_name:
        dup = db.execute(
            select(models.Entity).where(models.Entity.name == name,
                                        models.Entity.id != entity_id)
        ).scalars().first()
        if dup:
            raise HTTPException(400, "主体已存在")
    e.name, e.short, e.updatedAt = name, short, now_str()
    if name != old_name:
        # ADR-035：改名只留痕、**不回写** assets.subject（存量产品主体仍为旧全称，
        # 前端弹窗二次确认提示需逐个产品手动改选）
        add_log(db, "setting", name, "修改主体", f"主体名称 {old_name} → {name}",
                operator=operator)
    db.commit()
    return e


def delete_entity(db: Session, entity_id: int, operator: str = "") -> None:
    e = db.get(models.Entity, entity_id)
    if not e:
        raise HTTPException(404, "主体不存在")
    # H7 口径：SQLite 无外键，引用完整性由服务层校验（同 delete_base/delete_asset 风格）
    ref_cnt = db.execute(
        select(func.count()).select_from(models.Asset).where(models.Asset.subject == e.name)
    ).scalar() or 0
    if ref_cnt > 0:
        raise HTTPException(400, f"该主体下存在 {ref_cnt} 个产品，不可删除")
    add_log(db, "setting", e.name, "删除主体", f"删除资产主体「{e.name}」", operator=operator)
    db.delete(e)
    db.commit()


# ============================================================
# 产品交付物（ADR-024：模板体系下线，实例完全手动添加，不再惰性生成）
# ============================================================
DELIVERABLE_URL_MAX = 512


def _normalize_deliverable_url(raw: str | None) -> str:
    """ADR-044：交付物外链归一化与校验。

    规则：允许空（=无链接）；否则必须 http:// 或 https:// 开头、长度 ≤512。
    WHY 白名单：该字段会被渲染为可点击 <a>，javascript:/data: 等伪协议等于存储型 XSS 入口，
    不能只靠前端校验（curl 可绕过）。
    """
    u = (raw or "").strip()
    if not u:
        return ""
    low = u.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        raise HTTPException(400, "链接地址必须以 http:// 或 https:// 开头")
    if len(u) > DELIVERABLE_URL_MAX:
        raise HTTPException(400, f"链接地址过长（最多 {DELIVERABLE_URL_MAX} 字符）")
    return u


def add_asset_deliverable(db: Session, asset_id: int, data: schemas.AssetDeliverableInput) -> None:
    a = get_asset(db, asset_id)
    if a:
        a.deliverables.append(models.AssetDeliverable(
            asset_id=asset_id, name=data.name, category=data.category, required=data.required,
            note=data.note, version="V1.0", meta=data.note,
            status="todo" if "验收" in data.name else "ready",
            url=_normalize_deliverable_url(data.url), updatedAt=today(),
        ))
        # WHY：此前遗漏 asset_id，导致前端产品详情「操作记录」按 l.assetId === assetId 过滤时
        # 看不到这条「新增交付物」记录；与 update/remove_asset_deliverable 对齐补上 assetId。
        add_log(db, "asset", a.name, "新增交付物", f"新增交付物「{data.name}」", asset_id=a.id)
        db.commit()


def update_asset_deliverable(db: Session, asset_id: int, item_id: int, patch: dict) -> None:
    d = db.get(models.AssetDeliverable, item_id)
    a = get_asset(db, asset_id)
    if d and d.asset_id == asset_id:
        # ADR-044：外链先归一（strip + 协议白名单 + 长度），放在任何 setattr 之前——
        # 非法值直接 400，不产生"改一半"的脏会话。exclude_unset 语义不变：
        # 未传 url = 不动；传 ""/null = 清空（统一归一为空串）。
        if "url" in patch:
            patch["url"] = _normalize_deliverable_url(patch["url"])
        file_change = ""
        if "file" in patch:
            # ADR-024：单文件附件——空串/null 归一为 NULL（清空附件）
            new_file = patch["file"] or None
            if (d.file or None) != new_file:
                # 与产品文件字段同格式：散列名 → 原始名（如「附件: → 说明书.pdf」）
                file_change = f"附件: {_arrow(_file_display_name(db, d.file or ""), new_file or "")}"
                d.file = new_file
        for k in ("name", "category", "required", "note", "version", "meta", "status", "url"):
            if k in patch:
                setattr(d, k, patch[k])
        d.updatedAt = today()
        if a:
            add_log(db, "asset", a.name, "更新交付物", f"{d.name} 已更新（{d.version}）",
                    asset_id=a.id, changes=file_change)
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
    """可用数量（可重复售卖产品由调用处先判 repeatSale，不参与上限校验）。

    注：此处的 `max(0, ...)` 仅用于**展示文案**（把负可售显示为 0），不参与任何写路径的
    夹断——真正的数量变更走 `apply_item_lock` 的原子条件 UPDATE 与显式不变量校验
    （BUG-10 / ADR-033 §3：静默夹断会把错误钉在边界上且事后无告警）。
    """
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


# ADR-042 §1：同键行处理策略白名单
# - accumulate（默认，加购口径零变化）：同键行 qty 累加；
# - replace（回填/upsert 口径）：同键行 qty/amount/服务期限**覆盖**为本次值，不新增行、不累加。
CART_EXISTING_POLICIES = ("accumulate", "replace")


def _cart_add_inner(db: Session, data: schemas.CartItemInput, user_id: str = DEFAULT_USER, *,
                    existing_policy: str = "accumulate") -> models.CartItem:
    """加购核心（**不提交**，供 add_to_cart / add_to_cart_batch / 回填复用，批量可收敛为单一事务）。

    `existing_policy`（ADR-042 §1，关键字参数）：
    - `"accumulate"`（默认）：命中同键行 → **累加** qty（`POST /cart` 加购语义，零变化）；
    - `"replace"`：命中同键行 → **覆盖** qty / amount / serviceStart / serviceEnd（`updatedAt`
      刷新），不新增行、不累加——供 `_refill_cart_from_project` 使用，使回填/重试天然幂等。
    非法取值 → 400（内部函数同样防御）。可售/区间/客户校验对两种策略**同等生效**
    （replace 的净增按「本次值 − 原值」计，避免覆盖式回填被存量行误判超可售）。
    """
    if existing_policy not in CART_EXISTING_POLICIES:
        raise HTTPException(400, "非法的购物车重复行处理策略")
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
    if existing_policy == "replace":
        # ADR-042 §1：覆盖语义下同键行的净增 = 本次值 − 原值（覆盖后总量 = 合计 − cur + qty），
        # 否则「购物车已有 1 行 qty=1 + 回填 1 行 qty=1」会被误判为 2 > 可售 1 而拒回填
        delta = qty - cur
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
    # NO-DISCOUNT-20261022 / ADR-039：入参 `data.discountRate` **容忍但忽略**（不校验、不 400、不落库）；
    # 新行 discountRate 落 null，已有行的历史值保持原值不动（历史快照可查）
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
        if existing_policy == "replace":
            # ADR-042 §1：同键覆盖——qty/amount/服务期限一律取本次值（含 amount=None 的原价成交），
            # 不新增行、不累加（重试不再翻倍）
            existing.qty = qty
            existing.amount = amount
            existing.serviceStart, existing.serviceEnd = service_start, service_end
        else:
            # 明细行 qty 恒 1：重复加购幂等合并（不累加）；普通行累加
            existing.qty = 1 if rs is not None else cur + qty
            if amount is not None:
                existing.amount = amount
            # ADR-020：服务期限（本次传了才覆盖，未传保持原值）
            if service_start is not None or service_end is not None:
                existing.serviceStart, existing.serviceEnd = service_start, service_end
        # NO-DISCOUNT-20261022 / ADR-039：**不动** existing.discountRate
        #（历史快照保留，既不清空也不覆盖）
        existing.updatedAt = now_str()
    else:
        existing = models.CartItem(
            userId=user_id, assetId=data.assetId, customer=customer, qty=qty,
            amount=amount, itemId=data.itemId,
            serviceStart=service_start, serviceEnd=service_end,  # ADR-020：服务期限
            # NO-DISCOUNT-20261022 / ADR-039：折扣率已下线，新行恒 null
            discountRate=None,
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
                    amount=UNSET,
                    service_start=UNSET, service_end=UNSET,
                    viewer: bool = False) -> models.CartItem:
    """修改购物车行级客户（ADR-007）；可选携带合同金额（ADR-008）、服务期限（ADR-020）。

    ADR-037 §3（FORMS-20261022）：`viewer`（生态人员）行金额只校验参考区间**下限**
    （上限放开），与 PUT /cart/{id} / checkout 复用同一校验函数。

    **PATCH 语义（CART-PATCH-20261021）**：任一字段「未传（UNSET）= 保持原值不改」，
    显式传 null = 清空。修复「改客户时金额/服务期限被清空」。

    金额语义（ADR-018 §3，PRICING-20261020）：
    - unit / 遥感明细行：amount 传入即采信（过参考区间校验，超限 400）；显式 null = 清空；
    - amount 模式行：整数元权威（不传保持原值，结算时必填兜底不变）。
    折扣率（NO-DISCOUNT-20261022 / ADR-039）：**已下线**——入参 `discountRate` 由路由层
    直接丢弃（不入参本函数），`cart_items.discountRate` 保持原值不动（历史快照，不覆盖不清空）。
    目标 (userId, assetId, customer) 已存在其它行时 400（避免静默合并产生歧义，前端可先删除原行）。"""
    c = db.get(models.CartItem, cart_id)
    if not c or c.userId != user_id:
        raise HTTPException(404, "购物车项不存在")
    a = get_asset(db, c.assetId)
    is_discount_row = c.itemId is not None or (a is not None and not _is_amount_mode(a))
    # ADR-021（RSITEM-RANGE-20261020）：遥感明细行区间取该 rs_item 自身（不再取父产品容器区间）
    rs = db.get(models.RsItem, c.itemId) if c.itemId is not None else None
    # ADR-037 §3（FORMS-20261022）：viewer 只校验下限（上限放开）；editor/admin 双向
    enforce_max = not viewer
    # 行级金额（ADR-008 / ADR-018 §3）
    if amount is not UNSET:
        if amount is None:
            if is_discount_row:
                c.amount = None  # 显式 null = 清空折扣金额；amount 模式忽略
        elif is_discount_row:
            amt = _check_discount_range(a, c.qty, amount, unit=a.unit if a else "", rs=rs,
                                        enforce_max=enforce_max)
            c.amount = float(amt)
        else:
            amt = _cart_amount(a, amount)
            if amt is not None:
                c.amount = amt
    # ADR-020（PRICING-20261020）：服务期限（格式/顺序校验，start ≤ end 否则 400）
    if service_start is not UNSET or service_end is not UNSET:
        new_start, new_end = _validate_service_period(
            service_start if service_start is not UNSET and service_start is not None else c.serviceStart,
            service_end if service_end is not UNSET and service_end is not None else c.serviceEnd)
        c.serviceStart, c.serviceEnd = new_start, new_end
    # NO-DISCOUNT-20261022 / ADR-039：折扣率不再读写（c.discountRate 保持原值不动）
    if amount is not UNSET or service_start is not UNSET or service_end is not UNSET:
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
        # NO-DISCOUNT-20261022 / ADR-039：批量加购同样不读 `it.discountRate`（忽略）
        _cart_add_inner(db, schemas.CartItemInput(assetId=it.assetId, qty=qty, customer=customer,
                                                  amount=it.amount, itemId=it.itemId), user_id)
        added += 1
    db.commit()
    return {
        "addedCount": added,
        "skipped": skipped,
        "cart": [schemas.CartItemOut.model_validate(c).model_dump() for c in _cart_list(db, user_id)],
    }


def set_cart_qty(db: Session, cart_id: int, qty: int, user_id: str = DEFAULT_USER,
                 amount=UNSET,
                 service_start=UNSET, service_end=UNSET,
                 viewer: bool = False) -> models.CartItem:
    """PUT /cart/{id}：改数量；可选携带合同金额（ADR-008）、服务期限（ADR-020）。

    ADR-037 §3（FORMS-20261022）：`viewer`（生态人员）行金额只校验参考区间**下限**
    （上限放开），与 checkout 权威链复用同一校验函数（`_check_discount_range`）。
    NO-DISCOUNT-20261022 / ADR-039：入参 `discountRate` **已下线**——路由层不读取、本函数
    无该入参；`cart_items.discountRate` 列保留且**保持原值不动**（历史快照，不清空不覆盖）。

    **PATCH 语义（CART-PATCH-20261021）**：任一字段「未传（UNSET）= 保持原值不改」，
    显式传 null = 清空；只有 qty 必传。此前「未传 amount 即清空」导致填金额后
    选服务期限/改数量/改客户金额被抹掉（用户反馈 2026-10-21）。

    金额语义（ADR-018 §3，PRICING-20261020）：
    - unit / 遥感明细行：amount 传入即采信（过参考区间校验，超限 400）；显式 null = 清空（原价成交）；
    - amount 模式行：整数元权威（不传保持原值）。
    折扣率语义（NO-DISCOUNT-20261022 / ADR-039）：**已下线**——入参 `discountRate` 容忍但忽略
    （不校验、不 400、不落库），`cart_items.discountRate` 保持原值不动。
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
    old_qty = c.qty
    c.qty = int(qty)
    # 行级金额（ADR-008 / ADR-018 §3，PRICING-20261020）：改数量后按新 qty 重做区间校验
    is_discount_row = c.itemId is not None or (a is not None and not _is_amount_mode(a))
    # ADR-021（RSITEM-RANGE-20261020）：遥感明细行区间取该 rs_item 自身（不再取父产品容器区间）
    rs = db.get(models.RsItem, c.itemId) if c.itemId is not None else None
    # ADR-037 §3（FORMS-20261022）：viewer 只校验下限（上限放开）；editor/admin 双向
    enforce_max = not viewer
    if amount is not UNSET:
        if amount is None:
            if is_discount_row:
                c.amount = None  # 显式 null = 清空折扣金额（原价成交）；amount 模式忽略
        elif is_discount_row:
            amt = _check_discount_range(a, c.qty, amount, unit=a.unit if a else "", rs=rs,
                                        enforce_max=enforce_max)
            c.amount = float(amt)
        else:
            amt = _cart_amount(a, amount)
            if amt is not None:
                c.amount = amt
    # ADR-020（PRICING-20261020）：服务期限（格式/顺序校验，start ≤ end 否则 400）
    if service_start is not UNSET or service_end is not UNSET:
        new_start, new_end = _validate_service_period(
            service_start if service_start is not UNSET and service_start is not None else c.serviceStart,
            service_end if service_end is not UNSET and service_end is not None else c.serviceEnd)
        c.serviceStart, c.serviceEnd = new_start, new_end
    # NO-DISCOUNT-20261022 / ADR-039：折扣率不再读写——路由层不读 `data.discountRate`，
    # 本函数不写 `c.discountRate`（存量值保持原值不动，历史快照可查；不做数据清洗）
    # CART-PATCH-20261021：仅「数量真的变化」且未传 amount、该行无折扣率时，清空手工折扣金额
    # （旧总量对新数量已失真；有折扣率的行由前端按 rate 重算并显式提交 amount）。
    # 服务期限/客户等不改数量的部分更新不再触发清空（修复用户反馈的金额被抹掉问题）
    # 注：此处的 `c.discountRate is None` 读的是**存量历史列**（非本次入参）——
    # ADR-039 明确「不改金额口径」，故该分支语义保持原样（存量带 rate 的行仍不清空金额）。
    if amount is UNSET and is_discount_row and c.qty != old_qty and c.discountRate is None:
        c.amount = None
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


IDEMPOTENCY_TTL_SECONDS = 24 * 3600


def _idempotency_fresh(ts: str) -> bool:
    """幂等记录是否仍在保留期（24h，ADR-033 §1）。时间戳格式同 now_str「YYYY-MM-DD HH:MM」。"""
    try:
        created = datetime.strptime(ts or "", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return False
    return (datetime.now() - created).total_seconds() < IDEMPOTENCY_TTL_SECONDS


def _checkout_idempotent_hit(db: Session, user_id: str, request_id: str) -> models.Project | None:
    """`(userId, requestId)` 命中且未过期 → 返回首次创建的项目（幂等复用）。"""
    rec = db.execute(
        select(models.IdempotencyRecord).where(
            models.IdempotencyRecord.userId == user_id,
            models.IdempotencyRecord.scope == "checkout",
            models.IdempotencyRecord.requestId == request_id,
        )
    ).scalar_one_or_none()
    if rec is None or not rec.projectId:
        return None
    if not _idempotency_fresh(rec.createdAt):
        return None  # 过期：按新请求处理（下方会覆盖该记录）
    return get_project(db, rec.projectId)


def checkout(db: Session, data: schemas.CheckoutInput, user_id: str = DEFAULT_USER,
             operator: str = "", viewer: bool = False) -> tuple[models.Project, bool]:
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
    ADR-037 §3（FORMS-20261022）：区间校验分角色——viewer（`viewer=True`）行金额
    只校验参考区间下限（上限放开，加价成交允许）；editor/admin 双向不变。
    NO-DISCOUNT-20261022 / ADR-039：折扣率已下线——购物车行的历史 `discountRate`
    **不读、不校验、不落库**（新 `project_items.discountRate` 恒 null，存量单历史值不动）。
    ADR-013：不再校验同主体（记录粒度=单资产，天然单主体；同客户多主体=多条记录并列）。

    BUG-10 / ADR-033 §1：可选 `requestId` 幂等——
    `(userId, requestId)` 唯一记录，24h 内重复请求**返回首次生成的项目**（idempotent=True），
    不重复建单/锁量/清购物车。返回 `(project, idempotent)`。
    """
    # ---- 幂等（BUG-10）：先查已完成的同键请求，命中即直接返回首次项目 ----
    request_id = (data.requestId or "").strip()
    if len(request_id) > 64:
        raise HTTPException(400, "请求标识过长（requestId 最多 64 字符）")
    if request_id:
        hit = _checkout_idempotent_hit(db, user_id, request_id)
        if hit is not None:
            return hit, True
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
    # 按 (产品, 客户) 分组（保持购物车行序）；七元组
    # (产品, 数量, 权威金额, itemId, 行级客户, serviceStart, serviceEnd)
    # 明细行 qty 恒 1（ADR-011）；ADR-022 后 amount 恒非空且为合法整数元（上方必填校验保证）
    # ADR-037 §3（FORMS-20261022）：区间校验分角色——viewer 只校验下限（上限放开），
    # editor/admin 双向；角色取当前登录用户（路由层传 viewer），与改价入口同函数
    enforce_max = not viewer
    # ADR-018 §3（PRICING-20261020）：unit/遥感行金额 checkout 时再过一次区间校验
    #（行更新时已校验，此处防绕过行更新接口直接改库/旧客户端）
    # NO-DISCOUNT-20261022 / ADR-039：**不再带 discountRate**（购物车列的历史值也不再透传；
    # 新生成明细由 `_create_project_core` 统一写 null）
    # ADR-016（FIX-20261020-#3）：分组键由 assetId 单键升级为 (assetId, customer)——
    # 同产品多客户行不再被静默合并为一条记录（客户归属/金额串账），与前端预览口径一致
    groups: dict[tuple[int, str], list[tuple[models.Asset, int, Decimal, int | None, str,
                                            str | None, str | None]]] = {}
    for c in cart:
        a = get_asset(db, c.assetId)
        customer = (c.customer or "").strip()
        if c.itemId is not None:
            rs = db.get(models.RsItem, c.itemId)
            # ADR-018 §5：遥感明细行折扣金额采信（过区间校验）；
            # ADR-021（RSITEM-RANGE-20261020）：区间取该 rs_item 自身（不再取父产品容器区间）
            amt = _check_discount_range(a, 1, c.amount, unit=a.unit, rs=rs,
                                        enforce_max=enforce_max)
            groups.setdefault((c.assetId, customer), []).append(
                (a, 1, amt, c.itemId, customer, c.serviceStart, c.serviceEnd))
            continue
        if _is_amount_mode(a):
            amt = _validate_amount_yuan(c.amount)  # 整数元校验（必填校验已过，幂等兜底）
        else:
            # ADR-018 §3：unit 行折扣金额采信（过区间校验）
            amt = _check_discount_range(a, c.qty, c.amount, unit=a.unit,
                                        enforce_max=enforce_max)
        groups.setdefault((c.assetId, customer), []).append(
            (a, c.qty, amt, None, customer, c.serviceStart, c.serviceEnd))
    # 每组（产品×客户）→ 一条销售记录（ADR-016：一资产一客户一记录，customer 取分组键）
    # 计价（明细行=明细 price 权威 / amount 模式=权威金额 / unit 模式 price×qty）
    contracts_in: list[schemas.ContractInput] = []
    for (_asset_id, _customer), rows in groups.items():
        items: list[schemas.ProjectItemInput] = []
        total = Decimal("0")
        for a, qty, amt, item_id, _cust, s_start, s_end in rows:
            # ADR-022（REQUIRED-20261024）：amt 经上方必填校验恒非空（> 0 整数元）——
            # 「留空=原价成交」兜底已删除（unit 行 salePrice×qty / 遥感行明细 price 分支作废）
            price = _derived_price(amt, qty)  # 派生展示值（遥感明细行 qty 恒 1）
            amount = amt.quantize(CENT)  # 元口径，Decimal 精确到分
            total += amount
            items.append(schemas.ProjectItemInput(
                assetId=a.id, qty=qty, price=price, amount=float(amount),
                deliveryReq=data.deliveryReq, itemId=item_id,
                serviceStart=s_start, serviceEnd=s_end,  # ADR-020：服务期限透传
                # NO-DISCOUNT-20261022 / ADR-039：不传 discountRate（_create_project_core 写 null）
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
        # BUG-28：日期入参统一校验（YYYY-MM-DD，允许空串）；空则落今天
        expectedSignDate=(_validate_date_str(data.expectedSignDate, "预计签订日期", allow_empty=True)
                          or today()),
        lastFollowDate=today(),
        remark=data.remark,
        contracts=contracts_in,
    )
    # ---- 幂等占位（BUG-10 / ADR-033 §1）：先占 `(userId, requestId)`，再建单 ----
    # 并发重复提交时后到者 flush 触发唯一约束冲突 → 回滚并返回首次项目（或提示正在处理），
    # 绝不重复建单/锁量/清购物车。
    idem_rec = None
    if request_id:
        from sqlalchemy.exc import IntegrityError
        idem_rec = db.execute(
            select(models.IdempotencyRecord).where(
                models.IdempotencyRecord.userId == user_id,
                models.IdempotencyRecord.scope == "checkout",
                models.IdempotencyRecord.requestId == request_id,
            )
        ).scalar_one_or_none()
        if idem_rec is None:
            idem_rec = models.IdempotencyRecord(
                userId=user_id, scope="checkout", requestId=request_id,
                projectId=None, createdAt=now_str())
            db.add(idem_rec)
        else:
            idem_rec.projectId = None
            idem_rec.createdAt = now_str()
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            hit = _checkout_idempotent_hit(db, user_id, request_id)
            if hit is not None:
                return hit, True
            raise HTTPException(400, "该请求正在处理中，请稍后刷新查看结果")
    # H8：建项目（含合同/明细/锁定）→ 清空购物车 收敛为同一事务
    # ADR-012 修订（2026-10-19）：所有角色结算统一进「待审核」（pending），商务接手审核（改价/驳回）后生效
    project = _create_project_core(db, project_input, operator=operator,
                                   initial_status="pending", enforce_max=enforce_max)
    _clear_cart(db, user_id)
    if idem_rec is not None:
        idem_rec.projectId = project.id
    db.commit()
    db.refresh(project)
    return project, False


def create_sale_order(db: Session, data: schemas.SaleOrderInput,
                      operator: str = "") -> models.Project:
    """⚠️ **已无调用方（FIX-20261022 / ADR-029 §3）**：`POST /sales/order` 现直接返回 410 Gone，
    本函数仅作为历史实现保留，**新代码禁止调用**（唯一下单链路 = `POST /cart/checkout`）。

    产品直接下单：items 按产品分组拆销售记录（ADR-013，不再校验同主体），
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
    viewer 的 projects/contracts/outbounds/flows/logs/files 统一走 **Visibility 判定**
    （BUG-02 / BUG-13，ADR-030）——与 `GET /files/{name}`、`GET /assets/{id}/flows`
    等分页端点共用同一实现，不再有第二套口径。"""
    vis = build_visibility(db, user)
    assets = db.execute(select(models.Asset).order_by(models.Asset.id.desc())).scalars().all()
    projects = db.execute(select(models.Project).order_by(models.Project.id.desc())).scalars().all()
    # ADR-007：合同（含 items，明细挂 contractId）
    contracts = db.execute(select(models.Contract).order_by(models.Contract.id.asc())).scalars().all()
    outbounds = db.execute(select(models.Outbound).order_by(models.Outbound.id.desc())).scalars().all()
    flows = db.execute(select(models.AssetFlow).order_by(models.AssetFlow.id.asc())).scalars().all()
    logs = db.execute(select(models.OpLog).order_by(models.OpLog.id.asc())).scalars().all()
    if vis.restricted:
        # 结构化外键过滤（ADR-030 §2：禁止 detail 文本正则 / 项目名匹配）
        projects = [p for p in projects if p.id in vis.project_ids]
        contracts = [c for c in contracts if c.id in vis.contract_ids]
        outbounds = [o for o in outbounds if o.id in vis.outbound_ids]
        flows = [f for f in flows if vis.flow_visible(f)]
        logs = [lg for lg in logs if vis.log_visible(lg)]

    def _bases(kind: str):
        return db.execute(select(models.BaseRecord).where(models.BaseRecord.kind == kind)
                          .order_by(models.BaseRecord.id.asc())).scalars().all()

    # CLEANUP-20261020：移除 reps（生态人员）快照字段
    suppliers, customers = _bases("suppliers"), _bases("customers")

    deliv_map: dict[int, list] = {}
    for a in assets:
        if a.deliverables:
            deliv_map[str(a.id)] = [schemas.AssetDeliverableOut.model_validate(d).model_dump() for d in a.deliverables]

    category_units = db.execute(select(models.CategoryUnit).order_by(models.CategoryUnit.id.asc())).scalars().all()
    # ADR-009：购物车按登录用户隔离——仅返回当前请求用户的行（不再用 DEFAULT_USER）
    cart = _cart_list(db, user_id)
    # 上传文件原名映射（BUG-02 / ADR-030 §3）：与 `GET /files/{name}` 共用同一可见性判定——
    # 被任一产品引用（公开）或本人上传 → 可见；孤儿文件对 viewer 不返回（避免枚举下载）。
    files = [
        f for f in db.execute(
            select(models.FileMeta).order_by(models.FileMeta.storedName.asc())
        ).scalars().all()
        if vis.file_visible(f.storedName)
    ]
    # ADR-011：遥感数据可售明细全量（读随 bootstrap 放行，前端 RsItemPicker/明细页签消费）
    rs_items = db.execute(select(models.RsItem).order_by(models.RsItem.id.asc())).scalars().all()
    # BUG-46 收尾（FIX-20261022-FOLLOWUP）：rsItems 输出 RsItemOutWithSold 形状（补派生 soldCount），
    # 前端抽屉「已售次数」不再回退产品级 asset.soldCount。soldCount 由 `_rs_item_sold_counts`
    # **一条聚合查询**批量算出（与 `GET /assets/{id}/rs-items` 同一实现，避免 N+1 / 两套口径）。
    rs_sold = _rs_item_sold_counts(db)  # item_ids=None → 全表明细一次 GROUP BY
    # RS-STATUS-20261022：`occupied` 派生字段已删除（ADR-038 Decision 3 起「是否可售」只认
    # `status` 一个口径，避免 occupied / status / availableCount 三套语义并存）。
    rs_items_out = []
    for r in rs_items:
        d = schemas.RsItemOut.model_validate(r).model_dump()  # 含 status（in_stock/all_sold）
        d["soldCount"] = rs_sold.get(r.id, 0)
        rs_items_out.append(schemas.RsItemOutWithSold.model_validate(d).model_dump())

    # ADR-035（ENTITIES-20261022）：资产主体清单全量下发（无角色过滤——主体非敏感商业数据；
    # 前端删除 types.ts::ENTITIES 常量后由 db.entities 提供下拉/简称映射）
    entities = list_entities(db)

    # RS-STATUS-20261022（ADR-038 Decision 3 修订）：容器「可售数量」= `COUNT(status='in_stock')`
    # （明细状态 in_stock=可售 / all_sold=已售罄，与外层产品状态同构）。只对容器
    # （type == RS_DATA_TYPE）派生，非容器保持 None（前端继续用 quantity-lockedQty-shippedQty，
    # 双口径不混）；聚合为全量 1 条查询、与 viewer 可见性无关（见 _rs_container_available_counts）。
    # 注：GET /assets 列表接口**不动**（契约范围仅 bootstrap.assets）。
    rs_available = _rs_container_available_counts(db, rs_items)
    assets_out = []
    for a in assets:
        d = schemas.AssetOut.model_validate(a).model_dump()
        if a.type == RS_DATA_TYPE:
            d["availableCount"] = rs_available.get(a.id, 0)  # 无明细容器 = 0 份可售
        assets_out.append(d)

    return {
        "assets": assets_out,
        "rsItems": rs_items_out,
        "entities": [schemas.EntityOut.model_validate(e).model_dump() for e in entities],
        "projects": [schemas.ProjectOut.model_validate(p).model_dump() for p in projects],
        "contracts": [schemas.ContractOut.model_validate(c).model_dump() for c in contracts],
        "outbounds": [schemas.OutboundOut.model_validate(o).model_dump() for o in outbounds],
        "suppliers": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in suppliers],
        "customers": [schemas.BaseRecordOut.model_validate(x).model_dump() for x in customers],
        "flows": [schemas.FlowOut.model_validate(f).model_dump() for f in flows],
        "logs": [schemas.LogOut.model_validate(l).model_dump() for l in logs],
        # ADR-024：模板快照字段已下线移除；assetDeliverables 行携带 file 字段
        "assetDeliverables": deliv_map,
        "categoryUnits": [schemas.CategoryUnitOut.model_validate(c).model_dump() for c in category_units],
        "cart": [schemas.CartItemOut.model_validate(c).model_dump() for c in cart],
        "files": [schemas.FileMetaOut.model_validate(f).model_dump() for f in files],
    }
