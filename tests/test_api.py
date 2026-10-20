# -*- coding: utf-8 -*-
"""飞驰 MES · REST 接口测试（独立临时库 + 服务进程）"""
import json
import time
import urllib.error
import urllib.request

import pytest


class TestAuth:
    def test_login_ok(self, api):
        d = api.login("admin")
        assert d["role"] == "admin" and d["token"]

    def test_login_bad(self, api):
        api.err("POST", "/api/auth/login", {"username": "admin", "password": "x"}, 401)

    def test_me_requires_token(self, api):
        api.token = None
        api.err("GET", "/api/auth/me", code=401)

    def test_me(self, api):
        api.login("admin")
        me = api.ok("GET", "/api/auth/me")
        assert me["username"] == "admin" and "write" in me["perms"]

    def test_logout(self, api):
        d = api.login("admin")
        api.ok("POST", "/api/auth/logout", {}, token=d["token"])

    def test_role_account(self, api):
        d = api.login("liyun")
        assert d["role"] == "planner"


class TestBootstrap:
    def test_bootstrap(self, api):
        api.login("admin")
        b = api.ok("GET", "/api/bootstrap")
        assert "kpi" in b and len(b["trend"]) == 14
        assert b["kpi"]["wip"] >= 1
        assert len(b["lines"]) >= 5
        assert len(b["rules"]) == 8

    def test_health_open(self, api):
        st, r = api.call("GET", "/api/health")
        assert st == 200 and r["data"]["workOrders"] >= 30


