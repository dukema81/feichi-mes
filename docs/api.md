# 飞驰MES系统 REST 接口契约

> 版本 ｜ V1.0 · 2026 年 10 月 · 适用于 飞驰MES 1.0.0（OpenAPI 3.0：69 个路径 / 80 条路由）
>
> 运行时自描述：`GET /api/openapi.json` 返回完整规范，可直接导入 Postman / Apifox / Swagger UI。

## 1 通用约定

### 1.1 基础信息

| 项 | 值 |
| --- | --- |
| BaseURL | `http://<host>:8021` |
| 协议 | HTTP/1.1（生产建议放在 HTTPS 反向代理后） |
| 编码 | UTF-8；请求与响应均为 `application/json` |
| 时间格式 | 日期 `YYYY-MM-DD`；时间 `YYYY-MM-DD HH:MM:SS`（服务器本地时区） |
| 数字精度 | 数量与金额保留 2 位小数；比率保留 4 位小数（0~1） |
| 限流 | 单 IP 240 次/分钟，超限返回 `429` |

### 1.2 统一响应包

成功：

```json
{ "data": { "no": "WO20261020-0003", "status": "已开工" } }
```

失败：

```json
{ "error": "物料齐套率 83%，未达 100%" }
```

| 状态码 | 含义 | 典型场景 |
| --- | --- | --- |
| 200 | 成功 | 查询与写操作成功 |
| 400 | 参数或业务校验失败 | 闸口未通过、数量非法、必填缺失 |
| 401 | 未认证 / 令牌失效 | 未带令牌、Key 被吊销、会话过期 |
| 403 | 无权限 | 角色缺少对应权限位、非管理员访问集成配置 |
| 404 | 资源不存在 | 工单号、批次号、设备编码不存在 |
| 429 | 触发限流 | 单 IP 超过 240 次/分钟 |
| 500 | 服务内部错误 | 未捕获异常（含 DEMO 拦截器内部错误） |

### 1.3 认证方式

**方式一：会话令牌（前端与脚本）**

```http
POST /api/auth/login
Content-Type: application/json

{ "username": "admin", "password": "admin123" }
```

返回 `data.token`，后续请求任选一种携带（服务端按下列顺序逐个校验，取首个有效）：

1. `X-Fc-Key: fck_xxx`（API Key，见方式二）
2. `X-Fc-Token: <token>`
3. `X-Auth-Token: <token>`
4. `Authorization: Bearer <token>`
5. `Cookie: fc_token=<token>` 或 `Cookie: token=<token>`
6. 查询串 `?token=<token>`
7. 请求体 `{"token": "<token>"}`

**方式二：API Key（系统对接，推荐）**

```http
GET /api/orders?status=已开工
X-Fc-Key: fck_9f3aK2mQ7vT1xR8b
```

- 前缀固定 `fck_`，共 28 字符，仅创建时返回明文一次，服务端只存 SHA-256。
- `scope = read` 仅允许 GET；`scope = write` 允许全部；吊销后立即失效。

### 1.4 幂等

写接口可携带 `Idempotency-Key: <客户端生成的唯一串>`：

- 24 小时内同 Key 重复提交，返回首次结果，不重复执行；
- 适用于「网络超时重试」「ERP 重复下发工单」等场景；
- 未携带则不做幂等保护。

### 1.5 分页与筛选

列表接口统一返回形如：

```json
{ "list": [ ... ], "total": 37 }
```

常用参数：`limit`（默认 50，最大 400）、`kw`（模糊搜索，大小写不敏感）、`status`（状态过滤，`全部` 表示不过滤）。

## 2 认证与启动

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | 公开 | 账号密码登录，返回令牌与用户信息 |
| POST | `/api/auth/logout` | read | 注销当前会话 |
| GET | `/api/auth/me` | read | 当前用户与权限位 |
| GET | `/api/health` | 公开 | 健康检查：工单数、设备数、日志模式 |
| GET | `/api/bootstrap` | read | 启动数据：用户、KPI、14 天趋势、产线、状态分布、待办、预警、安灯、规则 |
| GET | `/api/openapi.json` | 公开 | OpenAPI 3.0 规范 |

`GET /api/bootstrap` 响应要点：

