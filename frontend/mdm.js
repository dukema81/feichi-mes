/* 飞驰 MES · 物料与 BOM、批次追溯 */
(function (window, document) {
  "use strict";
  var F = window.F;
  var TYPES = ["全部", "原材料", "半成品", "成品"];

  /* ---------------------------------------------------------- 物料主数据 */
  var st = { type: "全部", kw: "" };

  F.register("materials", function () {
    document.getElementById("view").innerHTML =
      '<div class="panel"><div class="panel-title">物料与 BOM' +
      '<span class="panel-actions">' +
      '<input id="mKw" placeholder="编码 / 名称 / 规格" style="width:200px;margin-right:6px">' +
      '<button class="btn sm" id="mSearch">查询</button> ' +
      '<button class="btn sm" id="mNew">新建物料</button></span></div>' +
      '<div class="panel-body"><div id="mChips"></div><div id="mSummary"></div>' +
      '<div id="mList">加载中…</div></div></div>';

    function load() {
      F.api("GET", "/api/materials?" + F.qs({ type: st.type === "全部" ? "" : st.type, kw: st.kw }))
        .then(function (d) {
          document.getElementById("mChips").innerHTML = F.chips(TYPES, st.type);
          document.getElementById("mSummary").innerHTML =
            '<div class="kpi-grid four" style="margin-bottom:10px">' +
            '<div class="kpi"><div class="k-label">物料数</div><div class="k-value">' + d.summary.count +
            '</div><div class="k-sub">成品 ' + d.summary.finished + " 项</div></div>" +
            '<div class="kpi red"><div class="k-label">低于安全库存</div><div class="k-value">' +
            d.summary.belowSafety + '</div><div class="k-sub">需补货或调整</div></div>' +
            '<div class="kpi"><div class="k-label">库存金额</div><div class="k-value">' +
            F.wan(d.summary.amount) + '</div><div class="k-sub">按标准成本</div></div>' +
            '<div class="kpi gold"><div class="k-label">成品 / 半成品</div><div class="k-value">' +
            (d.list.filter(function (x) { return x.type === "成品"; }).length) + " / " +
            (d.list.filter(function (x) { return x.type === "半成品"; }).length) +
            '</div><div class="k-sub">可下达工单</div></div></div>';
          document.getElementById("mList").innerHTML = F.table([
            { label: "物料编码", render: function (r) { return '<span class="mono small">' + F.esc(r.code) + "</span>"; } },
            { label: "名称 / 规格", render: function (r) { return F.esc(r.name) +
              '<div class="muted small">' + F.esc(r.spec || "—") + "</div>"; } },
            { label: "类型", render: function (r) { return F.tag(r.type, r.type === "成品" ? "green" :
              (r.type === "半成品" ? "blue" : "gray")); } },
            { label: "ABC", render: function (r) { return F.tag(r.abc); } },
            { label: "现存量", num: true, render: function (r) {
              return '<b class="' + (r.belowSafety ? "up" : "") + '">' + F.qty(r.onHand) + "</b> " +
                F.esc(r.unit); } },
            { label: "安全库存", num: true, render: function (r) { return F.qty(r.safetyStock); } },
            { label: "标准成本", num: true, render: function (r) { return F.num(r.stdCost, 2); } },
            { label: "库存金额", num: true, render: function (r) { return F.wan(r.amount); } },
            { label: "状态", render: function (r) { return F.tag(r.status); } }
          ], d.list, { empty: "没有匹配的物料", click: function (r) { return r.code; } });
          F.bindRows(document, function (code) { detail(code); });
          document.querySelectorAll("#mChips .chip").forEach(function (c) {
            c.addEventListener("click", function () { st.type = c.getAttribute("data-st"); load(); });
          });
          F.setStatus("物料主数据 · " + d.total + " 项");
          F.setSide('<div class="side-block"><div class="hd">物料分类</div><div class="bd">' +
            ["原材料", "半成品", "成品"].map(function (t) {
              var arr = d.list.filter(function (x) { return x.type === t; });
              return F.kv(t, arr.length + " 项 · " + F.wan(arr.reduce(function (a, b) {
                return a + b.amount;
              }, 0)));
            }).join("") + "</div></div>" +
            '<div class="side-block"><div class="hd">齐套口径</div><div class="bd small muted" ' +
            'style="line-height:1.9">工单齐套率 = 已齐套物料项数 ÷ 需求项数；可用量 = 现有库存 + 已发料。' +
            "齐套率 100% 才允许下达（规则可关闭）。</div></div>");
        }).catch(function (e) { F.toast(e.message, "err"); });
    }

    document.getElementById("mSearch").addEventListener("click", function () {
      st.kw = document.getElementById("mKw").value.trim();
      load();
    });
    document.getElementById("mKw").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { st.kw = e.target.value.trim(); load(); }
    });
    document.getElementById("mNew").addEventListener("click", function () {
      F.dialog("新建物料",
        '<div class="form-grid">' +
        '<label>物料编码</label><input id="nmCode" placeholder="MT-9100">' +
        '<label>名称</label><input id="nmName" placeholder="物料名称">' +
        '<label>规格</label><input id="nmSpec" placeholder="规格型号">' +
        '<label>单位</label><input id="nmUnit" value="件">' +
        '<label>类型</label><select id="nmType"><option>原材料</option><option>半成品</option>' +
        "<option>成品</option></select>" +
        '<label>安全库存</label><input id="nmSafety" type="number" value="100">' +
        '<label>标准成本</label><input id="nmCost" type="number" value="10">' +
        '<label>采购提前期</label><input id="nmLead" type="number" value="7">' +
        "</div>",
        '<button class="btn" id="nmOk">创建</button>');
      document.getElementById("nmOk").addEventListener("click", function () {
        F.api("POST", "/api/materials", {
          code: document.getElementById("nmCode").value.trim(),
          name: document.getElementById("nmName").value.trim(),
          spec: document.getElementById("nmSpec").value,
          unit: document.getElementById("nmUnit").value,
          type: document.getElementById("nmType").value,
          safetyStock: Number(document.getElementById("nmSafety").value || 0),
          stdCost: Number(document.getElementById("nmCost").value || 0),
          leadDays: Number(document.getElementById("nmLead").value || 7)
        }).then(function () {
          F.closeDialog();
          F.toast("物料已创建", "ok");
          load();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    });
    load();
  });

  function detail(code) {
    F.api("GET", "/api/materials/" + encodeURIComponent(code)).then(function (d) {
      var m = d.material;
      var bom = d.bom ? '<table class="grid-table"><thead><tr><th>序号</th><th>组件</th>' +
        '<th class="num">用量</th><th class="num">损耗率</th><th class="num">现有库存</th>' +
        '</tr></thead><tbody>' + d.bom.items.map(function (x) {
          return "<tr><td>" + x.component + "</td><td>" + F.esc(x.name) + "</td>" +
            "<td class='num'>" + F.qty(x.qty) + "</td><td class='num'>" + F.pct(x.lossRate, 1) +
            "</td><td class='num'>" + F.qty(x.onHand) + "</td></tr>";
        }).join("") + "</tbody></table>" : '<div class="muted small">该物料没有 BOM</div>';

      var routing = d.routing ? '<table class="grid-table"><thead><tr><th>工序</th><th>工位</th>' +
        '<th>设备类型</th><th class="num">标准工时</th><th class="num">节拍(秒)</th><th>关键</th>' +
        '</tr></thead><tbody>' + d.routing.steps.map(function (s) {
          return "<tr><td>" + s.seq + " " + F.esc(s.process) + "</td><td>" + F.esc(s.station) +
            "</td><td>" + F.esc(s.equipType) + "</td><td class='num'>" + F.num(s.stdMin, 2) +
            "</td><td class='num'>" + F.num(s.cycleSec, 0) + "</td><td>" +
            (s.isKey ? F.tag("关键", "gold") : "—") + "</td></tr>";
        }).join("") + "</tbody></table>" : '<div class="muted small">该物料没有工艺路线</div>';

      var stock = F.table([
        { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.batch) + "</span>"; } },
        { label: "仓库", key: "warehouse" },
        { label: "数量", num: true, render: function (r) { return F.qty(r.qty) + " " + F.esc(m.unit); } },
        { label: "更新时间", render: function (r) { return '<span class="small muted">' + F.esc(r.updatedAt) + "</span>"; } }
      ], d.stock, { empty: "暂无库存" });

      var orders = F.table([
        { label: "工单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
        { label: "计划完成", key: "planEnd" },
        { label: "状态", render: function (r) { return F.tag(r.status); } }
      ], d.orders, { empty: "暂无工单" });

      var batches = F.table([
        { label: "批次", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "工单", render: function (r) { return F.esc(r.woNo || "—"); } },
        { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
        { label: "产出时间", render: function (r) { return '<span class="small">' + F.esc(r.producedAt) + "</span>"; } },
        { label: "状态", render: function (r) { return F.tag(r.status); } }
      ], d.batches, { empty: "暂无批次" });

      F.dialog("物料 " + m.code,
        '<div class="detail-head"><b>' + F.esc(m.name) + '</b><span class="muted small">' +
        F.esc(m.spec || "") + '</span><span class="spacer"></span>' + F.tag(m.type, "blue") +
        F.tag(m.abc) + "</div>" +
        '<div class="kpi-grid four" style="margin:10px 0">' +
        '<div class="kpi"><div class="k-label">现存量</div><div class="k-value" style="font-size:18px">' +
        F.qty(m.onHand) + " " + F.esc(m.unit) + '</div><div class="k-sub">安全 ' +
        F.qty(m.safetyStock) + "</div></div>" +
        '<div class="kpi"><div class="k-label">库存金额</div><div class="k-value" style="font-size:18px">' +
        F.wan(m.amount) + '</div><div class="k-sub">标准成本 ' + F.num(m.stdCost, 2) + "</div></div>" +
        '<div class="kpi"><div class="k-label">提前期</div><div class="k-value" style="font-size:18px">' +
        m.leadDays + ' 天</div><div class="k-sub">分类 ' + F.esc(m.category || "—") + "</div></div>" +
        '<div class="kpi"><div class="k-label">BOM / 工序</div><div class="k-value" style="font-size:18px">' +
        (d.bom ? d.bom.items.length : 0) + " / " + (d.routing ? d.routing.steps.length : 0) +
        '</div><div class="k-sub">' + (d.routing ? "平衡率 " + F.pct(d.routing.steps.length ?
          0 : 0, 0) : "") + "</div></div></div>" +
        '<div class="section-title">BOM 结构' + (d.bom ? '（' + F.esc(d.bom.code) + " " +
          F.esc(d.bom.version) + "）" : "") + "</div>" + bom +
        '<div class="section-title">工艺路线' + (d.routing ? '（' + F.esc(d.routing.code) + " " +
          F.esc(d.routing.version) + "）" : "") + "</div>" + routing +
        '<div class="section-title">库存批次</div>' + stock +
        '<div class="section-title">近期工单</div>' + orders +
        '<div class="section-title">产出批次</div>' + batches,
        '<span class="small muted">库存数量随发料、入库实时变化</span>');
    }).catch(function (e) { F.toast(e.message, "err"); });
  }

  /* ---------------------------------------------------------- 批次追溯 */
  F.register("trace", function (params) {
    var view = document.getElementById("view");
    view.innerHTML = '<div class="panel"><div class="panel-title">批次追溯' +
      '<span class="panel-actions">' +
      '<input id="trBatch" placeholder="输入批次号，如 B20261018-01" style="width:240px;margin-right:6px">' +
      '<button class="btn sm" id="trGo">追溯</button></span></div>' +
      '<div class="panel-body"><div id="trResult" class="muted small">' +
      "输入批次号或从下方列表选择，正向展开成品→组件→原料，反向定位该批次流向。</div></div></div>" +
      '<div class="panel"><div class="panel-title">最近批次' +
      '<span class="panel-actions small muted">近 200 条</span></div>' +
      '<div class="panel-body flush" id="trList">加载中…</div></div>';

    function loadList() {
      F.api("GET", "/api/batches").then(function (d) {
        document.getElementById("trList").innerHTML = F.table([
          { label: "批次号", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
          { label: "物料", render: function (r) { return F.esc(r.materialName) +
            '<div class="muted small mono">' + F.esc(r.materialCode) + "</div>"; } },
          { label: "工单", render: function (r) { return F.esc(r.woNo || "—"); } },
          { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
          { label: "下级批次", num: true, render: function (r) { return r.children; } },
          { label: "产出时间", render: function (r) { return '<span class="small">' + F.esc(r.producedAt) + "</span>"; } },
          { label: "状态", render: function (r) { return F.tag(r.state, r.state === "正常" ? "green" :
            (r.state === "临期" ? "gold" : "red")); } }
        ], d.list, { empty: "暂无批次", click: function (r) { return r.no; } });
        F.bindRows(document, function (no) { show(no); });
        F.setStatus("批次追溯 · " + d.total + " 个批次");
        if (d.expiring) F.toast("有 " + d.expiring + " 个批次临期或已过期", "err");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function show(no) {
      if (!no) return;
      F.api("GET", "/api/trace?batch=" + encodeURIComponent(no)).then(function (d) {
        F.api("GET", "/api/batches/" + encodeURIComponent(no)).then(function (b) {
          var levels = {};
          d.nodes.forEach(function (n) {
            (levels[n.depth] = levels[n.depth] || []).push(n);
          });
          var tree = Object.keys(levels).sort().map(function (lv) {
            return '<div class="trace-level"><div class="tl-label">' +
              (Number(lv) === 0 ? "成品批次" : (Number(lv) === 1 ? "直接组件" : "第 " + lv + " 层物料")) +
              '</div><div class="tl-items">' + levels[lv].map(function (n) {
                return '<div class="tl-node"><span class="mono small">' + F.esc(n.batch) + "</span>" +
                  '<div class="small">' + F.esc(n.materialName) + "</div>" +
                  '<div class="muted small">' + F.qty(n.qty) + " · " + F.esc(n.producedAt.slice(0, 10)) +
                  "</div></div>";
              }).join("") + "</div></div>";
          }).join('<div class="trace-arrow">↓</div>');

          var html = '<div class="kpi-grid four" style="margin-bottom:10px">' +
            '<div class="kpi"><div class="k-label">批次</div><div class="k-value" style="font-size:15px">' +
            F.esc(d.root) + '</div><div class="k-sub">' + F.esc(b.materialName) + "</div></div>" +
            '<div class="kpi"><div class="k-label">来源工单</div><div class="k-value" style="font-size:15px">' +
            F.esc(b.woNo || "—") + '</div><div class="k-sub">' + F.esc(b.order ? b.order.status : "") +
            "</div></div>" +
            '<div class="kpi"><div class="k-label">数量</div><div class="k-value" style="font-size:15px">' +
            F.qty(b.qty) + ' <span class="small">' + F.esc(b.unit || "") + "</span></div>" +
            '<div class="k-sub">产出 ' + F.esc(b.producedAt) + "</div></div>" +
            '<div class="kpi"><div class="k-label">追溯节点</div><div class="k-value" style="font-size:15px">' +
            d.nodeCount + '</div><div class="k-sub">上游 ' + d.upstream.length + " 层</div></div></div>";

          html += '<div class="section-title">正向展开（成品 → 组件 → 原料）</div>' +
            '<div class="trace-tree">' + tree + "</div>";
          if (d.upstream.length) {
            html += '<div class="section-title">反向流向（该批次被用于）</div><div class="small">' +
              d.upstream.map(function (u) { return '<span class="tag blue">' + F.esc(u) + "</span>"; }).join(" ") +
              "</div>";
          }
          html += '<div class="section-title">报工记录（来源工单）</div>' + F.table([
            { label: "报工单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "工序", key: "process" },
            { label: "合格", num: true, render: function (r) { return F.qty(r.goodQty); } },
            { label: "操作员", key: "operator" },
            { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.reportedAt) + "</span>"; } }
          ], b.reports || [], { empty: "无报工记录" });

          document.getElementById("trResult").innerHTML = html;
          document.getElementById("trBatch").value = no;
          F.setStatus("批次 " + no + " · " + d.nodeCount + " 个节点");
        }).catch(function (e) { F.toast(e.message, "err"); });
      }).catch(function (e) {
        document.getElementById("trResult").innerHTML = '<div class="empty-hint">' + F.esc(e.message) + "</div>";
      });
    }

    document.getElementById("trGo").addEventListener("click", function () {
      show(document.getElementById("trBatch").value.trim());
    });
    document.getElementById("trBatch").addEventListener("keydown", function (e) {
      if (e.key === "Enter") show(e.target.value.trim());
    });
    loadList();
    if (params && params.batch) show(params.batch);
  });
})(window, document);
