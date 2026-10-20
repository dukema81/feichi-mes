# -*- coding: utf-8 -*-
"""飞驰 MES · REST 服务（标准库 http.server + sqlite3，零第三方依赖）

约定
- 成功 {"ok": true, "data": ...}；失败 {"error": "中文原因"}（可附带 missing / dups 等提示字段）
- 鉴权：用户会话 Token 与 API Key（系统对接，前缀 fck_）；票据支持多通道（头 / Cookie / 查询串），
  避免反向代理改写 Authorization 导致页面掉登录
- 并发：SQLite 单写者，所有 /api/ 请求整段串行化（RLock）
- 集成：每次业务变更写 change_log（增量同步）+ 生成 Webhook 投递任务（后台线程退避重试）
"""
import csv
import functools
import hmac
import http.client
import io
import json
import os
import re
import secrets
import threading
import time
import traceback
import uuid
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import db
import mes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
FRONTEND = os.path.join(ROOT, "frontend")
PORT = int(os.environ.get("FEICHI_PORT") or os.environ.get("PORT") or "8021")
HOST = os.environ.get("FEICHI_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
LOCK = threading.RLock()
VERSION = "1.0.0"
START_TS = time.time()

OPEN_PATHS = {("POST", "/api/auth/login"), ("GET", "/api/health"), ("GET", "/api/openapi.json")}
_RATE = {}
RATE_LIMIT = 240
WEBHOOK_MAX_TRY = 3


class ApiError(Exception):
    def __init__(self, message, code=400, **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


def today():
    return date.today().isoformat()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rows(cn, sql, args=()):
    return db.rows(cn, sql, args)


def one(cn, sql, args=()):
    return db.one(cn, sql, args)


def with_db(fn):
    @functools.wraps(fn)
    def wrapper(cn, *a, **kw):
        out = fn(cn, *a, **kw)
        cn.commit()
        return out
    return wrapper


def write_op(fn):
    @functools.wraps(fn)
    def wrapper(cn, *a, **kw):
        with LOCK:
            return with_db(fn)(cn, *a, **kw)
    return wrapper


def op(cn, username, action, detail=""):
    db.log_action(cn, username, action, detail)


def rule_value(cn, code, default=None):
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    if not r or not r["enabled"]:
        return default
    return r["value"]


def rule_num(cn, code, default):
    v = rule_value(cn, code, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def require(user, perm):
    if not mes.can(user["role"], perm):
        raise ApiError("当前角色（%s）无权执行该操作"
                       % mes.ROLE_LABEL.get(user["role"], user["role"]), 403)


def need_admin(user):
    if user["role"] != "admin":
        raise ApiError("仅系统管理员可操作集成配置", 403)


def scope_of(user):
    """数据范围：班组长只能操作自己班组所在车间的工单，其余角色全域可读。"""
    if user["role"] == "operator":
        return user["username"]
    return None


def q1(query, key, default=""):
    v = query.get(key)
    if not v:
        return default
    return v[0]


def qint(query, key, default=0):
    try:
        return int(q1(query, key, str(default)) or default)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 鉴权
def auth_user(cn, token):
    if not token:
        return None
    if token.startswith("fck_"):
        k = one(cn, "SELECT * FROM api_keys WHERE key_hash=? AND status='启用'", (mes.sha256(token),))
        if not k:
            return None
        if k["expires_at"] and k["expires_at"][:10] < today():
            return None
        cn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now(), k["id"]))
        cn.commit()
        return {"username": k["owner"] or "api", "displayName": k["name"],
                "role": "admin" if k["scope"] == "write" else "viewer",
                "roleLabel": "API Key（%s）" % ("读写" if k["scope"] == "write" else "只读"),
                "authType": "apikey", "keyId": k["id"], "scope": k["scope"]}
    s = one(cn, "SELECT * FROM sessions WHERE token=?", (token,))
    if not s:
        return None
    u = one(cn, "SELECT * FROM users WHERE username=?", (s["username"],))
    if not u:
        return None
    return {"username": u["username"], "displayName": u["display_name"], "role": u["role"],
            "roleLabel": mes.ROLE_LABEL.get(u["role"], u["role"]), "authType": "session"}


def rate_check(user):
    if user.get("authType") != "apikey":
        return
    kid = str(user.get("keyId"))
    win = int(time.time() // 60)
    slot = _RATE.get(kid)
    if not slot or slot[0] != win:
        _RATE[kid] = [win, 1]
        return
    slot[1] += 1
    if slot[1] > RATE_LIMIT:
        raise ApiError("超出调用配额（%d 次/分钟），请稍后重试" % RATE_LIMIT, 429)


# ---------------------------------------------------------------- 变更与事件
def emit(cn, event, obj_type, obj_no, payload, actor):
    body = mes.dumps(payload)
    cn.execute("INSERT INTO change_log(obj_type,obj_no,op,actor,payload,changed_at) VALUES(?,?,?,?,?,?)",
               (obj_type, obj_no, "upsert", actor, body, now()))
    hooks = rows(cn, "SELECT * FROM webhooks WHERE status='启用'")
    for h in hooks:
        evs = [x.strip() for x in str(h["events"] or "*").split(",") if x.strip()]
        if "*" not in evs and event not in evs:
            continue
        sig = mes.sign_payload(h["secret"], str(int(time.time())),
                               json.dumps({"event": event, "data": payload}, ensure_ascii=False,
                                          sort_keys=True))
        cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,signature,status,attempts,"
                   "http_code,error,next_at,created_at,delivered_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (h["id"], event, body, sig, "待投递", 0, 0, "", now(), now(), ""))


def next_no(cn, kind, table, column="no"):
    head = mes.doc_no(kind, today(), 0).rsplit("-", 1)[0] + "-"
    r = one(cn, "SELECT MAX(%s) m FROM %s WHERE %s LIKE ?" % (column, table, column), (head + "%",))
    seq = 0
    if r and r["m"]:
        tail = str(r["m"])[len(head):]
        digits = "".join(ch for ch in tail if ch.isdigit())
        seq = int(digits) if digits else 0
    return mes.doc_no(kind, today(), seq + 1)


def user_name(cn, username):
    if not username:
        return ""
    u = one(cn, "SELECT display_name FROM users WHERE username=?", (username,))
    return u["display_name"] if u else username


def name_map(cn):
    return {r["username"]: r["display_name"] for r in rows(cn, "SELECT username,display_name FROM users")}


# 产量口径：工单末工序报工视为产出，避免逐工序报工重复计数
LAST_OP = ("FROM prod_reports r JOIN (SELECT wo_no w, MAX(seq) s FROM wo_operations GROUP BY wo_no) t"
           " ON t.w=r.wo_no AND t.s=r.seq ")


def out_qty(cn, like=None, wo=None):
    sql = "SELECT COALESCE(SUM(r.good_qty),0) g, COALESCE(SUM(r.ng_qty),0) n " + LAST_OP + "WHERE 1=1"
    args = []
    if like:
        sql += " AND r.reported_at LIKE ?"
        args.append(like)
    if wo:
        sql += " AND r.wo_no=?"
        args.append(wo)
    return one(cn, sql, tuple(args))


# ---------------------------------------------------------------- 视图
def mat_view(r, stock=None):
    oh = float(r["on_hand"] or 0) if stock is None else float(stock)
    safety = float(r["safety_stock"] or 0)
    return {
        "code": r["code"], "name": r["name"], "spec": r["spec"], "unit": r["unit"],
        "category": r["category"], "type": r["mtype"], "abc": r["abc"],
        "safetyStock": mes.r2(safety), "onHand": mes.r2(oh), "stdCost": mes.r2(r["std_cost"]),
        "leadDays": r["lead_days"], "status": r["status"], "remark": r["remark"],
        "short": mes.r2(max(0.0, safety - oh)), "belowSafety": oh < safety,
        "amount": mes.r2(oh * float(r["std_cost"] or 0)), "updatedAt": r["updated_at"],
    }


def wo_view(r, ops=None, kit=None, names=None):
    names = names or {}
    ops = ops if ops is not None else []
    plan_qty = float(r["qty"] or 0)
    reported = sum(float(o["good_qty"] or 0) + float(o["ng_qty"] or 0) for o in ops)
    good = sum(float(o["good_qty"] or 0) for o in ops)
    ng = sum(float(o["ng_qty"] or 0) for o in ops)
    std = sum(float(o["std_min"] or 0) for o in ops)
    actual = sum(float(o["actual_min"] or 0) for o in ops)
    done = sum(1 for o in ops if o["status"] == "已完成")
    return {
        "no": r["no"], "materialCode": r["material_code"], "materialName": r.get("material_name") or "",
        "qty": mes.r2(plan_qty), "workshop": r["workshop"], "line": r["line"],
        "priority": r["priority"], "status": r["status"],
        "planStart": r["plan_start"], "planEnd": r["plan_end"],
        "actualStart": r["actual_start"], "actualEnd": r["actual_end"],
        "routingCode": r["routing_code"], "bomCode": r["bom_code"],
        "salesNo": r["sales_no"], "customer": r["customer"],
        "planner": r["planner"], "plannerName": names.get(r["planner"], r["planner"]),
        "owner": r["owner"], "ownerName": names.get(r["owner"], r["owner"]),
        "team": r["team"], "remark": r["remark"], "createdAt": r["created_at"],
        "reportedQty": mes.r2(reported), "goodQty": mes.r2(good), "ngQty": mes.r2(ng),
        "progress": mes.progress(plan_qty, reported), "opCount": len(ops), "opDone": done,
        "stdMin": mes.r2(std), "actualMin": mes.r2(actual),
        "eff": mes.manpower_efficiency(std, actual) if actual else 0.0,
        "dueState": mes.due_state(r["plan_end"], today()),
        "nextTargets": mes.wo_next(r["status"]),
        "canAdvance": [x for x in mes.wo_next(r["status"])
                       if not mes.wo_gate(x, wo_ctx_light(r, ops))],
        "kitRate": None if kit is None else kit.get("rate"),
        "kitShort": None if kit is None else len(kit.get("shortages") or []),
        "batchNo": r.get("batch_no") or "",
    }


def wo_ctx_light(r, ops):
    """列表页用的轻量闸口上下文（不查库，只做状态层面判断）。"""
    reported = sum(float(o["good_qty"] or 0) + float(o["ng_qty"] or 0) for o in ops)
    return {
        "status": r["status"], "qty": r["qty"], "reportedQty": reported,
        "opsDone": bool(ops) and all(o["status"] == "已完成" for o in ops),
        "kitRate": 1.0, "bomOk": True, "routingOk": True,
        "faiPass": True, "equipOk": True, "hasOperator": True, "inspPass": True,
        "batchNo": r.get("batch_no") or "", "defects": 0,
    }


def wo_ctx(cn, r):
    """完整闸口上下文：查工序、用料、首件、完工检、设备、批次、未处置不良。"""
    ops = rows(cn, "SELECT * FROM wo_operations WHERE wo_no=? ORDER BY seq", (r["no"],))
    mats = rows(cn, "SELECT * FROM wo_materials WHERE wo_no=?", (r["no"],))
    kit_items = []
    for m in mats:
        stock = one(cn, "SELECT COALESCE(SUM(qty),0) q FROM stocks WHERE material_code=?", (m["material_code"],))
        kit_items.append({"materialCode": m["material_code"],
                          "materialName": (one(cn, "SELECT name FROM materials WHERE code=?",
                                               (m["material_code"],)) or {}).get("name", ""),
                          "need": m["need_qty"],
                          "avail": float(stock["q"]) + float(m["issued_qty"] or 0),
                          "unit": m["unit"]})
    kit = mes.kit_rate(kit_items)
    fai = one(cn, "SELECT * FROM inspections WHERE wo_no=? AND type='首件' ORDER BY inspected_at DESC",
              (r["no"],))
    fqc = one(cn, "SELECT * FROM inspections WHERE wo_no=? AND type='完工检' ORDER BY inspected_at DESC",
              (r["no"],))
    b = one(cn, "SELECT no FROM batches WHERE wo_no=? ORDER BY produced_at DESC", (r["no"],))
    if ops:
        equip_bad = one(cn, "SELECT COUNT(*) c FROM equipment WHERE code IN (%s)"
                            " AND status IN ('故障','保养','停机')" % ",".join(["?"] * len(ops)),
                        tuple(o["equipment"] for o in ops))
    else:
        equip_bad = {"c": 0}
    defects = one(cn, "SELECT COUNT(*) c FROM defects WHERE wo_no=? AND disposition IN ('待处置','返修')",
                  (r["no"],))
    routing = one(cn, "SELECT * FROM routings WHERE code=?", (r["routing_code"],))
    bom = one(cn, "SELECT COUNT(*) c FROM bom_items WHERE bom_code=?", (r["bom_code"],))
    return {
        "status": r["status"], "qty": r["qty"], "kitRate": kit["rate"],
        "bomOk": bool(bom and bom["c"] > 0), "routingOk": bool(routing and routing["status"] == "已发布"),
        "faiPass": bool(fai and fai["result"] == "合格"),
        "equipOk": not (equip_bad and equip_bad["c"] > 0),
        "hasOperator": bool(r["team"] or r["owner"]),
        "opsDone": bool(ops) and all(o["status"] == "已完成" for o in ops),
        "reportedQty": sum(float(o["good_qty"] or 0) + float(o["ng_qty"] or 0) for o in ops),
        "inspPass": bool(fqc and fqc["result"] in ("合格", "让步接收")),
        "batchNo": (b or {}).get("no", ""),
        "defects": (defects or {}).get("c", 0) if defects else 0,
        "kit": kit, "ops": ops,
    }


def equip_view(r, metrics=None, plan=None):
    m = metrics or {}
    plan = plan or {}
    o = mes.oee(m.get("plan_min", 0), m.get("run_min", 0), m.get("ideal_cycle", 0),
                m.get("output", 0), m.get("good", 0))
    return {
        "code": r["code"], "name": r["name"], "type": r["type"], "line": r["line"],
        "station": r["station"], "vendor": r["vendor"], "model": r["model"],
        "buyDate": r["buy_date"], "status": r["status"], "runHours": mes.r2(r["run_hours"]),
        "downMin": mes.r2(r["down_min"]), "failures": r["failures"],
        "lastMaintAt": r["last_maint_at"], "nextMaintAt": r["next_maint_at"],
        "maintState": mes.maint_state(r["next_maint_at"], today(), 7),
        "oeeTarget": mes.r2(r["oee_target"]), "remark": r["remark"],
        "oee": o, "oeeLevel": mes.oee_level(o["oee"], r["oee_target"] or 0.85),
        "planCode": plan.get("code", ""), "planType": plan.get("type", ""),
        "openRepairs": int(m.get("open_repairs") or 0),
        "health": mes.equip_health(r["status"], 1 if mes.maint_state(r["next_maint_at"], today(), 7) == "逾期" else 0,
                                   m.get("open_repairs") or 0),
    }


def insp_view(r, names=None):
    names = names or {}
    rate = mes.ratio(r["defect_qty"], r["sample_qty"], 4)
    return {
        "no": r["no"], "woNo": r["wo_no"], "type": r["type"], "seq": r["seq"],
        "process": r["process"], "sampleQty": mes.r2(r["sample_qty"]),
        "defectQty": mes.r2(r["defect_qty"]), "defectRate": rate,
        "result": r["result"], "standard": r["standard"],
        "inspector": r["inspector"], "inspectorName": names.get(r["inspector"], r["inspector"]),
        "inspectedAt": r["inspected_at"], "remark": r["remark"],
    }


def batch_view(r):
    return {
        "no": r["no"], "materialCode": r["material_code"], "materialName": r.get("material_name") or "",
        "woNo": r["wo_no"], "qty": mes.r2(r["qty"]), "goodQty": mes.r2(r["good_qty"]),
        "workshop": r["workshop"], "line": r["line"], "producedAt": r["produced_at"],
        "expireAt": r["expire_at"], "status": r["status"], "parentBatch": r["parent_batch"],
        "remark": r["remark"],
    }

def andon_view(r, names=None):
    names = names or {}
    return {
        "id": r["id"], "no": r["no"], "line": r["line"], "station": r["station"],
        "type": r["type"], "level": r["level"], "status": r["status"],
        "reporter": r["reporter"], "reporterName": names.get(r["reporter"], r["reporter"]),
        "createdAt": r["created_at"], "closedAt": r["closed_at"], "remark": r["remark"],
        "minutes": mes.minutes_between(r["created_at"], r["closed_at"]) if r["closed_at"] else
        mes.minutes_between(r["created_at"], now()),
    }


# ---------------------------------------------------------------- 认证
def api_login(cn, user, body, query):
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    u = one(cn, "SELECT * FROM users WHERE username=?", (username,))
    if not u or u["password"] != db.sha256(password):
        raise ApiError("用户名或密码不正确", 401)
    if u["status"] != "在职":
        raise ApiError("账号已停用，请联系管理员", 403)
    token = secrets.token_urlsafe(24)
    cn.execute("INSERT INTO sessions(token,username,created_at) VALUES(?,?,?)", (token, username, now()))
    op(cn, username, "登录", "会话建立")
    cn.commit()
    return {"token": token, "username": username, "displayName": u["display_name"],
            "role": u["role"], "roleLabel": mes.ROLE_LABEL.get(u["role"], u["role"]),
            "perms": sorted(mes._PERM.get(u["role"], {"read"}))}


def api_logout(cn, token):
    cn.execute("DELETE FROM sessions WHERE token=?", (token,))
    cn.commit()
    return {"loggedOut": True}


def api_me(cn, user):
    return {"username": user["username"], "displayName": user["displayName"], "role": user["role"],
            "roleLabel": user["roleLabel"], "authType": user["authType"],
            "perms": sorted(mes._PERM.get(user["role"], {"read"}))}


def api_bootstrap(cn, user):
    names = name_map(cn)
    month = today()[:7]
    wos = rows(cn, "SELECT * FROM work_orders")
    active = [w for w in wos if w["status"] in ("已下达", "已开工")]
    m_wos = [w for w in wos if str(w["plan_start"]).startswith(month)]
    t_out = out_qty(cn, today() + "%")
    m_out = out_qty(cn, month + "%")
    oee_row = one(cn, "SELECT COALESCE(SUM(plan_min),0) p, COALESCE(SUM(run_min),0) r,"
                      " COALESCE(SUM(output),0) o, COALESCE(SUM(good),0) g, COALESCE(AVG(ideal_cycle),0) c"
                      " FROM equip_metrics WHERE day >= ?", (mes.add_days(today(), -6),))
    eq = rows(cn, "SELECT * FROM equipment")
    abnormal = [e for e in eq if e["status"] in ("故障", "保养", "停机")]
    maint_due = [e for e in eq if mes.maint_state(e["next_maint_at"], today(), 7) in ("逾期", "临期")]

    # 齐套预警（仅未下达与已下达）
    kit_warn = []
    for w in wos:
        if w["status"] not in ("草稿", "已下达"):
            continue
        ctx = wo_ctx(cn, w)
        if ctx["kitRate"] < 1.0:
            kit_warn.append({"no": w["no"], "materialName": (one(
                cn, "SELECT name FROM materials WHERE code=?", (w["material_code"],)) or {}).get("name", ""),
                "rate": ctx["kitRate"], "short": len(ctx["kit"]["shortages"])})

    # 待完工检
    pending = []
    for w in wos:
        if w["status"] == "已完工":
            fqc = one(cn, "SELECT * FROM inspections WHERE wo_no=? AND type='完工检'"
                          " AND result IN ('合格','让步接收')", (w["no"],))
            if not fqc:
                pending.append(w)

    overdue = [w for w in wos if w["plan_end"] and w["plan_end"] < today()
               and w["status"] not in ("已入库", "已关闭", "已取消")]

    o = mes.oee(oee_row["p"], oee_row["r"], oee_row["c"], oee_row["o"], oee_row["g"])
    yield_rate = mes.yield_rate(m_out["g"], float(m_out["g"] or 0) + float(m_out["n"] or 0))

    # 近 14 天趋势
    trend = []
    for i in range(13, -1, -1):
        day = mes.add_days(today(), -i)
        r = out_qty(cn, day + "%")
        plan = one(cn, "SELECT COALESCE(SUM(qty),0) q FROM work_orders WHERE plan_start <= ? AND plan_end >= ?"
                       " AND status NOT IN ('已取消')", (day, day))
        trend.append({"day": day[5:], "output": mes.r2(r["g"]), "ng": mes.r2(r["n"]),
                      "plan": mes.r2(plan["q"])})

    # 产线负荷
    lines = []
    for ln in rows(cn, "SELECT * FROM lines ORDER BY code"):
        w_line = [w for w in wos if w["line"] == ln["code"] and w["status"] in ("已下达", "已开工", "已完工")]
        std = 0.0
        for w in w_line:
            std += float(one(cn, "SELECT COALESCE(SUM(std_min),0) s FROM wo_operations WHERE wo_no=?",
                             (w["no"],))["s"] or 0)
        cap = 480 * 3 * 22
        lines.append({"code": ln["code"], "name": ln["name"], "workshop": ln["workshop"],
                      "status": ln["status"], "taktSec": ln["takt_sec"],
                      "wip": len([w for w in w_line if w["status"] in ("已下达", "已开工")]),
                      "orderCount": len(w_line), "stdMin": mes.r2(std),
                      "load": mes.capacity_load(std, cap), "capacityMin": cap})

    status_dist = {}
    for w in wos:
        status_dist[w["status"]] = status_dist.get(w["status"], 0) + 1

    todo = []
    for w in overdue[:3]:
        todo.append({"type": "逾期工单", "no": w["no"], "title": "%s 计划完成 %s" % (w["material_code"], w["plan_end"]),
                     "level": "high", "page": "orders"})
    for w in pending[:3]:
        todo.append({"type": "待完工检", "no": w["no"], "title": "完工待检验", "level": "mid", "page": "quality"})
    for k in kit_warn[:2]:
        todo.append({"type": "齐套不足", "no": k["no"], "title": "齐套率 %.0f%%" % (k["rate"] * 100),
                     "level": "mid", "page": "orders"})
    for e in abnormal[:2]:
        todo.append({"type": "设备异常", "no": e["code"], "title": "%s 状态 %s" % (e["name"], e["status"]),
                     "level": "high", "page": "equipment"})

    alarms = []
    for e in abnormal:
        alarms.append({"level": "high" if e["status"] == "故障" else "mid",
                       "text": "%s（%s）%s" % (e["name"], e["code"], e["status"]), "page": "equipment"})
    for e in maint_due[:3]:
        alarms.append({"level": "mid" if mes.maint_state(e["next_maint_at"], today(), 7) == "临期" else "high",
                       "text": "%s 保养%s（%s）" % (e["name"], mes.maint_state(e["next_maint_at"], today(), 7),
                                                e["next_maint_at"]), "page": "equipment"})
    for a in rows(cn, "SELECT * FROM andon WHERE status<>'已关闭' ORDER BY created_at DESC LIMIT 3"):
        alarms.append({"level": "high" if a["level"] == "紧急" else "mid",
                       "text": "%s %s 呼叫：%s" % (a["line"], a["type"], a["remark"]), "page": "board"})
    for d in rows(cn, "SELECT * FROM defects WHERE disposition='待处置' LIMIT 3"):
        alarms.append({"level": "mid", "text": "%s 不良待处置" % d["wo_no"], "page": "quality"})

    return {
        "user": api_me(cn, user),
        "kpi": {
            "wip": len(active), "todayOutput": mes.r2(t_out["g"]),
            "monthOutput": mes.r2(m_out["g"]),
            "monthPlan": mes.r2(sum(float(w["qty"] or 0) for w in m_wos)),
            "oee": o["oee"], "oeeLevel": mes.oee_level(o["oee"], 0.85),
            "yieldRate": yield_rate, "equipAbnormal": len(abnormal),
            "maintDue": len(maint_due), "kitWarn": len(kit_warn),
            "pendingInsp": len(pending), "overdue": len(overdue),
            "abnormalDefects": one(cn, "SELECT COUNT(*) c FROM defects WHERE disposition='待处置'")["c"],
        },
        "trend": trend,
        "lines": lines,
        "statusDist": [{"status": k, "count": v} for k, v in status_dist.items()],
        "todo": todo[:8],
        "alarms": alarms[:8],
        "andon": [andon_view(a, names) for a in rows(
            cn, "SELECT * FROM andon ORDER BY status='已关闭', created_at DESC LIMIT 6")],
        "rules": rows(cn, "SELECT * FROM rules ORDER BY category, code"),
    }


# ---------------------------------------------------------------- 车间与主数据
def api_workshops(cn, user):
    out = []
    for w in rows(cn, "SELECT * FROM workshops ORDER BY code"):
        ws_lines = rows(cn, "SELECT * FROM lines WHERE workshop=?", (w["code"],))
        wip = one(cn, "SELECT COUNT(*) c FROM work_orders WHERE workshop=? AND status IN ('已下达','已开工')",
                  (w["code"],))["c"]
        out.append({"code": w["code"], "name": w["name"], "manager": w["manager"],
                    "capacityMin": mes.r2(w["capacity_min"]), "status": w["status"],
                    "remark": w["remark"], "lineCount": len(ws_lines), "wip": wip})
    return {"list": out}


def api_lines(cn, user):
    out = []
    for ln in rows(cn, "SELECT * FROM lines ORDER BY code"):
        wip = one(cn, "SELECT COUNT(*) c FROM work_orders WHERE line=? AND status IN ('已下达','已开工')",
                  (ln["code"],))["c"]
        out.append({"code": ln["code"], "name": ln["name"], "workshop": ln["workshop"],
                    "leader": ln["leader"], "taktSec": mes.r2(ln["takt_sec"]),
                    "status": ln["status"], "wip": wip,
                    "stationCount": one(cn, "SELECT COUNT(*) c FROM stations WHERE line=?",
                                        (ln["code"],))["c"]})
    return {"list": out}


def api_stations(cn, user, query):
    line = q1(query, "line")
    sql, args = "SELECT * FROM stations", []
    if line:
        sql += " WHERE line=?"
        args.append(line)
    sql += " ORDER BY line, seq"
    out = [{"code": s["code"], "name": s["name"], "line": s["line"], "seq": s["seq"],
            "type": s["type"], "status": s["status"]} for s in rows(cn, sql, tuple(args))]
    return {"list": out}


def api_teams(cn, user):
    out = []
    for tm in rows(cn, "SELECT * FROM teams ORDER BY code"):
        out.append({"code": tm["code"], "name": tm["name"], "workshop": tm["workshop"],
                    "leader": tm["leader"], "members": tm["members"], "shift": tm["shift"],
                    "memberCount": len([x for x in str(tm["members"]).split("、") if x.strip()])})
    return {"list": out}


def api_materials(cn, user, query):
    kw = q1(query, "kw").strip()
    mtype = q1(query, "type")
    sql = "SELECT * FROM materials WHERE 1=1"
    args = []
    if kw:
        sql += " AND (code LIKE ? OR name LIKE ? OR spec LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if mtype:
        sql += " AND mtype=?"
        args.append(mtype)
    sql += " ORDER BY mtype DESC, code"
    lst = [mat_view(r) for r in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst),
            "summary": {
                "count": len(lst),
                "belowSafety": len([x for x in lst if x["belowSafety"]]),
                "amount": mes.r2(sum(x["amount"] for x in lst)),
                "finished": len([x for x in lst if x["type"] == "成品"]),
            }}


@write_op
def api_material_create(cn, user, body):
    require(user, "write")
    code = str(body.get("code") or "").strip()
    name = str(body.get("name") or "").strip()
    if not code or not name:
        raise ApiError("物料编码与名称不能为空")
    if one(cn, "SELECT 1 x FROM materials WHERE code=?", (code,)):
        raise ApiError("物料编码 %s 已存在" % code, 409)
    dup = rows(cn, "SELECT code,name FROM materials WHERE name=?", (name,))
    if dup:
        raise ApiError("同名物料已存在：%s" % dup[0]["code"], 409, dups=dup)
    cn.execute("INSERT INTO materials(code,name,spec,unit,category,mtype,abc,safety_stock,on_hand,std_cost,"
               "lead_days,status,remark,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, name, body.get("spec") or "", body.get("unit") or "件",
                body.get("category") or "", body.get("type") or "原材料", "C",
                float(body.get("safetyStock") or 0), float(body.get("onHand") or 0),
                float(body.get("stdCost") or 0), int(body.get("leadDays") or 7),
                "启用", body.get("remark") or "", now()))
    op(cn, user["username"], "新建物料", code)
    emit(cn, "material.created", "material", code, {"code": code, "name": name}, user["username"])
    return {"code": code, "name": name, "created": True}


