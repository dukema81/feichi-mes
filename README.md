# 飞驰MES系统（Feichi MES）

飞驰精密制造（苏州）有限公司的制造执行系统：把销售订单与到料结果变成「每张工单在每条产线每道工序做到哪一步」，并把质量、设备、人员、批次数据沉淀为可追溯、可分析、可对接的数据底座。

- **零依赖**：后端仅用 Python 标准库（`http.server` + `sqlite3`），前端原生 HTML/CSS/JS，无 pip、无 npm、无 CDN。
- **单机可跑**：`python backend/server.py` 一条命令启动，首次自动建库并写入确定性演示数据。
- **口径唯一**：OEE、产量、齐套率、Cpk 等指标只在 `backend/mes.py` 实现一次，报表与页面共用。
- **可对接**：80 条 REST 路由 + OpenAPI 3.0 + API Key + Webhook（HMAC 签名）+ 增量同步。

## 快速开始

```bash
cd feichi-mes
python backend/server.py          # 默认 http://127.0.0.1:8021
```

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | 系统管理员 |
| `qianwei` | `fc@2026` | 厂长 |
| `liyun` | `fc@2026` | 计划员 |
| `zhaolei` | `fc@2026` | 操作工 |
| `sunqi` | `fc@2026` | 质检员 |
| `zhouhang` | `fc@2026` | 设备工程师 |
| `wuping` | `fc@2026` | 仓管 |
| `chenmo` | `fc@2026` | 访客（只读） |

环境变量：`FEICHI_PORT`（默认 8021）、`FEICHI_DB`（默认 `backend/data/feichi.db`）。

## 目录结构

```
backend/   server.py（80 条路由 / OpenAPI）、mes.py（业务内核纯函数）、db.py（26 表）、seed.py（确定性数据）
frontend/  index.html、login.html、style.css、app.js / plan.js / mdm.js / qual.js / equip.js / stock.js / intg.js
demo/      feichi-mes-demo.html（离线单文件，双击即用）
tests/     test_unit_core.py（66）、test_api.py（78）、test_e2e_ui.py（6）
tools/     smoke_api、ui_check、build_demo、smoke_demo、build_docs、kb_upload、push_github
deploy/    build_package.py（打 feichi_app.tar.gz）
docs/      建设方案 / 接口契约 / 测试报告 / 操作手册（md + docx）
scripts/   run_tests.py（三层测试门禁）
```

## 核心机制

- **工单状态机**：草稿 → 已下达 → 已开工 → 已完工 → 已入库 → 已关闭（另有已取消）。只能前进、可跨级、终态锁定。
- **五道闸口**：下达看齐套 100% / 开工看首件合格与设备可用 / 完工看工序报齐 / 入库看完工检合格 / 关闭看不良清空。闸口返回"缺什么"，前端直接展示、后端二次拦截。
- **末工序产量口径**：每张工单只计末道工序报工，避免逐工序重复计数（曾是 3 倍虚高的根因）。
- **OEE**：可用率 × 性能率（上限 100%）× 质量率，等级按目标值 0.85 判达标/预警/未达标。
- **批次追溯**：`batch_links` 父子链支撑任意深度正向展开与反向流向。
- **三通道集成**：API Key（`fck_` 前缀，存 SHA-256）、Webhook（`HMAC-SHA256(secret, timestamp + "." + body)`，30×2^n 秒退避重投 3 次）、增量同步（`change_log` 游标续拉）。

## 测试

```bash
python scripts/run_tests.py        # 单元 66 + 接口 78 + 端到端 6 = 150 项门禁
python scripts/run_tests.py --fast # 跳过浏览器
python tools/smoke_api.py          # 业务主线冒烟（153 检查点，需先起服务）
python tools/ui_check.py           # 14 页巡检 + 截图
python tools/build_demo.py && python tools/smoke_demo.py   # 离线 DEMO 构建与冒烟
```

## 文档

| 文档 | 说明 |
| --- | --- |
| `docs/feichi-mes-design.md` | 建设方案：架构、状态机与闸口、算法口径、数据模型、权限、集成、实施计划 |
| `docs/api.md` | REST 接口契约：鉴权、幂等、全部路由、Webhook 协议、错误码、对接建议 |
| `docs/test-report.md` | 测试报告：150 项自动化 + 171 检查点、缺陷台账、验收对照 |
| `docs/user-guide.md` | 操作手册：14 页逐页操作、角色场景演练、FAQ、运维指南 |

## 许可证

内部项目，版权归飞驰精密制造（苏州）有限公司所有。
