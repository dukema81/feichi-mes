# -*- coding: utf-8 -*-
"""飞驰 MES · 业务内核（纯函数，无 IO / 无 SQL / 无全局状态）

所有口径集中在此文件，服务端、种子数据、报表、DEMO 与测试共用同一套算法：
- OEE（可用率 × 性能率 × 质量率）、MTBF / MTTR、工时达成
- 工单状态机与五类闸口（下达 / 开工 / 完工 / 入库 / 关闭）
- BOM 齐套率、节拍与产线平衡、ABC
- 过程检验结论、CPK、缺陷帕累托、PPM
- 设备状态与保养到期、批次追溯链路、Webhook 签名
"""
import hashlib
import hmac
import json
import math
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- 角色与权限
ROLE_LABEL = {
    "admin": "系统管理员",
    "plant_manager": "生产总监",
    "planner": "计划员",
    "operator": "班组长",
    "quality": "质量工程师",
    "equipment": "设备工程师",
    "warehouse": "仓管员",
    "viewer": "观察者",
}

_PERM = {
    "admin": {"read", "write", "approve", "report", "inspect", "equip", "stock", "admin"},
    "plant_manager": {"read", "write", "approve", "report", "inspect", "equip", "stock"},
    "planner": {"read", "write", "approve"},
    "operator": {"read", "write", "report"},
    "quality": {"read", "inspect", "report"},
    "equipment": {"read", "equip"},
    "warehouse": {"read", "stock", "report"},
    "viewer": {"read"},
}

PERM_LABEL = {
    "read": "查看", "write": "计划维护", "approve": "审批", "report": "报工",
    "inspect": "质检", "equip": "设备", "stock": "库存", "admin": "系统管理",
}


def can(role, perm):
    return perm in _PERM.get(role, {"read"})


# ---------------------------------------------------------------- 数值与格式
def r2(x):
    try:
        return round(float(x) + 0.0, 2)
    except (TypeError, ValueError):
        return 0.0


def r4(x):
    try:
        return round(float(x) + 0.0, 4)
    except (TypeError, ValueError):
        return 0.0


def ratio(a, b, digits=4):
    try:
        a, b = float(a or 0), float(b or 0)
    except (TypeError, ValueError):
        return 0.0
    if b == 0:
        return 0.0
    return round(a / b, digits)


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(x or 0)))