```json
{
  "data": {
    "user": { "username": "admin", "role": "admin", "roleLabel": "系统管理员",
              "perms": ["admin","approve","equip","inspect","read","report","stock","write"] },
    "kpi": { "wip": 15, "todayOutput": 541.6, "monthOutput": 1888.7, "monthPlan": 4798.0,
             "oee": 0.9068, "oeeLevel": "达标", "yieldRate": 0.9943, "equipAbnormal": 3,
             "maintDue": 7, "kitWarn": 0, "pendingInsp": 0, "overdue": 5,
             "abnormalDefects": 7 },
    "trend": [ { "day": "10-07", "output": 0.0, "ng": 0.0, "plan": 430.0 } ],
    "lines": [ { "code": "LN-101", "name": "精密加工线", "workshop": "WS-01",
                 "status": "运行", "taktSec": 60.0, "wip": 0, "orderCount": 1,
                 "stdMin": 5700.0, "load": 0.1799, "capacityMin": 31680 } ],
    "statusDist": [ { "status": "已入库", "count": 8 } ],
    "todo": [ { "type": "逾期工单", "no": "WO20261008-0001", "level": "high",
                "title": "MT-3002 计划完成 2026-10-11", "page": "orders" } ],
    "alarms": [ { "level": "high", "text": "激光焊接机（EQ-0007）故障", "page": "equipment" } ],
    "andon": [ { "id": 1, "no": "AD20260100", "line": "LN-101", "status": "待响应" } ],
    "rules": [ { "code": "oee_target", "name": "OEE 目标值", "value": 0.85, "enabled": 1 } ]
  }
}
```

## 3 组织与主数据

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/workshops` | read | 车间列表（编码、名称、负责人、产能分钟、状态） |
| GET | `/api/lines` | read | 产线列表（含所属车间、节拍、状态） |
| GET | `/api/stations` | read | 工位列表（产线、工序类型） |
| GET | `/api/teams` | read | 班组列表（班次、成员） |
| GET | `/api/materials` | read | 物料列表；参数 `type`（成品/半成品/原材料/辅料）、`kw`、`limit` |
| POST | `/api/materials` | write | 新建物料 |
| GET | `/api/materials/{code}` | read | 物料详情：主档 + 库存批次 + BOM + 工艺 + 近期工单 + 产出批次 |
| PUT | `/api/materials/{code}` | write | 更新物料主档（局部更新） |
| GET | `/api/boms` | read | BOM 列表（编码、物料、版本、状态） |
| GET | `/api/boms/{code}` | read | BOM 明细（组件、用量、损耗率、单位） |
| GET | `/api/routings` | read | 工艺路线列表 |
| GET | `/api/routings/{code}` | read | 工艺路线明细（工序、工位、设备类型、标准工时、节拍） |

新建物料：

```http
POST /api/materials
Content-Type: application/json

{ "code": "MT-9001", "name": "伺服电机 750W", "spec": "220V / 带抱闸",
  "unit": "台", "category": "驱动", "type": "原材料",
  "safetyStock": 50, "stdCost": 620, "leadDays": 14 }
```

响应：`{ "code": "MT-9001", "name": "伺服电机 750W" }`（未传 `code` 时按 `MT-xxxx` 自动生成）。

`GET /api/materials/{code}` 响应结构：

```json
{
  "data": {
    "material": { "code": "MT-3001", "name": "智能网关 GW-100", "type": "成品",
                  "abc": "C", "onHand": 210.0, "safetyStock": 120.0, "stdCost": 880.0 },
    "stock": [ { "batch": "B20261020-0001", "warehouse": "成品仓", "qty": 298.0,
                 "updatedAt": "2026-10-20 22:14:46" } ],
    "bom": { "code": "BOM-3001-01", "version": "V1.0", "status": "已发布",
             "items": [ { "component": "MT-1001", "qty": 2, "lossRate": 0.02 } ] },
    "routing": { "code": "RT-3001-01", "status": "已发布",
                 "steps": [ { "seq": 10, "process": "SMT 贴片", "stdMin": 12,
                              "cycleSec": 30, "isKey": 1 } ] },
    "orders": [ { "no": "WO20261020-0003", "qty": 60.0, "status": "已入库" } ],
    "batches": [ { "no": "B20261020-0001", "qty": 298.0, "producedAt": "2026-10-20 22:14:46" } ]
  }
}
```

## 4 工单

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/orders` | read | 工单列表；参数 `status`、`kw`、`overdue=1`、`limit` |
| POST | `/api/orders` | write | 新建工单（自动展开工序与用料） |
| GET | `/api/orders/{no}` | read | 工单详情：头部 + 工序 + 用料 + 齐套 + 闸口 + 检验 + 不良 + 报工 + 批次 |
| POST | `/api/orders/{no}/stage` | write/approve | 状态推进 `{ "target": "已下达" }` |
| POST | `/api/orders/{no}/cancel` | write | 取消工单 `{ "reason": "客户变更" }` |
| POST | `/api/orders/{no}/dispatch` | approve | 派工 `{ "owner": "qianwei", "team": "TM-01" }` |
| GET | `/api/orders/{no}/kit` | read | 齐套检查：按项 / 按量齐套率 + 缺口清单 |
| POST | `/api/orders/{no}/issue` | stock | 发料（按 BOM 一次发齐） |
| POST | `/api/orders/{no}/report` | report | 工序报工 |
| POST | `/api/orders/{no}/stock-in` | stock | 完工入库，生成批次与库存 |

