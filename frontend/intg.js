/* 飞驰 MES · 集成中心（API Key / Webhook / 投递 / 映射 / 增量同步） */
(function (window, document) {
  "use strict";
  var F = window.F;
  var tab = "overview";

  F.register("integration", function () {
    var view = document.getElementById("view");
    if (!F.isAdmin()) {
      view.innerHTML = '<div class="panel"><div class="panel-title">集成中心</div>' +
        '<div class="panel-body">' + F.empty("集成配置仅系统管理员可见（当前角色：" +
          (F.me().roleLabel || "—") + "）。如需对接，请联系管理员分配 API Key。") + "</div></div>";
      F.setStatus("集成中心 · 需要管理员权限");
      return;
    }

    view.innerHTML = '<div class="panel"><div class="panel-title">集成中心' +
      '<span class="panel-actions small muted">REST / Webhook / 增量同步 三通道</span></div>' +
      '<div class="panel-body"><div id="igTabs"></div><div id="igBody">加载中…</div></div></div>';

    function paint() {
      document.getElementById("igTabs").innerHTML =
        [["overview", "集成总览"], ["keys", "API Key"], ["hooks", "Webhook"],
          ["deliv", "投递记录"], ["map", "外部 ID 映射"], ["sync", "增量同步"]].map(function (t) {
          return '<button class="chip' + (tab === t[0] ? " on" : "") + '" data-tab="' + t[0] + '">' +
            t[1] + "</button>";
        }).join("");
      document.querySelectorAll("#igTabs [data-tab]").forEach(function (b) {
        b.addEventListener("click", function () { tab = b.getAttribute("data-tab"); paint(); load(); });
      });
    }

    function load() {
      if (tab === "overview") {
        F.api("GET", "/api/integration/overview").then(function (d) {
          document.getElementById("igBody").innerHTML =
            '<div class="kpi-grid six">' +
            '<div class="kpi"><div class="k-label">启用 Key</div><div class="k-value">' + d.keys +
            '</div><div class="k-sub">读写 / 只读分离</div></div>' +
            '<div class="kpi"><div class="k-label">Webhook 订阅</div><div class="k-value">' + d.webhooks +
            '</div><div class="k-sub">HMAC 签名</div></div>' +
            '<div class="kpi gold"><div class="k-label">投递总数</div><div class="k-value">' + d.deliveries +
            '</div><div class="k-sub">失败 ' + d.deliveryFailed + " 条</div></div>" +
            '<div class="kpi"><div class="k-label">变更事件</div><div class="k-value">' + d.changes +
            '</div><div class="k-sub">最近 ' + F.esc(d.lastChange || "—") + "</div></div>" +
            '<div class="kpi"><div class="k-label">外部映射</div><div class="k-value">' + d.mappings +
            '</div><div class="k-sub">ERP / WMS / QMS</div></div>' +
            '<div class="kpi green"><div class="k-label">可同步对象</div><div class="k-value">' +
            d.objects.length + '</div><div class="k-sub">' + F.esc(d.objects.join("、")) + "</div></div></div>" +
            '<div class="section-title">数据规模</div>' +
            F.table([
              { label: "对象", render: function (r) { return F.esc(r.k); } },
              { label: "数量", num: true, render: function (r) { return F.int(r.v); } }
            ], [
              { k: "生产工单", v: d.counts.work_orders }, { k: "批次", v: d.counts.batches },
              { k: "检验单", v: d.counts.inspections }, { k: "不良记录", v: d.counts.defects },
              { k: "设备", v: d.counts.equipment }
            ]) +
            '<div class="section-title">对接方式</div>' +
            '<div class="small muted" style="line-height:2">' +
            "① REST：`X-Fc-Key: fck_xxx` 调用 /api/*，读写分离、限流 240 次/分钟；<br>" +
            "② Webhook：工单状态、报工、检验、设备状态等事件实时推送，`X-Fc-Signature` HMAC-SHA256 验签；<br>" +
            "③ 增量同步：`GET /api/sync/changes?since={cursor}&object=work_order` 拉取变更，cursor 递增；<br>" +
            "④ 幂等：写接口带 `Idempotency-Key` 头，重复请求直接回放首次响应。</div>";
          F.setStatus("集成总览 · " + d.changes + " 条变更事件");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else if (tab === "keys") {
        F.api("GET", "/api/integration/keys").then(function (d) {
          document.getElementById("igBody").innerHTML =
            '<div class="panel-actions" style="margin-bottom:8px">' +
            '<button class="btn sm" id="ikNew">新建 API Key</button>' +
            '<span class="small muted" style="margin-left:8px">明文只在创建时返回一次</span></div>' +
            F.table([
              { label: "名称", key: "name" },
              { label: "前缀", render: function (r) { return '<span class="mono small">' + F.esc(r.prefix) + "…</span>"; } },
              { label: "权限", render: function (r) { return F.tag(r.scope === "write" ? "读写" : "只读",
                r.scope === "write" ? "gold" : "gray"); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "最近使用", render: function (r) { return '<span class="small muted">' +
                F.esc(r.lastUsedAt || "—") + "</span>"; } },
              { label: "创建时间", render: function (r) { return '<span class="small muted">' + F.esc(r.createdAt) + "</span>"; } },
              { label: "", render: function (r) {
                return r.status === "启用" ? '<button class="btn sm danger" data-revoke="' + r.id +
                  '">吊销</button>' : "";
              } }
            ], d.list, { empty: "尚未创建 Key" });
          document.getElementById("ikNew").addEventListener("click", function () {
            F.dialog("新建 API Key",
              '<div class="form-grid"><label>名称</label><input id="ikName" placeholder="如 ERP 生产订单同步">' +
              '<label>权限</label><select id="ikScope"><option value="read">只读（GET）</option>' +
              '<option value="write">读写（含写接口）</option></select></div>',
              '<button class="btn" id="ikOk">创建</button>');
            document.getElementById("ikOk").addEventListener("click", function () {
              F.api("POST", "/api/integration/keys", {
                name: document.getElementById("ikName").value.trim(),
                scope: document.getElementById("ikScope").value
              }).then(function (x) {
                F.dialog("请保存 Key（只显示一次）",
                  '<div class="small muted">' + F.esc(x.notice) + "</div>" +
                  '<div class="key-box mono">' + F.esc(x.key) + "</div>" +
                  '<div class="small muted" style="margin-top:8px">调用示例：<br>' +
                  '<span class="mono">curl -H "X-Fc-Key: ' + F.esc(x.key) + '" \\<br>' +
                  "  http://host:8021/api/orders</span></div>",
                  '<button class="btn" onclick="F.closeDialog()">我已保存</button>');
                load();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          document.querySelectorAll("[data-revoke]").forEach(function (b) {
            b.addEventListener("click", function () {
              if (!window.confirm("确定吊销该 Key？吊销后调用立即失效。")) return;
              F.api("DELETE", "/api/integration/keys/" + b.getAttribute("data-revoke")).then(function () {
                F.toast("Key 已吊销", "ok");
                load();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          F.setStatus("API Key · 启用 " + d.active + " 个");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else if (tab === "hooks") {
        F.api("GET", "/api/integration/webhooks").then(function (d) {
          document.getElementById("igBody").innerHTML =
            '<div class="panel-actions" style="margin-bottom:8px">' +
            '<button class="btn sm" id="iwNew">新建 Webhook</button></div>' +
            F.table([
              { label: "名称", key: "name" },
              { label: "回调地址", render: function (r) { return '<span class="mono small">' + F.esc(r.url) + "</span>"; } },
              { label: "事件", render: function (r) { return '<span class="small">' + F.esc(r.events) + "</span>"; } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "投递", num: true, render: function (r) { return r.deliveries; } },
              { label: "", render: function (r) {
                return '<button class="btn sm" data-test="' + r.id + '">测试</button> ' +
                  '<button class="btn sm danger" data-del="' + r.id + '">删除</button>';
              } }
            ], d.list, { empty: "尚未配置 Webhook" });
          document.getElementById("iwNew").addEventListener("click", function () {
            F.dialog("新建 Webhook",
              '<div class="form-grid"><label>名称</label><input id="iwName" placeholder="如 MES → ERP">' +
              '<label>回调地址</label><input id="iwUrl" placeholder="https://erp.example.com/hooks/mes">' +
              '<label>事件</label><input id="iwEvents" value="*" placeholder="wo.reported,wo.stage_changed 或 *">' +
              "</div><div class=\"small muted\" style=\"margin-top:8px\">事件：wo.created / wo.stage_changed / " +
              "wo.reported / wo.stock_in / inspection.created / defect.created / equipment.status_changed / " +
              "maintenance.finished / andon.created</div>",
              '<button class="btn" id="iwOk">创建</button>');
            document.getElementById("iwOk").addEventListener("click", function () {
              F.api("POST", "/api/integration/webhooks", {
                name: document.getElementById("iwName").value.trim(),
                url: document.getElementById("iwUrl").value.trim(),
                events: document.getElementById("iwEvents").value.trim() || "*"
              }).then(function (x) {
                F.dialog("Webhook 已创建",
                  '<div class="small muted">' + F.esc(x.notice) + "</div>" +
                  '<div class="key-box mono">' + F.esc(x.secret) + "</div>" +
                  '<div class="small muted" style="margin-top:8px">验签：HMAC-SHA256(secret, timestamp + "." + rawBody)，' +
                  '比对 <span class="mono">X-Fc-Signature</span>，并校验时间戳 5 分钟内。</div>',
                  '<button class="btn" onclick="F.closeDialog()">我已保存</button>');
                load();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          document.querySelectorAll("[data-test]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("POST", "/api/integration/webhooks/" + b.getAttribute("data-test") + "/test", {})
                .then(function () {
                  F.toast("测试事件已入队，可在投递记录查看结果", "ok");
                  tab = "deliv";
                  paint();
                  load();
                }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          document.querySelectorAll("[data-del]").forEach(function (b) {
            b.addEventListener("click", function () {
              if (!window.confirm("删除订阅及其投递记录？")) return;
              F.api("DELETE", "/api/integration/webhooks/" + b.getAttribute("data-del")).then(function () {
                F.toast("已删除", "ok");
                load();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          F.setStatus("Webhook · " + (d.list || []).length + " 个订阅");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else if (tab === "deliv") {
        F.api("GET", "/api/integration/deliveries").then(function (d) {
          document.getElementById("igBody").innerHTML =
            '<div class="small muted" style="margin-bottom:6px">共 ' + d.total + " 条 · 失败 " +
            d.failed + " 条（失败自动退避 30s / 60s / 120s，最多 3 次）</div>" +
            F.table([
              { label: "ID", render: function (r) { return '<span class="mono small">#' + r.id + "</span>"; } },
              { label: "事件", render: function (r) { return F.tag(r.event, "blue"); } },
              { label: "状态", render: function (r) { return F.tag(r.status); } },
              { label: "尝试", num: true, render: function (r) { return r.attempts; } },
              { label: "HTTP", num: true, render: function (r) { return r.httpCode || "—"; } },
              { label: "错误", render: function (r) { return '<span class="small muted">' +
                F.esc(r.error || "—") + "</span>"; } },
              { label: "创建", render: function (r) { return '<span class="small">' + F.esc(r.createdAt) + "</span>"; } },
              { label: "", render: function (r) {
                return '<button class="btn sm" data-retry="' + r.id + '">重投</button>';
              } }
            ], d.list, { empty: "暂无投递" });
          document.querySelectorAll("[data-retry]").forEach(function (b) {
            b.addEventListener("click", function () {
              F.api("POST", "/api/integration/deliveries/" + b.getAttribute("data-retry") + "/retry", {})
                .then(function () {
                  F.toast("已重新入队", "ok");
                  setTimeout(load, 1200);
                }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          F.setStatus("投递记录 · " + d.total + " 条");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else if (tab === "map") {
        F.api("GET", "/api/integration/mappings").then(function (d) {
          document.getElementById("igBody").innerHTML =
            '<div class="panel-actions" style="margin-bottom:8px">' +
            '<button class="btn sm" id="imNew">绑定外部 ID</button></div>' +
            F.table([
              { label: "对象类型", render: function (r) { return F.tag(r.objType, "gray"); } },
              { label: "本系统单号", render: function (r) { return '<span class="mono small">' + F.esc(r.localNo) + "</span>"; } },
              { label: "外部 ID", render: function (r) { return '<span class="mono small">' + F.esc(r.externalId) + "</span>"; } },
              { label: "系统", key: "system" },
              { label: "建立时间", render: function (r) { return '<span class="small muted">' + F.esc(r.createdAt) + "</span>"; } }
            ], d.list, { empty: "暂无映射" });
          document.getElementById("imNew").addEventListener("click", function () {
            F.dialog("绑定外部 ID",
              '<div class="form-grid"><label>对象类型</label><select id="imType">' +
              "<option>work_order</option><option>batch</option><option>material</option>" +
              "<option>inspection</option></select>" +
              '<label>本系统单号</label><input id="imLocal" placeholder="WO20261020-0001">' +
              '<label>外部 ID</label><input id="imExt" placeholder="ERP-WO-9001">' +
              '<label>来源系统</label><input id="imSys" value="ERP"></div>',
              '<button class="btn" id="imOk">保存</button>');
            document.getElementById("imOk").addEventListener("click", function () {
              F.api("POST", "/api/integration/mappings", {
                objType: document.getElementById("imType").value,
                localNo: document.getElementById("imLocal").value.trim(),
                externalId: document.getElementById("imExt").value.trim(),
                system: document.getElementById("imSys").value.trim()
              }).then(function () {
                F.closeDialog();
                F.toast("映射已保存", "ok");
                load();
              }).catch(function (e) { F.toast(e.message, "err"); });
            });
          });
          F.setStatus("外部 ID 映射 · " + d.total + " 条");
        }).catch(function (e) { F.toast(e.message, "err"); });
      } else {
        F.api("GET", "/api/sync/changes?since=0&limit=30").then(function (d) {
          document.getElementById("igBody").innerHTML =
            '<div class="small muted" style="margin-bottom:8px">游标 ' + d.cursor + " · 本次 " +
            d.count + " 条 · " + (d.hasMore ? "还有更多" : "已到末尾") +
            '　<a class="btn sm" id="syNext" href="javascript:void 0">拉取后续</a></div>' +
            F.table([
              { label: "ID", render: function (r) { return '<span class="mono small">#' + r.id + "</span>"; } },
              { label: "对象", render: function (r) { return F.tag(r.objType, "gray"); } },
              { label: "单号", render: function (r) { return '<span class="mono small">' + F.esc(r.objNo) + "</span>"; } },
              { label: "操作", render: function (r) { return F.esc(r.op); } },
              { label: "操作人", key: "actor" },
              { label: "时间", render: function (r) { return '<span class="small">' + F.esc(r.changedAt) + "</span>"; } },
              { label: "载荷", render: function (r) {
                return '<span class="small muted mono">' + F.esc(JSON.stringify(r.payload).slice(0, 70)) + "</span>";
              } }
            ], d.changes, { empty: "暂无变更" });
          var cursor = d.cursor;
          document.getElementById("syNext").addEventListener("click", function () {
            F.api("GET", "/api/sync/changes?since=" + cursor + "&limit=30").then(function (x) {
              cursor = x.cursor;
              F.toast("已拉取 " + x.count + " 条，游标 " + x.cursor, "ok");
              load();
            }).catch(function (e) { F.toast(e.message, "err"); });
          });
          F.setStatus("增量同步 · 游标 " + d.cursor);
        }).catch(function (e) { F.toast(e.message, "err"); });
      }
    }

    paint();
    load();
  });
})(window, document);