def api_material_detail(cn, user, code):
    r = one(cn, "SELECT * FROM materials WHERE code=?", (code,))
    if not r:
        raise ApiError("物料 %s 不存在" % code, 404)
    stock_rows = rows(cn, "SELECT * FROM stocks WHERE material_code=? AND qty>0 ORDER BY batch_no", (code,))
    bom = one(cn, "SELECT * FROM boms WHERE material_code=? ORDER BY version DESC", (code,))
    bom_items = rows(cn, "SELECT bi.*, m.name, m.unit FROM bom_items bi LEFT JOIN materials m"
                         " ON m.code=bi.component WHERE bi.bom_code=? ORDER BY bi.seq",
                     (bom["code"] if bom else "",))
    routing = one(cn, "SELECT * FROM routings WHERE material_code=? ORDER BY version DESC", (code,))
    steps = rows(cn, "SELECT * FROM routing_steps WHERE routing_code=? ORDER BY seq",
                 (routing["code"] if routing else "",))
    orders = rows(cn, "SELECT * FROM work_orders WHERE material_code=? ORDER BY created_at DESC LIMIT 8", (code,))
    batches = rows(cn, "SELECT * FROM batches WHERE material_code=? ORDER BY produced_at DESC LIMIT 8", (code,))
    return {
        "material": mat_view(r),
        "stock": [{"batch": s["batch_no"], "warehouse": s["warehouse"], "qty": mes.r2(s["qty"]),
                   "updatedAt": s["updated_at"]} for s in stock_rows],
        "bom": None if not bom else {
            "code": bom["code"], "version": bom["version"], "status": bom["status"],
            "items": [{"component": b["component"], "name": b.get("name") or "",
                       "qty": mes.r2(b["qty"]), "unit": b.get("unit") or "",
                       "lossRate": b["loss_rate"]} for b in bom_items],
        },
        "routing": None if not routing else {
            "code": routing["code"], "version": routing["version"], "name": routing["name"],
            "status": routing["status"],
            "steps": [{"seq": s["seq"], "process": s["process"], "station": s["station"],
                       "equipType": s["equip_type"], "stdMin": mes.r2(s["std_min"]),
                       "cycleSec": mes.r2(s["cycle_sec"]), "isKey": bool(s["is_key"])} for s in steps],
        },
        "orders": [{"no": o["no"], "qty": mes.r2(o["qty"]), "status": o["status"],
                    "planEnd": o["plan_end"]} for o in orders],
        "batches": [batch_view(b) for b in batches],
    }


@write_op
def api_material_update(cn, user, code, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM materials WHERE code=?", (code,))
    if not r:
        raise ApiError("物料 %s 不存在" % code, 404)
    fields = {"name": "name", "spec": "spec", "unit": "unit", "category": "category",
              "type": "mtype", "safetyStock": "safety_stock", "stdCost": "std_cost",
              "leadDays": "lead_days", "status": "status", "remark": "remark"}
    sets, args = [], []
    for k, col in fields.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(body[k])
    if not sets:
        raise ApiError("没有可更新的字段")
    sets.append("updated_at=?")
    args.append(now())
    args.append(code)
    cn.execute("UPDATE materials SET %s WHERE code=?" % ",".join(sets), tuple(args))
    op(cn, user["username"], "更新物料", code)
    return {"updated": True, "code": code}


def api_boms(cn, user, query):
    kw = q1(query, "kw").strip()
    sql = ("SELECT b.*, m.name material_name FROM boms b LEFT JOIN materials m ON m.code=b.material_code")
    args = []
    if kw:
        sql += " WHERE b.code LIKE ? OR b.material_code LIKE ? OR m.name LIKE ?"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY b.code"
    out = []
    for b in rows(cn, sql, tuple(args)):
        items = rows(cn, "SELECT COUNT(*) c, COALESCE(SUM(qty),0) q FROM bom_items WHERE bom_code=?",
                     (b["code"],))
        out.append({"code": b["code"], "materialCode": b["material_code"],
                    "materialName": b.get("material_name") or "", "version": b["version"],
                    "status": b["status"], "itemCount": items[0]["c"],
                    "totalQty": mes.r2(items[0]["q"]), "updatedAt": b["updated_at"]})
    return {"list": out, "total": len(out)}


def api_bom_detail(cn, user, code):
    b = one(cn, "SELECT * FROM boms WHERE code=?", (code,))
    if not b:
        raise ApiError("BOM %s 不存在" % code, 404)
    items = rows(cn, "SELECT bi.*, m.name, m.unit, m.on_hand, m.std_cost FROM bom_items bi"
                     " LEFT JOIN materials m ON m.code=bi.component WHERE bi.bom_code=? ORDER BY bi.seq",
                 (code,))
    return {"code": b["code"], "materialCode": b["material_code"], "version": b["version"],
            "status": b["status"], "remark": b["remark"],
            "items": [{"seq": x["seq"], "component": x["component"], "name": x.get("name") or "",
                       "qty": mes.r2(x["qty"]), "unit": x.get("unit") or "",
                       "lossRate": x["loss_rate"], "onHand": mes.r2(x.get("on_hand") or 0),
                       "cost": mes.r2(x.get("std_cost") or 0)} for x in items]}


def api_routings(cn, user, query):
    kw = q1(query, "kw").strip()
    sql = ("SELECT r.*, m.name material_name FROM routings r LEFT JOIN materials m ON m.code=r.material_code")
    args = []
    if kw:
        sql += " WHERE r.code LIKE ? OR r.material_code LIKE ? OR m.name LIKE ?"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY r.code"
    out = []
    for r in rows(cn, sql, tuple(args)):
        st = rows(cn, "SELECT COALESCE(SUM(std_min),0) s, COUNT(*) c FROM routing_steps WHERE routing_code=?",
                  (r["code"],))
        out.append({"code": r["code"], "materialCode": r["material_code"],
                    "materialName": r.get("material_name") or "", "version": r["version"],
                    "name": r["name"], "status": r["status"], "stepCount": st[0]["c"],
                    "stdMin": mes.r2(st[0]["s"]), "updatedAt": r["updated_at"]})
    return {"list": out, "total": len(out)}


def api_routing_detail(cn, user, code):
    r = one(cn, "SELECT * FROM routings WHERE code=?", (code,))
    if not r:
        raise ApiError("工艺路线 %s 不存在" % code, 404)
    steps = rows(cn, "SELECT * FROM routing_steps WHERE routing_code=? ORDER BY seq", (code,))
    return {"code": r["code"], "materialCode": r["material_code"], "version": r["version"],
            "name": r["name"], "status": r["status"],
            "steps": [{"seq": x["seq"], "process": x["process"], "station": x["station"],
                       "equipType": x["equip_type"], "stdMin": mes.r2(x["std_min"]),
                       "cycleSec": mes.r2(x["cycle_sec"]), "isKey": bool(x["is_key"])} for x in steps],
            "balance": mes.line_balance([x["std_min"] for x in steps]),
            "bottleneck": mes.bottleneck([x["std_min"] for x in steps])}


# ---------------------------------------------------------------- 生产工单
def api_orders(cn, user, query):
    status = q1(query, "status")
    kw = q1(query, "kw").strip()
    line = q1(query, "line")
    prio = q1(query, "priority")
    overdue = q1(query, "overdue") in ("1", "true")
    sql = ("SELECT w.*, m.name material_name FROM work_orders w LEFT JOIN materials m ON m.code=w.material_code"
           " WHERE 1=1")
    args = []
    if status and status != "全部":
        sql += " AND w.status=?"
        args.append(status)
    if kw:
        sql += " AND (w.no LIKE ? OR w.material_code LIKE ? OR w.customer LIKE ? OR m.name LIKE ?)"
        args += ["%" + kw + "%"] * 4
    if line and line != "全部":
        sql += " AND w.line=?"
        args.append(line)
    if prio and prio != "全部":
        sql += " AND w.priority=?"
        args.append(prio)
    sql += " ORDER BY CASE w.status WHEN '已开工' THEN 0 WHEN '已下达' THEN 1 WHEN '已完工' THEN 2"
    sql += " WHEN '草稿' THEN 3 ELSE 4 END, w.plan_end, w.no"
    names = name_map(cn)
    out = []
    for r in rows(cn, sql, tuple(args)):
        ops = rows(cn, "SELECT * FROM wo_operations WHERE wo_no=? ORDER BY seq", (r["no"],))
        v = wo_view(r, ops, None, names)
        if overdue and v["dueState"] != "逾期":
            continue
        out.append(v)
    dist = {x["status"]: 0 for x in rows(cn, "SELECT DISTINCT status FROM work_orders")}
    for r in rows(cn, "SELECT status, COUNT(*) c FROM work_orders GROUP BY status"):
        dist[r["status"]] = r["c"]
    return {"list": out, "total": len(out), "statusDist": dist}


@write_op
def api_order_create(cn, user, body):
    require(user, "write")
    mat = str(body.get("materialCode") or "").strip()
    m = one(cn, "SELECT * FROM materials WHERE code=?", (mat,))
    if not m:
        raise ApiError("物料 %s 不存在" % mat, 404)
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("计划数量必须大于 0")
    line = str(body.get("line") or "").strip()
    if not line:
        line = (one(cn, "SELECT line FROM lines ORDER BY code") or {}).get("line", "LN-301")
    ln = one(cn, "SELECT * FROM lines WHERE code=?", (line,))
    if not ln:
        raise ApiError("产线 %s 不存在" % line, 404)
    routing = one(cn, "SELECT * FROM routings WHERE material_code=? AND status='已发布'", (mat,))
    bom = one(cn, "SELECT * FROM boms WHERE material_code=? AND status='已发布'", (mat,))
    if not routing:
        raise ApiError("物料 %s 没有已发布的工艺路线，不能下单" % mat)
    if not bom:
        raise ApiError("物料 %s 没有已发布的 BOM，不能下单" % mat)
    no = next_no(cn, "WO", "work_orders")
    plan_start = str(body.get("planStart") or today())[:10]
    span = int(body.get("spanDays") or (3 if qty < 100 else 5))
    plan_end = str(body.get("planEnd") or mes.add_days(plan_start, span))[:10]
    cn.execute("INSERT INTO work_orders(no,material_code,qty,workshop,line,priority,status,plan_start,plan_end,"
               "routing_code,bom_code,sales_no,customer,planner,owner,team,remark,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, mat, qty, ln["workshop"], line, body.get("priority") or "普通", "草稿",
                plan_start, plan_end, routing["code"], bom["code"],
                body.get("salesNo") or "", body.get("customer") or "",
                user["username"], "", "", body.get("remark") or "", now()))
    steps = rows(cn, "SELECT * FROM routing_steps WHERE routing_code=? ORDER BY seq", (routing["code"],))
    for s in steps:
        eq = one(cn, "SELECT code FROM equipment WHERE type=? AND line=? ORDER BY code", (s["equip_type"], line))
        if not eq:
            eq = one(cn, "SELECT code FROM equipment WHERE type=? ORDER BY code", (s["equip_type"],))
        cn.execute("INSERT INTO wo_operations(wo_no,seq,process,station,equipment,plan_qty,good_qty,ng_qty,"
                   "std_min,actual_min,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (no, s["seq"], s["process"], s["station"], (eq or {}).get("code", ""),
                    qty, 0, 0, round(float(s["std_min"]) * qty, 2), 0, "待开工"))
    for b in rows(cn, "SELECT * FROM bom_items WHERE bom_code=? ORDER BY seq", (bom["code"],)):
        need = round(float(b["qty"]) * qty * (1 + float(b["loss_rate"] or 0)), 2)
        unit = (one(cn, "SELECT unit FROM materials WHERE code=?", (b["component"],)) or {}).get("unit", "件")
        cn.execute("INSERT INTO wo_materials(wo_no,material_code,need_qty,issued_qty,unit,state)"
                   " VALUES(?,?,?,?,?,?)", (no, b["component"], need, 0, unit, "待齐套"))
    op(cn, user["username"], "新建工单", "%s %s×%g" % (no, mat, qty))
    emit(cn, "wo.created", "work_order", no,
         {"no": no, "materialCode": mat, "qty": qty, "line": line, "status": "草稿"}, user["username"])
    return {"no": no, "status": "草稿", "qty": qty, "line": line,
            "routingCode": routing["code"], "bomCode": bom["code"], "opCount": len(steps)}


