/* 飞驰 MES · 库存台账与报表分析 */
(function (window, document) {
  "use strict";
  var F = window.F;

  /* ---------------------------------------------------------- 库存台账 */
  F.register("stock", function () {
    var st = { wh: "全部", kw: "" };
    document.getElementById("view").innerHTML =
      '<div class="panel"><div class="panel-title">库存台账' +
      '<span class="panel-actions">' +
      '<input id="skKw" placeholder="物料 / 批次" style="width:180px;margin-right:6px">' +
      '<button class="btn sm" id="skSearch">查询</button></span></div>' +
      '<div class="panel-body"><div id="skKpi"></div><div id="skChips"></div>' +
      '<div id="skList">加载中…</div></div></div>';

    function load() {
      F.api("GET", "/api/stock?" + F.qs({ warehouse: st.wh, kw: st.kw })).then(function (d) {
        document.getElementById("skKpi").innerHTML =
          '<div class="kpi-grid four" style="margin-bottom:10px">' +
          '<div class="kpi"><div class="k-label">库存行</div><div class="k-value">' + d.summary.rows +
          '</div><div class="k-sub">按批次展开</div></div>' +
          '<div class="kpi"><div class="k-label">库存总量</div><div class="k-value">' +
          F.wan(d.summary.qty) + '</div><div class="k-sub">件 / 张 / 只</div></div>' +
          '<div class="kpi green"><div class="k-label">库存金额</div><div class="k-value">' +
          F.wan(d.summary.amount) + '</div><div class="k-sub">按标准成本</div></div>' +
          '<div class="kpi"><div class="k-label">仓库</div><div class="k-value">' +
          d.warehouses.length + '</div><div class="k-sub">' + F.esc(d.warehouses.join("、")) + "</div></div></div>";
        document.getElementById("skChips").innerHTML =
          F.chips(["全部"].concat(d.warehouses), st.wh);
        document.getElementById("skList").innerHTML = F.table([
          { label: "物料", render: function (r) { return F.esc(r.name) +
            '<div class="muted small mono">' + F.esc(r.materialCode) + "</div>"; } },
          { label: "仓库", render: function (r) { return F.tag(r.warehouse, "blue"); } },
          { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.batch) + "</span>"; } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty) + " " + F.esc(r.unit); } },
          { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
          { label: "更新时间", render: function (r) { return '<span class="small muted">' + F.esc(r.updatedAt) + "</span>"; } }
        ], d.list, { empty: "没有匹配的库存", click: function (r) { return r.batch; } });
        F.bindRows(document, function (batch) { F.go("trace", { batch: batch }); });
        document.querySelectorAll("#skChips .chip").forEach(function (c) {
          c.addEventListener("click", function () { st.wh = c.getAttribute("data-st"); load(); });
        });
        F.setStatus("库存台账 · " + d.total + " 行 · " + F.wan(d.summary.amount));
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    document.getElementById("skSearch").addEventListener("click", function () {
      st.kw = document.getElementById("skKw").value.trim();
      load();
    });
    document.getElementById("skKw").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { st.kw = e.target.value.trim(); load(); }
    });
    load();
  });

  /* ---------------------------------------------------------- 报表分析 */
  var days = 14;

  F.register("reports", function () {
    document.getElementById("view").innerHTML =
      '<div class="panel"><div class="panel-title">经营与制造指标' +
      '<span class="panel-actions">' + F.chips(["7 天", "14 天", "30 天"], "14 天", "data-days") +
      " " + '<button class="btn sm" id="rpExport">导出工单</button></span></div>' +
      '<div class="panel-body" id="rpBody">加载中…</div></div>';

    function load() {
      F.api("GET", "/api/reports?days=" + days).then(function (d) {
        var p = d.production, o = d.oee, q = d.quality, e = d.equipment;
        var html = '<div class="kpi-grid six">' +
          '<div class="kpi"><div class="k-label">期间产出</div><div class="k-value">' + F.wan(p.output) +
          '</div><div class="k-sub">计划 ' + F.wan(p.plan) + " · 达成 " + F.pct(p.completion, 1) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">本月产出</div><div class="k-value">' +
          F.wan(p.monthOutput) + '</div><div class="k-sub">计划 ' + F.wan(p.monthPlan) + " · 达成 " +
          F.pct(p.monthCompletion, 1) + "</div></div>" +
          '<div class="kpi"><div class="k-label">综合 OEE</div><div class="k-value">' +
          F.pct(o.plant.oee, 1) + '</div><div class="k-sub">可用 ' + F.pct(o.plant.availability, 0) +
          " · 性能 " + F.pct(o.plant.performance, 0) + "</div></div>" +
          '<div class="kpi green"><div class="k-label">一次良率</div><div class="k-value">' +
          F.pct(q.yieldRate, 2) + '</div><div class="k-sub">PPM ' + F.int(q.ppm) + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">MTBF / MTTR</div><div class="k-value" style="font-size:17px">' +
          F.hour(e.mtbf) + " / " + F.hour(e.mttr) + '</div><div class="k-sub">故障 ' + e.failures +
          " 次 · 停机 " + F.hour(e.downMin) + "</div></div>" +
          '<div class="kpi red"><div class="k-label">保养到期</div><div class="k-value">' + e.maintDue +
          '</div><div class="k-sub">让步接收 ' + q.concession + " 批</div></div></div>";

        html += '<div class="panel" style="margin-top:10px"><div class="panel-title">产量与计划</div>' +
          '<div class="panel-body">' + F.lineChart([
            { name: "产出", data: p.trend.map(function (x) { return x.output; }) },
            { name: "计划", data: p.trend.map(function (x) { return x.plan; }) },
            { name: "不良", data: p.trend.map(function (x) { return x.ng; }) }
          ], { labels: p.trend.map(function (x) { return x.day; }),
            colors: ["#1f7a8c", "#c8963e", "#b4463a"] }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">OEE 三率趋势' +
          '<span class="panel-actions small muted">目标 ' + F.pct(o.target, 0) + "</span></div>" +
          '<div class="panel-body">' + F.lineChart([
            { name: "OEE", data: o.trend.map(function (x) { return x.oee * 100; }) },
            { name: "可用率", data: o.trend.map(function (x) { return x.availability * 100; }) },
            { name: "性能率", data: o.trend.map(function (x) { return x.performance * 100; }) }
          ], { labels: o.trend.map(function (x) { return x.day; }), zero: false,
            colors: ["#1f7a8c", "#2f8f5b", "#c8963e"] }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">质量与缺陷帕累托</div><div class="panel-body" ' +
          'style="display:grid;grid-template-columns:1fr 1fr;gap:14px">' +
          "<div>" + F.barChart(q.pareto.slice(0, 8).map(function (x) {
            return { label: String(x.name).slice(0, 4), value: x.qty, label2: F.qty(x.qty),
              color: x.key ? "#b4463a" : "#8fb3c4" };
          }), { height: 170 }) + "</div>" +
          '<div class="small" style="line-height:2">' +
          F.kv("检验单", q.inspCount + " 张") +
          F.kv("首件合格率", F.pct(q.faiPassRate, 1)) +
          F.kv("完工检合格率", F.pct(q.fqcPassRate, 1)) +
          F.kv("巡检异常", q.patrolAbnormal + " 次") +
          F.kv("让步接收 / 退货", q.concession + " / " + q.rejected) +
          F.kv("不良待处置", q.pendingDispose + " 条") + "</div></div></div>";

        html += '<div class="panel"><div class="panel-title">产线负荷与平衡</div><div class="panel-body">' +
          F.table([
            { label: "产线", render: function (r) { return F.esc(r.name) +
              '<div class="muted small mono">' + F.esc(r.code) + "</div>"; } },
            { label: "在制", num: true, render: function (r) { return r.wip; } },
            { label: "标准工时", num: true, render: function (r) { return F.hour(r.stdMin); } },
            { label: "产出", num: true, render: function (r) { return F.qty(r.output); } },
            { label: "负荷", render: function (r) {
              return '<div class="tl">' + F.progress(r.load) + '<span class="small">' + F.pct(r.load, 0) + "</span></div>"; } },
            { label: "平衡率", num: true, render: function (r) { return F.pct(r.balance, 1); } }
          ], d.lines) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">设备 OEE 排名</div><div class="panel-body flush">' +
          F.table([
            { label: "设备", render: function (r) { return F.esc(r.name) + '<div class="muted small mono">' +
              F.esc(r.code) + " · " + F.esc(r.line) + "</div>"; } },
            { label: "OEE", num: true, render: function (r) {
              return '<div class="tl">' + F.progress(r.oee, r.oee >= 0.85 ? "" : "warn") + "<b>" +
                F.pct(r.oee, 1) + "</b></div>"; } },
            { label: "可用率", num: true, render: function (r) { return F.pct(r.availability, 0); } },
            { label: "性能率", num: true, render: function (r) { return F.pct(r.performance, 0); } },
            { label: "质量率", num: true, render: function (r) { return F.pct(r.quality, 1); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } },
            { label: "评价", render: function (r) { return F.tag(r.level); } }
          ], e.rank) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">停机原因 TOP</div><div class="panel-body">' +
          F.barChart(e.downTop.map(function (x) {
            return { label: String(x.reason).slice(0, 5), value: x.minutes, label2: F.hour(x.minutes),
              color: x.reason === "设备故障" ? "#b4463a" : "#8fb3c4" };
          }), { height: 160 }) + "</div></div>";

        html += '<div class="panel"><div class="panel-title">物料消耗 TOP</div><div class="panel-body flush">' +
          F.table([
            { label: "物料", render: function (r) { return F.esc(r.name) +
              '<div class="muted small mono">' + F.esc(r.materialCode) + "</div>"; } },
            { label: "消耗量", num: true, render: function (r) { return F.qty(r.qty) + " " + F.esc(r.unit); } },
            { label: "金额", num: true, render: function (r) { return F.wan(r.amount); } },
            { label: "占比", num: true, render: function (r) {
              return '<div class="tl">' + F.progress(r.share) + '<span class="small">' + F.pct(r.share, 1) + "</span></div>"; } }
          ], d.consumption) + "</div></div>";

        document.getElementById("rpBody").innerHTML = html;
        document.querySelectorAll("[data-days]").forEach(function (c) {
          c.addEventListener("click", function () {
            days = parseInt(c.getAttribute("data-days"), 10);
            document.querySelectorAll("[data-days]").forEach(function (x) { x.classList.remove("on"); });
            c.classList.add("on");
            load();
          });
        });
        document.getElementById("rpExport").addEventListener("click", function () {
          window.open("/api/export/orders", "_blank");
        });
        F.setStatus("报表分析 · 近 " + days + " 天 · OEE " + F.pct(o.plant.oee, 1) +
          " · 达成 " + F.pct(p.completion, 1));
        F.setSide('<div class="side-block"><div class="hd">指标口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">产出取工单末工序报工，避免逐工序重复计数；<br>' +
          "计划按工单计划期均摊；<br>负荷 = 需求标准工时 ÷ 可用工时（3 班 × 22 天）；<br>" +
          "MTBF = 运行时间 ÷ 故障次数，MTTR = 停机时间 ÷ 故障次数。</div></div>" +
          '<div class="side-block"><div class="hd">期间摘要</div><div class="bd">' +
          F.kv("产出", F.wan(p.output)) +
          F.kv("达成率", F.pct(p.completion, 1)) +
          F.kv("良率", F.pct(q.yieldRate, 2)) +
          F.kv("OEE", F.pct(o.plant.oee, 1)) + "</div></div>");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    load();
  });
})(window, document);