### 4.1 新建工单

```http
POST /api/orders
Content-Type: application/json

{ "materialCode": "MT-3004", "qty": 45, "line": "LN-302",
  "priority": "紧急", "planStart": "2026-10-18", "planEnd": "2026-10-21",
  "customer": "南京工控", "salesNo": "SO-20261007", "remark": "插单" }
```

响应：`{ "no": "WO20261020-0003", "opCount": 5, "status": "草稿" }`

- 按物料绑定的已发布工艺路线生成 `opCount` 道工序，按 BOM 生成用料行（含损耗率）。
- 物料无工艺路线时返回 400，提示先维护并发布工艺。

### 4.2 工单详情

```json
{
  "data": {
    "no": "WO20261018-0001", "materialCode": "MT-3004", "materialName": "运动控制器 CTR-10",
    "qty": 45.0, "line": "LN-302", "status": "已开工", "priority": "紧急",
    "planStart": "2026-10-18", "planEnd": "2026-10-21",
    "reportedQty": 49.02, "goodQty": 48.65, "ngQty": 0.37, "progress": 1.0893,
    "opCount": 5, "opDone": 0, "eff": 2.4767, "dueState": "临期",
    "nextTargets": ["已完工"],
    "kitRate": 1.0, "kitShort": 0,
    "operations": [ { "seq": 10, "process": "SMT 贴片", "planQty": 45, "goodQty": 45,
                      "ngQty": 0, "stdMin": 240, "actualMin": 210, "status": "已完工" } ],
    "materials": [ { "materialCode": "MT-1001", "need": 90.0, "issued": 90.0,
                     "onHand": 260.0, "state": "齐套", "short": 0 } ],
    "kit": { "rate": 1.0, "qtyRate": 1.0, "total": 5, "ready": 5, "shortages": [] },
    "gate": { "已完工": ["仍有工序未完成报工"], "已入库": ["工单尚未完工"] },
    "inspections": [ { "no": "IQ20261018-01-FAI", "type": "首件", "result": "合格" } ],
    "defects": [], "reports": [ { "no": "RP101-01", "qty": 45.0 } ],
    "batch": null
  }
}
```

`gate` 的键是**待推进的目标状态**，值是缺失项数组（空数组即"可推进"）。前端据此渲染按钮与提示。

### 4.3 状态推进

```http
POST /api/orders/WO20261018-0001/stage
Content-Type: application/json

{ "target": "已完工" }
```

成功：`{ "no": "WO20261018-0001", "status": "已完工", "nextTargets": ["已入库","已关闭"] }`

失败示例（闸口未通过，400）：

```json
{ "error": "闸口未通过：仍有工序未完成报工" }
```

### 4.4 报工

```http
POST /api/orders/WO20261018-0001/report
Content-Type: application/json

{ "seq": 20, "goodQty": 45, "ngQty": 1, "actualMin": 210, "remark": "换刀 10 分钟" }
```

响应：

```json
{ "reportNo": "RP101-03", "eff": 1.1429, "woStatus": "已开工",
  "goodQty": 45.0, "reportedQty": 46.0, "progress": 1.0222 }
```

校验链（任一不通过返回 400 并说明原因）：

1. 工单状态必须在「已开工 / 已完工」之间（草稿与已下达不可报工）；
2. `goodQty + ngQty > 0`，且均不为负；
3. 规则 `fai_required=1` 时必须存在首件合格记录；
4. 本工序累计报工 ≤ `planQty × (1 + over_report_tol)`；
5. 全部工序完成后自动转「已完工」，`woStatus` 返回新状态。