def api_order_detail(cn, user, no):
    r = one(cn, "SELECT w.*, m.name material_name, m.unit, m.spec FROM work_orders w"
                " LEFT JOIN materials m ON m.code=w.material_code WHERE w.no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    names = name_map(cn)
    ctx = wo_ctx(cn, r)
    ops = []
    for o in ctx["ops"]:
        rep = rows(cn, "SELECT * FROM prod_reports WHERE wo_no=? AND seq=? ORDER BY reported_at", (no, o["seq"]))
        ops.append({
            "id": o["id"], "seq": o["seq"], "process": o["process"], "station": o["station"],
            "equipment": o["equipment"], "planQty": mes.r2(o["plan_qty"]),
            "goodQty": mes.r2(o["good_qty"]), "ngQty": mes.r2(o["ng_qty"]),
            "stdMin": mes.r2(o["std_min"]), "actualMin": mes.r2(o["actual_min"]),
            "status": o["status"], "operator": o["operator"],
            "operatorName": names.get(o["operator"], o["operator"]),
            "startAt": o["start_at"], "endAt": o["end_at"],
            "progress": mes.progress(o["plan_qty"], float(o["good_qty"] or 0) + float(o["ng_qty"] or 0)),
            "reportCount": len(rep),
        })
    mats = []
    for m in rows(cn, "SELECT wm.*, m.name, m.spec FROM wo_materials wm LEFT JOIN materials m"
                      " ON m.code=wm.material_code WHERE wm.wo_no=? ORDER BY wm.id", (no,)):
        stock = one(cn, "SELECT COALESCE(SUM(qty),0) q FROM stocks WHERE material_code=?", (m["material_code"],))
        mats.append({"materialCode": m["material_code"], "name": m.get("name") or "",
                     "spec": m.get("spec") or "", "need": mes.r2(m["need_qty"]),
                     "issued": mes.r2(m["issued_qty"]), "unit": m["unit"],
                     "onHand": mes.r2(stock["q"]), "state": m["state"],
                     "short": mes.short_qty(m["need_qty"], m["issued_qty"])})
    v = wo_view(r, ctx["ops"], ctx["kit"], names)
    v["materialSpec"] = r.get("spec") or ""
    v["unit"] = r.get("unit") or ""
    v["operations"] = ops
    v["materials"] = mats
    v["kit"] = ctx["kit"]
    v["gate"] = {t: mes.wo_gate(t, ctx) for t in mes.wo_next(r["status"])}
    v["inspections"] = [insp_view(x, names) for x in rows(
        cn, "SELECT * FROM inspections WHERE wo_no=? ORDER BY inspected_at", (no,))]
    v["defects"] = [{"id": d["id"], "code": d["defect_code"], "qty": mes.r2(d["qty"]),
                     "process": d["process"], "disposition": d["disposition"],
                     "occurAt": d["occur_at"], "inspectionNo": d["inspection_no"]}
                    for d in rows(cn, "SELECT * FROM defects WHERE wo_no=? ORDER BY occur_at", (no,))]
    v["reports"] = [{"no": x["no"], "seq": x["seq"], "process": x["process"], "qty": mes.r2(x["qty"]),
                     "goodQty": mes.r2(x["good_qty"]), "ngQty": mes.r2(x["ng_qty"]),
                     "actualMin": mes.r2(x["actual_min"]), "operator": x["operator"],
                     "shift": x["shift"], "reportedAt": x["reported_at"]}
                    for x in rows(cn, "SELECT * FROM prod_reports WHERE wo_no=? ORDER BY reported_at DESC",
                                  (no,))]
    v["batch"] = batch_view(one(cn, "SELECT b.*, m.name material_name FROM batches b"
                                    " LEFT JOIN materials m ON m.code=b.material_code"
                                    " WHERE b.wo_no=? ORDER BY b.produced_at DESC", (no,))) \
        if one(cn, "SELECT 1 x FROM batches WHERE wo_no=?", (no,)) else None
    return v


@write_op
def api_order_stage(cn, user, no, body):
    target = str(body.get("target") or "").strip()
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    if target == "已下达" or target == "已关闭":
        require(user, "approve")
    else:
        require(user, "write")
    if not mes.can_move_wo(r["status"], target):
        raise ApiError("工单状态不能从「%s」推进到「%s」" % (r["status"], target))
    ctx = wo_ctx(cn, r)
    miss = mes.wo_gate(target, ctx)
    if miss:
        raise ApiError("闸口未通过：" + "；".join(miss), 400, missing=miss)
    sets, args = ["status=?"], [target]
    if target == "已开工" and not r["actual_start"]:
        sets.append("actual_start=?")
        args.append(now())
    if target == "已完工":
        sets.append("actual_end=?")
        args.append(now())
    args.append(no)
    cn.execute("UPDATE work_orders SET %s WHERE no=?" % ",".join(sets), tuple(args))
    if target == "已开工":
        first = rows(cn, "SELECT id FROM wo_operations WHERE wo_no=? ORDER BY seq LIMIT 1", (no,))
        if first:
            cn.execute("UPDATE wo_operations SET status='进行中', start_at=COALESCE(NULLIF(start_at,''),?)"
                       " WHERE id=?", (now(), first[0]["id"]))
    op(cn, user["username"], "工单推进", "%s → %s" % (no, target))
    emit(cn, "wo.stage_changed", "work_order", no, {"no": no, "from": r["status"], "to": target},
         user["username"])
    return {"no": no, "status": target, "from": r["status"]}


@write_op
def api_order_cancel(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    if not mes.can_move_wo(r["status"], "已取消"):
        raise ApiError("当前状态「%s」不允许取消" % r["status"])
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise ApiError("取消必须填写原因")
    cn.execute("UPDATE work_orders SET status='已取消', remark=? WHERE no=?",
               ((r["remark"] + " | 取消：" + reason).strip(" |"), no))
    op(cn, user["username"], "取消工单", "%s：%s" % (no, reason))
    emit(cn, "wo.cancelled", "work_order", no, {"no": no, "reason": reason}, user["username"])
    return {"no": no, "status": "已取消", "reason": reason}


@write_op
def api_order_dispatch(cn, user, no, body):
    require(user, "write")
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    team = str(body.get("team") or "").strip()
    operator = str(body.get("operator") or "").strip()
    if team and not one(cn, "SELECT 1 x FROM teams WHERE code=?", (team,)):
        raise ApiError("班组 %s 不存在" % team, 404)
    if operator and not one(cn, "SELECT 1 x FROM users WHERE username=?", (operator,)):
        raise ApiError("操作员 %s 不存在" % operator, 404)
    cn.execute("UPDATE work_orders SET team=?, owner=? WHERE no=?",
               (team or r["team"], operator or r["owner"], no))
    op(cn, user["username"], "工单派工", "%s → %s/%s" % (no, team, operator))
    emit(cn, "wo.dispatched", "work_order", no, {"no": no, "team": team, "operator": operator},
         user["username"])
    return {"no": no, "team": team, "operator": operator}


def api_order_kit(cn, user, no):
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    ctx = wo_ctx(cn, r)
    return {"no": no, "rate": ctx["kit"]["rate"], "qtyRate": ctx["kit"]["qtyRate"],
            "ready": ctx["kit"]["ready"], "total": ctx["kit"]["total"],
            "shortages": ctx["kit"]["shortages"]}


@write_op
def api_order_issue(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    if r["status"] not in ("已下达", "已开工"):
        raise ApiError("工单状态「%s」不允许发料" % r["status"])
    mats = rows(cn, "SELECT * FROM wo_materials WHERE wo_no=? AND state<>'已齐套'", (no,))
    if not mats:
        return {"no": no, "issued": 0, "detail": [], "message": "用料已全部发放"}
    # 先做整体可用性校验，避免部分扣减
    need_total = []
    for m in mats:
        need = float(m["need_qty"]) - float(m["issued_qty"])
        avail = one(cn, "SELECT COALESCE(SUM(qty),0) q FROM stocks WHERE material_code=?",
                    (m["material_code"],))["q"]
        if float(avail) + 1e-9 < need:
            need_total.append("%s 需 %.2f 可用 %.2f" % (m["material_code"], need, float(avail)))
    if need_total:
        raise ApiError("库存不足，不能发料：" + "；".join(need_total), 400, missing=need_total)
    detail = []
    for m in mats:
        need = float(m["need_qty"]) - float(m["issued_qty"])
        left = need
        for s in rows(cn, "SELECT * FROM stocks WHERE material_code=? AND qty>0 ORDER BY batch_no",
                      (m["material_code"],)):
            if left <= 1e-9:
                break
            take = min(float(s["qty"]), left)
            cn.execute("UPDATE stocks SET qty=qty-?, updated_at=? WHERE id=?", (take, now(), s["id"]))
            detail.append({"materialCode": m["material_code"], "batch": s["batch_no"],
                           "qty": mes.r2(take)})
            left = round(left - take, 4)
        cn.execute("UPDATE wo_materials SET issued_qty=need_qty, state='已齐套' WHERE id=?", (m["id"],))
    op(cn, user["username"], "工单发料", "%s 共 %d 项" % (no, len(mats)))
    emit(cn, "wo.issued", "work_order", no, {"no": no, "items": len(mats)}, user["username"])
    return {"no": no, "issued": len(mats), "detail": detail}


@write_op
def api_order_report(cn, user, no, body):
    require(user, "report")
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    if r["status"] not in ("已下达", "已开工"):
        raise ApiError("工单状态「%s」不允许报工" % r["status"])
    seq = int(body.get("seq") or 0)
    op_row = one(cn, "SELECT * FROM wo_operations WHERE wo_no=? AND seq=?", (no, seq))
    if not op_row:
        raise ApiError("工序 %s 不存在" % seq, 404)
    if op_row["status"] == "已完成":
        raise ApiError("工序「%s」已完成报工" % op_row["process"])
    good = float(body.get("goodQty") or 0)
    ng = float(body.get("ngQty") or 0)
    if good < 0 or ng < 0:
        raise ApiError("报工数量不能为负")
    qty = round(good + ng, 4)
    if qty <= 0:
        raise ApiError("报工数量必须大于 0")
    if float(rule_num(cn, "fai_required", 1)) >= 1:
        fai = one(cn, "SELECT * FROM inspections WHERE wo_no=? AND type='首件' AND result='合格'", (no,))
        if not fai:
            raise ApiError("首件检验未合格，不能报工（规则：首件必检）")
    tol = rule_num(cn, "over_report_tol", 0.05)
    reported = sum(float(x["qty"] or 0) for x in rows(
        cn, "SELECT qty FROM prod_reports WHERE wo_no=? AND seq=?", (no, seq)))
    limit = float(op_row["plan_qty"]) * (1 + tol)
    if reported + qty > limit + 1e-9:
        raise ApiError("超出超产容差：本工序已报 %.2f，本次 %.2f，上限 %.2f"
                       % (reported, qty, limit))
    step = one(cn, "SELECT * FROM routing_steps WHERE routing_code=? AND seq=?",
               (r["routing_code"], seq))
    std_min = round(float((step or {}).get("std_min") or 0) * qty, 2)
    actual = float(body.get("actualMin") or 0) or std_min
    rno = next_no(cn, "RP", "prod_reports")
    cn.execute("INSERT INTO prod_reports(no,wo_no,seq,process,qty,good_qty,ng_qty,std_min,actual_min,"
               "equipment,operator,batch_no,shift,reported_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (rno, no, seq, op_row["process"], qty, good, ng, std_min, actual,
                body.get("equipment") or op_row["equipment"], user["username"],
                body.get("batchNo") or "", mes.shift_of(now()), now(), body.get("remark") or ""))
    new_good = float(op_row["good_qty"] or 0) + good
    new_ng = float(op_row["ng_qty"] or 0) + ng
    done = new_good + new_ng >= float(op_row["plan_qty"]) - 1e-9
    cn.execute("UPDATE wo_operations SET good_qty=?, ng_qty=?, actual_min=actual_min+?,"
               " status=?, start_at=COALESCE(NULLIF(start_at,''),?), end_at=?, operator=?"
               " WHERE id=?",
               (round(new_good, 2), round(new_ng, 2), actual,
                "已完成" if done else "进行中", now(), now() if done else "",
                user["username"], op_row["id"]))
    if r["status"] == "已下达":
        cn.execute("UPDATE work_orders SET status='已开工', actual_start=? WHERE no=?", (now(), no))
    all_done = one(cn, "SELECT COUNT(*) c FROM wo_operations WHERE wo_no=? AND status<>'已完成'", (no,))["c"] == 0
    if all_done:
        cn.execute("UPDATE work_orders SET status='已完工', actual_end=? WHERE no=?", (now(), no))
    op(cn, user["username"], "生产报工", "%s %s 合格 %.2f 不良 %.2f" % (no, op_row["process"], good, ng))
    emit(cn, "wo.reported", "work_order", no,
         {"no": no, "seq": seq, "process": op_row["process"], "goodQty": good, "ngQty": ng,
          "status": "已完工" if all_done else "已开工", "reportNo": rno}, user["username"])
    return {"no": no, "reportNo": rno, "seq": seq, "qty": qty, "goodQty": good, "ngQty": ng,
            "stdMin": std_min, "actualMin": mes.r2(actual), "opStatus": "已完成" if done else "进行中",
            "woStatus": "已完工" if all_done else "已开工",
            "eff": mes.manpower_efficiency(std_min, actual)}


@write_op
def api_order_stockin(cn, user, no, body):
    require(user, "stock")
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no,))
    if not r:
        raise ApiError("工单 %s 不存在" % no, 404)
    if r["status"] not in ("已完工",):
        raise ApiError("工单状态「%s」不允许入库，需先完工" % r["status"])
    ctx = wo_ctx(cn, r)
    if not ctx["inspPass"]:
        raise ApiError("完工检验未合格，不能入库")
    qty = sum(float(x["good_qty"] or 0) for x in ctx["ops"])
    if qty <= 0:
        raise ApiError("没有可入库的合格品")
    bno = next_no(cn, "B", "batches")
    wh = str(body.get("warehouse") or "成品仓")
    cn.execute("INSERT INTO batches(no,material_code,wo_no,qty,good_qty,workshop,line,produced_at,expire_at,"
               "status,parent_batch,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (bno, r["material_code"], no, mes.r2(qty), mes.r2(qty), r["workshop"], r["line"],
                now(), mes.add_days(today(), 730), "正常", "", "工单入库批次"))
    cn.execute("INSERT INTO stocks(material_code,warehouse,batch_no,qty,updated_at) VALUES(?,?,?,?,?)",
               (r["material_code"], wh, bno, mes.r2(qty), now()))
    # 组件批次关联（用于正向追溯）
    for m in rows(cn, "SELECT * FROM wo_materials WHERE wo_no=?", (no,)):
        sb = one(cn, "SELECT batch_no, SUM(qty) q FROM stocks WHERE material_code=? GROUP BY batch_no"
                     " ORDER BY SUM(qty) DESC", (m["material_code"],))
        if sb and sb["batch_no"]:
            cn.execute("INSERT INTO batch_links(parent_batch,child_batch,material_code,qty,wo_no)"
                       " VALUES(?,?,?,?,?)", (bno, sb["batch_no"], m["material_code"],
                                              mes.r2(m["issued_qty"]), no))
    cn.execute("UPDATE work_orders SET status='已入库' WHERE no=?", (no,))
    op(cn, user["username"], "完工入库", "%s 批次 %s 数量 %.2f" % (no, bno, qty))
    emit(cn, "wo.stock_in", "work_order", no, {"no": no, "batch": bno, "qty": mes.r2(qty)}, user["username"])
    emit(cn, "batch.created", "batch", bno, {"batch": bno, "materialCode": r["material_code"],
                                             "qty": mes.r2(qty), "woNo": no}, user["username"])
    return {"no": no, "status": "已入库", "batch": bno, "qty": mes.r2(qty), "warehouse": wh}