class TestMaster:
    def test_workshops(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/workshops")
        assert len(d["list"]) == 4

    def test_lines(self, api):
        d = api.ok("GET", "/api/lines")
        assert d["list"][0]["code"].startswith("LN-")

    def test_stations_filter(self, api):
        d = api.ok("GET", "/api/stations?line=LN-201")
        assert all(x["line"] == "LN-201" for x in d["list"])

    def test_teams(self, api):
        d = api.ok("GET", "/api/teams")
        assert len(d["list"]) >= 5

    def test_materials(self, api):
        d = api.ok("GET", "/api/materials")
        assert d["total"] >= 24 and d["summary"]["finished"] >= 6

    def test_material_type_filter(self, api):
        d = api.ok("GET", "/api/materials?type=成品")
        assert all(x["type"] == "成品" for x in d["list"])

    def test_material_create_and_dup(self, api):
        uniq = "MT-9%03d" % (int(time.time()) % 1000)
        d = api.ok("POST", "/api/materials", {"code": uniq, "name": "接口测试物料", "unit": "件",
                                              "type": "原材料"})
        assert d["created"]
        api.err("POST", "/api/materials", {"code": uniq, "name": "重复"}, 409)

    def test_material_detail(self, api):
        d = api.ok("GET", "/api/materials/MT-3001")
        assert d["bom"]["items"] and d["routing"]["steps"]

    def test_material_update(self, api):
        d = api.ok("PUT", "/api/materials/MT-1001", {"safetyStock": 150})
        assert d["updated"]
        assert api.ok("GET", "/api/materials/MT-1001")["material"]["safetyStock"] == 150

    def test_boms(self, api):
        d = api.ok("GET", "/api/boms")
        assert d["total"] >= 10
        det = api.ok("GET", "/api/boms/" + d["list"][0]["code"])
        assert len(det["items"]) >= 2

    def test_routings(self, api):
        d = api.ok("GET", "/api/routings")
        assert d["total"] >= 10
        det = api.ok("GET", "/api/routings/" + d["list"][0]["code"])
        assert det["balance"] > 0 and det["bottleneck"] > 0


class TestOrderFlow:
    @pytest.fixture(scope="class")
    def wo(self, api):
        api.login("admin")
        d = api.ok("POST", "/api/orders", {"materialCode": "MT-3001", "qty": 50, "line": "LN-301",
                                           "planStart": "2026-10-21", "customer": "接口测试"})
        return d["no"]

    def test_create(self, api, wo):
        assert wo.startswith("WO")
        d = api.ok("GET", "/api/orders/" + wo)
        assert d["status"] == "草稿" and len(d["operations"]) >= 4 and len(d["materials"]) >= 4

    def test_create_bad_material(self, api):
        api.err("POST", "/api/orders", {"materialCode": "NOPE", "qty": 1}, 404)

    def test_create_zero_qty(self, api):
        api.err("POST", "/api/orders", {"materialCode": "MT-3001", "qty": 0}, 400)

    def test_kit(self, api, wo):
        d = api.ok("GET", "/api/orders/%s/kit" % wo)
        assert 0 <= d["rate"] <= 1 and d["total"] >= 3

    def test_cannot_start_before_release(self, api, wo):
        r = api.err("POST", "/api/orders/%s/stage" % wo, {"target": "已开工"}, 400)
        assert "闸口" in r["error"]

    def test_release_gate(self, api, wo):
        d = api.ok("POST", "/api/orders/%s/stage" % wo, {"target": "已下达"})
        assert d["status"] == "已下达"

    def test_dispatch(self, api, wo):
        d = api.ok("POST", "/api/orders/%s/dispatch" % wo, {"team": "TM-04", "operator": "qianwei"})
        assert d["team"] == "TM-04"

    def test_issue(self, api, wo):
        d = api.ok("POST", "/api/orders/%s/issue" % wo, {})
        assert d["issued"] >= 3

    def test_report_needs_fai(self, api, wo):
        det = api.ok("GET", "/api/orders/" + wo)
        seq = det["operations"][0]["seq"]
        r = api.err("POST", "/api/orders/%s/report" % wo, {"seq": seq, "goodQty": 50}, 400)
        assert "首件" in r["error"]

    def test_fai(self, api, wo):
        d = api.ok("POST", "/api/inspections", {"woNo": wo, "type": "首件",
                                                "items": [{"item": "关键尺寸", "value": 100.0,
                                                           "lsl": 99.7, "usl": 100.3}]})
        assert d["result"] == "合格"

    def test_report_flow(self, api, wo):
        det = api.ok("GET", "/api/orders/" + wo)
        first = det["operations"][0]
        d = api.ok("POST", "/api/orders/%s/report" % wo,
                   {"seq": first["seq"], "goodQty": 48, "ngQty": 2,
                    "actualMin": float(first["stdMin"]) * 1.2})
        assert d["woStatus"] == "已开工" and d["reportNo"].startswith("RP")
        assert d["eff"] < 1.0

    def test_report_over_tolerance(self, api, wo):
        det = api.ok("GET", "/api/orders/" + wo)
        first = det["operations"][0]
        api.err("POST", "/api/orders/%s/report" % wo,
                {"seq": first["seq"], "goodQty": 50}, 400)

    def test_full_report_then_finish(self, api, wo):
        det = api.ok("GET", "/api/orders/" + wo)
        for o in det["operations"][1:]:
            api.ok("POST", "/api/orders/%s/report" % wo, {"seq": o["seq"], "goodQty": 50})
        d = api.ok("GET", "/api/orders/" + wo)
        assert d["status"] == "已完工"

    def test_stockin_needs_inspection(self, api, wo):
        api.err("POST", "/api/orders/%s/stock-in" % wo, {"warehouse": "成品仓"}, 400)

    def test_fqc_and_stockin(self, api, wo):
        d = api.ok("POST", "/api/inspections", {"woNo": wo, "type": "完工检", "sampleQty": 50,
                                                "defectQty": 0})
        assert d["result"] == "合格"
        r = api.ok("POST", "/api/orders/%s/stock-in" % wo, {"warehouse": "成品仓"})
        assert r["batch"].startswith("B") and r["status"] == "已入库"

    def test_trace_after_stockin(self, api, wo):
        det = api.ok("GET", "/api/orders/" + wo)
        tr = api.ok("GET", "/api/trace?batch=" + det["batch"]["no"])
        assert tr["nodeCount"] >= 1

    def test_cannot_regress(self, api, wo):
        r = api.err("POST", "/api/orders/%s/stage" % wo, {"target": "已开工"}, 400)
        assert "推进" in r["error"]

    def test_cancel_terminal_locked(self, api, wo):
        api.err("POST", "/api/orders/%s/cancel" % wo, {"reason": "x"}, 400)

    def test_list_filters(self, api):
        d = api.ok("GET", "/api/orders?status=已入库")
        assert all(x["status"] == "已入库" for x in d["list"])
        d2 = api.ok("GET", "/api/orders?kw=接口测试")
        assert d2["total"] >= 1

    def test_ops_endpoints(self, api, wo):
        ops = api.ok("GET", "/api/ops?wo=" + wo)
        assert ops["total"] >= 4


class TestQualityApi:
    def test_inspections_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/inspections")
        assert d["total"] >= 2 and "typeDist" in d

    def test_inspection_detail(self, api):
        d = api.ok("GET", "/api/inspections?limit=1")
        det = api.ok("GET", "/api/inspections/" + d["list"][0]["no"])
        assert "items" in det

    def test_patrol(self, api):
        wo_list = api.ok("GET", "/api/orders?status=已开工")
        if not wo_list["list"]:
            pytest.skip("无在制工单")
        d = api.ok("POST", "/api/inspections", {"woNo": wo_list["list"][0]["no"], "type": "巡检",
                                                "sampleQty": 20, "defectQty": 1})
        assert d["result"] == "异常"

    def test_fqc_reject(self, api):
        wo_list = api.ok("GET", "/api/orders?status=已开工")
        if not wo_list["list"]:
            pytest.skip("无在制工单")
        d = api.ok("POST", "/api/inspections", {"woNo": wo_list["list"][0]["no"], "type": "完工检",
                                                "sampleQty": 10, "defectQty": 3})
        assert d["result"] == "退货"

    def test_defect_flow(self, api):
        wo_list = api.ok("GET", "/api/orders?status=已开工")
        if not wo_list["list"]:
            pytest.skip("无在制工单")
        d = api.ok("POST", "/api/defects", {"woNo": wo_list["list"][0]["no"],
                                            "defectCode": "DC-03", "qty": 2})
        assert d["id"] > 0
        api.ok("POST", "/api/defects/%d/dispose" % d["id"], {"disposition": "返修"})
        lst = api.ok("GET", "/api/defects?wo=" + wo_list["list"][0]["no"])
        assert any(x["id"] == d["id"] and x["disposition"] == "返修" for x in lst["list"])

    def test_defect_bad_code(self, api):
        api.err("POST", "/api/defects", {"woNo": "WO-X", "defectCode": "NOPE", "qty": 1}, 404)

    def test_defect_codes(self, api):
        d = api.ok("GET", "/api/defect-codes")
        assert len(d["list"]) >= 10

    def test_cpk(self, api):
        d = api.ok("GET", "/api/cpk")
        assert d["items"] >= 1 and d["samples"] >= 1

    def test_quality_summary(self, api):
        d = api.ok("GET", "/api/quality/summary")
        assert 0 <= d["yieldRate"] <= 1 and len(d["pareto"]) >= 1 and len(d["trend"]) == 14


class TestEquipment:
    def test_list(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/equipment")
        assert d["total"] >= 20
        e = d["list"][0]
        assert 0 <= e["oee"]["oee"] <= 1

    def test_status_filter(self, api):
        d = api.ok("GET", "/api/equipment?status=运行")
        assert all(x["status"] == "运行" for x in d["list"])

    def test_detail(self, api):
        d = api.ok("GET", "/api/equipment/EQ-0001")
        assert len(d["daily"]) >= 5 and "downtimeTop" in d

    def test_status_change(self, api):
        d = api.ok("POST", "/api/equipment/EQ-0004/status", {"status": "故障", "reason": "测试"})
        assert d["to"] == "故障"
        api.ok("POST", "/api/equipment/EQ-0004/status", {"status": "运行", "reason": "修复"})

    def test_status_needs_reason(self, api):
        api.err("POST", "/api/equipment/EQ-0004/status", {"status": "停机"}, 400)

    def test_status_bad(self, api):
        api.err("POST", "/api/equipment/EQ-0004/status", {"status": "跳舞"}, 400)

    def test_logs(self, api):
        d = api.ok("GET", "/api/equip/logs")
        assert d["total"] >= 1 and "top" in d

    def test_check(self, api):
        d = api.ok("POST", "/api/equip/checks", {"equipment": "EQ-0001",
                                                 "items": [{"item": "油位", "result": "正常"}]})
        assert d["result"] == "正常"

    def test_check_abnormal_sets_fault(self, api):
        d = api.ok("POST", "/api/equip/checks", {"equipment": "EQ-0002",
                                                 "items": [{"item": "气压", "result": "异常"}]})
        assert d["result"] == "异常"
        eq = api.ok("GET", "/api/equipment/EQ-0002")
        assert eq["status"] == "故障"
        api.ok("POST", "/api/equipment/EQ-0002/status", {"status": "运行", "reason": "修复"})

    def test_maint_plan_and_order(self, api):
        plans = api.ok("GET", "/api/maint/plans")
        assert plans["total"] >= 20
        mo = api.ok("POST", "/api/maint/orders", {"equipment": "EQ-0003", "type": "计划保养",
                                                  "reason": "接口测试"})
        assert mo["no"].startswith("MT")
        f = api.ok("POST", "/api/maint/orders/%s/finish" % mo["no"],
                   {"downtimeMin": 30, "cost": 500})
        assert f["status"] == "已完成"
        lst = api.ok("GET", "/api/maint/orders")
        assert lst["total"] >= 1


class TestStockTrace:
    def test_stock(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/stock")
        assert d["total"] >= 10 and len(d["warehouses"]) >= 3

    def test_batches(self, api):
        d = api.ok("GET", "/api/batches")
        assert d["total"] >= 10
        det = api.ok("GET", "/api/batches/" + d["list"][0]["no"])
        assert "reports" in det

    def test_trace_missing(self, api):
        api.err("GET", "/api/trace", code=400)


class TestBoardAndon:
    def test_board(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/board")
        assert len(d["lines"]) >= 6

    def test_andon_flow(self, api):
        d = api.ok("POST", "/api/andon", {"line": "LN-301", "type": "质量", "level": "一般",
                                          "remark": "接口测试"})
        assert d["no"].startswith("AD")
        lst = api.ok("GET", "/api/andon")
        target = [x for x in lst["list"] if x["no"] == d["no"]][0]
        c = api.ok("POST", "/api/andon/%d/close" % target["id"], {"remark": "处理完成"})
        assert c["status"] == "已关闭" and c["minutes"] >= 0


class TestReportsSettings:
    def test_reports(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/reports?days=14")
        for k in ("production", "oee", "quality", "lines", "equipment", "consumption"):
            assert k in d
        assert 0 <= d["oee"]["plant"]["oee"] <= 1
        assert len(d["production"]["trend"]) == 14

    def test_settings(self, api):
        d = api.ok("GET", "/api/settings")
        assert len(d["rules"]) == 8 and len(d["roles"]) == 8

    def test_rule_update_admin(self, api):
        d = api.ok("PUT", "/api/rules/patrol_interval_min", {"value": 100})
        assert float(d["value"]) == 100
        api.ok("PUT", "/api/rules/patrol_interval_min", {"value": 120})

    def test_rule_update_non_admin(self, api):
        api.login("liyun")
        api.err("PUT", "/api/rules/oee_target", {"value": 0.9}, 403)

    def test_logs(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/logs?limit=50")
        assert d["total"] >= 5

    def test_users(self, api):
        d = api.ok("GET", "/api/users")
        assert len(d["list"]) >= 8


class TestIntegration:
    def test_overview(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/integration/overview")
        assert d["changes"] >= 1 and "counts" in d

    def test_key_lifecycle(self, api):
        k = api.ok("POST", "/api/integration/keys", {"name": "接口测试 Key", "scope": "read"})
        assert k["key"].startswith("fck_")
        st, _ = api.call("GET", "/api/orders", token="", headers={"X-Fc-Key": k["key"]})
        assert st == 200
        st, _ = api.call("POST", "/api/orders", {"materialCode": "MT-3001", "qty": 1},
                         token="", headers={"X-Fc-Key": k["key"]})
        assert st == 403
        api.ok("DELETE", "/api/integration/keys/%d" % k["id"])
        st, _ = api.call("GET", "/api/orders", token="", headers={"X-Fc-Key": k["key"]})
        assert st == 401

    def test_webhook_flow(self, api):
        api.login("admin")
        w = api.ok("POST", "/api/integration/webhooks", {"name": "接口测试",
                                                         "url": "https://example.com/hook",
                                                         "events": "wo.reported"})
        assert w["secret"].startswith("whsec_")
        api.ok("PUT", "/api/integration/webhooks/%d" % w["id"], {"name": "接口测试2"})
        t = api.ok("POST", "/api/integration/webhooks/%d/test" % w["id"])
        assert t["queued"]
        dl = api.ok("GET", "/api/integration/deliveries")
        assert dl["total"] >= 1
        api.ok("DELETE", "/api/integration/webhooks/%d" % w["id"])

    def test_mapping_resolve(self, api):
        api.login("admin")
        m = api.ok("POST", "/api/integration/mappings", {"objType": "work_order",
                                                         "localNo": "WO-MAP-1",
                                                         "externalId": "ERP-901",
                                                         "system": "ERP"})
        assert m.get("created") or m.get("updated")
        r = api.ok("GET", "/api/integration/resolve?externalId=ERP-901")
        assert r["localNo"] == "WO-MAP-1"

    def test_sync(self, api):
        api.login("admin")
        d = api.ok("GET", "/api/sync/changes?since=0&limit=10")
        assert d["count"] >= 1
        if d["hasMore"]:
            d2 = api.ok("GET", "/api/sync/changes?since=%d&limit=10" % d["cursor"])
            assert d2["changes"][0]["id"] > d["changes"][-1]["id"]


class TestExportOpenapi:
    def test_export_orders(self, api):
        api.login("admin")
        st, headers, body = api.raw("GET", "/api/export/orders")
        assert st == 200 and body[:3] == b"\xef\xbb\xbf"

    def test_export_oee(self, api):
        st, _, body = api.raw("GET", "/api/export/oee")
        assert st == 200 and b"OEE" in body

    def test_openapi(self, api):
        st, r = api.call("GET", "/api/openapi.json")
        assert st == 200 and r["openapi"] == "3.0.3"
        assert len(r["paths"]) >= 60

    def test_unknown_route(self, api):
        api.err("GET", "/api/nope", code=404)
