# -*- coding: utf-8 -*-
"""飞驰 MES · 接口冒烟（开发期全链路自检）

跑通：主数据 → 工单创建 → 齐套 → 发料 → 首件 → 报工 → 完工 → 完工检 → 入库 →
批次追溯 → 设备 OEE / 保养 → 报表 → 设置 → 集成三通道 → 导出。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("MES_BASE", "http://127.0.0.1:8021")
FAIL = []
COUNT = [0]


def call(method, path, body=None, token=None, headers=None, raw=False):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = r.read()
            if raw:
                return r.status, payload
            return r.status, json.loads(payload)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAIL.append("%s %s" % (name, detail))


def ok(method, path, body=None, token=None, headers=None):
    st, r = call(method, path, body, token, headers)
    if st != 200 or not (isinstance(r, dict) and r.get("ok")):
        FAIL.append("%s %s -> %s %s" % (method, path, st, str(r)[:180]))
        print("  FAIL %s %s -> %s %s" % (method, path, st, str(r)[:180]))
        return None
    COUNT[0] += 1
    return r.get("data")


def main():
    print("== 认证 ==")
    st, r = call("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    check("登录", st == 200 and r.get("ok"), str(r)[:120])
    tok = (r.get("data") or {}).get("token")
    st, r = call("POST", "/api/auth/login", {"username": "admin", "password": "bad"})
    check("错误密码 401", st == 401)
    st, _ = call("GET", "/api/auth/me")
    check("未登录 401", st == 401)
    me = ok("GET", "/api/auth/me", token=tok)
    check("当前用户", me and me["username"] == "admin")

    boot = ok("GET", "/api/bootstrap", token=tok)
    check("启动数据", boot and "kpi" in boot and len(boot["trend"]) == 14,
          str(boot)[:100] if boot else "None")
    if boot:
        print("     KPI: 在制 %s / 今日 %s / 月产 %s / OEE %s / 良率 %s" % (
            boot["kpi"]["wip"], boot["kpi"]["todayOutput"], boot["kpi"]["monthOutput"],
            boot["kpi"]["oee"], boot["kpi"]["yieldRate"]))
        check("产线负荷", len(boot["lines"]) >= 5)

    print("== 主数据 ==")
    ws = ok("GET", "/api/workshops", token=tok)
    check("车间", ws and len(ws["list"]) == 4)
    lines = ok("GET", "/api/lines", token=tok)
    check("产线", lines and len(lines["list"]) >= 6)
    sts = ok("GET", "/api/stations", token=tok)
    check("工位", sts and len(sts["list"]) >= 20)
    teams = ok("GET", "/api/teams", token=tok)
    check("班组", teams and len(teams["list"]) >= 5)
    mats = ok("GET", "/api/materials", token=tok)
    check("物料", mats and len(mats["list"]) >= 24)
    md = ok("GET", "/api/materials/MT-3001", token=tok)
    check("物料详情含 BOM/工艺", md and md["bom"] and md["routing"]["steps"], str(md)[:120] if md else "")
    boms = ok("GET", "/api/boms", token=tok)
    check("BOM 列表", boms and boms["total"] >= 10)
    bd = ok("GET", "/api/boms/" + boms["list"][0]["code"], token=tok)
    check("BOM 明细", bd and len(bd["items"]) >= 3)
    rts = ok("GET", "/api/routings", token=tok)
    check("工艺列表", rts and rts["total"] >= 10)
    rd = ok("GET", "/api/routings/" + rts["list"][0]["code"], token=tok)
    check("工艺明细含平衡率", rd and rd["balance"] > 0)
    uniq = "MT-9%03d" % (int(time.time()) % 1000)
    nm = ok("POST", "/api/materials", {"code": uniq, "name": "冒烟测试物料", "unit": "件",
                                       "type": "原材料", "safetyStock": 50, "stdCost": 9.9}, token=tok)
    check("新建物料", nm and nm["created"])
    st, r = call("POST", "/api/materials", {"code": uniq, "name": "重复"}, token=tok)
    check("物料编码重复 409", st == 409)

    print("== 工单 ==")
    od = ok("POST", "/api/orders", {"materialCode": "MT-3001", "qty": 60, "line": "LN-301",
                                    "planStart": "2026-10-21", "customer": "冒烟客户",
                                    "priority": "紧急"}, token=tok)
    check("新建工单", od and od["no"].startswith("WO") and od["opCount"] >= 4, str(od)[:120])
    no = od["no"]
    det = ok("GET", "/api/orders/" + no, token=tok)
    check("工单详情工序", det and len(det["operations"]) >= 4)
    kit = ok("GET", "/api/orders/%s/kit" % no, token=tok)
    check("齐套检查", kit and "rate" in kit)
    if kit:
        print("     齐套率 %s（缺口 %s 项）" % (kit["rate"], len(kit["shortages"])))
    st, r = call("POST", "/api/orders/%s/stage" % no, {"target": "已开工"}, token=tok)
    check("未下达不能开工", st == 400)
    rst = ok("POST", "/api/orders/%s/stage" % no, {"target": "已下达"}, token=tok)
    check("下达（齐套闸口）", rst and rst["status"] == "已下达", str(rst)[:160])
    iss = ok("POST", "/api/orders/%s/issue" % no, {}, token=tok)
    check("发料", iss and iss["issued"] >= 3, str(iss)[:120])
    st, r = call("POST", "/api/orders/%s/report" % no,
                 {"seq": det["operations"][0]["seq"], "goodQty": 60}, token=tok)
    check("无首件不能报工", st == 400, str(r)[:120])
    fai = ok("POST", "/api/inspections", {"woNo": no, "type": "首件",
                                          "items": [{"item": "长度", "value": 100.0,
                                                     "lsl": 99.7, "usl": 100.3}]}, token=tok)
    check("首件检验", fai and fai["result"] == "合格")
    rep = ok("POST", "/api/orders/%s/report" % no,
             {"seq": det["operations"][0]["seq"], "goodQty": 58, "ngQty": 2,
              "actualMin": det["operations"][0]["stdMin"] * 1.1}, token=tok)
    check("报工", rep and rep["woStatus"] == "已开工" and rep["reportNo"].startswith("RP"), str(rep)[:160])
    if rep:
        print("     效率 %s / 标准 %s 分钟 / 实际 %s 分钟" % (rep["eff"], rep["stdMin"], rep["actualMin"]))
    for o in det["operations"][1:]:
        r2 = ok("POST", "/api/orders/%s/report" % no, {"seq": o["seq"], "goodQty": 60}, token=tok)
        if not r2:
            break
    det2 = ok("GET", "/api/orders/" + no, token=tok)
    check("全部报工后自动完工", det2 and det2["status"] == "已完工", det2["status"] if det2 else "")
    fqc = ok("POST", "/api/inspections", {"woNo": no, "type": "完工检", "sampleQty": 50,
                                          "defectQty": 0}, token=tok)
    check("完工检合格", fqc and fqc["result"] == "合格")
    st, r = call("POST", "/api/orders/%s/stock-in" % no, {"warehouse": "成品仓"}, token=tok)
    check("入库", st == 200 and r["data"]["batch"].startswith("B"), str(r)[:160])
    batch = (r.get("data") or {}).get("batch")
    det3 = ok("GET", "/api/orders/" + no, token=tok)
    check("工单已入库", det3 and det3["status"] == "已入库")
    batch = batch or ""
    tr = ok("GET", "/api/trace?batch=" + batch, token=tok)
    check("批次追溯树", tr and tr["nodeCount"] >= 1, str(tr)[:120])
    bl = ok("GET", "/api/batches?kw=" + batch, token=tok)
    check("批次列表", bl and bl["total"] >= 1)
    bdet = ok("GET", "/api/batches/" + (batch or "B0"), token=tok)
    check("批次详情", bdet and bdet["materialCode"] == "MT-3001")

    print("== 工序与看板 ==")
    ops = ok("GET", "/api/ops?wo=" + no, token=tok)
    check("工序列表", ops and ops["total"] >= 4)
    board = ok("GET", "/api/board", token=tok)
    check("生产看板", board and len(board["lines"]) >= 6)
    ad = ok("POST", "/api/andon", {"line": "LN-301", "type": "物料", "level": "一般",
                                   "remark": "冒烟呼叫"}, token=tok)
    check("发起安灯", ad and ad["no"].startswith("AD"))
    ads = ok("GET", "/api/andon", token=tok)
    check("安灯列表", ads and ads["total"] >= 1)
    if ad and ads and ads["list"]:
        cl = ok("POST", "/api/andon/%d/close" % ads["list"][0]["id"], {"remark": "已处理"}, token=tok)
        check("关闭安灯", cl and cl["status"] == "已关闭")
    rp = ok("GET", "/api/prod-reports?limit=10", token=tok)
    check("报工记录", rp and rp["total"] >= 1)

    print("== 质量 ==")
    ins = ok("GET", "/api/inspections", token=tok)
    check("检验列表", ins and ins["total"] >= 1)
    ide = ok("GET", "/api/inspections/" + ins["list"][0]["no"], token=tok)
    check("检验详情", ide and "items" in ide)
    dfs = ok("GET", "/api/defects", token=tok)
    check("不良列表", dfs and "list" in dfs)
    dft = ok("POST", "/api/defects", {"woNo": no, "defectCode": "DC-02", "qty": 1,
                                      "process": "装配"}, token=tok)
    check("登记不良", dft and dft["id"])
    if dft:
        dp = ok("POST", "/api/defects/%d/dispose" % dft["id"], {"disposition": "返修"}, token=tok)
        check("不良处置", dp and dp["disposition"] == "返修")
    codes = ok("GET", "/api/defect-codes", token=tok)
    check("不良代码", codes and len(codes["list"]) >= 10)
    cpk = ok("GET", "/api/cpk", token=tok)
    check("过程能力", cpk and cpk["items"] >= 1, str(cpk)[:140])
    qs = ok("GET", "/api/quality/summary", token=tok)
    check("质量总览", qs and "pareto" in qs and len(qs["trend"]) == 14)

    print("== 设备 ==")
    eq = ok("GET", "/api/equipment", token=tok)
    check("设备列表", eq and eq["total"] >= 20)
    if eq:
        e0 = eq["list"][0]
        print("     %s OEE %s（A %s / P %s / Q %s）" % (e0["name"], e0["oee"]["oee"],
                                                      e0["oee"]["availability"], e0["oee"]["performance"],
                                                      e0["oee"]["quality"]))
        check("设备 OEE 口径", 0 <= e0["oee"]["oee"] <= 1)
    ed = ok("GET", "/api/equipment/EQ-0001", token=tok)
    check("设备详情", ed and len(ed["daily"]) >= 5)
    stt = ok("POST", "/api/equipment/EQ-0004/status", {"status": "故障", "reason": "主轴异响"}, token=tok)
    check("设备状态变更", stt and stt["to"] == "故障")
    st, r = call("POST", "/api/equipment/EQ-0004/status", {"status": "停机"}, token=tok)
    check("停机无原因 400", st == 400)
    ok("POST", "/api/equipment/EQ-0004/status", {"status": "运行", "reason": "修复"}, token=tok)
    logs = ok("GET", "/api/equip/logs", token=tok)
    check("设备日志", logs and logs["total"] >= 1)
    ck = ok("POST", "/api/equip/checks", {"equipment": "EQ-0001", "type": "日常点检",
                                          "items": [{"item": "油位", "result": "正常"},
                                                    {"item": "气压", "result": "正常"}]}, token=tok)
    check("提交点检", ck and ck["result"] == "正常")
    cks = ok("GET", "/api/equip/checks", token=tok)
    check("点检记录", cks and cks["total"] >= 1)
    mp = ok("GET", "/api/maint/plans", token=tok)
    check("保养计划", mp and mp["total"] >= 20)
    mo = ok("POST", "/api/maint/orders", {"equipment": "EQ-0001", "type": "计划保养",
                                          "reason": "冒烟保养"}, token=tok)
    check("新建保养工单", mo and mo["no"].startswith("MT"))
    mf = ok("POST", "/api/maint/orders/%s/finish" % mo["no"], {"downtimeMin": 45, "cost": 800}, token=tok)
    check("完成保养", mf and mf["status"] == "已完成")
    mo2 = ok("GET", "/api/maint/orders", token=tok)
    check("保养工单列表", mo2 and mo2["total"] >= 1)

    print("== 库存与报表 ==")
    stk = ok("GET", "/api/stock", token=tok)
    check("库存台账", stk and stk["total"] >= 10)
    rep = ok("GET", "/api/reports?days=14", token=tok)
    check("报表聚合", rep and "production" in rep and "oee" in rep, str(rep)[:120] if rep else "")
    if rep:
        print("     产量 %s / 计划 %s / 达成 %s；OEE %s；MTBF %s；MTTR %s" % (
            rep["production"]["output"], rep["production"]["plan"],
            rep["production"]["completion"], rep["oee"]["plant"]["oee"],
            rep["equipment"]["mtbf"], rep["equipment"]["mttr"]))
        check("报表模块完整", all(k in rep for k in ("production", "oee", "quality", "lines",
                                                    "equipment", "statusDist", "consumption")))
        check("帕累托", len(rep["defectPareto"]) >= 3)
    st, body = call("GET", "/api/export/orders", token=tok, raw=True)
    check("导出工单 CSV", st == 200 and body[:3] == b"\xef\xbb\xbf")
    st, body = call("GET", "/api/export/oee", token=tok, raw=True)
    check("导出 OEE CSV", st == 200)

    print("== 设置与集成 ==")
    se = ok("GET", "/api/settings", token=tok)
    check("系统设置", se and len(se["rules"]) == 8 and len(se["roles"]) == 8)
    ru = ok("PUT", "/api/rules/patrol_interval_min", {"value": 90}, token=tok)
    check("规则调整", ru and float(ru["value"]) == 90)
    ok("PUT", "/api/rules/patrol_interval_min", {"value": 120}, token=tok)
    lg = ok("GET", "/api/logs", token=tok)
    check("操作日志", lg and lg["total"] >= 5)
    us = ok("GET", "/api/users", token=tok)
    check("用户列表", us and len(us["list"]) >= 8)
    ov = ok("GET", "/api/integration/overview", token=tok)
    check("集成总览", ov and "changes" in ov)
    key = ok("POST", "/api/integration/keys", {"name": "冒烟只读", "scope": "read"}, token=tok)
    check("新建 Key", key and key["key"].startswith("fck_"), str(key)[:100])
    st, r = call("GET", "/api/orders", token="", headers={"X-Fc-Key": key["key"]})
    check("Key 鉴权读", st == 200)
    st, r = call("POST", "/api/orders", {"materialCode": "MT-3001", "qty": 1},
                 token="", headers={"X-Fc-Key": key["key"]})
    check("只读 Key 不能写", st == 403, str(r)[:120])
    ok("DELETE", "/api/integration/keys/%d" % key["id"], token=tok)
    wh = ok("POST", "/api/integration/webhooks", {"name": "冒烟回调",
                                                  "url": "https://example.com/hook",
                                                  "events": ["wo.reported"]}, token=tok)
    check("新建 Webhook", wh and wh["secret"].startswith("whsec_"))
    wt = ok("POST", "/api/integration/webhooks/%d/test" % wh["id"], token=tok)
    check("测试事件入队", wt and wt["queued"])
    dl = ok("GET", "/api/integration/deliveries", token=tok)
    check("投递记录", dl and dl["total"] >= 1)
    if dl and dl["list"]:
        ok("POST", "/api/integration/deliveries/%d/retry" % dl["list"][0]["id"], token=tok)
    mp2 = ok("POST", "/api/integration/mappings", {"objType": "work_order", "localNo": no,
                                                   "externalId": "ERP-WO-9001", "system": "ERP"}, token=tok)
    check("绑定外部 ID", mp2 and (mp2.get("created") or mp2.get("updated")))
    rs = ok("GET", "/api/integration/resolve?externalId=ERP-WO-9001", token=tok)
    check("外部 ID 反查", rs and rs["localNo"] == no)
    ch = ok("GET", "/api/sync/changes?since=0&limit=50", token=tok)
    check("增量变更流", ch and ch["count"] >= 1, str(ch)[:100])
    spec = call("GET", "/api/openapi.json")[1]
    check("OpenAPI", spec.get("openapi") == "3.0.3" and len(spec["paths"]) >= 60)

    print("\n检查点 %d，失败 %d" % (COUNT[0], len(FAIL)))
    if FAIL:
        print("失败明细：")
        for x in FAIL:
            print("  -", x)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