def api_prod_reports(cn, user, query):
    wo = q1(query, "wo").strip()
    limit = min(300, max(1, qint(query, "limit", 100)))
    sql = "SELECT * FROM prod_reports WHERE 1=1"
    args = []
    if wo:
        sql += " AND wo_no LIKE ?"
        args.append("%" + wo + "%")
    sql += " ORDER BY reported_at DESC LIMIT %d" % limit
    names = name_map(cn)
    out = [{"no": x["no"], "woNo": x["wo_no"], "seq": x["seq"], "process": x["process"],
            "qty": mes.r2(x["qty"]), "goodQty": mes.r2(x["good_qty"]), "ngQty": mes.r2(x["ng_qty"]),
            "stdMin": mes.r2(x["std_min"]), "actualMin": mes.r2(x["actual_min"]),
            "equipment": x["equipment"], "operator": x["operator"],
            "operatorName": names.get(x["operator"], x["operator"]),
            "shift": x["shift"], "reportedAt": x["reported_at"],
            "eff": mes.manpower_efficiency(x["std_min"], x["actual_min"])}
           for x in rows(cn, sql, tuple(args))]
    total = out_qty(cn)
    return {"list": out, "total": len(out),
            "summary": {"good": mes.r2(total["g"]), "ng": mes.r2(total["n"]),
                        "yieldRate": mes.yield_rate(total["g"], float(total["g"]) + float(total["n"]))}}


def api_ops(cn, user, query):
    wo = q1(query, "wo").strip()
    sql = "SELECT * FROM wo_operations WHERE 1=1"
    args = []
    if wo:
        sql += " AND wo_no LIKE ?"
        args.append("%" + wo + "%")
    sql += " ORDER BY wo_no, seq LIMIT 300"
    out = [{"id": x["id"], "woNo": x["wo_no"], "seq": x["seq"], "process": x["process"],
            "station": x["station"], "equipment": x["equipment"], "planQty": mes.r2(x["plan_qty"]),
            "goodQty": mes.r2(x["good_qty"]), "ngQty": mes.r2(x["ng_qty"]),
            "status": x["status"], "operator": x["operator"], "startAt": x["start_at"],
            "endAt": x["end_at"]} for x in rows(cn, sql, tuple(args))]
    return {"list": out, "total": len(out)}


@write_op
def api_op_start(cn, user, op_id):
    require(user, "report")
    o = one(cn, "SELECT * FROM wo_operations WHERE id=?", (op_id,))
    if not o:
        raise ApiError("工序不存在", 404)
    if o["status"] != "待开工":
        raise ApiError("工序当前状态「%s」不能开工" % o["status"])
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (o["wo_no"],))
    if r["status"] not in ("已下达", "已开工"):
        raise ApiError("工单状态「%s」不允许开工" % r["status"])
    cn.execute("UPDATE wo_operations SET status='进行中', start_at=?, operator=? WHERE id=?",
               (now(), user["username"], op_id))
    if r["status"] == "已下达":
        cn.execute("UPDATE work_orders SET status='已开工', actual_start=? WHERE no=?", (now(), r["no"]))
    op(cn, user["username"], "工序开工", "%s %s" % (o["wo_no"], o["process"]))
    return {"id": op_id, "status": "进行中"}


@write_op
def api_op_finish(cn, user, op_id, body):
    require(user, "report")
    o = one(cn, "SELECT * FROM wo_operations WHERE id=?", (op_id,))
    if not o:
        raise ApiError("工序不存在", 404)
    if o["status"] == "已完成":
        raise ApiError("工序已完成")
    good = float(body.get("goodQty") if body.get("goodQty") is not None else o["plan_qty"])
    ng = float(body.get("ngQty") or 0)
    cn.execute("UPDATE wo_operations SET good_qty=?, ng_qty=?, status='已完成', end_at=?,"
               " actual_min=CASE WHEN actual_min>0 THEN actual_min ELSE std_min*1.05 END WHERE id=?",
               (good, ng, now(), op_id))
    left = one(cn, "SELECT COUNT(*) c FROM wo_operations WHERE wo_no=? AND status<>'已完成'", (o["wo_no"],))["c"]
    if left == 0:
        cn.execute("UPDATE work_orders SET status='已完工', actual_end=? WHERE no=? AND status='已开工'",
                   (now(), o["wo_no"]))
    op(cn, user["username"], "工序完工", "%s %s" % (o["wo_no"], o["process"]))
    return {"id": op_id, "status": "已完成", "woCompleted": left == 0}


def api_board(cn, user):
    lines = []
    for ln in rows(cn, "SELECT * FROM lines ORDER BY code"):
        cur = rows(cn, "SELECT w.*, m.name material_name FROM work_orders w LEFT JOIN materials m"
                       " ON m.code=w.material_code WHERE w.line=? AND w.status IN ('已开工','已下达')"
                       " ORDER BY w.priority='紧急' DESC, w.plan_end LIMIT 4", (ln["code"],))
        items = []
        for w in cur:
            ops = rows(cn, "SELECT * FROM wo_operations WHERE wo_no=? ORDER BY seq", (w["no"],))
            now_op = next((o for o in ops if o["status"] == "进行中"), None)
            rep = one(cn, "SELECT COALESCE(SUM(good_qty),0) g FROM prod_reports WHERE wo_no=?",
                      (w["no"],))
            items.append({"no": w["no"], "materialName": w.get("material_name") or "",
                          "qty": mes.r2(w["qty"]), "goodQty": mes.r2(rep["g"]),
                          "status": w["status"], "currentOp": (now_op or {}).get("process", "待开工"),
                          "progress": mes.progress(w["qty"], float(rep["g"] or 0)),
                          "planEnd": w["plan_end"],
                          "todayOutput": mes.r2(out_qty(cn, today() + "%", w["no"])["g"])})
        eq = rows(cn, "SELECT code,name,status FROM equipment WHERE line=?", (ln["code"],))
        lines.append({"code": ln["code"], "name": ln["name"], "workshop": ln["workshop"],
                      "status": ln["status"], "orders": items,
                      "equipRun": len([e for e in eq if e["status"] == "运行"]),
                      "equipTotal": len(eq),
                      "equipAbnormal": [e["name"] for e in eq if e["status"] in ("故障", "保养", "停机")]})
    andon = [andon_view(a, name_map(cn)) for a in rows(
        cn, "SELECT * FROM andon WHERE status<>'已关闭' ORDER BY level='紧急' DESC, created_at DESC")]
    return {"lines": lines, "andon": andon, "time": now()}


def api_andon(cn, user, query):
    st = q1(query, "status")
    sql = "SELECT * FROM andon"
    args = []
    if st and st != "全部":
        sql += " WHERE status=?"
        args.append(st)
    sql += " ORDER BY status='已关闭', created_at DESC LIMIT 50"
    names = name_map(cn)
    lst = [andon_view(a, names) for a in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst),
            "open": len([x for x in lst if x["status"] != "已关闭"])}


@write_op
def api_andon_create(cn, user, body):
    require(user, "report")
    no = next_no(cn, "AD", "andon")
    cn.execute("INSERT INTO andon(no,line,station,type,level,status,reporter,created_at,remark)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               (no, body.get("line") or "", body.get("station") or "",
                body.get("type") or "设备", body.get("level") or "一般",
                "待响应", user["username"], now(), body.get("remark") or ""))
    op(cn, user["username"], "安灯呼叫", no)
    emit(cn, "andon.created", "andon", no,
         {"no": no, "line": body.get("line"), "type": body.get("type")}, user["username"])
    return {"no": no, "status": "待响应"}


@write_op
def api_andon_close(cn, user, aid, body):
    require(user, "write")
    a = one(cn, "SELECT * FROM andon WHERE id=?", (aid,))
    if not a:
        raise ApiError("安灯呼叫不存在", 404)
    if a["status"] == "已关闭":
        raise ApiError("该呼叫已关闭")
    cn.execute("UPDATE andon SET status='已关闭', closed_at=?, remark=? WHERE id=?",
               (now(), (a["remark"] + " | " + str(body.get("remark") or "")).strip(" |"), aid))
    op(cn, user["username"], "关闭安灯", a["no"])
    emit(cn, "andon.closed", "andon", a["no"], {"no": a["no"]}, user["username"])
    return {"id": aid, "status": "已关闭",
            "minutes": mes.minutes_between(a["created_at"], now())}

# ---------------------------------------------------------------- 质量
def api_inspections(cn, user, query):
    typ = q1(query, "type")
    wo = q1(query, "wo").strip()
    limit = min(300, max(1, qint(query, "limit", 100)))
    sql = "SELECT * FROM inspections WHERE 1=1"
    args = []
    if typ and typ != "全部":
        sql += " AND type=?"
        args.append(typ)
    if wo:
        sql += " AND wo_no LIKE ?"
        args.append("%" + wo + "%")
    sql += " ORDER BY inspected_at DESC LIMIT %d" % limit
    names = name_map(cn)
    lst = [insp_view(x, names) for x in rows(cn, sql, tuple(args))]
    dist = {r["type"]: r["c"] for r in rows(cn, "SELECT type, COUNT(*) c FROM inspections GROUP BY type")}
    return {"list": lst, "total": len(lst), "typeDist": dist}


@write_op
def api_inspection_create(cn, user, body):
    require(user, "inspect")
    no_wo = str(body.get("woNo") or "").strip()
    r = one(cn, "SELECT * FROM work_orders WHERE no=?", (no_wo,))
    if not r:
        raise ApiError("工单 %s 不存在" % no_wo, 404)
    typ = str(body.get("type") or "巡检")
    if typ not in ("首件", "巡检", "完工检", "来料检"):
        raise ApiError("检验类型不支持：%s" % typ)
    seq = int(body.get("seq") or 0)
    if not seq:
        first = one(cn, "SELECT seq FROM wo_operations WHERE wo_no=? ORDER BY seq", (no_wo,))
        seq = first["seq"] if first else 10
    process = str(body.get("process") or "")
    if not process:
        o = one(cn, "SELECT process FROM wo_operations WHERE wo_no=? AND seq=?", (no_wo, seq))
        process = (o or {}).get("process", "")
    items = body.get("items") or []
    sample = float(body.get("sampleQty") or 0)
    if sample <= 0 and typ == "首件":
        sample = float(len(items) or 5)
    defect = float(body.get("defectQty") or 0)
    if sample <= 0:
        raise ApiError("抽样数量必须大于 0")
    if defect > sample:
        raise ApiError("不良数不能大于抽样数")
    if typ == "首件":
        result = mes.fai_conclusion(sample, defect)
    elif typ == "巡检":
        result = mes.patrol_conclusion(defect, 0)
    else:
        aql = rule_num(cn, "scrap_warn_rate", 0.02)
        result = mes.inspect_conclusion(sample, defect, aql)
    no = next_no(cn, "IQ", "inspections")
    cn.execute("INSERT INTO inspections(no,wo_no,type,seq,process,sample_qty,defect_qty,result,standard,"
               "inspector,inspected_at,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, no_wo, typ, seq, process, sample, defect, result,
                body.get("standard") or ("GB/T 2828.1" if typ != "首件" else "首件全尺寸"),
                user["username"], now(), body.get("remark") or ""))
    for it in items:
        try:
            val = float(it.get("value") or 0)
            lsl = float(it.get("lsl") or 0)
            usl = float(it.get("usl") or 0)
        except (TypeError, ValueError):
            raise ApiError("检验项数值格式不正确")
        ok = "合格" if (lsl - 1e-9) <= val <= (usl + 1e-9) else "超差"
        cn.execute("INSERT INTO inspection_items(inspection_no,item,value,lsl,usl,result)"
                   " VALUES(?,?,?,?,?,?)", (no, it.get("item") or "", val, lsl, usl, ok))
    op(cn, user["username"], "质量检验", "%s %s %s" % (no, no_wo, result))
    emit(cn, "inspection.created", "inspection", no,
         {"no": no, "woNo": no_wo, "type": typ, "result": result,
          "sampleQty": sample, "defectQty": defect}, user["username"])
    return {"no": no, "woNo": no_wo, "type": typ, "result": result,
            "defectRate": mes.ratio(defect, sample), "itemCount": len(items)}


def api_inspection_detail(cn, user, no):
    r = one(cn, "SELECT * FROM inspections WHERE no=?", (no,))
    if not r:
        raise ApiError("检验单 %s 不存在" % no, 404)
    v = insp_view(r, name_map(cn))
    v["items"] = [{"item": x["item"], "value": mes.r2(x["value"]), "lsl": mes.r2(x["lsl"]),
                   "usl": mes.r2(x["usl"]), "result": x["result"]}
                  for x in rows(cn, "SELECT * FROM inspection_items WHERE inspection_no=?", (no,))]
    v["defects"] = [{"code": d["defect_code"], "qty": mes.r2(d["qty"]), "disposition": d["disposition"]}
                    for d in rows(cn, "SELECT * FROM defects WHERE inspection_no=?", (no,))]
    v["cpk"] = None
    if v["items"]:
        vals = [x["value"] for x in v["items"]]
        v["cpk"] = mes.cpk(vals, v["items"][0]["lsl"], v["items"][0]["usl"])
    return v


def api_defects(cn, user, query):
    wo = q1(query, "wo").strip()
    disp = q1(query, "disposition")
    sql = ("SELECT d.*, c.name defect_name, c.category, c.severity FROM defects d"
           " LEFT JOIN defect_codes c ON c.code=d.defect_code WHERE 1=1")
    args = []
    if wo:
        sql += " AND d.wo_no LIKE ?"
        args.append("%" + wo + "%")
    if disp and disp != "全部":
        sql += " AND d.disposition=?"
        args.append(disp)
    sql += " ORDER BY d.occur_at DESC LIMIT 200"
    lst = [{"id": d["id"], "woNo": d["wo_no"], "inspectionNo": d["inspection_no"],
            "code": d["defect_code"], "name": d.get("defect_name") or "",
            "category": d.get("category") or "", "severity": d.get("severity") or "",
            "qty": mes.r2(d["qty"]), "process": d["process"], "equipment": d["equipment"],
            "operator": d["operator"], "occurAt": d["occur_at"],
            "disposition": d["disposition"], "remark": d["remark"]} for d in rows(cn, sql, tuple(args))]
    total = sum(x["qty"] for x in lst)
    return {"list": lst, "total": len(lst), "qty": mes.r2(total),
            "pending": len([x for x in lst if x["disposition"] == "待处置"])}


@write_op
def api_defect_create(cn, user, body):
    require(user, "inspect")
    no_wo = str(body.get("woNo") or "").strip()
    if not one(cn, "SELECT 1 x FROM work_orders WHERE no=?", (no_wo,)):
        raise ApiError("工单 %s 不存在" % no_wo, 404)
    code = str(body.get("defectCode") or "").strip()
    dc = one(cn, "SELECT * FROM defect_codes WHERE code=?", (code,))
    if not dc:
        raise ApiError("不良代码 %s 不存在" % code, 404)
    qty = float(body.get("qty") or 0)
    if qty <= 0:
        raise ApiError("不良数量必须大于 0")
    cur = cn.execute("INSERT INTO defects(wo_no,inspection_no,defect_code,qty,process,equipment,operator,"
                     "occur_at,disposition,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (no_wo, body.get("inspectionNo") or "", code, qty, body.get("process") or "",
                      body.get("equipment") or "", user["username"], now(),
                      body.get("disposition") or "待处置", body.get("remark") or ""))
    did = cur.lastrowid
    op(cn, user["username"], "登记不良", "%s %s ×%g" % (no_wo, dc["name"], qty))
    emit(cn, "defect.created", "defect", no_wo,
         {"woNo": no_wo, "code": code, "qty": qty}, user["username"])
    return {"id": did, "woNo": no_wo,
            "code": code, "qty": qty, "disposition": body.get("disposition") or "待处置"}


@write_op
def api_defect_dispose(cn, user, did, body):
    require(user, "inspect")
    d = one(cn, "SELECT * FROM defects WHERE id=?", (did,))
    if not d:
        raise ApiError("不良记录不存在", 404)
    disp = str(body.get("disposition") or "").strip()
    if disp not in ("返修", "报废", "让步接收", "退货"):
        raise ApiError("处置方式必须是 返修 / 报废 / 让步接收 / 退货")
    cn.execute("UPDATE defects SET disposition=?, remark=? WHERE id=?",
               (disp, (d["remark"] + " | " + str(body.get("remark") or "")).strip(" |"), did))
    op(cn, user["username"], "不良处置", "%s %s ×%g" % (d["wo_no"], disp, d["qty"]))
    emit(cn, "defect.disposed", "defect", d["wo_no"],
         {"id": did, "disposition": disp}, user["username"])
    return {"id": did, "disposition": disp}