### 4.5 发料与入库

```http
POST /api/orders/WO20261018-0001/issue
```

响应：`{ "no": "WO20261018-0001", "issued": 5, "kit": { "rate": 1.0, "ready": 5, "total": 5 } }`

```http
POST /api/orders/WO20261018-0001/stock-in
Content-Type: application/json

{ "warehouse": "成品仓" }
```

响应：`{ "batch": "B20261020-0001", "qty": 45.0, "status": "已入库" }`

入库前校验：状态必须为「已完工」且存在合格（或让步接收）的完工检。

## 5 工序与报工记录

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/ops` | read | 工序列表；参数 `wo`（工单号）、`status` |
| POST | `/api/ops/{id}/start` | report | 工序开工（记录实际开始时间） |
| POST | `/api/ops/{id}/finish` | report | 工序完工（不含数量，数量走报工） |
| GET | `/api/prod-reports` | read | 报工记录；参数 `wo`、`limit` |

## 6 现场：看板与安灯

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/board` | read | 生产看板：产线卡片（在制工单、当前工序、产出）、未关闭安灯、服务器时间 |
| GET | `/api/andon` | read | 安灯列表；参数 `status`、`limit` |
| POST | `/api/andon` | write | 发起呼叫 |
| POST | `/api/andon/{id}/close` | write | 关闭呼叫 |

```http
POST /api/andon

{ "line": "LN-101", "station": "ST-1012", "type": "设备",
  "level": "紧急", "remark": "拧紧机扭矩报警" }
```

响应：`{ "id": 5, "no": "AD202610-05" }`

关闭：`POST /api/andon/5/close`，请求体 `{ "remark": "已更换传感器" }`，响应 `{ "id": 5, "status": "已关闭" }`。

## 7 质量

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/quality/summary` | read | 质量总览：良品率、PPM、检验数、首件/完工检合格率、让步、退货、帕累托、趋势 |
| GET | `/api/inspections` | read | 检验单列表；参数 `type`（首件/巡检/完工检/来料检）、`kw` |
| POST | `/api/inspections` | inspect | 创建检验 |
| GET | `/api/inspections/{no}` | read | 检验单详情（含明细与 Cpk） |
| GET | `/api/defects` | read | 不良记录列表；参数 `wo`、`disposition` |
| POST | `/api/defects` | inspect | 登记不良 |
| POST | `/api/defects/{id}/dispose` | inspect | 不良处置 |
| GET | `/api/defect-codes` | read | 不良代码字典 |
| GET | `/api/cpk` | read | 过程能力（按被测项汇总） |

### 7.1 创建检验

```http
POST /api/inspections

{ "woNo": "WO20261018-0001", "type": "完工检", "sampleQty": 50, "defectQty": 0,
  "items": [ { "item": "关键尺寸", "value": 100.02, "lsl": 99.7, "usl": 100.3 } ],
  "remark": "" }
```

响应：`{ "no": "IQ20261020-0002", "result": "合格", "type": "完工检", "defectRate": 0.0 }`

结论规则：

| 类型 | 规则 |
| --- | --- |
| 首件 | `defectQty = 0` → 合格，否则不合格（不允许让步） |
| 巡检 | 有不良 → 异常（触发安灯与不良登记建议） |
| 完工检 | 0 不良 → 合格；不良率 ≤ `scrap_warn_rate` → 让步接收；否则不合格（退货） |

### 7.2 登记与处置不良

```http
POST /api/defects

{ "woNo": "WO20261018-0001", "defectCode": "DC-02", "qty": 2,
  "process": "整机装配", "remark": "来料表面划伤" }
```

响应：`{ "id": 25, "qty": 2, "disposition": "待处置" }`

```http
POST /api/defects/25/dispose

