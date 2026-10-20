# -*- coding: utf-8 -*-
"""飞驰 MES · 数据层：SQLite 零依赖，建表 / 连接 / 种子装载。

并发纪律
- journal_mode 是持久化设置，只在 init_db 设一次；
- 每连接只设 busy_timeout；
- 服务层对所有 /api/ 请求整段串行化（RLock），这里不再做额外锁。
"""
import hashlib
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FEICHI_DB", os.path.join(BASE_DIR, "data", "feichi.db"))

SCHEMA = """
-- ---------------------------------------------------------------- 账号与组织
CREATE TABLE IF NOT EXISTS users (
  username     TEXT PRIMARY KEY,
  password     TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL,
  dept_code    TEXT DEFAULT '',
  phone        TEXT DEFAULT '',
  email        TEXT DEFAULT '',
  status       TEXT DEFAULT '在职',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS teams (
  code      TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  workshop  TEXT DEFAULT '',
  leader    TEXT DEFAULT '',
  members   TEXT DEFAULT '',
  shift     TEXT DEFAULT '白班',
  remark    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rules (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  category TEXT DEFAULT '生产',
  value    REAL DEFAULT 0,
  unit     TEXT DEFAULT '',
  enabled  INTEGER DEFAULT 1,
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS op_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT DEFAULT '',
  action     TEXT DEFAULT '',
  detail     TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 车间 / 产线 / 工位
CREATE TABLE IF NOT EXISTS workshops (
  code         TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  manager      TEXT DEFAULT '',
  capacity_min REAL DEFAULT 0,
  status       TEXT DEFAULT '启用',
  remark       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS lines (
  code      TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  workshop  TEXT DEFAULT '',
  leader    TEXT DEFAULT '',
  takt_sec  REAL DEFAULT 0,
  status    TEXT DEFAULT '运行',
  remark    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stations (
  code    TEXT PRIMARY KEY,
  name    TEXT NOT NULL,
  line    TEXT DEFAULT '',
  seq     INTEGER DEFAULT 0,
  type    TEXT DEFAULT '机加工',
  status  TEXT DEFAULT '启用',
  remark  TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 设备
CREATE TABLE IF NOT EXISTS equipment (
  code          TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  type          TEXT DEFAULT '',
  line          TEXT DEFAULT '',
  station       TEXT DEFAULT '',
  vendor        TEXT DEFAULT '',
  model         TEXT DEFAULT '',
  buy_date      TEXT DEFAULT '',
  status        TEXT DEFAULT '运行',
  run_hours     REAL DEFAULT 0,
  down_min      REAL DEFAULT 0,
  failures      INTEGER DEFAULT 0,
  last_maint_at TEXT DEFAULT '',
  next_maint_at TEXT DEFAULT '',
  oee_target    REAL DEFAULT 0.85,
  remark        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS equip_logs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment   TEXT NOT NULL,
  status      TEXT DEFAULT '',
  prev_status TEXT DEFAULT '',
  reason      TEXT DEFAULT '',
  minutes     REAL DEFAULT 0,
  wo_no       TEXT DEFAULT '',
  operator    TEXT DEFAULT '',
  start_at    TEXT DEFAULT '',
  end_at      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS equip_checks (
  no          TEXT PRIMARY KEY,
  equipment   TEXT NOT NULL,
  check_type  TEXT DEFAULT '日常点检',
  result      TEXT DEFAULT '正常',
  items_json  TEXT DEFAULT '[]',
  checker     TEXT DEFAULT '',
  checked_at  TEXT DEFAULT '',
  remark      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS maint_plans (
  code         TEXT PRIMARY KEY,
  equipment    TEXT NOT NULL,
  type         TEXT DEFAULT '一级保养',
  cycle_days   INTEGER DEFAULT 30,
  cycle_hours  REAL DEFAULT 0,
  last_at      TEXT DEFAULT '',
  next_at      TEXT DEFAULT '',
  owner        TEXT DEFAULT '',
  status       TEXT DEFAULT '启用',
  remark       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS maint_orders (
  no           TEXT PRIMARY KEY,
  equipment    TEXT NOT NULL,
  plan_code    TEXT DEFAULT '',
  type         TEXT DEFAULT '计划保养',
  reason       TEXT DEFAULT '',
  status       TEXT DEFAULT '待执行',
  plan_at      TEXT DEFAULT '',
  start_at     TEXT DEFAULT '',
  finish_at    TEXT DEFAULT '',
  downtime_min REAL DEFAULT 0,
  cost         REAL DEFAULT 0,
  owner        TEXT DEFAULT '',
  remark       TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 主数据
CREATE TABLE IF NOT EXISTS materials (
  code         TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  spec         TEXT DEFAULT '',
  unit         TEXT DEFAULT '件',
  category     TEXT DEFAULT '',
  mtype        TEXT DEFAULT '原材料',
  abc          TEXT DEFAULT 'C',
  safety_stock REAL DEFAULT 0,
  on_hand      REAL DEFAULT 0,
  std_cost     REAL DEFAULT 0,
  lead_days    INTEGER DEFAULT 7,
  status       TEXT DEFAULT '启用',
  remark       TEXT DEFAULT '',
  updated_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS boms (
  code          TEXT PRIMARY KEY,
  material_code TEXT NOT NULL,
  version       TEXT DEFAULT 'V1.0',
  status        TEXT DEFAULT '已发布',
  remark        TEXT DEFAULT '',
  updated_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bom_items (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  bom_code  TEXT NOT NULL,
  component TEXT NOT NULL,
  qty       REAL DEFAULT 0,
  loss_rate REAL DEFAULT 0,
  seq       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS routings (
  code          TEXT PRIMARY KEY,
  material_code TEXT NOT NULL,
  version       TEXT DEFAULT 'V1.0',
  name          TEXT DEFAULT '',
  status        TEXT DEFAULT '已发布',
  updated_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS routing_steps (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  routing_code TEXT NOT NULL,
  seq          INTEGER DEFAULT 0,
  process      TEXT DEFAULT '',
  station      TEXT DEFAULT '',
  equip_type   TEXT DEFAULT '',
  std_min      REAL DEFAULT 0,
  cycle_sec    REAL DEFAULT 0,
  is_key       INTEGER DEFAULT 0,
  remark       TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 工单与执行
CREATE TABLE IF NOT EXISTS work_orders (
  no           TEXT PRIMARY KEY,
  material_code TEXT NOT NULL,
  qty          REAL DEFAULT 0,
  workshop     TEXT DEFAULT '',
  line         TEXT DEFAULT '',
  priority     TEXT DEFAULT '普通',
  status       TEXT DEFAULT '草稿',
  plan_start   TEXT DEFAULT '',
  plan_end     TEXT DEFAULT '',
  actual_start TEXT DEFAULT '',
  actual_end   TEXT DEFAULT '',
  routing_code TEXT DEFAULT '',
  bom_code     TEXT DEFAULT '',
  sales_no     TEXT DEFAULT '',
  customer     TEXT DEFAULT '',
  planner      TEXT DEFAULT '',
  owner        TEXT DEFAULT '',
  team         TEXT DEFAULT '',
  remark       TEXT DEFAULT '',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS wo_operations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_no      TEXT NOT NULL,
  seq        INTEGER DEFAULT 0,
  process    TEXT DEFAULT '',
  station    TEXT DEFAULT '',
  equipment  TEXT DEFAULT '',
  plan_qty   REAL DEFAULT 0,
  good_qty   REAL DEFAULT 0,
  ng_qty     REAL DEFAULT 0,
  std_min    REAL DEFAULT 0,
  actual_min REAL DEFAULT 0,
  status     TEXT DEFAULT '待开工',
  operator   TEXT DEFAULT '',
  start_at   TEXT DEFAULT '',
  end_at     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS wo_materials (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_no        TEXT NOT NULL,
  material_code TEXT NOT NULL,
  need_qty     REAL DEFAULT 0,
  issued_qty   REAL DEFAULT 0,
  unit         TEXT DEFAULT '件',
  state        TEXT DEFAULT '待齐套'
);
CREATE TABLE IF NOT EXISTS prod_reports (
  no          TEXT PRIMARY KEY,
  wo_no       TEXT NOT NULL,
  seq         INTEGER DEFAULT 0,
  process     TEXT DEFAULT '',
  qty         REAL DEFAULT 0,
  good_qty    REAL DEFAULT 0,
  ng_qty      REAL DEFAULT 0,
  std_min     REAL DEFAULT 0,
  actual_min  REAL DEFAULT 0,
  equipment   TEXT DEFAULT '',
  operator    TEXT DEFAULT '',
  batch_no    TEXT DEFAULT '',
  shift       TEXT DEFAULT '白班',
  reported_at TEXT DEFAULT '',
  remark      TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 质量
CREATE TABLE IF NOT EXISTS inspections (
  no           TEXT PRIMARY KEY,
  wo_no        TEXT DEFAULT '',
  type         TEXT DEFAULT '首件',
  seq          INTEGER DEFAULT 0,
  process      TEXT DEFAULT '',
  sample_qty   REAL DEFAULT 0,
  defect_qty   REAL DEFAULT 0,
  result       TEXT DEFAULT '待检',
  standard     TEXT DEFAULT '',
  inspector    TEXT DEFAULT '',
  inspected_at TEXT DEFAULT '',
  remark       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS inspection_items (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  inspection_no  TEXT NOT NULL,
  item           TEXT DEFAULT '',
  value          REAL DEFAULT 0,
  lsl            REAL DEFAULT 0,
  usl            REAL DEFAULT 0,
  result         TEXT DEFAULT '合格'
);
CREATE TABLE IF NOT EXISTS defect_codes (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  category TEXT DEFAULT '',
  severity TEXT DEFAULT '一般',
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS defects (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_no         TEXT DEFAULT '',
  inspection_no TEXT DEFAULT '',
  defect_code   TEXT DEFAULT '',
  qty           REAL DEFAULT 0,
  process       TEXT DEFAULT '',
  equipment     TEXT DEFAULT '',
  operator      TEXT DEFAULT '',
  occur_at      TEXT DEFAULT '',
  disposition   TEXT DEFAULT '待处置',
  remark        TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 批次与库存
CREATE TABLE IF NOT EXISTS batches (
  no           TEXT PRIMARY KEY,
  material_code TEXT NOT NULL,
  wo_no        TEXT DEFAULT '',
  qty          REAL DEFAULT 0,
  good_qty     REAL DEFAULT 0,
  workshop     TEXT DEFAULT '',
  line         TEXT DEFAULT '',
  produced_at  TEXT DEFAULT '',
  expire_at    TEXT DEFAULT '',
  status       TEXT DEFAULT '正常',
  parent_batch TEXT DEFAULT '',
  remark       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS batch_links (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_batch TEXT NOT NULL,
  child_batch  TEXT NOT NULL,
  material_code TEXT DEFAULT '',
  qty          REAL DEFAULT 0,
  wo_no        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stocks (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  material_code TEXT NOT NULL,
  warehouse    TEXT DEFAULT '原料仓',
  batch_no     TEXT DEFAULT '',
  qty          REAL DEFAULT 0,
  updated_at   TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS andon (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  no         TEXT DEFAULT '',
  line       TEXT DEFAULT '',
  station    TEXT DEFAULT '',
  type       TEXT DEFAULT '设备',
  level      TEXT DEFAULT '一般',
  status     TEXT DEFAULT '待响应',
  reporter   TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  closed_at  TEXT DEFAULT '',
  remark     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS equip_metrics (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment   TEXT NOT NULL,
  day         TEXT NOT NULL,
  plan_min    REAL DEFAULT 0,
  run_min     REAL DEFAULT 0,
  output      REAL DEFAULT 0,
  good        REAL DEFAULT 0,
  ideal_cycle REAL DEFAULT 0
);

-- ---------------------------------------------------------------- 集成
CREATE TABLE IF NOT EXISTS change_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type   TEXT DEFAULT '',
  obj_no     TEXT DEFAULT '',
  op         TEXT DEFAULT 'upsert',
  actor      TEXT DEFAULT '',
  payload    TEXT DEFAULT '{}',
  changed_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS api_keys (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  key_hash     TEXT NOT NULL,
  prefix       TEXT DEFAULT '',
  scope        TEXT DEFAULT 'read',
  owner        TEXT DEFAULT '',
  status       TEXT DEFAULT '启用',
  created_at   TEXT DEFAULT '',
  last_used_at TEXT DEFAULT '',
  expires_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhooks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  url        TEXT NOT NULL,
  events     TEXT DEFAULT '*',
  secret     TEXT DEFAULT '',
  status     TEXT DEFAULT '启用',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  webhook_id   INTEGER DEFAULT 0,
  event        TEXT DEFAULT '',
  payload      TEXT DEFAULT '',
  signature    TEXT DEFAULT '',
  status       TEXT DEFAULT '待投递',
  attempts     INTEGER DEFAULT 0,
  http_code    INTEGER DEFAULT 0,
  error        TEXT DEFAULT '',
  next_at      TEXT DEFAULT '',
  created_at   TEXT DEFAULT '',
  delivered_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS idem_keys (
  key        TEXT PRIMARY KEY,
  path       TEXT DEFAULT '',
  response   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ext_mappings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  obj_type    TEXT DEFAULT '',
  local_no    TEXT DEFAULT '',
  external_id TEXT DEFAULT '',
  system      TEXT DEFAULT '',
  created_at  TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 索引
CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_wo_mat ON work_orders(material_code);
CREATE INDEX IF NOT EXISTS idx_woop ON wo_operations(wo_no);
CREATE INDEX IF NOT EXISTS idx_rep ON prod_reports(wo_no);
CREATE INDEX IF NOT EXISTS idx_insp ON inspections(wo_no);
CREATE INDEX IF NOT EXISTS idx_def ON defects(wo_no);
CREATE INDEX IF NOT EXISTS idx_elog ON equip_logs(equipment);
CREATE INDEX IF NOT EXISTS idx_batch ON batches(wo_no);
CREATE INDEX IF NOT EXISTS idx_change ON change_log(changed_at);
CREATE INDEX IF NOT EXISTS idx_stock ON stocks(material_code);
CREATE INDEX IF NOT EXISTS idx_em ON equip_metrics(equipment, day);
CREATE INDEX IF NOT EXISTS idx_andon ON andon(status);
CREATE INDEX IF NOT EXISTS idx_bom ON bom_items(bom_code);
CREATE INDEX IF NOT EXISTS idx_rs ON routing_steps(routing_code);
"""


def sha256(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    return c


def rows(cn, sql, args=()):
    return [dict(r) for r in cn.execute(sql, args).fetchall()]


def one(cn, sql, args=()):
    r = cn.execute(sql, args).fetchone()
    return dict(r) if r else None


def log_action(cn, username, action, detail=""):
    import datetime
    cn.execute("INSERT INTO op_logs(username, action, detail, created_at) VALUES(?,?,?,?)",
               (username, action, detail,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def init_db():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    cn = conn()
    try:
        cn.execute("PRAGMA journal_mode=WAL")
        cn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    cn.executescript(SCHEMA)
    if cn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        import seed
        seed.load(cn)
    cn.commit()
    cn.close()


if __name__ == "__main__":
    init_db()
    print("db ready:", DB_PATH)