def api_defect_codes(cn, user):
    lst = [{"code": x["code"], "name": x["name"], "category": x["category"],
            "severity": x["severity"]} for x in rows(cn, "SELECT * FROM defect_codes ORDER BY code")]
    return {"list": lst}


def api_cpk(cn, user, query):
    wo = q1(query, "wo").strip()
    item = q1(query, "item").strip()
    sql = ("SELECT ii.* FROM inspection_items ii JOIN inspections i ON i.no=ii.inspection_no WHERE 1=1")
    args = []
    if wo:
        sql += " AND i.wo_no=?"
        args.append(wo)
    if item:
        sql += " AND ii.item=?"
        args.append(item)
    data = rows(cn, sql, tuple(args))
    names = {}
    for d in data:
        names.setdefault(d["item"], []).append(d)
    out = []
    for name, lst in names.items():
        vals = [float(x["value"]) for x in lst]
        v = mes.cpk(vals, lst[0]["lsl"], lst[0]["usl"])
        out.append({"item": name, "n": len(vals), "lsl": mes.r2(lst[0]["lsl"]),
                    "usl": mes.r2(lst[0]["usl"]),
                    "mean": mes.r4(sum(vals) / len(vals)) if vals else 0,
                    "min": mes.r2(min(vals)) if vals else 0, "max": mes.r2(max(vals)) if vals else 0,
                    "cpk": v, "level": mes.cpk_level(v, rule_num(cn, "cpk_min", 1.33))})
    out.sort(key=lambda x: (x["cpk"] is None, x["cpk"] or 0))
    return {"list": out, "items": len(out), "samples": len(data)}


def api_quality_summary(cn, user):
    month = today()[:7]
    ins = rows(cn, "SELECT * FROM inspections")
    reports = out_qty(cn, month + "%")
    defs = rows(cn, "SELECT d.*, c.name FROM defects d LEFT JOIN defect_codes c ON c.code=d.defect_code")
    agg = {}
    for d in defs:
        k = d.get("name") or d["defect_code"]
        agg[k] = agg.get(k, 0.0) + float(d["qty"] or 0)
    pareto = mes.pareto([{"name": k, "qty": v} for k, v in agg.items()])
    trend = []
    for i in range(13, -1, -1):
        day = mes.add_days(today(), -i)
        r = out_qty(cn, day + "%")
        trend.append({"day": day[5:], "good": mes.r2(r["g"]), "ng": mes.r2(r["n"]),
                      "yieldRate": mes.yield_rate(r["g"], float(r["g"]) + float(r["n"]))})
    fai = [x for x in ins if x["type"] == "首件"]
    fqc = [x for x in ins if x["type"] == "完工检"]
    patrol = [x for x in ins if x["type"] == "巡检"]
    total = float(reports["g"]) + float(reports["n"])
    return {
        "yieldRate": mes.yield_rate(reports["g"], total),
        "ppm": mes.ppm(reports["n"], total),
        "inspCount": len(ins),
        "faiPassRate": mes.r4(len([x for x in fai if x["result"] == "合格"]) / len(fai)) if fai else 0.0,
        "fqcPassRate": mes.r4(len([x for x in fqc if x["result"] in ("合格", "让步接收")]) / len(fqc)) if fqc else 0.0,
        "patrolAbnormal": len([x for x in patrol if x["result"] == "异常"]),
        "concession": len([x for x in fqc if x["result"] == "让步接收"]),
        "rejected": len([x for x in fqc if x["result"] == "退货"]),
        "pareto": pareto[:10], "trend": trend,
        "defectQty": mes.r2(sum(x["qty"] for x in defs)),
        "pendingDispose": len([x for x in defs if x["disposition"] == "待处置"]),
    }


# ---------------------------------------------------------------- 设备
def _equip_metrics(cn, code, days):
    since = mes.add_days(today(), -days + 1)
    m = one(cn, "SELECT COALESCE(SUM(plan_min),0) p, COALESCE(SUM(run_min),0) r,"
                " COALESCE(SUM(output),0) o, COALESCE(SUM(good),0) g, COALESCE(AVG(ideal_cycle),0) c"
                " FROM equip_metrics WHERE equipment=? AND day>=?", (code, since))
    return m


def api_equipment(cn, user, query):
    st = q1(query, "status")
    line = q1(query, "line")
    kw = q1(query, "kw").strip()
    sql = "SELECT * FROM equipment WHERE 1=1"
    args = []
    if st and st != "全部":
        sql += " AND status=?"
        args.append(st)
    if line and line != "全部":
        sql += " AND line=?"
        args.append(line)
    if kw:
        sql += " AND (code LIKE ? OR name LIKE ? OR model LIKE ?)"
        args += ["%" + kw + "%"] * 3
    sql += " ORDER BY code"
    lst = []
    for r in rows(cn, sql, tuple(args)):
        m = _equip_metrics(cn, r["code"], 7)
        plan = one(cn, "SELECT * FROM maint_plans WHERE equipment=? ORDER BY code LIMIT 1", (r["code"],))
        repairs = one(cn, "SELECT COUNT(*) c FROM maint_orders WHERE equipment=? AND status<>'已完成'",
                      (r["code"],))
        m["open_repairs"] = repairs["c"] if repairs else 0
        lst.append(equip_view(r, m, plan))
    dist = {x["status"]: x["c"] for x in rows(cn, "SELECT status, COUNT(*) c FROM equipment GROUP BY status")}
    return {"list": lst, "total": len(lst), "statusDist": dist}


def api_equipment_detail(cn, user, code):
    r = one(cn, "SELECT * FROM equipment WHERE code=?", (code,))
    if not r:
        raise ApiError("设备 %s 不存在" % code, 404)
    m = _equip_metrics(cn, code, 7)
    repairs = one(cn, "SELECT COUNT(*) c FROM maint_orders WHERE equipment=? AND status<>'已完成'", (code,))
    m["open_repairs"] = repairs["c"] if repairs else 0
    plan = one(cn, "SELECT * FROM maint_plans WHERE equipment=? ORDER BY code LIMIT 1", (code,))
    v = equip_view(r, m, plan)
    v["daily"] = [{"day": x["day"][5:], "planMin": mes.r2(x["plan_min"]), "runMin": mes.r2(x["run_min"]),
                   "output": mes.r2(x["output"]), "good": mes.r2(x["good"]),
                   "oee": mes.oee(x["plan_min"], x["run_min"], x["ideal_cycle"],
                                  x["output"], x["good"])["oee"]}
                  for x in rows(cn, "SELECT * FROM equip_metrics WHERE equipment=? ORDER BY day DESC LIMIT 14",
                                (code,))]
    v["daily"].reverse()
    v["logs"] = [{"status": x["status"], "reason": x["reason"], "minutes": mes.r2(x["minutes"]),
                  "startAt": x["start_at"], "endAt": x["end_at"]}
                 for x in rows(cn, "SELECT * FROM equip_logs WHERE equipment=? ORDER BY start_at DESC LIMIT 10",
                               (code,))]
    v["checks"] = [{"no": x["no"], "type": x["check_type"], "result": x["result"],
                    "checker": x["checker"], "checkedAt": x["checked_at"]}
                   for x in rows(cn, "SELECT * FROM equip_checks WHERE equipment=? ORDER BY checked_at DESC LIMIT 5",
                                 (code,))]
    v["maint"] = [{"no": x["no"], "type": x["type"], "reason": x["reason"], "status": x["status"],
                   "planAt": x["plan_at"], "finishAt": x["finish_at"],
                   "downtimeMin": mes.r2(x["downtime_min"]), "cost": mes.r2(x["cost"])}
                  for x in rows(cn, "SELECT * FROM maint_orders WHERE equipment=? ORDER BY plan_at DESC LIMIT 8",
                                (code,))]
    v["downtimeTop"] = mes.downtime_top(
        [{"reason": x["reason"], "minutes": x["minutes"]}
         for x in rows(cn, "SELECT * FROM equip_logs WHERE equipment=?", (code,))])
    v["plan"] = None if not plan else {
        "code": plan["code"], "type": plan["type"], "cycleDays": plan["cycle_days"],
        "cycleHours": mes.r2(plan["cycle_hours"]), "lastAt": plan["last_at"],
        "nextAt": plan["next_at"], "owner": plan["owner"], "state": mes.maint_state(plan["next_at"], today(), 7)}
    m14 = one(cn, "SELECT COALESCE(SUM(plan_min),0) p, COALESCE(SUM(run_min),0) r,"
                  " COALESCE(AVG(ideal_cycle),0) c, COALESCE(SUM(output),0) o,"
                  " COALESCE(SUM(good),0) g FROM equip_metrics WHERE equipment=? AND day>=?",
              (code, mes.add_days(today(), -6)))
    v["oee14"] = mes.oee(m14["p"], m14["r"], m14["c"], m14["o"], m14["g"])
    return v


@write_op
def api_equip_status(cn, user, code, body):
    require(user, "equip")
    r = one(cn, "SELECT * FROM equipment WHERE code=?", (code,))
    if not r:
        raise ApiError("设备 %s 不存在" % code, 404)
    target = str(body.get("status") or "").strip()
    if target not in mes.EQUIP_STATES:
        raise ApiError("设备状态必须是：%s" % " / ".join(mes.EQUIP_STATES))
    if target == r["status"]:
        return {"code": code, "status": target, "changed": False}
    reason = str(body.get("reason") or "").strip()
    if target in ("故障", "停机", "保养") and not reason:
        raise ApiError("停机类状态必须填写原因")
    # 复位历史未闭合日志
    open_log = one(cn, "SELECT * FROM equip_logs WHERE equipment=? AND end_at='' ORDER BY id DESC", (code,))
    if open_log:
        mins = mes.minutes_between(open_log["start_at"], now())
        cn.execute("UPDATE equip_logs SET end_at=?, minutes=? WHERE id=?", (now(), mins, open_log["id"]))
        if open_log["status"] in ("故障", "停机", "保养"):
            cn.execute("UPDATE equipment SET down_min=down_min+? WHERE code=?", (mins, code))
    if target != "运行":
        cn.execute("INSERT INTO equip_logs(equipment,status,prev_status,reason,minutes,wo_no,operator,"
                   "start_at,end_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (code, target, r["status"], reason or target, 0, "", user["username"], now(), ""))
    else:
        cn.execute("INSERT INTO equip_logs(equipment,status,prev_status,reason,minutes,wo_no,operator,"
                   "start_at,end_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (code, "运行", r["status"], body.get("reason") or "恢复生产", 0, "",
                    user["username"], now(), now()))
        if r["status"] == "故障":
            cn.execute("UPDATE equipment SET failures=failures+1 WHERE code=?", (code,))
    cn.execute("UPDATE equipment SET status=? WHERE code=?", (target, code))
    op(cn, user["username"], "设备状态", "%s %s→%s" % (code, r["status"], target))
    emit(cn, "equipment.status_changed", "equipment", code,
         {"code": code, "from": r["status"], "to": target, "reason": reason}, user["username"])
    return {"code": code, "from": r["status"], "to": target, "changed": True}


def api_equip_logs(cn, user, query):
    code = q1(query, "equipment").strip()
    sql = "SELECT * FROM equip_logs WHERE 1=1"
    args = []
    if code:
        sql += " AND equipment LIKE ?"
        args.append("%" + code + "%")
    sql += " ORDER BY start_at DESC LIMIT 100"
    lst = [{"id": x["id"], "equipment": x["equipment"], "status": x["status"],
            "prevStatus": x["prev_status"], "reason": x["reason"], "minutes": mes.r2(x["minutes"]),
            "startAt": x["start_at"], "endAt": x["end_at"], "operator": x["operator"]}
           for x in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst), "top": mes.downtime_top(lst)}


def api_equip_checks(cn, user, query):
    code = q1(query, "equipment").strip()
    sql = "SELECT c.*, e.name equip_name FROM equip_checks c LEFT JOIN equipment e ON e.code=c.equipment WHERE 1=1"
    args = []
    if code:
        sql += " AND c.equipment LIKE ?"
        args.append("%" + code + "%")
    sql += " ORDER BY c.checked_at DESC LIMIT 100"
    lst = [{"no": x["no"], "equipment": x["equipment"], "equipName": x.get("equip_name") or "",
            "type": x["check_type"], "result": x["result"], "checker": x["checker"],
            "checkedAt": x["checked_at"], "items": json.loads(x["items_json"] or "[]"),
            "remark": x["remark"]} for x in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst),
            "abnormal": len([x for x in lst if x["result"] == "异常"])}


@write_op
def api_equip_check_create(cn, user, body):
    require(user, "equip")
    code = str(body.get("equipment") or "").strip()
    r = one(cn, "SELECT * FROM equipment WHERE code=?", (code,))
    if not r:
        raise ApiError("设备 %s 不存在" % code, 404)
    items = body.get("items") or []
    abnormal = [x for x in items if str(x.get("result") or "正常") != "正常"]
    result = "异常" if abnormal else "正常"
    no = next_no(cn, "EC", "equip_checks")
    cn.execute("INSERT INTO equip_checks(no,equipment,check_type,result,items_json,checker,checked_at,remark)"
               " VALUES(?,?,?,?,?,?,?,?)",
               (no, code, body.get("type") or "日常点检", result,
                json.dumps(items, ensure_ascii=False), user["username"], now(),
                body.get("remark") or ""))
    if abnormal:
        cn.execute("UPDATE equipment SET status='故障' WHERE code=? AND status='运行'", (code,))
    op(cn, user["username"], "设备点检", "%s %s" % (code, result))
    emit(cn, "equipment.checked", "equipment", code,
         {"no": no, "equipment": code, "result": result}, user["username"])
    return {"no": no, "result": result, "abnormal": len(abnormal)}


def api_maint_plans(cn, user):
    out = []
    for p in rows(cn, "SELECT p.*, e.name equip_name FROM maint_plans p LEFT JOIN equipment e"
                      " ON e.code=p.equipment ORDER BY p.next_at"):
        out.append({"code": p["code"], "equipment": p["equipment"], "equipName": p.get("equip_name") or "",
                    "type": p["type"], "cycleDays": p["cycle_days"],
                    "cycleHours": mes.r2(p["cycle_hours"]), "lastAt": p["last_at"],
                    "nextAt": p["next_at"], "owner": p["owner"], "status": p["status"],
                    "state": mes.maint_state(p["next_at"], today(), 7)})
    return {"list": out, "total": len(out),
            "due": len([x for x in out if x["state"] in ("逾期", "临期")])}


@write_op
def api_maint_plan_save(cn, user, body):
    require(user, "equip")
    code = str(body.get("code") or "").strip()
    if not code:
        code = "MP-%04d" % (len(rows(cn, "SELECT 1 x FROM maint_plans")) + 1)
    eq = str(body.get("equipment") or "").strip()
    if not one(cn, "SELECT 1 x FROM equipment WHERE code=?", (eq,)):
        raise ApiError("设备 %s 不存在" % eq, 404)
    cn.execute("INSERT OR REPLACE INTO maint_plans(code,equipment,type,cycle_days,cycle_hours,last_at,next_at,"
               "owner,status,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (code, eq, body.get("type") or "一级保养", int(body.get("cycleDays") or 30),
                float(body.get("cycleHours") or 0), body.get("lastAt") or "",
                body.get("nextAt") or mes.add_days(today(), int(body.get("cycleDays") or 30)),
                body.get("owner") or user["username"], body.get("status") or "启用", ""))
    op(cn, user["username"], "保养计划", code)
    return {"code": code, "equipment": eq, "saved": True}


def api_maint_orders(cn, user, query):
    st = q1(query, "status")
    sql = ("SELECT m.*, e.name equip_name FROM maint_orders m LEFT JOIN equipment e ON e.code=m.equipment"
           " WHERE 1=1")
    args = []
    if st and st != "全部":
        sql += " AND m.status=?"
        args.append(st)
    sql += " ORDER BY m.plan_at DESC LIMIT 100"
    lst = [{"no": x["no"], "equipment": x["equipment"], "equipName": x.get("equip_name") or "",
            "planCode": x["plan_code"], "type": x["type"], "reason": x["reason"],
            "status": x["status"], "planAt": x["plan_at"], "startAt": x["start_at"],
            "finishAt": x["finish_at"], "downtimeMin": mes.r2(x["downtime_min"]),
            "cost": mes.r2(x["cost"]), "owner": x["owner"]} for x in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst),
            "open": len([x for x in lst if x["status"] != "已完成"])}


@write_op
def api_maint_create(cn, user, body):
    require(user, "equip")
    eq = str(body.get("equipment") or "").strip()
    r = one(cn, "SELECT * FROM equipment WHERE code=?", (eq,))
    if not r:
        raise ApiError("设备 %s 不存在" % eq, 404)
    typ = str(body.get("type") or "计划保养")
    no = next_no(cn, "MT", "maint_orders")
    plan = one(cn, "SELECT * FROM maint_plans WHERE equipment=? ORDER BY code LIMIT 1", (eq,))
    cn.execute("INSERT INTO maint_orders(no,equipment,plan_code,type,reason,status,plan_at,start_at,"
               "finish_at,downtime_min,cost,owner,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, eq, (plan or {}).get("code", ""), typ, body.get("reason") or typ,
                "待执行", body.get("planAt") or today(), "", "", 0, 0,
                body.get("owner") or user["username"], body.get("remark") or ""))
    op(cn, user["username"], "保养工单", "%s %s" % (no, eq))
    emit(cn, "maintenance.created", "maintenance", no,
         {"no": no, "equipment": eq, "type": typ}, user["username"])
    return {"no": no, "equipment": eq, "status": "待执行"}


