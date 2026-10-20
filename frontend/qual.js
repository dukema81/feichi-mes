/* 飞驰 MES · 质量检验、不良处置与过程能力 */
(function (window, document) {
  "use strict";
  var F = window.F;
  var TYPES = ["全部", "首件", "巡检", "完工检", "来料检"];
  var tab = "insp";

  F.register("quality", function () {
    var view = document.getElementById("view");
    view.innerHTML = '<div class="panel"><div class="panel-title">质量总览' +
      '<span class="panel-actions small muted">本月口径</span></div>' +
      '<div class="panel-body" id="qKpi">加载中…</div></div>' +
      '<div class="panel"><div class="panel-title">质量作业' +
      '<span class="panel-actions"><button class="btn sm" id="qNewInsp">登记检验</button> ' +
      '<button class="btn sm" id="qNewDef">登记不良</button></span></div>' +
      '<div class="panel-body"><div id="qTabs" class="chips"></div><div id="qBody"></div></div></div>';

    var type = "全部";

    function loadKpi() {
      F.api("GET", "/api/quality/summary").then(function (d) {
        document.getElementById("qKpi").innerHTML =
          '<div class="kpi-grid six">' +
          '<div class="kpi green"><div class="k-label">一次良率</div><div class="k-value">' +
          F.pct(d.yieldRate, 2) + '</div><div class="k-sub">PPM ' + F.int(d.ppm) + "</div></div>" +
          '<div class="kpi"><div class="k-label">首件合格率</div><div class="k-value">' +
          F.pct(d.faiPassRate, 1) + '</div><div class="k-sub">未做首件不得开工</div></div>' +
          '<div class="kpi"><div class="k-label">完工检合格率</div><div class="k-value">' +
          F.pct(d.fqcPassRate, 1) + '</div><div class="k-sub">让步 ' + d.concession +
          " · 退货 " + d.rejected + "</div></div>" +
          '<div class="kpi gold"><div class="k-label">巡检异常</div><div class="k-value">' +
          d.patrolAbnormal + '</div><div class="k-sub">检验单 ' + d.inspCount + " 张</div></div>" +
          '<div class="kpi red"><div class="k-label">不良待处置</div><div class="k-value">' +
          d.pendingDispose + '</div><div class="k-sub">累计不良 ' + F.qty(d.defectQty) + " 件</div></div>" +
          '<div class="kpi"><div class="k-label">质量趋势</div><div class="k-value" style="font-size:15px">' +
          F.pct((d.trend[d.trend.length - 1] || {}).yieldRate || 0, 2) +
          '</div><div class="k-sub">昨日良率</div></div></div>' +
          '<div style="display:grid;grid-template-columns:1.4fr 1fr;gap:12px;margin-top:8px">' +
          '<div><div class="small muted" style="margin-bottom:4px">近 14 天良率</div>' +
          F.lineChart([{ name: "良率", data: (d.trend || []).map(function (t) { return t.yieldRate * 100; }) }],
            { labels: (d.trend || []).map(function (t) { return t.day; }), height: 170, colors: ["#2f8f5b"],
              zero: false }) + "</div>" +
          '<div><div class="small muted" style="margin-bottom:4px">不良帕累托（TOP 8）</div>' +
          F.barChart((d.pareto || []).slice(0, 8).map(function (p) {
            return { label: String(p.name).slice(0, 4), value: p.qty, label2: F.qty(p.qty),
              color: p.key ? "#b4463a" : "#8fb3c4" };
          }), { height: 170 }) + "</div></div>";
        F.setSide('<div class="side-block"><div class="hd">质量判定口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">首件：零缺陷才合格；巡检：发现不良即异常；' +
          "完工检：不良率 ≤ 报废预警阈值判让步接收，超阈值退货。只有合格与让步接收允许入库。</div></div>" +
          '<div class="side-block"><div class="hd">不良 TOP</div><div class="bd">' +
          (d.pareto || []).slice(0, 6).map(function (p) {
            return F.kv(String(p.name).slice(0, 10), F.qty(p.qty) + " · " + F.pct(p.share, 1));
          }).join("") + "</div></div>");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function paintTabs() {
      document.getElementById("qTabs").innerHTML =
        [["insp", "检验单"], ["defect", "不良记录"], ["cpk", "过程能力"]].map(function (t) {
          return '<button class="chip' + (tab === t[0] ? " on" : "") + '" data-tab="' + t[0] + '">' +
            t[1] + "</button>";
        }).join("") + (tab === "insp" ? '<span style="margin-left:10px">' + F.chips(TYPES, type) + "</span>" : "");
      document.querySelectorAll("#qTabs [data-tab]").forEach(function (b) {
        b.addEventListener("click", function () { tab = b.getAttribute("data-tab"); paintTabs(); loadBody(); });
      });
      document.querySelectorAll("#qTabs .chip[data-st]").forEach(function (c) {
        c.addEventListener("click", function () { type = c.getAttribute("data-st"); paintTabs(); loadBody(); });
      });
    }

    function loadBody() {
      if (tab === "insp") {
        F.api("GET", "/api/inspections?" + F.qs({ type: type === "全部" ? "" : type })).then(function (d) {
          document.getElementById("qBody").innerHTML = F.table([
            { label: "检验单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
            { label: "类型", render: function (r) { return F.tag(r.type); } },
            { label: "工单", render: function (r) { return '<span class="mono small">' + F.esc(r.woNo) + "</span>"; } },
            { label: "工序", render: function (r) { return F.esc(r.process); } },
            { label: "抽样", num: true, render: function (r) { return F.qty(r.sampleQty); } },
            { label: "不良", num: true, render: function (r) { return F.qty(r.defectQty); } },
            { label: "不良率", num: true, render: function (r) { return F.pct(r.defectRate, 2); } },
            { label: "结论", render: function (r) { return F.tag(r.result); } },
            { label: "检验员", render: function (r) { return F.esc(r.inspectorName); } },
            { label: "时间", render: function (r) { return '<span class="small muted">' + F.esc(r.inspectedAt) + "</span>"; } }
          ], d.list, { empty: "暂无检验单", click: function (r) { return r.no; } });
          F.bindRows(document, function (no) { showInsp(no); });
          F.setStatus("检验单 · " + d.total + " 张");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else if (tab === "defect") {
        F.api("GET", "/api/defects").then(function (d) {
          document.getElementById("qBody").innerHTML =
            '<div class="small muted" style="margin-bottom:6px">共 ' + d.total + " 条 · 待处置 " +
            d.pending + " 条 · 累计 " + F.qty(d.qty) + " 件</div>" + F.table([
              { label: "工单", render: function (r) { return '<span class="mono small">' + F.esc(r.woNo) + "</span>"; } },
              { label: "不良代码", render: function (r) { return F.esc(r.code) + ' <span class="muted small">' +
                F.esc(r.name) + "</span>"; } },
              { label: "类别", render: function (r) { return F.tag(r.category, "gray"); } },
              { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
              { label: "工序 / 设备", render: function (r) { return F.esc(r.process) +
                '<div class="muted small mono">' + F.esc(r.equipment || "") + "</div>"; } },
              { label: "发生时间", render: function (r) { return '<span class="small">' + F.esc(r.occurAt) + "</span>"; } },
              { label: "处置", render: function (r) { return F.tag(r.disposition); } },
              { label: "", render: function (r) {
                if (r.disposition !== "待处置") return "";
                if (!F.can("inspect")) return "";
                return '<button class="btn sm" data-disp="' + r.id + '">处置</button>';
              } }
            ], d.list, { empty: "暂无不良记录" });
          document.querySelectorAll("[data-disp]").forEach(function (b) {
            b.addEventListener("click", function () { dispose(Number(b.getAttribute("data-disp"))); });
          });
          F.setStatus("不良记录 · " + d.total + " 条");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else {
        F.api("GET", "/api/cpk").then(function (d) {
          document.getElementById("qBody").innerHTML =
            '<div class="small muted" style="margin-bottom:6px">样本 ' + d.samples + " 个 · 特性 " +
            d.items + " 项（Cpk 下限 1.33）</div>" + F.table([
              { label: "检验特性", key: "item" },
              { label: "样本", num: true, render: function (r) { return r.n; } },
              { label: "下限 LSL", num: true, render: function (r) { return r.lsl; } },
              { label: "上限 USL", num: true, render: function (r) { return r.usl; } },
              { label: "均值", num: true, render: function (r) { return r.mean; } },
              { label: "极值", num: true, render: function (r) { return r.min + " ~ " + r.max; } },
              { label: "Cpk", num: true, render: function (r) {
                return r.cpk === null ? "—" : '<b>' + Number(r.cpk).toFixed(2) + "</b>"; } },
              { label: "评价", render: function (r) { return F.tag(r.level); } }
            ], d.list, { empty: "暂无测量数据" });
          F.setStatus("过程能力 · " + d.items + " 项特性");
        }).catch(function (e) { F.toast(e.message, "err"); });
      }
    }

    function showInsp(no) {
      F.api("GET", "/api/inspections/" + encodeURIComponent(no)).then(function (d) {
        var items = F.table([
          { label: "检验项", key: "item" },
          { label: "实测值", num: true, render: function (r) { return r.value; } },
          { label: "下限", num: true, render: function (r) { return r.lsl; } },
          { label: "上限", num: true, render: function (r) { return r.usl; } },
          { label: "判定", render: function (r) { return F.tag(r.result); } }
        ], d.items, { empty: "该检验单无测量项" });
        F.dialog("检验单 " + d.no,
          '<div class="kpi-grid four" style="margin-bottom:10px">' +
          '<div class="kpi"><div class="k-label">类型</div><div class="k-value" style="font-size:16px">' +
          F.tag(d.type) + '</div><div class="k-sub">' + F.esc(d.woNo) + "</div></div>" +
          '<div class="kpi"><div class="k-label">抽样 / 不良</div><div class="k-value" style="font-size:16px">' +
          F.qty(d.sampleQty) + " / " + F.qty(d.defectQty) + '</div><div class="k-sub">不良率 ' +
          F.pct(d.defectRate, 2) + "</div></div>" +
          '<div class="kpi"><div class="k-label">结论</div><div class="k-value" style="font-size:16px">' +
          F.tag(d.result) + '</div><div class="k-sub">' + F.esc(d.standard) + "</div></div>" +
          '<div class="kpi"><div class="k-label">Cpk</div><div class="k-value" style="font-size:16px">' +
          (d.cpk === null ? "—" : Number(d.cpk).toFixed(2)) + '</div><div class="k-sub">检验员 ' +
          F.esc(d.inspectorName) + "</div></div></div>" +
          '<div class="section-title">测量项</div>' + items +
          '<div class="section-title">关联不良</div>' + F.table([
            { label: "代码", key: "code" },
            { label: "数量", num: true, render: function (r) { return F.qty(r.qty); } },
            { label: "处置", render: function (r) { return F.tag(r.disposition); } }
          ], d.defects, { empty: "无不良" }),
          '<span class="small muted">检验时间 ' + F.esc(d.inspectedAt) + "</span>");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    function dispose(id) {
      F.dialog("不良处置",
        '<div class="form-grid"><label>处置方式</label><select id="dpWay">' +
        "<option>返修</option><option>报废</option><option>让步接收</option><option>退货</option></select>" +
        '<label>说明</label><input id="dpRemark" placeholder="选填"></div>',
        '<button class="btn" id="dpOk">提交</button>');
      document.getElementById("dpOk").addEventListener("click", function () {
        F.api("POST", "/api/defects/" + id + "/dispose", {
          disposition: document.getElementById("dpWay").value,
          remark: document.getElementById("dpRemark").value
        }).then(function () {
          F.closeDialog();
          F.toast("处置完成", "ok");
          loadKpi();
          loadBody();
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    document.getElementById("qNewInsp").addEventListener("click", function () {
      if (!F.can("inspect")) return F.toast("当前角色无质检权限", "err");
      F.api("GET", "/api/orders?status=已开工").then(function (a) {
        F.api("GET", "/api/orders?status=已完工").then(function (b) {
          var list = (a.list || []).concat(b.list || []);
          if (!list.length) return F.toast("没有在制或待检工单", "err");
          F.dialog("登记检验",
            '<div class="form-grid">' +
            '<label>工单</label><select id="niWo">' + list.map(function (w) {
              return '<option value="' + F.esc(w.no) + '">' + F.esc(w.no + " " + w.materialName) + "</option>";
            }).join("") + "</select>" +
            '<label>类型</label><select id="niType"><option>首件</option><option>巡检</option>' +
            "<option>完工检</option><option>来料检</option></select>" +
            '<label>抽样数</label><input id="niSample" type="number" value="5">' +
            '<label>不良数</label><input id="niDefect" type="number" value="0">' +
            '<label>被测值</label><input id="niVal" type="number" step="0.001" value="100.0">' +
            '<label>公差下限</label><input id="niLsl" type="number" step="0.001" value="99.7">' +
            '<label>公差上限</label><input id="niUsl" type="number" step="0.001" value="100.3">' +
            '<label>说明</label><input id="niRemark" placeholder="选填"></div>',
            '<button class="btn primary" id="niOk">提交</button>');
          document.getElementById("niOk").addEventListener("click", function () {
            var body = {
              woNo: document.getElementById("niWo").value,
              type: document.getElementById("niType").value,
              sampleQty: Number(document.getElementById("niSample").value || 0),
              defectQty: Number(document.getElementById("niDefect").value || 0),
              remark: document.getElementById("niRemark").value
            };
            if (body.type !== "巡检") {
              body.items = [{ item: "关键尺寸", value: Number(document.getElementById("niVal").value),
                lsl: Number(document.getElementById("niLsl").value),
                usl: Number(document.getElementById("niUsl").value) }];
            }
            F.api("POST", "/api/inspections", body).then(function (x) {
              F.closeDialog();
              F.toast("检验完成：" + x.result, x.result === "合格" ? "ok" : "err");
              loadKpi();
              loadBody();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    });

    document.getElementById("qNewDef").addEventListener("click", function () {
      if (!F.can("inspect")) return F.toast("当前角色无质检权限", "err");
      F.api("GET", "/api/defect-codes").then(function (c) {
        F.api("GET", "/api/orders?status=已开工").then(function (o) {
          var list = (o.list || []);
          if (!list.length) return F.toast("没有在制工单", "err");
          F.dialog("登记不良",
            '<div class="form-grid">' +
            '<label>工单</label><select id="ndWo">' + list.map(function (w) {
              return '<option value="' + F.esc(w.no) + '">' + F.esc(w.no + " " + w.materialName) + "</option>";
            }).join("") + "</select>" +
            '<label>不良代码</label><select id="ndCode">' + (c.list || []).map(function (x) {
              return '<option value="' + F.esc(x.code) + '">' + F.esc(x.code + " " + x.name) + "</option>";
            }).join("") + "</select>" +
            '<label>数量</label><input id="ndQty" type="number" value="1">' +
            '<label>工序</label><input id="ndProc" placeholder="如 整机装配">' +
            '<label>说明</label><input id="ndRemark" placeholder="选填"></div>',
            '<button class="btn" id="ndOk">登记</button>');
          document.getElementById("ndOk").addEventListener("click", function () {
            F.api("POST", "/api/defects", {
              woNo: document.getElementById("ndWo").value,
              defectCode: document.getElementById("ndCode").value,
              qty: Number(document.getElementById("ndQty").value || 0),
              process: document.getElementById("ndProc").value,
              remark: document.getElementById("ndRemark").value
            }).then(function () {
              F.closeDialog();
              F.toast("不良已登记", "ok");
              tab = "defect";
              paintTabs();
              loadKpi();
              loadBody();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    });

    loadKpi();
    paintTabs();
    loadBody();
  });
})(window, document);
