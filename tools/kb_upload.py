# -*- coding: utf-8 -*-
"""飞驰MES系统 · 文档批量上传知识库（分类 33 企业管理系统）

用法：
    python tools/kb_upload.py            # 仅上传（会与旧文档并存）
    python tools/kb_upload.py --replace  # 先删同名旧文档再上传（改版推荐）

docx/zip 必须走 curl -F（手写 multipart 会 parse 失败），md 亦统一走 curl。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feichi-mes"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feichi-mes-design.md", "飞驰MES系统建设方案",
     "「飞驰MES系统」完整建设方案 V1.0：建设背景与目标、四车间七产线现场蓝图、零依赖总体架构"
     "（标准库 http.server + sqlite3）、排产到入库主线、工单六态状态机与五道闸口（下达/开工/完工/入库/关闭）、"
     "核心算法与口径（末工序产量法、OEE 三率、MTBF/MTTR、工时达成率、产能负荷、节拍、产线平衡、"
     "齐套率、ABC、Cpk、缺陷帕累托、PPM）、26 表数据模型、8 类角色权限矩阵、8 条业务规则、"
     "三通道集成（API Key / Webhook HMAC 签名 / 增量同步）、80 条 REST 路由总览、14 页前端设计、"
     "非功能设计、六阶段实施计划与验收标准、风险应对。",
     "飞驰MES,企业管理系统,MES,制造执行,生产工单,OEE,批次追溯,建设方案"),
    ("docs/feichi_design_v1.docx", "飞驰MES系统建设方案（docx 版）",
     "《飞驰MES系统建设方案》排版版本（Word V1.0，27 页），含封面、目录与全部 16 章内容。",
     "飞驰MES,企业管理系统,建设方案,docx"),
    ("docs/api.md", "飞驰MES系统 REST 接口契约",
     "80 条路由的完整契约：统一响应包与状态码、多通道鉴权（会话令牌 7 种携带方式 / API Key fck_）、"
     "Idempotency-Key 幂等、限流 240 次每分钟、组织与主数据、工单（新建/详情/推进/取消/派工/齐套/发料/"
     "报工/入库）、工序、看板与安灯、质量（首件/巡检/完工检/不良/CPK）、设备与保养、批次追溯、库存、"
     "报表与 CSV 导出、设置与日志、集成中心（Key/Webhook/投递/映射/反查/增量同步）、"
     "Webhook HMAC-SHA256 签名协议（11 种事件）、错误码速查与对接实施建议。",
     "飞驰MES,API,接口契约,REST,Webhook,增量同步,对接"),
    ("docs/feichi_api_v1.docx", "飞驰MES系统 REST 接口契约（docx 版）",
     "《飞驰MES系统 REST 接口契约》排版版本（Word V1.0，26 页），面向对接方提供。",
     "飞驰MES,API,docx,对接"),
    ("docs/test-report.md", "飞驰MES系统测试报告",
     "三层自动化测试 150 项全部通过（业务内核单元 66 / REST 接口 78 / 端到端 UI 6），"
     "另有业务主线冒烟 153 检查点与离线 DEMO 冒烟 18 检查点；质量门禁 PASS。"
     "含分层策略与测试环境、覆盖矩阵、关键验证点（状态机与五道闸口、末工序产量口径、首件必检、"
     "完工检入库拦截、权限隔离、Key 鉴权、Webhook 验签、增量游标）、18 项缺陷台账（现象/根因/修复）、"
     "非功能验证（并发、限流、幂等、备份恢复）、验收对照与复现命令。",
     "飞驰MES,测试报告,质量门禁,自动化测试,Playwright"),
    ("docs/feichi_test_v1.docx", "飞驰MES系统测试报告（docx 版）",
     "《飞驰MES系统测试报告》排版版本（Word V1.0，14 页），含封面、目录与完整测试结论（150 项 + 171 检查点）。",
     "飞驰MES,测试报告,docx"),
    ("docs/user-guide.md", "飞驰MES系统项目说明与操作手册",
     "面向岗位的操作手册：启动与环境变量、八账号登录、界面骨架、14 个页面逐页操作说明、"
     "六类角色场景演练（计划员一个上午 / 操作工报工 / 质检员三检 / 设备工程师保养 / 仓管收发 / 厂长日报）、"
     "离线 DEMO 使用、10 条常见问题（闸口缺项、首件拦截、入库置灰、产量对账、OEE 排查、追溯查不到、"
     "Webhook 失败）、运维指南（守护进程、备份恢复、重置演示数据、健康检查、故障排查）。",
     "飞驰MES,操作手册,用户指南,MES,制造执行"),
    ("docs/feichi_manual_v1.docx", "飞驰MES系统项目说明与操作手册（docx 版）",
     "《飞驰MES系统项目说明与操作手册》排版版本（Word V1.0，19 页）。",
     "飞驰MES,操作手册,docx"),
    ("demo/feichi-mes-demo.zip", "飞驰MES系统离线演示（DEMO）",
     "单文件离线演示：解压后双击 HTML 即可用浏览器打开，无需服务与网络。内置确定性演示数据"
     "（4 车间 / 7 产线 / 25 设备 / 26 物料 / 37 工单 / 55 批次 / 64 检验），"
     "新建工单、报工、状态推进、发料、完工入库、检验登记、不良处置、设备状态、保养完成、安灯、"
     "API Key 生成吊销都在浏览器内存里按与后端一致的口径真实计算。",
     "飞驰MES,DEMO,离线演示,MES,制造执行"),
]


def req(path, method="GET", body=None, token=None, ctype="application/json"):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", ctype)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    mime = "application/zip" if full.endswith(".zip") else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if full.endswith(".docx") else "text/markdown")
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    """拉取分类下的文档（分页参数 pageNum/pageSize，返回 records 而非 list）。"""
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def build_demo_zip():
    src = os.path.join(ROOT, "demo", "feichi-mes-demo.html")
    out = os.path.join(ROOT, "demo", "feichi-mes-demo.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "飞驰MES系统Demo.html")
        z.writestr("使用说明.txt",
                   "飞驰MES系统 · 离线演示\r\n"
                   "1. 解压后双击「飞驰MES系统Demo.html」，用浏览器打开即可，无需安装、无需联网。\r\n"
                   "2. 内置确定性演示数据：4 车间 / 7 产线 / 25 工位 / 25 设备 / 26 物料 / 37 工单 / 55 批次 / 64 检验。\r\n"
                   "3. 新建工单、报工、状态推进、发料、完工入库、检验登记、不良处置、设备状态、保养完成、安灯、\r\n"
                   "   API Key 生成与吊销，都在浏览器内存里按与后端一致的口径真实计算。\r\n"
                   "4. 账号：离线版固定以 admin（系统管理员）进入，便于一个人体验完整流程。\r\n"
                   "5. 完整版本（多账号 + 真实权限 + 落地数据）请部署 backend/server.py 后访问 http://127.0.0.1:8021/。\r\n")
    print("DEMO zip 重建：%.1f KB" % (os.path.getsize(out) / 1024.0))


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    st, j = req("/api/users/whoami", token=TOKEN)
    print("whoami:", j.get("code"))

    build_demo_zip()

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-32s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    st, j = req("/api/document-categories", token=TOKEN)
    for c in (j.get("data") or []):
        if isinstance(c, dict) and c.get("id") == CAT:
            print("cat%d docCount:" % CAT, c.get("docCount"))


if __name__ == "__main__":
    main()