@write_op
def api_maint_finish(cn, user, no, body):
    require(user, "equip")
    m = one(cn, "SELECT * FROM maint_orders WHERE no=?", (no,))
    if not m:
        raise ApiError("保养工单 %s 不存在" % no, 404)
    if m["status"] == "已完成":
        raise ApiError("该工单已完成")
    down = float(body.get("downtimeMin") or 0)
    cost = float(body.get("cost") or 0)
    cn.execute("UPDATE maint_orders SET status='已完成', start_at=COALESCE(NULLIF(start_at,''),?),"
               " finish_at=?, downtime_min=?, cost=?, remark=? WHERE no=?",
               (now(), now(), down, cost,
                (m["remark"] + " | " + str(body.get("remark") or "")).strip(" |"), no))
    cn.execute("UPDATE equipment SET status='运行', last_maint_at=?, next_maint_at=?,"
               " down_min=down_min+?, run_hours=0 WHERE code=?",
               (today(), mes.add_days(today(), 30), down, m["equipment"]))
    plan = one(cn, "SELECT * FROM maint_plans WHERE equipment=?", (m["equipment"],))
    if plan:
        cn.execute("UPDATE maint_plans SET last_at=?, next_at=? WHERE code=?",
                   (today(), mes.add_days(today(), int(plan["cycle_days"] or 30)), plan["code"]))
    op(cn, user["username"], "保养完成", "%s %s" % (no, m["equipment"]))
    emit(cn, "maintenance.finished", "maintenance", no,
         {"no": no, "equipment": m["equipment"], "downtimeMin": down}, user["username"])
    return {"no": no, "status": "已完成", "downtimeMin": down, "cost": cost}


# ---------------------------------------------------------------- 批次与库存
def api_batches(cn, user, query):
    kw = q1(query, "kw").strip()
    wo = q1(query, "wo").strip()
    sql = ("SELECT b.*, m.name material_name FROM batches b LEFT JOIN materials m ON m.code=b.material_code"
           " WHERE 1=1")
    args = []
    if kw:
        sql += " AND (b.no LIKE ? OR b.material_code LIKE ? OR m.name LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if wo:
        sql += " AND b.wo_no LIKE ?"
        args.append("%" + wo + "%")
    sql += " ORDER BY b.produced_at DESC LIMIT 200"
    lst = []
    for b in rows(cn, sql, tuple(args)):
        v = batch_view(b)
        v["state"] = mes.batch_state(b["qty"], b["good_qty"], b["expire_at"], today())
        v["children"] = one(cn, "SELECT COUNT(*) c FROM batch_links WHERE parent_batch=?", (b["no"],))["c"]
        lst.append(v)
    return {"list": lst, "total": len(lst),
            "expiring": len([x for x in lst if x["state"] in ("临期", "已过期")])}


def api_batch_detail(cn, user, no):
    b = one(cn, "SELECT b.*, m.name material_name, m.unit FROM batches b LEFT JOIN materials m"
                " ON m.code=b.material_code WHERE b.no=?", (no,))
    if not b:
        raise ApiError("批次 %s 不存在" % no, 404)
    v = batch_view(b)
    v["unit"] = b.get("unit") or ""
    v["state"] = mes.batch_state(b["qty"], b["good_qty"], b["expire_at"], today())
    v["children"] = [{"batch": x["child_batch"], "materialCode": x["material_code"],
                      "qty": mes.r2(x["qty"])}
                     for x in rows(cn, "SELECT * FROM batch_links WHERE parent_batch=?", (no,))]
    v["parent"] = [{"batch": x["parent_batch"], "qty": mes.r2(x["qty"])}
                   for x in rows(cn, "SELECT * FROM batch_links WHERE child_batch=?", (no,))]
    wo = one(cn, "SELECT * FROM work_orders WHERE no=?", (b["wo_no"],)) if b["wo_no"] else None
    v["order"] = None if not wo else {"no": wo["no"], "qty": mes.r2(wo["qty"]),
                                      "status": wo["status"], "customer": wo["customer"]}
    v["stock"] = [{"warehouse": s["warehouse"], "qty": mes.r2(s["qty"]), "updatedAt": s["updated_at"]}
                  for s in rows(cn, "SELECT * FROM stocks WHERE batch_no=?", (no,))]
    v["reports"] = [{"no": x["no"], "process": x["process"], "goodQty": mes.r2(x["good_qty"]),
                     "operator": x["operator"], "reportedAt": x["reported_at"]}
                    for x in rows(cn, "SELECT * FROM prod_reports WHERE wo_no=? ORDER BY reported_at",
                                  (b["wo_no"],))]
    return v


def api_trace(cn, user, query):
    root = q1(query, "batch").strip()
    if not root:
        raise ApiError("请提供批次号 batch")
    b = one(cn, "SELECT * FROM batches WHERE no=?", (root,))
    if not b:
        raise ApiError("批次 %s 不存在" % root, 404)
    edges = rows(cn, "SELECT * FROM batch_links")
    down = mes.trace_chain([{"parent": e["parent_batch"], "child": e["child_batch"]} for e in edges], root)
    up = mes.trace_up([{"parent": e["parent_batch"], "child": e["child_batch"]} for e in edges], root)
    nodes = []
    for x in down:
        bb = one(cn, "SELECT b.*, m.name material_name FROM batches b LEFT JOIN materials m"
                     " ON m.code=b.material_code WHERE b.no=?", (x["batch"],))
        if not bb:
            continue
        nodes.append({"batch": bb["no"], "materialCode": bb["material_code"],
                      "materialName": bb.get("material_name") or "",
                      "qty": mes.r2(bb["qty"]), "depth": x["depth"],
                      "producedAt": bb["produced_at"], "status": bb["status"]})
    return {"root": root, "materialCode": b["material_code"], "woNo": b["wo_no"],
            "nodes": nodes, "upstream": up, "nodeCount": len(nodes)}


def api_stock(cn, user, query):
    kw = q1(query, "kw").strip()
    wh = q1(query, "warehouse")
    sql = ("SELECT s.*, m.name, m.unit, m.safety_stock, m.std_cost FROM stocks s"
           " LEFT JOIN materials m ON m.code=s.material_code WHERE s.qty>0")
    args = []
    if kw:
        sql += " AND (s.material_code LIKE ? OR m.name LIKE ? OR s.batch_no LIKE ?)"
        args += ["%" + kw + "%"] * 3
    if wh and wh != "全部":
        sql += " AND s.warehouse=?"
        args.append(wh)
    sql += " ORDER BY s.material_code, s.batch_no"
    lst = [{"materialCode": x["material_code"], "name": x.get("name") or "", "unit": x.get("unit") or "",
            "warehouse": x["warehouse"], "batch": x["batch_no"], "qty": mes.r2(x["qty"]),
            "amount": mes.r2(float(x["qty"]) * float(x.get("std_cost") or 0)),
            "updatedAt": x["updated_at"]} for x in rows(cn, sql, tuple(args))]
    whs = [r["warehouse"] for r in rows(cn, "SELECT DISTINCT warehouse FROM stocks ORDER BY warehouse")]
    return {"list": lst, "total": len(lst), "warehouses": whs,
            "summary": {"rows": len(lst), "qty": mes.r2(sum(x["qty"] for x in lst)),
                        "amount": mes.r2(sum(x["amount"] for x in lst))}}

# ---------------------------------------------------------------- 报表
def api_reports(cn, user, query):
    days = min(120, max(7, qint(query, "days", 14)))
    wos = rows(cn, "SELECT * FROM work_orders WHERE status<>'已取消'")
    trend = []
    for i in range(days - 1, -1, -1):
        day = mes.add_days(today(), -i)
        r = out_qty(cn, day + "%")
        plan = 0.0
        for w in wos:
            ps, pe = str(w["plan_start"] or ""), str(w["plan_end"] or "")
            if ps <= day <= pe:
                span = max(1, mes.days_between(ps, pe) + 1)
                plan += float(w["qty"] or 0) / span
        trend.append({"day": day[5:], "output": mes.r2(r["g"]), "ng": mes.r2(r["n"]),
                      "plan": mes.r2(plan), "yieldRate": mes.yield_rate(r["g"], float(r["g"]) + float(r["n"]))})

    since = mes.add_days(today(), -days + 1)
    window_plan = sum(float(w["qty"] or 0) for w in wos
                      if str(w["plan_start"] or "") >= since and str(w["plan_start"] or "") <= today())
    oee_trend = []
    for i in range(days - 1, -1, -1):
        day = mes.add_days(today(), -i)
        m = one(cn, "SELECT COALESCE(SUM(plan_min),0) p, COALESCE(SUM(run_min),0) r,"
                    " COALESCE(SUM(output),0) o, COALESCE(SUM(good),0) g, COALESCE(AVG(ideal_cycle),0) c"
                    " FROM equip_metrics WHERE day=?", (day,))
        o = mes.oee(m["p"], m["r"], m["c"], m["o"], m["g"])
        oee_trend.append({"day": day[5:], "oee": o["oee"], "availability": o["availability"],
                          "performance": o["performance"], "quality": o["quality"]})

    total = one(cn, "SELECT COALESCE(SUM(plan_min),0) p, COALESCE(SUM(run_min),0) r,"
                    " COALESCE(SUM(output),0) o, COALESCE(SUM(good),0) g, COALESCE(AVG(ideal_cycle),0) c"
                    " FROM equip_metrics")
    plant_oee = mes.oee(total["p"], total["r"], total["c"], total["o"], total["g"])

    lines = []
    for ln in rows(cn, "SELECT * FROM lines ORDER BY code"):
        w_line = [w for w in wos if w["line"] == ln["code"] and w["status"] in ("已下达", "已开工", "已完工")]
        std = 0.0
        for w in w_line:
            std += float(one(cn, "SELECT COALESCE(SUM(std_min),0) s FROM wo_operations WHERE wo_no=?",
                             (w["no"],))["s"] or 0)
        out = one(cn, "SELECT COALESCE(SUM(r.good_qty),0) g FROM prod_reports r"
                      " JOIN work_orders w ON w.no=r.wo_no WHERE w.line=?", (ln["code"],))
        cap = 480 * 3 * 22
        lines.append({"code": ln["code"], "name": ln["name"], "workshop": ln["workshop"],
                      "load": mes.capacity_load(std, cap), "stdMin": mes.r2(std),
                      "output": mes.r2(out["g"]), "wip": len([w for w in w_line
                                                              if w["status"] in ("已下达", "已开工")]),
                      "balance": mes.line_balance([float(x["std_min"] or 0) for x in rows(
                          cn, "SELECT rs.std_min FROM routing_steps rs JOIN routings r"
                              " ON r.code=rs.routing_code JOIN work_orders w ON w.routing_code=r.code"
                              " WHERE w.line=? GROUP BY rs.seq ORDER BY rs.seq LIMIT 8", (ln["code"],))])})

    q = api_quality_summary(cn, user)

    eq_rows = rows(cn, "SELECT * FROM equipment ORDER BY code")
    eq_rank = []
    for e in eq_rows:
        m = _equip_metrics(cn, e["code"], days)
        o = mes.oee(m["p"], m["r"], m["c"], m["o"], m["g"])
        eq_rank.append({"code": e["code"], "name": e["name"], "line": e["line"],
                        "oee": o["oee"], "availability": o["availability"],
                        "performance": o["performance"], "quality": o["quality"],
                        "level": mes.oee_level(o["oee"], e["oee_target"] or 0.85),
                        "status": e["status"]})
    eq_rank.sort(key=lambda x: -x["oee"])
    logs = rows(cn, "SELECT * FROM equip_logs WHERE status<>'运行'")
    down_top = mes.downtime_top([{"reason": x["reason"], "minutes": x["minutes"]} for x in logs])
    run_min = float(total["r"] or 0)
    failures = sum(int(e["failures"] or 0) for e in eq_rows)
    down_min = sum(float(e["down_min"] or 0) for e in eq_rows)

    status_dist = {}
    for w in rows(cn, "SELECT status, qty, COUNT(*) c FROM work_orders GROUP BY status, qty"):
        status_dist[w["status"]] = status_dist.get(w["status"], 0) + w["c"]

    cons = rows(cn, "SELECT wm.material_code, m.name, m.unit, m.std_cost,"
                    " SUM(wm.issued_qty) q, SUM(wm.issued_qty*m.std_cost) amt"
                    " FROM wo_materials wm LEFT JOIN materials m ON m.code=wm.material_code"
                    " GROUP BY wm.material_code ORDER BY amt DESC LIMIT 12")
    consumption = [{"materialCode": c["material_code"], "name": c.get("name") or "",
                    "unit": c.get("unit") or "", "qty": mes.r2(c["q"]),
                    "amount": mes.r2(c["amt"]), "share": mes.ratio(c["amt"], sum(
                        float(x["amt"] or 0) for x in cons))} for c in cons]

    month = today()[:7]
    m_plan = sum(float(w["qty"] or 0) for w in wos if str(w["plan_start"]).startswith(month))
    m_out = one(cn, "SELECT COALESCE(SUM(good_qty),0) g, COALESCE(SUM(ng_qty),0) n FROM prod_reports"
                    " WHERE reported_at LIKE ?", (month + "%",))
    return {
        "days": days,
        "production": {
            "trend": trend,
            "output": mes.r2(sum(x["output"] for x in trend)),
            "plan": mes.r2(window_plan),
            "completion": mes.ratio(sum(x["output"] for x in trend), window_plan),
            "monthOutput": mes.r2(m_out["g"]), "monthPlan": mes.r2(m_plan),
            "monthCompletion": mes.ratio(m_out["g"], m_plan),
        },
        "oee": {"plant": plant_oee, "trend": oee_trend,
                "target": rule_num(cn, "oee_target", 0.85),
                "level": mes.oee_level(plant_oee["oee"], rule_num(cn, "oee_target", 0.85))},
        "quality": q,
        "lines": lines,
        "equipment": {"rank": eq_rank[:12], "worst": eq_rank[-5:], "downTop": down_top[:8],
                      "mtbf": mes.mtbf(run_min, failures), "mttr": mes.mttr(down_min, failures),
                      "failures": failures, "downMin": mes.r2(down_min),
                      "maintDue": len([e for e in eq_rows
                                       if mes.maint_state(e["next_maint_at"], today(), 7) != "正常"])},
        "statusDist": [{"status": k, "count": v} for k, v in status_dist.items()],
        "consumption": consumption,
        "defectPareto": q["pareto"],
    }


# ---------------------------------------------------------------- 设置与日志
def api_settings(cn, user):
    return {
        "rules": rows(cn, "SELECT * FROM rules ORDER BY category, code"),
        "workshops": [{"code": w["code"], "name": w["name"], "manager": w["manager"],
                       "capacityMin": mes.r2(w["capacity_min"]), "status": w["status"]}
                      for w in rows(cn, "SELECT * FROM workshops ORDER BY code")],
        "lines": [{"code": l["code"], "name": l["name"], "workshop": l["workshop"],
                   "leader": l["leader"], "taktSec": mes.r2(l["takt_sec"]), "status": l["status"]}
                  for l in rows(cn, "SELECT * FROM lines ORDER BY code")],
        "teams": [{"code": t["code"], "name": t["name"], "workshop": t["workshop"],
                   "leader": t["leader"], "shift": t["shift"], "members": t["members"]}
                  for t in rows(cn, "SELECT * FROM teams ORDER BY code")],
        "users": [{"username": u["username"], "name": u["display_name"], "role": u["role"],
                   "roleLabel": mes.ROLE_LABEL.get(u["role"], u["role"]), "dept": u["dept_code"],
                   "status": u["status"]} for u in rows(cn, "SELECT * FROM users ORDER BY role, username")],
        "shifts": mes.SHIFTS,
        "roles": [{"role": k, "label": v, "perms": sorted(mes._PERM.get(k, []))}
                  for k, v in mes.ROLE_LABEL.items()],
    }


@write_op
def api_rule_toggle(cn, user, code, body):
    need_admin(user)
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    if not r:
        raise ApiError("规则 %s 不存在" % code, 404)
    if "enabled" in body:
        cn.execute("UPDATE rules SET enabled=? WHERE code=?", (1 if body.get("enabled") else 0, code))
    if "value" in body:
        try:
            v = float(body["value"])
        except (TypeError, ValueError):
            raise ApiError("阈值必须是数字")
        cn.execute("UPDATE rules SET value=? WHERE code=?", (v, code))
    op(cn, user["username"], "规则调整", "%s → %s" % (code, mes.dumps(body)))
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    return {"code": r["code"], "value": r["value"], "enabled": bool(r["enabled"])}


def api_logs(cn, user, query):
    limit = min(300, max(1, qint(query, "limit", 100)))
    lst = [{"id": x["id"], "username": x["username"], "action": x["action"],
            "detail": x["detail"], "createdAt": x["created_at"]}
           for x in rows(cn, "SELECT * FROM op_logs ORDER BY id DESC LIMIT %d" % limit)]
    return {"list": lst, "total": len(lst)}


def api_users(cn, user):
    return {"list": [{"username": u["username"], "name": u["display_name"], "role": u["role"],
                      "roleLabel": mes.ROLE_LABEL.get(u["role"], u["role"]),
                      "dept": u["dept_code"], "phone": u["phone"], "status": u["status"]}
                     for u in rows(cn, "SELECT * FROM users ORDER BY role")]}


# ---------------------------------------------------------------- 集成
def api_integration_overview(cn, user):
    need_admin(user)
    counts = {}
    for t in ("work_orders", "batches", "inspections", "defects", "equipment"):
        counts[t] = one(cn, "SELECT COUNT(*) c FROM %s" % t)["c"]
    return {
        "keys": one(cn, "SELECT COUNT(*) c FROM api_keys WHERE status='启用'")["c"],
        "webhooks": one(cn, "SELECT COUNT(*) c FROM webhooks WHERE status='启用'")["c"],
        "deliveries": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries")["c"],
        "deliveryFailed": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries WHERE status='失败'")["c"],
        "changes": one(cn, "SELECT COUNT(*) c FROM change_log")["c"],
        "lastChange": (one(cn, "SELECT MAX(changed_at) m FROM change_log") or {}).get("m", ""),
        "mappings": one(cn, "SELECT COUNT(*) c FROM ext_mappings")["c"],
        "counts": counts,
        "objects": ["work_order", "batch", "inspection", "defect", "equipment", "material"],
    }


def api_int_keys(cn, user):
    need_admin(user)
    lst = [{"id": k["id"], "name": k["name"], "prefix": k["prefix"], "scope": k["scope"],
            "owner": k["owner"], "status": k["status"], "createdAt": k["created_at"],
            "lastUsedAt": k["last_used_at"], "expiresAt": k["expires_at"]}
           for k in rows(cn, "SELECT * FROM api_keys ORDER BY id DESC")]
    return {"list": lst, "active": len([x for x in lst if x["status"] == "启用"])}


