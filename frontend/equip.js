/* 飞驰 MES · 设备台账（OEE）与保养点检 */
(function (window, document) {
  "use strict";
  var F = window.F;
  var STATES = ["全部", "运行", "待机", "故障", "保养", "停机"];

  /* ---------------------------------------------------------- 设备台账 */
  F.register("equipment", function () {
    var st = { status: "全部", kw: "" };
    document.getElementById("view").innerHTML =
      '<div class="panel"><div class="panel-title">设备台账与 OEE' +
      '<span class="panel-actions">' +
      '<input id="eKw" placeholder="设备编码 / 名称 / 型号" style="width:200px;margin-right:6px">' +
      '<button class="btn sm" id="eSearch">查询</button> ' +
      '<a class="btn sm" href="#maint">保养点检</a></span></div>' +
      '<div class="panel-body"><div id="eKpi"></div><div id="eChips"></div><div id="eList">加载中…</div></div></div>';

    function load() {
      F.api("GET", "/api/equipment?" + F.qs({ status: st.status, kw: st.kw })).then(function (d) {
        var list = d.list || [];
        var avg = list.length ? list.reduce(function (a, x) { return a + x.oee.oee; }, 0) / list.length : 0;
        var run = list.filter(function (x) { return x.status === "运行"; }).length;
        var bad = list.filter(function (x) { return x.status === "故障" || x.status === "停机"; }).length;
        var maint = list.filter(function (x) { return x.maintState === "逾期" || x.maintState === "临期"; }).length;
        document.getElementById("eKpi").innerHTML =
          '<div class="kpi-grid four" style="margin-bottom:10px">' +
          '<div class="kpi"><div class="k-label">设备总数</div><div class="k-value">' + d.total +
          '</div><div class="k-sub">运行 ' + run + " 台</div></div>" +
          '<div class="kpi"><div class="k-label">平均 OEE（近 7 天）</div><div class="k-value">' +
          F.pct(avg, 1) + '</div><div class="k-sub">目标 85%</div></div>' +
          '<div class="kpi red"><div class="k-label">故障 / 停机</div><div class="k-value">' + bad +
          '</div><div class="k-sub">需处理</div></div>' +
          '<div class="kpi gold"><div class="k-label">保养临期 / 逾期</div><div class="k-value">' + maint +
          '</div><div class="k-sub">按保养计划</div></div></div>';
        document.getElementById("eChips").innerHTML = F.chips(STATES, st.status);
        document.getElementById("eList").innerHTML = F.table([
          { label: "设备", render: function (r) { return '<b>' + F.esc(r.name) + '</b><div class="muted small mono">' +
            F.esc(r.code) + " · " + F.esc(r.model) + "</div>"; } },
          { label: "类型", render: function (r) { return F.tag(r.type, "gray"); } },
          { label: "产线 / 工位", render: function (r) { return F.esc(r.line) +
            '<div class="muted small">' + F.esc(r.station) + "</div>"; } },
          { label: "状态", render: function (r) { return F.tag(r.status); } },
          { label: "OEE", num: true, render: function (r) {
            return '<b>' + F.pct(r.oee.oee, 1) + "</b> " + F.tag(r.oeeLevel);
          } },
          { label: "可用率", num: true, render: function (r) { return F.pct(r.oee.availability, 0); } },
          { label: "性能率", num: true, render: function (r) { return F.pct(r.oee.performance, 0); } },
          { label: "质量率", num: true, render: function (r) { return F.pct(r.oee.quality, 1); } },
          { label: "下次保养", render: function (r) { return F.esc(r.nextMaintAt) + " " + F.tag(r.maintState); } }
        ], list, { empty: "没有匹配设备", click: function (r) { return r.code; } });
        F.bindRows(document, function (code) { detail(code); });
        document.querySelectorAll("#eChips .chip").forEach(function (c) {
          c.addEventListener("click", function () { st.status = c.getAttribute("data-st"); load(); });
        });
        F.setStatus("设备台账 · " + d.total + " 台 · 平均 OEE " + F.pct(avg, 1));
        F.setSide('<div class="side-block"><div class="hd">OEE 口径</div><div class="bd small muted" ' +
          'style="line-height:1.9">OEE = 可用率 × 性能率 × 质量率。<br>' +
          "可用率 = 运行时间 ÷ 计划开机；<br>性能率 = 理论节拍 × 产出 ÷ 运行时间；<br>" +
          "质量率 = 良品 ÷ 产出。</div></div>" +
          '<div class="side-block"><div class="hd">状态计数</div><div class="bd">' +
          Object.keys(d.statusDist || {}).map(function (k) {
            return F.kv(k, d.statusDist[k] + " 台");
          }).join("") + "</div></div>");
      }).catch(function (e) { F.toast(e.message, "err"); });
    }

    document.getElementById("eSearch").addEventListener("click", function () {
      st.kw = document.getElementById("eKw").value.trim();
      load();
    });
    document.getElementById("eKw").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { st.kw = e.target.value.trim(); load(); }
    });
    load();
  });

  function detail(code) {
    F.api("GET", "/api/equipment/" + encodeURIComponent(code)).then(function (d) {
      var o = d.oee14 || d.oee;
      var logs = F.table([
        { label: "状态", render: function (r) { return F.tag(r.status); } },
        { label: "原因", key: "reason" },
        { label: "时长", num: true, render: function (r) { return r.minutes ? F.hour(r.minutes) : "进行中"; } },
        { label: "开始", render: function (r) { return '<span class="small">' + F.esc(r.startAt) + "</span>"; } },
        { label: "结束", render: function (r) { return '<span class="small">' + F.esc(r.endAt || "—") + "</span>"; } }
      ], d.logs || [], { empty: "无状态记录" });
      var checks = F.table([
        { label: "点检单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "类型", key: "type" },
        { label: "结论", render: function (r) { return F.tag(r.result); } },
        { label: "点检人", key: "checker" },
        { label: "时间", render: function (r) { return '<span class="small">' + F.esc(r.checkedAt) + "</span>"; } }
      ], d.checks || [], { empty: "无点检记录" });
      var maint = F.table([
        { label: "工单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
        { label: "类型", key: "type" },
        { label: "原因", key: "reason" },
        { label: "状态", render: function (r) { return F.tag(r.status); } },
        { label: "停机", num: true, render: function (r) { return r.downtimeMin ? F.hour(r.downtimeMin) : "—"; } },
        { label: "费用", num: true, render: function (r) { return F.num(r.cost, 0); } }
      ], d.maint || [], { empty: "无保养工单" });

      var body = '<div class="detail-head"><b>' + F.esc(d.name) + '</b><span class="muted small mono">' +
        F.esc(d.code) + " · " + F.esc(d.vendor) + " " + F.esc(d.model) + "</span>" +
        '<span class="spacer"></span>' + F.tag(d.status) + "</div>" +
        '<div class="oee-flex" style="margin:10px 0">' + F.ring(o.oee, { label: "OEE" }) +
        '<div class="oee-legend">可用率 <b>' + F.pct(o.availability, 1) + "</b>（运行 " + F.hour(o.runMin) +
        " / 计划 " + F.hour(o.planMin) + "，损失 " + F.hour(o.downMin) + "）<br>" +
        "性能率 <b>" + F.pct(o.performance, 1) + "</b>（产出 " + F.qty(o.output) + " 件）<br>" +
        "质量率 <b>" + F.pct(o.quality, 1) + "</b>（良品 " + F.qty(o.good) + " 件）<br>" +
        "OEE 目标 " + F.pct(d.oeeTarget, 0) + " · " + F.tag(d.oeeLevel) + "</div></div>" +
        '<div class="section-title">近 14 天 OEE</div>' +
        F.lineChart([{ name: "OEE", data: (d.daily || []).map(function (x) { return x.oee * 100; }) }],
          { labels: (d.daily || []).map(function (x) { return x.day.slice(3); }), height: 150,
            colors: ["#1f7a8c"], zero: false }) +
        '<div class="section-title">停机原因 TOP</div>' + F.table([
          { label: "原因", key: "reason" },
          { label: "时长", num: true, render: function (r) { return F.hour(r.minutes); } },
          { label: "占比", num: true, render: function (r) { return F.pct(r.share, 1); } }
        ], d.downtimeTop || [], { empty: "暂无停机" }) +
        '<div class="section-title">状态记录</div>' + logs +
        '<div class="section-title">点检记录</div>' + checks +
        '<div class="section-title">保养工单</div>' + maint;

      var foot = "";
      if (F.can("equip")) {
        foot = '<button class="btn sm" data-es="故障">报修</button> ' +
          '<button class="btn sm" data-es="保养">转保养</button> ' +
          '<button class="btn sm primary" data-es="运行">恢复运行</button> ' +
          '<button class="btn sm" id="edMaint">新建保养工单</button>';
      }
      F.dialog("设备 " + d.code, body, foot || '<span class="small muted">当前角色只读</span>');
      document.querySelectorAll("[data-es]").forEach(function (b) {
        b.addEventListener("click", function () {
          var target = b.getAttribute("data-es");
          var reason = target === "运行" ? "修复复位" :
            window.prompt("请输入" + target + "原因", target === "故障" ? "设备异常停机" : "计划保养");
          if (!reason) return;
          F.api("POST", "/api/equipment/" + d.code + "/status", { status: target, reason: reason })
            .then(function () {
              F.closeDialog();
              F.toast("设备状态已切换为「" + target + "」", "ok");
              F.reload().then(function () { detail(d.code); });
            }).catch(function (e) { F.toast(e.message, "err"); });
        });
      });
      var mb = document.getElementById("edMaint");
      if (mb) mb.addEventListener("click", function () {
        F.api("POST", "/api/maint/orders", { equipment: d.code, type: "计划保养", reason: "设备详情发起" })
          .then(function (x) {
            F.closeDialog();
            F.toast("已创建保养工单 " + x.no, "ok");
            F.reload().then(function () { F.go("maint"); });
          }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }).catch(function (e) { F.toast(e.message, "err"); });
  }

  /* ---------------------------------------------------------- 保养点检 */
  var tab = "plan";

  F.register("maint", function () {
    document.getElementById("view").innerHTML =
      '<div class="panel"><div class="panel-title">保养与点检' +
      '<span class="panel-actions"><button class="btn sm" id="mnNew">新建保养工单</button> ' +
      '<button class="btn sm" id="mnCheck">提交点检</button></span></div>' +
      '<div class="panel-body"><div id="mnTabs"></div><div id="mnBody">加载中…</div></div></div>';

    function paint() {
      document.getElementById("mnTabs").innerHTML =
        [["plan", "保养计划"], ["order", "保养工单"], ["check", "点检记录"]].map(function (t) {
          return '<button class="chip' + (tab === t[0] ? " on" : "") + '" data-tab="' + t[0] + '">' +
            t[1] + "</button>";
        }).join("");
      document.querySelectorAll("#mnTabs [data-tab]").forEach(function (b) {
        b.addEventListener("click", function () { tab = b.getAttribute("data-tab"); paint(); load(); });
      });
    }

    function load() {
      if (tab === "plan") {
        F.api("GET", "/api/maint/plans").then(function (d) {
          document.getElementById("mnBody").innerHTML =
            '<div class="small muted" style="margin-bottom:6px">共 ' + d.total + " 项计划 · 临期/逾期 " +
            d.due + " 项</div>" + F.table([
              { label: "计划", render: function (r) { return '<span class="mono small">' + F.esc(r.code) + "</span>"; } },
              { label: "设备", render: function (r) { return F.esc(r.equipName) +
                '<div class="muted small mono">' + F.esc(r.equipment) + "</div>"; } },
              { label: "类型", render: function (r) { return F.tag(r.type, "blue"); } },
              { label: "周期", num: true, render: function (r) { return r.cycleDays + " 天"; } },
              { label: "上次", key: "lastAt" },
              { label: "下次", render: function (r) { return F.esc(r.nextAt) + " " + F.tag(r.state); } },
              { label: "负责人", key: "owner" }
            ], d.list, { empty: "暂无保养计划" });
          F.setStatus("保养计划 · " + d.total + " 项");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else if (tab === "order") {
        F.api("GET", "/api/maint/orders").then(function (d) {
          document.getElementById("mnBody").innerHTML =
            '<div class="small muted" style="margin-bottom:6px">共 ' + d.total + " 单 · 未完成 " +
            d.open + " 单</div>" + F.table([
              { label: "工单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "设备", render: function (r) { return F.esc(r.equipName) +
                '<div class="muted small mono">' + F.esc(r.equipment) + "</div>"; } },
              { label: "类型 / 原因", render: function (r) { return F.esc(r.type) +
                '<div class="muted small">' + F.esc(r.reason) + "</div>"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "计划", key: "planAt" },
              { label: "停机", num: true, render: function (r) { return r.downtimeMin ? F.hour(r.downtimeMin) : "—"; } },
              { label: "费用", num: true, render: function (r) { return F.num(r.cost, 0); } },
              { label: "", render: function (r) {
                if (r.status === "已完成" || !F.can("equip")) return "";
                return '<button class="btn sm" data-fin="' + F.esc(r.no) + '">完成</button>';
              } }
            ], d.list, { empty: "暂无保养工单" });
          document.querySelectorAll("[data-fin]").forEach(function (b) {
            b.addEventListener("click", function () { finish(b.getAttribute("data-fin")); });
          });
          F.setStatus("保养工单 · " + d.total + " 单");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else {
        F.api("GET", "/api/equip/checks").then(function (d) {
          document.getElementById("mnBody").innerHTML =
            '<div class="small muted" style="margin-bottom:6px">共 ' + d.total + " 条 · 异常 " +
            d.abnormal + " 条</div>" + F.table([
              { label: "点检单", render: function (r) { return '<span class="mono small">' + F.esc(r.no) + "</span>"; } },
              { label: "设备", render: function (r) { return F.esc(r.equipName) +
                '<div class="muted small mono">' + F.esc(r.equipment) + "</div>"; } },
              { label: "类型", key: "type" },
              { label: "结论", render: function (r) { return F.tag(r.result); } },
              { label: "点检项", render: function (r) {
                return (r.items || []).map(function (i) {
                  return '<span class="tag ' + (i.result === "正常" ? "green" : "red") + '">' +
                    F.esc(i.item) + "</span>";
                }).join(" ");
              } },
              { label: "点检人", key: "checker" },
              { label: "时间", render: function (r) { return '<span class="small">' + F.esc(r.checkedAt) + "</span>"; } }
            ], d.list, { empty: "暂无点检记录" });
          F.setStatus("点检记录 · " + d.total + " 条");
        }).catch(function (e) { F.toast(e.message, "err"); });
      }
    }

    function finish(no) {
      F.dialog("完成保养 " + no,
        '<div class="form-grid"><label>停机时长(分)</label><input id="mfDown" type="number" value="60">' +
        '<label>费用(元)</label><input id="mfCost" type="number" value="800">' +
        '<label>说明</label><input id="mfRemark" placeholder="保养内容"></div>',
        '<button class="btn primary" id="mfOk">确认完成</button>');
      document.getElementById("mfOk").addEventListener("click", function () {
        F.api("POST", "/api/maint/orders/" + encodeURIComponent(no) + "/finish", {
          downtimeMin: Number(document.getElementById("mfDown").value || 0),
          cost: Number(document.getElementById("mfCost").value || 0),
          remark: document.getElementById("mfRemark").value
        }).then(function () {
          F.closeDialog();
          F.toast("保养已完成，设备已恢复运行", "ok");
          F.reload().then(load);
        }).catch(function (e) { F.toast(e.message, "err"); });
      });
    }

    document.getElementById("mnNew").addEventListener("click", function () {
      if (!F.can("equip")) return F.toast("当前角色无设备权限", "err");
      F.api("GET", "/api/equipment").then(function (d) {
        F.dialog("新建保养工单",
          '<div class="form-grid"><label>设备</label><select id="mnEq">' +
          (d.list || []).map(function (e) {
            return '<option value="' + F.esc(e.code) + '">' + F.esc(e.code + " " + e.name) + "</option>";
          }).join("") + "</select>" +
          '<label>类型</label><select id="mnType"><option>计划保养</option><option>故障维修</option>' +
          "<option>点检异常</option></select>" +
          '<label>计划日期</label><input id="mnDate" type="date" value="' + F.today() + '">' +
          '<label>原因</label><input id="mnReason" placeholder="如 主轴异响"></div>',
          '<button class="btn" id="mnOk">创建</button>');
        document.getElementById("mnOk").addEventListener("click", function () {
          F.api("POST", "/api/maint/orders", {
            equipment: document.getElementById("mnEq").value,
            type: document.getElementById("mnType").value,
            planAt: document.getElementById("mnDate").value,
            reason: document.getElementById("mnReason").value
          }).then(function (x) {
            F.closeDialog();
            F.toast("已创建 " + x.no, "ok");
            tab = "order";
            paint();
            load();
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    });

    document.getElementById("mnCheck").addEventListener("click", function () {
      if (!F.can("equip")) return F.toast("当前角色无设备权限", "err");
      F.api("GET", "/api/equipment").then(function (d) {
        F.dialog("设备点检",
          '<div class="form-grid"><label>设备</label><select id="ckEq">' +
          (d.list || []).map(function (e) {
            return '<option value="' + F.esc(e.code) + '">' + F.esc(e.code + " " + e.name) + "</option>";
          }).join("") + "</select>" +
          '<label>类型</label><select id="ckType"><option>日常点检</option><option>周检</option>' +
          "<option>月检</option></select>" +
          '<label>油位</label><select id="ckOil"><option>正常</option><option>异常</option></select>' +
          '<label>气压</label><select id="ckAir"><option>正常</option><option>异常</option></select>' +
          '<label>安全门</label><select id="ckDoor"><option>正常</option><option>异常</option></select>' +
          '<label>说明</label><input id="ckRemark" placeholder="选填"></div>' +
          '<div class="small muted" style="margin-top:8px">任一项异常将把设备置为「故障」并提示处理。</div>',
          '<button class="btn primary" id="ckOk">提交</button>');
        document.getElementById("ckOk").addEventListener("click", function () {
          F.api("POST", "/api/equip/checks", {
            equipment: document.getElementById("ckEq").value,
            type: document.getElementById("ckType").value,
            items: [
              { item: "油位", result: document.getElementById("ckOil").value },
              { item: "气压", result: document.getElementById("ckAir").value },
              { item: "安全门", result: document.getElementById("ckDoor").value }
            ],
            remark: document.getElementById("ckRemark").value
          }).then(function (x) {
            F.closeDialog();
            F.toast("点检已提交：" + x.result, x.result === "正常" ? "ok" : "err");
            tab = "check";
            paint();
            F.reload().then(load);
          }).catch(function (e) { F.toast(e.message, "err"); });
        });
      }).catch(function (e) { F.toast(e.message, "err"); });
    });

    paint();
    load();
  });
})(window, document);
