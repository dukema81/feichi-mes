/* 飞驰 MES · 排产计划与生产工单（工单状态机 / 报工 / 入库） */
(function (window, document) {
  "use strict";
  var F = window.F;
  var STATUS = ["全部", "草稿", "已下达", "已开工", "已完工", "已入库", "已关闭", "已取消"];

  function daysBetween(a, b) {
    if (!a || !b) return 0;
    return Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 86400000);
  }
  function addDays(d, n) {
    var x = new Date(d + "T00:00:00");
    x.setDate(x.getDate() + n);
    return x.toISOString().slice(0, 10);
  }

  /* ---------------------------------------------------------- 排产计划 */
  F.register("schedule", function () {
    F.api("GET", "/api/orders?status=全部").then(function (d) {
      var today = F.today();
      var start = addDays(today, -3);
      var days = 17;
      var list = (d.list || []).filter(function (w) {
        return w.status !== "已取消" && w.status !== "已关闭" && w.planEnd >= start &&
          w.planStart <= addDays(start, days - 1);
      });
      var head = '<tr><th style="width:120px">产线</th>';
      for (var i = 0; i < days; i++) {
        var day = addDays(start, i);
        head += '<th class="num" style="width:' + (100 / days).toFixed(2) + '%">' +
          (i % 2 === 0 ? day.slice(5) : "&nbsp;") + "</th>";
      }
      head += "</tr>";
      var rowsHtml = "";
      var lines = (F.state.boot.lines || []);
      lines.forEach(function (ln) {
        rowsHtml += '<tr><td><b>' + F.esc(ln.name) + '</b><div class="muted small mono">' +
          F.esc(ln.code) + "</div></td>";
        var cells = [];
        for (var i = 0; i < days; i++) cells.push([]);
        list.filter(function (w) { return w.line === ln.code; }).forEach(function (w) {
          var s = Math.max(0, daysBetween(start, w.planStart));
          var e = Math.min(days - 1, daysBetween(start, w.planEnd));
          if (e < 0 || s > days - 1) return;
          if (e < s) e = s;
          cells[s].push({ w: w, span: e - s + 1 });
        });
        for (var i2 = 0; i2 < days; i2++) {
          var items = cells[i2];
          if (!items.length) {
            rowsHtml += '<td class="' + (addDays(start, i2) === today ? "today" : "") + '"></td>';
            continue;
          }
          var cell = "";
          items.forEach(function (it) {
            var cls = it.w.status === "已开工" ? "g-run" : (it.w.status === "已下达" ? "g-plan" :
              (it.w.status === "已完工" ? "g-done" : "g-draft"));
            cell += '<div class="gantt-bar ' + cls + '" title="' + F.esc(it.w.no + " " +
              it.w.materialName + " ×" + it.w.qty + " · " + it.w.status) +
              '" data-wo="' + F.esc(it.w.no) + '">' + F.esc(it.w.materialName.slice(0, 6)) +
              " " + F.qty(it.w.qty) + "</div>";
          });
          rowsHtml += '<td class="' + (addDays(start, i2) === today ? "today" : "") + '">' + cell + "</td>";
        }
        rowsHtml += "</tr>";
      });

      var html = '<div class="panel"><div class="panel-title">排产甘特（未来两周）' +
        '<span class="panel-actions small muted">共 ' + list.length + " 个未结工单</span></div>" +
        '<div class="panel-body"><div style="overflow-x:auto"><table class="gantt-table">' +
        head + rowsHtml + "</table></div>" +
        '<div class="small muted" style="margin-top:8px">' +
        '<span class="dot" style="background:#8fb3c4"></span>草稿 ' +
        '<span class="dot" style="background:#2b7fa8"></span>已下达 ' +
        '<span class="dot" style="background:#c8963e"></span>已开工 ' +
        '<span class="dot" style="background:#2f8f5b"></span>已完工　（点击色块打开工单）</div></div></div>';

      var byLine = {};
      list.forEach(function (w) {
        byLine[w.line] = byLine[w.line] || { qty: 0, std: 0, count: 0 };
        byLine[w.line].qty += Number(w.qty || 0);
        byLine[w.line].std += Number(w.stdMin || 0);
        byLine[w.line].count += 1;
      });
      html += '<div class="panel"><div class="panel-title">产能负荷' +
        '<span class="panel-actions small muted">按标准工时 / 可用工时</span></div>' +
        '<div class="panel-body">' +
        F.barChart(lines.map(function (l) {
          var v = byLine[l.code] || { std: 0 };
          return { label: l.code.replace("LN-", ""), value: v.std, label2: F.hour(v.std) };
        }), { height: 170 }) + "</div></div>";

      html += '<div class="panel"><div class="panel-title">待下达工单' +
        '<span class="panel-actions"><button class="btn sm" id="scNew">新建工单</button></span></div>' +
        '<div class="panel-body flush">' +
        F.table([
          { label: "工单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "物料", render: function (r) { return F.esc(r.materialName) +
            '<div class="muted small mono">' + F.esc(r.materialCode) + "</div>"; } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "齐套", render: function (r) {
            if (r.kitRate === null || r.kitRate === undefined) return "—";
            return F.progress(r.kitRate, r.kitRate < 1 ? "warn" : "") + '<span class="small">' +
              F.pct(r.kitRate, 0) + "</span>";
          } },
          { label: "计划完成", key: "planEnd" },
          { label: "状态", render: function (r) { return F.tag(r.status); } }
        ], list.filter(function (w) { return w.status === "草稿" || w.status === "已下达"; }),
          { empty: "没有待下达工单", click: function (r) { return r.no; } }) + "</div></div>";

      document.getElementById("view").innerHTML = html;
      F.bindRows(document, function (no) { openOrder(no); });
      document.querySelectorAll("[data-wo]").forEach(function (b) {
        b.addEventListener("click", function () { openOrder(b.getAttribute("data-wo")); });
      });
      var nb = document.getElementById("scNew");
      if (nb) nb.addEventListener("click", newOrder);
      F.setStatus("排产计划 · " + list.length + " 个工单分布在未来两周");
    }).catch(function (e) { F.toast(e.message, "err"); });
  });

  /* ---------------------------------------------------------- 工单列表 */
  var st = { status: "全部", kw: "", overdue: false };

  F.register("orders", function () {
    var view = document.getElementById("view");
    view.innerHTML = '<div class="panel"><div class="panel-title">生产工单' +
      '<span class="panel-actions">' +
      '<input id="oKw" placeholder="工单号 / 物料 / 客户" style="width:190px;margin-right:6px">' +
      '<button class="btn sm" id="oSearch">查询</button> ' +
      '<button class="btn sm" id="oNew">新建工单</button></span></div>' +
      '<div class="panel-body"><div id="oChips"></div><div id="oList">加载中…</div></div></div>';

    function load() {
      F.api("GET", "/api/orders?" + F.qs({ status: st.status, kw: st.kw,
        overdue: st.overdue ? 1 : "" })).then(function (d) {
        document.getElementById("oChips").innerHTML =
          F.chips(STATUS, st.status) +
          '<label class="small" style="margin-left:10px"><input type="checkbox" id="oOd"' +
          (st.overdue ? " checked" : "") + "> 只看逾期</label>" +
          '<span class="small muted" style="margin-left:10px">共 ' + d.total + " 单</span>";
        document.getElementById("oList").innerHTML = F.table([
          { label: "工单号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "物料", render: function (r) { return F.esc(r.materialName) +
            '<div class="muted small mono">' + F.esc(r.materialCode) + "</div>"; } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "报工 / 合格", num: true, render: function (r) {
            return F.qty(r.reportedQty) + " / " + F.qty(r.goodQty); } },
          { label: "进度", render: function (r) {
            return '<div class="tl">' + F.progress(r.progress, r.progress >= 1 ? "" : "warn") +
              '<span class="small">' + F.pct(Math.min(1, r.progress), 0) + "</span></div>"; } },
          { label: "工序", num: true, render: function (r) { return r.opDone + "/" + r.opCount; } },
          { label: "产线", key: "line" },
          { label: "计划完成", render: function (r) { return F.esc(r.planEnd) +
            (r.dueState === "逾期" ? " " + F.tag("逾期", "red") : ""); } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "优先级", render: function (r) { return F.prio(r.priority); } }
        ], d.list, { empty: "没有符合条件的工单", click: function (r) { return r.no; } });
        F.bindRows(document, function (no) { openOrder(no); });
        document.querySelectorAll("#oChips .chip").forEach(function (c) {
          c.addEventListener("click", function () {
            st.status = c.getAttribute("data-st");
            load();
          });
        });
        document.getElementById("oOd").addEventListener("change", function (e) {
          st.overdue = e.target.checked;
          load();
        });
        F.setStatus("生产工单 · " + d.total + " 单（" + st.status + "）");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    document.getElementById("oSearch").addEventListener("click", function () {
      st.kw = document.getElementById("oKw").value.trim();
      load();
    });
    document.getElementById("oKw").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { st.kw = e.target.value.trim(); load(); }
    });
    document.getElementById("oNew").addEventListener("click", newOrder);
    load();
  });

  /* ---------------------------------------------------------- 新建工单 */
  function newOrder() {
    F.api("GET", "/api/materials?type=成品").then(function (m) {
      var mats = (m.list || []).concat([]);
      F.api("GET", "/api/materials?type=半成品").then(function (h) {
        mats = mats.concat(h.list || []);
        var lines = F.state.boot.lines || [];
        F.dialog("新建生产工单",
          '<div class="form-grid">' +
          '<label>产出物料</label><select id="noMat">' + mats.map(function (x) {
            return '<option value="' + F.esc(x.code) + '">' + F.esc(x.code + " " + x.name) + "</option>";
          }).join("") + "</select>" +
          '<label>计划数量</label><input id="noQty" type="number" value="100" min="1">' +
          '<label>产线</label><select id="noLine">' + lines.map(function (l) {
            return '<option value="' + F.esc(l.code) + '">' + F.esc(l.name) + "</option>";
          }).join("") + "</select>" +
          '<label>优先级</label><select id="noPrio"><option>普通</option><option>紧急</option></select>' +
          '<label>计划开始</label><input id="noStart" type="date" value="' + F.today() + '">' +
          '<label>客户 / 来源</label><input id="noCust" placeholder="如 苏州智联科技">' +
          '<label>备注</label><input id="noRemark" placeholder="选填"></div>' +
          '<div class="small muted" style="margin-top:8px">新建后为「草稿」，需齐套率 100% 且工艺路线、BOM 已发布才能下达。</div>',
          '<button class="btn" id="noOk">创建</button>');
        document.getElementById("noOk").addEventListener("click", function () {
          F.api("POST", "/api/orders", {
            materialCode: document.getElementById("noMat").value,
            qty: Number(document.getElementById("noQty").value),
            line: document.getElementById("noLine").value,
            priority: document.getElementById("noPrio").value,
            planStart: document.getElementById("noStart").value,
            customer: document.getElementById("noCust").value,
            remark: document.getElementById("noRemark").value
          }).then(function (x) {
            F.closeDialog();
            F.toast("已创建 " + x.no + "（" + x.opCount + " 道工序）", "ok");
            F.reload().then(function () { F.go("orders"); location.reload(); });
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
    }).catch(function (e) { F.toast(e.message, "err"); });
  }

  /* ---------------------------------------------------------- 工单详情 */
  function openOrder(no) {
    F.api("GET", "/api/orders/" + encodeURIComponent(no)).then(function (d) {
      var canWrite = F.can("write"), canApprove = F.can("approve"), canRep = F.can("report"),
        canStock = F.can("stock");

      var gates = "";
      Object.keys(d.gate || {}).forEach(function (t) {
        var miss = d.gate[t];
        var ok = !miss.length;
        gates += '<div class="gate ' + (ok ? "ok" : "") + '"><b>' + F.esc(t) + "</b>" +
          (ok ? '<span class="tag green">可推进</span>' :
            '<span class="small muted">' + F.esc(miss.join("；")) + "</span>") + "</div>";
      });

      var ops = '<table class="grid-table"><thead><tr><th>工序</th><th>工位 / 设备</th>' +
        '<th class="num">计划</th><th class="num">合格</th><th class="num">不良</th>' +
        '<th class="num">标准/实际</th><th>状态</th><th>操作</th></tr></thead><tbody>' +
        (d.operations || []).map(function (o) {
          return "<tr><td>" + F.esc(o.seq + " " + o.process) + "</td><td>" + F.esc(o.station) +
            '<div class="muted small mono">' + F.esc(o.equipment || "") + "</div></td>" +
            '<td class="num">' + F.qty(o.planQty) + '</td><td class="num">' + F.qty(o.goodQty) +
            '</td><td class="num">' + F.qty(o.ngQty) + "</td>" +
            '<td class="num small">' + F.hour(o.stdMin) + " / " + F.hour(o.actualMin) + "</td>" +
            "<td>" + F.tag(o.status) + "</td>" +
            '<td>' + (canRep && o.status !== "已完成" && (d.status === "已下达" || d.status === "已开工")
              ? '<button class="btn sm" data-rep="' + o.seq + '">报工</button>' : "") + "</td></tr>";
        }).join("") + "</tbody></table>";

      var mats = '<table class="grid-table"><thead><tr><th>物料</th><th class="num">需求</th>' +
        '<th class="num">已发</th><th class="num">现有库存</th><th class="num">缺口</th><th>状态</th></tr></thead><tbody>' +
        (d.materials || []).map(function (m) {
          return "<tr><td>" + F.esc(m.name) + '<div class="muted small mono">' + F.esc(m.materialCode) +
            "</div></td><td class='num'>" + F.qty(m.need) + '</td><td class="num">' + F.qty(m.issued) +
            "</td><td class='num'>" + F.qty(m.onHand) + "</td><td class='num'>" +
            (m.short > 0 ? '<b class="up">' + F.qty(m.short) + "</b>" : "0") +
            "</td><td>" + F.tag(m.state, m.state === "已齐套" ? "green" : "gold") + "</td></tr>";
        }).join("") + "</tbody></table>";

      var insp = F.table([
        { label: "检验单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "类型", render: function (r) { return F.tag(r.type); } },
        { label: "工序", render: function (r) { return F.esc(r.process); } },
        { label: "抽样/不良", num: true, render: function (r) { return F.qty(r.sampleQty) + " / " + F.qty(r.defectQty); } },
        { label: "结论", render: function (r) { return F.tag(r.result); } },
        { label: "检验员", render: function (r) { return F.esc(r.inspectorName); } },
        { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.inspectedAt) + "</span>"; } }
      ], d.inspections || [], { empty: "尚无检验记录" });

      var body = '<div class="kpi-grid four" style="margin-bottom:10px">' +
        '<div class="kpi"><div class="k-label">计划 / 已报工</div><div class="k-value" style="font-size:19px">' +
        F.qty(d.qty) + " / " + F.qty(d.reportedQty) + '</div><div class="k-sub">合格 ' + F.qty(d.goodQty) +
        " · 不良 " + F.qty(d.ngQty) + "</div></div>" +
        '<div class="kpi"><div class="k-label">进度</div><div class="k-value" style="font-size:19px">' +
        F.pct(Math.min(1, d.progress), 1) + '</div><div class="k-sub">工序 ' + d.opDone + "/" +
        d.opCount + "</div></div>" +
        '<div class="kpi"><div class="k-label">工时达成</div><div class="k-value" style="font-size:19px">' +
        (d.eff ? F.pct(d.eff, 1) : "—") + '</div><div class="k-sub">标准 ' + F.hour(d.stdMin) + "</div></div>" +
        '<div class="kpi"><div class="k-label">状态</div><div class="k-value" style="font-size:19px">' +
        F.tag(d.status) + '</div><div class="k-sub">' + F.esc(d.dueState) + " · 计划完成 " +
        F.esc(d.planEnd) + "</div></div></div>" +
        '<div class="detail-head"><b>' + F.esc(d.materialName) + "</b> <span class=\"mono small\">" +
        F.esc(d.materialCode) + "</span> <span class=\"muted small\">" + F.esc(d.materialSpec || "") +
        "</span></div>" +
        '<div class="small muted" style="margin:6px 0 10px">客户：' + F.esc(d.customer || "—") +
        " · 产线：" + F.esc(d.line) + " · 工艺：" + F.esc(d.routingCode) + " · BOM：" + F.esc(d.bomCode) +
        " · 计划 " + F.esc(d.planStart) + " ~ " + F.esc(d.planEnd) + "</div>" +
        '<div class="gate-box">' + gates + "</div>" +
        '<div class="section-title">工序与报工</div>' + ops +
        '<div class="section-title">用料与齐套（' + F.pct(d.kit.rate, 0) + "）</div>" + mats +
        '<div class="section-title">检验记录</div>' + insp +
        (d.batch ? '<div class="section-title">产出批次</div><div class="small">' +
          '<span class="mono">' + F.esc(d.batch.no) + "</span> · 数量 " + F.qty(d.batch.qty) +
          " · " + F.esc(d.batch.producedAt) +
          ' · <a href="#trace?batch=' + encodeURIComponent(d.batch.no) + '">查看追溯</a></div>' : "");

      var foot = "";
      if (canWrite && (d.status === "草稿" || d.status === "已下达" || d.status === "已开工")) {
        foot += '<button class="btn sm" id="odIssue">发料</button> ';
      }
      (d.nextTargets || []).forEach(function (t) {
        var allow = (t === "已下达" ? canApprove : (t === "已入库" ? canStock : canWrite));
        if (!allow) return;
        var miss = (d.gate && d.gate[t]) || [];
        foot += '<button class="btn sm ' + (t === "已下达" ? "" : "primary") + '" data-stage="' + t + '"' +
          (t === "已入库" && d.status !== "已完工" ? " disabled" : "") + ">" +
          (t === "已下达" ? "下达" : (t === "已开工" ? "开工" : (t === "已完工" ? "完工确认" : t))) +
          (miss.length ? "（缺 " + miss.length + " 项）" : "") + "</button> ";
      });
      if (canWrite && (d.status === "草稿" || d.status === "已下达" || d.status === "已开工")) {
        foot += '<button class="btn sm danger" id="odCancel">取消工单</button>';
      }
      if (d.status === "已完工" && canStock) {
        foot += '<button class="btn sm primary" id="odStock">完工入库</button>';
      }
      if (!foot) foot = '<span class="small muted">当前角色无可用操作</span>';

      F.dialog("工单 " + d.no, body, foot);

      document.querySelectorAll("[data-rep]").forEach(function (b) {
        b.addEventListener("click", function () { reportDialog(d, b.getAttribute("data-rep")); });
      });
      document.querySelectorAll("[data-stage]").forEach(function (b) {
        b.addEventListener("click", function () {
          var t = b.getAttribute("data-stage");
          if (t === "已入库") return stockIn(d.no);
          F.api("POST", "/api/orders/" + d.no + "/stage", { target: t }).then(function () {
            F.closeDialog();
            F.toast("工单已推进到「" + t + "」", "ok");
            F.reload().then(function () { openOrder(d.no); });
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
      var iss = document.getElementById("odIssue");
      if (iss) iss.addEventListener("click", function () {
        F.api("POST", "/api/orders/" + d.no + "/issue", {}).then(function (x) {
          F.toast("发料完成：" + x.issued + " 项", "ok");
          F.closeDialog();
          openOrder(d.no);
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
      var cxl = document.getElementById("odCancel");
      if (cxl) cxl.addEventListener("click", function () {
        var r = window.prompt("取消原因（必填）", "客户订单变更");
        if (!r) return;
        F.api("POST", "/api/orders/" + d.no + "/cancel", { reason: r }).then(function () {
          F.closeDialog();
          F.toast("工单已取消", "ok");
          F.reload().then(function () { openOrder(d.no); });
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
      var stk = document.getElementById("odStock");
      if (stk) stk.addEventListener("click", function () { stockIn(d.no); });
      F.setStatus("工单 " + d.no + " · " + d.status + " · 进度 " + F.pct(d.progress, 0));
    }).catch(function (e) { F.toast(e.message, "err"); });
  }

  function stockIn(no) {
    F.api("POST", "/api/orders/" + no + "/stock-in", { warehouse: "成品仓" }).then(function (x) {
      F.closeDialog();
      F.toast("已入库，批次 " + x.batch + "：" + F.qty(x.qty) + " 件", "ok");
      F.reload().then(function () { openOrder(no); });
    }).catch(function (e) { F.toast(e.message, "err"); });
  }

  function reportDialog(d, seq) {
    var op = (d.operations || []).filter(function (o) { return String(o.seq) === String(seq); })[0];
    if (!op) return;
    var left = Math.max(0, Number(op.planQty) - Number(op.goodQty) - Number(op.ngQty));
    F.dialog("报工 · " + op.process,
      '<div class="form-grid">' +
      '<label>工序</label><input value="' + F.esc(op.seq + " " + op.process) + '" disabled>' +
      '<label>设备</label><input value="' + F.esc(op.equipment || "") + '" disabled>' +
      '<label>合格数</label><input id="rpGood" type="number" value="' + left + '" min="0">' +
      '<label>不良数</label><input id="rpNg" type="number" value="0" min="0">' +
      '<label>实际工时</label><input id="rpMin" type="number" value="' +
      (op.stdMin ? Number(op.stdMin).toFixed(1) : 0) + '" min="0">' +
      '<label>备注</label><input id="rpRemark" placeholder="选填">' +
      "</div>" +
      '<div class="small muted" style="margin-top:8px">本工序待报 ' + F.qty(left) +
      " 件；标准工时 " + F.hour(op.stdMin) + "。报工将累计到工单，全部工序完成后自动转「已完工」。</div>",
      '<button class="btn primary" id="rpOk">提交报工</button>');
    document.getElementById("rpOk").addEventListener("click", function () {
      F.api("POST", "/api/orders/" + d.no + "/report", {
        seq: Number(seq),
        goodQty: Number(document.getElementById("rpGood").value || 0),
        ngQty: Number(document.getElementById("rpNg").value || 0),
        actualMin: Number(document.getElementById("rpMin").value || 0),
        remark: document.getElementById("rpRemark").value
      }).then(function (x) {
        F.closeDialog();
        F.toast("报工成功 " + x.reportNo + " · 效率 " + F.pct(x.eff, 1) +
          (x.woStatus === "已完工" ? " · 工单已完工" : ""), "ok");
        F.reload().then(function () { openOrder(d.no); });
      }).catch(function (e) { F.toast(e.message, "err"); });
    });
  }
})(window, document);