@write_op
def api_int_key_create(cn, user, body):
    need_admin(user)
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError("Key 名称不能为空")
    scope = str(body.get("scope") or "read")
    if scope not in ("read", "write"):
        raise ApiError("scope 只能是 read 或 write")
    raw = "fck_" + secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:36]
    cur = cn.execute("INSERT INTO api_keys(name,key_hash,prefix,scope,owner,status,created_at,last_used_at,"
                     "expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (name, mes.sha256(raw), raw[:12], scope, user["username"], "启用", now(), "",
                      body.get("expiresAt") or ""))
    kid = cur.lastrowid
    op(cn, user["username"], "新建 API Key", name)
    return {"id": kid, "name": name,
            "key": raw, "prefix": raw[:12], "scope": scope,
            "notice": "明文 Key 只显示一次，请立即保存"}


@write_op
def api_int_key_revoke(cn, user, kid):
    need_admin(user)
    k = one(cn, "SELECT * FROM api_keys WHERE id=?", (kid,))
    if not k:
        raise ApiError("Key 不存在", 404)
    cn.execute("UPDATE api_keys SET status='吊销' WHERE id=?", (kid,))
    op(cn, user["username"], "吊销 API Key", k["name"])
    return {"id": kid, "status": "吊销"}


def api_int_webhooks(cn, user):
    need_admin(user)
    lst = []
    for h in rows(cn, "SELECT * FROM webhooks ORDER BY id DESC"):
        lst.append({"id": h["id"], "name": h["name"], "url": h["url"], "events": h["events"],
                    "status": h["status"], "secret": h["secret"][:10] + "****",
                    "createdAt": h["created_at"],
                    "deliveries": one(cn, "SELECT COUNT(*) c FROM webhook_deliveries WHERE webhook_id=?",
                                      (h["id"],))["c"]})
    return {"list": lst}


@write_op
def api_int_webhook_save(cn, user, body, wid=None):
    need_admin(user)
    name = str(body.get("name") or "").strip()
    url = str(body.get("url") or "").strip()
    events = body.get("events") or "*"
    if isinstance(events, list):
        events = ",".join(str(x) for x in events)
    if wid:
        h = one(cn, "SELECT * FROM webhooks WHERE id=?", (wid,))
        if not h:
            raise ApiError("Webhook 不存在", 404)
        name = name or h["name"]
        url = url or h["url"]
        if not name or not url:
            raise ApiError("名称与回调地址不能为空")
        if not url.startswith("http"):
            raise ApiError("回调地址必须以 http(s):// 开头")
        if not body.get("events"):
            events = h["events"]
        cn.execute("UPDATE webhooks SET name=?, url=?, events=?, status=? WHERE id=?",
                   (name, url, events, body.get("status") or h["status"], wid))
        op(cn, user["username"], "更新 Webhook", name)
        return {"id": wid, "updated": True}
    if not name or not url:
        raise ApiError("名称与回调地址不能为空")
    if not url.startswith("http"):
        raise ApiError("回调地址必须以 http(s):// 开头")
    secret = "whsec_" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
    cur = cn.execute("INSERT INTO webhooks(name,url,events,secret,status,created_at) VALUES(?,?,?,?,?,?)",
                     (name, url, events, secret, "启用", now()))
    wid_new = cur.lastrowid
    op(cn, user["username"], "新建 Webhook", name)
    return {"id": wid_new, "name": name,
            "secret": secret, "events": events, "notice": "签名密钥只显示一次"}


@write_op
def api_int_webhook_delete(cn, user, wid):
    need_admin(user)
    cn.execute("DELETE FROM webhooks WHERE id=?", (wid,))
    cn.execute("DELETE FROM webhook_deliveries WHERE webhook_id=?", (wid,))
    op(cn, user["username"], "删除 Webhook", str(wid))
    return {"id": wid, "deleted": True}


@write_op
def api_int_webhook_test(cn, user, wid):
    need_admin(user)
    h = one(cn, "SELECT * FROM webhooks WHERE id=?", (wid,))
    if not h:
        raise ApiError("Webhook 不存在", 404)
    payload = {"event": "webhook.test", "data": {"at": now(), "source": "feichi-mes"}}
    body = mes.dumps(payload)
    sig = mes.sign_payload(h["secret"], str(int(time.time())), body)
    cur = cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,signature,status,attempts,"
                     "http_code,error,next_at,created_at,delivered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (wid, "webhook.test", body, sig, "待投递", 0, 0, "", now(), now(), ""))
    return {"queued": True, "event": "webhook.test", "deliveryId": cur.lastrowid}


def api_int_deliveries(cn, user, query):
    need_admin(user)
    st = q1(query, "status")
    sql = "SELECT * FROM webhook_deliveries WHERE 1=1"
    args = []
    if st and st != "全部":
        sql += " AND status=?"
        args.append(st)
    sql += " ORDER BY id DESC LIMIT 100"
    lst = [{"id": d["id"], "webhookId": d["webhook_id"], "event": d["event"],
            "status": d["status"], "attempts": d["attempts"], "httpCode": d["http_code"],
            "error": d["error"], "createdAt": d["created_at"], "deliveredAt": d["delivered_at"],
            "nextAt": d["next_at"]} for d in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst),
            "failed": len([x for x in lst if x["status"] == "失败"])}


@write_op
def api_int_delivery_retry(cn, user, did):
    need_admin(user)
    d = one(cn, "SELECT * FROM webhook_deliveries WHERE id=?", (did,))
    if not d:
        raise ApiError("投递记录不存在", 404)
    cn.execute("UPDATE webhook_deliveries SET status='待投递', next_at=?, error='' WHERE id=?",
               (now(), did))
    return {"id": did, "status": "待投递"}


def api_int_mappings(cn, user, query):
    need_admin(user)
    obj = q1(query, "objType")
    sql = "SELECT * FROM ext_mappings WHERE 1=1"
    args = []
    if obj:
        sql += " AND obj_type=?"
        args.append(obj)
    sql += " ORDER BY id DESC LIMIT 200"
    lst = [{"id": m["id"], "objType": m["obj_type"], "localNo": m["local_no"],
            "externalId": m["external_id"], "system": m["system"], "createdAt": m["created_at"]}
           for m in rows(cn, sql, tuple(args))]
    return {"list": lst, "total": len(lst)}


@write_op
def api_int_mapping_save(cn, user, body):
    need_admin(user)
    obj = str(body.get("objType") or "").strip()
    local = str(body.get("localNo") or "").strip()
    ext = str(body.get("externalId") or "").strip()
    system = str(body.get("system") or "ERP").strip()
    if not obj or not local or not ext:
        raise ApiError("objType / localNo / externalId 均不能为空")
    old = one(cn, "SELECT * FROM ext_mappings WHERE obj_type=? AND local_no=?", (obj, local))
    if old:
        cn.execute("UPDATE ext_mappings SET external_id=?, system=? WHERE id=?",
                   (ext, system, old["id"]))
        return {"id": old["id"], "updated": True}
    cur = cn.execute("INSERT INTO ext_mappings(obj_type,local_no,external_id,system,created_at)"
                     " VALUES(?,?,?,?,?)", (obj, local, ext, system, now()))
    return {"id": cur.lastrowid, "created": True}


def api_int_resolve(cn, user, query):
    ext = q1(query, "externalId").strip()
    if not ext:
        raise ApiError("请提供 externalId")
    m = one(cn, "SELECT * FROM ext_mappings WHERE external_id=?", (ext,))
    if not m:
        raise ApiError("外部 ID %s 未建立映射" % ext, 404)
    return {"externalId": ext, "objType": m["obj_type"], "localNo": m["local_no"],
            "system": m["system"]}


def api_sync_changes(cn, user, query):
    since = qint(query, "since", 0)
    obj = q1(query, "object")
    limit = min(500, max(1, qint(query, "limit", 200)))
    sql = "SELECT * FROM change_log WHERE id>?"
    args = [since]
    if obj:
        sql += " AND obj_type=?"
        args.append(obj)
    sql += " ORDER BY id LIMIT %d" % (limit + 1)
    lst = rows(cn, sql, tuple(args))
    has_more = len(lst) > limit
    lst = lst[:limit]
    cursor = lst[-1]["id"] if lst else since
    return {"changes": [{"id": x["id"], "objType": x["obj_type"], "objNo": x["obj_no"],
                         "op": x["op"], "actor": x["actor"],
                         "payload": json.loads(x["payload"] or "{}"), "changedAt": x["changed_at"]}
                        for x in lst],
            "cursor": cursor, "hasMore": has_more, "count": len(lst)}


def api_export_orders(cn, user, query):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["工单号", "物料编码", "物料名称", "计划数量", "已报工", "合格数", "不良数",
                "产线", "车间", "状态", "优先级", "计划开始", "计划完成", "客户"])
    for r in rows(cn, "SELECT w.*, m.name material_name FROM work_orders w LEFT JOIN materials m"
                      " ON m.code=w.material_code ORDER BY w.no"):
        rep = one(cn, "SELECT COALESCE(SUM(qty),0) q, COALESCE(SUM(good_qty),0) g,"
                      " COALESCE(SUM(ng_qty),0) n FROM prod_reports WHERE wo_no=?", (r["no"],))
        w.writerow([r["no"], r["material_code"], r.get("material_name") or "", r["qty"],
                    mes.r2(rep["q"]), mes.r2(rep["g"]), mes.r2(rep["n"]), r["line"], r["workshop"],
                    r["status"], r["priority"], r["plan_start"], r["plan_end"], r["customer"]])
    return {"csv": buf.getvalue(), "filename": "work_orders.csv"}


def api_export_oee(cn, user, query):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["设备编码", "设备名称", "产线", "状态", "可用率", "性能率", "质量率", "OEE", "目标"])
    for e in rows(cn, "SELECT * FROM equipment ORDER BY code"):
        m = _equip_metrics(cn, e["code"], 7)
        o = mes.oee(m["p"], m["r"], m["c"], m["o"], m["g"])
        w.writerow([e["code"], e["name"], e["line"], e["status"], o["availability"],
                    o["performance"], o["quality"], o["oee"], e["oee_target"]])
    return {"csv": buf.getvalue(), "filename": "equipment_oee.csv"}


# ---------------------------------------------------------------- OpenAPI
API_DOC = [
    ("POST", "/api/auth/login", "登录", "认证"),
    ("POST", "/api/auth/logout", "登出", "认证"),
    ("GET", "/api/auth/me", "当前用户", "认证"),
    ("GET", "/api/bootstrap", "启动数据（KPI / 趋势 / 待办 / 规则）", "认证"),
    ("GET", "/api/health", "健康检查", "系统"),
    ("GET", "/api/openapi.json", "OpenAPI 规范", "系统"),
    ("GET", "/api/workshops", "车间列表", "主数据"),
    ("GET", "/api/lines", "产线列表", "主数据"),
    ("GET", "/api/stations", "工位列表", "主数据"),
    ("GET", "/api/teams", "班组列表", "主数据"),
    ("GET", "/api/materials", "物料列表", "主数据"),
    ("POST", "/api/materials", "新建物料", "主数据"),
    ("GET", "/api/materials/{code}", "物料详情（BOM / 工艺 / 批次）", "主数据"),
    ("PUT", "/api/materials/{code}", "更新物料", "主数据"),
    ("GET", "/api/boms", "BOM 列表", "主数据"),
    ("GET", "/api/boms/{code}", "BOM 明细", "主数据"),
    ("GET", "/api/routings", "工艺路线列表", "主数据"),
    ("GET", "/api/routings/{code}", "工艺路线明细", "主数据"),
    ("GET", "/api/orders", "工单列表", "生产"),
    ("POST", "/api/orders", "新建工单", "生产"),
    ("GET", "/api/orders/{no}", "工单详情（工序 / 用料 / 检验 / 闸口）", "生产"),
    ("POST", "/api/orders/{no}/stage", "工单状态推进", "生产"),
    ("POST", "/api/orders/{no}/cancel", "取消工单", "生产"),
    ("POST", "/api/orders/{no}/dispatch", "工单派工", "生产"),
    ("GET", "/api/orders/{no}/kit", "齐套检查", "生产"),
    ("POST", "/api/orders/{no}/issue", "工单发料", "生产"),
    ("POST", "/api/orders/{no}/report", "生产报工", "生产"),
    ("POST", "/api/orders/{no}/stock-in", "完工入库", "生产"),
    ("GET", "/api/prod-reports", "报工记录", "生产"),
    ("GET", "/api/ops", "工序列表", "生产"),
    ("POST", "/api/ops/{id}/start", "工序开工", "生产"),
    ("POST", "/api/ops/{id}/finish", "工序完工", "生产"),
    ("GET", "/api/board", "生产看板", "生产"),
    ("GET", "/api/andon", "安灯呼叫列表", "生产"),
    ("POST", "/api/andon", "发起安灯呼叫", "生产"),
    ("POST", "/api/andon/{id}/close", "关闭安灯呼叫", "生产"),
    ("GET", "/api/inspections", "检验单列表", "质量"),
    ("POST", "/api/inspections", "创建检验（首件 / 巡检 / 完工检）", "质量"),
    ("GET", "/api/inspections/{no}", "检验单详情（含 CPK）", "质量"),
    ("GET", "/api/defects", "不良记录", "质量"),
    ("POST", "/api/defects", "登记不良", "质量"),
    ("POST", "/api/defects/{id}/dispose", "不良处置", "质量"),
    ("GET", "/api/defect-codes", "不良代码", "质量"),
    ("GET", "/api/cpk", "过程能力 Cpk", "质量"),
    ("GET", "/api/quality/summary", "质量总览", "质量"),
    ("GET", "/api/equipment", "设备列表（含 OEE）", "设备"),
    ("GET", "/api/equipment/{code}", "设备详情", "设备"),
    ("POST", "/api/equipment/{code}/status", "设备状态变更", "设备"),
    ("GET", "/api/equip/logs", "设备状态日志", "设备"),
    ("GET", "/api/equip/checks", "点检记录", "设备"),
    ("POST", "/api/equip/checks", "提交点检", "设备"),
    ("GET", "/api/maint/plans", "保养计划", "设备"),
    ("POST", "/api/maint/plans", "保存保养计划", "设备"),
    ("GET", "/api/maint/orders", "保养工单", "设备"),
    ("POST", "/api/maint/orders", "新建保养工单", "设备"),
    ("POST", "/api/maint/orders/{no}/finish", "完成保养", "设备"),
    ("GET", "/api/batches", "批次列表", "追溯"),
    ("GET", "/api/batches/{no}", "批次详情", "追溯"),
    ("GET", "/api/trace", "批次追溯树", "追溯"),
    ("GET", "/api/stock", "库存台账", "追溯"),
    ("GET", "/api/reports", "报表聚合（产量 / OEE / 质量 / 设备 / 负荷）", "报表"),
    ("GET", "/api/settings", "系统设置", "系统"),
    ("PUT", "/api/rules/{code}", "规则启停 / 调阈值", "系统"),
    ("GET", "/api/logs", "操作日志", "系统"),
    ("GET", "/api/users", "用户列表", "系统"),
    ("GET", "/api/integration/overview", "集成总览", "集成"),
    ("GET", "/api/integration/keys", "API Key 列表", "集成"),
    ("POST", "/api/integration/keys", "新建 API Key", "集成"),
    ("DELETE", "/api/integration/keys/{id}", "吊销 API Key", "集成"),
    ("GET", "/api/integration/webhooks", "Webhook 列表", "集成"),
    ("POST", "/api/integration/webhooks", "新建 Webhook", "集成"),
    ("PUT", "/api/integration/webhooks/{id}", "更新 Webhook", "集成"),
    ("DELETE", "/api/integration/webhooks/{id}", "删除 Webhook", "集成"),
    ("POST", "/api/integration/webhooks/{id}/test", "发送测试事件", "集成"),
    ("GET", "/api/integration/deliveries", "投递记录", "集成"),
    ("POST", "/api/integration/deliveries/{id}/retry", "手动重投", "集成"),
    ("GET", "/api/integration/mappings", "外部 ID 映射", "集成"),
    ("POST", "/api/integration/mappings", "绑定外部 ID", "集成"),
    ("GET", "/api/integration/resolve", "外部 ID 反查", "集成"),
    ("GET", "/api/sync/changes", "增量变更流", "集成"),
    ("GET", "/api/export/orders", "导出工单 CSV", "导出"),
    ("GET", "/api/export/oee", "导出设备 OEE CSV", "导出"),
]


def openapi_spec():
    paths = {}
    for method, path, summary, tag in API_DOC:
        item = paths.setdefault(path, {})
        params = []
        for seg in re.findall(r"\{(\w+)\}", path):
            params.append({"name": seg, "in": "path", "required": True, "schema": {"type": "string"}})
        item[method.lower()] = {
            "summary": summary, "tags": [tag], "parameters": params,
            "responses": {"200": {"description": "成功，返回 {ok:true, data:...}"},
                          "400": {"description": "业务校验失败"},
                          "401": {"description": "未登录"},
                          "403": {"description": "权限不足"}},
        }
    return {
        "openapi": "3.0.3",
        "info": {"title": "飞驰MES系统 API", "version": VERSION,
                 "description": "制造执行系统 REST 接口：工单状态机、报工、质检、设备 OEE、批次追溯、"
                                "三层集成通道（API Key / Webhook / 增量同步）"},
        "servers": [{"url": "/", "description": "当前服务"}],
        "components": {
            "securitySchemes": {
                "sessionToken": {"type": "apiKey", "in": "header", "name": "X-Fc-Token"},
                "apiKey": {"type": "apiKey", "in": "header", "name": "X-Fc-Key"},
            }
        },
        "security": [{"sessionToken": []}, {"apiKey": []}],
        "tags": [{"name": t} for t in ("认证", "主数据", "生产", "质量", "设备", "追溯", "报表", "系统", "集成", "导出")],
        "paths": paths,
    }

