/* 飞驰 MES · 前端框架、制造驾驶舱、生产看板、设置与日志（原生 JS，零依赖） */
(function (window, document) {
  "use strict";

  var F = window.F = {};
  var TOKEN_KEY = "fc_token";

  F.state = { boot: null, route: "dashboard", params: {}, timer: null };

  /* ---------------------------------------------------------- 基础工具 */
  F.esc = function (s) {
    return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  F.num = function (v, d) {
    var n = Number(v || 0);
    return n.toLocaleString("zh-CN", { minimumFractionDigits: d === undefined ? 2 : d,
      maximumFractionDigits: d === undefined ? 2 : d });
  };
  F.int = function (v) { return F.num(v, 0); };
  F.qty = function (v) {
    var n = Number(v || 0);
    return Number.isInteger(n) ? F.int(n) : F.num(n, 1);
  };
  F.wan = function (v) {
    var n = Number(v || 0);
    return Math.abs(n) >= 10000 ? (n / 10000).toFixed(1) + " 万" : F.num(n, 0);
  };
  F.pct = function (v, d) {
    var n = Number(v || 0) * 100;
    return n.toFixed(d === undefined ? 1 : d) + "%";
  };
  F.hour = function (min) {
    var m = Number(min || 0);
    return m >= 60 ? (m / 60).toFixed(1) + " h" : m.toFixed(0) + " min";
  };
  F.today = function () { return new Date().toISOString().slice(0, 10); };
  F.qs = function (o) {
    return Object.keys(o || {}).filter(function (k) { return o[k] !== undefined && o[k] !== null; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(o[k]); }).join("&");
  };
  F.dash = function (v) { return v === null || v === undefined || v === "" ? "—" : v; };

  var TAGS = {
    // 工单
    "草稿": "gray", "已下达": "blue", "已开工": "gold", "已完工": "green",
    "已入库": "green", "已关闭": "gray", "已取消": "gray",
    // 工序
    "待开工": "gray", "进行中": "gold", "已完成": "green",
    // 设备
    "运行": "green", "待机": "gray", "故障": "red", "保养": "gold", "停机": "red",
    // 质量
    "合格": "green", "不合格": "red", "让步接收": "gold", "退货": "red", "待检": "gray",
    "正常": "green", "异常": "red", "超差": "red",
    "待处置": "gold", "返修": "blue", "报废": "red",
    // 保养
    "待执行": "gold", "执行中": "blue", "逾期": "red", "临期": "gold", "未排程": "gray",
    // 优先级 / 等级
    "紧急": "red", "普通": "gray", "A": "green", "B": "blue", "C": "gold",
    "达标": "green", "预警": "gold", "未达标": "red",
    "充足": "green", "偏低": "gold", "不足": "red", "数据不足": "gray",
    // 通用
    "启用": "green", "停用": "gray", "吊销": "red", "禁用": "gray",
    "成功": "green", "失败": "red", "待投递": "gold",
    "首件": "blue", "巡检": "gold", "完工检": "green", "来料检": "gray",
    "待响应": "red", "已关闭": "gray"
  };
  F.TAGS = TAGS;
  F.tag = function (s, cls) {
    return '<span class="tag ' + (cls || TAGS[s] || "gray") + '">' + F.esc(s) + "</span>";
  };
  F.prio = function (p) { return F.tag(p, p === "紧急" ? "red" : "gray"); };

  /* ---------------------------------------------------------- 请求 */
  F.raw = function (method, path, body, headers) {
    var h = { "Content-Type": "application/json" };
    var tk = localStorage.getItem(TOKEN_KEY);
    if (tk) { h.Authorization = "Bearer " + tk; h["X-Fc-Token"] = tk; }
    Object.keys(headers || {}).forEach(function (k) { h[k] = headers[k]; });
    var opt = { method: method, headers: h, credentials: "same-origin" };
    if (body !== undefined && body !== null) opt.body = JSON.stringify(body);
    return fetch(path.replace(/^\//, ""), opt).then(function (r) {
      return r.json().catch(function () { return { error: "响应解析失败" }; })
        .then(function (j) { return { status: r.status, body: j }; });
    });
  };

  F.api = function (method, path, body) {
    return F.raw(method, path, body).then(function (x) {
      if (x.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        location.href = "./login.html";
        return new Promise(function () {});
      }
      if (x.status >= 400) {
        var e = new Error((x.body && x.body.error) || ("请求失败 " + x.status));
        e.status = x.status;
        e.body = x.body;
        throw e;
      }
      return x.body.data;
    });
  };

  F.toast = function (msg, kind) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    el.textContent = msg;
    F._toastUntil = Date.now() + 6000;
    el.style.color = kind === "err" ? "#ffb3a7" : (kind === "ok" ? "#9ee6b8" : "");
    clearTimeout(F._t);
    F._t = setTimeout(function () { el.style.color = ""; }, 8000);
  };
  F.setStatus = function (t) {
    var el = document.getElementById("statusMsg");
    if (!el) return;
    if (F._toastUntil && Date.now() < F._toastUntil) return;
    el.textContent = t;
  };
  F.setSide = function (html) { var el = document.getElementById("side"); if (el) el.innerHTML = html; };

  F.can = function (perm) {
    var b = F.state.boot;
    return !!(b && b.user && (b.user.perms || []).indexOf(perm) >= 0);
  };
  F.isAdmin = function () { return F.state.boot && F.state.boot.user.role === "admin"; };
  F.me = function () { return (F.state.boot && F.state.boot.user) || {}; };

  /* ---------------------------------------------------------- 路由 */
  function parseHash() {
    var h = (location.hash || "#dashboard").replace(/^#\/?/, "");
    var i = h.indexOf("?");
    var route = i < 0 ? h : h.slice(0, i);
    var qs = i < 0 ? "" : h.slice(i + 1);
    var params = {};
    qs.split("&").forEach(function (kv) {
      if (!kv) return;
      var j = kv.indexOf("=");
      params[decodeURIComponent(j < 0 ? kv : kv.slice(0, j))] =
        decodeURIComponent(j < 0 ? "" : kv.slice(j + 1));
    });
    return { route: route || "dashboard", params: params };
  }

  F.go = function (route, params) {
    location.hash = "#" + route + (params && Object.keys(params).length ? "?" + F.qs(params) : "");
  };

  var PAGES = {};
  F.register = function (name, fn) { PAGES[name] = fn; };

  function render() {
    var r = parseHash();
    F.state.route = r.route;
    F.state.params = r.params;
    if (F.state.timer) { clearInterval(F.state.timer); F.state.timer = null; }
    var fn = PAGES[r.route] || PAGES.dashboard;
    var view = document.getElementById("view");
    view.innerHTML = "";
    paintNav(r.route);
    try {
      fn(r.params);
    } catch (e) {
      view.innerHTML = '<div class="panel"><div class="panel-body">页面渲染失败：' +
        F.esc(e.message) + "</div></div>";
    }
  }

  /* ---------------------------------------------------------- 导航 */
  var TREE = [
    { grp: "生产运营", items: [["dashboard", "制造驾驶舱"], ["board", "生产看板"],
      ["schedule", "排产计划"], ["orders", "生产工单"]] },
    { grp: "主数据", items: [["materials", "物料与 BOM"]] },
    { grp: "质量与追溯", items: [["quality", "质量检验"], ["trace", "批次追溯"]] },
    { grp: "设备管理", items: [["equipment", "设备台账"], ["maint", "保养点检"]] },
    { grp: "库存与报表", items: [["stock", "库存台账"], ["reports", "报表分析"]] },
    { grp: "系统", items: [["integration", "集成中心"], ["settings", "基础设置"],
      ["logs", "操作日志"]] }
  ];

  var MENU = TREE.map(function (g) { return [g.grp, g.items.map(function (i) { return i[0]; })]; });

  var TITLE = {
    dashboard: "制造驾驶舱", board: "生产看板", schedule: "排产计划", orders: "生产工单",
    materials: "物料与 BOM", quality: "质量检验", trace: "批次追溯",
    equipment: "设备台账", maint: "保养点检", stock: "库存台账", reports: "报表分析",
    integration: "集成中心", settings: "基础设置", logs: "操作日志"
  };
  F.TITLE = TITLE;

  function paintNav(route) {
    var tree = document.getElementById("tree");
    var boot = F.state.boot || {};
    var kpi = boot.kpi || {};
    var badgeFor = { orders: kpi.wip || 0, quality: kpi.pendingInsp || 0,
      equipment: kpi.equipAbnormal || 0, maint: kpi.maintDue || 0,
      dashboard: (boot.todo || []).length };
    tree.innerHTML = TREE.map(function (g) {
      return '<div class="grp">' + F.esc(g.grp) + "</div>" + g.items.map(function (it) {
        var n = badgeFor[it[0]] || 0;
        var badge = n ? '<b class="nav-badge">' + n + "</b>" : "";
        return '<a href="#' + it[0] + '" class="' + (it[0] === route ? "on" : "") + '">' +
          F.esc(it[1]) + badge + "</a>";
      }).join("");
    }).join("");

    var mb = document.getElementById("menubar");
    var groupOf = {};
    MENU.forEach(function (m) { m[1].forEach(function (r) { groupOf[r] = m[0]; }); });
    mb.innerHTML = MENU.map(function (m) {
      return '<button class="' + (groupOf[route] === m[0] ? "on" : "") + '" data-group="' +
        F.esc(m[0]) + '">' + F.esc(m[0]) + "</button>";
    }).join("");
    mb.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        var g = b.getAttribute("data-group");
        var target = MENU.filter(function (m) { return m[0] === g; })[0];
        if (target) F.go(target[1][0]);
      });
    });

    var ts = document.getElementById("tabstrip");
    ts.innerHTML = '<span class="tab">' + F.esc(TITLE[route] || route) + "</span>" +
      '<span class="muted small">飞驰 MES / ' + F.esc(TITLE[route] || route) + "</span>";
  }

  /* ---------------------------------------------------------- 通用渲染 */
  F.table = function (headers, rows, opts) {
    opts = opts || {};
    var th = headers.map(function (h) {
      return "<th class='" + (h.num ? "num" : "") + "'" +
        (h.width ? " style='width:" + h.width + "'" : "") + ">" + F.esc(h.label) + "</th>";
    }).join("");
    var body = rows && rows.length ? rows.map(function (r, i) {
      return '<tr class="' + (opts.click ? "clickable" : "") + '"' +
        (opts.click ? " data-key='" + F.esc(opts.click(r, i)) + "'" : "") + ">" +
        headers.map(function (h) {
          var v = h.render ? h.render(r, i) : F.esc(r[h.key]);
          return "<td class='" + (h.num ? "num" : "") + "'>" + v + "</td>";
        }).join("") + "</tr>";
    }).join("") : '<tr class="empty-row"><td colspan="' + headers.length + '">' +
      F.esc(opts.empty || "暂无数据") + "</td></tr>";
    return "<table class='grid-table'><thead><tr>" + th + "</tr></thead><tbody>" + body + "</tbody></table>";
  };

  F.bindRows = function (root, fn) {
    (root || document).querySelectorAll("#view tbody tr[data-key]").forEach(function (tr) {
      tr.addEventListener("click", function () { fn(tr.getAttribute("data-key"), tr); });
    });
  };

  F.dialog = function (title, body, foot) {
    var mask = document.getElementById("mask");
    var dlg = document.getElementById("dialog");
    dlg.innerHTML = '<div class="dh">' + F.esc(title) +
      '<span class="x" data-close="1">×</span></div><div class="db">' + body + "</div>" +
      (foot ? '<div class="df">' + foot + "</div>" : "");
    mask.className = "mask on";
    dlg.querySelector("[data-close]").addEventListener("click", F.closeDialog);
    return dlg;
  };
  F.closeDialog = function () { document.getElementById("mask").className = "mask"; };
  F.dialogOpen = function () {
    return document.getElementById("mask").className.indexOf("on") >= 0;
  };

  F.chips = function (items, active, attr) {
    return '<div class="chips">' + items.map(function (it) {
      return '<button class="chip' + (it === active ? " on" : "") + '" ' + (attr || "data-st") +
        '="' + F.esc(it) + '">' + F.esc(it) + "</button>";
    }).join("") + "</div>";
  };

  F.lineChart = function (series, opts) {
    opts = opts || {};
    var W = opts.width || 640, H = opts.height || 190, P = 34;
    var labels = opts.labels || [];
    var all = [];
    series.forEach(function (s) { all = all.concat(s.data); });
    var max = Math.max.apply(null, all.concat([1]));
    var min = opts.zero === false ? Math.min.apply(null, all) : 0;
    var span = max - min || 1;
    var colors = opts.colors || ["#1f7a8c", "#c8963e", "#7a5ea8"];
    var w = (W - P * 2) / Math.max(1, labels.length - 1);
    var grid = [0, 0.25, 0.5, 0.75, 1].map(function (t) {
      var y = P + (H - P * 1.6) * t;
      var val = max - span * t;
      return '<line x1="' + P + '" y1="' + y + '" x2="' + (W - P) + '" y2="' + y +
        '" stroke="#eef2f5"/><text x="6" y="' + (y + 4) + '" font-size="10" fill="#8b9aa6">' +
        (val >= 10000 ? (val / 10000).toFixed(1) + "万" : Math.round(val)) + "</text>";
    }).join("");
    var paths = series.map(function (s, si) {
      var d = s.data.map(function (v, i) {
        var x = P + w * i;
        var y = P + (H - P * 1.6) * (1 - (v - min) / span);
        return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      }).join(" ");
      return '<path d="' + d + '" fill="none" stroke="' + colors[si % colors.length] +
        '" stroke-width="2"/>' + s.data.map(function (v, i) {
          var x = P + w * i;
          var y = P + (H - P * 1.6) * (1 - (v - min) / span);
          return '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="2.6" fill="' +
            colors[si % colors.length] + '"/>';
        }).join("");
    }).join("");
    var xlabels = labels.map(function (t, i) {
      return '<text x="' + (P + w * i) + '" y="' + (H - 6) +
        '" font-size="10" fill="#8b9aa6" text-anchor="middle">' + F.esc(t) + "</text>";
    }).join("");
    return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">' +
      grid + paths + xlabels + "</svg>";
  };

  F.barChart = function (items, opts) {
    opts = opts || {};
    var W = opts.width || 640, H = opts.height || 180, P = 34;
    var max = Math.max.apply(null, items.map(function (i) { return i.value; }).concat([1]));
    var gap = (W - P * 2) / Math.max(1, items.length);
    var bw = gap * 0.56;
    return '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" height="' + H + '">' +
      items.map(function (it, i) {
        var h = (H - P * 1.8) * (it.value / max);
        var x = P + gap * i + (gap - bw) / 2;
        var y = H - P - h;
        return '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
          '" height="' + Math.max(1, h).toFixed(1) + '" rx="2" fill="' + (it.color || "#2b9eb3") + '"/>' +
          '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 5) +
          '" font-size="10" fill="#5d6f7c" text-anchor="middle">' + F.esc(it.label2 || "") +
          "</text>" + '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 8) +
          '" font-size="10" fill="#8b9aa6" text-anchor="middle">' + F.esc(it.label) + "</text>";
      }).join("") + "</svg>";
  };

  /* 状态分布条：按工单数量 */
  F.stageBars = function (stages) {
    var max = Math.max.apply(null, stages.map(function (s) { return s.count; }).concat([1]));
    return '<div class="funnel">' + stages.map(function (s) {
      var w = Math.max(5, Math.round(s.count / max * 100));
      var color = TAGS[s.status] === "gold" ? "#c8963e" : (TAGS[s.status] === "green" ? "#2f8f5b" :
        (TAGS[s.status] === "red" ? "#b4463a" : "#2b7fa8"));
      return '<div class="fn-row"><div class="fn-name">' + F.esc(s.status) + "</div>" +
        '<div class="fn-bar"><i style="width:' + w + "%;background:" + color + '"></i></div>' +
        '<div class="fn-val">' + s.count + ' <span class="muted small">单</span></div>' +
        '<div class="fn-conv"></div></div>';
    }).join("") + "</div>";
  };

  /* OEE 环形 */
  F.ring = function (v, opts) {
    opts = opts || {};
    var p = Math.max(0, Math.min(1, Number(v || 0)));
    var color = p >= 0.85 ? "#2f8f5b" : (p >= 0.72 ? "#c8963e" : "#b4463a");
    var deg = (p * 360).toFixed(1);
    return '<div class="ring" style="background:conic-gradient(' + color + " 0deg " + deg +
      "deg,#eef2f5 " + deg + 'deg 360deg)"><div class="ring-in"><b>' + F.pct(p, 1) +
      "</b><span>" + F.esc(opts.label || "OEE") + "</span></div></div>";
  };

  F.empty = function (text) {
    return '<div class="empty-hint">' + F.esc(text || "暂无数据") + "</div>";
  };

  F.kv = function (label, value) {
    return '<div class="side-kv"><span>' + F.esc(label) + "</span><b>" + value + "</b></div>";
  };

  F.progress = function (v, cls) {
    var p = Math.max(0, Math.min(1, Number(v || 0)));
    return '<div class="pbar ' + (cls || "") + '"><i style="width:' + (p * 100).toFixed(1) + '%"></i></div>';
  };

  /* ---------------------------------------------------------- 驾驶舱 */
  F.register("dashboard", function () {
    var b = F.state.boot;
    if (!b) return;
    var k = b.kpi;
    var html = '<div class="kpi-grid six">' +
      '<div class="kpi"><div class="k-label">在制工单</div><div class="k-value">' + k.wip +
      '</div><div class="k-sub">今日产出 ' + F.qty(k.todayOutput) + " 件</div></div>" +
      '<div class="kpi green"><div class="k-label">本月产出</div><div class="k-value">' +
      F.wan(k.monthOutput) + '</div><div class="k-sub">计划 ' + F.wan(k.monthPlan) + " · 达成 " +
      F.pct(k.monthPlan ? k.monthOutput / k.monthPlan : 0, 0) + "</div></div>" +
      '<div class="kpi"><div class="k-label">综合 OEE</div><div class="k-value">' + F.pct(k.oee, 1) +
      '</div><div class="k-sub">目标 85% · ' + F.tag(k.oeeLevel) + "</div></div>" +
      '<div class="kpi green"><div class="k-label">一次良率</div><div class="k-value">' +
      F.pct(k.yieldRate, 2) + '</div><div class="k-sub">不良待处置 ' + k.abnormalDefects + " 条</div></div>" +
      '<div class="kpi red"><div class="k-label">设备异常</div><div class="k-value">' + k.equipAbnormal +
      '</div><div class="k-sub">保养临期/逾期 ' + k.maintDue + " 台</div></div>" +
      '<div class="kpi gold"><div class="k-label">齐套 / 待检</div><div class="k-value">' +
      k.kitWarn + " / " + k.pendingInsp +
      '</div><div class="k-sub">逾期工单 ' + k.overdue + " 单</div></div></div>";

    html += '<div class="panel"><div class="panel-title">近 14 天产量与计划' +
      '<span class="panel-actions small muted">末工序产出（件）</span></div><div class="panel-body">' +
      F.lineChart([
        { name: "产出", data: (b.trend || []).map(function (t) { return t.output; }) },
        { name: "计划", data: (b.trend || []).map(function (t) { return t.plan; }) },
        { name: "不良", data: (b.trend || []).map(function (t) { return t.ng; }) }
      ], { labels: (b.trend || []).map(function (t) { return t.day; }),
        colors: ["#1f7a8c", "#c8963e", "#b4463a"] }) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">工单状态分布' +
      '<span class="panel-actions small muted">共 ' + (b.statusDist || []).reduce(function (a, x) {
        return a + x.count;
      }, 0) + " 单</span></div><div class=\"panel-body\">" +
      F.stageBars((b.statusDist || []).slice().sort(function (x, y) { return y.count - x.count; })) +
      "</div></div>";

    html += '<div class="panel"><div class="panel-title">产线负荷与产出' +
      '<span class="panel-actions"><a class="btn sm" href="#board">看板</a></span></div>' +
      '<div class="panel-body flush">' +
      F.table([
        { label: "产线", render: function (r) { return F.esc(r.name) +
          '<div class="muted small mono">' + F.esc(r.code) + "</div>"; } },
        { label: "在制", num: true, render: function (r) { return r.wip + " 单"; } },
        { label: "标准工时", num: true, render: function (r) { return F.hour(r.stdMin); } },
        { label: "负荷", render: function (r) {
          return '<div style="display:flex;align-items:center;gap:8px">' + F.progress(r.load) +
            '<span class="small">' + F.pct(r.load, 0) + "</span></div>";
        } },
        { label: "状态", render: function (r) { return F.tag(r.status); } }
      ], b.lines || []) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">待办与预警' +
      '<span class="panel-actions"><a class="btn sm" href="#reports">看报表</a></span></div>' +
      '<div class="panel-body flush">' +
      F.table([
        { label: "类别", render: function (r) { return F.tag(r.type, "gray"); } },
        { label: "对象", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "事项", render: function (r) { return F.esc(r.title); } },
        { label: "级别", render: function (r) {
          return F.tag(r.level === "high" ? "高" : "中", r.level === "high" ? "red" : "gold");
        } },
        { label: "", render: function (r) {
          return '<a class="btn sm" href="#' + F.esc(r.page) + '">处理</a>';
        } }
      ], b.todo || [], { empty: "没有待办，节奏不错" }) + "</div></div>";

    html += '<div class="panel"><div class="panel-title">安灯呼叫' +
      '<span class="panel-actions small muted">未关闭 ' +
      (b.andon || []).filter(function (a) { return a.status !== "已关闭"; }).length + " 条</span></div>" +
      '<div class="panel-body flush">' +
      F.table([
        { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "产线 / 工位", render: function (r) { return F.esc(r.line) +
          '<div class="muted small">' + F.esc(r.station) + "</div>"; } },
        { label: "类型", render: function (r) { return F.tag(r.type, "blue"); } },
        { label: "级别", render: function (r) { return F.tag(r.level, r.level === "紧急" ? "red" : "gold"); } },
        { label: "持续", num: true, render: function (r) { return r.minutes + " 分"; } },
        { label: "状态", render: function (r) { return F.tag(r.status); } }
      ], b.andon || [], { empty: "产线平稳，无呼叫" }) + "</div></div>";

    document.getElementById("view").innerHTML = html;

    var eqAb = (b.alarms || []).filter(function (a) { return a.level === "high"; });
    F.setSide(
      '<div class="side-block"><div class="hd">今日快照</div><div class="bd">' +
      F.kv("今日产出", '<span class="up">' + F.qty(k.todayOutput) + "</span>") +
      F.kv("在制工单", k.wip + " 单") +
      F.kv("综合 OEE", F.pct(k.oee, 1)) +
      F.kv("一次良率", F.pct(k.yieldRate, 2)) +
      F.kv("设备异常", k.equipAbnormal + " 台") +
      "</div></div>" +
      '<div class="side-block"><div class="hd">实时预警</div><div class="bd">' +
      (eqAb.length ? eqAb.map(function (a) {
        return '<div class="side-kv"><span>' + F.esc(a.text) + "</span><b>" + F.tag("高", "red") + "</b></div>";
      }).join("") : '<div class="muted small">无高优先级预警</div>') + "</div></div>" +
      '<div class="side-block"><div class="hd">业务规则</div><div class="bd small muted" style="line-height:1.9">' +
      (b.rules || []).map(function (r) {
        return (r.enabled ? "● " : "○ ") + F.esc(r.name) + "：" + r.value + F.esc(r.unit || "") +
          (r.enabled ? "" : "（停用）");
      }).join("<br>") + "</div></div>");
    F.setStatus("制造驾驶舱 · 数据截至 " + new Date().toLocaleTimeString("zh-CN"));
  });

  /* ---------------------------------------------------------- 生产看板 */
  F.register("board", function () {
    function draw(d) {
      var html = '<div class="panel"><div class="panel-title">产线实时状态' +
        '<span class="panel-actions small muted">刷新于 ' + F.esc(d.time) + "</span></div>" +
        '<div class="panel-body"><div class="board-grid">';
      (d.lines || []).forEach(function (ln) {
        html += '<div class="board-card"><div class="bc-hd"><b>' + F.esc(ln.name) + "</b>" +
          '<span class="muted small mono">' + F.esc(ln.code) + "</span>" +
          '<span class="spacer"></span>' + F.tag(ln.status) + "</div>" +
          '<div class="bc-meta small muted">设备 ' + ln.equipRun + "/" + ln.equipTotal + " 运行" +
          (ln.equipAbnormal.length ? " · 异常：" + F.esc(ln.equipAbnormal.join("、")) : "") + "</div>";
        if (!ln.orders.length) {
          html += '<div class="muted small" style="padding:8px 0">暂无在制工单</div>';
        }
        ln.orders.forEach(function (o) {
          html += '<div class="bc-order"><div class="bo-line"><span class="mono small">' +
            F.esc(o.no.slice(-8)) + '</span><span class="small">' + F.esc(o.materialName) + "</span>" +
            '<span class="spacer"></span>' + F.tag(o.status) + "</div>" +
            '<div class="bo-line small muted">当前工序：' + F.esc(o.currentOp) +
            " · 产出 " + F.qty(o.goodQty) + "/" + F.qty(o.qty) + "</div>" +
            F.progress(o.progress) + "</div>";
        });
        html += "</div>";
      });
      html += "</div></div></div>";

      html += '<div class="panel"><div class="panel-title">安灯（Andon）' +
        '<span class="panel-actions"><button class="btn sm" id="adNew">发起呼叫</button></span></div>' +
        '<div class="panel-body flush">' +
        F.table([
          { label: "编号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "产线", key: "line" }, { label: "工位", key: "station" },
          { label: "类型", render: function (r) { return F.tag(r.type, "blue"); } },
          { label: "级别", render: function (r) { return F.tag(r.level, r.level === "紧急" ? "red" : "gold"); } },
          { label: "持续", num: true, render: function (r) { return r.minutes + " 分"; } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "", render: function (r) {
            return r.status === "已关闭" ? "" : '<button class="btn sm" data-close-ad="' + r.id + '">关闭</button>';
          } }
        ], d.andon || [], { empty: "无呼叫" }) + "</div></div>";
      document.getElementById("view").innerHTML = html;

      document.querySelectorAll("[data-close-ad]").forEach(function (b) {
        b.addEventListener("click", function () {
          F.api("POST", "/api/andon/" + b.getAttribute("data-close-ad") + "/close",
            { remark: "班组处理完成" }).then(function () {
            F.toast("呼叫已关闭", "ok");
            load();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
      var nb = document.getElementById("adNew");
      if (nb) nb.addEventListener("click", function () {
        F.dialog("发起安灯呼叫",
          '<div class="form-grid">' +
          '<label>产线<select id="adLine">' + (d.lines || []).map(function (l) {
            return '<option value="' + F.esc(l.code) + '">' + F.esc(l.name) + "</option>";
          }).join("") + "</select></label>" +
          '<label>工位<input id="adStation" placeholder="如 ST-3012"></label>' +
          '<label>类型<select id="adType"><option>设备</option><option>质量</option>' +
          "<option>物料</option><option>人员</option></select></label>" +
          '<label>级别<select id="adLevel"><option>一般</option><option>紧急</option></select></label>' +
          '<label class="full">说明<input id="adRemark" placeholder="如 拧紧机扭矩报警"></label></div>',
          '<button class="btn" id="adOk">提交</button>');
        document.getElementById("adOk").addEventListener("click", function () {
          F.api("POST", "/api/andon", {
            line: document.getElementById("adLine").value,
            station: document.getElementById("adStation").value,
            type: document.getElementById("adType").value,
            level: document.getElementById("adLevel").value,
            remark: document.getElementById("adRemark").value
          }).then(function (x) {
            F.closeDialog();
            F.toast("已发起呼叫 " + x.no, "ok");
            load();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
      F.setSide('<div class="side-block"><div class="hd">看板说明</div><div class="bd small muted" ' +
        'style="line-height:1.9">按产线展示在制工单、当前工序与产出进度；设备异常与安灯呼叫实时提示。' +
        '页面每 30 秒自动刷新，也可点右上角「刷新」。</div></div>');
    }

    function load() {
      F.api("GET", "/api/board").then(function (d) {
        draw(d);
        F.setStatus("生产看板 · " + d.lines.length + " 条产线");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    var view = document.getElementById("view");
    view.innerHTML = '<div class="panel"><div class="panel-title">生产看板' +
      '<span class="panel-actions"><button class="btn sm" id="bdRefresh">刷新</button></span></div>' +
      '<div class="panel-body">加载中…</div></div>';
    document.getElementById("bdRefresh").addEventListener("click", load);
    load();
    F.state.timer = setInterval(function () {
      if (!F.dialogOpen() && F.state.route === "board") load();
    }, 30000);
  });

  /* ---------------------------------------------------------- 设置 */
  F.register("settings", function () {
    F.api("GET", "/api/settings").then(function (d) {
      var admin = F.isAdmin();
      var html = '<div class="panel"><div class="panel-title">业务规则' +
        (admin ? '<span class="panel-actions small muted">管理员可启停与调整阈值</span>' : "") +
        "</div><div class='panel-body flush'>" +
        F.table([
          { label: "规则", render: function (r) { return F.esc(r.name) + ' <span class="muted small mono">' +
            F.esc(r.code) + "</span>"; } },
          { label: "分类", render: function (r) { return F.tag(r.category, "gray"); } },
          { label: "阈值", num: true, render: function (r) {
            if (!admin) return r.value + F.esc(r.unit || "");
            return '<input type="number" step="any" data-rule-val="' + F.esc(r.code) +
              '" value="' + r.value + '" style="width:90px"> <span class="small muted">' +
              F.esc(r.unit || "") + "</span>";
          } },
          { label: "说明", render: function (r) { return '<span class="small muted">' + F.esc(r.remark) + "</span>"; } },
          { label: "状态", render: function (r) {
            if (!admin) return r.enabled ? F.tag("启用") : F.tag("停用");
            return '<label class="small"><input type="checkbox" data-rule="' + F.esc(r.code) + '"' +
              (r.enabled ? " checked" : "") + "> 启用</label>";
          } }
        ], d.rules || []) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">车间 · 产线 · 班组</div><div class="panel-body">' +
        '<div class="small muted" style="margin-bottom:8px">车间</div>' +
        F.table([{ label: "编码", key: "code" }, { label: "名称", key: "name" },
          { label: "负责人", key: "manager" },
          { label: "可用工时", num: true, render: function (r) { return F.hour(r.capacityMin); } },
          { label: "状态", render: function (r) { return F.tag(r.status); } }], d.workshops || []) +
        '<div class="small muted" style="margin:12px 0 8px">产线</div>' +
        F.table([{ label: "编码", key: "code" }, { label: "名称", key: "name" },
          { label: "车间", key: "workshop" }, { label: "线长", key: "leader" },
          { label: "节拍", num: true, render: function (r) { return r.taktSec + " 秒"; } },
          { label: "状态", render: function (r) { return F.tag(r.status); } }], d.lines || []) +
        '<div class="small muted" style="margin:12px 0 8px">班组</div>' +
        F.table([{ label: "编码", key: "code" }, { label: "名称", key: "name" },
          { label: "车间", key: "workshop" }, { label: "班组长", key: "leader" },
          { label: "班次", render: function (r) { return F.tag(r.shift, "blue"); } },
          { label: "成员", render: function (r) { return '<span class="small muted">' + F.esc(r.members) + "</span>"; } }],
          d.teams || []) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">用户与角色</div><div class="panel-body flush">' +
        F.table([{ label: "账号", key: "username" }, { label: "姓名", key: "name" },
          { label: "角色", render: function (r) { return F.tag(r.roleLabel, "blue"); } },
          { label: "部门", key: "dept" }, { label: "状态", render: function (r) { return F.tag(r.status); } }],
          d.users || []) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">角色权限矩阵</div><div class="panel-body flush">' +
        F.table([{ label: "角色", render: function (r) { return F.esc(r.label) +
            ' <span class="muted small mono">' + F.esc(r.role) + "</span>"; } },
          { label: "权限位", render: function (r) {
            return r.perms.map(function (p) { return F.tag(p, "gray"); }).join(" ");
          } }], d.roles || []) + "</div></div>";

      document.getElementById("view").innerHTML = html;
      document.querySelectorAll("[data-rule]").forEach(function (cb) {
        cb.addEventListener("change", function () {
          var code = cb.getAttribute("data-rule");
          F.api("PUT", "/api/rules/" + encodeURIComponent(code), { enabled: cb.checked })
            .then(function () { F.toast("规则已" + (cb.checked ? "启用" : "停用") + "：" + code, "ok"); })
            .catch(function (e) { cb.checked = !cb.checked; F.toast(e.message, "err"); });
        });
      });
      document.querySelectorAll("[data-rule-val]").forEach(function (inp) {
        inp.addEventListener("change", function () {
          var code = inp.getAttribute("data-rule-val");
          F.api("PUT", "/api/rules/" + encodeURIComponent(code), { value: Number(inp.value) })
            .then(function (x) { F.toast("阈值已更新：" + code + " = " + x.value, "ok"); F.reload(); })
            .catch(function (e) { F.toast(e.message, "err"); });
        });
      });
      F.setStatus("基础设置 · " + (d.rules || []).length + " 条业务规则");
      F.setSide('<div class="side-block"><div class="hd">当前登录</div><div class="bd">' +
        F.kv("账号", F.esc(F.me().username || "")) +
        F.kv("姓名", F.esc(F.me().displayName || "")) +
        F.kv("角色", F.esc(F.me().roleLabel || "")) +
        "</div></div>" +
        '<div class="side-block"><div class="hd">口径提示</div><div class="bd small muted" ' +
        'style="line-height:1.9">规则调整立即生效并写入操作日志：OEE 目标影响看板判定，' +
        "首件必检影响报工准入，缺料禁止下达影响工单下达闸口，超产容差影响报工上限。</div></div>");
    }).catch(function (e) { F.toast(e.message, "err"); });
  });

  /* ---------------------------------------------------------- 日志 */
  F.register("logs", function () {
    F.api("GET", "/api/logs?limit=200").then(function (d) {
      document.getElementById("view").innerHTML =
        '<div class="panel"><div class="panel-title">操作日志' +
        '<span class="panel-actions small muted">最近 ' + d.total + " 条</span></div>" +
        '<div class="panel-body flush">' +
        F.table([
          { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.createdAt) + "</span>"; } },
          { label: "操作员", key: "username" },
          { label: "动作", render: function (r) { return F.tag(r.action, "blue"); } },
          { label: "详情", render: function (r) { return '<span class="small">' + F.esc(r.detail || "—") + "</span>"; } }
        ], d.list, { empty: "暂无日志" }) + "</div></div>";
      F.setStatus("操作日志 · " + d.total + " 条");
    }).catch(function (e) { F.toast(e.message, "err"); });
  });

  /* ---------------------------------------------------------- 启动 */
  function boot() {
    if (!localStorage.getItem(TOKEN_KEY)) {
      location.href = "./login.html";
      return;
    }
    var lg = document.getElementById("btnLogout");
    if (lg) {
      lg.addEventListener("click", function () {
        F.api("POST", "/api/auth/logout", {}).catch(function () {}).then(function () {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem("fc_user");
          location.href = "./login.html";
        });
      });
    }
    var foot = document.getElementById("opFoot");
    if (foot) {
      foot.textContent = "操作员：" + (localStorage.getItem("fc_name") || "") +
        "（" + (localStorage.getItem("fc_role_label") || "") + "）";
    }
    F.reload().then(function () {
      window.addEventListener("hashchange", render);
      if (!location.hash) location.hash = "dashboard";
      render();
      F.setStatus("系统就绪 · 演示数据为确定性生成");
    }).catch(function (e) {
      F.toast("初始化失败：" + e.message, "err");
    });
  }

  F.reload = function () {
    return F.api("GET", "/api/bootstrap").then(function (d) {
      F.state.boot = d;
      var a = document.getElementById("pipeLabel");
      if (a) a.textContent = "在制工单：" + d.kpi.wip;
      var r = document.getElementById("wonLabel");
      if (r) r.textContent = "今日产出：" + F.qty(d.kpi.todayOutput);
      localStorage.setItem("fc_role", d.user.role);
      localStorage.setItem("fc_name", d.user.displayName);
      localStorage.setItem("fc_role_label", d.user.roleLabel);
      localStorage.setItem("fc_user", d.user.username);
      return d;
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})(window, document);