{ "disposition": "返修", "remark": "已打磨复检合格" }
```

`disposition` 取值：`返修`、`报废`、`让步接收`、`退货`。处置完成后工单才可能通过「已关闭」闸口。

### 7.3 Cpk

```json
{
  "data": {
    "list": [ { "item": "宽度(mm)", "n": 26, "lsl": 99.7, "usl": 100.3,
                "mean": 99.9873, "min": 99.9, "max": 100.09,
                "cpk": 1.6041, "level": "充足" } ],
    "items": 4, "samples": 79
  }
}
```

等级：≥ 1.67 充足 / ≥ 1.33 尚可 / ≥ 1.00 不足 / < 1.00 严重不足。

## 8 设备与保养

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/equipment` | read | 设备列表（含 OEE 与等级）；参数 `status`、`kw` |
| GET | `/api/equipment/{code}` | read | 设备详情：OEE、14 天日指标、状态日志、点检、保养工单、停机 TOP、保养计划 |
| POST | `/api/equipment/{code}/status` | equip | 状态变更（停机类必须填原因） |
| GET | `/api/equip/logs` | read | 设备状态日志；参数 `equipment`、`limit` |
| GET | `/api/equip/checks` | read | 点检记录；参数 `equipment` |
| POST | `/api/equip/checks` | equip | 提交点检 |
| GET | `/api/maint/plans` | read | 保养计划（含逾期 / 临期状态） |
| POST | `/api/maint/plans` | equip | 新建或更新保养计划 |
| GET | `/api/maint/orders` | read | 保养工单 |
| POST | `/api/maint/orders` | equip | 新建保养工单 |
| POST | `/api/maint/orders/{no}/finish` | equip | 完成保养 |

### 8.1 设备状态变更

```http
POST /api/equipment/EQ-0007/status

{ "status": "故障", "reason": "激光器功率衰减" }
```

- `status` ∈ `运行 / 待机 / 故障 / 保养 / 停机`；
- `故障 / 保养 / 停机` 必须提供 `reason`，否则 400；
- 变更写 `equip_logs`（状态、原因、开始时间），恢复运行时回填结束时间与停机分钟。

### 8.2 点检

```http
POST /api/equip/checks

{ "equipment": "EQ-0001", "type": "日常点检",
  "items": [ { "item": "油位", "result": "正常" },
             { "item": "气压", "result": "正常" },
             { "item": "安全门", "result": "异常" } ],
  "remark": "安全门联锁松动" }
```

响应：`{ "no": "CK20261020-0001", "result": "异常" }`

**任一项异常 → 设备自动置「故障」并写状态日志**，避免"点检发现问题但设备还在跑"。

### 8.3 保养

```http
POST /api/maint/orders

{ "equipment": "EQ-0016", "type": "计划保养", "planAt": "2026-10-22",
  "reason": "到保养周期" }
```

响应：`{ "no": "MT20261020-0001", "status": "待处理" }`

```http
POST /api/maint/orders/MT20261020-0001/finish

{ "downtimeMin": 90, "cost": 800, "remark": "更换主轴油封" }
```

完成动作同时：工单置「已完成」、设备置「运行」、回写 `last_maint_at / next_maint_at`、复位保养计划。

## 9 批次追溯与库存

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/batches` | read | 批次列表；参数 `kw`、`limit` |
| GET | `/api/batches/{no}` | read | 批次详情：主档 + 子批次 + 父批次 + 关联工单 + 库存 + 报工 |
| GET | `/api/trace` | read | 追溯树；参数 `batch=<批次号>` |
| GET | `/api/stock` | read | 库存台账；参数 `warehouse`、`kw` |

追溯响应：

```json
{
  "data": {
    "root": "B20261020-0001", "materialCode": "MT-3001", "woNo": "WO20261020-0003",
    "nodes": [ { "batch": "B20261020-0001", "materialCode": "MT-3001",
                 "qty": 298.0, "depth": 0, "producedAt": "2026-10-20 22:14:46",
                 "status": "正常" } ],
    "upstream": [ { "batch": "RM2609001", "materialCode": "MT-1001", "qty": 596.0, "depth": 1 } ],
    "nodeCount": 6
  }
}
```

`nodes` 为正向展开（成品 → 下级组件），`upstream` 为反向流向（原料 → 被哪些成品消耗）。

## 10 报表与导出

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/reports` | read | 报表聚合；参数 `days`（7/14/30，默认 14） |
| GET | `/api/export/orders` | read | 导出工单 CSV（UTF-8 BOM，Excel 直接打开） |
| GET | `/api/export/oee` | read | 导出设备 OEE CSV |

`GET /api/reports?days=7` 响应结构：