def parse_date(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time(s):
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except ValueError:
            continue
    return None


def days_between(a, b):
    """b - a 的天数（a、b 可为字符串）。"""
    da, db_ = parse_date(a), parse_date(b)
    if not da or not db_:
        return 0
    return (db_ - da).days


def minutes_between(a, b):
    ta, tb = parse_time(a), parse_time(b)
    if not ta or not tb:
        return 0
    return int((tb - ta).total_seconds() // 60)


def add_days(d, n):
    dd = parse_date(d) or date.today()
    return (dd + timedelta(days=int(n))).isoformat()


def doc_no(kind, day, seq):
    d = parse_date(day) or date.today()
    return "%s%s-%04d" % (kind, d.strftime("%Y%m%d"), int(seq))


def norm_text(s):
    return "".join(str(s or "").split()).replace("（", "(").replace("）", ")").lower()


def sha256(s):
    return hashlib.sha256(str(s or "").encode("utf-8")).hexdigest()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def sign_payload(secret, timestamp, body):
    """Webhook 签名：HMAC-SHA256(secret, timestamp + "." + body)。"""
    msg = ("%s.%s" % (timestamp, body)).encode("utf-8")
    return hmac.new(str(secret or "").encode("utf-8"), msg, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- 工单状态机
WO_FLOW = ["草稿", "已下达", "已开工", "已完工", "已入库", "已关闭"]
WO_CLOSED = {"已关闭", "已取消"}


def wo_index(status):
    try:
        return WO_FLOW.index(status)
    except ValueError:
        return -1


def can_move_wo(cur, target):
    """只能前进（可跨级）、不能回退、终态锁定。"""
    if cur in WO_CLOSED:
        return False
    if target == "已取消":
        return cur in ("草稿", "已下达", "已开工")
    i, j = wo_index(cur), wo_index(target)
    return i >= 0 and j > i


def wo_next(status):
    i = wo_index(status)
    if i < 0 or i >= len(WO_FLOW) - 1:
        return []
    return WO_FLOW[i + 1:]


def wo_gate(target, ctx):
    """返回推进到 target 缺失的条件清单；空清单表示闸口通过。

    ctx 约定：
      qty 计划数量 / kitRate 齐套率 / bomOk / routingOk / faiPass 首件合格
      equipOk 设备可用 / opsDone 工序全部报工 / goodQty 合格数 / reportedQty 已报工数
      inspPass 完工检验合格 / batchNo 批次号 / defects 未处置不良数
    """
    miss = []
    target = str(target or "")
    if target == "已下达":
        if float(ctx.get("qty") or 0) <= 0:
            miss.append("计划数量必须大于 0")
        if not ctx.get("routingOk"):
            miss.append("工艺路线未发布")
        if not ctx.get("bomOk"):
            miss.append("BOM 未发布或无明细")
        if float(ctx.get("kitRate") or 0) < 1.0 - 1e-9:
            miss.append("物料齐套率 %.0f%%，未达 100%%" % (float(ctx.get("kitRate") or 0) * 100))
    elif target == "已开工":
        if wo_index(ctx.get("status")) < wo_index("已下达"):
            miss.append("工单尚未下达")
        if not ctx.get("faiPass"):
            miss.append("首件检验未合格")
        if not ctx.get("equipOk"):
            miss.append("工位设备处于故障或保养状态")
        if not ctx.get("hasOperator"):
            miss.append("未派工（缺少责任班组）")
    elif target == "已完工":
        if wo_index(ctx.get("status")) < wo_index("已开工"):
            miss.append("工单尚未开工")
        if not ctx.get("opsDone"):
            miss.append("仍有工序未完成报工")
        need = float(ctx.get("qty") or 0)
        if float(ctx.get("reportedQty") or 0) < need - 1e-9:
            miss.append("累计报工 %.0f < 计划 %.0f" % (float(ctx.get("reportedQty") or 0), need))
    elif target == "已入库":
        if wo_index(ctx.get("status")) < wo_index("已完工"):
            miss.append("工单尚未完工")
        if not ctx.get("inspPass"):
            miss.append("完工检验未合格")
        if not ctx.get("batchNo"):
            miss.append("缺少产出批次号")
    elif target == "已关闭":
        if wo_index(ctx.get("status")) < wo_index("已入库"):
            miss.append("工单尚未入库")
        if int(ctx.get("defects") or 0) > 0:
            miss.append("仍有 %d 件不良未处置" % int(ctx.get("defects") or 0))
    return miss


def wo_stage_by_qty(qty, reported, good):
    """按报工量推断阶段（未显式推进时用于展示）。"""
    qty, reported = float(qty or 0), float(reported or 0)
    if reported <= 0:
        return "已下达"
    if reported >= qty > 0:
        return "已完工"
    return "已开工"


def progress(qty, reported):
    q = float(qty or 0)
    if q <= 0:
        return 0.0
    return r4(clamp(float(reported or 0) / q, 0, 1.5))


def due_state(plan_end, today, warn_days=1):
    d = days_between(today, plan_end)
    if not plan_end:
        return "未排期"
    if d < 0:
        return "逾期"
    if d <= warn_days:
        return "临期"
    return "正常"


# ---------------------------------------------------------------- 效率指标
def availability(plan_min, run_min):
    """可用率 = 实际运行 / 计划开机。"""
    plan = float(plan_min or 0)
    if plan <= 0:
        return 0.0
    return r4(clamp(float(run_min or 0) / plan))


def performance(ideal_cycle_sec, output, run_min):
    """性能率 = 理论节拍 × 产出 / 实际运行时间（上限 100%）。"""
    run = float(run_min or 0)
    if run <= 0:
        return 0.0
    return r4(clamp(float(ideal_cycle_sec or 0) * float(output or 0) / 60.0 / run))


def quality_rate(good, output):
    return r4(ratio(good, output))


def oee(plan_min, run_min, ideal_cycle_sec, output, good):
    a = availability(plan_min, run_min)
    p = performance(ideal_cycle_sec, output, run_min)
    q = quality_rate(good, output)
    return {
        "availability": a, "performance": p, "quality": q,
        "oee": r4(a * p * q),
        "planMin": r2(plan_min), "runMin": r2(run_min),
        "downMin": r2(max(0.0, float(plan_min or 0) - float(run_min or 0))),
        "output": r2(output), "good": r2(good),
        "lossMin": r2(max(0.0, float(plan_min or 0) - float(run_min or 0))),
    }


def yield_rate(good, total):
    return r4(ratio(good, total))


def scrap_rate(ng, total):
    return r4(ratio(ng, total))


def ppm(ng, total):
    return int(round(ratio(ng, total, 6) * 1000000))


def oee_level(v, target=0.85):
    v = float(v or 0)
    if v >= float(target):
        return "达标"
    if v >= float(target) * 0.85:
        return "预警"
    return "未达标"


def mtbf(run_min, failures):
    f = int(failures or 0)
    if f <= 0:
        return r2(run_min)
    return r2(float(run_min or 0) / f)


def mttr(down_min, failures):
    f = int(failures or 0)
    if f <= 0:
        return 0.0
    return r2(float(down_min or 0) / f)


def manpower_efficiency(std_min, actual_min):
    """工时达成率 = 标准工时 / 实际工时（>1 表示效率高于标准）。"""
    return r4(ratio(std_min, actual_min))


def capacity_load(std_min, avail_min):
    """产能负荷 = 需求标准工时 / 可用工时。"""
    return r4(ratio(std_min, avail_min))


def takt_time(avail_min, demand):
    d = float(demand or 0)
    if d <= 0:
        return 0.0
    return r2(float(avail_min or 0) / d)


def line_balance(step_times):
    """产线平衡率 = Σ工时 / (瓶颈工时 × 工位数)。"""
    ts = [float(x or 0) for x in step_times if float(x or 0) > 0]
    if not ts:
        return 0.0
    return r4(sum(ts) / (max(ts) * len(ts)))


def bottleneck(step_times):
    ts = [float(x or 0) for x in step_times]
    return r2(max(ts)) if ts else 0.0


# ---------------------------------------------------------------- 齐套与 BOM
def kit_rate(items):
    """items: [{need, avail}]；返回按项齐套率、按量齐套率与缺口清单。"""
    rows_ = list(items or [])
    if not rows_:
        return {"rate": 0.0, "qtyRate": 0.0, "shortages": [], "total": 0, "ready": 0}
    ready = 0
    need_sum = avail_sum = 0.0
    shortages = []
    for it in rows_:
        need = float(it.get("need") or 0)
        avail = float(it.get("avail") or 0)
        need_sum += need
        avail_sum += min(need, avail)
        if avail + 1e-9 >= need:
            ready += 1
        else:
            shortages.append({
                "materialCode": it.get("materialCode") or it.get("code"),
                "materialName": it.get("materialName") or it.get("name") or "",
                "need": r2(need), "avail": r2(avail), "short": r2(need - avail),
                "unit": it.get("unit") or "",
            })
    return {
        "rate": r4(ready / len(rows_)),
        "qtyRate": r4(ratio(avail_sum, need_sum)),
        "shortages": shortages, "total": len(rows_), "ready": ready,
    }


def short_qty(need, avail):
    return r2(max(0.0, float(need or 0) - float(avail or 0)))


def abc_classify(items, a_line=0.7, b_line=0.9, key="amount"):
    """ABC：按金额降序累计，判定用「加入本物料之前」的累计占比。"""
    lst = [dict(x) for x in (items or [])]
    total = sum(float(x.get(key) or 0) for x in lst)
    out = []
    cum = 0.0
    for j in sorted(lst, key=lambda x: -float(x.get(key) or 0)):
        amt = float(j.get(key) or 0)
        share = r4(amt / total) if total else 0.0
        before = cum
        cum = r4(cum + share)
        j["share"] = share
        j["cum"] = cum
        j["abc"] = ("A" if before < float(a_line) - 1e-9
                    else ("B" if before < float(b_line) - 1e-9 else "C"))
        out.append(j)
    return out


# ---------------------------------------------------------------- 质量
def inspect_conclusion(sample_qty, defect_qty, aql=0.02):
    """完工/入库检结论：0 不良合格；不良率 ≤ 容差让步接收；否则退货。"""
    s, d = float(sample_qty or 0), float(defect_qty or 0)
    if s <= 0:
        return "待检"
    if d <= 0:
        return "合格"
    if d / s <= float(aql) + 1e-9:
        return "让步接收"
    return "退货"


def fai_conclusion(sample_qty, defect_qty):
    """首件：必须零缺陷。"""
    if float(sample_qty or 0) <= 0:
        return "待检"
    return "合格" if float(defect_qty or 0) <= 0 else "不合格"


def patrol_conclusion(defect_qty, defect_limit=0):
    return "正常" if float(defect_qty or 0) <= float(defect_limit or 0) else "异常"


def cpk(values, lsl, usl):
    """过程能力指数 Cpk = min((USL-μ), (μ-LSL)) / (3σ)，样本标准差。"""
    xs = []
    for v in values or []:
        try:
            xs.append(float(v))
        except (TypeError, ValueError):
            continue
    if len(xs) < 2:
        return None
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    sd = math.sqrt(var)
    if sd <= 1e-12:
        return None
    cpu = (float(usl) - mean) / (3 * sd)
    cpl = (mean - float(lsl)) / (3 * sd)
    return r4(min(cpu, cpl))


def cpk_level(v, minimum=1.33):
    if v is None:
        return "数据不足"
    v = float(v)
    if v >= float(minimum):
        return "充足"
    if v >= 1.0:
        return "偏低"
    return "不足"


def pareto(rows_, qty_key="qty"):
    """缺陷帕累托：数量降序 + 占比 + 累计占比（80% 线定位关键少数）。"""
    lst = [dict(x) for x in (rows_ or [])]
    total = sum(float(x.get(qty_key) or 0) for x in lst)
    out, cum = [], 0.0
    for j in sorted(lst, key=lambda x: -float(x.get(qty_key) or 0)):
        v = float(j.get(qty_key) or 0)
        share = r4(v / total) if total else 0.0
        cum = r4(cum + share)
        j["share"] = share
        j["cum"] = cum
        j["key"] = cum <= 0.8 + 1e-9
        out.append(j)
    return out


def loss_minutes(plan_min, run_min):
    return r2(max(0.0, float(plan_min or 0) - float(run_min or 0)))


# ---------------------------------------------------------------- 设备
EQUIP_STATES = ["运行", "待机", "故障", "保养", "停机"]
DOWN_REASONS = ["设备故障", "换型调机", "待料", "待检", "计划保养", "缺人", "其他"]

DOWN_REASON_NORM = {
    "设备故障": "故障", "换型调机": "换型", "待料": "待料", "待检": "待检",
    "计划保养": "保养", "缺人": "缺人", "其他": "其他",
}


def equip_available(status):
    return str(status or "") not in ("故障", "保养", "停机")


def maint_state(next_at, today, warn_days=7):
    if not next_at:
        return "未排程"
    d = days_between(today, next_at)
    if d < 0:
        return "逾期"
    if d <= int(warn_days or 0):
        return "临期"
    return "正常"


def maint_health(overdue, warn):
    if int(overdue or 0) > 0:
        return "逾期"
    if int(warn or 0) > 0:
        return "临期"
    return "正常"


def equip_health(status, overdue_maint, open_repairs):
    if str(status) == "故障" or int(open_repairs or 0) > 0:
        return "异常"
    if int(overdue_maint or 0) > 0:
        return "待保养"
    return "正常"


def downtime_top(logs, key="reason"):
    agg = {}
    for r in logs or []:
        k = str(r.get(key) or "其他")
        agg[k] = agg.get(k, 0.0) + float(r.get("minutes") or 0)
    total = sum(agg.values())
    out = [{"reason": k, "minutes": r2(v), "share": r4(v / total) if total else 0.0}
           for k, v in agg.items()]
    return sorted(out, key=lambda x: -x["minutes"])


# ---------------------------------------------------------------- 批次与追溯
def batch_state(qty, good, expire_at, today, warn_days=30):
    if float(qty or 0) <= 0:
        return "已耗尽"
    st = str(expire_at or "")
    if st:
        d = days_between(today, st)
        if d < 0:
            return "已过期"
        if d <= int(warn_days or 0):
            return "临期"
    return "正常"


def trace_chain(edges, root):
    """edges: [{parent, child}]；从 root 向下展开（成品 → 组件 → 原料）。"""
    children = {}
    for e in edges or []:
        children.setdefault(str(e.get("parent")), []).append(str(e.get("child")))
    out, seen, queue = [], set(), [(str(root), 0)]
    while queue:
        node, depth = queue.pop(0)
        if node in seen or depth > 8:
            continue
        seen.add(node)
        out.append({"batch": node, "depth": depth})
        for c in children.get(node, []):
            queue.append((c, depth + 1))
    return out


def trace_up(edges, leaf):
    parent = {}
    for e in edges or []:
        parent[str(e.get("child"))] = str(e.get("parent"))
    out, node, guard = [], str(leaf), 0
    while node in parent and guard < 8:
        node = parent[node]
        out.append(node)
        guard += 1
    return out


# ---------------------------------------------------------------- 班次与其他
SHIFTS = [
    {"code": "S1", "name": "白班", "start": 8, "end": 16},
    {"code": "S2", "name": "中班", "start": 16, "end": 24},
    {"code": "S3", "name": "夜班", "start": 0, "end": 8},
]


def shift_of(ts):
    t = parse_time(ts)
    h = t.hour if t else 8
    for s in SHIFTS:
        if s["start"] <= h < s["end"]:
            return s["name"]
    return "白班"


def sum_amount(items, key="amount"):
    return r2(sum(float(x.get(key) or 0) for x in (items or [])))


def weighted_avg(items, value_key, weight_key):
    tw = sum(float(x.get(weight_key) or 0) for x in (items or []))
    if tw <= 0:
        return 0.0
    return r4(sum(float(x.get(value_key) or 0) * float(x.get(weight_key) or 0)
                  for x in (items or [])) / tw)


def seq_label(i):
    return "OP%02d" % int(i)


def human_minutes(m):
    m = int(round(float(m or 0)))
    if m < 60:
        return "%d 分钟" % m
    return "%d 小时 %d 分" % (m // 60, m % 60)
