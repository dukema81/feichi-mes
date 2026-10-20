/* 飞驰 MES · 离线 DEMO 数据层：拦截 fetch，在浏览器内存中实现与后端同口径的读写 */
(function () {
  "use strict";
  if (!window.__DEMO__ || !window.DB) return;

  var DB = window.DB;

  /* 会话内续期：前端部分操作会 location.reload()，离线环境用 sessionStorage 保住内存改动 */
  var STORE_KEY = "fc_demo_db";
  try {
    var saved = sessionStorage.getItem(STORE_KEY);
    if (saved) {
      var parsed = JSON.parse(saved);
      if (parsed && parsed.orders && parsed.orderD) DB = window.DB = parsed;
    }
  } catch (e) { /* 隐私模式忽略 */ }

  function persist() {
    try {
      var s = JSON.stringify(DB);
      if (s.length < 3.6e6) sessionStorage.setItem(STORE_KEY, s);
    } catch (e) { /* 超限或隐私模式忽略 */ }
  }
  var NOW = new Date();

  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function r2(v) { return Math.round((Number(v || 0) + 1e-9) * 100) / 100; }
  function r4(v) { return Math.round((Number(v || 0) + 1e-9) * 10000) / 10000; }
  function clone(x) { return JSON.parse(JSON.stringify(x)); }
  function today() {
    return NOW.getFullYear() + "-" + pad(NOW.getMonth() + 1) + "-" + pad(NOW.getDate());
  }
  function nowStr() {
    return today() + " " + pad(NOW.getHours()) + ":" + pad(NOW.getMinutes()) + ":" + pad(NOW.getSeconds());
  }
  function minusMin(m) {
    var d = new Date(NOW.getTime() - m * 60000);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
      pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":00";
  }
  function addDays(n) {
    var d = new Date(NOW.getTime() + n * 86400000);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function docNo(list, prefix) {
    var max = 0;
    list.forEach(function (x) {
      var m = String(x.no || "").match(/(\d+)$/);
      if (m) max = Math.max(max, Number(m[1]));
    });
    return prefix + today().replace(/-/g, "") + "-" + ("000" + (max + 1)).slice(-4);
  }
  function ruleVal(code, def) {
    var hit = (DB.settings.rules || []).filter(function (r) { return r.code === code; })[0];
    return hit ? Number(hit.value) : def;
  }

  /* 演示环境固定以超级管理员身份进入 */
  DB.me = { username: "admin", displayName: "系统管理员", role: "admin",
    roleLabel: "系统管理员", authType: "demo",
    perms: ["admin", "approve", "equip", "inspect", "read", "report", "stock", "write"] };
  DB.boot.user = DB.me;
  DB.__changes = DB.sync.changes || [];
  DB.__changeId = DB.__changes.reduce(function (a, c) { return Math.max(a, c.id || 0); }, 0);
  DB.__keySeq = (DB.integ.keys.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__hookSeq = (DB.integ.webhooks.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__dlvSeq = (DB.integ.deliveries.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__mapSeq = (DB.integ.mappings.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__defSeq = (DB.defects.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);
  DB.__andonSeq = (DB.andon.list || []).reduce(function (a, k) { return Math.max(a, k.id); }, 0);

  var FLOW = ["草稿", "已下达", "已开工", "已完工", "已入库", "已关闭"];
  var TARGETS = ["已下达", "已开工", "已完工", "已入库", "已关闭"];

  function idx(s) { return FLOW.indexOf(s); }

  function log(action, detail) {
    var row = { id: (DB.logs.list.length ? DB.logs.list[0].id : 0) + 1,
      username: DB.me.username, name: DB.me.displayName, action: action,
      detail: detail || "", ip: "127.0.0.1", createdAt: nowStr() };
    DB.logs.list.unshift(row);
    if (DB.logs.list.length > 300) DB.logs.list.pop();
    if (DB.logs.total !== undefined) DB.logs.total += 1;
    DB.__changeId += 1;
    DB.__changes.push({ id: DB.__changeId, objType: "", objNo: String(detail || ""),
      op: "upsert", actor: DB.me.username, payload: {}, changedAt: nowStr() });
    DB.integ.overview.changes = DB.__changes.length;
    DB.integ.overview.lastChange = nowStr();
  }

  /* ------------------------------------------------------------ 工单口径 */
  function orderListRow(o) {
    var row = DB.orders.list.filter(function (x) { return x.no === o.no; })[0];
    if (!row) return null;
    ["status", "reportedQty", "goodQty", "ngQty", "progress", "opDone", "opCount",
      "actualMin", "eff", "kitRate", "kitShort", "batchNo", "actualStart", "actualEnd",
      "dueState", "nextTargets"].forEach(function (k) { row[k] = o[k]; });
    return row;
  }

  function currentOp(o) {
    var ops = o.operations || [];
    for (var i = 0; i < ops.length; i++) {
      if (Number(ops[i].goodQty) + Number(ops[i].ngQty) < Number(ops[i].planQty) - 1e-9) {
        return ops[i].process;
      }
    }
    return ops.length ? ops[ops.length - 1].process : "—";
  }

  function kitOf(o) {
    var total = 0, ready = 0;
    (o.materials || []).forEach(function (m) {
      total += 1;
      if (Number(m.onHand) + Number(m.issued) >= Number(m.need) - 1e-9) ready += 1;
    });
    return { total: total, ready: ready, rate: total ? r4(ready / total) : 1 };
  }

  function gateOf(o) {
    var g = {}, kit = o.kit || kitOf(o), cur = idx(o.status);
    TARGETS.forEach(function (t) {
      if (idx(t) <= cur) return;
      var miss = [];
      if (t === "已下达") {
        if (!(Number(o.qty) > 0)) miss.push("计划数量必须大于 0");
        if (!o.routingCode) miss.push("工艺路线未发布");
        if (!o.bomCode) miss.push("BOM 未发布或无明细");
        if (kit.rate < 1 - 1e-9) miss.push("物料齐套率 " + Math.round(kit.rate * 100) + "%，未达 100%");
      } else if (t === "已开工") {
        if (!(o.inspections || []).some(function (x) { return x.type === "首件" && x.result === "合格"; })) {
          miss.push("首件检验未合格");
        }
        if (!o.owner) miss.push("尚未派工");
        var bad = (o.operations || []).some(function (x) {
          var e = DB.equipD[x.equipment];
          return e && (e.status === "故障" || e.status === "停机");
        });
        if (bad) miss.push("存在故障或停机设备");
      } else if (t === "已完工") {
        if (Number(o.opDone) < Number(o.opCount)) miss.push("仍有工序未完成报工");
        else if (Number(o.reportedQty) < Number(o.qty)) miss.push("报工量不足计划数量");
      } else if (t === "已入库") {
        if (idx(o.status) < idx("已完工")) miss.push("工单尚未完工");
        if (!(o.inspections || []).some(function (x) {
          return x.type === "完工检" && x.result !== "不合格";
        })) miss.push("完工检未合格");
      } else if (t === "已关闭") {
        if (idx(o.status) < idx("已入库")) miss.push("工单尚未入库");
        var open = (o.defects || []).filter(function (d) {
          return !d.disposition || d.disposition === "待处置";
        });
        if (open.length) miss.push(open.length + " 条不良未处置");
      }
      if (miss.length) g[t] = miss;
    });
    return g;
  }

  function refreshOrder(o) {
    var good = 0, ng = 0, act = 0, done = 0;
    (o.operations || []).forEach(function (x) {
      good += Number(x.goodQty || 0);
      ng += Number(x.ngQty || 0);
      act += Number(x.actualMin || 0);
      var q = Number(x.goodQty || 0) + Number(x.ngQty || 0);
      x.progress = Number(x.planQty) ? r4(q / Number(x.planQty)) : 0;
      if (q >= Number(x.planQty) - 1e-9) done += 1;
      else x.status = q > 0 ? "进行中" : "待开工";
    });
    o.goodQty = r2(good);
    o.ngQty = r2(ng);
    o.reportedQty = r2(good + ng);
    o.actualMin = r2(act);
    o.opCount = (o.operations || []).length;
    o.opDone = done;
    o.progress = Number(o.qty) ? r4((good + ng) / Number(o.qty)) : 0;
    o.eff = act > 0 ? r4(Number(o.stdMin) / act) : 0;
    o.kit = kitOf(o);
    o.kitRate = o.status === "草稿" ? null : o.kit.rate;
    o.kitShort = o.status === "草稿" ? null : (o.kit.total - o.kit.ready);
    if (["已下达", "已开工"].indexOf(o.status) >= 0 && done === o.opCount &&
        (good + ng) >= Number(o.qty) - 1e-9) {
      o.status = "已完工";
      o.actualEnd = o.actualEnd || nowStr();
    }
    var cur = TARGETS.indexOf(o.status);
    o.nextTargets = TARGETS.slice(cur + 1);
    if (o.status === "已关闭" || o.status === "已取消") o.nextTargets = [];
    o.gate = gateOf(o);
    if (!o.batch) o.batchNo = o.batchNo || "";
    orderListRow(o);
  }

  /* ------------------------------------------------------------ 派生数据 */
  function refreshKpi() {
    var k = DB.boot.kpi, wip = 0, overdue = 0;
    DB.orders.list.forEach(function (o) {
      if (o.status === "已下达" || o.status === "已开工") {
        wip += 1;
        if (o.dueState === "逾期") overdue += 1;
      }
    });
    k.wip = wip;
    k.overdue = overdue;
    k.equipAbnormal = DB.equipment.list.filter(function (e) {
      return e.status === "故障" || e.status === "停机";
    }).length;
    k.maintDue = (DB.plans.list || []).filter(function (p) {
      return p.state === "逾期" || p.state === "临期";
    }).length;
    k.abnormalDefects = DB.defects.list.filter(function (d) {
      return !d.disposition || d.disposition === "待处置";
    }).length;
    k.pendingInsp = 0;
    var a = document.getElementById("pipeLabel");
    if (a) a.textContent = "在制工单：" + k.wip;
  }

  function buildBoard() {
    var b = clone(DB.board);
    b.lines.forEach(function (ln) {
      ln.orders = DB.orders.list.filter(function (o) {
        return o.line === ln.code && (o.status === "已下达" || o.status === "已开工");
      }).map(function (o) {
        var d = DB.orderD[o.no] || o;
        return { no: o.no, materialName: o.materialName, qty: o.qty, goodQty: o.goodQty,
          status: o.status, progress: o.progress, planEnd: o.planEnd,
          currentOp: currentOp(d) };
      });
      ln.wip = ln.orders.length;
    });
    b.andon = DB.andon.list.filter(function (x) { return x.status !== "已关闭"; })
      .map(function (x) { return decorateAndon(x); });
    b.time = nowStr();
    return b;
  }

  function decorateAndon(x) {
    var c = clone(x);
    var t0 = Date.parse(String(x.createdAt || "").replace(/-/g, "/"));
    if (!x.closedAt && t0) c.minutes = Math.max(0, Math.round((NOW.getTime() - t0) / 60000));
    return c;
  }

  function trimReport(days) {
    var d = clone(DB.reports);
    d.days = days;
    function cut(a) { return (a || []).slice(Math.max(0, (a || []).length - days)); }
    if (d.production) d.production.trend = cut(d.production.trend);
    if (d.oee) d.oee.trend = cut(d.oee.trend);
    if (d.quality) d.quality.trend = cut(d.quality.trend);
    return d;
  }

  function ok(data) { return { status: 200, body: { data: data } }; }
  function bad(msg, code) { return { status: code || 400, body: { error: msg } }; }

  /* ------------------------------------------------------------ 路由 */
  var ROUTES = [];
  function on(method, re, fn) { ROUTES.push([method, re, fn]); }
  function find(list, key, v) {
    for (var i = 0; i < (list || []).length; i++) if (list[i][key] === v) return list[i];
    return null;
  }

  /* 认证 / 启动 */
  on("POST", /^api\/auth\/login$/, function () {
    return ok({ token: "demo-token", user: DB.me });
  });
  on("POST", /^api\/auth\/logout$/, function () { return ok({ ok: true }); });
  on("GET", /^api\/auth\/me$/, function () { return ok(DB.me); });
  on("GET", /^api\/health$/, function () {
    return ok({ ok: true, version: "1.0.0-demo", journal: "memory" });
  });
  on("GET", /^api\/bootstrap$/, function () {
    refreshKpi();
    return ok(DB.boot);
  });

  /* 看板 / 安灯 */
  on("GET", /^api\/board$/, function () { return ok(buildBoard()); });
  on("GET", /^api\/andon$/, function () {
    var list = DB.andon.list.map(decorateAndon);
    return ok({ list: list, total: list.length,
      open: list.filter(function (x) { return x.status !== "已关闭"; }).length });
  });
  on("POST", /^api\/andon$/, function (m, qs, b) {
    if (!b.line) return bad("产线与工位不能为空");
    DB.__andonSeq += 1;
    var row = { id: DB.__andonSeq, no: "AD" + today().replace(/-/g, "").slice(0, 6) + pad(DB.__andonSeq),
      line: b.line, station: b.station || "", type: b.type || "设备",
      level: b.level || "一般", status: "待响应", reporter: DB.me.username,
      reporterName: DB.me.displayName, createdAt: nowStr(), closedAt: "",
      remark: b.remark || "", minutes: 0 };
    DB.andon.list.unshift(row);
    log("发起安灯呼叫", row.no + " · " + row.line);
    return ok({ id: row.id, no: row.no });
  });
  on("POST", /^api\/andon\/(\d+)\/close$/, function (m) {
    var a = find(DB.andon.list, "id", Number(m[1]));
    if (!a) return bad("安灯记录不存在", 404);
    if (a.status === "已关闭") return bad("该呼叫已关闭");
    a.status = "已关闭";
    a.closedAt = nowStr();
    log("关闭安灯呼叫", a.no);
    return ok({ id: a.id, status: a.status });
  });

  /* 工单 */
  on("GET", /^api\/orders$/, function (m, qs) {
    var list = DB.orders.list.slice(0);
    if (qs.status && qs.status !== "全部") {
      list = list.filter(function (o) { return o.status === qs.status; });
    }
    if (qs.overdue === "1") list = list.filter(function (o) { return o.dueState === "逾期"; });
    if (qs.kw) {
      var k = qs.kw.toLowerCase();
      list = list.filter(function (o) {
        return [o.no, o.materialCode, o.materialName, o.customer].join(" ").toLowerCase().indexOf(k) >= 0;
      });
    }
    list.sort(function (a, b) { return String(a.no) < String(b.no) ? 1 : -1; });
    return ok({ list: list, total: list.length });
  });
  on("GET", /^api\/orders\/([^/]+)$/, function (m) {
    var no = decodeURIComponent(m[1]);
    var o = DB.orderD[no];
    if (!o) return bad("工单不存在：" + no, 404);
    refreshOrder(o);
    return ok(o);
  });
  on("POST", /^api\/orders$/, function (m, qs, b) {
    var mat = DB.matD[b.materialCode] || find(DB.materials.list, "code", b.materialCode);
    if (!mat) return bad("产出物料不存在");
    var qty = Number(b.qty || 0);
    if (!(qty > 0)) return bad("计划数量必须大于 0");
    var tpl = null;
    DB.orders.list.some(function (o) {
      var d = DB.orderD[o.no];
      if (d && d.materialCode === b.materialCode) { tpl = d; return true; }
      return false;
    });
    var no = docNo(DB.orders.list, "WO");
    var steps = (mat.routing && mat.routing.steps) || [];
    var ops = (tpl && tpl.operations || []).map(function (x, i) {
      return { id: 900000 + i, seq: x.seq, process: x.process, station: x.station,
        equipment: x.equipment, planQty: qty, goodQty: 0, ngQty: 0,
        stdMin: r2(Number(x.stdMin || 0) * qty / Number(tpl.qty || qty)),
        actualMin: 0, status: "待开工", operator: "", operatorName: "",
        startAt: "", endAt: "", progress: 0, reportCount: 0 };
    });
    if (!ops.length) {
      ops = steps.map(function (s, i) {
        return { id: 910000 + i, seq: s.seq, process: s.process, station: s.station,
          equipment: "", planQty: qty, goodQty: 0, ngQty: 0, stdMin: 60, actualMin: 0,
          status: "待开工", operator: "", operatorName: "", startAt: "", endAt: "",
          progress: 0, reportCount: 0 };
      });
    }
    if (!ops.length) ops = [{ id: 920000, seq: 10, process: "总装", station: "ST-3011",
      equipment: "", planQty: qty, goodQty: 0, ngQty: 0, stdMin: 60, actualMin: 0,
      status: "待开工", operator: "", operatorName: "", startAt: "", endAt: "",
      progress: 0, reportCount: 0 }];

    var mats = ((mat.bom && mat.bom.items) || []).map(function (it) {
      var mo = find(DB.materials.list, "code", it.component) || {};
      return { materialCode: it.component, name: it.name || mo.name, spec: mo.spec || "",
        need: r2(Number(it.qty) * qty * (1 + Number(it.lossRate || 0))), issued: 0,
        unit: it.unit || mo.unit, onHand: Number(mo.onHand || 0), state: "", short: 0 };
    });
    mats.forEach(function (x) {
      x.short = Math.max(0, r2(x.need - x.onHand - x.issued));
      x.state = x.short > 0 ? "缺料" : "齐套";
    });

    var o = {
      no: no, materialCode: b.materialCode, materialName: mat.name,
      materialSpec: mat.spec, unit: mat.unit, qty: qty,
      workshop: (DB.boot.lines.filter(function (l) { return l.code === b.line; })[0] || {}).workshop || "WS-01",
      line: b.line || (DB.boot.lines[0] || {}).code, priority: b.priority || "普通",
      status: "草稿", planStart: b.planStart || today(),
      planEnd: b.planEnd || addDays(3), actualStart: "", actualEnd: "",
      routingCode: (mat.routing && mat.routing.code) || "", bomCode: (mat.bom && mat.bom.code) || "",
      salesNo: b.salesNo || "", customer: b.customer || "", planner: DB.me.username,
      plannerName: DB.me.displayName, owner: "", ownerName: "", team: "",
      remark: b.remark || "", createdAt: nowStr(),
      reportedQty: 0, goodQty: 0, ngQty: 0, progress: 0, opCount: ops.length, opDone: 0,
      stdMin: r2(ops.reduce(function (a, x) { return a + Number(x.stdMin || 0); }, 0)),
      actualMin: 0, eff: 0, dueState: "正常", nextTargets: TARGETS.slice(1),
      kitRate: null, kitShort: null, batchNo: "", batch: null,
      operations: ops, materials: mats, inspections: [], defects: [], reports: [],
      gate: {}
    };
    refreshOrder(o);
    DB.orderD[no] = o;
    DB.orders.list.unshift({
      no: no, materialCode: o.materialCode, materialName: o.materialName, qty: qty,
      workshop: o.workshop, line: o.line, priority: o.priority, status: "草稿",
      planStart: o.planStart, planEnd: o.planEnd, actualStart: "", actualEnd: "",
      routingCode: o.routingCode, bomCode: o.bomCode, customer: o.customer,
      planner: o.planner, plannerName: o.plannerName, owner: "", ownerName: "",
      team: "", remark: o.remark, createdAt: o.createdAt, reportedQty: 0, goodQty: 0,
      ngQty: 0, progress: 0, opCount: o.opCount, opDone: 0, stdMin: o.stdMin,
      actualMin: 0, eff: 0, dueState: "正常", nextTargets: o.nextTargets,
      canAdvance: [], kitRate: null, kitShort: null, batchNo: ""
    });
    DB.orders.total = (DB.orders.total || 0) + 1;
    log("新建生产工单", no + " · " + o.materialCode + " × " + qty);
    return ok({ no: no, opCount: o.opCount, status: o.status });
  });
  on("POST", /^api\/orders\/([^/]+)\/stage$/, function (m, qs, b) {
    var no = decodeURIComponent(m[1]), o = DB.orderD[no];
    if (!o) return bad("工单不存在", 404);
    var t = b.target;
    if ((o.nextTargets || []).indexOf(t) < 0) {
      return bad("不允许从「" + o.status + "」推进到「" + t + "」");
    }
    var miss = (o.gate || {})[t] || [];
    if (miss.length) return bad("闸口未通过：" + miss.join("；"));
    if (t === "已入库") return bad("请使用完工入库操作");
    o.status = t;
    if (t === "已开工") o.actualStart = o.actualStart || nowStr();
    if (t === "已完工") o.actualEnd = nowStr();
    refreshOrder(o);
    log("工单状态推进", no + " → " + t);
    return ok({ no: no, status: o.status, nextTargets: o.nextTargets });
  });
  on("POST", /^api\/orders\/([^/]+)\/cancel$/, function (m, qs, b) {
    var no = decodeURIComponent(m[1]), o = DB.orderD[no];
    if (!o) return bad("工单不存在", 404);
    if (["已入库", "已关闭", "已取消"].indexOf(o.status) >= 0) {
      return bad("工单已" + o.status + "，不能取消");
    }
    if (!b.reason) return bad("取消原因必填");
    o.status = "已取消";
    o.remark = (o.remark ? o.remark + "；" : "") + "取消：" + b.reason;
    refreshOrder(o);
    log("取消工单", no + " · " + b.reason);
    return ok({ no: no, status: o.status });
  });
  on("POST", /^api\/orders\/([^/]+)\/issue$/, function (m) {
    var no = decodeURIComponent(m[1]), o = DB.orderD[no];
    if (!o) return bad("工单不存在", 404);
    if (["已入库", "已关闭", "已取消"].indexOf(o.status) >= 0) return bad("工单已" + o.status);
    var n = 0;
    (o.materials || []).forEach(function (x) {
      if (Number(x.issued) < Number(x.need)) { x.issued = Number(x.need); n += 1; }
      x.short = Math.max(0, r2(Number(x.need) - Number(x.onHand) - Number(x.issued)));
      x.state = x.short > 0 ? "缺料" : "齐套";
    });
    refreshOrder(o);
    log("工单发料", no + " · " + n + " 项");
    return ok({ no: no, issued: n, kit: o.kit });
  });
  on("POST", /^api\/orders\/([^/]+)\/report$/, function (m, qs, b) {
    var no = decodeURIComponent(m[1]), o = DB.orderD[no];
    if (!o) return bad("工单不存在", 404);
    if (["草稿", "已下达"].indexOf(o.status) >= 0) return bad("工单尚未开工，不能报工");
    if (["已入库", "已关闭", "已取消"].indexOf(o.status) >= 0) return bad("工单已" + o.status);
    var op = (o.operations || []).filter(function (x) { return String(x.seq) === String(b.seq); })[0];
    if (!op) return bad("工序不存在");
    var good = Number(b.goodQty || 0), ng = Number(b.ngQty || 0);
    if (good < 0 || ng < 0) return bad("数量不能为负");
    if (good + ng <= 0) return bad("报工数量必须大于 0");
    if (Number(ruleVal("fai_required", 1)) >= 1 &&
        !(o.inspections || []).some(function (x) { return x.type === "首件" && x.result === "合格"; })) {
      return bad("首件检验未合格，不能报工（规则：首件必检）");
    }
    var tol = Number(ruleVal("over_report_tol", 0.05));
    var limit = Number(op.planQty) * (1 + tol);
    if (Number(op.goodQty) + Number(op.ngQty) + good + ng > limit + 1e-9) {
      return bad("超出工序计划量（含 " + Math.round(tol * 100) + "% 容差）");
    }
    op.goodQty = r2(Number(op.goodQty) + good);
    op.ngQty = r2(Number(op.ngQty) + ng);
    op.actualMin = r2(Number(op.actualMin) + Number(b.actualMin || 0));
    op.reportCount = Number(op.reportCount || 0) + 1;
    op.operator = DB.me.username;
    op.operatorName = DB.me.displayName;
    op.startAt = op.startAt || nowStr();
    op.endAt = nowStr();
    var reportNo = "RP" + today().replace(/-/g, "").slice(0, 8) + "-" + pad((o.reports || []).length + 1);
    o.reports = o.reports || [];
    o.reports.push({ no: reportNo, seq: op.seq, process: op.process, qty: good + ng,
      goodQty: good, ngQty: ng, actualMin: Number(b.actualMin || 0),
      operator: DB.me.username, shift: "白班", reportedAt: nowStr() });
    refreshOrder(o);
    log("生产报工", no + " · " + op.process + " +" + (good + ng));
    return ok({ reportNo: reportNo, eff: o.eff, woStatus: o.status,
      goodQty: o.goodQty, reportedQty: o.reportedQty, progress: o.progress });
  });
  on("POST", /^api\/orders\/([^/]+)\/stock-in$/, function (m, qs, b) {
    var no = decodeURIComponent(m[1]), o = DB.orderD[no];
    if (!o) return bad("工单不存在", 404);
    if (o.status !== "已完工") return bad("工单尚未完工，不能入库");
    if (!(o.inspections || []).some(function (x) {
      return x.type === "完工检" && x.result !== "不合格";
    })) return bad("完工检未合格，不能入库");
    var qty = Number(o.goodQty || o.qty);
    var bno = "B" + today().replace(/-/g, "") + "-" + pad(DB.batches.list.length + 1);
    var batch = { no: bno, materialCode: o.materialCode, materialName: o.materialName,
      woNo: o.no, qty: qty, goodQty: qty, workshop: o.workshop, line: o.line,
      producedAt: nowStr(), expireAt: addDays(730), status: "正常", parentBatch: "",
      remark: "工单入库批次", unit: o.unit, state: "正常", children: [], parent: [],
      order: { no: o.no, qty: o.qty, status: "已入库", customer: o.customer },
      stock: [{ warehouse: b.warehouse || "成品仓", qty: qty, updatedAt: nowStr() }],
      reports: (o.reports || []).map(function (x) {
        return { no: x.no, process: x.process, goodQty: x.goodQty,
          operator: x.operator, reportedAt: x.reportedAt };
      }) };
    DB.batches.list.unshift(batch);
    DB.batchD[bno] = batch;
    DB.trace[bno] = { root: bno, materialCode: o.materialCode, woNo: o.no,
      nodes: [{ batch: bno, materialCode: o.materialCode, materialName: o.materialName,
        qty: qty, depth: 0, producedAt: batch.producedAt, status: "正常" }],
      upstream: [], nodeCount: 1 };
    DB.stock.list.unshift({ materialCode: o.materialCode, name: o.materialName,
      unit: o.unit, warehouse: b.warehouse || "成品仓", batch: bno, qty: qty,
      amount: r2(qty * 0), updatedAt: nowStr() });
    DB.stock.total = (DB.stock.total || 0) + 1;
    var mat = DB.matD[o.materialCode];
    if (mat && mat.material) mat.material.onHand = r2(Number(mat.material.onHand) + qty);
    o.status = "已入库";
    o.batch = { no: bno, qty: qty, producedAt: batch.producedAt };
    o.batchNo = bno;
    refreshOrder(o);
    log("完工入库", no + " · 批次 " + bno);
    return ok({ batch: bno, qty: qty, status: o.status });
  });

  /* 物料与 BOM */
  on("GET", /^api\/materials$/, function (m, qs) {
    var list = DB.materials.list.slice(0);
    if (qs.type && qs.type !== "全部") list = list.filter(function (x) { return x.type === qs.type; });
    if (qs.kw) {
      var k = qs.kw.toLowerCase();
      list = list.filter(function (x) {
        return [x.code, x.name, x.spec].join(" ").toLowerCase().indexOf(k) >= 0;
      });
    }
    return ok({ list: list, total: list.length, summary: DB.materials.summary });
  });
  on("GET", /^api\/materials\/([^/]+)$/, function (m) {
    var code = decodeURIComponent(m[1]), d = DB.matD[code];
    if (!d) return bad("物料不存在：" + code, 404);
    return ok(d);
  });
  on("POST", /^api\/materials$/, function (m, qs, b) {
    if (!b.name) return bad("物料名称不能为空");
    var max = 0;
    DB.materials.list.forEach(function (x) {
      var n = Number(String(x.code || "").replace(/\D/g, ""));
      if (n) max = Math.max(max, n);
    });
    var code = b.code || ("MT-" + (max + 1));
    if (find(DB.materials.list, "code", code)) return bad("物料编码已存在：" + code);
    var row = { code: code, name: b.name, spec: b.spec || "", unit: b.unit || "件",
      category: b.category || "通用", type: b.type || "原材料", abc: "C",
      safetyStock: Number(b.safetyStock || 0), onHand: 0, stdCost: Number(b.stdCost || 0),
      leadDays: Number(b.leadDays || 0), status: "启用", remark: b.remark || "",
      short: 0, belowSafety: false, amount: 0, updatedAt: nowStr() };
    DB.materials.list.push(row);
    DB.materials.total = DB.materials.list.length;
    DB.matD[code] = { material: row, stock: [], bom: null, routing: null, orders: [], batches: [] };
    log("新建物料", code + " · " + row.name);
    return ok({ code: code, name: row.name });
  });

  /* 批次与追溯 */
  on("GET", /^api\/batches$/, function (m, qs) {
    var list = DB.batches.list.slice(0);
    if (qs.kw) {
      var k = qs.kw.toLowerCase();
      list = list.filter(function (x) {
        return [x.no, x.materialCode, x.materialName, x.woNo].join(" ").toLowerCase().indexOf(k) >= 0;
      });
    }
    return ok({ list: list, total: list.length, expiring: 0 });
  });
  on("GET", /^api\/batches\/([^/]+)$/, function (m) {
    var no = decodeURIComponent(m[1]), d = DB.batchD[no];
    if (!d) return bad("批次不存在：" + no, 404);
    return ok(d);
  });
  on("GET", /^api\/trace$/, function (m, qs) {
    var no = qs.batch || "";
    if (!no) return bad("批次号不能为空");
    var t = DB.trace[no];
    if (!t) {
      var b = DB.batchD[no];
      if (!b) return bad("批次不存在：" + no, 404);
      t = { root: no, materialCode: b.materialCode, woNo: b.woNo,
        nodes: [{ batch: no, materialCode: b.materialCode, materialName: b.materialName,
          qty: b.qty, depth: 0, producedAt: b.producedAt, status: b.status }],
        upstream: [], nodeCount: 1 };
    }
    return ok(t);
  });

  /* 质量 */
  on("GET", /^api\/quality\/summary$/, function () { return ok(DB.quality); });
  on("GET", /^api\/cpk$/, function () { return ok(DB.cpk); });
  on("GET", /^api\/defect-codes$/, function () { return ok(DB.defectCodes); });
  on("GET", /^api\/inspections$/, function (m, qs) {
    var list = DB.inspections.list.slice(0);
    if (qs.type && qs.type !== "全部") list = list.filter(function (x) { return x.type === qs.type; });
    if (qs.kw) {
      var k = qs.kw.toLowerCase();
      list = list.filter(function (x) {
        return [x.no, x.woNo, x.process].join(" ").toLowerCase().indexOf(k) >= 0;
      });
    }
    return ok({ list: list, total: list.length, typeDist: DB.inspections.typeDist });
  });
  on("GET", /^api\/inspections\/([^/]+)$/, function (m) {
    var no = decodeURIComponent(m[1]), d = DB.inspD[no];
    if (!d) return bad("检验单不存在：" + no, 404);
    return ok(d);
  });
  on("POST", /^api\/inspections$/, function (m, qs, b) {
    var o = DB.orderD[b.woNo];
    if (!o) return bad("工单不存在：" + b.woNo);
    var sample = Number(b.sampleQty || 0) || (b.items || []).length || 5;
    var defect = Number(b.defectQty || 0);
    if (sample <= 0) return bad("抽样数量必须大于 0");
    if (defect < 0) return bad("不良数不能为负");
    var rate = r4(defect / sample);
    var warn = Number(ruleVal("scrap_warn_rate", 0.03));
    var result = defect === 0 ? "合格" : (rate <= warn ? "让步接收" : "不合格");
    var cnt = DB.inspections.list.length + 1;
    var no = "IQ" + today().replace(/-/g, "") + "-" + pad(cnt);
    var row = { no: no, woNo: o.no, type: b.type || "巡检", seq: Number(b.seq || 0),
      process: b.process || "", sampleQty: sample, defectQty: defect, defectRate: rate,
      result: result, standard: "GB/T 2828.1", inspector: DB.me.username,
      inspectorName: DB.me.displayName, inspectedAt: nowStr(), remark: b.remark || "" };
    DB.inspections.list.unshift(row);
    DB.inspections.total = DB.inspections.list.length;
    DB.inspD[no] = Object.assign({}, row, { items: b.items || [], defects: [], cpk: null });
    o.inspections = o.inspections || [];
    o.inspections.unshift(row);
    refreshOrder(o);
    log("登记检验", no + " · " + row.type + " · " + result);
    return ok({ no: no, result: result, type: row.type, defectRate: rate });
  });
  on("GET", /^api\/defects$/, function () {
    return ok(DB.defects);
  });
  on("POST", /^api\/defects$/, function (m, qs, b) {
    var o = DB.orderD[b.woNo];
    if (!o) return bad("工单不存在：" + b.woNo);
    var qty = Number(b.qty || 0);
    if (!(qty > 0)) return bad("不良数量必须大于 0");
    var code = find((DB.defectCodes.list || []), "code", b.defectCode) || {};
    DB.__defSeq += 1;
    var row = { id: DB.__defSeq, woNo: o.no, inspectionNo: "", code: code.code || b.defectCode,
      name: code.name || "", category: code.category || "", severity: code.severity || "一般",
      qty: qty, process: b.process || "", equipment: "", operator: DB.me.username,
      occurAt: nowStr(), disposition: "待处置", remark: b.remark || "" };
    DB.defects.list.unshift(row);
    DB.defects.total = DB.defects.list.length;
    DB.defects.qty = r2(Number(DB.defects.qty || 0) + qty);
    DB.defects.pending = (DB.defects.pending || 0) + 1;
    o.defects = o.defects || [];
    o.defects.unshift({ id: row.id, code: row.code, qty: qty, process: row.process,
      disposition: row.disposition, occurAt: row.occurAt, inspectionNo: "" });
    refreshOrder(o);
    log("登记不良", o.no + " · " + row.code + " × " + qty);
    return ok({ id: row.id, qty: qty, disposition: row.disposition });
  });
  on("POST", /^api\/defects\/(\d+)\/dispose$/, function (m, qs, b) {
    var d = find(DB.defects.list, "id", Number(m[1]));
    if (!d) return bad("不良记录不存在", 404);
    if (!b.disposition) return bad("处置方式不能为空");
    d.disposition = b.disposition;
    if (b.remark) d.remark = b.remark;
    DB.defects.pending = Math.max(0, (DB.defects.pending || 1) - 1);
    var o = DB.orderD[d.woNo];
    if (o) {
      (o.defects || []).forEach(function (x) { if (x.id === d.id) x.disposition = d.disposition; });
      refreshOrder(o);
    }
    log("不良处置", d.woNo + " · " + d.code + " → " + d.disposition);
    return ok({ id: d.id, disposition: d.disposition });
  });

  /* 设备与保养 */
  on("GET", /^api\/equipment$/, function (m, qs) {
    var list = DB.equipment.list.slice(0);
    if (qs.status && qs.status !== "全部") list = list.filter(function (x) { return x.status === qs.status; });
    if (qs.kw) {
      var k = qs.kw.toLowerCase();
      list = list.filter(function (x) {
        return [x.code, x.name, x.line, x.type].join(" ").toLowerCase().indexOf(k) >= 0;
      });
    }
    return ok({ list: list, total: list.length, statusDist: DB.equipment.statusDist });
  });
  on("GET", /^api\/equipment\/([^/]+)$/, function (m) {
    var code = decodeURIComponent(m[1]), d = DB.equipD[code];
    if (!d) return bad("设备不存在：" + code, 404);
    return ok(d);
  });
  on("POST", /^api\/equipment\/([^/]+)\/status$/, function (m, qs, b) {
    var code = decodeURIComponent(m[1]), d = DB.equipD[code], row = find(DB.equipment.list, "code", code);
    if (!d) return bad("设备不存在：" + code, 404);
    var st = b.status;
    if (["运行", "待机", "故障", "保养", "停机"].indexOf(st) < 0) return bad("设备状态不合法");
    if (["故障", "保养", "停机"].indexOf(st) >= 0 && !b.reason) return bad("停机类状态必须填写原因");
    d.status = st;
    if (row) row.status = st;
    d.logs = d.logs || [];
    d.logs.unshift({ status: st, reason: b.reason || "", minutes: 0,
      startAt: nowStr(), endAt: "" });
    if (st === "运行") { d.health = "正常"; d.openRepairs = 0; }
    else if (st === "故障") { d.health = "异常"; d.openRepairs = Number(d.openRepairs || 0) + 1; }
    log("设备状态变更", code + " → " + st + (b.reason ? "（" + b.reason + "）" : ""));
    return ok({ code: code, status: st });
  });
  on("GET", /^api\/equip\/checks$/, function () {
    var list = DB.checks.list.slice(0);
    return ok({ list: list, total: list.length,
      abnormal: list.filter(function (x) { return x.result !== "正常"; }).length });
  });
  on("POST", /^api\/equip\/checks$/, function (m, qs, b) {
    var d = DB.equipD[b.equipment], row = find(DB.equipment.list, "code", b.equipment);
    if (!d) return bad("设备不存在：" + b.equipment);
    var bad2 = (b.items || []).filter(function (x) { return x.result !== "正常"; });
    var result = bad2.length ? "异常" : "正常";
    var no = "CK" + today().replace(/-/g, "") + "-" + pad(DB.checks.list.length + 1);
    var rec = { no: no, equipment: b.equipment, equipName: d.name, type: b.type || "日常点检",
      result: result, checker: DB.me.username, checkedAt: nowStr(),
      items: (b.items || []).map(function (x) { return x.item + "：" + x.result; }).join("；"),
      remark: b.remark || "" };
    DB.checks.list.unshift(rec);
    DB.checks.total = DB.checks.list.length;
    DB.checks.abnormal = (DB.checks.abnormal || 0) + (bad2.length ? 1 : 0);
    d.checks = d.checks || [];
    d.checks.unshift({ no: no, type: rec.type, result: result,
      checker: DB.me.username, checkedAt: rec.checkedAt });
    if (bad2.length) {
      d.status = "故障";
      d.health = "异常";
      if (row) row.status = "故障";
      d.logs = d.logs || [];
      d.logs.unshift({ status: "故障", reason: "点检异常：" + bad2[0].item,
        minutes: 0, startAt: nowStr(), endAt: "" });
    }
    log("设备点检", b.equipment + " · " + result);
    return ok({ no: no, result: result });
  });
  on("GET", /^api\/maint\/plans$/, function () {
    var list = DB.plans.list.map(function (p) {
      var c = clone(p);
      if (p.nextAt && String(p.nextAt) < today()) c.state = "逾期";
      return c;
    });
    return ok({ list: list, total: list.length,
      due: list.filter(function (p) { return p.state === "逾期" || p.state === "临期"; }).length });
  });
  on("GET", /^api\/maint\/orders$/, function () {
    return ok({ list: DB.maintOrders.list, total: DB.maintOrders.list.length,
      open: DB.maintOrders.list.filter(function (x) { return x.status !== "已完成"; }).length });
  });
  on("POST", /^api\/maint\/orders$/, function (m, qs, b) {
    var d = DB.equipD[b.equipment], row = find(DB.equipment.list, "code", b.equipment);
    if (!d) return bad("设备不存在：" + b.equipment);
    var no = "MT" + today().replace(/-/g, "").slice(0, 8) + "-" + pad(DB.maintOrders.list.length + 1);
    var rec = { no: no, equipment: b.equipment, equipName: d.name,
      planCode: d.planCode || "", type: b.type || "计划保养", reason: b.reason || "",
      status: "待处理", planAt: b.planAt || today(), startAt: "", finishAt: "",
      downtimeMin: 0, cost: 0, owner: DB.me.username };
    DB.maintOrders.list.unshift(rec);
    DB.maintOrders.total = DB.maintOrders.list.length;
    d.maint = d.maint || [];
    d.maint.unshift({ no: no, type: rec.type, reason: rec.reason, status: rec.status,
      planAt: rec.planAt, finishAt: "", downtimeMin: 0, cost: 0 });
    if (row && b.type === "故障维修") row.status = "故障";
    else if (row) row.status = "保养";
    d.status = b.type === "故障维修" ? "故障" : "保养";
    log("新建保养工单", no + " · " + b.equipment);
    return ok({ no: no, status: rec.status });
  });
  on("POST", /^api\/maint\/orders\/([^/]+)\/finish$/, function (m, qs, b) {
    var no = decodeURIComponent(m[1]), rec = find(DB.maintOrders.list, "no", no);
    if (!rec) return bad("保养工单不存在：" + no, 404);
    if (rec.status === "已完成") return bad("该保养工单已完成");
    rec.status = "已完成";
    rec.startAt = rec.startAt || nowStr();
    rec.finishAt = nowStr();
    rec.downtimeMin = Number(b.downtimeMin || 0);
    rec.cost = Number(b.cost || 0);
    var d = DB.equipD[rec.equipment], row = find(DB.equipment.list, "code", rec.equipment);
    if (d) {
      d.status = "运行";
      d.health = "正常";
      d.lastMaintAt = today();
      d.nextMaintAt = addDays(30);
      d.openRepairs = 0;
      (d.maint || []).forEach(function (x) { if (x.no === no) { x.status = "已完成"; x.finishAt = rec.finishAt; } });
      if (d.plan) { d.plan.lastAt = today(); d.plan.nextAt = addDays(30); d.plan.state = "正常"; }
    }
    if (row) { row.status = "运行"; row.lastMaintAt = today(); row.nextMaintAt = addDays(30); row.maintState = "正常"; }
    var plan = find(DB.plans.list, "code", rec.planCode);
    if (plan) { plan.lastAt = today(); plan.nextAt = addDays(30); plan.state = "正常"; }
    log("完成保养", no + " · " + rec.equipment);
    return ok({ no: no, status: rec.status, equipment: rec.equipment });
  });

  /* 库存与报表 */
  on("GET", /^api\/stock$/, function (m, qs) {
    var list = DB.stock.list.slice(0);
    if (qs.warehouse && qs.warehouse !== "全部") {
      list = list.filter(function (x) { return x.warehouse === qs.warehouse; });
    }
    if (qs.kw) {
      var k = qs.kw.toLowerCase();
      list = list.filter(function (x) {
        return [x.materialCode, x.name, x.batch].join(" ").toLowerCase().indexOf(k) >= 0;
      });
    }
    var qty = 0, amount = 0;
    list.forEach(function (x) { qty += Number(x.qty || 0); amount += Number(x.amount || 0); });
    return ok({ list: list, total: list.length, warehouses: DB.stock.warehouses,
      summary: { rows: list.length, qty: r2(qty), amount: r2(amount) } });
  });
  on("GET", /^api\/reports$/, function (m, qs) {
    return ok(trimReport(Number(qs.days || 30)));
  });

  /* 设置 / 日志 */
  on("GET", /^api\/settings$/, function () { return ok(DB.settings); });
  on("PUT", /^api\/rules\/([^/]+)$/, function (m, qs, b) {
    var code = decodeURIComponent(m[1]);
    var r = find(DB.settings.rules, "code", code) || find(DB.boot.rules, "code", code);
    if (!r) return bad("规则不存在", 404);
    if (b.value !== undefined) r.value = Number(b.value);
    if (b.enabled !== undefined) r.enabled = b.enabled ? 1 : 0;
    log("调整业务规则", code + " → " + (b.value !== undefined ? b.value : (b.enabled ? "启用" : "停用")));
    return ok({ code: code, value: r.value, enabled: r.enabled });
  });
  on("GET", /^api\/logs$/, function (m, qs) {
    var limit = Number(qs.limit || 200);
    return ok({ list: DB.logs.list.slice(0, limit), total: DB.logs.list.length });
  });

  /* 集成中心 */
  on("GET", /^api\/integration\/overview$/, function () {
    var o = clone(DB.integ.overview);
    o.keys = DB.integ.keys.list.length;
    o.webhooks = DB.integ.webhooks.list.length;
    o.deliveries = DB.integ.deliveries.list.length;
    o.deliveryFailed = DB.integ.deliveries.list.filter(function (x) { return x.status === "失败"; }).length;
    o.mappings = DB.integ.mappings.list.length;
    o.changes = DB.__changes.length;
    o.lastChange = DB.__changes.length ? DB.__changes[DB.__changes.length - 1].changedAt : "";
    return ok(o);
  });
  on("GET", /^api\/integration\/keys$/, function () {
    var list = DB.integ.keys.list;
    return ok({ list: list, active: list.filter(function (x) { return x.status === "启用"; }).length });
  });
  on("POST", /^api\/integration\/keys$/, function (m, qs, b) {
    if (!b.name) return bad("Key 名称不能为空");
    DB.__keySeq += 1;
    var raw = "fck_" + Math.random().toString(36).slice(2, 12) + Math.random().toString(36).slice(2, 8);
    var rec = { id: DB.__keySeq, name: b.name, prefix: raw.slice(0, 12),
      scope: b.scope || "read", owner: DB.me.username, status: "启用",
      createdAt: nowStr(), lastUsedAt: "", expiresAt: "" };
    DB.integ.keys.list.unshift(rec);
    log("创建 API Key", b.name);
    return ok({ id: rec.id, key: raw, name: b.name, scope: rec.scope,
      notice: "密钥只显示一次，请立即保存（DEMO 中刷新即失效）" });
  });
  on("DELETE", /^api\/integration\/keys\/(\d+)$/, function (m) {
    var rec = find(DB.integ.keys.list, "id", Number(m[1]));
    if (!rec) return bad("Key 不存在", 404);
    rec.status = "吊销";
    log("吊销 API Key", rec.name);
    return ok({ id: rec.id, status: rec.status });
  });
  on("GET", /^api\/integration\/webhooks$/, function () {
    return ok({ list: DB.integ.webhooks.list, total: DB.integ.webhooks.list.length });
  });
  on("POST", /^api\/integration\/webhooks$/, function (m, qs, b) {
    if (!b.name || !b.url) return bad("名称与回调地址不能为空");
    if (String(b.url).indexOf("http") !== 0) return bad("回调地址必须以 http(s):// 开头");
    DB.__hookSeq += 1;
    var rec = { id: DB.__hookSeq, name: b.name, url: b.url, events: b.events || "*",
      status: "启用", secret: "whsec_demo" + Math.random().toString(36).slice(2, 10),
      createdAt: nowStr(), deliveries: 0 };
    DB.integ.webhooks.list.unshift(rec);
    log("创建 Webhook", b.name);
    return ok({ id: rec.id, name: rec.name, events: rec.events, secret: rec.secret,
      notice: "签名密钥只显示一次，请妥善保存" });
  });
  on("DELETE", /^api\/integration\/webhooks\/(\d+)$/, function (m) {
    var id = Number(m[1]);
    DB.integ.webhooks.list = DB.integ.webhooks.list.filter(function (x) { return x.id !== id; });
    DB.integ.deliveries.list = DB.integ.deliveries.list.filter(function (x) { return x.webhookId !== id; });
    log("删除 Webhook", String(id));
    return ok({ id: id, deleted: true });
  });
  on("POST", /^api\/integration\/webhooks\/(\d+)\/test$/, function (m) {
    var id = Number(m[1]), hook = find(DB.integ.webhooks.list, "id", id);
    if (!hook) return bad("Webhook 不存在", 404);
    DB.__dlvSeq += 1;
    var rec = { id: DB.__dlvSeq, webhookId: id, event: "webhook.test", status: "失败",
      attempts: 1, httpCode: 0, error: "离线演示环境无外网，投递记为失败",
      createdAt: nowStr(), deliveredAt: "", nextAt: minusMin(-30) };
    DB.integ.deliveries.list.unshift(rec);
    hook.deliveries = Number(hook.deliveries || 0) + 1;
    log("测试 Webhook", hook.name);
    return ok({ id: rec.id, status: rec.status, event: rec.event });
  });
  on("GET", /^api\/integration\/deliveries$/, function () {
    var list = DB.integ.deliveries.list;
    return ok({ list: list, total: list.length,
      failed: list.filter(function (x) { return x.status === "失败"; }).length });
  });
  on("POST", /^api\/integration\/deliveries\/(\d+)\/retry$/, function (m) {
    var rec = find(DB.integ.deliveries.list, "id", Number(m[1]));
    if (!rec) return bad("投递记录不存在", 404);
    rec.attempts = Number(rec.attempts || 0) + 1;
    rec.nextAt = minusMin(-30);
    log("重投事件", rec.event + " #" + rec.id);
    return ok({ id: rec.id, attempts: rec.attempts, status: rec.status });
  });
  on("GET", /^api\/integration\/mappings$/, function () {
    var list = DB.integ.mappings.list;
    return ok({ list: list, total: list.length });
  });
  on("POST", /^api\/integration\/mappings$/, function (m, qs, b) {
    if (!b.localNo || !b.externalId) return bad("本地单号与外部 ID 不能为空");
    DB.__mapSeq += 1;
    var rec = { id: DB.__mapSeq, objType: b.objType || "work_order", localNo: b.localNo,
      externalId: b.externalId, system: b.system || "ERP", createdAt: nowStr() };
    DB.integ.mappings.list.unshift(rec);
    log("新增外部 ID 映射", b.localNo + " ⇄ " + b.externalId);
    return ok({ id: rec.id, localNo: rec.localNo, externalId: rec.externalId });
  });
  on("DELETE", /^api\/integration\/mappings\/(\d+)$/, function (m) {
    var id = Number(m[1]);
    DB.integ.mappings.list = DB.integ.mappings.list.filter(function (x) { return x.id !== id; });
    log("删除外部 ID 映射", String(id));
    return ok({ id: id, deleted: true });
  });
  on("GET", /^api\/sync\/changes$/, function (m, qs) {
    var since = Number(qs.since || 0), limit = Number(qs.limit || 50);
    var rows = DB.__changes.filter(function (c) { return c.id > since; }).slice(0, limit);
    var cursor = rows.length ? rows[rows.length - 1].id : since;
    return ok({ changes: rows, cursor: cursor,
      hasMore: DB.__changes.some(function (c) { return c.id > cursor; }), count: rows.length });
  });

  /* ------------------------------------------------------------ fetch 拦截 */
  var _fetch = window.fetch;
  window.fetch = function (input, opt) {
    opt = opt || {};
    var url = String(input);
    var mp = url.match(/api\/[^?#]+/);
    if (!mp) return _fetch ? _fetch(input, opt) : Promise.reject(new Error("no fetch"));
    var path = mp[0].replace(/^\//, "");
    var qs = {};
    var q2 = url.split("?")[1] || "";
    q2.split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      qs[decodeURIComponent(i < 0 ? kv : kv.slice(0, i))] =
        decodeURIComponent(i < 0 ? "" : kv.slice(i + 1).replace(/\+/g, " "));
    });
    if (path.indexOf("?") >= 0) path = path.slice(0, path.indexOf("?"));
    var method = String(opt.method || "GET").toUpperCase();
    var body = {};
    if (opt.body) { try { body = JSON.parse(opt.body); } catch (e) { body = {}; } }
    for (var i = 0; i < ROUTES.length; i++) {
      var r = ROUTES[i];
      if (r[0] !== method) continue;
      var m2 = path.match(r[1]);
      if (!m2) continue;
      var out;
      try {
        out = r[2](m2, qs, body);
      } catch (e) {
        out = bad("DEMO 内部错误：" + e.message, 500);
      }
      if (method !== "GET" && out.status < 400) persist();
      return Promise.resolve({
        status: out.status, ok: out.status < 400,
        json: function () { return Promise.resolve(out.body); }
      });
    }
    return Promise.resolve({ status: 404, ok: false,
      json: function () {
        return Promise.resolve({ error: "DEMO 未模拟该接口：" + method + " " + path });
      } });
  };

  /* 导出 CSV：离线环境用 Blob 下载替代 window.open */
  var _open = window.open;
  window.open = function (u, n, f) {
    if (String(u).indexOf("/api/export/orders") === 0) {
      var head = ["工单号", "物料编码", "物料名称", "数量", "报工", "合格", "状态", "产线", "计划完成"];
      var lines = [head.join(",")];
      DB.orders.list.forEach(function (o) {
        lines.push([o.no, o.materialCode, o.materialName, o.qty, o.reportedQty, o.goodQty,
          o.status, o.line, o.planEnd].join(","));
      });
      var blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "feichi_orders.csv";
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 800);
      return null;
    }
    return _open ? _open.apply(window, arguments) : null;
  };

  /* 绕过登录页 */
  try {
    localStorage.setItem("fc_token", "demo-token");
    localStorage.setItem("fc_user", "admin");
    localStorage.setItem("fc_name", "系统管理员");
    localStorage.setItem("fc_role", "admin");
    localStorage.setItem("fc_role_label", "系统管理员");
  } catch (e) { /* 隐私模式忽略 */ }

  /* 初始化派生数据 */
  Object.keys(DB.orderD).forEach(function (no) { refreshOrder(DB.orderD[no]); });
  refreshKpi();
})();