```json
{
  "data": {
    "days": 7,
    "production": { "trend": [ { "day": "10-14", "output": 0, "ng": 0, "plan": 430,
                                 "yieldRate": 0.99 } ],
                    "output": 1279.5, "plan": 2150.0, "completion": 0.5951,
                    "monthOutput": 7987.13, "monthPlan": 4298.0, "monthCompletion": 1.8583 },
    "oee": { "plant": { "availability": 0.9234, "performance": 1.0, "quality": 0.9846,
                        "oee": 0.9092, "planMin": 120000, "runMin": 110810,
                        "downMin": 9190, "output": 339486, "good": 334249 },
             "trend": [ { "day": "10-14", "oee": 0.9, "availability": 0.92,
                          "performance": 1.0, "quality": 0.98 } ],
             "target": 0.85, "level": "达标" },
    "quality": { "yieldRate": 0.9943, "ppm": 5722, "pareto": [ { "name": "标签错误",
                 "qty": 8, "share": 0.1702, "cum": 0.1702, "key": true } ] },
    "lines": [ { "code": "LN-101", "load": 0.1799, "output": 884.99, "wip": 0,
                 "balance": 0.7037 } ],
    "equipment": { "rank": [], "worst": [], "downTop": [], "mtbf": 1385.12, "mttr": 134.26 },
    "materials": { "top": [] }
  }
}
```

**产量口径提示**：`production.output` 采用末工序法（每张工单只计末道工序报工），因此与"入库量"天然接近；`oee.plant.performance` 上限为 1，避免理论节拍失真导致 OEE > 100%。

## 11 系统设置与日志

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/settings` | read | 设置总览：规则、车间、产线、班组、用户、班制、角色 |
| PUT | `/api/rules/{code}` | admin | 规则启停或调阈值 `{ "value": 0.8 }` / `{ "enabled": 0 }` |
| GET | `/api/logs` | read | 操作日志；参数 `limit`（默认 200） |
| GET | `/api/users` | read | 用户列表（账号、姓名、角色、部门、状态） |

```http
PUT /api/rules/oee_target

{ "value": 0.9 }
```

响应：`{ "code": "oee_target", "value": 0.9, "enabled": 1 }`（**即时生效**，下次判定即使用新阈值）。

## 12 集成中心

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/integration/overview` | read | 总览：Key/Webhook/投递/变更/映射数量与各对象记录数 |
| GET | `/api/integration/keys` | admin | Key 列表（前缀、scope、状态、最后使用时间） |
| POST | `/api/integration/keys` | admin | 新建 Key，**明文只返回一次** |
| DELETE | `/api/integration/keys/{id}` | admin | 吊销 Key |
| GET | `/api/integration/webhooks` | admin | Webhook 列表（密钥打码） |
| POST | `/api/integration/webhooks` | admin | 新建 Webhook，返回签名密钥 |
| PUT | `/api/integration/webhooks/{id}` | admin | 更新（支持局部字段） |
| DELETE | `/api/integration/webhooks/{id}` | admin | 删除订阅及投递记录 |
| POST | `/api/integration/webhooks/{id}/test` | admin | 发送 `webhook.test` 事件 |
| GET | `/api/integration/deliveries` | admin | 投递记录（事件、次数、HTTP 码、下次重试时间） |
| POST | `/api/integration/deliveries/{id}/retry` | admin | 手动重投 |
| GET | `/api/integration/mappings` | read | 外部 ID 映射列表 |
| POST | `/api/integration/mappings` | admin | 绑定外部 ID |
| DELETE | `/api/integration/mappings/{id}` | admin | 解绑 |
| GET | `/api/integration/resolve` | read | 反查 `?obj=work_order&localNo=...` 或 `&externalId=...` |
| GET | `/api/sync/changes` | read | 增量变更流；参数 `since`、`object`、`limit` |

### 12.1 新建 API Key

```http
POST /api/integration/keys

{ "name": "ERP 生产订单同步", "scope": "write" }
```

```json
{ "data": { "id": 3, "key": "fck_9f3aK2mQ7vT1xR8bWc4n",
            "name": "ERP 生产订单同步", "scope": "write",
            "notice": "密钥只显示一次，请立即保存" } }
```

调用示例：

```bash
curl -H "X-Fc-Key: fck_9f3aK2mQ7vT1xR8bWc4n" \
     "http://mes.feichi.local:8021/api/orders?status=已开工"
```

### 12.2 Webhook 签名与验签

请求头：