# ---------------------------------------------------------------- 路由表
ROUTES = [
    # 认证
    ("POST", r"^/api/auth/login$", lambda cn, u, b, q: api_login(cn, u, b, q), "登录"),
    ("POST", r"^/api/auth/logout$",
     lambda cn, u, b, q: api_logout(cn, (q.get("_token") or [""])[0]), "登出"),
    ("GET", r"^/api/auth/me$", lambda cn, u, b, q: api_me(cn, u), "当前用户"),
    ("GET", r"^/api/bootstrap$", lambda cn, u, b, q: api_bootstrap(cn, u), "启动数据"),
    # 主数据
    ("GET", r"^/api/workshops$", lambda cn, u, b, q: api_workshops(cn, u), "车间"),
    ("GET", r"^/api/lines$", lambda cn, u, b, q: api_lines(cn, u), "产线"),
    ("GET", r"^/api/stations$", lambda cn, u, b, q: api_stations(cn, u, q), "工位"),
    ("GET", r"^/api/teams$", lambda cn, u, b, q: api_teams(cn, u), "班组"),
    ("GET", r"^/api/materials$", lambda cn, u, b, q: api_materials(cn, u, q), "物料列表"),
    ("POST", r"^/api/materials$", lambda cn, u, b, q: api_material_create(cn, u, b), "新建物料"),
    ("GET", r"^/api/materials/([\w\-]+)$", lambda cn, u, b, q, c: api_material_detail(cn, u, c), "物料详情"),
    ("PUT", r"^/api/materials/([\w\-]+)$", lambda cn, u, b, q, c: api_material_update(cn, u, c, b),
     "更新物料"),
    ("GET", r"^/api/boms$", lambda cn, u, b, q: api_boms(cn, u, q), "BOM 列表"),
    ("GET", r"^/api/boms/([\w\-]+)$", lambda cn, u, b, q, c: api_bom_detail(cn, u, c), "BOM 明细"),
    ("GET", r"^/api/routings$", lambda cn, u, b, q: api_routings(cn, u, q), "工艺列表"),
    ("GET", r"^/api/routings/([\w\-]+)$", lambda cn, u, b, q, c: api_routing_detail(cn, u, c), "工艺明细"),
    # 工单
    ("GET", r"^/api/orders$", lambda cn, u, b, q: api_orders(cn, u, q), "工单列表"),
    ("POST", r"^/api/orders$", lambda cn, u, b, q: api_order_create(cn, u, b), "新建工单"),
    ("GET", r"^/api/orders/([\w\-]+)$", lambda cn, u, b, q, c: api_order_detail(cn, u, c), "工单详情"),
    ("POST", r"^/api/orders/([\w\-]+)/stage$", lambda cn, u, b, q, c: api_order_stage(cn, u, c, b),
     "工单推进"),
    ("POST", r"^/api/orders/([\w\-]+)/cancel$", lambda cn, u, b, q, c: api_order_cancel(cn, u, c, b),
     "取消工单"),
    ("POST", r"^/api/orders/([\w\-]+)/dispatch$",
     lambda cn, u, b, q, c: api_order_dispatch(cn, u, c, b), "派工"),
    ("GET", r"^/api/orders/([\w\-]+)/kit$", lambda cn, u, b, q, c: api_order_kit(cn, u, c), "齐套检查"),
    ("POST", r"^/api/orders/([\w\-]+)/issue$", lambda cn, u, b, q, c: api_order_issue(cn, u, c, b),
     "工单发料"),
    ("POST", r"^/api/orders/([\w\-]+)/report$", lambda cn, u, b, q, c: api_order_report(cn, u, c, b),
     "生产报工"),
    ("POST", r"^/api/orders/([\w\-]+)/stock-in$",
     lambda cn, u, b, q, c: api_order_stockin(cn, u, c, b), "完工入库"),
    ("GET", r"^/api/prod-reports$", lambda cn, u, b, q: api_prod_reports(cn, u, q), "报工记录"),
    ("GET", r"^/api/ops$", lambda cn, u, b, q: api_ops(cn, u, q), "工序列表"),
    ("POST", r"^/api/ops/(\d+)/start$", lambda cn, u, b, q, c: api_op_start(cn, u, int(c)), "工序开工"),
    ("POST", r"^/api/ops/(\d+)/finish$", lambda cn, u, b, q, c: api_op_finish(cn, u, int(c), b),
     "工序完工"),
    ("GET", r"^/api/board$", lambda cn, u, b, q: api_board(cn, u), "生产看板"),
    ("GET", r"^/api/andon$", lambda cn, u, b, q: api_andon(cn, u, q), "安灯列表"),
    ("POST", r"^/api/andon$", lambda cn, u, b, q: api_andon_create(cn, u, b), "发起安灯"),
    ("POST", r"^/api/andon/(\d+)/close$", lambda cn, u, b, q, c: api_andon_close(cn, u, int(c), b),
     "关闭安灯"),
    # 质量
    ("GET", r"^/api/inspections$", lambda cn, u, b, q: api_inspections(cn, u, q), "检验列表"),
    ("POST", r"^/api/inspections$", lambda cn, u, b, q: api_inspection_create(cn, u, b), "创建检验"),
    ("GET", r"^/api/inspections/([\w\-]+)$", lambda cn, u, b, q, c: api_inspection_detail(cn, u, c),
     "检验详情"),
    ("GET", r"^/api/defects$", lambda cn, u, b, q: api_defects(cn, u, q), "不良列表"),
    ("POST", r"^/api/defects$", lambda cn, u, b, q: api_defect_create(cn, u, b), "登记不良"),
    ("POST", r"^/api/defects/(\d+)/dispose$", lambda cn, u, b, q, c: api_defect_dispose(cn, u, int(c), b),
     "不良处置"),
    ("GET", r"^/api/defect-codes$", lambda cn, u, b, q: api_defect_codes(cn, u), "不良代码"),
    ("GET", r"^/api/cpk$", lambda cn, u, b, q: api_cpk(cn, u, q), "过程能力"),
    ("GET", r"^/api/quality/summary$", lambda cn, u, b, q: api_quality_summary(cn, u), "质量总览"),
    # 设备
    ("GET", r"^/api/equipment$", lambda cn, u, b, q: api_equipment(cn, u, q), "设备列表"),
    ("GET", r"^/api/equipment/([\w\-]+)$", lambda cn, u, b, q, c: api_equipment_detail(cn, u, c),
     "设备详情"),
    ("POST", r"^/api/equipment/([\w\-]+)/status$", lambda cn, u, b, q, c: api_equip_status(cn, u, c, b),
     "设备状态"),
    ("GET", r"^/api/equip/logs$", lambda cn, u, b, q: api_equip_logs(cn, u, q), "设备日志"),
    ("GET", r"^/api/equip/checks$", lambda cn, u, b, q: api_equip_checks(cn, u, q), "点检记录"),
    ("POST", r"^/api/equip/checks$", lambda cn, u, b, q: api_equip_check_create(cn, u, b), "提交点检"),
    ("GET", r"^/api/maint/plans$", lambda cn, u, b, q: api_maint_plans(cn, u), "保养计划"),
    ("POST", r"^/api/maint/plans$", lambda cn, u, b, q: api_maint_plan_save(cn, u, b), "保存计划"),
    ("GET", r"^/api/maint/orders$", lambda cn, u, b, q: api_maint_orders(cn, u, q), "保养工单"),
    ("POST", r"^/api/maint/orders$", lambda cn, u, b, q: api_maint_create(cn, u, b), "新建保养工单"),
    ("POST", r"^/api/maint/orders/([\w\-]+)/finish$",
     lambda cn, u, b, q, c: api_maint_finish(cn, u, c, b), "完成保养"),
    # 追溯
    ("GET", r"^/api/batches$", lambda cn, u, b, q: api_batches(cn, u, q), "批次列表"),
    ("GET", r"^/api/batches/([\w\-]+)$", lambda cn, u, b, q, c: api_batch_detail(cn, u, c), "批次详情"),
    ("GET", r"^/api/trace$", lambda cn, u, b, q: api_trace(cn, u, q), "追溯树"),
    ("GET", r"^/api/stock$", lambda cn, u, b, q: api_stock(cn, u, q), "库存台账"),
    # 报表与系统
    ("GET", r"^/api/reports$", lambda cn, u, b, q: api_reports(cn, u, q), "报表聚合"),
    ("GET", r"^/api/settings$", lambda cn, u, b, q: api_settings(cn, u), "系统设置"),
    ("PUT", r"^/api/rules/([\w\-]+)$", lambda cn, u, b, q, c: api_rule_toggle(cn, u, c, b), "规则调整"),
    ("GET", r"^/api/logs$", lambda cn, u, b, q: api_logs(cn, u, q), "操作日志"),
    ("GET", r"^/api/users$", lambda cn, u, b, q: api_users(cn, u), "用户列表"),
    # 集成
    ("GET", r"^/api/integration/overview$", lambda cn, u, b, q: api_integration_overview(cn, u),
     "集成总览"),
    ("GET", r"^/api/integration/keys$", lambda cn, u, b, q: api_int_keys(cn, u), "Key 列表"),
    ("POST", r"^/api/integration/keys$", lambda cn, u, b, q: api_int_key_create(cn, u, b), "新建 Key"),
    ("DELETE", r"^/api/integration/keys/(\d+)$",
     lambda cn, u, b, q, c: api_int_key_revoke(cn, u, int(c)), "吊销 Key"),
    ("GET", r"^/api/integration/webhooks$", lambda cn, u, b, q: api_int_webhooks(cn, u), "Webhook 列表"),
    ("POST", r"^/api/integration/webhooks$",
     lambda cn, u, b, q: api_int_webhook_save(cn, u, b), "新建 Webhook"),
    ("PUT", r"^/api/integration/webhooks/(\d+)$",
     lambda cn, u, b, q, c: api_int_webhook_save(cn, u, b, int(c)), "更新 Webhook"),
    ("DELETE", r"^/api/integration/webhooks/(\d+)$",
     lambda cn, u, b, q, c: api_int_webhook_delete(cn, u, int(c)), "删除 Webhook"),
    ("POST", r"^/api/integration/webhooks/(\d+)/test$",
     lambda cn, u, b, q, c: api_int_webhook_test(cn, u, int(c)), "测试事件"),
    ("GET", r"^/api/integration/deliveries$", lambda cn, u, b, q: api_int_deliveries(cn, u, q),
     "投递记录"),
    ("POST", r"^/api/integration/deliveries/(\d+)/retry$",
     lambda cn, u, b, q, c: api_int_delivery_retry(cn, u, int(c)), "重投"),
    ("GET", r"^/api/integration/mappings$", lambda cn, u, b, q: api_int_mappings(cn, u, q), "映射列表"),
    ("POST", r"^/api/integration/mappings$", lambda cn, u, b, q: api_int_mapping_save(cn, u, b),
     "绑定映射"),
    ("GET", r"^/api/integration/resolve$", lambda cn, u, b, q: api_int_resolve(cn, u, q), "外部 ID 反查"),
    ("GET", r"^/api/sync/changes$", lambda cn, u, b, q: api_sync_changes(cn, u, q), "增量变更"),
    ("GET", r"^/api/export/orders$", lambda cn, u, b, q: api_export_orders(cn, u, q), "导出工单"),
    ("GET", r"^/api/export/oee$", lambda cn, u, b, q: api_export_oee(cn, u, q), "导出 OEE"),
]


# ---------------------------------------------------------------- Webhook 投递
def _post_json(url, body, headers, timeout=6):
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("unsupported scheme")
    conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    conn = conn_cls(u.hostname, u.port, timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()[:200]
    finally:
        conn.close()


def _deliver(d):
    headers = {"Content-Type": "application/json", "X-Fc-Event": d["event"],
               "X-Fc-Signature": d["signature"], "X-Fc-Delivery": str(d["id"]),
               "X-Fc-Timestamp": str(int(time.time())), "User-Agent": "FeichiMES/1.0"}
    return _post_json(d["url"], d["payload"], headers) if d.get("url") else (0, b"")


def _worker_loop():
    while True:
        try:
            time.sleep(2)
            cn = db.conn()
            try:
                items = rows(cn, "SELECT d.*, w.url FROM webhook_deliveries d LEFT JOIN webhooks w"
                                 " ON w.id=d.webhook_id WHERE d.status='待投递' AND d.next_at<=?"
                                 " ORDER BY d.id LIMIT 10", (now(),))
                for d in items:
                    try:
                        code, _ = _deliver(d)
                        ok = 200 <= int(code) < 300
                    except Exception as e:  # noqa: BLE001
                        code, ok = 0, False
                        cn.execute("UPDATE webhook_deliveries SET error=? WHERE id=?",
                                   (str(e)[:200], d["id"]))
                    attempts = int(d["attempts"] or 0) + 1
                    if ok:
                        cn.execute("UPDATE webhook_deliveries SET status='成功', attempts=?, http_code=?,"
                                   " delivered_at=?, error='' WHERE id=?",
                                   (attempts, code, now(), d["id"]))
                    elif attempts >= WEBHOOK_MAX_TRY:
                        cn.execute("UPDATE webhook_deliveries SET status='失败', attempts=?, http_code=?"
                                   " WHERE id=?", (attempts, code, d["id"]))
                    else:
                        delay = 30 * (2 ** (attempts - 1))
                        nxt = (datetime.now() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                        cn.execute("UPDATE webhook_deliveries SET attempts=?, http_code=?, next_at=?"
                                   " WHERE id=?", (attempts, code, nxt, d["id"]))
                cn.commit()
            finally:
                cn.close()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            time.sleep(5)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "FeichiMES/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        return None

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError("请求体不是合法 JSON", 400)

    def _tokens(self):
        """多通道取票：任意一个有效即可，避免反向代理改写 Authorization 后掉登录。"""
        out = []
        for h in ("X-Fc-Key", "X-Fc-Token", "X-Auth-Token", "Authorization"):
            v = (self.headers.get(h) or "").strip()
            if not v:
                continue
            if v[:7].lower() == "bearer ":
                v = v[7:].strip()
            if v:
                out.append(v)
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() in ("fc_token", "token") and v.strip():
                    out.append(v.strip())
        seen, res = set(), []
        for t in out:
            if t not in seen:
                seen.add(t)
                res.append(t)
        return res

    def _dispatch(self, method):
        with LOCK:
            return self._route(method)

    def _route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        for prefix in ("/mes", "/feichi"):
            if path.startswith(prefix + "/"):
                path = path[len(prefix):]
        query = parse_qs(parsed.query)
        body = {}
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            try:
                body = self._read_body()
            except ApiError as e:
                return self._send(e.code, {"error": e.message})

        if path == "/api/health":
            info = {"status": "up", "version": VERSION, "time": now(),
                    "pid": os.getpid(), "uptime": int(time.time() - START_TS)}
            try:
                cn = db.conn()
                info["workOrders"] = cn.execute("SELECT COUNT(*) c FROM work_orders").fetchone()["c"]
                info["equipment"] = cn.execute("SELECT COUNT(*) c FROM equipment").fetchone()["c"]
                info["journal"] = cn.execute("PRAGMA journal_mode").fetchone()[0]
                cn.close()
            except Exception as e:  # noqa: BLE001
                info["dbError"] = str(e)[:120]
            return self._send(200, {"ok": True, "data": info})

        if path == "/api/openapi.json":
            return self._send(200, openapi_spec())

        tokens = self._tokens()
        if query.get("token"):
            tokens.append(query["token"][0])
        if isinstance(body, dict) and body.get("token"):
            tokens.append(str(body["token"]))
        token = tokens[0] if tokens else ""
        if method == "POST" and path == "/api/auth/logout":
            cn = db.conn()
            try:
                api_logout(cn, token)
            finally:
                cn.close()
            return self._send(200, {"ok": True, "data": {"loggedOut": True}})

        if not path.startswith("/api/"):
            return self._static(path)

        idem = self.headers.get("Idempotency-Key") or ""
        if idem and method == "POST":
            cn0 = db.conn()
            try:
                cached = one(cn0, "SELECT * FROM idem_keys WHERE key=?", (idem,))
            finally:
                cn0.close()
            if cached:
                return self._send(200, json.loads(cached["response"]),
                                  headers={"X-Idempotent-Replay": "true"})

        for m, pattern, fn, _ in ROUTES:
            if m != method:
                continue
            match = re.match(pattern, path)
            if not match:
                continue
            groups = match.groups()
            need_token = (method, path) not in OPEN_PATHS
            cn = db.conn()
            try:
                user = None
                for tk in tokens:
                    user = auth_user(cn, tk)
                    if user:
                        token = tk
                        break
                if need_token and not user:
                    return self._send(401, {"error": "未登录或会话已过期"})
                if user:
                    rate_check(user)
                query["_token"] = [token]
                data = fn(cn, user, body, query, *groups)
                if isinstance(data, dict) and "csv" in data:
                    csv_body = ("\ufeff" + data["csv"]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename*=UTF-8''" + quote(data["filename"]))
                    self.send_header("Content-Length", str(len(csv_body)))
                    self.end_headers()
                    self.wfile.write(csv_body)
                    return None
                payload = {"ok": True, "data": data}
                if idem and method == "POST":
                    cn.execute("INSERT OR REPLACE INTO idem_keys(key,path,response,created_at)"
                               " VALUES(?,?,?,?)",
                               (idem, path, json.dumps(payload, ensure_ascii=False), now()))
                    cn.commit()
                return self._send(200, payload)
            except ApiError as e:
                out = {"error": e.message}
                out.update(e.extra)
                headers = {"Retry-After": "60"} if e.code == 429 else None
                return self._send(e.code, out, headers=headers)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._send(500, {"error": "服务异常：%s" % e})
            finally:
                cn.close()
        return self._send(404, {"error": "接口不存在：%s %s" % (method, path)})

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        safe = path.replace("\\", "/").lstrip("/")
        if ".." in safe.split("/"):
            return self._send(403, {"error": "非法路径"})
        target = os.path.join(FRONTEND, *safe.split("/"))
        if not os.path.isfile(target):
            return self._send(404, {"error": "文件不存在"})
        ctype = "text/html; charset=utf-8"
        if target.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif target.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
        return None

    def do_GET(self):
        return self._dispatch("GET")

    def do_POST(self):
        return self._dispatch("POST")

    def do_PUT(self):
        return self._dispatch("PUT")

    def do_DELETE(self):
        return self._dispatch("DELETE")


def main():
    db.init_db()
    threading.Thread(target=_worker_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("飞驰 MES v%s 已启动：http://%s:%s" % (VERSION, HOST, PORT))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
