# -*- coding: utf-8 -*-
"""飞驰MES系统 · 离线单文件 DEMO 生成器

思路：起一个临时后端（独立临时库），把前端需要的全部数据抓成快照内嵌进单个 HTML；
再用 tools/demo_mock.js 里的 fetch 拦截器在浏览器内存中实现
工单创建 / 报工 / 推进 / 发料 / 入库 / 检验 / 不良处置 / 设备状态 / 保养 / 点检 /
安灯 / 集成配置等写操作，口径与后端一致。DEMO 打开即用，无需服务与网络。
"""
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8881
BASE = "http://127.0.0.1:%d" % PORT

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path, method="GET", body=None, token=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + urllib.parse.quote(path, safe="/?=&%.:_-"),
                                 data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=60) as r:
            j = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit("接口异常 %s %s：%s" % (method, path, e.read().decode("utf-8", "ignore")))
    if "data" not in j:
        raise SystemExit("接口异常 %s：%s" % (path, j))
    return j["data"]


def wait_health(timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            call("/api/health")
            return True
        except Exception:
            time.sleep(0.4)
    return False


def q(v):
    return urllib.parse.quote(str(v))


def snapshot():
    db_path = os.path.join(ROOT, "reports", "demo_seed.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suf):
            os.remove(db_path + suf)
    env = dict(os.environ)
    env["FEICHI_PORT"] = str(PORT)
    env["FEICHI_DB"] = db_path
    env.pop("http_proxy", None)
    env.pop("HTTP_PROXY", None)
    proc = subprocess.Popen([sys.executable, os.path.join("backend", "server.py")],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        if not wait_health():
            raise SystemExit("后端启动失败（端口 %d 被占用？）" % PORT)
        tk = call("/api/auth/login", "POST",
                  {"username": "admin", "password": "admin123"})["token"]

        snap = {"boot": call("/api/bootstrap", token=tk),
                "me": call("/api/auth/me", token=tk),
                "board": call("/api/board", token=tk),
                "andon": call("/api/andon", token=tk)}

        snap["orders"] = call("/api/orders?limit=400", token=tk)
        snap["orderD"] = {}
        for x in snap["orders"]["list"]:
            snap["orderD"][x["no"]] = call("/api/orders/" + q(x["no"]), token=tk)

        snap["materials"] = call("/api/materials?limit=400", token=tk)
        snap["matD"] = {}
        for x in snap["materials"]["list"]:
            snap["matD"][x["code"]] = call("/api/materials/" + q(x["code"]), token=tk)

        snap["batches"] = call("/api/batches?limit=400", token=tk)
        snap["batchD"] = {}
        snap["trace"] = {}
        for x in snap["batches"]["list"]:
            snap["batchD"][x["no"]] = call("/api/batches/" + q(x["no"]), token=tk)
            snap["trace"][x["no"]] = call("/api/trace?batch=" + q(x["no"]), token=tk)

        snap["inspections"] = call("/api/inspections?limit=400", token=tk)
        snap["inspD"] = {}
        for x in snap["inspections"]["list"]:
            snap["inspD"][x["no"]] = call("/api/inspections/" + q(x["no"]), token=tk)
        snap["defects"] = call("/api/defects?limit=400", token=tk)
        snap["defectCodes"] = call("/api/defect-codes", token=tk)
        snap["cpk"] = call("/api/cpk", token=tk)
        snap["quality"] = call("/api/quality/summary", token=tk)

        snap["equipment"] = call("/api/equipment?limit=200", token=tk)
        snap["equipD"] = {}
        for x in snap["equipment"]["list"]:
            snap["equipD"][x["code"]] = call("/api/equipment/" + q(x["code"]), token=tk)
        snap["checks"] = call("/api/equip/checks", token=tk)
        snap["plans"] = call("/api/maint/plans", token=tk)
        snap["maintOrders"] = call("/api/maint/orders", token=tk)

        snap["stock"] = call("/api/stock?limit=400", token=tk)
        snap["reports"] = call("/api/reports?days=30", token=tk)
        snap["settings"] = call("/api/settings", token=tk)
        snap["logs"] = call("/api/logs?limit=200", token=tk)
        snap["integ"] = {
            "overview": call("/api/integration/overview", token=tk),
            "keys": call("/api/integration/keys", token=tk),
            "webhooks": call("/api/integration/webhooks", token=tk),
            "deliveries": call("/api/integration/deliveries", token=tk),
            "mappings": call("/api/integration/mappings", token=tk),
        }
        snap["sync"] = call("/api/sync/changes?since=0&limit=200", token=tk)

        print("快照完成：工单 %d / 物料 %d / 批次 %d / 检验 %d / 不良 %d / 设备 %d / "
              "库存 %d 行 / 保养工单 %d / 变更 %d"
              % (len(snap["orders"]["list"]), len(snap["materials"]["list"]),
                 len(snap["batches"]["list"]), len(snap["inspections"]["list"]),
                 len(snap["defects"]["list"]), len(snap["equipment"]["list"]),
                 len(snap["stock"]["list"]), len(snap["maintOrders"]["list"]),
                 len(snap["sync"]["changes"])))
        return snap
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def main():
    snap = snapshot()

    read = lambda p: io.open(os.path.join(ROOT, p), encoding="utf-8").read()
    css = read("frontend/style.css")
    shell = read("frontend/index.html")
    mock = read("tools/demo_mock.js")
    fe = [read("frontend/app.js"), read("frontend/plan.js"), read("frontend/mdm.js"),
          read("frontend/qual.js"), read("frontend/equip.js"), read("frontend/stock.js"),
          read("frontend/intg.js")]

    body = shell.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    body = body.split('<div class="mask"')[0]

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>飞驰MES系统 · 离线演示版</title>",
        "<style>",
        css,
        "html,body{height:auto}",
        ".app{height:auto;min-height:100vh}",
        ".demo-badge{position:fixed;right:16px;bottom:38px;z-index:99;background:#2f7d5d;"
        "color:#eafff4;font-size:12px;padding:5px 12px;border-radius:14px;"
        "box-shadow:0 4px 14px rgba(0,0,0,.25);font-weight:600;letter-spacing:.3px}",
        "</style>",
        "</head>",
        "<body>",
        body,
        '<div class="demo-badge">离线演示版 · 数据确定性生成，写操作只在浏览器内存生效</div>',
        '<div class="mask" id="mask"><div class="dialog" id="dialog"></div></div>',
        "<script>window.__DEMO__ = true; var DB = " +
        json.dumps(snap, ensure_ascii=False) + ";</script>",
        "<script>\n" + mock + "\n</script>",
    ]
    for js in fe:
        parts.append("<script>\n" + js + "\n</script>")
    parts += ["</body>", "</html>"]

    out_dir = os.path.join(ROOT, "demo")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "feichi-mes-demo.html")
    io.open(out, "w", encoding="utf-8").write("\n".join(parts))
    print("已生成：%s（%.1f KB）" % (out, os.path.getsize(out) / 1024.0))


if __name__ == "__main__":
    main()