```http
POST /your-endpoint
X-Fc-Event: work_order.reported
X-Fc-Timestamp: 1792459200
X-Fc-Signature: 5f0c...（HMAC-SHA256 十六进制小写）
X-Fc-Delivery: 41
Content-Type: application/json

{ "event": "work_order.reported", "at": "2026-10-20 22:14:46",
  "data": { "no": "WO20261018-0001", "seq": 20, "goodQty": 45, "ngQty": 1 } }
```

签名算法：

```
signature = hex(HMAC_SHA256(secret, timestamp + "." + rawBody))
```

验签方要求：

1. 取**原始请求体字符串**（不要重新序列化）；
2. 校验 `|now - timestamp| ≤ 300` 秒，防重放；
3. 常量时间比较签名；
4. 按 `X-Fc-Delivery` 去重（同 ID 只处理一次）。

重投：失败按 `30 × 2^n` 秒退避，最多 3 次；终态失败可在集成中心手动重投。

### 12.3 事件清单

| 事件 | 触发时机 | data 主要字段 |
| --- | --- | --- |
| `work_order.created` | 新建工单 | `no`、`materialCode`、`qty`、`line` |
| `work_order.stage_changed` | 状态推进 | `no`、`from`、`to`、`actor` |
| `work_order.reported` | 报工 | `no`、`seq`、`goodQty`、`ngQty`、`actualMin` |
| `work_order.stock_in` | 完工入库 | `no`、`batch`、`qty` |
| `inspection.created` | 检验完成 | `no`、`woNo`、`type`、`result` |
| `defect.created` | 登记不良 | `woNo`、`code`、`qty` |
| `defect.disposed` | 不良处置 | `woNo`、`code`、`disposition` |
| `equipment.status_changed` | 设备状态变更 | `code`、`from`、`to`、`reason` |
| `maintenance.finished` | 完成保养 | `no`、`equipment`、`downtimeMin` |
| `andon.created` / `andon.closed` | 安灯发起 / 关闭 | `no`、`line`、`level`、`status` |

### 12.4 增量同步

```http
GET /api/sync/changes?since=0&object=work_order&limit=100
X-Fc-Key: fck_xxx
```

```json
{
  "data": {
    "changes": [ { "id": 1, "objType": "work_order", "objNo": "WO20260924-0001",
                   "op": "upsert", "actor": "qianwei", "changedAt": "2026-09-28 18:00:00",
                   "payload": { "no": "WO20260924-0001", "status": "已开工", "qty": 40 } } ],
    "cursor": 100, "hasMore": true, "count": 100
  }
}
```

对接建议：客户端保存 `cursor`，每 1~5 分钟拉一次；`hasMore=true` 时立即续拉；`op=delete` 表示对象作废。

## 13 错误码速查

| 错误信息 | 触发条件 | 处理建议 |
| --- | --- | --- |
| `账号或密码错误` | 登录失败 | 核对账号密码（演示账号见手册） |
| `登录状态已失效，请重新登录` | 令牌过期 / 吊销 | 重新登录 |
| `当前角色无此操作权限` | 缺少权限位 | 换角色或申请授权 |
| `物料齐套率 83%，未达 100%` | 下达闸口 | 先发料 / 补库存，或由管理员关闭 `kit_block` |
| `首件检验未合格，不能报工（规则：首件必检）` | 报工闸口 | 先做首件检验并合格 |
| `超出工序计划量（含 5% 容差）` | 超报 | 核对报工数量 |
| `完工检未合格，不能入库` | 入库闸口 | 重新检验或走让步接收 |
| `停机类状态必须填写原因` | 设备状态 | 补 `reason` |
| `不允许从「已关闭」推进到「已入库」` | 状态机 | 终态不可回退 |
| `触发限流，请稍后再试` | 429 | 降低频率或申请白名单 |

## 14 对接实施建议

1. **先只读后写入**：给对接方先发 `read` scope 的 Key，跑通查询与对账，再开 `write`。
2. **用幂等键**：ERP 下发工单、WMS 回传入库必须带 `Idempotency-Key`，避免重试造成重复单。
3. **事件优先于轮询**：实时性要求高的用 Webhook；每日对账用增量同步，二者并行不冲突。
4. **字段映射表落库**：外部单号不要塞进 `remark`，用 `ext_mappings` 绑定，便于双向反查。
5. **先跑沙箱**：`python backend/server.py` 用独立 `FEICHI_DB` 起一套演示库联调，通过后再切生产库。
