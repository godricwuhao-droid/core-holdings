"""种子数据（首次启动登记，来源：前端 seed.ts / 《产品情况.md》）

金额单位：元（ADR-006，2026-10-16 起库内金额一律存元；本文件数值已按元值给出，
即原万元口径数值 ×10000）。
"""

ASSETS = [
    # ================= 具身智能 =================
    {"code": "CH-EMB-001", "name": "智元机器人-G1", "board": "embodied", "type": "机器人",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 15, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 3006700, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2026-03-15", "expiryDate": "", "perpetual": True,
     "spec": "本体整机，可对外销售", "remark": "本体整机可售", "updatedAt": "2026-09-01"},
    {"code": "CH-EMB-002", "name": "智元机器人-X2", "board": "embodied", "type": "机器人",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 20, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 1205000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2026-03-15", "expiryDate": "", "perpetual": True,
     "spec": "本体整机，可对外销售", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-EMB-003", "name": "数采软件及设备接入", "board": "embodied", "type": "数采设备",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 7400000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2026-04-10", "expiryDate": "", "perpetual": True,
     "spec": "数采软件及设备接入（整套）", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-EMB-004", "name": "松延人形机器人M1-爪手V1.3", "board": "embodied", "type": "机器人",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 35, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 957100, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2026-05-20", "expiryDate": "", "perpetual": True,
     "spec": "人形机器人（二期）", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-EMB-005", "name": "具身智能数据采集全链路管理平台", "board": "embodied", "type": "平台软件",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 3200000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2026-05-20", "expiryDate": "", "perpetual": True,
     "spec": "数据采集全链路管理平台", "remark": "", "updatedAt": "2026-09-01"},

    # ================= 卫星 Token =================
    # ADR-008：卫星 Token 为包量计价（pricingMode='amount'，合同金额整数元权威；salePrice 仅参考值）
    # BUG-34（FIX-20261022）：单位统一为「个」（ADR-025；当前库 `unit like '%颗%'` 已为 0 条，
    # 此处修正只影响**空库重建**，不迁移存量库）。
    # 数量口径自洽：非 repeatSale 且 soldCount=1 ⇒ 必须有对应已交付口径（shippedQty=1，
    # 数量售罄时 status=all_sold）；repeatSale 不加 shippedQty（只计次不扣量）。
    {"code": "CH-SAT-001", "name": "宏大卫星（26年10月发射）", "board": "satellite", "type": "卫星Token",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "个", "quantity": 2, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 0, "soldAmount": 0, "soldCount": 0, "status": "in_stock", "pricingMode": "amount",
     "inboundDate": "2026-06-01", "expiryDate": "2028-10-31", "perpetual": False,
     "spec": "2 颗自持卫星 Token 服务", "remark": "26 年 10 月发射", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-002", "name": "46号卫星（Token服务）", "board": "satellite", "type": "卫星Token",
     "subject": "蜂云时代科技有限公司", "unit": "个", "quantity": 1, "lockedQty": 0, "shippedQty": 1, "repeatSale": False,
     "salePrice": 10000000, "soldAmount": 10000000, "soldCount": 1, "status": "all_sold", "pricingMode": "amount",
     "inboundDate": "2026-01-10", "expiryDate": "2026-12-01", "perpetual": False,
     "spec": "3 亿 Token，1000 万/3 亿 Token", "remark": "26 年已售 1000 万；服务期至 26 年 12 月", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-003", "name": "38号卫星（Token服务）", "board": "satellite", "type": "卫星Token",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "个", "quantity": 1, "lockedQty": 0, "shippedQty": 1, "repeatSale": False,
     "salePrice": 20000000, "soldAmount": 20000000, "soldCount": 1, "status": "all_sold", "pricingMode": "amount",
     "inboundDate": "2026-01-10", "expiryDate": "2029-06-30", "perpetual": False,
     "spec": "3 亿 Token，1000 万/3 亿 Token", "remark": "26 年已售 2000 万", "updatedAt": "2026-09-01"},

    # ================= 卫星数据（可重复售卖） =================
    {"code": "CH-SAT-004", "name": "宏大低轨卫星数据", "board": "satellite", "type": "卫星数据",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "轨", "quantity": 1000, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 25000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2026-06-15", "expiryDate": "", "perpetual": True,
     "spec": "低轨卫星遥感数据 1000 轨", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-005", "name": "中电云卫星数据", "board": "satellite", "type": "卫星数据",
     "subject": "蜂云时代科技有限公司", "unit": "轨", "quantity": 1000, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 24243, "soldAmount": 14023500, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-20", "expiryDate": "", "perpetual": True,
     "spec": "卫星数据 1000 轨", "remark": "可重复售卖；所得税 25%，需核算成本", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-006", "name": "大川海创卫星数据-电磁", "board": "satellite", "type": "卫星数据",
     "subject": "蜂云时代科技有限公司", "unit": "轨", "quantity": 200, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 24240, "soldAmount": 5246000, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-11-05", "expiryDate": "", "perpetual": True,
     "spec": "电磁数据 200 轨", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-007", "name": "大川海创卫星数据-遥感", "board": "satellite", "type": "卫星数据",
     "subject": "蜂云时代科技有限公司", "unit": "轨", "quantity": 350, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 24240, "soldAmount": 9180500, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-11-05", "expiryDate": "", "perpetual": True,
     "spec": "遥感数据 350 轨", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-008", "name": "城市部品数据资源（配景）", "board": "satellite", "type": "卫星数据",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "条", "quantity": 8385, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 2000, "soldAmount": 6515760, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-10-01", "expiryDate": "", "perpetual": True,
     "spec": "城市部品配景数据 8385 条", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-009", "name": "城市部品数据资源（材质）", "board": "satellite", "type": "卫星数据",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "条", "quantity": 3040, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 1500, "soldAmount": 4651200, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-10-01", "expiryDate": "", "perpetual": True,
     "spec": "城市部品材质数据 3040 条", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-010", "name": "低轨卫星监测数据", "board": "satellite", "type": "卫星数据",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "轨", "quantity": 500, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 35100, "soldAmount": 17732500, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-09-15", "expiryDate": "", "perpetual": True,
     "spec": "监测数据 500 轨", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-011", "name": "低轨卫星数据", "board": "satellite", "type": "卫星数据",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "轨", "quantity": 307, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 26800, "soldAmount": 8341800, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-09-15", "expiryDate": "", "perpetual": True,
     "spec": "低轨卫星数据 307 轨", "remark": "可重复售卖", "updatedAt": "2026-09-01"},
    {"code": "CH-SAT-012", "name": "德数交遥感数据", "board": "satellite", "type": "卫星数据",
     "subject": "蜂云时代科技有限公司", "unit": "期", "quantity": 16, "lockedQty": 0, "shippedQty": 0, "repeatSale": True,
     "salePrice": 3125000, "soldAmount": 50000000, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-08-20", "expiryDate": "", "perpetual": True,
     "spec": "16 期遥感数据（6 省份）", "remark": "可重复售卖", "updatedAt": "2026-09-01"},

    # ================= 算力服务（建设中，只读） =================
    {"code": "CH-CMP-001", "name": "雅安/肇庆算力服务器", "board": "compute", "type": "算力服务器",
     "subject": "蜂云时代科技有限公司", "unit": "台", "quantity": 266, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 0, "soldAmount": 460000000, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-06-01", "expiryDate": "2028-12-31", "perpetual": False,
     "spec": "算力服务器 266 台", "remark": "已售 4.6 亿服务，26 年算力运载及总盘已超负荷销售", "updatedAt": "2026-09-01"},
    {"code": "CH-CMP-002", "name": "广西贺州算力服务器", "board": "compute", "type": "算力服务器",
     "subject": "蜂云纪元科技(贺州)有限公司", "unit": "台", "quantity": 171, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 0, "soldAmount": 70000000, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-08-01", "expiryDate": "2028-08-31", "perpetual": False,
     "spec": "算力服务器 171 台", "remark": "已售 7000 万服务，26 年已超负荷销售；未销售 1.3 亿差额部分未收到发票", "updatedAt": "2026-09-01"},
    {"code": "CH-CMP-003", "name": "马鞍山算力服务器", "board": "compute", "type": "算力服务器",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "台", "quantity": 174, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 0, "soldAmount": 180000000, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-07-01", "expiryDate": "2028-07-31", "perpetual": False,
     "spec": "算力服务器 174 台", "remark": "已售 1.8 亿服务，差额部分抵减贸易利润，26 年已超负荷销售", "updatedAt": "2026-09-01"},

    # ================= 软件产品 =================
    {"code": "CH-SW-001", "name": "区县级优质资源共建共享平台", "board": "software", "type": "软件",
     "subject": "蜂云时代科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 102200, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-SW-002", "name": "面向具身智能的纯视觉人体动作捕捉系统", "board": "software", "type": "软件",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 5582500, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-SW-003", "name": "面向具身智能的三维物体生成系统", "board": "software", "type": "软件",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 5582500, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-SW-004", "name": "大语言知识模型服务系统", "board": "software", "type": "软件",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 3160000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-SW-005", "name": "青牛企业大数据分析平台V1.0", "board": "software", "type": "软件",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 5661000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-SW-006", "name": "电磁数据处理软件", "board": "software", "type": "软件",
     "subject": "四川蜂云星座人工智能科技有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 5100000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},
    {"code": "CH-SW-007", "name": "融合视讯云平台", "board": "software", "type": "软件",
     "subject": "蜂云纪元科技(贺州)有限公司", "unit": "套", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 7580000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-12-01", "expiryDate": "", "perpetual": True, "spec": "", "remark": "", "updatedAt": "2026-09-01"},

    # ================= 硬件产品 =================
    {"code": "CH-HW-001", "name": "星河AI算力集群", "board": "hardware", "type": "硬件集群",
     "subject": "安徽天枢智算人工智能科技有限公司", "unit": "集群", "quantity": 1, "lockedQty": 0, "shippedQty": 0, "repeatSale": False,
     "salePrice": 32560000, "soldAmount": 0, "soldCount": 0, "status": "in_stock",
     "inboundDate": "2025-11-10", "expiryDate": "", "perpetual": True,
     "spec": "AI 算力集群（整机柜交付）", "remark": "集群可售", "updatedAt": "2026-09-01"},
]

def _apply_quantity_invariants(rows: list[dict]) -> None:
    """种子数量口径自洽（BUG-34，FIX-20261022；**只影响空库重建**，不迁移存量库）。

    平台数量不变量（`services.auto_status` / 交付链路）：
    - 交付一次 ⇒ `soldCount += 1`；非 repeatSale 同时 `shippedQty += qty`；
    - repeatSale 只计次不扣量 ⇒ `shippedQty` 必须保持 0；
    - `shippedQty` 累加后不可超过 `quantity`；售罄（可售=0 且非 repeatSale）⇒ `all_sold`。
    历史汇总金额（`soldAmount`）> 0 但 `soldCount` = 0 的行属自相矛盾（有成交却无售卖次数），
    按「至少成交 1 次」归一，避免抽屉「已售次数 0 / 累计金额非 0」的错位展示。
    """
    for a in rows:
        if not a.get("soldAmount"):
            continue
        if not a.get("soldCount"):
            a["soldCount"] = 1
        if a.get("repeatSale"):
            a["shippedQty"] = 0
            continue
        a["shippedQty"] = max(int(a.get("shippedQty") or 0), 1)
        if a["quantity"] - (a.get("lockedQty") or 0) - a["shippedQty"] <= 0:
            a["status"] = "all_sold"


_apply_quantity_invariants(ASSETS)


SUPPLIERS = [
    {"name": "智元", "contact": "", "phone": "", "remark": "机器人本体"},
    {"name": "松延", "contact": "", "phone": "", "remark": "人形机器人（二期）"},
    {"name": "宏大卫星", "contact": "", "phone": "", "remark": "卫星 / 卫星数据"},
    {"name": "中电云", "contact": "", "phone": "", "remark": "卫星数据"},
    {"name": "大川海创", "contact": "", "phone": "", "remark": "电磁 / 遥感卫星数据"},
    {"name": "优斯图", "contact": "", "phone": "", "remark": "低轨卫星数据"},
    {"name": "德数交", "contact": "", "phone": "", "remark": "遥感数据"},
    {"name": "星河", "contact": "", "phone": "", "remark": "AI 算力集群"},
]

CATEGORY_UNITS = [
    {"board": "embodied", "type": "机器人", "unit": "套 / 台", "note": "整机交付，可选序列号交付"},
    {"board": "embodied", "type": "数采设备", "unit": "套", "note": "数采软件及设备接入"},
    {"board": "embodied", "type": "平台软件", "unit": "套", "note": "管理平台类"},
    {"board": "satellite", "type": "卫星Token", "unit": "个", "note": "按 Token 额度与有效期售卖（包量计价，合同金额整数元权威，ADR-008）"},
    {"board": "satellite", "type": "卫星数据", "unit": "轨 / 期 / 条", "note": "默认可重复售卖，不扣减数量"},
    {"board": "satellite", "type": "遥感数据", "unit": "份（区域·精度·日期）", "note": "按 省/精度/日期 三维唯一售卖（ADR-010）"},
    {"board": "software", "type": "软件", "unit": "套", "note": "永久 / 年限 / 并发 / 账号授权"},
    {"board": "hardware", "type": "硬件集群", "unit": "集群 / 台", "note": "整机柜或单台交付"},
    {"board": "compute", "type": "算力服务器", "unit": "台（服务期）", "note": "按服务期售卖，建设中"},
]
# ADR-024：交付物模板种子数据已删除（模板体系下线，实例完全手动维护）
